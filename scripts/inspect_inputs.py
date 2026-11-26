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

def _preview_csv(path: Path, delim: str, max_rows: int = 45, max_scan: int = 5000):
    try:
        raw_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        banner_notes = []
        clean_lines = []
        for ln in raw_lines:
            s = ln.strip()
            if not s:
                continue
            if not clean_lines and s.startswith("#"):
                banner_notes.append(s.lstrip("#").strip()[:160])
                continue
            clean_lines.append(ln)
        first_ln = clean_lines[0] if clean_lines else ""
        if delim == "," and first_ln.count(";") >= 2 and first_ln.count(",") == 0:
            delim = ";"
        all_rows = list(csv.reader(clean_lines, delimiter=delim))
        h_idx, b_notes = _detect_header_row(all_rows)
        banner_notes.extend(b_notes)
        cols = [c.strip() for c in all_rows[h_idx]] if h_idx < len(all_rows) else []
        data_all = all_rows[h_idx + 1:] if h_idx < len(all_rows) else []
        n_total = len(data_all)
        data = data_all[:max_scan]
        take = len(data) if n_total <= 70 else max_rows
        num_stats, cat_prev = _table_stats(cols, data)
        res_t = {
            "n_rows": n_total,
            "columns": cols,
            "numeric_stats": num_stats,
            "head": data[:take],
            "truncated": n_total > take,
        }
        if banner_notes:
            res_t["banner_notes"] = banner_notes[:3]
        if cat_prev:
            res_t["categorical_preview"] = cat_prev
        return res_t
    except Exception as e:
        return {"error": str(e)}

