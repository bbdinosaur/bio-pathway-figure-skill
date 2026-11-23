#!/usr/bin/env python3
"""inspect_inputs.py — one-shot deterministic inspector for /input case bundles.

Reads case.json, task.md, workorders, CSV/TSV/JSON/XLSX tables, PDF text (with
multi-backend fallback, figure/table page index, and scanned-page detection),
and SVG layer/text/shape IDs in ONE fast call.

Usage:
  python3 inspect_inputs.py /input [--max-pdf-chars 28000] [--dump-dir /app/work/extracted]
"""
from __future__ import annotations
import argparse, csv, json, re, shutil, subprocess, sys, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

def _preview_csv(path: Path, delim: str, max_rows: int = 18, max_scan: int = 5000):
    try:
        cols, data = [], []
        n_total = 0
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            rdr = csv.reader(fh, delimiter=delim)
            for ri, row in enumerate(rdr):
                if ri == 0:
                    cols = row
                else:
                    n_total += 1
                    if len(data) < max_scan:
                        data.append(row)
        take = len(data) if n_total <= 25 else max_rows
        num_stats, cat_prev = _table_stats(cols, data)
        res_t = {
            "n_rows": n_total,
            "columns": cols,
            "numeric_stats": num_stats,
            "head": data[:take],
            "truncated": n_total > take,
        }
        if cat_prev:
            res_t["categorical_preview"] = cat_prev
        return res_t
    except Exception as e:
        return {"error": str(e)}

