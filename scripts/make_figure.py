#!/usr/bin/env python3
"""make_figure.py — spec.json -> layered SVG + 300 DPI PNG/PDF + 100 DPI preview + 5-layer audits.

Supports modes:
  - "mechanism" (default): compartment & transmembrane biological mechanism diagram
  - "chart": publication-grade bar, hbar, line/timecourse, scatter/volcano, heatmap
  - "composite": multi-panel figure (panels=[{id:"A", spec:{...}}, {id:"B", spec:{...}}])

Usage:
  python3 make_figure.py --spec spec.json --outdir out/ --basename fig [--dpi 300]
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import SCALES
from build import build_mechanism, build_composite
from chart import build_chart
from viz_check import check, attach_check
from check_figure import audit as svg_audit, pixel_audit
from bio_lint import bio_audit, verify_legend_consistency
from viz_svg import to_svg
from viz_mpl import to_mpl

_NODE_KIND_ALIAS = {
    "ligand": "protein", "cytokine": "protein", "chemokine": "protein", "hormone": "protein",
    "kinase": "protein", "enzyme": "protein", "tf": "protein", "transcription_factor": "protein",
    "antibody": "protein", "factor": "protein", "adaptor": "protein", "channel": "receptor",
    "transporter": "receptor", "rtk": "receptor", "gpcr": "receptor", "tm_receptor": "receptor",
    "mrna": "gene", "rna": "gene", "lncrna": "gene", "mirna": "gene", "transcript": "gene",
    "inhibitor": "drug", "small_molecule": "drug", "compound": "drug", "therapy": "drug",
    "pathway": "process", "outcome": "process", "function": "process", "event": "process",
    "response": "process", "cell_type": "cell", "immune_cell": "cell",
}
_EDGE_TYPE_ALIAS = {
    "activate": "activation", "activates": "activation", "promotes": "activation",
    "induces": "activation", "stimulates": "activation", "upregulates": "activation",
    "inhibit": "inhibition", "inhibits": "inhibition", "represses": "inhibition",
    "blocks": "inhibition", "suppresses": "inhibition", "downregulates": "inhibition",
    "bind": "binding", "binds": "binding", "interacts": "binding", "complexes": "binding",
    "associates": "binding", "dimerizes": "binding",
    "phosphorylate": "phosphorylation", "phosphorylates": "phosphorylation",
    "ubiquitinate": "ubiquitination", "ubiquitinates": "ubiquitination",
    "recruit": "recruitment", "recruits": "recruitment",
    "translocate": "translocation", "translocates": "translocation",
    "imports": "translocation", "exports": "translocation", "shuttles": "translocation",
    "transcribe": "transcription", "transcribes": "transcription", "expresses": "expression",
    "degrade": "degradation", "degrades": "degradation", "cleaves": "degradation", "cleavage": "degradation",
    "modifies": "modification", "acetylates": "modification", "methylates": "modification",
    "association": "undirected", "associated": "undirected", "unknown": "undirected",
    "unknown_direction": "undirected", "correlates": "undirected", "correlate": "undirected",
}
_COMP_KIND_ALIAS = {
    "extracellular": "exterior", "outside": "exterior", "lumen": "exterior", "tme": "exterior",
    "plasma_membrane": "membrane", "cell_membrane": "membrane", "bilayer": "membrane",
    "cytoplasm": "cytosol", "intracellular": "cytosol",
    "mitochondria": "organelle", "mitochondrion": "organelle", "er": "organelle",
    "golgi": "organelle", "lysosome": "organelle", "endosome": "organelle", "vesicle": "organelle",
    "nucleoplasm": "nucleus", "chromatin": "nucleus",
}

def _pick_prov(obj, fallback=None):
    for k in ("source", "citation", "provenance", "ref", "evidence_source"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return fallback

def normalize_spec(spec):
    """Non-destructive normalization of common LLM schema aliases (returns a normalized copy)."""
    from copy import deepcopy
    sp = deepcopy(spec)
    if sp.get("mode") == "composite":
        for pi, pdef in enumerate(sp.get("panels") or []):
            if isinstance(pdef, dict):
                pdef.setdefault("id", chr(65 + pi))
                if isinstance(pdef.get("spec"), dict):
                    pdef["spec"] = normalize_spec(pdef["spec"])
        return sp
    if sp.get("mode") == "chart" and isinstance(sp.get("chart"), dict):
        from chart import _normalize_chart_spec
        sp["chart"] = _normalize_chart_spec(sp["chart"])
        return sp
    for ci, c in enumerate(sp.get("compartments") or []):
        if not c.get("id"):
            c["id"] = str(c.get("label") or f"c{ci}").lower().replace(" ", "_")
        ck = str(c.get("kind") or "").strip().lower()
        if ck in _COMP_KIND_ALIAS:
            c["kind"] = _COMP_KIND_ALIAS[ck]
    top_src = _pick_prov(sp, sp.get("data_source"))
    node_ids = set()
    label_to_id = {}
    for ni, n in enumerate(sp.get("nodes") or []):
        if not n.get("id"):
            n["id"] = str(n.get("label") or f"n{ni}").split("\n")[0].strip().replace(" ", "_")
        node_ids.add(n["id"])
        lbl_k = str(n.get("label") or "").split("\n")[0].strip()
        if lbl_k:
            label_to_id.setdefault(lbl_k, n["id"])
            label_to_id.setdefault(lbl_k.lower(), n["id"])
        nk = str(n.get("kind") or "").strip().lower()
        if nk in _NODE_KIND_ALIAS:
            n["kind"] = _NODE_KIND_ALIAS[nk]
        if not str(n.get("source") or "").strip():
            pv = _pick_prov(n, top_src)
            if pv:
                n["source"] = pv
    for e in sp.get("edges") or []:
        # Handle D3/Cytoscape style {source: nodeA, target: nodeB} or src/dst/start/end aliases
        if "from" not in e:
            for fk in ("src", "start", "source_id", "from_id"):
                if e.get(fk) is not None:
                    e["from"] = e[fk]; break
        if "to" not in e:
            for tk in ("dst", "end", "target_id", "to_id", "target"):
                if e.get(tk) is not None:
                    e["to"] = e[tk]; break
        if "from" not in e and e.get("source") in node_ids:
            e["from"] = e["source"]
            e["source"] = _pick_prov({k: v for k, v in e.items() if k != "source"}, top_src or "")
        # Resolve label-referenced endpoints cleanly to node IDs
        for ek in ("from", "to"):
            ev = e.get(ek)
            if ev is not None and ev not in node_ids:
                s_ev = str(ev).strip()
                if s_ev in label_to_id:
                    e[ek] = label_to_id[s_ev]
                elif s_ev.lower() in label_to_id:
                    e[ek] = label_to_id[s_ev.lower()]
        et = str(e.get("type") or "").strip().lower()
        if et in _EDGE_TYPE_ALIAS:
            e["type"] = _EDGE_TYPE_ALIAS[et]
        if e.get("directed") is False and e.get("type") not in ("binding", "undirected"):
            e["type"] = "undirected"
        if not str(e.get("source") or "").strip():
            pv = _pick_prov(e, top_src)
            if pv:
                e["source"] = pv
    for g in sp.get("groups") or []:
        if not str(g.get("source") or "").strip() and top_src:
            g["source"] = top_src
    return sp

def lint_spec(spec):
    """Honesty/consistency warnings collected into checks.json['spec_warnings']."""
    from viz_style import EDGE_ORDER, NODE_STYLES
    w = []
    if spec.get("mode") == "composite":
        for pdef in spec.get("panels") or []:
            pid = pdef.get("id", "?")
            for msg in lint_spec(pdef.get("spec") or pdef):
                w.append(f"[{pid}] {msg}")
        return w
    if spec.get("mode") == "chart":
        ch = spec.get("chart") or {}
        if ch.get("_table_error"):
            w.append(f"from_table: {ch['_table_error']}")
        has_data = any(bool(ch.get(k)) for k in ("bars", "series", "points", "items", "groups", "values"))
        if not has_data:
            w.append("empty_chart_data: chart has 0 plotted data items (check column names or data array)")
        return w
    if len(spec.get("nodes", [])) < 2:
        w.append(f"too_few_nodes: mechanism has only {len(spec.get('nodes', []))} node(s)")
    ids = {n.get("id") for n in spec.get("nodes", [])}
    comp_ids = {c.get("id") for c in spec.get("compartments", [])}
    for n in spec.get("nodes", []):
        if n.get("kind") and n.get("kind") not in NODE_STYLES:
            w.append(f"node {n.get('id')}: unknown kind {n.get('kind')!r} (rendered as other)")
        if n.get("compartment") and comp_ids and n["compartment"] not in comp_ids:
            w.append(f"node {n.get('id')}: compartment {n['compartment']!r} not declared")
        if not str(n.get("source") or "").strip():
            w.append(f"node {n.get('id')}: missing source provenance")
    for i, e in enumerate(spec.get("edges", [])):
        if e.get("type") and e.get("type") not in EDGE_ORDER:
            w.append(f"edge[{i}] {e.get('from')}->{e.get('to')}: unknown type {e.get('type')!r}")
        if e.get("from") not in ids or e.get("to") not in ids:
            w.append(f"edge[{i}]: endpoint not in nodes ({e.get('from')}->{e.get('to')})")
        if not str(e.get("source") or "").strip():
            w.append(f"edge[{i}] {e.get('from')}->{e.get('to')}: missing source provenance")
    return w

def _build_one(spec, scale):
    mode = spec.get("mode", "mechanism")
    if mode == "composite":
        flat_prims, chrome_prims, panel_groups, W, H, panel_meta = build_composite(spec, scale)
        viol = check(flat_prims, W, H)
        used = []
        n_nodes = 0
        for pm in panel_meta:
            if pm["spec"].get("mode", "mechanism") == "mechanism":
                viol += attach_check(pm["placed"], pm["spec"].get("edges", []), routed=pm["routed"])
            n_nodes += len(pm["placed"])
            for et in pm["used"]:
                if et not in used:
                    used.append(et)
        return {"scale": scale, "prims": flat_prims, "svg_prims": chrome_prims,
                "panel_groups": panel_groups, "panel_meta": panel_meta, "W": W, "H": H, "viol": viol, "n": len(viol),
                "n_nodes": n_nodes, "used": used, "placed": []}
    if mode == "chart":
        prims, W, H, placed, used = build_chart(spec, scale)
        viol = check(prims, W, H)
        return {"scale": scale, "prims": prims, "svg_prims": prims, "panel_groups": None,
                "W": W, "H": H, "viol": viol, "n": len(viol), "n_nodes": len(placed), "used": used,
                "placed": placed}
    prims, W, H, placed, used, routed = build_mechanism(spec, scale)
    viol = check(prims, W, H) + attach_check(placed, spec.get("edges", []), routed=routed)
    return {"scale": scale, "prims": prims, "svg_prims": prims, "panel_groups": None,
            "W": W, "H": H, "viol": viol, "n": len(viol), "n_nodes": len(placed), "used": used,
            "placed": placed}

def _with_layout_override(spec, extra_lopts):
    """Return deep copy of spec (or composite panels) with merged layout overrides."""
    from copy import deepcopy
    sp = deepcopy(spec)
    if sp.get("mode") == "composite":
        for pdef in sp.get("panels") or []:
            ps = pdef.get("spec") if isinstance(pdef, dict) and "spec" in pdef else pdef
            if isinstance(ps, dict) and ps.get("mode", "mechanism") == "mechanism":
                ps["layout"] = {**(ps.get("layout") or {}), **extra_lopts}
    elif sp.get("mode", "mechanism") == "mechanism":
        sp["layout"] = {**(sp.get("layout") or {}), **extra_lopts}
    return sp

def render(spec, dpi=300, scales=None, outdir=None, basename="fig",
           verbose=True, preview_dpi=100):
    spec = normalize_spec(spec)
    scales = scales or list(SCALES.keys())
    outdir = Path(outdir or ".")
    outdir.mkdir(parents=True, exist_ok=True)
    best = None
    # Pass 1: standard scales; Pass 2+: automatic self-healing layout fallbacks if any violation remains
    strategies = [{}]
    if spec.get("mode", "mechanism") in ("mechanism", "composite"):
        strategies.extend([
            {"preserve_order": True},
            {"auto_tier": False, "preserve_order": True},
            {"auto_tier": False, "preserve_order": True, "wide_canvas": True},
        ])
    for lopts in strategies:
        sp_try = spec if not lopts else _with_layout_override(spec, lopts)
        for s in scales:
            cand = _build_one(sp_try, s)
            if best is None or cand["n"] < best["n"]:
                best = cand
            if cand["n"] == 0:
                break
        if best and best["n"] == 0:
            break
    p = best
    svg = to_svg(p["svg_prims"], p["W"], p["H"], spec.get("title", "figure"),
                 panel_groups=p["panel_groups"])
    f_svg = outdir / f"{basename}.svg"
    f_png = outdir / f"{basename}.png"
    f_pdf = outdir / f"{basename}.pdf"
    f_prev = outdir / f"{basename}.preview.png"
    f_svg.write_text(svg, encoding="utf-8")

    export = {"png": str(f_png), "pdf": str(f_pdf), "preview_png": str(f_prev), "mpl": True, "png_dpi": int(dpi)}
    try:
        eff_dpi = to_mpl(p["prims"], p["W"], p["H"], dpi, png=str(f_png), pdf=str(f_pdf),
                         preview_png=str(f_prev) if preview_dpi else None, preview_dpi=preview_dpi or 100)
        if isinstance(eff_dpi, int) and eff_dpi > 0:
            export["png_dpi"] = eff_dpi
    except Exception as ex:  # mpl missing -> raster fallback chain
        export = raster_fallback(svg, p["W"], p["H"], str(f_png), str(f_pdf), str(ex), svg_path=str(f_svg))

    aud = svg_audit(svg)
    pix = pixel_audit(f_png) if f_png.exists() else {"ok": False, "error": "PNG not produced"}
    baud = bio_audit(spec)
    lcons = verify_legend_consistency(spec, p["prims"], p["used"], p.get("placed") or [],
                                      panel_meta=p.get("panel_meta"))
    pdf_tt = False
    if f_pdf.exists():
        try:
            pb = f_pdf.read_bytes()
            pdf_tt = (b"/TrueType" in pb or b"/Font" in pb)
        except Exception:
            pass
    checks = {"violations": p["viol"], "n_violations": p["n"], "scale": p["scale"],
              "canvas": [p["W"], p["H"]], "nodes": p["n_nodes"],
              "edge_types_used": p["used"],
              "spec_warnings": lint_spec(spec),
              "bio_audit": baud,
              "legend_consistency": lcons,
              "legend": bool([q for q in p["prims"] if q.get("role", "").startswith("legend")]),
              "pdf_font_embedded": pdf_tt,
              "pixel_audit": pix,
              "svg_audit": {"n_violations": aud["n_violations"],
                            "layers_named": aud["layers_named"],
                            "elements": aud["elements"],
                            "violations": aud["violations"][:10]}}
    (outdir / f"{basename}.checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"editable_source": {"path": str(f_svg), "format": "svg", "layers_named": True,
                                   "canvas_wh": [p["W"], p["H"]]},
               "export_artifact": export, "checks": checks, "layout_scale": p["scale"]}
    (outdir / f"{basename}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    cm = content_map_draft(spec, p["prims"])
    (outdir / f"{basename}.content-map.json").write_text(
        json.dumps(cm, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary

def content_map_draft(spec, prims=None, prefix=""):
    """Element->source provenance draft covering mechanism, all 9 chart types, and composites."""
    from bio_lint import resolve_canonical
    from viz_style import EDGE_STYLES
    cm = []
    if spec.get("mode") == "composite":
        for idx, pdef in enumerate(spec.get("panels") or []):
            pid = str(pdef.get("id") or chr(65 + idx))
            cm.extend(content_map_draft(pdef.get("spec") or pdef, prefix=f"{pid}:"))
        return cm
    for n in spec.get("nodes", []):
        nkind = str(n.get("kind", "protein"))
        ncomp = str(n.get("compartment", "unspecified"))
        lbl_s = str(n.get("label", n["id"]))
        canon = resolve_canonical(lbl_s) or (resolve_canonical(str(n["alias"])) if n.get("alias") else None)
        rel = f"{nkind} in {ncomp}"
        if n.get("alias"):
            rel += f" (alias: {n['alias']})"
        if n.get("mods"):
            rel += f"; mods={','.join(str(m) for m in n['mods'])}"
        if isinstance(n.get("value"), (int, float)):
            rel += f"; value={n['value']}"
        if isinstance(n.get("size_value"), (int, float)):
            rel += f"; size_value={n['size_value']}"
        entry = {
            "element": f"{prefix}{lbl_s}",
            "entity_id": str(n["id"]),
            "kind": "node",
            "symbol_style": ("italic_gene" if nkind == "gene" else f"roman_{nkind}"),
            "compartment": ncomp,
            "relation": rel,
            "source": n.get("source", "unspecified — fill before shipping"),
        }
        if canon:
            entry["canonical_symbol"] = canon
        if n.get("alias"):
            entry["alias"] = str(n["alias"])
        if n.get("mods"):
            entry["modifications"] = [str(m) for m in n["mods"]]
        if n.get("subunits"):
            entry["subunits"] = [str(u) for u in n["subunits"]]
        cm.append(entry)
    for g in spec.get("groups") or []:
        cm.append({"element": f"{prefix}group:{g.get('label', g.get('id', 'module'))}",
                   "kind": "complex_group",
                   "relation": f"encloses {', '.join(g.get('members') or [])}",
                   "source": g.get("source", spec.get("source", "unspecified — fill before shipping"))})
    for e in spec.get("edges", []):
        etype = str(e.get("type", "other"))
        evid = str(e.get("evidence") or ("indirect" if e.get("dashed") else "direct"))
        rel = etype
        if e.get("label"):
            rel += f" ({e['label']})"
        if e.get("evidence"):
            rel += f" [{e['evidence']}]"
        if e.get("dashed"):
            rel += " [dashed: indirect/uncertain]"
        if isinstance(e.get("weight") if e.get("weight") is not None else e.get("confidence"), (int, float)):
            wval = e.get("weight") if e.get("weight") is not None else e.get("confidence")
            rel += f"; weight={wval}"
        est = EDGE_STYLES.get(etype, EDGE_STYLES["other"])
        glyph = est.get("end", "arrow") + (f"({est['tag']})" if est.get("tag") else "")
        cm.append({"element": f"{prefix}{e.get('from')}->{e.get('to')}", "kind": "edge",
                   "from": str(e.get("from")), "to": str(e.get("to")),
                   "interaction_type": etype, "arrow_glyph": glyph, "evidence": evid,
                   "relation": rel, "source": e.get("source", "unspecified — fill before shipping")})
    if spec.get("width_map"):
        wm = spec["width_map"]
        cm.append({"element": f"{prefix}width_map/legend", "kind": "encoding",
                   "relation": str(wm.get("caption", "edge width encoding")),
                   "source": wm.get("source") or spec.get("data_source", "unspecified — fill before shipping")})
    if spec.get("size_map"):
        sm = spec["size_map"]
        cm.append({"element": f"{prefix}size_map/legend", "kind": "encoding",
                   "relation": str(sm.get("caption", f"node size encoding ({sm.get('min')}..{sm.get('max')})")),
                   "source": sm.get("source") or spec.get("data_source", "unspecified — fill before shipping")})
    if spec.get("data_map"):
        dm = spec["data_map"]
        cm.append({"element": f"{prefix}data_map/legend", "kind": "encoding",
                   "relation": str(dm.get("caption", ""))
                               + ("; " + str(dm["size_caption"]) if dm.get("size_caption") else ""),
                   "source": dm.get("source") or spec.get("data_source", "unspecified — fill before shipping")})
    if spec.get("mode") == "chart":
        ch = spec.get("chart") or {}
        ft = ch.get("from_table") if isinstance(ch.get("from_table"), dict) else {}
        ft_src = Path(str(ft["file"])).name if ft.get("file") else None
        dsrc = ch.get("source") or ft_src or ch.get("y_note") or "unspecified — fill before shipping"
        bars_all = ch.get("bars") or []
        if len(bars_all) > 40:
            cm.append({"element": f"{prefix}bars_dataset:{len(bars_all)}_bars", "kind": "data",
                       "relation": f"total={len(bars_all)} bars (showing first 40)", "source": dsrc})
        for b in bars_all[:40]:
            cm.append({"element": f"{prefix}bar:{b.get('label', '')}", "kind": "data",
                       "relation": f"value={b.get('value')} err={b.get('err', 0)} group={b.get('group', '')}",
                       "source": b.get("source", dsrc)})
        for s in ch.get("series") or []:
            vals_s = s.get("y") if s.get("y") is not None else s.get("values")
            vals_list = vals_s or []
            if len(vals_list) > 12:
                nums_s = [float(v) for v in vals_list if isinstance(v, (int, float))]
                rel_s = f"n={len(vals_list)} range=[{min(nums_s):.4g}..{max(nums_s):.4g}] head={vals_list[:6]}" if nums_s else f"n={len(vals_list)} head={vals_list[:6]}"
            else:
                rel_s = f"n={len(vals_list)} values={vals_list}"
            cm.append({"element": f"{prefix}series:{s.get('name', '')}", "kind": "data",
                       "relation": rel_s, "source": s.get("source", dsrc)})
        pts_all = ch.get("points") or []
        if len(pts_all) > 25:
            xt = abs(float(ch["x_thresh"])) if ch.get("x_thresh") is not None else 0.0
            yt = float(ch["y_thresh"]) if ch.get("y_thresh") is not None else 0.0
            n_up = sum(1 for pt in pts_all if isinstance(pt.get("x"), (int, float)) and isinstance(pt.get("y"), (int, float)) and pt["y"] >= yt and pt["x"] >= xt)
            n_dn = sum(1 for pt in pts_all if isinstance(pt.get("x"), (int, float)) and isinstance(pt.get("y"), (int, float)) and pt["y"] >= yt and pt["x"] <= -xt)
            cm.append({
                "element": f"{prefix}{ch.get('kind', 'scatter')}_dataset:{len(pts_all)}_points",
                "kind": "data",
                "relation": f"n={len(pts_all)} (Up={n_up}, Down={n_dn} at |x|>={xt:g}, y>={yt:g}; top/highlighted listed below)",
                "source": dsrc,
            })
            hl_set = set(str(g) for g in (ch.get("highlight_labels") or ch.get("highlight_genes") or ch.get("label_genes") or []))
            scored = []
            for pt in pts_all:
                if not pt.get("label"):
                    continue
                xv = float(pt["x"]) if isinstance(pt.get("x"), (int, float)) else 0.0
                yv = float(pt["y"]) if isinstance(pt.get("y"), (int, float)) else 0.0
                is_hl = 1 if str(pt["label"]) in hl_set else 0
                is_sig = 1 if (yv >= yt and abs(xv) >= xt) else 0
                scored.append((is_hl, is_sig, abs(xv) * max(0.5, yv) + yv, pt))
            scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
            pts_show = [t[3] for t in scored[:25]]
        else:
            pts_show = [pt for pt in pts_all if pt.get("label") or len(pts_all) <= 15]
        for pt in pts_show:
            plbl = pt.get("label") or f"({pt.get('x')},{pt.get('y')})"
            cm.append({"element": f"{prefix}point:{plbl}",
                       "kind": "data",
                       "relation": f"x={pt.get('x')} y={pt.get('y')} group={pt.get('group', '')}",
                       "source": pt.get("source", dsrc)})
        items_all = ch.get("items") or []
        if len(items_all) > 40:
            cm.append({"element": f"{prefix}dotplot_dataset:{len(items_all)}_items", "kind": "data",
                       "relation": f"total={len(items_all)} items (showing first 40)", "source": dsrc})
        for it in items_all[:40]:
            cm.append({"element": f"{prefix}dot:{it.get('label', '')}", "kind": "data",
                       "relation": f"x={it.get('x')} size={it.get('size')} color={it.get('color')}",
                       "source": it.get("source", dsrc)})
        for g in ch.get("groups") or []:
            if isinstance(g, dict) and g.get("values"):
                gv = g["values"]
                rel_g = (f"n={len(gv)} range=[{min(gv):.4g}..{max(gv):.4g}]"
                         if len(gv) > 12 and all(isinstance(v, (int, float)) for v in gv) else f"n={len(gv)} values={gv}")
                cm.append({"element": f"{prefix}box:{g.get('label', '')}", "kind": "data",
                           "relation": rel_g, "source": g.get("source", dsrc)})
        if ch.get("rows") and ch.get("values"):
            cm.append({"element": f"{prefix}heatmap:{len(ch['rows'])}x{len(ch.get('cols') or [])}",
                       "kind": "data",
                       "relation": f"rows={ch['rows']}; cols={ch.get('cols')}",
                       "source": dsrc})
    return cm

def raster_fallback(svg, W, H, png, pdf, mpl_err, svg_path=None):
    note = {"mpl": False, "mpl_error": mpl_err, "fallback": None}
    w_px = min(3600, max(1600, int(W * 2)))
    if svg_path and Path(svg_path).exists():
        try:
            from render_preview import render as rp_png, render_pdf as rp_pdf
            ptool = rp_png(svg_path, png, w_px)
            ftool = rp_pdf(svg_path, pdf)
            if ptool or ftool:
                note["fallback"] = ptool or ftool
                if ftool and ftool != ptool:
                    note["pdf_fallback"] = ftool
                return {
                    "png": png if (ptool and Path(png).exists()) else None,
                    "pdf": pdf if (ftool and Path(pdf).exists()) else None,
                    **note,
                }
        except Exception:
            pass
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=svg.encode(), write_to=png, output_width=w_px)
        cairosvg.svg2pdf(bytestring=svg.encode(), write_to=pdf)
        note["fallback"] = "cairosvg"
        return {"png": png, "pdf": pdf, **note}
    except Exception:
        pass
    for mod in ("pymupdf", "fitz"):
        try:
            m = __import__(mod)
            doc = m.open(stream=svg.encode("utf-8"), filetype="svg")
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            Path(pdf).write_bytes(pdf_bytes)
            pdoc = m.open("pdf", pdf_bytes)
            pix = pdoc[0].get_pixmap(matrix=m.Matrix(2.0, 2.0), alpha=False)
            pix.save(png)
            pdoc.close()
            note["fallback"] = mod
            return {"png": png, "pdf": pdf, **note}
        except Exception:
            continue
    import shutil, subprocess
    if shutil.which("rsvg-convert"):
        try:
            subprocess.run(["rsvg-convert", "-w", str(w_px), "-o", png], input=svg.encode(),
                           check=True, timeout=30)
            note["fallback"] = "rsvg-convert"
            return {"png": png if Path(png).exists() else None, "pdf": None, **note}
        except Exception:
            pass
    note["fallback"] = "none; SVG written; raster failed"
    return {"png": None, "pdf": None, **note}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--basename", default="fig")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--preview-dpi", type=int, default=100)
    ap.add_argument("--scales", default="compact,regular,roomy")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    s = render(spec, dpi=a.dpi, scales=a.scales.split(","), outdir=a.outdir,
               basename=a.basename, preview_dpi=a.preview_dpi)
    if a.strict and (s["checks"]["n_violations"] > 0 or s["checks"]["svg_audit"]["n_violations"] > 0):
        sys.exit(2)

if __name__ == "__main__":
    main()
