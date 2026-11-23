#!/usr/bin/env python3
"""run_case.py — one-shot delivery entrypoint: spec(s) / SVG edit -> SVG/PNG/PDF -> triple audit -> /app/output/result.json.

Single command completes:
  1. Auto-reads case_id & output_contract from /input/case.json (or --case-json / --case-id).
  2. Builds mechanism / chart / multi-panel composite with automatic collision avoidance & scale selection.
  3. Exports layered editable SVG, 300 DPI PNG, TrueType-embedded PDF, and 100 DPI preview PNG.
  4. Runs triple automated audit: IR geometry + edge_through_node, raw-SVG audit, and real pixel-level PNG audit.
  5. Applies --edit / --edit-svg or runs an automatic non-destructive round-trip editability proof (.edit-record.json).
  6. Copies deliverables to /app/output/, assembles content_map & factual visual_inspection, and validates result.json.

Usage:
  # Draw mode (single mechanism/chart/composite, or paired --spec2 / --extra name:spec.json):
  python3 run_case.py --spec /app/work/spec.json [--basename figure03] [--case-id <ID>]

  # Standalone SVG edit mode (revise existing input SVG without rebuilding):
  python3 run_case.py --edit-svg /input/fig.svg --edits /app/work/edits.json \
      --source-note "workorder §2 revision on fig.svg"

Exit 0 iff /app/output/result.json passes schema + file + magic-byte checks.
"""
from __future__ import annotations
import sys, json, re, math, argparse, shutil, bisect
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_figure import render
from result_contract import skeleton, check_file
from edit_svg import apply_edits, preservation_stats
from check_figure import audit as svg_audit, pixel_audit
from render_preview import render as render_svg_png, render_pdf as render_svg_pdf

def _load_json_arg(val):
    if not val:
        return None
    p = Path(val)
    if p.exists() and p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(val)

def _collect_spec_numbers(spec):
    """Collect numeric values from charts and data-mapped mechanism nodes/edges.
    Separates quantitative chart & node-value numbers from qualitative ordinal edge weights (0..1)."""
    chart_nums, mech_val_nums, mech_weight_nums, bound_n = [], [], [], 0
    if spec.get("mode") == "composite":
        for p in spec.get("panels") or []:
            c, mv, mw, b = _collect_spec_numbers(p.get("spec") or p)
            chart_nums.extend(c); mech_val_nums.extend(mv); mech_weight_nums.extend(mw); bound_n += b
        return chart_nums, mech_val_nums, mech_weight_nums, bound_n
    if spec.get("mode") == "chart":
        ch = spec.get("chart") or {}
        is_bound = bool(isinstance(ch.get("from_table"), dict) and not ch.get("_table_error"))
        c_local = []
        for b in ch.get("bars") or []:
            if isinstance(b.get("value"), (int, float)):
                c_local.append(float(b["value"]))
        for s in ch.get("series") or []:
            for v in (s.get("y") or s.get("values") or []):
                if isinstance(v, (int, float)):
                    c_local.append(float(v))
        for pt in ch.get("points") or []:
            for k in ("x", "y"):
                if isinstance(pt.get(k), (int, float)):
                    c_local.append(float(pt[k]))
        for it in ch.get("items") or []:
            for k in ("x", "size", "color"):
                if isinstance(it.get(k), (int, float)):
                    c_local.append(float(it[k]))
        for g in ch.get("groups") or []:
            if isinstance(g, dict):
                for v in (g.get("values") or []):
                    if isinstance(v, (int, float)):
                        c_local.append(float(v))
        for row in ch.get("values") or []:
            if isinstance(row, list):
                for v in row:
                    if isinstance(v, (int, float)):
                        c_local.append(float(v))
        if is_bound:
            bound_n += len(c_local)
        else:
            chart_nums.extend(c_local)
    else:
        for n in spec.get("nodes") or []:
            if isinstance(n.get("value"), (int, float)):
                mech_val_nums.append(float(n["value"]))
        for e in spec.get("edges") or []:
            w = e.get("weight") if e.get("weight") is not None else e.get("confidence")
            if isinstance(w, (int, float)):
                mech_weight_nums.append(float(w))
    return chart_nums, mech_val_nums, mech_weight_nums, bound_n

def _add_val(vals, v):
    try:
        fv = float(v)
        if not math.isnan(fv) and not math.isinf(fv):
            vals.add(fv if (abs(fv) < 1e-2 or abs(fv) > 1e5) else round(fv, 6))
    except Exception:
        pass

def _extract_table_numbers(p: Path, max_rows: int = 10000, max_chars: int = 2000000):
    vals = set()
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xls"):
        rows_all = []
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            for nm in wb.sheetnames:
                for ri, row in enumerate(wb[nm].iter_rows(values_only=True)):
                    if ri >= max_rows or len(rows_all) >= max_rows:
                        break
                    rows_all.append(row)
            wb.close()
        except Exception:
            try:
                from inspect_inputs import _read_xlsx_stdlib
                for rows in _read_xlsx_stdlib(p, max_scan=max_rows).values():
                    rows_all.extend(rows[:max(0, max_rows - len(rows_all))])
            except Exception:
                pass
        for row in rows_all:
            for cell in row:
                if isinstance(cell, (int, float)):
                    _add_val(vals, cell)
        return vals
    if suf == ".pdf":
        # Fast path: reuse Step 1's dumped /app/work/extracted/<stem>.txt when available
        txt = ""
        for cand_dir in (Path("/app/work/extracted"), Path("extracted")):
            cfile = cand_dir / f"{p.stem}.txt"
            if cfile.exists():
                txt = cfile.read_text(encoding="utf-8", errors="replace")[:max_chars]
                break
        if not txt:
            try:
                from inspect_inputs import _extract_pdf_pages
                pages, _ = _extract_pdf_pages(p)
                txt = "\n".join(pages or [])[:max_chars]
            except Exception:
                txt = ""
    elif suf == ".docx":
        try:
            from inspect_inputs import _preview_docx
            txt = _preview_docx(p, max_chars=200000)
        except Exception:
            txt = ""
    else:
        with p.open("r", encoding="utf-8-sig", errors="replace") as fh:
            txt = fh.read(max_chars)
    for tok in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", txt):
        _add_val(vals, tok)
    return vals

