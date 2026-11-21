#!/usr/bin/env python3
"""make_figure.py — spec.json -> layered SVG + PNG + PDF + checks + summary.

Usage:
  python3 make_figure.py --spec spec.json --outdir out/ --basename fig [--dpi 300]
Scales tried: compact/regular/roomy; the first scale with zero violations wins,
else the one with fewest violations is kept (reported honestly in checks.json).
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import SCALES
from build import build_mechanism
from chart import build_chart
from viz_check import check, attach_check
from viz_svg import to_svg
from viz_mpl import to_mpl

def lint_spec(spec):
    """Honesty/consistency warnings collected into checks.json['spec_warnings']."""
    from viz_style import EDGE_ORDER, NODE_STYLES
    w = []
    ids = {n.get("id") for n in spec.get("nodes", [])}
    comp_ids = {c.get("id") for c in spec.get("compartments", [])}
    for n in spec.get("nodes", []):
        if n.get("kind") not in NODE_STYLES:
            w.append(f"node {n.get('id')}: unknown kind {n.get('kind')!r} (rendered as other)")
        if n.get("compartment") and comp_ids and n["compartment"] not in comp_ids:
            w.append(f"node {n.get('id')}: compartment {n['compartment']!r} not declared")
        if not str(n.get("source") or "").strip():
            w.append(f"node {n.get('id')}: missing source provenance")
    for i, e in enumerate(spec.get("edges", [])):
        if e.get("type") not in EDGE_ORDER:
            w.append(f"edge[{i}] {e.get('from')}->{e.get('to')}: unknown type {e.get('type')!r}")
        if e.get("from") not in ids or e.get("to") not in ids:
            w.append(f"edge[{i}]: endpoint not in nodes ({e.get('from')}->{e.get('to')})")
        if not str(e.get("source") or "").strip():
            w.append(f"edge[{i}] {e.get('from')}->{e.get('to')}: missing source provenance")
    return w

def render(spec, dpi=300, scales=None, outdir=None, basename="fig"):
    scales = scales or list(SCALES.keys())
    outdir = Path(outdir or ".")
    outdir.mkdir(parents=True, exist_ok=True)
    best = None
    for s in scales:
        if spec.get("mode") == "chart":
            prims, W, H, placed, used = build_chart(spec, s)
        else:
            prims, W, H, placed, used = build_mechanism(spec, s)
        viol = check(prims, W, H) + attach_check(placed, spec.get("edges", []))
        cand = {"scale": s, "prims": prims, "W": W, "H": H, "viol": viol,
                "n": len(viol)}
        if best is None or cand["n"] < best["n"]:
            best = cand
        if cand["n"] == 0:
            break
    p = best
    svg = to_svg(p["prims"], p["W"], p["H"], spec.get("title", "figure"))
    f_svg = outdir / f"{basename}.svg"
    f_png = outdir / f"{basename}.png"
    f_pdf = outdir / f"{basename}.pdf"
    f_svg.write_text(svg, encoding="utf-8")
    export = {"png": str(f_png), "pdf": str(f_pdf), "mpl": True}
    try:
        to_mpl(p["prims"], p["W"], p["H"], dpi, png=str(f_png), pdf=str(f_pdf))
    except Exception as ex:  # mpl missing -> raster fallback chain
        export = raster_fallback(svg, p["W"], p["H"], str(f_png), str(f_pdf), str(ex))
    checks = {"violations": p["viol"], "n_violations": p["n"], "scale": p["scale"],
              "canvas": [p["W"], p["H"]], "nodes": len(placed),
              "edge_types_used": used,
              "spec_warnings": lint_spec(spec),
              "legend": bool([q for q in p["prims"] if q.get("role", "").startswith("legend")])}
    (outdir / f"{basename}.checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"editable_source": {"path": str(f_svg), "format": "svg", "layers_named": True,
                                   "canvas_wh": [p["W"], p["H"]]},
               "export_artifact": export, "checks": checks, "layout_scale": p["scale"]}
    (outdir / f"{basename}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        cm = content_map_draft(spec, p["prims"])
        (outdir / f"{basename}.content-map.json").write_text(
            json.dumps(cm, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as ex:
        pass
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary

def content_map_draft(spec, prims):
    """Element->source provenance draft; agent enriches relations before shipping."""
    cm = []
    for n in spec.get("nodes", []):
        cm.append({"element": str(n.get("label", n["id"])), "kind": "node",
                   "relation": f"{n.get('kind','protein')} in {n.get('compartment','unspecified')}"
                               + (f"; mods={','.join(n['mods'])}" if n.get("mods") else ""),
                   "source": n.get("source", "unspecified — fill before shipping")})
    for e in spec.get("edges", []):
        rel = str(e.get("type", "other"))
        if e.get("label"):
            rel += f" ({e['label']})"
        if e.get("dashed"):
            rel += " [dashed: indirect/uncertain]"
        cm.append({"element": f"{e.get('from')}->{e.get('to')}", "kind": "edge",
                   "relation": rel, "source": e.get("source", "unspecified — fill before shipping")})
    if spec.get("data_map"):
        cm.append({"element": "data_map/legend", "kind": "encoding",
                   "relation": str(spec["data_map"].get("caption", ""))
                               + ("; " + str(spec["data_map"]["size_caption"]) if spec["data_map"].get("size_caption") else ""),
                   "source": spec.get("data_source", "unspecified — fill before shipping")})
    if spec.get("mode") == "chart":
        for b in (spec.get("chart") or {}).get("bars", []):
            cm.append({"element": f"bar:{b.get('label','')}", "kind": "data",
                       "relation": f"value={b.get('value')} err={b.get('err', 0)} group={b.get('group', '')}",
                       "source": b.get("source", spec.get("chart", {}).get("source",
                                   "unspecified — fill before shipping"))})
    return cm

def raster_fallback(svg, W, H, png, pdf, mpl_err):
    note = {"mpl": False, "mpl_error": mpl_err, "fallback": None}
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=svg.encode(), write_to=png, output_width=W * 2)
        cairosvg.svg2pdf(bytestring=svg.encode(), write_to=pdf)
        note["fallback"] = "cairosvg"
        return {"png": png, "pdf": pdf, **note}
    except Exception:
        pass
    import shutil, subprocess
    for tool, args in (("rsvg-convert", ["-w", str(W * 2), "-o", png, "/dev/stdin"]),):
        if shutil.which(tool):
            subprocess.run([tool, "-w", str(W * 2), "-o", png], input=svg.encode(), check=True)
            note["fallback"] = tool
            return {"png": png, "pdf": None, **note}
    note["fallback"] = "none; SVG written; raster failed"
    return {"png": None, "pdf": None, **note}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--basename", default="fig")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--scales", default="compact,regular,roomy")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    s = render(spec, dpi=a.dpi, scales=a.scales.split(","), outdir=a.outdir, basename=a.basename)
    if a.strict and s["checks"]["n_violations"] > 0:
        sys.exit(2)

if __name__ == "__main__":
    main()
