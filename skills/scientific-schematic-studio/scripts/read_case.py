#!/usr/bin/env python3
"""read_case.py — one-shot input triage for /input (saves agent requests at S0).

Usage: python3 read_case.py [--input /input] [--out /app/work/case_brief.json]
Prints a compact brief: case_id, output_contract hints, materials inventory with
type sniffing (PDF pages + Fig/Table page index, CSV/TSV/XLSX columns + preview,
JSON keys, SVG viewBox/layers/texts, image dims). Never fails.
"""
import argparse, csv, json, os, re, subprocess, sys, zipfile
import xml.etree.ElementTree as ET

SNIP = 400


def _import_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def _sniff_pdf_poppler(path):
    """Zero-dependency fallback via pdfinfo + pdftotext (poppler-utils)."""
    out = {}
    try:
        r = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            m = re.search(r"^Pages:\s*(\d+)", r.stdout, re.MULTILINE)
            if m:
                out["pages"] = int(m.group(1))
    except Exception:
        pass
    try:
        n_pages = out.get("pages") or 40
        r = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(min(n_pages, 40)), path, "-"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout:
            pages_txt = r.stdout.split("\x0c")
            if pages_txt:
                out["text_sample"] = pages_txt[0][:SNIP].replace("\n", " ").strip()
            fig_pages = {}
            for pi, pt in enumerate(pages_txt[:40]):
                for m in re.findall(r'\b(?:Fig(?:ure)?\.?\s*\d+[A-Za-z]?|Table\s*\d+)\b', pt):
                    k = re.sub(r'\s+', ' ', m)
                    fig_pages.setdefault(k, []).append(pi + 1)
            if fig_pages:
                out["fig_table_pages"] = {k: sorted(set(v))[:5]
                                          for k, v in list(fig_pages.items())[:20]}
            out["pdf_reader"] = "poppler"
    except Exception as e:
        out["pdf_error"] = str(e)
    return out


def _xlsx_sheet_entries(zf):
    """Return list of (sheet_name, zip_member_path) in workbook order using stdlib only."""
    names = set(zf.namelist())
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        try:
            rroot = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rroot:
                rid = rel.get("Id")
                tgt = rel.get("Target", "").lstrip("/")
                if rid and tgt:
                    if not tgt.startswith("xl/"):
                        tgt = "xl/" + tgt
                    rels[rid] = tgt
        except Exception:
            pass
    entries = []
    if "xl/workbook.xml" in names:
        try:
            wroot = ET.fromstring(zf.read("xl/workbook.xml"))
            for sh in wroot.iter():
                if sh.tag.endswith("}sheet"):
                    sname = sh.get("name", "Sheet")
                    rid = None
                    for k, v in sh.attrib.items():
                        if k.endswith("}id") or k == "id":
                            rid = v
                            break
                    tgt = rels.get(rid)
                    if tgt and tgt in names:
                        entries.append((sname, tgt))
        except Exception:
            pass
    if not entries:
        for i, m in enumerate(sorted(n for n in names
                                     if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))):
            entries.append(("Sheet%d" % (i + 1), m))
    return entries


def _col_ref_to_idx(ref):
    """Convert Excel cell coordinate like 'C5' or 'AA12' to 0-based column index."""
    if not ref:
        return None
    m = re.match(r"^\s*([A-Za-z]+)", str(ref))
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _cell_ref_to_rc(ref):
    """Convert Excel cell coordinate like 'C5' to (0-based row, 0-based col)."""
    if not ref:
        return None
    m = re.match(r"^\s*([A-Za-z]+)(\d+)\s*$", str(ref))
    if not m:
        return None
    return int(m.group(2)) - 1, _col_ref_to_idx(m.group(1))


