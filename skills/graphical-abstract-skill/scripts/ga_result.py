#!/usr/bin/env python3
"""Build result.json: merge output_contract fields, scan ACTUAL output dir, honest status.

Usage:
  python3 ga_result.py --case /input/case.json --out /app/output/result.json \
      [--outdir /app/output] [--work /app/work] [--report report.json] \
      [--build-report _build_report.json] [--main file.svg]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gaconfig import VERSION, parse_svg_dims  # noqa: E402


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def png_dims(p: Path):
    try:
        with p.open("rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return [w, h]
    except Exception:
        pass
    return None


def contract_fields(case: dict):
    for key in ("output_contract", "required_outputs", "output_schema",
                "result_contract"):
        v = case.get(key)
        if isinstance(v, dict):
            # Support JSON-schema-like {"properties": {...}} or flat dict
            if isinstance(v.get("properties"), dict):
                return list(v["properties"].keys()), key
            return list(v.keys()), key
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            return list(v), key
    return [], None


def _extract_inventory(brief_path: Path) -> dict | None:
    """Auto-extract machine-auditable entity/relation/visual-encoding inventory from brief.json."""
    if not brief_path.exists():
        return None
    try:
        br = json.loads(brief_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    panels_inv, entities, relations, encodings = [], [], [], []

    _CHART_TYPES = {
        "chart", "bar", "hbar", "stacked", "line", "dot", "box", "scatter",
        "volcano", "paired", "slope", "before_after", "heatmap", "survival", "km",
    }

    def _walk(pid, blocks):
        for bl in blocks:
            bt = str(bl.get("type", "")).lower()
            if bt == "row":
                _walk(pid, bl.get("blocks", []))
            elif bt == "mechanism":
                zmap = {}
                for z in bl.get("zones", []):
                    for nid in z.get("nodes", []):
                        zmap[nid] = z.get("label", "")
                for nd in bl.get("nodes", []):
                    entities.append({
                        "panel": pid,
                        "id": nd.get("id", ""),
                        "label": nd.get("label", ""),
                        "sub": nd.get("sub", ""),
                        "compartment": zmap.get(nd.get("id", ""), ""),
                        "icon": nd.get("icon", ""),
                    })
                for ed in bl.get("edges", []):
                    relations.append({
                        "panel": pid,
                        "from": ed.get("from", ""),
                        "to": ed.get("to", ""),
                        "kind": ed.get("kind", "activate"),
                        "label": ed.get("label", ""),
                    })
            elif bt in _CHART_TYPES:
                kind = bl.get("kind", "bar" if bt == "chart" else bt)
                ch_map = {
                    "bar": "bar_height", "hbar": "bar_length", "stacked": "stacked_segment_height",
                    "line": "y_position+slope", "dot": "y_position", "box": "box_whisker_quartiles+replicates",
                    "paired": "paired_before_after_trajectory", "slope": "paired_before_after_trajectory",
                    "before_after": "paired_before_after_trajectory",
                    "scatter": "x_y_coordinates", "volcano": "log2FC_x_neglog10p_y_threshold_color",
                    "survival": "kaplan_meier_step_survival", "km": "kaplan_meier_step_survival",
                    "heatmap": "sequential_or_diverging_color_ramp",
                }
                series = bl.get("series", [])
                encodings.append({
                    "panel": pid,
                    "chart_kind": kind,
                    "title": bl.get("title", ""),
                    "channel": ch_map.get(kind, kind),
                    "ylabel": bl.get("ylabel", ""),
                    "xlabel": bl.get("xlabel", ""),
                    "series": [s.get("name", f"S{i+1}") for i, s in enumerate(series)],
                    "has_error_bars": any(bool(s.get("err")) for s in series),
                    "has_replicates": any(bool(s.get("points")) for s in series),
                    "has_sig_brackets": bool(bl.get("sig")),
                    "note": bl.get("note", ""),
                })
            elif bt == "svg":
                encodings.append({
                    "panel": pid,
                    "chart_kind": "custom_svg_schematic",
                    "title": bl.get("title", ""),
                    "channel": "vector_schematic",
                    "note": bl.get("note", ""),
                })

    for idx, p in enumerate(br.get("panels", [])):
        pid = p.get("id", f"P{idx+1}")
        panels_inv.append({
            "id": pid,
            "badge": p.get("badge", chr(65 + idx % 26)),
            "role": p.get("role", "neutral"),
            "title": p.get("title", ""),
        })
        _walk(pid, p.get("blocks", []))

    return {
        "title": br.get("title", ""),
        "sources_declared": br.get("sources", ""),
        "panels": panels_inv,
        "entities": entities,
        "relations": relations,
        "visual_encodings": encodings,
    }


def _auto_provenance(brief_path: Path) -> tuple[dict, dict]:
    """Derive baseline source_map & data_mapping from brief.json if report.json omits them."""
    smap, dmap = {}, {}
    if not brief_path.exists():
        return smap, dmap
    try:
        br = json.loads(brief_path.read_text(encoding="utf-8"))
    except Exception:
        return smap, dmap
    root_src = str(br.get("sources", "")).strip()
    if root_src:
        smap["figure_sources"] = root_src

    _CHART_TYPES = {
        "chart", "bar", "hbar", "stacked", "line", "dot", "box", "scatter",
        "volcano", "paired", "slope", "before_after", "heatmap", "survival", "km",
    }

    def _walk(pid, blocks, p_src):
        ci = 0
        for bl in blocks:
            bt = str(bl.get("type", "")).lower()
            if bt == "row":
                _walk(pid, bl.get("blocks", []), p_src)
            elif bt in _CHART_TYPES:
                ci += 1
                key = f"{pid}.chart{ci}" if ci > 1 else f"{pid}.chart"
                parts = [bl.get("kind", "bar" if bt == "chart" else bt)]
                if bl.get("title"):
                    parts.append(str(bl["title"]))
                if bl.get("ylabel"):
                    parts.append(f"y={bl['ylabel']}")
                if bl.get("xlabel"):
                    parts.append(f"x={bl['xlabel']}")
                if bl.get("note"):
                    parts.append(str(bl["note"]))
                if bl.get("source"):
                    parts.append(f"source={bl['source']}")
                    smap[key] = str(bl["source"])
                elif p_src:
                    smap.setdefault(key, p_src)
                dmap[key] = "; ".join(parts)
            elif bt in ("mechanism", "svg") and bl.get("source"):
                smap[f"{pid}.{bt}"] = str(bl["source"])

    for idx, p in enumerate(br.get("panels") or br.get("panel") or []):
        pid = p.get("id", f"P{idx+1}")
        p_src = str(p.get("source") or root_src or "").strip()
        if p_src:
            smap[pid] = p_src
        _walk(pid, p.get("blocks", []), p_src)
    return smap, dmap


def build_result(case_path: Path, out_path: Path, outdir: Path | None = None,
                 work: Path | None = None, report_path: Path | None = None,
                 build_report_path: Path | None = None, main_svg: str | None = None,
                 brief_path: Path | None = None) -> dict:
    case = json.loads(Path(case_path).read_text(encoding="utf-8"))
    out = Path(out_path).resolve()
    outdir = Path(outdir).resolve() if outdir else out.parent
    work = Path(work).resolve() if work else outdir

    rep = {}
    if report_path and Path(report_path).exists():
        try:
            loaded = json.loads(Path(report_path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                rep = loaded
        except Exception:
            rep = {}

    # Merge pipeline _build_report diagnostics into checks
    br_cands = []
    if build_report_path:
        br_cands.append(Path(build_report_path))
    br_cands.extend([work / "_build_report.json", outdir / "_build_report.json"])
    for cand in br_cands:
        if cand.exists():
            try:
                br = json.loads(cand.read_text(encoding="utf-8"))
                ck = rep.setdefault("checks", {})
                if isinstance(ck, dict):
                    if br.get("export_check"):
                        ck["export_check"] = br.get("export_check")
                    if br.get("render_engine"):
                        ck["render_engine"] = br.get("render_engine")
                    if br.get("layout"):
                        ck["layout"] = br.get("layout")
                    if br.get("canvas"):
                        ck["canvas"] = br.get("canvas")
                    panels = br.get("diag", {}).get("panels", {})
                    if panels:
                        ck["panel_autofit"] = {k: v.get("fs") for k, v in panels.items()}
                break
            except Exception:
                pass

    # Auto-merge machine-verified ga_check telemetry if present
    for ck_cand in (work / "_check_report.json", outdir / "_check_report.json"):
        if ck_cand.exists():
            try:
                cr = json.loads(ck_cand.read_text(encoding="utf-8"))
                ck = rep.setdefault("checks", {})
                if isinstance(ck, dict):
                    ck["ga_check"] = {
                        "pass": cr.get("pass"),
                        "n_errors": len(cr.get("errors", [])),
                        "n_warnings": len(cr.get("warnings", [])),
                        "n_text": cr.get("n_text"),
                        "n_shapes": cr.get("n_shapes"),
                        "n_mech_nodes": cr.get("n_mech_nodes"),
                    }
                    for k_sub in ("font_audit", "color_audit", "layer_audit", "data_grounding"):
                        if cr.get(k_sub):
                            ck[k_sub] = cr[k_sub]
                break
            except Exception:
                pass

    # Auto-merge surgical edit preservation proof if Path B was executed
    edit_changes = []
    edit_source_info = None
    for ed_cand in (work / "_edit_report.json", outdir / "_edit_report.json"):
        if ed_cand.exists():
            try:
                er = json.loads(ed_cand.read_text(encoding="utf-8"))
                ck = rep.setdefault("checks", {})
                if isinstance(ck, dict):
                    ck["source_preservation"] = {
                        "source_svg": er.get("source_svg"),
                        "source_sha256_16": er.get("source_sha256_16"),
                        "edited_sha256_16": er.get("edited_sha256_16"),
                        "dom_elements_before": er.get("dom_elements_before"),
                        "dom_elements_after": er.get("dom_elements_after"),
                        "untouched_layers_preserved": er.get("untouched_layers_preserved"),
                        "n_changes": len(er.get("changes", [])),
                    }
                if er.get("source_svg"):
                    edit_source_info = f"{er.get('source_svg')} (sha256:{er.get('source_sha256_16', '')})"
                edit_changes = list(er.get("changes", []))
                break
            except Exception:
                pass

    # Scan ACTUAL delivered output directory first (no ghost artifacts!)
    scan_dir = outdir if any(outdir.glob("*.svg")) or any(outdir.glob("*.png")) else work
    arts = []
    for suf in ("svg", "png", "pdf"):
        for p in sorted(scan_dir.glob(f"*.{suf}")):
            if p.name.startswith("_"):
                continue
            dims = (list(parse_svg_dims(p.read_text(encoding="utf-8", errors="ignore")))
                    if suf == "svg" else (png_dims(p) if suf == "png" else None))
            arts.append({"path": p.name, "type": suf, "bytes": p.stat().st_size,
                         "sha256_16": sha256(p), "dims": dims})

    svgs = [x for x in arts if x["type"] == "svg"]
    pngs = [x for x in arts if x["type"] == "png" and "@2x" not in x["path"]]
    pngs_all = [x for x in arts if x["type"] == "png"]
    pdfs = [x for x in arts if x["type"] == "pdf"]

    fields, src = contract_fields(case)
    main_rel = main_svg or (svgs[0]["path"] if svgs else None)
    png_rel = (pngs[0]["path"] if pngs else (pngs_all[0]["path"] if pngs_all else None))
    pdf_rel = pdfs[0]["path"] if pdfs else None

    chg_log = list(rep.get("change_log") or [])
    if edit_changes:
        for ch_item in edit_changes:
            if ch_item not in chg_log:
                chg_log.append(ch_item)
    if not chg_log:
        chg_log = [f"{VERSION}: deterministic build, all checks logged"]

    bp_use = Path(brief_path) if brief_path else (work / "brief.json")
    inv = _extract_inventory(bp_use)
    auto_smap, auto_dmap = _auto_provenance(bp_use)
    if edit_source_info and "source_svg" not in auto_smap:
        auto_smap["source_svg"] = edit_source_info
    rep_smap = rep.get("source_map")
    rep_dmap = rep.get("data_mapping")
    merged_smap = ({**auto_smap, **rep_smap} if isinstance(rep_smap, dict)
                   else (rep_smap if rep_smap else auto_smap))
    merged_dmap = ({**auto_dmap, **rep_dmap} if isinstance(rep_dmap, dict)
                   else (rep_dmap if rep_dmap else auto_dmap))
    ck_dict = rep.get("checks", {"note": "run ga_check.py; see stderr/stdout"})
    if isinstance(ck_dict, dict):
        png_dpi = (ck_dict.get("export_check", {}).get("png", {}).get("dpi")
                   if isinstance(ck_dict.get("export_check"), dict) else None) or 96
        ck_dict.setdefault("export_specs", {
            "svg": next(({"file": x["path"], "dims": x["dims"], "sha256_16": x["sha256_16"]} for x in svgs), None),
            "png": next(({"file": x["path"], "dims": x["dims"], "dpi": png_dpi, "sha256_16": x["sha256_16"]} for x in pngs), None),
            "pdf": next(({"file": x["path"], "bytes": x["bytes"], "sha256_16": x["sha256_16"]} for x in pdfs), None),
        })
    auto_ok = []
    if isinstance(ck_dict, dict):
        if isinstance(ck_dict.get("ga_check"), dict) and ck_dict["ga_check"].get("pass"):
            auto_ok.append("geometry_bounds_overlap_font_floor")
        if isinstance(ck_dict.get("export_check"), dict):
            if ck_dict["export_check"].get("png", {}).get("non_blank"):
                auto_ok.append("png_non_blank_1to1")
            if ck_dict["export_check"].get("pdf", {}).get("searchable_text"):
                auto_ok.append("pdf_vector_searchable_text")
        if isinstance(ck_dict.get("color_audit"), dict) and ck_dict["color_audit"].get("deuteranopia_pass"):
            auto_ok.append("colorblind_grayscale_contrast")
        if isinstance(ck_dict.get("data_grounding"), dict) and ck_dict["data_grounding"].get("checked", 0) > 0:
            dg = ck_dict["data_grounding"]
            auto_ok.append(f"source_data_grounding({dg.get('matched')}/{dg.get('checked')})")
        if isinstance(ck_dict.get("source_preservation"), dict) and ck_dict["source_preservation"].get("untouched_layers_preserved"):
            auto_ok.append("source_svg_layers_preserved")

    human_conf = rep.get("human_confirmation") or {
        "status": "pending_domain_author_signoff",
        "auto_verified": auto_ok,
        "requires_author_review": [
            "Confirm biological/scientific entity spelling and causal arrow directionality against original manuscript",
            "Confirm statistical test interpretation (error bar type SD/SEM and p-value annotations) and journal canvas specs",
        ],
    }

    result = {
        "case_id": case.get("case_id", case.get("id", "unknown")),
        "status": "complete",
        "version": VERSION,
        "main_result": main_rel,
        "artifacts": arts,
        "source_map": merged_smap,
        "data_mapping": merged_dmap,
        "checks": ck_dict,
        "uncertainty": rep.get("uncertainty", []),
        "change_log": chg_log,
        "human_confirmation": human_conf,
        "notes": rep.get("notes", ""),
        "limits": list(rep.get("limits", [])),
    }
    if inv:
        result["scientific_inventory"] = inv

    def autofill(f):
        fl = f.lower()
        if "png" in fl and png_rel:
            return png_rel
        if "pdf" in fl and pdf_rel:
            return pdf_rel
        if any(k in fl for k in ("svg", "figure", "editable", "source_file", "main")) \
                and not any(x in fl for x in ("source_map", "source_files", "provenance")) and main_rel:
            return main_rel
        if any(k in fl for k in ("export_check", "export_report", "audit", "check", "verification")):
            return result["checks"]
        if any(k in fl for k in ("export", "raster", "preview", "deliverable")):
            d = {}
            if main_rel:
                d["svg"] = main_rel
            if png_rel:
                d["png"] = png_rel
            if pdf_rel:
                d["pdf"] = pdf_rel
            return d or None
        if any(k in fl for k in ("data_map", "encoding", "legend")):
            return result["data_mapping"]
        if any(k in fl for k in ("provenance", "evidence", "source")):
            return result["source_map"]
        if any(k in fl for k in ("inventory", "entit", "relation", "panel_map", "claim")):
            return result.get("scientific_inventory") or result["source_map"]
        if "version" in fl:
            return result["version"]
        if any(k in fl for k in ("human", "confirm", "signoff", "review")):
            return result["human_confirmation"]
        if any(k in fl for k in ("change", "revision", "edit_log")):
            return result["change_log"]
        if any(k in fl for k in ("uncertain", "caveat")):
            return result["uncertainty"]
        if any(k in fl for k in ("limit", "partial")):
            return result["limits"]
        if any(k in fl for k in ("summary", "takeaway", "abstract", "caption", "description")):
            if rep.get("notes"):
                return rep["notes"]
            if bp_use.exists():
                try:
                    br_t = json.loads(bp_use.read_text(encoding="utf-8"))
                    ttl = str(br_t.get("title", "")).strip()
                    sub = str(br_t.get("subtitle", "")).strip()
                    return f"{ttl} — {sub}" if (ttl and sub) else (ttl or None)
                except Exception:
                    pass
        return None

    missing = []
    for f in fields:
        if f in result:
            continue
        if f in rep:
            result[f] = rep[f]
            continue
        v = autofill(f)
        if v is not None:
            result[f] = v
        else:
            result[f] = ""
            missing.append(f)

    if missing:
        result["status"] = "partial"
        result["limits"].append(f"missing output_contract fields: {missing}")
    if not (svgs and pngs_all and pdfs):
        result["status"] = "partial"
        miss = [t for t, lst in (("svg", svgs), ("png", pngs_all), ("pdf", pdfs)) if not lst]
        result["limits"].append(f"missing exports: {miss}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"out": str(out), "status": result["status"],
            "contract_source": src, "contract_fields": fields,
            "missing": missing, "artifacts": len(arts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--outdir", default=None,
                    help="directory containing delivered artifacts (default: out.parent)")
    ap.add_argument("--work", default=None,
                    help="work directory for locating _build_report.json (fallback scan)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--build-report", default=None)
    ap.add_argument("--main", default=None, help="main editable svg filename")
    ap.add_argument("--brief", default=None, help="optional brief.json path for inventory/provenance")
    a = ap.parse_args()
    summary = build_result(
        case_path=Path(a.case),
        out_path=Path(a.out),
        outdir=Path(a.outdir) if a.outdir else None,
        work=Path(a.work) if a.work else None,
        report_path=Path(a.report) if a.report else None,
        build_report_path=Path(a.build_report) if a.build_report else None,
        main_svg=a.main,
        brief_path=Path(a.brief) if a.brief else None,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