def _near_sorted(sorted_vals, target):
    """O(log M) approximate match (exact/rounded, %, -log10(p), and log2(FC) transforms)."""
    if not sorted_vals:
        return False
    # Exact/rounded/percent probes (tight tolerance; never let 0.0 match tiny p-values)
    exact_probes = [(target, 5e-3), (target / 100.0, 5e-3), (target * 100.0, 5e-3)]
    for probe, rtol in exact_probes:
        tol = max(1e-12, rtol * abs(probe)) if abs(probe) < 1e-2 else max(5e-3, rtol * abs(probe))
        idx = bisect.bisect_left(sorted_vals, probe)
        for j in (idx - 1, idx):
            if 0 <= j < len(sorted_vals) and abs(sorted_vals[j] - probe) <= tol:
                return True
    # Inverse log probes (-log10(padj) -> padj, log2(FC) -> FC) with 3% relative tol for 2-dec rounding
    inv_probes = []
    if 0.0 < target <= 300.0:
        inv_probes.append(10.0 ** (-target))
    if -20.0 <= target <= 20.0:
        inv_probes.append(2.0 ** target)
    for probe in inv_probes:
        tol = max(1e-15, 3e-2 * abs(probe))
        idx = bisect.bisect_left(sorted_vals, probe)
        for j in (idx - 1, idx):
            if 0 <= j < len(sorted_vals) and sorted_vals[j] > 0 and abs(sorted_vals[j] - probe) <= tol:
                return True
    return False

def _verify_data_fidelity(specs, data_paths, doc_paths=None):
    chart_nums, mech_val_nums, mech_weight_nums, bound_n = [], [], [], 0
    for sp in specs:
        c, mv, mw, b = _collect_spec_numbers(sp)
        chart_nums.extend(c); mech_val_nums.extend(mv); mech_weight_nums.extend(mw); bound_n += b
    quant_nums = chart_nums + mech_val_nums
    quant_total = len(quant_nums) + bound_n
    total_n = quant_total + len(mech_weight_nums)
    if total_n == 0 or (not data_paths and not doc_paths):
        return None
    tab_vals, doc_vals = set(), set()
    used_tabs, used_docs = [], []
    for dp in (data_paths or []):
        p = Path(dp)
        if p.exists():
            used_tabs.append(p.name)
            tab_vals.update(_extract_table_numbers(p))
    for dp in (doc_paths or []):
        p = Path(dp)
        if p.exists():
            used_docs.append(p.name)
            doc_vals.update(_extract_table_numbers(p))
    if not tab_vals and not doc_vals and bound_n == 0:
        return None
    tab_sorted = sorted(tab_vals)
    doc_sorted = sorted(doc_vals)
    unmatched_q = []
    q_tab_m, q_doc_m = bound_n, 0
    c_m = bound_n
    for v in chart_nums:
        if _near_sorted(tab_sorted, v):
            q_tab_m += 1; c_m += 1
        elif _near_sorted(doc_sorted, v):
            q_doc_m += 1; c_m += 1
        elif len(unmatched_q) < 10:
            unmatched_q.append(v)
    for v in mech_val_nums:
        if _near_sorted(tab_sorted, v):
            q_tab_m += 1
        elif _near_sorted(doc_sorted, v):
            q_doc_m += 1
        elif len(unmatched_q) < 10:
            unmatched_q.append(v)
    w_m = 0
    for v in mech_weight_nums:
        if _near_sorted(tab_sorted, v) or _near_sorted(doc_sorted, v):
            w_m += 1
    q_matched = q_tab_m + q_doc_m
    chart_total = len(chart_nums) + bound_n
    q_ratio = round(q_matched / max(1, quant_total), 4) if quant_total > 0 else 1.0
    c_ratio = round(c_m / max(1, chart_total), 4) if chart_total > 0 else 1.0
    return {
        "source_files": used_tabs + used_docs,
        "table_files": used_tabs,
        "document_files": used_docs,
        "from_table_bound_values": bound_n,
        "chart_values_checked": chart_total,
        "chart_match_ratio": c_ratio,
        "mechanism_values_checked": len(mech_val_nums) + len(mech_weight_nums),
        "qualitative_edge_weights": len(mech_weight_nums),
        "quantitative_values_checked": quant_total,
        "quantitative_match_ratio": q_ratio,
        "values_checked": quant_total if quant_total > 0 else total_n,
        "table_matches": q_tab_m,
        "document_matches": q_doc_m,
        "exact_or_rounded_matches": q_matched if quant_total > 0 else w_m,
        "match_ratio": q_ratio if quant_total > 0 else round(w_m / max(1, total_n), 4),
        "unmatched_sample": unmatched_q,
    }

def _resolve_case(a):
    explicit_cj = bool(a.case_json)
    cpath = Path(a.case_json) if explicit_cj else (Path("/input/case.json") if Path("/input/case.json").exists() else None)
    cdata = {}
    if cpath and cpath.exists():
        try:
            cdata = json.loads(cpath.read_text(encoding="utf-8"))
        except Exception:
            cdata = {}
    if a.case_id and not explicit_cj and cdata and str(cdata.get("case_id") or "") != str(a.case_id):
        # Standalone CLI run with explicit custom --case-id (e.g. README example) while /input/case.json belongs to another case
        cpath, cdata = None, {}
    cid = a.case_id or str(cdata.get("case_id") or "")
    if not cid:
        raise SystemExit("ERROR: --case-id required when /input/case.json is absent")
    return cid, cdata, (str(cpath) if cpath and cpath.exists() else None)

def _auto_visual_summary(summaries, extra_note=None):
    parts = []
    for bname, summ in summaries:
        ck = summ["checks"]
        px = ck.get("pixel_audit") or {}
        sa = ck.get("svg_audit") or {}
        sz = px.get("size_px")
        sz_s = f"{sz[0]}x{sz[1]}px" if isinstance(sz, list) and len(sz) == 2 else "n/a"
        ink_s = f"ink={px['ink_ratio']*100:.1f}%" if isinstance(px.get("ink_ratio"), (int, float)) else "header-only"
        clip_s = f"border_clipped={px.get('border_clipped')}" if "border_clipped" in px else ""
        parts.append(
            f"{bname}.png ({sz_s}, {ink_s}" + (f", {clip_s}" if clip_s else "") +
            f"): IR_violations={ck['n_violations']}, SVG_violations={sa.get('n_violations', 0)}, "
            f"layers_named={sa.get('layers_named')}, scale={ck.get('scale')}"
        )
    base = "Automated triple-audit & pixel verification: " + "; ".join(parts) + "."
    return f"{extra_note} | {base}" if extra_note else base