def _read_xlsx_sheet_rows(zf, member, shared, max_rows=30):
    sroot = ET.fromstring(zf.read(member))
    # Collect horizontal merged headers (B2:D2) AND vertical group-label merges (A2:A4)
    h_merges, v_merges = [], []
    for mc in sroot.iter():
        if mc.tag.endswith("}mergeCell") and mc.get("ref") and ":" in mc.get("ref"):
            a_ref, b_ref = mc.get("ref").split(":", 1)
            rc0, rc1 = _cell_ref_to_rc(a_ref), _cell_ref_to_rc(b_ref)
            if rc0 and rc1:
                if rc0[0] == rc1[0] and rc1[1] > rc0[1]:
                    h_merges.append((rc0[0], rc0[1], rc1[1]))
                elif rc0[1] == rc1[1] and rc1[0] > rc0[0] and rc0[1] <= 2:
                    v_merges.append((rc0[1], rc0[0], rc1[0]))
    rows_by_r = {}
    row_order = []
    for row in sroot.iter():
        if not row.tag.endswith("}row"):
            continue
        r_attr = row.get("r")
        r_idx = (int(r_attr) - 1) if (r_attr and r_attr.isdigit()) else len(row_order)
        vals = []
        for c in row:
            if not c.tag.endswith("}c"):
                continue
            cidx = _col_ref_to_idx(c.get("r"))
            if cidx is None:
                cidx = len(vals)
            if cidx >= len(vals):
                vals.extend([""] * (cidx - len(vals) + 1))
            t = c.get("t", "")
            v_el = next((ch for ch in c if ch.tag.endswith("}v")), None)
            is_el = next((ch for ch in c if ch.tag.endswith("}is")), None)
            if t == "s" and v_el is not None and v_el.text is not None:
                idx = int(v_el.text)
                val = shared[idx] if 0 <= idx < len(shared) else ""
            elif t == "inlineStr" and is_el is not None:
                val = "".join(x.text or "" for x in is_el.iter() if x.tag.endswith("}t"))
            elif t == "b" and v_el is not None and v_el.text is not None:
                val = "TRUE" if v_el.text.strip() == "1" else "FALSE"
            elif v_el is not None and v_el.text is not None:
                val = v_el.text
            else:
                val = ""
            vals[cidx] = val
        if any(v != "" for v in vals):
            rows_by_r[r_idx] = vals
            row_order.append(r_idx)
            if max_rows and len(row_order) >= max_rows:
                break
    # Propagate non-numeric horizontal merged headers across spanned empty cells
    for r_i, c0, c1 in h_merges:
        rv = rows_by_r.get(r_i)
        if not rv or c0 >= len(rv) or not str(rv[c0]).strip():
            continue
        txt = str(rv[c0]).strip()
        try:
            float(txt.replace(",", ""))
            continue  # do not duplicate numeric values
        except ValueError:
            pass
        if c1 >= len(rv):
            rv.extend([""] * (c1 - len(rv) + 1))
        for ci in range(c0 + 1, c1 + 1):
            if not str(rv[ci]).strip():
                rv[ci] = txt
    # Propagate non-numeric vertical merged group/condition labels (e.g. A2:A4 = "WT" in replicate tables)
    for c_i, r0, r1 in v_merges:
        rv0 = rows_by_r.get(r0)
        if not rv0 or c_i >= len(rv0) or not str(rv0[c_i]).strip():
            continue
        txt = str(rv0[c_i]).strip()
        try:
            float(txt.replace(",", ""))
            continue
        except ValueError:
            pass
        for r_cur in range(r0 + 1, r1 + 1):
            rv_cur = rows_by_r.get(r_cur)
            if rv_cur is None:
                continue
            if c_i >= len(rv_cur):
                rv_cur.extend([""] * (c_i - len(rv_cur) + 1))
            if not str(rv_cur[c_i]).strip():
                rv_cur[c_i] = txt
    return [rows_by_r[r_i] for r_i in row_order]


def _sniff_xlsx(path):
    info = {"type": "xlsx"}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            shared = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.iter():
                    if si.tag.endswith("}si"):
                        shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
            entries = _xlsx_sheet_entries(zf)
            info["n_sheets"] = len(entries)
            info["sheet_names"] = [nm for nm, _ in entries[:20]]
            sheets_summary = []
            for sname, member in entries[:10]:
                rows = _read_xlsx_sheet_rows(zf, member, shared, max_rows=200)
                if rows:
                    sheets_summary.append({
                        "name": sname,
                        "columns": rows[0][:15],
                        "rows": len(rows) - 1,
                        "preview_rows": rows[1:3],
                    })
            if sheets_summary:
                info["columns"] = sheets_summary[0]["columns"]
                info["rows"] = sheets_summary[0]["rows"]
                info["preview_rows"] = sheets_summary[0]["preview_rows"]
                if len(sheets_summary) > 1:
                    info["sheets"] = sheets_summary
            info["sheet_names"] = [sn for sn, _ in entries]
    except Exception as e:
        info["error"] = str(e)
    return info