def _parse_num_cell(raw: str):
    s = str(raw or "").strip()
    if not s or s.lower() in ("na", "nan", "none", "null", "-"):
        return None
    if "," in s and re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?", s):
        s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        fv = float(s)
        return None if (fv != fv) else fv
    except Exception:
        return None

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
                fv = _parse_num_cell(raw)
                if fv is not None:
                    vals.append(fv)
                else:
                    if raw not in seen_c:
                        seen_c.add(raw)
                        if len(cats) < 6:
                            cats.append(raw[:40])
        if vals:
            num_stats[str(cname)] = {
                "n": len(vals), "min": min(vals), "max": max(vals),
                "mean": round(sum(vals) / len(vals), 4),
            }
        elif cats and len(seen_c) <= max(12, len(data) // 2 + 2):
            cat_prev[str(cname)] = {"n_unique": len(seen_c), "sample": cats}
    return num_stats, cat_prev

def _xlsx_col_idx(ref: str) -> int | None:
    m = re.match(r"([A-Za-z]+)", str(ref or ""))
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1

def _read_xlsx_stdlib(path: Path, max_scan: int = 5000):
    """Pure-stdlib XLSX reader (sharedStrings + sparse-cell column alignment) when openpyxl unavailable."""
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
                    c_idx = _xlsx_col_idx(c.attrib.get("r"))
                    if c_idx is not None and c_idx > len(vals):
                        vals.extend([""] * (c_idx - len(vals)))
                    ct = c.attrib.get("t")
                    v_el = next((ch for ch in c if ch.tag.split("}")[-1] == "v"), None)
                    is_el = next((ch for ch in c if ch.tag.split("}")[-1] == "is"), None)
                    if ct == "s" and v_el is not None and v_el.text is not None:
                        idx_s = int(v_el.text)
                        val = shared[idx_s] if 0 <= idx_s < len(shared) else ""
                    elif ct == "inlineStr" and is_el is not None:
                        val = "".join(is_el.itertext())
                    elif v_el is not None and v_el.text is not None:
                        try:
                            fv = float(v_el.text)
                            val = int(fv) if fv.is_integer() else fv
                        except Exception:
                            val = v_el.text
                    else:
                        val = ""
                    if c_idx is not None and c_idx < len(vals):
                        vals[c_idx] = val
                    else:
                        vals.append(val)
                if any(str(v) != "" for v in vals):
                    rows.append(vals)
            out[sheet_names.get(nm, Path(nm).stem)] = rows
    return out

def _detect_header_row(rows: list) -> tuple[int, list[str]]:
    """Skip leading 1-cell title banners (e.g. 'Table S1. ...') in supplementary Excel sheets."""
    if not rows:
        return 0, []
    def _nonempty(r):
        return [c for c in r if str(c).strip() != ""]
    ne0 = _nonempty(rows[0])
    if len(ne0) <= 1 and len(rows) > 1:
        for i in range(1, min(8, len(rows))):
            nei = _nonempty(rows[i])
            if len(nei) >= 2:
                # Prefer a row with mostly string column labels
                n_str = sum(1 for c in nei if not isinstance(c, (int, float)))
                if n_str >= max(2, len(nei) // 2):
                    notes = [" ".join(str(x).strip() for x in _nonempty(r)) for r in rows[:i] if _nonempty(r)]
                    return i, notes
    return 0, []

def _preview_xlsx(path: Path, max_rows: int = 45, max_scan: int = 5000):
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
        h_idx, banner_notes = _detect_header_row(rows)
        cols = [str(c).strip() for c in rows[h_idx]] if h_idx < len(rows) else []
        data = rows[h_idx + 1:] if h_idx < len(rows) else []
        take = len(data) if len(data) <= 70 else max_rows
        num_stats, cat_prev = _table_stats(cols, data)
        sh_obj = {
            "n_rows": len(data),
            "columns": cols,
            "numeric_stats": num_stats,
            "head": data[:take],
            "truncated": len(data) > take,
        }
        if banner_notes:
            sh_obj["banner_notes"] = banner_notes[:3]
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
            body = next((el for el in root if el.tag.split("}")[-1] == "body"), root)
            blocks = []
            for ch in body:
                tag = ch.tag.split("}")[-1]
                if tag == "p":
                    t = "".join(x.text or "" for x in ch.iter() if x.tag.split("}")[-1] == "t").strip()
                    if t:
                        blocks.append(t)
                elif tag == "tbl":
                    for tr in ch:
                        if tr.tag.split("}")[-1] != "tr":
                            continue
                        cells = []
                        for tc in tr:
                            if tc.tag.split("}")[-1] != "tc":
                                continue
                            ct = " ".join(
                                "".join(x.text or "" for x in p.iter() if x.tag.split("}")[-1] == "t").strip()
                                for p in tc if p.tag.split("}")[-1] == "p"
                            ).strip()
                            cells.append(ct)
                        if any(cells):
                            blocks.append(" | ".join(cells))
            if not blocks:
                for p in root.iter():
                    if p.tag.split("}")[-1] == "p":
                        t = "".join(ch.text or "" for ch in p.iter() if ch.tag.split("}")[-1] == "t").strip()
                        if t:
                            blocks.append(t)
            return "\n".join(blocks)[:max_chars]
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
                ilbl = next((v for k, v in el.attrib.items() if k.endswith("}label") or k == "inkscape:label"), None)
                info["layers"].append(f"{eid} ({ilbl})" if (ilbl and ilbl != eid) else eid)
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
        try:
            _sd = str(Path(__file__).resolve().parent)
            if _sd not in sys.path:
                sys.path.insert(0, _sd)
            from render_preview import parse_svg_dimensions
            d = parse_svg_dimensions(txt)
            info["width"] = d["width_raw"]
            info["height"] = d["height_raw"]
            if d["viewbox"]:
                info["viewBox"] = " ".join(f"{x:g}" for x in d["viewbox"])
            if d["css_w"] > 0 and d["css_h"] > 0:
                info["css_size_px"] = [round(d["css_w"], 2), round(d["css_h"], 2)]
        except Exception:
            pass
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
    """Extract target Figure/Table numbers (EN & ZH, incl. Fig. S3 / Extended Data Fig. 3)."""
    refs = []
    pat = r"(?:\b(?:(?:extended\s+data\s+|supplementary\s+)?fig(?:ure)?\.?\s*s?0*(\d+)|(?:supplementary\s+)?table\s*s?0*(\d+))\b|(?:附图|附表|图|表)\s*S?0*(\d+))"
    for m in re.finditer(pat, blob or "", re.I):
        num = m.group(1) or m.group(2) or m.group(3)
        if num and num not in refs:
            refs.append(num)
    return refs[:8]

def _bound_caption_end(text: str, c0: int, max_len: int) -> int:
    """End a figure/table caption cleanly before the next Figure/Table/Section heading."""
    c1 = min(len(text), c0 + max_len)
    tail = text[c0 + 40:c1]
    nxt = re.search(
        r"\n\s*(?:(?:Extended\s+Data\s+|Supplementary\s+)?(?:Fig(?:ure)?\.?|Table)\s*S?\d+(?:\s*[\.:\|\-\u2013\u2014]|\s*\n)|(?:附图|附表|图|表)\s*S?\d+(?:\s*[\.:\|\-\u2013\u2014：]|\s*\n)|(?:References|Bibliography|Methods|Acknowledgements?)\b)",
        tail, re.I,
    )
    return (c0 + 40 + nxt.start()) if nxt else c1

def _preview_pdf(path: Path, max_chars: int, dump_dir: Path | None = None, target_refs=None, dump_name: str | None = None):
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
    target_captions = []
    tcap_chars = 0
    captions = []
    cap_chars = 0
    t_snips = []
    t_chars = 0
    mech_snips = []
    mech_chars = 0
    ref_alt = "|".join(re.escape(r) for r in (target_refs or []))
    t_pat = (re.compile(r"(?:\b(?:(?:Extended\s+Data\s+|Supplementary\s+)?Fig(?:ure)?\.?\s*S?|(?:Supplementary\s+)?Table\s*S?)|(?:附图|附表|图|表)\s*S?)\s*0*(?:" + ref_alt + r")[A-Za-z]?(?:\b|(?=\D|$))", re.I)
             if ref_alt else None)
    t_cap_pat = (re.compile(r"(?:^|\n)\s*((?:(?:(?:Extended\s+Data\s+|Supplementary\s+)?Fig(?:ure)?\.?\s*S?|(?:Supplementary\s+)?Table\s*S?)\s*0*(?:" + ref_alt + r")(?:\s*[\.:\|\-\u2013\u2014]\s*(?:\n\s*)?|\s*\n\s*)|(?:附图|附表|图|表)\s*S?0*(?:" + ref_alt + r")(?:\s*[\.:\|\-\u2013\u2014：]\s*(?:\n\s*)?|\s*\n\s*))[^\n]{8,})", re.I)
                 if ref_alt else None)
    cap_pat = re.compile(r"(?:\b(?:(?:Extended\s+Data\s+|Supplementary\s+)?Fig(?:ure)?\.?\s*S?\d+[A-Za-z]?|(?:Supplementary\s+)?Table\s*S?\d+)\b|(?:附图|附表|图|表)\s*S?\d+[A-Za-z]?)", re.I)
    cap_start_pat = re.compile(r"(?:^|\n)\s*((?:(?:(?:Extended\s+Data\s+|Supplementary\s+)?Fig(?:ure)?\.?\s*S?\d+|(?:Supplementary\s+)?Table\s*S?\d+)(?:\s*[\.:\|\-\u2013\u2014]\s*(?:\n\s*)?|\s*\n\s*)|(?:附图|附表|图|表)\s*S?\d+(?:\s*[\.:\|\-\u2013\u2014：]\s*(?:\n\s*)?|\s*\n\s*))[^\n]{10,})", re.I)
    mech_pat = re.compile(r"(?:^|\n)\s*(?:[0-9]+\.?\s+)?(?:Results|Discussion|Mechanism|Working\s+model|Proposed\s+model|Pathway|Signaling|Conclusions?)\b[^\n]*", re.I)
    ref_pat = re.compile(r"(?:^|\n)\s*(?:References|Bibliography|Acknowledgements?|Author\s+Contributions|参考文献)\s*(?:\n|$)", re.I)
    in_refs = False
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
        # Priority 1: Complete target Figure/Table captions (up to 2600 chars each, even after References!)
        if t_cap_pat and tcap_chars < 6000:
            for cm in t_cap_pat.finditer(t):
                c0 = cm.start(1)
                c1 = _bound_caption_end(t, c0, 2600)
                cwin = f"[p.{pno}] " + " ".join(t[c0:c1].split())
                if tcap_chars + len(cwin) <= 6000:
                    target_captions.append(cwin)
                    tcap_chars += len(cwin)
        # Priority 2: Target ref discussion snippets across Results/Discussion
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
        # Priority 3: General Figure/Table captions (excluding already-captured target captions)
        if cap_chars < 4800:
            for cm in cap_start_pat.finditer(t):
                c0 = cm.start(1)
                c1 = _bound_caption_end(t, c0, 950)
                cwin = f"[p.{pno}] " + " ".join(t[c0:c1].split())
                if any(cwin[:80] in tc for tc in target_captions):
                    continue
                if cap_chars + len(cwin) <= 4800:
                    captions.append(cwin)
                    cap_chars += len(cwin)
        full_buf.append(f"=== PAGE {pno} ===\n{t}")
        added_to_excerpt = False
        if pno >= 3 and not in_refs:
            rm = ref_pat.search(t)
            if rm:
                t_body = t[:rm.start()].strip()
                in_refs = True
                if total_chars < max_chars and t_body:
                    take = t_body[:max(0, max_chars - total_chars)]
                    buf.append(f"=== PAGE {pno} (pre-References) ===\n{take}")
                    total_chars += len(take)
                    added_to_excerpt = True
        if not added_to_excerpt and total_chars < max_chars and t and not in_refs:
            take = t[:max(0, max_chars - total_chars)]
            buf.append(f"=== PAGE {pno} ===\n{take}")
            total_chars += len(take)
            added_to_excerpt = True
        if not added_to_excerpt:
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
        out_txt = dump_dir / f"{dump_name or path.stem}.txt"
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
    if target_captions:
        res_pdf["target_figure_captions"] = target_captions
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
    # Pass 1: read case.json, task.md, workorders & brief docs first so PDF retrieval can prioritize target figures/tables
    brief_blobs = []
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
            elif suf in (".md", ".txt", ".yaml", ".yml") and p.stat().st_size <= 24000 and any(k in low for k in ("workorder", "brief", "instruction", "spec", "rubric", "prompt")):
                txt_b = p.read_text(encoding="utf-8", errors="replace")[:6000]
                summary["other_texts"][rel] = txt_b
                brief_blobs.append(txt_b)
        except Exception as e:
            summary["other_texts"][rel] = f"[inspect error: {e}]"

    blob = ((summary.get("task_md") or "") + " " + json.dumps(summary.get("workorders") or {}, ensure_ascii=False)
            + " " + " ".join(brief_blobs))
    target_refs = _extract_target_refs(blob)
    ref_images = []
    used_pdf_stems = set()

    # Pass 2: inspect tables, SVGs, PDFs (with workorder-targeted retrieval), DOCX, and reference images
    for p in files:
        rel = str(p.relative_to(root))
        low = p.name.lower()
        suf = p.suffix.lower()
        if low in ("case.json", "task.md") or ("workorder" in low and suf == ".json") or rel in summary["other_texts"]:
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
                dnm = p.stem if p.stem not in used_pdf_stems else re.sub(r"[^A-Za-z0-9_.-]+", "_", rel[:-4])
                used_pdf_stems.add(dnm)
                summary["pdfs"][rel] = _preview_pdf(p, max_pdf_chars, dump_dir=dump_dir, target_refs=target_refs, dump_name=dnm)
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

    stems = []
    for wo in (summary.get("workorders") or {}).values():
        if isinstance(wo, dict):
            for wk in ("output_basename", "basename", "figure_id", "target_figure", "target_file"):
                wv = wo.get(wk)
                if isinstance(wv, str) and wv.strip():
                    st = Path(wv.strip()).stem
                    if re.fullmatch(r"[A-Za-z][\w-]{1,40}", st) and st not in stems:
                        stems.append(st)
    for st in sorted(set(re.findall(r"\b(figure\d+[a-z]?|fig_?\d+[a-z]?|pathway_?[a-z0-9_]*)\b", blob, re.I))):
        if st not in stems:
            stems.append(st)
    in_stems = {p.stem.lower() for p in files}
    for m_fn in re.finditer(r"\b([A-Za-z][\w-]{2,40})\.(?:svg|png|pdf)\b", blob):
        st = m_fn.group(1)
        if st.lower() not in in_stems and st not in stems:
            stems.append(st)
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

def _fit_stdout_budget(summary: dict, max_bytes: int = 52000) -> str:
    """Keep stdout <= max_bytes while PROTECTING task_md, workorders, target_ref_snippets, captions, tables & PDF excerpt."""
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 1: trim long other_texts & compact large page_index lists first
    for k, v in list((summary.get("other_texts") or {}).items()):
        if isinstance(v, str) and len(v) > 2000:
            summary["other_texts"][k] = v[:2000] + "...[trimmed]"
    for pv in (summary.get("pdfs") or {}).values():
        if isinstance(pv, dict) and isinstance(pv.get("page_index"), list) and len(pv["page_index"]) > 28:
            pv["page_index"] = [s[:64] for s in pv["page_index"][:28]]
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 2: trim large SVG shape lists (keep >=50 shapes + ALL texts, layers & css_classes) & secondary snippets
    for sv in (summary.get("svgs") or {}).values():
        if isinstance(sv, dict) and isinstance(sv.get("shape_ids"), list) and len(sv["shape_ids"]) > 50:
            sv["shape_ids"] = sv["shape_ids"][:50]
            sv["shape_ids_truncated"] = True
    for pv in (summary.get("pdfs") or {}).values():
        if isinstance(pv, dict) and isinstance(pv.get("beyond_cutoff_fig_snippets"), list):
            pv["beyond_cutoff_fig_snippets"] = pv["beyond_cutoff_fig_snippets"][:5]
    txt = json.dumps(summary, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 3: gently trim PDF text_excerpt (target_ref_snippets, figure_captions, mechanism_section_snippets & full tables stay intact!)
    for limit in (24000, 20000, 16000, 12000):
        for pv in (summary.get("pdfs") or {}).values():
            if isinstance(pv, dict) and isinstance(pv.get("text_excerpt"), str) and len(pv["text_excerpt"]) > limit:
                pv["text_excerpt"] = pv["text_excerpt"][:limit] + "\n...[trimmed for stdout; full text in full_text_file]"
                pv["truncated"] = True
        txt = json.dumps(summary, ensure_ascii=False, indent=1)
        if len(txt.encode("utf-8")) <= max_bytes:
            return txt
    # Pass 4 (extreme last resort only): trim very large table previews while preserving >=20 rows (NEVER slash to 5!)
    for row_cap in (30, 20):
        for tv in (summary.get("tables") or {}).values():
            if isinstance(tv, dict):
                if isinstance(tv.get("head"), list) and len(tv["head"]) > row_cap:
                    tv["head"] = tv["head"][:row_cap]
                    tv["truncated"] = True
                    tv["table_truncation_hint"] = "Read full table directly or bind via chart.from_table"
                else:
                    for sh in tv.values():
                        if isinstance(sh, dict) and isinstance(sh.get("head"), list) and len(sh["head"]) > row_cap:
                            sh["head"] = sh["head"][:row_cap]
                            sh["truncated"] = True
                            sh["table_truncation_hint"] = "Read full table directly or bind via chart.from_table"
        txt = json.dumps(summary, ensure_ascii=False, indent=1)
        if len(txt.encode("utf-8")) <= max_bytes:
            return txt
    return txt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", nargs="?", default="/input")
    ap.add_argument("--max-pdf-chars", type=int, default=28000)
    ap.add_argument("--max-stdout-bytes", type=int, default=52000)
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