def _table_stats(cols, data):
    num_stats = {}
    cat_prev = {}
    for ci, cname in enumerate(cols):
        vals = []
        cats = []
        seen_c = set()
        for r in data:
            if ci < len(r):
                raw = str(r[ci]).strip()
                if not raw:
                    continue
                try:
                    vals.append(float(raw))
                except Exception:
                    if raw not in seen_c:
                        seen_c.add(raw)
                        if len(cats) < 6:
                            cats.append(raw[:40])
        if vals:
            num_stats[str(cname)] = {"n": len(vals), "min": min(vals), "max": max(vals)}
        elif cats and len(seen_c) <= max(12, len(data) // 2 + 2):
            cat_prev[str(cname)] = {"n_unique": len(seen_c), "sample": cats}
    return num_stats, cat_prev

def _read_xlsx_stdlib(path: Path, max_scan: int = 5000):
    """Pure-stdlib XLSX reader (sharedStrings + sheet XML) when openpyxl/pandas unavailable."""
    out = {}
    with zipfile.ZipFile(path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot.iter():
                if si.tag.split("}")[-1] == "si":
                    shared.append("".join(t.text or "" for t in si.iter() if t.tag.split("}")[-1] == "t"))
        sheet_names = {}
        if "xl/workbook.xml" in zf.namelist():
            wroot = ET.fromstring(zf.read("xl/workbook.xml"))
            idx = 1
            for sh in wroot.iter():
                if sh.tag.split("}")[-1] == "sheet":
                    sheet_names[f"xl/worksheets/sheet{idx}.xml"] = sh.attrib.get("name", f"Sheet{idx}")
                    idx += 1
        for nm in sorted(zf.namelist()):
            if not (nm.startswith("xl/worksheets/sheet") and nm.endswith(".xml")):
                continue
            root = ET.fromstring(zf.read(nm))
            rows = []
            for row_el in root.iter():
                if row_el.tag.split("}")[-1] != "row":
                    continue
                if len(rows) > max_scan:
                    break
                vals = []
                for c in row_el:
                    if c.tag.split("}")[-1] != "c":
                        continue
                    ct = c.attrib.get("t")
                    v_el = next((ch for ch in c if ch.tag.split("}")[-1] == "v"), None)
                    is_el = next((ch for ch in c if ch.tag.split("}")[-1] == "is"), None)
                    if ct == "s" and v_el is not None and v_el.text is not None:
                        idx_s = int(v_el.text)
                        vals.append(shared[idx_s] if 0 <= idx_s < len(shared) else "")
                    elif ct == "inlineStr" and is_el is not None:
                        vals.append("".join(is_el.itertext()))
                    elif v_el is not None and v_el.text is not None:
                        try:
                            fv = float(v_el.text)
                            vals.append(int(fv) if fv.is_integer() else fv)
                        except Exception:
                            vals.append(v_el.text)
                    else:
                        vals.append("")
                if any(str(v) != "" for v in vals):
                    rows.append(vals)
            out[sheet_names.get(nm, Path(nm).stem)] = rows
    return out

def _preview_xlsx(path: Path, max_rows: int = 18, max_scan: int = 5000):
    sheets_raw = None
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets_raw = {}
        for name in wb.sheetnames:
            ws = wb[name]
            rows = []
            for ri, row in enumerate(ws.iter_rows(values_only=True)):
                if ri > max_scan:
                    break
                vals = [("" if v is None else v) for v in row]
                if any(str(v) != "" for v in vals):
                    rows.append(vals)
            sheets_raw[name] = rows
        wb.close()
    except Exception:
        pass
    if sheets_raw is None:
        try:
            import pandas as pd
            xl = pd.ExcelFile(str(path))
            sheets_raw = {}
            for name in xl.sheet_names:
                df = xl.parse(name, nrows=max_scan)
                sheets_raw[name] = [list(df.columns)] + df.fillna("").values.tolist()
        except Exception:
            pass
    if sheets_raw is None:
        try:
            sheets_raw = _read_xlsx_stdlib(path, max_scan=max_scan)
        except Exception as e:
            return {"error": str(e)}
    out = {}
    for name, rows in sheets_raw.items():
        cols = rows[0] if rows else []
        data = rows[1:]
        take = len(data) if len(data) <= 25 else max_rows
        num_stats, cat_prev = _table_stats(cols, data)
        sh_obj = {
            "n_rows": len(data),
            "columns": cols,
            "numeric_stats": num_stats,
            "head": data[:take],
            "truncated": len(data) > take,
        }
        if cat_prev:
            sh_obj["categorical_preview"] = cat_prev
        out[name] = sh_obj
    return out

def _preview_docx(path: Path, max_chars: int = 12000):
    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            root = ET.fromstring(zf.read("word/document.xml"))
            paras = []
            for p in root.iter():
                if p.tag.split("}")[-1] == "p":
                    t = "".join(ch.text or "" for ch in p.iter() if ch.tag.split("}")[-1] == "t").strip()
                    if t:
                        paras.append(t)
            return "\n".join(paras)[:max_chars]
    except Exception as e:
        return f"[docx inspect error: {e}]"

def _preview_svg(path: Path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    info = {"bytes": len(txt.encode("utf-8")), "layers": [], "css_classes": {}, "texts": [], "shape_ids": []}
    for sm in re.finditer(r"<style[^>]*>(.*?)</style>", txt, re.S | re.I):
        for cm in re.finditer(r"(\.[A-Za-z0-9_-]+)\s*\{([^}]*)\}", sm.group(1)):
            if len(info["css_classes"]) < 40:
                info["css_classes"][cm.group(1)] = " ".join(cm.group(2).split())[:120]
    try:
        root = ET.fromstring(txt)
        info["width"] = root.attrib.get("width")
        info["height"] = root.attrib.get("height")
        info["viewBox"] = root.attrib.get("viewBox")
        def _walk(el, parent_g=None):
            tag = el.tag.split("}")[-1]
            eid = el.attrib.get("id")
            cur_g = parent_g
            if tag == "g" and eid:
                info["layers"].append(eid)
                cur_g = eid
            elif tag == "text":
                t = " ".join(s.strip() for s in el.itertext() if s and s.strip())
                if t:
                    tspans = [ch for ch in el if ch.tag.split("}")[-1] == "tspan"]
                    item = {"id": eid, "text": t}
                    if cur_g:
                        item["parent_g"] = cur_g
                    if tspans:
                        item["n_tspans"] = len(tspans)
                    for ak in ("x", "y", "font-size", "fill", "class"):
                        if el.attrib.get(ak) is not None:
                            item[ak] = el.attrib.get(ak)
                    info["texts"].append(item)
            elif tag in ("rect", "path", "circle", "ellipse", "polygon", "polyline", "line") and eid:
                if len(info["shape_ids"]) < 120:
                    item = {"tag": tag, "id": eid}
                    if cur_g:
                        item["parent_g"] = cur_g
                    for ak in ("x", "y", "cx", "cy", "fill", "stroke", "class"):
                        if el.attrib.get(ak) is not None:
                            item[ak] = el.attrib.get(ak)
                    info["shape_ids"].append(item)
            for ch in el:
                _walk(ch, cur_g)
        _walk(root, None)
    except Exception as e:
        info["parse_error"] = str(e)
    if not info["css_classes"]:
        info.pop("css_classes", None)
    return info

def _extract_pdf_pages(path: Path):
    """Extract list of page strings using pymupdf -> fitz -> pdfplumber -> pypdf -> pdftotext."""
    for mod in ("pymupdf", "fitz"):
        try:
            m = __import__(mod)
            doc = m.open(str(path))
            pages = [(p.get_text() or "").strip() for p in doc]
            doc.close()
            return pages, mod
        except Exception:
            continue
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return [((p.extract_text() or "").strip()) for p in pdf.pages], "pdfplumber"
    except Exception:
        pass
    for mod in ("pypdf", "PyPDF2"):
        try:
            m = __import__(mod)
            rdr = m.PdfReader(str(path))
            return [((p.extract_text() or "").strip()) for p in rdr.pages], mod
        except Exception:
            continue
    if shutil.which("pdftotext"):
        try:
            res = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True, timeout=30)
            pages = [pg.strip() for pg in res.stdout.split("\x0c")]
            if pages and not pages[-1]:
                pages = pages[:-1]
            return pages, "pdftotext"
        except Exception:
            pass
    return None, None

def _extract_target_refs(blob: str) -> list[str]:
    """Extract target Figure/Table numbers referenced in task.md / workorder (e.g. figure03 -> '3')."""
    refs = []
    for m in re.finditer(r"\b(?:fig(?:ure)?\.?\s*0*(\d+)|table\s*s?0*(\d+))\b", blob or "", re.I):
        num = m.group(1) or m.group(2)
        if num and num not in refs:
            refs.append(num)
    return refs[:8]

def _preview_pdf(path: Path, max_chars: int, dump_dir: Path | None = None, target_refs=None):
    pages_txt, backend = _extract_pdf_pages(path)
    if pages_txt is None:
        return {"warning": "No PDF text extractor available (pymupdf/fitz/pdfplumber/pypdf/pdftotext)"}
    pages = []
    empty_pages = []
    fig_index = {}
    total_chars = 0
    buf = []
    full_buf = []
    snippets = []
    snip_chars = 0
    captions = []
    cap_chars = 0
    t_snips = []
    t_chars = 0
    mech_snips = []
    mech_chars = 0
    t_pat = (re.compile(r"\b(?:Fig(?:ure)?\.?|Table\s*S?)\s*0*(?:" + "|".join(re.escape(r) for r in target_refs) + r")[A-Za-z]?\b", re.I)
             if target_refs else None)
    cap_pat = re.compile(r"\b(?:Fig(?:ure)?\.?\s*\d+[A-Za-z]?|Table\s*S?\d+|Extended\s+Data\s+Fig(?:ure)?\.?\s*\d+)\b", re.I)
    cap_start_pat = re.compile(r"(?:^|\n)\s*((?:Fig(?:ure)?\.?\s*\d+|Table\s*S?\d+|Extended\s+Data\s+Fig(?:ure)?\.?\s*\d+)\s*[\.:\|\-\u2013\u2014][^\n]{15,})", re.I)
    mech_pat = re.compile(r"(?:^|\n)\s*(?:[0-9]+\.?\s+)?(?:Results|Discussion|Mechanism|Working\s+model|Proposed\s+model|Pathway|Signaling|Conclusions?)\b[^\n]*", re.I)
    total_doc_chars = 0
    for i, t in enumerate(pages_txt):
        pno = i + 1
        total_doc_chars += len(t)
        if len(t) < 20:
            empty_pages.append(pno)
        head_ln = " ".join(t.strip().split())[:68]
        hits = list(cap_pat.finditer(t))
        page_tags = []
        for m in hits:
            key = re.sub(r"\s+", " ", m.group(0).strip())
            fig_index.setdefault(key, []).append(pno)
            if key not in page_tags and len(page_tags) < 4:
                page_tags.append(key)
        tag_str = f" [{', '.join(page_tags)}]" if page_tags else ""
        pages.append(f"p{pno} ({len(t)}c){tag_str}: {head_ln}")
        if t_pat and t_chars < 5500:
            seen_t = -999
            for tm in t_pat.finditer(t):
                if tm.start() - seen_t < 420:
                    continue
                seen_t = tm.start()
                s0 = max(0, tm.start() - 200)
                s1 = min(len(t), tm.end() + 850)
                twin = f"[p.{pno}] " + " ".join(t[s0:s1].split())
                if t_chars + len(twin) <= 5500:
                    t_snips.append(twin)
                    t_chars += len(twin)
        if cap_chars < 5500:
            for cm in cap_start_pat.finditer(t):
                c0 = cm.start(1)
                c1 = min(len(t), c0 + 820)
                cwin = f"[p.{pno}] " + " ".join(t[c0:c1].split())
                if cap_chars + len(cwin) <= 5500:
                    captions.append(cwin)
                    cap_chars += len(cwin)
        full_buf.append(f"=== PAGE {pno} ===\n{t}")
        if total_chars < max_chars and t:
            take = t[:max(0, max_chars - total_chars)]
            buf.append(f"=== PAGE {pno} ===\n{take}")
            total_chars += len(take)
        else:
            if hits and snip_chars < 5000:
                seen_pos = -999
                for m in hits:
                    if m.start() - seen_pos < 320:
                        continue
                    seen_pos = m.start()
                    s0 = max(0, m.start() - 120)
                    s1 = min(len(t), m.end() + 420)
                    win = f"[p.{pno}] " + " ".join(t[s0:s1].split())
                    if snip_chars + len(win) <= 5000:
                        snippets.append(win)
                        snip_chars += len(win)
            if mech_chars < 3200:
                for mm in mech_pat.finditer(t):
                    m0 = mm.start()
                    m1 = min(len(t), m0 + 620)
                    mwin = f"[p.{pno}] " + " ".join(t[m0:m1].split())
                    if mech_chars + len(mwin) <= 3200:
                        mech_snips.append(mwin)
                        mech_chars += len(mwin)
    dumped_to = None
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        out_txt = dump_dir / f"{path.stem}.txt"
        out_txt.write_text("\n\n".join(full_buf), encoding="utf-8")
        dumped_to = str(out_txt)
    is_trunc = total_doc_chars > max_chars
    res_pdf = {
        "backend": backend,
        "n_pages": len(pages),
        "page_index": pages[:35],
        "empty_or_scanned_pages": empty_pages,
        "scanned_warning": (len(empty_pages) == len(pages) and len(pages) > 0),
        "figure_table_pages": {k: sorted(set(v)) for k, v in sorted(fig_index.items())},
        "figure_captions": captions,
        "beyond_cutoff_fig_snippets": snippets,
        "full_text_file": dumped_to,
        "truncated": is_trunc,
        "text_excerpt": "\n\n".join(buf),
    }
    if t_snips:
        res_pdf["target_ref_snippets"] = t_snips
    if mech_snips:
        res_pdf["mechanism_section_snippets"] = mech_snips
    if is_trunc and dumped_to:
        res_pdf["slice_hint"] = f"Full page-indexed text saved at {dumped_to}; grep/slice relevant '=== PAGE N ===' sections if key mechanism/methods pages were beyond excerpt."
    return res_pdf

def inspect_dir(root: Path, max_pdf_chars: int = 28000, dump_dir: Path | None = None):
    files = sorted(p for p in root.rglob("*") if p.is_file())
    summary = {
        "root": str(root),
        "files": [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size} for p in files],
        "case": None,
        "task_md": None,
        "workorders": {},
        "tables": {},
        "svgs": {},
        "pdfs": {},
        "other_texts": {},
    }
    # Pass 1: read case.json, task.md, workorders first so PDF retrieval can prioritize target figures/tables
    for p in files:
        rel = str(p.relative_to(root))
        low = p.name.lower()
        suf = p.suffix.lower()
        try:
            if low == "case.json":
                summary["case"] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            elif low == "task.md":
                summary["task_md"] = p.read_text(encoding="utf-8", errors="replace")[:12000]
            elif "workorder" in low and suf == ".json":
                summary["workorders"][rel] = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            summary["other_texts"][rel] = f"[inspect error: {e}]"

    blob = (summary.get("task_md") or "") + " " + json.dumps(summary.get("workorders") or {}, ensure_ascii=False)
    target_refs = _extract_target_refs(blob)
    ref_images = []

    # Pass 2: inspect tables, SVGs, PDFs (with workorder-targeted retrieval), DOCX, and reference images
    for p in files:
        rel = str(p.relative_to(root))
        low = p.name.lower()
        suf = p.suffix.lower()
        if low in ("case.json", "task.md") or ("workorder" in low and suf == ".json"):
            continue
        try:
            if suf == ".csv":
                summary["tables"][rel] = _preview_csv(p, ",")
            elif suf == ".tsv":
                summary["tables"][rel] = _preview_csv(p, "\t")
            elif suf in (".xlsx", ".xls"):
                summary["tables"][rel] = _preview_xlsx(p)
            elif suf == ".svg":
                summary["svgs"][rel] = _preview_svg(p)
            elif suf == ".pdf":
                summary["pdfs"][rel] = _preview_pdf(p, max_pdf_chars, dump_dir=dump_dir, target_refs=target_refs)
            elif suf == ".docx":
                summary["other_texts"][rel] = _preview_docx(p)
            elif suf in (".png", ".jpg", ".jpeg", ".webp"):
                im_info = {"path": rel, "bytes": p.stat().st_size}
                try:
                    from PIL import Image
                    with Image.open(p) as im:
                        im_info["size_px"] = list(im.size)
                except Exception:
                    try:
                        hdr = p.read_bytes()[:24]
                        if hdr.startswith(b"\x89PNG") and len(hdr) >= 24:
                            im_info["size_px"] = [int.from_bytes(hdr[16:20], "big"), int.from_bytes(hdr[20:24], "big")]
                    except Exception:
                        pass
                ref_images.append(im_info)
            elif suf in (".json", ".md", ".txt", ".yaml", ".yml") and p.stat().st_size <= 96000:
                summary["other_texts"][rel] = p.read_text(encoding="utf-8", errors="replace")[:6000]
        except Exception as e:
            summary["other_texts"][rel] = f"[inspect error: {e}]"

    stems = sorted(set(re.findall(r"\b(figure\d+[a-z]?|fig_?\d+[a-z]?|pathway_?[a-z0-9_]*)\b", blob, re.I)))
    case = summary.get("case") or {}
    ex_svgs = [str(root / k) for k in summary["svgs"]]
    d_tabs = [str(root / k) for k in summary["tables"]]
    p_pdfs = [str(root / k) for k in summary["pdfs"]]
    b0 = stems[0] if stems else "figure01"
    if ex_svgs and not p_pdfs and not d_tabs:
        sug_cmd = f'python3 "$SK/scripts/run_case.py" --edit-svg {ex_svgs[0]} --edits /app/work/edits.json --basename {b0}_edited --source-note "workorder revision"'
    elif ex_svgs:
        sug_cmd = f'python3 "$SK/scripts/run_case.py" --spec /app/work/spec.json --basename {b0} --edit-svg {ex_svgs[0]} --edits /app/work/edits.json'
    else:
        sug_cmd = f'python3 "$SK/scripts/run_case.py" --spec /app/work/spec.json --basename {b0}'
    summary["action_hints"] = {
        "case_id": case.get("case_id"),
        "required_contract_fields": case.get("output_contract") or [],
        "suggested_basenames": stems[:8],
        "target_figure_table_refs": target_refs,
        "existing_svgs": ex_svgs,
        "data_tables": d_tabs,
        "pdfs": p_pdfs,
        "scanned_pdfs": [k for k, v in summary["pdfs"].items() if isinstance(v, dict) and v.get("scanned_warning")],
        "reference_images": ref_images,
        "suggested_command": sug_cmd,
    }
    return summary

def _init_output_contract(summary: dict, out_path: Path):
    """Write an immediate valid partial /app/output/result.json from inspected case.json."""
    case = summary.get("case") or {}
    case_id = str(case.get("case_id") or "UNKNOWN-CASE")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    skel = {
        "case_id": case_id,
        "status": "partial",
        "editable_source": None,
        "export_artifact": [],
        "content_map": [],
        "compliance_checks": {
            "geometry": None,
            "legend_consistency": None,
            "export_checks": [],
            "visual_inspection": "initialized at Step 1; awaiting render & pixel audit",
        },
        "exceptions": [{"issue": "initialized skeleton", "handling": "will be replaced by run_case.py"}],
    }
    for k in (case.get("output_contract") or []):
        if k not in skel:
            skel[k] = None
    out_path.write_text(json.dumps(skel, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out_path)

def _fit_stdout_budget(summary: dict, max_bytes: int = 48000) -> str:
    """Keep stdout <= max_bytes while SACREDLY protecting task_md, workorders, target_ref_snippets, captions & PDF excerpt."""
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 1: trim long other_texts first
    for k, v in list((summary.get("other_texts") or {}).items()):
        if isinstance(v, str) and len(v) > 2000:
            summary["other_texts"][k] = v[:2000] + "...[trimmed]"
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 2: trim raw table preview rows BEFORE touching PDF paper text (charts use from_table + columns/stats!)
    for row_cap in (10, 5):
        for tv in (summary.get("tables") or {}).values():
            if isinstance(tv, dict):
                if isinstance(tv.get("head"), list) and len(tv["head"]) > row_cap:
                    tv["head"] = tv["head"][:row_cap]
                    tv["truncated"] = True
                else:
                    for sh in tv.values():
                        if isinstance(sh, dict) and isinstance(sh.get("head"), list) and len(sh["head"]) > row_cap:
                            sh["head"] = sh["head"][:row_cap]
                            sh["truncated"] = True
        txt = json.dumps(summary, ensure_ascii=False, indent=1)
        if len(txt.encode("utf-8")) <= max_bytes:
            return txt
    # Pass 3: trim large SVG shape lists (preserving >=40 shapes + ALL texts, layers & css_classes)
    for sv in (summary.get("svgs") or {}).values():
        if isinstance(sv, dict) and isinstance(sv.get("shape_ids"), list) and len(sv["shape_ids"]) > 40:
            sv["shape_ids"] = sv["shape_ids"][:40]
            sv["shape_ids_truncated"] = True
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 4: compact page_index previews & secondary beyond-cutoff snippets before touching primary text_excerpt
    for pv in (summary.get("pdfs") or {}).values():
        if isinstance(pv, dict):
            if isinstance(pv.get("page_index"), list):
                pv["page_index"] = [s[:64] for s in pv["page_index"][:25]]
            if isinstance(pv.get("beyond_cutoff_fig_snippets"), list):
                pv["beyond_cutoff_fig_snippets"] = pv["beyond_cutoff_fig_snippets"][:4]
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 5 (last resort only): gently trim PDF text_excerpt while keeping rich core text
    for limit in (26000, 22000, 18000, 14000, 10000):
        for pv in (summary.get("pdfs") or {}).values():
            if isinstance(pv, dict) and isinstance(pv.get("text_excerpt"), str) and len(pv["text_excerpt"]) > limit:
                pv["text_excerpt"] = pv["text_excerpt"][:limit] + "\n...[trimmed for stdout; full text in full_text_file]"
                pv["truncated"] = True
        txt = json.dumps(summary, ensure_ascii=False, indent=1)
        if len(txt.encode("utf-8")) <= max_bytes:
            return txt
    return txt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", nargs="?", default="/input")
    ap.add_argument("--max-pdf-chars", type=int, default=28000)
    ap.add_argument("--max-stdout-bytes", type=int, default=48000)
    ap.add_argument("--dump-dir", default=None, help="optional dir to dump full page-indexed PDF text")
    ap.add_argument("--init-output", default=None,
                    help="if set (e.g. /app/output/result.json), immediately write a valid partial skeleton")
    a = ap.parse_args()
    root = Path(a.input_dir)
    if not root.exists():
        print(json.dumps({"error": f"input dir not found: {root}"}))
        sys.exit(1)
    dd = Path(a.dump_dir) if a.dump_dir else None
    summary = inspect_dir(root, a.max_pdf_chars, dump_dir=dd)
    if a.init_output:
        summary["initialized_result_json"] = _init_output_contract(summary, Path(a.init_output))
    print(_fit_stdout_budget(summary, max_bytes=a.max_stdout_bytes))

if __name__ == "__main__":
    main()