def _extract_docx_text(path, max_chars=24000):
    """Zero-dependency .docx paragraph & table extractor via stdlib zipfile+xml."""
    parts = []
    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        root = ET.fromstring(zf.read("word/document.xml"))
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "p":
                txt = "".join(t.text or "" for t in el.iter() if t.tag.endswith("}t")).strip()
                if txt:
                    parts.append(txt)
    return "\n".join(parts)[:max_chars]


def _extract_pptx_text(path, max_chars=24000):
    """Zero-dependency .pptx slide text extractor via stdlib zipfile+xml."""
    parts = []
    with zipfile.ZipFile(path, "r") as zf:
        slides = sorted(
            (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda s: int(re.search(r"(\d+)\.xml$", s).group(1)),
        )
        for idx, smem in enumerate(slides, 1):
            root = ET.fromstring(zf.read(smem))
            texts = [t.text.strip() for t in root.iter() if t.tag.endswith("}t") and t.text and t.text.strip()]
            if texts:
                parts.append("--- SLIDE %d ---\n%s" % (idx, " | ".join(texts)))
    return "\n\n".join(parts)[:max_chars]


def sniff(path):
    info = {"path": path, "bytes": os.path.getsize(path)}
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        info.update(_sniff_xlsx(path))
        return info
    if ext == ".docx":
        info["type"] = "docx"
        try:
            txt = _extract_docx_text(path, max_chars=4000)
            info["chars"] = len(txt)
            info["text_sample"] = txt[:SNIP].replace("\n", " ")
        except Exception as e:
            info["error"] = str(e)
        return info
    if ext == ".pptx":
        info["type"] = "pptx"
        try:
            txt = _extract_pptx_text(path, max_chars=4000)
            info["slides_detected"] = txt.count("--- SLIDE ")
            info["text_sample"] = txt[:SNIP].replace("\n", " ")
        except Exception as e:
            info["error"] = str(e)
        return info
    try:
        head = open(path, "rb").read(4096)
    except Exception as e:
        info["error"] = str(e)
        return info

    if head.startswith(b"%PDF"):
        info["type"] = "pdf"
        try:
            pymupdf = _import_pymupdf()
            doc = pymupdf.open(path)
            info["pages"] = doc.page_count
            info["text_sample"] = doc[0].get_text()[:SNIP].replace("\n", " ")
            fig_pages = {}
            for pi in range(min(doc.page_count, 40)):
                pt = doc[pi].get_text()
                for m in re.findall(r'\b(?:Fig(?:ure)?\.?\s*\d+[A-Za-z]?|Table\s*\d+)\b', pt):
                    k = re.sub(r'\s+', ' ', m)
                    fig_pages.setdefault(k, []).append(pi + 1)
            if fig_pages:
                info["fig_table_pages"] = {k: sorted(set(v))[:5]
                                           for k, v in list(fig_pages.items())[:20]}
            doc.close()
        except Exception:
            info.update(_sniff_pdf_poppler(path))
    elif ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        info["type"] = "image"
        try:
            from PIL import Image
            im = Image.open(path)
            info["dims"] = list(im.size)
        except Exception:
            pass
        try:
            r = subprocess.run(["tesseract", path, "stdout", "--psm", "11"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                toks = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
                if toks:
                    info["ocr_text"] = " | ".join(toks)[:1200]
        except Exception:
            pass
    elif ext == ".svg" or head.lstrip()[:4] in (b"<?xm", b"<svg"):
        info["type"] = "svg"
        try:
            root = ET.parse(path).getroot()
            info["viewBox"] = root.get("viewBox")
            gids = [el.get("id") for el in root.iter() if el.tag.endswith("}g") and el.get("id")]
            txts = ["".join(el.itertext()).strip() for el in root.iter() if el.tag.endswith("}text")]
            info["n_groups"] = len(gids)
            info["groups_sample"] = gids[:15]
            info["texts_sample"] = [t[:40] for t in txts if t][:15]
        except Exception as e:
            info["svg_error"] = str(e)
    elif ext in (".csv", ".tsv"):
        info["type"] = "table"
        try:
            delim = "\t" if ext == ".tsv" else ","
            with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
                rows = list(csv.reader(f, delimiter=delim))
            if rows:
                info["columns"] = [c.strip() for c in rows[0][:25]]
                info["rows"] = len(rows) - 1
                info["preview_rows"] = rows[1:4]
        except Exception as e:
            info["error"] = str(e)
    elif ext == ".json":
        info["type"] = "json"
        try:
            d = json.load(open(path, encoding="utf-8"))
            info["keys"] = list(d.keys())[:25] if isinstance(d, dict) else "list[%d]" % len(d)
        except Exception as e:
            info["error"] = str(e)
    else:
        info["type"] = "text"
        try:
            info["text_sample"] = head.decode("utf-8", "ignore")[:SNIP]
        except Exception:
            pass
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/input")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    brief = {"input_dir": a.input, "warnings": [], "materials": []}
    cj = os.path.join(a.input, "case.json")
    if os.path.exists(cj):
        try:
            case = json.load(open(cj, encoding="utf-8"))
            brief["case_id"] = case.get("case_id") or case.get("id") or "unknown"
            brief["case_keys"] = list(case.keys())
            for k in ("task", "task_text", "description", "instruction", "prompt"):
                if isinstance(case.get(k), str):
                    brief["task_text"] = case[k][:16000]
                    break
            for k in ("output_contract", "output_schema", "required_fields"):
                if case.get(k):
                    brief["output_contract"] = case[k]
                    break
            for k in ("materials", "files", "sources", "attachments", "inputs"):
                v = case.get(k)
                if isinstance(v, list):
                    brief["material_refs"] = v
                    break
                elif isinstance(v, dict):
                    brief["material_refs"] = v
                    break
            # Preserve all additional constraint/requirement fields in case.json without loss
            skip_k = {"case_id", "id", "task", "task_text", "description", "instruction",
                      "prompt", "output_contract", "output_schema", "required_fields",
                      "materials", "files", "sources", "attachments", "inputs"}
            extra = {}
            for k, v in case.items():
                if k not in skip_k and v not in (None, "", [], {}):
                    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                    extra[k] = v if len(s) <= 2000 else (s[:2000] + "...[truncated]")
            if extra:
                brief["case_extra"] = extra
        except Exception as e:
            brief["warnings"].append("case.json parse: %s" % e)
    else:
        brief["warnings"].append("case.json not found at %s" % cj)
    tmd = os.path.join(a.input, "task.md")
    if os.path.exists(tmd):
        brief["task_md_chars"] = os.path.getsize(tmd)
        brief["task_md_head"] = open(tmd, encoding="utf-8", errors="ignore").read(16000)

    files = []
    for root, dirs, fs in os.walk(a.input):
        for f in fs:
            files.append(os.path.join(root, f))
    for p in sorted(files)[:50]:
        if os.path.basename(p) in ("case.json", "task.md"):
            continue
        brief["materials"].append(sniff(p))

    lines = [
        "== case brief ==",
        "case_id: %s" % brief.get("case_id", "?"),
        "task: %s" % (brief.get("task_text", "?")[:300].replace("\n", " "),),
    ]
    if brief.get("output_contract"):
        lines.append("output_contract: %s" % json.dumps(brief["output_contract"], ensure_ascii=False)[:300])
    for m in brief["materials"]:
        t = m.get("type")
        if t == "pdf":
            extra = "pages=%s figs=%s" % (m.get("pages"), list((m.get("fig_table_pages") or {}).keys())[:6])
        elif t == "xlsx":
            extra = "sheets=%s rows=%s cols=%s" % (
                m.get("sheet_names", [])[:5], m.get("rows"), m.get("columns", [])[:6])
        elif t == "table":
            extra = "rows=%s cols=%s" % (m.get("rows"), m.get("columns", [])[:8])
        elif t == "svg":
            extra = "viewBox=%s groups=%s texts=%s" % (m.get("viewBox"), m.get("n_groups"), len(m.get("texts_sample", [])))
        elif t == "image":
            extra = "dims=%s" % m.get("dims")
        else:
            extra = str(t)
        lines.append("  [%s] %s (%s)" % (t, m["path"], extra))
    for w in brief["warnings"]:
        lines.append("WARN: %s" % w)
    print("\n".join(lines))
    if a.out:
        d = os.path.dirname(a.out)
        if d:
            os.makedirs(d, exist_ok=True)
        json.dump(brief, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("brief -> %s" % a.out)


if __name__ == "__main__":
    main()