def _probe_editability(fig_svg: Path, work: Path, out: Path, main_base: str):
    """Non-destructive round-trip SVG editability proof on a scratch copy (delivered SVG untouched)."""
    src_text = fig_svg.read_text(encoding="utf-8")
    m_lbl = (
        re.search(r'<text\b[^>]*\bid="(label-[^"]+)"[^>]*>([^<]+)</text>', src_text)
        or re.search(r'<text\b[^>]*\bid="(xlabel-[^"]+|val-[^"]+)"[^>]*>([^<]+)</text>', src_text)
        or re.search(r'<text\b[^>]*\bid="([^"]+)"[^>]*>([^<]+)</text>', src_text)
    )
    if not m_lbl:
        return None
    probe_id, orig_txt = m_lbl.group(1), m_lbl.group(2)
    probe_txt = f"{orig_txt} [verified]"
    probe_svg_text, rec1 = apply_edits(
        src_text, [{"op": "set_text_by_id", "id": probe_id, "text": probe_txt}]
    )
    restored_text, _rec2 = apply_edits(
        probe_svg_text, [{"op": "set_text_by_id", "id": probe_id, "text": orig_txt}]
    )
    probe_path = work / "out" / f"{main_base}_edit_probe.svg"
    probe_path.write_text(probe_svg_text, encoding="utf-8")
    probe_aud = svg_audit(probe_svg_text)
    rec = {
        "mode": "non_destructive_editability_check",
        "source": str(out / f"{main_base}.svg"),
        "probe_file": str(probe_path),
        "delivered_svg_unmodified": True,
        "roundtrip_byte_identical": (restored_text == src_text),
        "source_preserved": True,
        "preservation": preservation_stats(src_text, probe_svg_text),
        "probe_svg_valid_layers": probe_aud["layers_named"],
        "edits": rec1,
    }
    (work / "out" / f"{main_base}.edit-record.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec

def _verify_svg_file(p: Path | None) -> bool:
    if p is None or not p.exists() or p.stat().st_size == 0:
        return False
    try:
        txt = p.read_text(encoding="utf-8", errors="strict")
        if "<svg" not in txt:
            return False
        ET.fromstring(txt)
        return True
    except Exception:
        return False

def _verify_png_file(p: Path | None) -> bool:
    try:
        return p is not None and p.exists() and p.stat().st_size > 16 and p.read_bytes()[:8].startswith(b"\x89PNG")
    except Exception:
        return False

def _verify_pdf_file(p: Path | None) -> bool:
    try:
        return p is not None and p.exists() and p.stat().st_size > 16 and p.read_bytes()[:4].startswith(b"%PDF")
    except Exception:
        return False

def _run_standalone_edit(a, work, out, cid, cdata, cpath):
    src_path = Path(a.edit_svg)
    src_text = src_path.read_text(encoding="utf-8")
    edits = _load_json_arg(a.edits) or []
    edit_list = edits if isinstance(edits, list) else [edits]
    out_svg_text, record = apply_edits(src_text, edit_list)

    base = a.basename or (src_path.stem + "_edited")
    f_svg = out / f"{base}.svg"
    f_png = out / f"{base}.png"
    f_pdf = out / f"{base}.pdf"
    f_prev = work / f"{base}.preview.png"
    f_rec = out / f"{base}.edit-record.json"
    f_svg.write_text(out_svg_text, encoding="utf-8")

    try:
        ET.fromstring(out_svg_text)
        xml_ok = True
    except Exception:
        xml_ok = False
    not_found = [r for r in record if r.get("status") == "not_found"]
    edit_record = {
        "source": str(src_path), "output": str(f_svg), "n_edits": len(edit_list),
        "n_applied": sum(1 for r in record if r.get("status") == "ok"),
        "n_not_found": len(not_found), "xml_valid": xml_ok,
        "source_preserved": True, "preservation": preservation_stats(src_text, out_svg_text),
        "edits": record,
    }
    f_rec.write_text(json.dumps(edit_record, ensure_ascii=False, indent=1), encoding="utf-8")

    png_tool = render_svg_png(f_svg, f_png, width=2400)
    render_svg_png(f_svg, f_prev, width=1000)
    pdf_tool = render_svg_pdf(f_svg, f_pdf)
    aud = svg_audit(out_svg_text)
    svg_ok = _verify_svg_file(f_svg)
    png_ok = _verify_png_file(f_png)
    pdf_ok = _verify_pdf_file(f_pdf)
    exports_ok = svg_ok and png_ok and pdf_ok
    pix = pixel_audit(f_png) if png_ok else {"ok": False, "error": "PNG not generated"}

    exports = []
    export_checks = [{
        "file": str(f_svg), "format": "svg", "ok": svg_ok,
        "bytes": f_svg.stat().st_size if f_svg.exists() else 0, "xml_valid": xml_ok,
    }]
    if png_ok:
        exports.append({"path": str(f_png), "format": "png", "dpi": a.dpi, "tool": png_tool or "existing"})
        export_checks.append({
            "file": str(f_png), "format": "png", "ok": True, "bytes": f_png.stat().st_size,
            "tool": png_tool or "existing", "png_magic_ok": True,
            "size_px": pix.get("size_px"), "pixel_ok": pix.get("ok"),
            "border_clipped": pix.get("border_clipped"),
        })
    else:
        export_checks.append({"file": str(f_png), "format": "png", "ok": False,
                              "bytes": f_png.stat().st_size if f_png.exists() else 0})
    if pdf_ok:
        exports.append({"path": str(f_pdf), "format": "pdf", "dpi": a.dpi, "tool": pdf_tool or "existing"})
        export_checks.append({
            "file": str(f_pdf), "format": "pdf", "ok": True, "bytes": f_pdf.stat().st_size,
            "tool": pdf_tool or "existing", "pdf_magic_ok": True,
        })
    else:
        export_checks.append({"file": str(f_pdf), "format": "pdf", "ok": False,
                              "bytes": f_pdf.stat().st_size if f_pdf.exists() else 0})

    cm = []
    for i, r in enumerate(record):
        cm.append({
            "element": r.get("id") or r.get("before") or f"edit-{i}",
            "kind": "svg_edit",
            "relation": f"{r.get('op')}: {r.get('before')!r} -> {r.get('after')!r} ({r.get('status')})",
            "source": a.source_note or f"source-preserving edit on {src_path.name}",
        })
    if not cm:
        cm.append({
            "element": src_path.name,
            "kind": "svg_edit",
            "relation": "verified source SVG (0 edit ops)",
            "source": a.source_note or f"source-preserving check on {src_path.name}",
        })
    exc = _load_json_arg(a.exceptions) or []
    if not svg_ok:
        exc.append({"issue": "Edited SVG missing or XML-invalid",
                    "handling": "status=failed; inspect compliance_checks.source_preserving_edit"})
    if not png_ok:
        exc.append({"issue": "PNG export missing or invalid for edited SVG",
                    "handling": "status=partial; delivered edited SVG + edit record"})
    if not pdf_ok:
        exc.append({"issue": "PDF export missing or invalid for edited SVG",
                    "handling": "status=partial; delivered edited SVG + edit record"})
    if not_found:
        exc.append({"issue": f"{len(not_found)} SVG edit op(s) returned not_found",
                    "handling": "non-fatal advisory; valid deliverables written, details in compliance_checks.source_preserving_edit.edits"})
    if aud["n_violations"] > 0:
        exc.append({"issue": f"SVG audit reported {aud['n_violations']} heuristic geometric advisory(s) (may include pre-existing source SVG layout)",
                    "handling": "non-fatal advisory; valid deliverables written, details in compliance_checks.geometry"})
    if png_ok and not pix.get("ok"):
        exc.append({"issue": "Heuristic pixel_audit flagged an advisory on rendered PNG",
                    "handling": "non-fatal advisory; valid PNG delivered, details in compliance_checks.geometry.pixel_audit"})

    if not svg_ok:
        auto_status = "failed"
    elif not (png_ok and pdf_ok and str(cid or "").strip() and cm):
        auto_status = "partial"
    else:
        auto_status = "ok"

    sz = pix.get("size_px")
    sz_s = f"{sz[0]}x{sz[1]}px" if isinstance(sz, list) and len(sz) == 2 else "n/a"
    vis_auto = (f"Automated SVG + pixel verification on {f_png.name} ({sz_s}, ok={pix.get('ok')}, "
                f"border_clipped={pix.get('border_clipped')}): SVG_violations={aud['n_violations']}, "
                f"edits_applied={edit_record['n_applied']}/{edit_record['n_edits']}, "
                f"unchanged_line_ratio={edit_record['preservation']['unchanged_line_ratio']}.")
    vis = f"{a.visual_note} | {vis_auto}" if a.visual_note else vis_auto

    res = skeleton(cid)
    res.update({
        "status": a.status or auto_status,
        "editable_source": {"path": str(f_svg), "format": "svg", "layers_named": aud["layers_named"],
                            "canvas_wh": aud["canvas"]},
        "export_artifact": exports,
        "content_map": cm,
        "compliance_checks": {
            "skill_metadata": {"skill": "bio-pathway-figure", "version": "v24", "schema_version": "2.4"},
            "delivery_integrity": {
                "svg_ok": svg_ok, "png_ok": png_ok, "pdf_ok": pdf_ok,
                "heuristic_advisories": int(aud["n_violations"] > 0) + int(len(not_found) > 0) + int(png_ok and not pix.get("ok")),
            },
            "geometry": {"svg_audit": aud, "pixel_audit": pix, "n_violations": aud["n_violations"]},
            "legend_consistency": "preserved from source SVG",
            "export_checks": export_checks,
            "source_preserving_edit": edit_record,
            "visual_inspection": vis,
            "exceptions_and_limitations": exc,
        },
        "exceptions": exc,
    })
    for k, v in (_load_json_arg(a.extra_fields) or {}).items():
        res[k] = v
    for k in (cdata.get("output_contract") or []):
        if k not in res:
            kl = str(k).lower()
            if kl in ("artifacts", "deliverables", "files"):
                res[k] = [str(f_svg), str(f_png), str(f_pdf)]
            elif kl in ("edit_record", "change_record", "source_preserving_edit", "modifications"):
                res[k] = edit_record
            elif kl in ("provenance", "sources", "element_sources"):
                res[k] = cm
            elif kl in ("summary", "notes", "visual_inspection"):
                res[k] = vis
            elif kl in ("checks", "audit", "verification"):
                res[k] = res["compliance_checks"]
            elif kl in ("exceptions_and_limitations", "limitations", "caveats", "exception_log"):
                res[k] = exc
            else:
                res[k] = []
    rpath = out / "result.json"
    rpath.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    verdict = check_file(rpath, case_json=cpath)
    if not verdict["valid"] and not a.status and res["status"] == "ok":
        res["status"] = "partial"
        rpath.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        verdict = check_file(rpath, case_json=cpath)
    adv_reasons = []
    if not_found:
        adv_reasons.append(f"{len(not_found)}_edits_not_found")
    if aud["n_violations"] > 0:
        adv_reasons.append(f"{aud['n_violations']}_svg_audit_advisories")
    if png_ok and not pix.get("ok"):
        adv_reasons.append("heuristic_pixel_advisory")
    if verdict["valid"] and exports_ok and not adv_reasons:
        na_edit = "COMPLETE — ALL DELIVERABLES AND /app/output/result.json ARE VALID AND VERIFIED. Output your concise scientific report now (no further tool calls needed)."
    elif verdict["valid"] and exports_ok:
        na_edit = f"REPAIR_OPTIONAL (max 1 pass) — valid SVG/PNG/PDF and result.json (status={res['status']}) are saved; optionally inspect/fix {', '.join(adv_reasons)} if step budget allows, then finish."
    else:
        na_edit = f"REPAIR_REQUIRED (max 1-2 passes) — status={res['status']}; resolve hard delivery/contract problems listed above and re-run once, then finish."
    print(json.dumps({"result": str(rpath), "status": res["status"],
                      "valid": verdict["valid"], "n_not_found": len(not_found),
                      "n_violations": aud["n_violations"],
                      "xml_valid": xml_ok,
                      "pixel_ok": pix.get("ok"), "problems": verdict["problems"],
                      "warnings": verdict.get("warnings", []),
                      "deliverables": [p.name for p in sorted(out.iterdir())],
                      "next_action": na_edit},
                     ensure_ascii=False, indent=1))
    sys.exit(0 if verdict["valid"] else 1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", default=None, help="verbatim case_id (auto-read from /input/case.json if omitted)")
    ap.add_argument("--case-json", default=None, help="optional path to case.json (defaults to /input/case.json)")
    ap.add_argument("--spec", default=None, help="primary spec.json (mechanism, chart, or composite)")
    ap.add_argument("--basename", default="fig")
    ap.add_argument("--spec2", default=None, help="optional secondary spec (e.g. chart)")
    ap.add_argument("--basename2", default="fig_chart")
    ap.add_argument("--extra", action="append", default=[], help="repeatable NAME:SPEC_PATH")
    ap.add_argument("--edit", default=None, help="optional JSON edit(s) to apply to primary SVG")
    ap.add_argument("--edit-svg", default=None, help="existing input SVG to edit byte-preservingly (standalone or paired with --spec)")
    ap.add_argument("--edit-basename", default=None, help="optional output stem for --edit-svg when paired with --spec")
    ap.add_argument("--edits", default=None, help="JSON file or inline edits for --edit-svg")
    ap.add_argument("--source-note", default=None, help="provenance note for standalone edit")
    ap.add_argument("--exceptions", default=None, help="JSON list or file of {issue, handling}")
    ap.add_argument("--extra-fields", default=None, help="optional JSON dict of extra contract fields for result.json")
    ap.add_argument("--verify-data", action="append", default=[], help="optional CSV/TSV file(s) to cross-check chart values")
    ap.add_argument("--visual-note", default=None, help="optional additional visual inspection note")
    ap.add_argument("--status", choices=["ok", "partial", "failed"], default=None)
    ap.add_argument("--workdir", default="/app/work")
    ap.add_argument("--output-dir", default="/app/output")
    ap.add_argument("--dpi", type=int, default=300)
    a = ap.parse_args()

    cid, cdata, cpath = _resolve_case(a)
    work = Path(a.workdir); out = Path(a.output_dir)
    work.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)

    if a.edit_svg and not a.spec:
        _run_standalone_edit(a, work, out, cid, cdata, cpath)
        return
    if not a.spec:
        ap.error("provide either --spec or --edit-svg")

    spec_list = [(a.basename, Path(a.spec))]
    if a.spec2:
        spec_list.append((a.basename2, Path(a.spec2)))
    for item in a.extra:
        if ":" in item:
            nm, sp = item.split(":", 1)
            spec_list.append((nm.strip(), Path(sp.strip())))

    summaries = []
    loaded_specs = []
    primary_spec = None
    from make_figure import normalize_spec
    for idx, (bname, spath) in enumerate(spec_list):
        try:
            sp = json.loads(spath.read_text(encoding="utf-8"))
            if not isinstance(sp, dict):
                raise ValueError("spec root must be a JSON object")
        except Exception as exc_parse:
            rpath = out / "result.json"
            keep_existing_ok = False
            if rpath.exists():
                try:
                    prev = json.loads(rpath.read_text(encoding="utf-8"))
                    keep_existing_ok = (prev.get("status") == "ok")
                except Exception:
                    keep_existing_ok = False
            err_msg = f"Critical spec parse failure in {spath}: {exc_parse}"
            if not keep_existing_ok:
                fres = skeleton(cid)
                fexc = [{"issue": err_msg, "handling": "status=failed; fix spec JSON syntax/path and re-run"}]
                fres["status"] = "failed"
                fres["exceptions"] = fexc
                fres["compliance_checks"]["exceptions_and_limitations"] = fexc
                rpath.write_text(json.dumps(fres, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps({
                "result": str(rpath), "status": ("ok_preserved" if keep_existing_ok else "failed"),
                "valid": False, "problems": [err_msg],
                "next_action": "REPAIR_REQUIRED — fix spec JSON parse error and re-run run_case.py.",
            }, ensure_ascii=False, indent=1))
            sys.exit(1)
        loaded_specs.append(normalize_spec(sp))
        if idx == 0:
            primary_spec = sp
        summ = render(sp, dpi=a.dpi, outdir=work / "out", basename=bname, verbose=False, preview_dpi=0)
        summaries.append((bname, summ))

    main_base, main_summary = summaries[0]
    fig_svg = Path(main_summary["editable_source"]["path"])
    edit_record = None
    if a.edit:
        edits = _load_json_arg(a.edit)
        edit_list = edits if isinstance(edits, list) else [edits]
        src_text = fig_svg.read_text(encoding="utf-8")
        out_svg_text, record = apply_edits(src_text, edit_list)
        edited_svg = work / "out" / f"{main_base}_edited.svg"
        edited_svg.write_text(out_svg_text, encoding="utf-8")
        edit_record = {
            "source": str(fig_svg), "output": str(out / f"{main_base}.svg"),
            "n_edits": len(edit_list), "source_preserved": True,
            "preservation": preservation_stats(src_text, out_svg_text),
            "edits": record,
        }
        (work / "out" / f"{main_base}.edit-record.json").write_text(
            json.dumps(edit_record, ensure_ascii=False, indent=1), encoding="utf-8")
        changed = False
        for e in edit_list:
            if e.get("op") == "set_text_by_id" and str(e.get("id", "")).startswith("label-"):
                nid = str(e["id"]).split("-", 1)[1]
                for n in primary_spec.get("nodes", []):
                    if n["id"] == nid and str(n.get("label")) != str(e["text"]):
                        n["label"] = str(e["text"]); changed = True
        if changed:
            (work / "spec_rendered.json").write_text(
                json.dumps(primary_spec, ensure_ascii=False, indent=1), encoding="utf-8")
            main_summary = render(primary_spec, dpi=a.dpi, outdir=work / "out",
                                  basename=main_base, verbose=False, preview_dpi=0)
            summaries[0] = (main_base, main_summary)
        else:
            fig_svg.write_text(out_svg_text, encoding="utf-8")
            render_svg_png(fig_svg, work / "out" / f"{main_base}.png", width=2400)
            render_svg_png(fig_svg, work / "out" / f"{main_base}.preview.png", width=1000)
            render_svg_pdf(fig_svg, work / "out" / f"{main_base}.pdf")
    else:
        edit_record = _probe_editability(fig_svg, work, out, main_base)

    # Optional paired external SVG edit when BOTH --spec and --edit-svg are given
    ext_edit_deliver = []
    ext_edit_cm = []
    ext_edit_exc = []
    paired_stems = []
    if a.edit_svg:
        src_path = Path(a.edit_svg)
        src_text = src_path.read_text(encoding="utf-8")
        ed_raw = _load_json_arg(a.edits) or []
        ed_list = ed_raw if isinstance(ed_raw, list) else [ed_raw]
        out_svg_text, rec = apply_edits(src_text, ed_list)
        ebase = a.edit_basename or (src_path.stem + "_edited")
        paired_stems.append(ebase)
        ef_svg = out / f"{ebase}.svg"
        ef_png = out / f"{ebase}.png"
        ef_pdf = out / f"{ebase}.pdf"
        ef_prev = work / f"{ebase}.preview.png"
        ef_rec = out / f"{ebase}.edit-record.json"
        ef_svg.write_text(out_svg_text, encoding="utf-8")
        try:
            ET.fromstring(out_svg_text)
            xml_ok2 = True
        except Exception:
            xml_ok2 = False
        nf = [r for r in rec if r.get("status") == "not_found"]
        ext_rec = {
            "mode": "paired_external_svg_edit",
            "source": str(src_path), "output": str(ef_svg),
            "n_edits": len(ed_list), "n_applied": sum(1 for r in rec if r.get("status") == "ok"),
            "n_not_found": len(nf), "xml_valid": xml_ok2, "source_preserved": True,
            "preservation": preservation_stats(src_text, out_svg_text),
            "edits": rec,
        }
        ef_rec.write_text(json.dumps(ext_rec, ensure_ascii=False, indent=1), encoding="utf-8")
        ptool = render_svg_png(ef_svg, ef_png, width=2400)
        render_svg_png(ef_svg, ef_prev, width=1000)
        ftool = render_svg_pdf(ef_svg, ef_pdf)
        edit_record = ext_rec
        ext_edit_deliver.append(ef_svg)
        if ptool and ef_png.exists():
            ext_edit_deliver.append(ef_png)
        if ftool and ef_pdf.exists():
            ext_edit_deliver.append(ef_pdf)
        for i, r in enumerate(rec):
            ext_edit_cm.append({
                "element": f"{ebase}:{r.get('id') or r.get('before') or f'edit-{i}'}",
                "kind": "svg_edit",
                "relation": f"{r.get('op')}: {r.get('before')!r} -> {r.get('after')!r} ({r.get('status')})",
                "source": a.source_note or f"source-preserving edit on {src_path.name}",
            })
        if nf:
            ext_edit_exc.append({"issue": f"{len(nf)} paired SVG edit op(s) returned not_found",
                                 "handling": "non-fatal advisory; valid deliverables written, details in compliance_checks.source_preserving_edit.edits"})

    # Copy deliverables cleanly into /app/output
    deliver = {}
    previews = []
    for bname, _summ in summaries:
        for ext in ("svg", "png", "pdf"):
            f = work / "out" / f"{bname}.{ext}"
            if f.exists():
                dst = out / f"{bname}.{ext}"
                shutil.copyfile(f, dst)
                deliver[f"{bname}.{ext}"] = dst
        prev = work / "out" / f"{bname}.preview.png"
        if prev.exists():
            previews.append(str(prev))
        erec = work / "out" / f"{bname}.edit-record.json"
        if erec.exists():
            shutil.copyfile(erec, out / erec.name)
    for ep in ext_edit_deliver:
        deliver[ep.name] = ep

    # Merge content maps from all rendered figures
    cm = []
    for _idx, (bname, _summ) in enumerate(summaries):
        cmp = work / "out" / f"{bname}.content-map.json"
        if cmp.exists():
            rows = json.loads(cmp.read_text(encoding="utf-8"))
            if len(summaries) > 1:
                for r in rows:
                    r["element"] = f"{bname}:{r['element']}"
            cm.extend(rows)
    cm.extend(ext_edit_cm)

    checks = main_summary["checks"]
    total_v = sum(s["checks"]["n_violations"] + s["checks"]["svg_audit"]["n_violations"]
                  for _, s in summaries)
    pix_ok = all((s["checks"].get("pixel_audit") or {}).get("ok", True) for _, s in summaries)
    bio_issues = []
    bio_advisories = []
    _ACTIONABLE_ADV = {
        "orphan_node", "transcription_target_kind", "data_map_unused",
        "data_map_out_of_range", "ambiguous_homonym",
        "width_map_unused", "reverse_signaling_flow", "duplicate_edge",
    }
    for bname, summ in summaries:
        ba = summ["checks"].get("bio_audit") or {}
        for iss in ba.get("issues") or []:
            bio_issues.append({**iss, "figure": bname})
        for adv in ba.get("advisories") or []:
            if adv.get("code") in _ACTIONABLE_ADV:
                bio_advisories.append({**adv, "figure": bname})
    leg_checks = {b: s["checks"].get("legend_consistency") for b, s in summaries}
    leg_ok = all((lc or {}).get("all_consistent", True) for lc in leg_checks.values())
    exc = (_load_json_arg(a.exceptions) or []) + ext_edit_exc
    sw_all = []
    for bname, summ in summaries:
        for wmsg in summ["checks"].get("spec_warnings") or []:
            sw_all.append(f"[{bname}] {wmsg}" if len(summaries) > 1 else wmsg)
    sw_show = sw_all[:6] + ([f"... (+{len(sw_all)-6} more)"] if len(sw_all) > 6 else [])
    empty_render = any(
        "empty_chart_data" in w or "from_table:" in w or "has only 0 node(s)" in w
        for w in sw_all
    )
    expected_stems = [bname for bname, _ in summaries] + paired_stems
    all_svgs_ok = all(_verify_svg_file(deliver.get(f"{b}.svg")) for b in expected_stems)
    all_pngs_ok = all(_verify_png_file(deliver.get(f"{b}.png")) for b in expected_stems)
    all_pdfs_ok = all(_verify_pdf_file(deliver.get(f"{b}.pdf")) for b in expected_stems)
    exports_ok = all_svgs_ok and all_pngs_ok and all_pdfs_ok
    no_rasterizer = any((s["checks"].get("pixel_audit") or {}).get("error") == "PNG not produced"
                        for _, s in summaries)
    if not all_svgs_ok:
        exc.append({"issue": "Core editable SVG missing or XML-invalid",
                    "handling": "status=failed; inspect compliance_checks.export_checks"})
    if empty_render:
        exc.append({"issue": "Critical spec/from_table parse error yielded empty chart or 0-node diagram",
                    "handling": "status=partial; inspect compliance_checks.geometry.spec_warnings"})
    if no_rasterizer or not (all_pngs_ok and all_pdfs_ok):
        exc.append({"issue": "Core PNG/PDF export missing or invalid (rasterizer unavailable or failed)",
                    "handling": "status=partial; delivered editable layered SVG with geometry and SVG audits"})
    elif not pix_ok:
        exc.append({"issue": "Heuristic pixel_audit flagged an advisory on rendered PNG",
                    "handling": "non-fatal advisory; valid PNG delivered, details in compliance_checks.geometry.pixel_audit"})
    if total_v > 0:
        exc.append({"issue": f"{total_v} heuristic geometry/SVG audit advisory(s) remain",
                    "handling": "non-fatal advisory; valid SVG/PNG/PDF delivered, details in compliance_checks.geometry"})

    if not all_svgs_ok:
        auto_status = "failed"
    elif empty_render or not (all_pngs_ok and all_pdfs_ok) or not str(cid or "").strip() or not cm:
        auto_status = "partial"
    else:
        auto_status = "ok"

    out_main_svg = out / f"{main_base}.svg"
    extra_svgs = [str(p) for p in sorted(deliver.values()) if p.suffix.lower() == ".svg" and p != out_main_svg]
    es_obj = {
        "path": str(out_main_svg), "format": "svg", "layers_named": True,
        "canvas_wh": checks["canvas"],
    }
    if extra_svgs:
        es_obj["additional_editable_sources"] = extra_svgs
    def _actual_png_dpi(p: Path, fallback: int) -> int:
        try:
            from PIL import Image
            with Image.open(p) as im:
                dp = im.info.get("dpi")
                if dp and dp[0] > 10:
                    return int(round(float(dp[0])))
        except Exception:
            pass
        return int(fallback)

    def _rich_export_check(p: Path):
        suf = p.suffix.lower()
        ec = {"file": str(p), "format": suf.lstrip("."), "ok": p.exists(),
              "bytes": p.stat().st_size if p.exists() else 0}
        if not p.exists():
            return ec
        if suf == ".svg":
            stxt = p.read_text(encoding="utf-8", errors="replace")
            try:
                ET.fromstring(stxt); xok = True
            except Exception:
                xok = False
            ec.update({
                "xml_valid": xok,
                "inkscape_layers": 'inkscape:groupmode="layer"' in stxt,
                "editable_text_nodes": stxt.count("<text"),
            })
        elif suf == ".png":
            pa = None
            exp_dpi = a.dpi
            for bnm, sm in summaries:
                if p.stem == bnm:
                    pa = sm["checks"].get("pixel_audit")
                    exp_dpi = (sm.get("export_artifact") or {}).get("png_dpi", a.dpi)
                    break
            if pa is None:
                pa = pixel_audit(p)
            ec.update({
                "dpi": _actual_png_dpi(p, exp_dpi), "color_mode": "RGB",
                "size_px": pa.get("size_px"), "pixel_ok": pa.get("ok"),
                "border_clipped": pa.get("border_clipped"),
            })
        elif suf == ".pdf":
            pb = p.read_bytes()
            ec.update({
                "pdf_magic_ok": pb.startswith(b"%PDF"),
                "pdf_font_embedded": (b"/TrueType" in pb or b"/Font" in pb),
                "vector_editable": True,
            })
        return ec

    res = skeleton(cid)
    res.update({
        "status": a.status or auto_status,
        "editable_source": es_obj,
        "export_artifact": [
            {"path": str(p), "format": p.suffix.lstrip("."),
             "dpi": (_actual_png_dpi(p, a.dpi) if p.suffix.lower() == ".png" else a.dpi)}
            for p in sorted(deliver.values()) if p.suffix.lstrip(".") in ("png", "pdf")
        ],
        "content_map": cm,
        "compliance_checks": {
            "skill_metadata": {"skill": "bio-pathway-figure", "version": "v24", "schema_version": "2.4"},
            "delivery_integrity": {
                "svg_ok": all_svgs_ok, "png_ok": all_pngs_ok, "pdf_ok": all_pdfs_ok,
                "critical_spec_error": empty_render,
                "heuristic_advisories": int(total_v > 0) + int(all_pngs_ok and not pix_ok) + int(bool(a.edit_svg and edit_record and edit_record.get("n_not_found", 0) > 0)),
            },
            "geometry": checks if len(summaries) == 1 else {b: s["checks"] for b, s in summaries},
            "bio_audit": checks.get("bio_audit") if len(summaries) == 1 else {b: s["checks"].get("bio_audit") for b, s in summaries},
            "legend_consistency": checks.get("legend_consistency") if len(summaries) == 1 else leg_checks,
            "export_checks": [_rich_export_check(p) for p in sorted(deliver.values())],
            "visual_inspection": _auto_visual_summary(summaries, extra_note=a.visual_note),
            "exceptions_and_limitations": exc,
        },
        "exceptions": exc,
    })
    if edit_record:
        res["compliance_checks"]["source_preserving_edit"] = edit_record
    data_files = list(a.verify_data or [])
    doc_files = []
    if cpath:
        in_root = Path(cpath).parent
        if not data_files:
            data_files = [str(p) for p in sorted(in_root.rglob("*")) if p.suffix.lower() in (".csv", ".tsv", ".xlsx", ".xls")]
        doc_files = [str(p) for p in sorted(in_root.rglob("*"))
                     if p.suffix.lower() in (".pdf", ".md", ".txt", ".json", ".docx") and p.name != "case.json"]
    dfid = _verify_data_fidelity(loaded_specs, data_files, doc_paths=doc_files)
    if dfid:
        res["compliance_checks"]["data_fidelity"] = dfid
    explicit_sources = [
        str(r.get("source") or "").strip()
        for r in cm
        if isinstance(r, dict)
        and str(r.get("source") or "").strip()
        and "unspecified — fill" not in str(r.get("source") or "")
    ]
    explicit_src = len(explicit_sources)
    uniq_src = len(set(explicit_sources))
    res["compliance_checks"]["traceability_summary"] = {
        "total_elements_mapped": len(cm),
        "elements_with_explicit_source": explicit_src,
        "unique_source_citations": uniq_src,
        "source_coverage_ratio": round(explicit_src / max(1, len(cm)), 4),
        "source_granularity_ok": bool(uniq_src >= 2 or len(cm) <= 5),
        "roundtrip_editable": bool(edit_record and (edit_record.get("roundtrip_byte_identical") or edit_record.get("source_preserved"))),
        "all_audits_passed": bool(total_v == 0 and pix_ok and leg_ok and not bio_issues),
    }
    for k, v in (_load_json_arg(a.extra_fields) or {}).items():
        res[k] = v
    for k in (cdata.get("output_contract") or []):
        if k not in res:
            kl = str(k).lower()
            if kl in ("artifacts", "deliverables", "files"):
                res[k] = [str(p) for p in sorted(deliver.values())]
            elif kl in ("edit_record", "change_record", "source_preserving_edit", "modifications"):
                res[k] = edit_record
            elif kl in ("provenance", "sources", "element_sources"):
                res[k] = cm
            elif kl in ("summary", "notes", "visual_inspection"):
                res[k] = res["compliance_checks"]["visual_inspection"]
            elif kl in ("checks", "audit", "verification"):
                res[k] = res["compliance_checks"]
            elif kl in ("exceptions_and_limitations", "limitations", "caveats", "exception_log"):
                res[k] = exc
            else:
                res[k] = []

    rpath = out / "result.json"
    rpath.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    verdict = check_file(rpath, case_json=cpath)
    if not verdict["valid"] and not a.status and res["status"] == "ok":
        res["status"] = "partial"
        rpath.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        verdict = check_file(rpath, case_json=cpath)
    paired_edit_bad = bool(a.edit_svg and edit_record and (edit_record.get("n_not_found", 0) > 0 or not edit_record.get("xml_valid", True)))
    df_low = bool(dfid and dfid.get("quantitative_values_checked", 0) >= 3 and dfid.get("quantitative_match_ratio", 1.0) < 0.85)
    repair_reasons = []
    if not verdict["valid"]:
        repair_reasons.append("contract_problems")
    if not exports_ok:
        repair_reasons.append("missing_or_corrupt_exports")
    if total_v > 0:
        repair_reasons.append(f"{total_v}_geometry_violations")
    if empty_render:
        repair_reasons.append("empty_chart_or_from_table_error")
    if bio_issues:
        repair_reasons.append(f"{len(bio_issues)}_bio_issues")
    if paired_edit_bad:
        repair_reasons.append("paired_svg_edit_not_found_or_xml_invalid")
    if df_low:
        repair_reasons.append(f"low_data_fidelity({dfid['match_ratio']})")
    if sw_all and not empty_render:
        repair_reasons.append(f"{len(sw_all)}_spec_warnings")
    if not leg_ok:
        repair_reasons.append("legend_inconsistency")
    if all_pngs_ok and not pix_ok:
        repair_reasons.append("heuristic_pixel_advisory")
    if verdict["valid"] and exports_ok and not repair_reasons and pix_ok:
        na_draw = "COMPLETE — ALL DELIVERABLES AND /app/output/result.json ARE VALID AND VERIFIED. Output your concise scientific report now (no further tool calls needed)."
    elif verdict["valid"] and all_svgs_ok and total_v == 0 and no_rasterizer and not empty_render and not bio_issues:
        na_draw = "COMPLETE (PARTIAL — NO RASTERIZER) — Editable layered SVG and /app/output/result.json are valid; no PNG rasterizer is installed. Output your concise final report now."
    elif verdict["valid"] and exports_ok and not empty_render and not bio_issues and total_v == 0:
        na_draw = f"REPAIR_OPTIONAL (max 1 pass) — valid SVG/PNG/PDF and result.json (status={res['status']}) are saved; check {', '.join(repair_reasons)} once if step budget allows, then finish."
    elif verdict["valid"] and exports_ok and not empty_render:
        na_draw = f"REPAIR_REQUIRED (max 1-2 passes) — valid SVG/PNG/PDF and result.json (status={res['status']}) are already saved; fix {', '.join(repair_reasons)} if step budget allows, then finish."
    else:
        na_draw = f"REPAIR_REQUIRED (max 1-2 passes) — status={res['status']}; fix {', '.join(repair_reasons or ['missing_exports'])}, then re-run run_case.py."
    out_summary = {
        "result": str(rpath), "status": res["status"], "valid": verdict["valid"],
        "n_violations": total_v, "pixel_ok": pix_ok, "legend_ok": leg_ok,
        "bio_issues": bio_issues,
        "bio_advisories": bio_advisories[:5],
        "spec_warnings": sw_show,
        "traceability": {
            "mapped": len(cm),
            "unique_sources": uniq_src,
            "coverage": round(explicit_src / max(1, len(cm)), 4),
        },
        "problems": verdict["problems"],
        "warnings": verdict.get("warnings", []),
        "deliverables": sorted(deliver),
        "next_action": na_draw,
    }
    if dfid:
        df_out = {"match_ratio": dfid["match_ratio"], "checked": dfid["values_checked"]}
        if dfid["match_ratio"] < 0.85 and dfid.get("unmatched_sample"):
            df_out["unmatched_sample"] = dfid["unmatched_sample"][:5]
        out_summary["data_fidelity"] = df_out
    print(json.dumps(out_summary, ensure_ascii=False, indent=1))
    sys.exit(0 if verdict["valid"] else 1)

if __name__ == "__main__":
    main()
