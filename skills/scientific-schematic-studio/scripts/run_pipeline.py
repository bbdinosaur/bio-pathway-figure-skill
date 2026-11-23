#!/usr/bin/env python3
"""run_pipeline.py — 2-step turnkey pipeline for scientific schematic generation & editing.

Commands:
  1) prepare:
     python3 run_pipeline.py prepare [--input /input] [--work /app/work] [--out /app/output]
     Inspects /input (case.json, task.md, PDFs, CSV/TSV/XLSX, SVGs, images), dumps usable
     text/table/SVG excerpts, writes /app/work/case_brief.json + /app/work/pdf_extract.txt,
     and immediately emits an honest partial /app/output/result.json safety net.

  2) deliver:
     python3 run_pipeline.py deliver /app/work/plan.json [--input /input] [--work /app/work] [--out /app/output]
     Accepts a single plan.json (generate spec OR edit_svg + ops, plus optional inventories/notes/
     output_contract fields), runs build_figure or edit_svg -> audit_figure -> export_check ->
     optional build_pptx -> make_result, and prints a pure-text geometry & compliance digest
     (for text-only models; no binary PNG read required). Always exits 0 after writing result.json.
"""
import argparse, csv, datetime, hashlib, json, math, os, re, subprocess, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import read_case as RC

SPEC_ONLY_KEYS = {
    "canvas", "panels", "style", "units_ok", "footnote", "preset", "post_edit_ops",
    "mode", "edit_svg", "ops", "stem", "dpi", "tiff",
    "pptx", "pptx_title", "pptx_subtitle", "case_id", "task_type", "probe",
}


def _run_py(script_name, args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-B", os.path.join(SCRIPT_DIR, script_name)] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=240)
    return r.returncode, r.stdout, r.stderr


def _extract_pdf_text(path, max_pages=60):
    try:
        pymupdf = RC._import_pymupdf()
        doc = pymupdf.open(path)
        n_pg = min(doc.page_count, max_pages)
        page_texts = [doc[pi].get_text().strip() for pi in range(n_pg)]
        doc.close()
        # Selective pdfplumber table extraction ONLY on pages mentioning Table / tabular numbers (fast on dense PDFs!)
        plumber_tables = {}
        cand_pages = [
            pi for pi, t in enumerate(page_texts)
            if t and (re.search(r'\bTable\s*\d', t, re.I) or len(re.findall(r'\d+\.\d+\s*±', t)) >= 2)
        ][:8]
        if cand_pages:
            try:
                import pdfplumber
                with pdfplumber.open(path) as ppdf:
                    for pi in cand_pages:
                        if pi >= len(ppdf.pages):
                            continue
                        tbls = ppdf.pages[pi].extract_tables() or []
                        out_t = []
                        for ti, rows in enumerate(tbls[:3], 1):
                            clean_rows = []
                            for r in (rows or [])[:24]:
                                cells = [re.sub(r"\s+", " ", str(c or "")).strip()[:36] for c in r[:12]]
                                if any(cells):
                                    clean_rows.append(" | ".join(cells))
                            if len(clean_rows) >= 2:
                                out_t.append("[TABLE p.%d.%d]\n" % (pi + 1, ti) + "\n".join(clean_rows))
                        if out_t:
                            plumber_tables[pi] = "\n\n".join(out_t)
            except Exception:
                pass
        chunks = []
        for pi, txt in enumerate(page_texts):
            t_blk = plumber_tables.get(pi, "")
            if txt or t_blk:
                body = txt + ("\n\n" + t_blk if t_blk else "")
                chunks.append("--- PAGE %d ---\n%s" % (pi + 1, body.strip()))
        res_txt = "\n\n".join(chunks)
        if len(res_txt.strip()) >= 80:
            return res_txt
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), path, "-"],
            capture_output=True, text=True, timeout=45)
        if r.returncode == 0 and r.stdout:
            pages = r.stdout.split("\x0c")
            chunks = []
            for pi, txt in enumerate(pages[:max_pages]):
                t = txt.strip()
                if t:
                    chunks.append("--- PAGE %d ---\n%s" % (pi + 1, t))
            res_txt = "\n\n".join(chunks)
            if len(res_txt.strip()) >= 80:
                return res_txt
    except Exception:
        pass
    # Scanned/image-only PDF OCR fallback (triggers ONLY when text extraction yields <80 chars)
    import shutil, tempfile
    if shutil.which("pdftoppm") and shutil.which("tesseract"):
        try:
            with tempfile.TemporaryDirectory(prefix="pdfocr_") as td:
                pref = os.path.join(td, "pg")
                subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "6", path, pref],
                               capture_output=True, timeout=45)
                imgs = sorted(f for f in os.listdir(td) if f.endswith(".png"))
                ocr_chunks = []
                for idx_i, imf in enumerate(imgs, 1):
                    ro = subprocess.run(["tesseract", os.path.join(td, imf), "stdout"],
                                        capture_output=True, text=True, timeout=25)
                    ot = (ro.stdout or "").strip()
                    if ot:
                        ocr_chunks.append("--- PAGE %d (OCR) ---\n%s" % (idx_i, ot))
                if ocr_chunks:
                    return "\n\n".join(ocr_chunks)
        except Exception:
            pass
    return ""


def _col_idx_to_letter(idx):
    s = ""
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _read_table_preview(path, max_rows=28, task_hint="", full_dump_out=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        import zipfile, xml.etree.ElementTree as ET
        lines = []
        dump_lines = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                shared = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in root.iter():
                        if si.tag.endswith("}si"):
                            shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")))
                entries = RC._xlsx_sheet_entries(zf)
                # Prioritize sheets matching target Fig/Table numbers mentioned in task_hint
                t_nums = set(re.findall(r'(?:fig(?:ure)?|table|panel)\s*0*(\d+[a-z]?)', task_hint or "", re.I))
                t_nums |= set(re.findall(r'0*(\d+)', " ".join(t_nums)))
                def _sheet_score(item):
                    sn = item[0].lower()
                    sc = 0
                    for tn in t_nums:
                        if re.search(r'(?:fig|f|panel|tab|s)?0*%s(?:\b|[a-z])' % re.escape(tn.lower()), sn):
                            sc += 10
                    return -sc
                ordered = sorted(entries, key=_sheet_score)
                for idx, (sname, mem) in enumerate(ordered):
                    lim = max_rows if idx < 8 else 3
                    all_rows = RC._read_xlsx_sheet_rows(zf, mem, shared, max_rows=300)
                    # Write full untruncated sheet to table_extract.txt if requested
                    if full_dump_out is not None:
                        dump_lines.append("=== SHEET: %s (rows=%d) ===" % (sname, len(all_rows)))
                        mc_all = min(max((len(r) for r in all_rows), default=0), 26)
                        if mc_all:
                            dump_lines.append("COLS: " + " | ".join(_col_idx_to_letter(ci) for ci in range(mc_all)))
                        for ri_d, rd in enumerate(all_rows, 1):
                            dump_lines.append("R%d: " % ri_d + " | ".join(str(c)[:36] for c in rd[:mc_all]))
                    # Detect stacked sub-table headers beyond row `lim` (e.g. Fig. 3b / Fig. 3c in tall sheets!)
                    def _is_num_row(rv):
                        hits = 0
                        for c in rv:
                            s0 = str(c).strip().replace(",", "").rstrip("%")
                            try:
                                float(s0); hits += 1
                            except Exception:
                                pass
                        return hits >= 1
                    subtables = []
                    prev_was_num = False
                    for ri_s, rs in enumerate(all_rows):
                        non_e = [str(c).strip() for c in rs if str(c).strip()]
                        is_n = _is_num_row(rs)
                        has_fig_tag = bool(non_e and re.search(r'\b(?:fig(?:ure)?\.?\s*\d|panel\s*[a-z]|table\s*\d)', " ".join(non_e[:3]), re.I))
                        if (ri_s == 0 or (prev_was_num and not is_n) or (has_fig_tag and not is_n)) and non_e:
                            subtables.append((ri_s, non_e[0][:40]))
                        prev_was_num = is_n
                    rows = all_rows[:lim]
                    more = ("+%d" % (len(all_rows) - lim)) if len(all_rows) > lim else ""
                    max_cols = min(max((len(r) for r in rows), default=0), 16)
                    lines.append("  [sheet=%s rows=%d shown=%d%s]" % (sname, len(all_rows), len(rows), more))
                    if len(subtables) >= 2 and len(all_rows) > lim:
                        st_str = " | ".join("R%d:%r" % (ri_s + 1, lbl) for ri_s, lbl in subtables[:10])
                        lines.append("    SUBTABLES: " + st_str)
                    if max_cols:
                        hdr_cols = " | ".join(_col_idx_to_letter(ci) for ci in range(max_cols))
                        lines.append("    COLS: " + hdr_cols)
                    for r in rows:
                        # Trim trailing empty cells per row to keep preview compact
                        tr = list(r[:max_cols])
                        while tr and not str(tr[-1]).strip():
                            tr.pop()
                        lines.append("    " + " | ".join(str(c)[:34] for c in tr))
                    # Also preview up to 4 rows of each stacked sub-table located PAST `lim`!
                    if len(all_rows) > lim and idx < 4:
                        extra_sts = [(ri_s, lbl) for ri_s, lbl in subtables if ri_s >= lim][:4]
                        for ri_s, lbl in extra_sts:
                            lines.append("    --- stacked subtable @ R%d (%s) ---" % (ri_s + 1, lbl))
                            for r_ex in all_rows[ri_s:ri_s + 5]:
                                tr = list(r_ex[:max_cols])
                                while tr and not str(tr[-1]).strip():
                                    tr.pop()
                                lines.append("      " + " | ".join(str(c)[:34] for c in tr))
        except Exception as e:
            lines.append("  xlsx read error: %s" % e)
        if full_dump_out is not None and dump_lines:
            full_dump_out.append("=== XLSX: %s ===\n%s" % (path, "\n".join(dump_lines)))
        return "\n".join(lines)
    else:
        delim = "\t" if ext == ".tsv" else ","
        lines = []
        dump_lines = []
        try:
            with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
                all_rows = [r for i, r in enumerate(csv.reader(f, delimiter=delim)) if i < 300 and any(c.strip() for c in r)]
            if full_dump_out is not None and all_rows:
                mc_all = min(max((len(r) for r in all_rows), default=0), 26)
                if mc_all:
                    dump_lines.append("COLS: " + " | ".join(_col_idx_to_letter(ci) for ci in range(mc_all)))
                for ri_d, rd in enumerate(all_rows, 1):
                    dump_lines.append("R%d: " % ri_d + " | ".join(str(c).strip()[:36] for c in rd[:mc_all]))
                full_dump_out.append("=== TABLE: %s (rows=%d) ===\n%s" % (path, len(all_rows), "\n".join(dump_lines)))
            max_cols = min(max((len(r) for r in all_rows[:max_rows]), default=0), 16)
            if max_cols:
                lines.append("    COLS: " + " | ".join(_col_idx_to_letter(ci) for ci in range(max_cols)))
            for r in all_rows[:max_rows]:
                tr = [c.strip()[:34] for c in r[:max_cols]]
                while tr and not tr[-1]:
                    tr.pop()
                lines.append("    " + " | ".join(tr))
            # Detect stacked subtables past max_rows (common in SourceData CSVs)
            if len(all_rows) > max_rows:
                extra_sts = []
                for ri_s in range(max_rows, len(all_rows)):
                    non_e = [c.strip() for c in all_rows[ri_s] if c.strip()]
                    if non_e and re.search(r'\b(?:fig(?:ure)?\.?\s*\d|panel\s*[a-z]|table\s*\d)', " ".join(non_e[:3]), re.I):
                        extra_sts.append((ri_s, " | ".join(non_e[:3])[:60]))
                for ri_s, lbl in extra_sts[:4]:
                    lines.append("    --- stacked subtable @ R%d (%s) ---" % (ri_s + 1, lbl))
                    for r_ex in all_rows[ri_s:ri_s + 5]:
                        lines.append("      " + " | ".join(c.strip()[:34] for c in r_ex[:max_cols]))
        except Exception as e:
            lines.append("  table read error: %s" % e)
        return "\n".join(lines)


def _extract_target_pdf_excerpts(full_txt, task_hint, budget=6500):
    """Find PDF pages matching target Fig/Table mentions & captions; return (page_index, excerpts)."""
    all_lines = full_txt.splitlines()
    page_spans = []
    cur_file, cur_pno, cur_start = "", None, 0
    seen_files = set()
    for li, ln in enumerate(all_lines):
        s_ln = ln.strip()
        mf = re.match(r"^=== FILE:\s*(.+?)\s*===$", s_ln)
        if mf:
            if cur_pno is not None:
                page_spans.append((cur_file, cur_pno, cur_start + 1, li, "\n".join(all_lines[cur_start:li])))
                cur_pno = None
            cur_file = os.path.basename(mf.group(1).strip())
            seen_files.add(cur_file)
            continue
        m = re.match(r"^--- PAGE (\d+) ---$", s_ln)
        if m:
            if cur_pno is not None:
                page_spans.append((cur_file, cur_pno, cur_start + 1, li, "\n".join(all_lines[cur_start:li])))
            cur_pno, cur_start = int(m.group(1)), li
    if cur_pno is not None:
        page_spans.append((cur_file, cur_pno, cur_start + 1, len(all_lines), "\n".join(all_lines[cur_start:])))
    if not page_spans:
        return [], full_txt[:budget]
    multi_pdf = len(seen_files) > 1
    targets = set()
    for m in re.finditer(r'\b(?:fig(?:ure)?\.?\s*0*(\d+)|table\.?\s*0*(\d+))\b', task_hint or "", re.I):
        if m.group(1):
            targets.add(("fig", m.group(1)))
        if m.group(2):
            targets.add(("tab", m.group(2)))
    want_ext_data = bool(re.search(r'extended\s+data|supplementary|supp\.', task_hint or "", re.I))
    page_idx = []
    span_by_key = {}
    scored = []
    for ftag, pno, l0, l1, block in page_spans:
        pkey = (ftag, pno)
        span_by_key[pkey] = (l0, l1)
        ptag = ("%s p.%d" % (ftag, pno)) if (multi_pdf and ftag) else ("p.%d" % pno)
        body = "\n".join(block.splitlines()[1:])
        first_line = next((x.strip()[:65] for x in body.splitlines() if x.strip()), "")
        figs_here = sorted(set(re.findall(
            r'\b(?:Extended Data Fig\.?\s*\d+[A-Za-z]?|Fig(?:ure)?\.?\s*\d+[A-Za-z]?|Table\s*\d+)\b',
            body)))[:5]
        page_idx.append("%s[L%d-%d]: %s %s" % (ptag, l0, l1, figs_here if figs_here else "", first_line))
        score = 0
        for kind, num in targets:
            if kind == "fig":
                # Main Fig. N caption strictly outranks Extended Data Fig. N unless Extended Data was requested
                has_main_cap = bool(re.search(
                    r'(?:^|\n)\s*Fig(?:ure)?\.?\s*0*%s(?:\s*[\|\.\:\-]|[A-Za-z]\b)' % re.escape(num), body, re.I))
                has_ext_cap = bool(re.search(
                    r'(?:^|\n)\s*Extended Data\s+Fig(?:ure)?\.?\s*0*%s(?:\s*[\|\.\:\-]|[A-Za-z]\b)' % re.escape(num), body, re.I))
                if has_main_cap:
                    score += 30
                elif has_ext_cap:
                    score += (30 if want_ext_data else 15)
                elif re.search(r'\bFig(?:ure)?\.?\s*0*%s\b' % re.escape(num), body, re.I):
                    score += 12
            if kind == "tab":
                if re.search(r'(?:^|\n)\s*Table\s*0*%s(?:\s*[\|\.\:\-])' % re.escape(num), body, re.I):
                    score += 30
                elif re.search(r'\bTable\s*0*%s\b' % re.escape(num), body, re.I):
                    score += 12
        if not targets and figs_here:
            score += 4
        if re.search(r'\b(?:mechanism|pathway|model|schematic|signaling|inhibit|activat|translocat)\b', body, re.I):
            score += 2
        if pno == 1:
            score += 2
        scored.append((score, ftag, pno, block))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    chosen = []
    # 1) Pin full verbatim matching Figure/Table captions (allows blank lines inside multi-panel captions a-g!)
    caps = []
    if targets:
        for sc, ftag, pno, blk in scored:
            if sc < 15:
                continue
            ptag = ("%s p.%d" % (ftag, pno)) if (multi_pdf and ftag) else ("p.%d" % pno)
            blk_lines = blk.splitlines()
            for kind, num in sorted(targets):
                start_re = (
                    re.compile(r'^\s*(?:Extended Data\s+)?Fig(?:ure)?\.?\s*0*%s(?:\s*[\|\.\:\-]|[A-Za-z]\b)' % re.escape(num), re.I)
                    if kind == "fig" else
                    re.compile(r'^\s*Table\s*0*%s(?:\s*[\|\.\:\-])' % re.escape(num), re.I)
                )
                stop_re = re.compile(
                    r'^\s*(?:(?:Extended Data\s+)?Fig(?:ure)?\.?\s*\d+(?:\s*[\|\.\:\-])|Table\s*\d+(?:\s*[\|\.\:\-])|Methods\b|References\b|Reporting summary\b|Acknowledgements\b|Data availability\b|--- PAGE )',
                    re.I,
                )
                for li_c, ln_c in enumerate(blk_lines):
                    if not start_re.match(ln_c):
                        continue
                    buf = [ln_c.strip()]
                    blank_run = 0
                    for ln_next in blk_lines[li_c + 1:li_c + 64]:
                        if stop_re.match(ln_next):
                            break
                        if not ln_next.strip():
                            blank_run += 1
                            if blank_run >= 2:
                                break
                            continue
                        blank_run = 0
                        buf.append(ln_next.strip())
                        if sum(len(x) + 1 for x in buf) >= 4000:
                            break
                    cblk = "[%s CAPTION] %s" % (ptag, "\n".join(buf)[:4000])
                    if cblk not in caps:
                        caps.append(cblk)
        if caps:
            chosen.append("=== TARGET CAPTIONS (VERBATIM) ===\n" + "\n\n".join(caps[:2])[:4500])

    # 2) Guaranteed coherent full paper pages (full `budget` chars)
    used_pages = 0
    included_keys = set()
    for sc, ftag, pno, blk in scored:
        if used_pages >= budget:
            break
        hdr = ("[%s]\n" % ftag) if (multi_pdf and ftag) else ""
        take = (hdr + blk)[:max(1200, budget - used_pages)]
        chosen.append(take)
        used_pages += len(take)
        included_keys.add((ftag, pno))

    # 3) Compact cross-page in-text Results mentions ONLY from pages NOT already printed above + exact read hints
    if targets:
        mentions = []
        unread_hints = []
        for sc, ftag, pno, blk in scored:
            pkey = (ftag, pno)
            if sc < 12 or pkey in included_keys:
                continue
            ptag = ("%s p.%d" % (ftag, pno)) if (multi_pdf and ftag) else ("p.%d" % pno)
            l0, l1 = span_by_key.get(pkey, (1, 1))
            unread_hints.append("%s[L%d-%d]" % (ptag, l0, l1))
            for kind, num in sorted(targets):
                mpat = (r'[^\n]{0,140}\bFig(?:ure)?\.?\s*0*%s[a-z]?(?:[\s,\)\]\.\-;][^\n]{0,180})'
                        if kind == "fig" else
                        r'[^\n]{0,140}\bTable\s*0*%s(?:[\s,\)\]\.\-;][^\n]{0,180})') % re.escape(num)
                for mm in re.finditer(mpat, blk, re.I):
                    snip = re.sub(r"\s+", " ", mm.group(0)).strip()
                    if len(snip) > 25:
                        entry = "[%s] %s" % (ptag, snip[:260])
                        if entry not in mentions:
                            mentions.append(entry)
        if mentions:
            chosen.append("=== CROSS-PAGE RESULTS MENTIONS ===\n" + "\n".join(mentions[:12])[:2200])
        if unread_hints:
            chosen.append("[PDF_READ_HINT] Additional pages mentioning target figure/table not printed in full: %s — use read(pdf_extract.txt, offset, limit) if any subpanel/molecule/value is missing." % ", ".join(unread_hints[:8]))
    return page_idx, "\n\n".join(chosen)


def _guess_stem(brief, task_type):
    txt = (brief.get("task_text", "") + " " + brief.get("task_md_head", ""))
    m_file = re.search(r'\b([A-Za-z0-9][A-Za-z0-9_\-]{2,40})\.svg\b', txt)
    if m_file:
        return m_file.group(1)
    m_fig = re.search(r'\b(figure\s*0*\d+|fig\s*0*\d+)\b', txt, re.I)
    if m_fig:
        return re.sub(r'\s+', '', m_fig.group(1).lower())
    if task_type == "edit":
        for m in brief.get("materials", []):
            if m.get("type") == "svg" and m.get("path"):
                return os.path.splitext(os.path.basename(m["path"]))[0] + "_edited"
    return "figure1"


def _guess_task_type(brief):
    txt = (brief.get("task_text", "") + " " + brief.get("task_md_head", "")).lower()
    has_svg = any(m.get("type") == "svg" for m in brief.get("materials", []))
    edit_words = ("edit", "modify", "revise", "update existing", "preserve", "修改", "编辑已有", "保源")
    if has_svg and any(w in txt for w in edit_words):
        return "edit"
    return "generate"


def cmd_prepare(a):
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    brief_path = os.path.join(a.work, "case_brief.json")
    _, out_rc, _ = _run_py("read_case.py", ["--input", a.input, "--out", brief_path])
    brief = json.load(open(brief_path, encoding="utf-8")) if os.path.exists(brief_path) else {}
    case_id = str(brief.get("case_id") or "unknown")
    task_type = _guess_task_type(brief)
    case_json_path = os.path.join(a.input, "case.json")

    # Dump full PDF text to /app/work/pdf_extract.txt for quick targeted reading
    mat_names = " ".join(os.path.basename(m.get("path", "")) for m in brief.get("materials", []))
    extra_hint = json.dumps(brief.get("case_extra") or {}, ensure_ascii=False)[:1000]
    task_hint_full = (brief.get("task_text", "") + " " + brief.get("task_md_head", "") + " " + extra_hint + " " + mat_names)
    pdf_dump_parts = []
    doc_dump_parts = []
    table_dump_parts = []
    svg_inspects = {}
    table_dumps = {}
    for m in brief.get("materials", []):
        p, t = m.get("path", ""), m.get("type")
        if t == "pdf":
            txt = _extract_pdf_text(p, max_pages=60)
            if txt:
                pdf_dump_parts.append("=== FILE: %s ===\n%s" % (p, txt))
        elif t == "docx":
            try:
                txt = RC._extract_docx_text(p)
                if txt:
                    doc_dump_parts.append("=== DOCX: %s ===\n%s" % (p, txt))
            except Exception:
                pass
        elif t == "pptx":
            try:
                txt = RC._extract_pptx_text(p)
                if txt:
                    doc_dump_parts.append("=== PPTX: %s ===\n%s" % (p, txt))
            except Exception:
                pass
        elif t == "svg":
            _, sout, _ = _run_py("edit_svg.py", [p, "--inspect"])
            try:
                svg_inspects[p] = json.loads(sout)
            except Exception:
                pass
        elif t in ("table", "xlsx"):
            table_dumps[p] = _read_table_preview(p, max_rows=28, task_hint=task_hint_full,
                                                 full_dump_out=table_dump_parts)

    pdf_extract_path = None
    if pdf_dump_parts:
        pdf_extract_path = os.path.join(a.work, "pdf_extract.txt")
        with open(pdf_extract_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(pdf_dump_parts))
    doc_extract_path = None
    if doc_dump_parts:
        doc_extract_path = os.path.join(a.work, "doc_extract.txt")
        with open(doc_extract_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(doc_dump_parts))
    table_extract_path = None
    if table_dump_parts:
        table_extract_path = os.path.join(a.work, "table_extract.txt")
        with open(table_extract_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(table_dump_parts))

    # Immediate honest partial result.json safety net
    init_man = {
        "deliverables": {"editable_source": None, "exports": []},
        "entity_inventory": [],
        "relation_inventory": [],
        "sources": [os.path.basename(m["path"]) for m in brief.get("materials", []) if m.get("path")],
        "uncertainty": [],
        "limits": ["Initial prepare scaffold; figure generation/editing pending deliver step."],
        "change_records": [{"step": "prepare", "what": "input triage and safety-net result.json", "why": "early partial persistence"}],
        "notes": "Prepared by run_pipeline.py prepare",
    }
    init_man_path = os.path.join(a.work, "manifest_init.json")
    json.dump(init_man, open(init_man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    mr_args = [
        "--case-id", case_id, "--task-type", task_type,
        "--manifest", init_man_path, "--status", "partial",
        "--out", os.path.join(a.out, "result.json"),
    ]
    if os.path.exists(case_json_path):
        mr_args += ["--case-json", case_json_path]
    _run_py("make_result.py", mr_args)

    # Print rich, compact pure-text digest for the agent (saves 3-5 tool calls!)
    suggested_stem = _guess_stem(brief, task_type)
    lines = [
        "== PREPARE BRIEF ==",
        "case_id: %s | suggested_task_type: %s | suggested_stem: %s" % (case_id, task_type, suggested_stem),
        "safety_net_result: %s (status=partial written)" % os.path.join(a.out, "result.json"),
    ]
    if brief.get("output_contract"):
        lines.append("output_contract: %s" % json.dumps(brief["output_contract"], ensure_ascii=False))
    if brief.get("case_extra"):
        lines.append("case_extra: %s" % json.dumps(brief["case_extra"], ensure_ascii=False)[:3000])
    if brief.get("task_text"):
        tt = brief["task_text"]
        lines.append("task_text:\n%s" % tt[:8000])
        if len(tt) > 8000:
            lines.append("  [TRUNCATED task_text — read %s for full content]" % case_json_path)
    if brief.get("task_md_head"):
        tm = brief["task_md_head"]
        lines.append("task_md (%d bytes):\n%s" % (brief.get("task_md_chars", len(tm)), tm[:8000]))
        if brief.get("task_md_chars", len(tm)) > 8000:
            lines.append("  [TRUNCATED task.md — read %s for full content]" % os.path.join(a.input, "task.md"))
    lines.append("materials (%d):" % len(brief.get("materials", [])))
    for m in brief.get("materials", []):
        p, t = m.get("path", ""), m.get("type")
        if t == "pdf":
            lines.append("  [pdf] %s (pages=%s, figs=%s)" % (
                p, m.get("pages"), m.get("fig_table_pages", {})))
        elif t == "xlsx":
            lines.append("  [xlsx] %s (sheets=%s)" % (p, m.get("sheet_names")))
            if p in table_dumps:
                lines.append(table_dumps[p])
        elif t == "table":
            lines.append("  [table] %s (rows=%s, cols=%s)" % (p, m.get("rows"), m.get("columns")))
            if p in table_dumps:
                lines.append(table_dumps[p])
        elif t == "svg":
            ins = svg_inspects.get(p, {})
            lines.append("  [svg] %s (viewBox=%s, groups=%d, shapes=%d, edges=%d, texts=%d)" % (
                p, ins.get("viewBox"), ins.get("n_groups_with_id", 0),
                len(ins.get("named_shapes", [])), len(ins.get("edges", [])), ins.get("n_texts", 0)))
            lines.append("    group_ids: %s" % ins.get("groups", [])[:40])
            if ins.get("node_boxes"):
                lines.append("    node_boxes: %s" % [
                    "%s@%s" % (nb.get("label", "?")[:28], nb.get("bbox"))
                    for nb in ins.get("node_boxes", [])[:30]])
            if ins.get("named_shapes"):
                lines.append("    named_shapes: %s" % ins.get("named_shapes", [])[:30])
            if ins.get("edges"):
                lines.append("    edges: %s" % [
                    "#%d(%s) %s->%s [%s] %s->%s mk=%s" % (
                        ed.get("edge_idx", 0), ed.get("id") or ed.get("group_id") or "unnamed",
                        ed.get("from_label") or "?", ed.get("to_label") or "?",
                        ed.get("inferred_kind") or "edge",
                        ed.get("p0"), ed.get("p1"), ed.get("marker_end"))
                    for ed in ins.get("edges", [])[:28]])
            lines.append("    texts: %s" % [
                "%s@(%s,%s):%s" % (tx.get("group_id") or tx.get("id") or "?",
                                   tx.get("x") or "?", tx.get("y") or "?", tx.get("text", "")[:40])
                for tx in ins.get("texts", [])[:40]])
        elif t == "image":
            lines.append("  [image] %s (dims=%s)" % (p, m.get("dims")))
            if m.get("ocr_text"):
                lines.append("    ocr_text: %s" % m["ocr_text"][:900])
        elif t in ("docx", "pptx"):
            lines.append("  [%s] %s (%d bytes)" % (t, p, m.get("bytes", 0)))
            if m.get("text_sample"):
                lines.append("    sample: %s" % m["text_sample"][:600])
        else:
            lines.append("  [%s] %s (%d bytes)" % (t, p, m.get("bytes", 0)))
            try:
                raw_t = open(p, encoding="utf-8", errors="ignore").read(6000)
                if raw_t.strip():
                    lines.append("    content:\n%s" % raw_t)
                    if m.get("bytes", 0) > 6000:
                        lines.append("    [TRUNCATED — read %s for full content]" % p)
            except Exception:
                if m.get("text_sample"):
                    lines.append("    sample: %s" % m["text_sample"][:600].replace("\n", " "))
    if doc_extract_path:
        dtxt = open(doc_extract_path, encoding="utf-8").read()
        lines.append("doc_extract: %s (%d chars)" % (doc_extract_path, len(dtxt)))
        lines.append("doc_text:\n%s" % dtxt[:3500])
        if len(dtxt) > 3500:
            lines.append("  [TRUNCATED — read %s for full content]" % doc_extract_path)
    if table_extract_path:
        lines.append("table_extract: %s (full untruncated XLSX sheets for deep lookup)" % table_extract_path)
    if pdf_extract_path:
        full_txt = open(pdf_extract_path, encoding="utf-8").read()
        lines.append("pdf_extract: %s (%d chars, %d lines)" % (
            pdf_extract_path, len(full_txt), len(full_txt.splitlines())))
        if len(full_txt) <= 10500:
            lines.append("pdf_text_inline:\n%s" % full_txt)
        else:
            pidx, excerpts = _extract_target_pdf_excerpts(full_txt, task_hint_full, budget=10500)
            if pidx:
                lines.append("pdf_page_index: " + " | ".join(pidx[:35]))
            lines.append("target_pdf_excerpts (read %s with offset/limit for full page text):\n%s"
                         % (pdf_extract_path, excerpts))
    print("\n".join(lines))


def _auto_probes(plan):
    if plan.get("probe"):
        return str(plan["probe"])
    ascii_probes, any_probes = [], []
    for p in plan.get("panels", []):
        for n in p.get("nodes", []):
            lbl = str(n.get("label") or n.get("entity") or n.get("name") or "").split("\n")[0].strip()
            if 2 <= len(lbl) <= 24 and "," not in lbl:
                any_probes.append(lbl)
                if lbl.isascii():
                    ascii_probes.append(lbl)
        if p.get("type") == "chart":
            for s in p.get("chart", {}).get("series", []):
                nm = str(s.get("name", "")).strip()
                if 2 <= len(nm) <= 24 and "," not in nm:
                    any_probes.append(nm)
                    if nm.isascii():
                        ascii_probes.append(nm)
    probes = ascii_probes if ascii_probes else any_probes
    seen = []
    for pr in probes:
        if pr not in seen:
            seen.append(pr)
        if len(seen) >= 3:
            break
    return ",".join(seen)


def _min_node_gap(nodes):
    ks = list(nodes.keys())
    if len(ks) < 2:
        return None
    best = float("inf")
    for i in range(len(ks)):
        a = nodes[ks[i]]
        ax0, ay0, ax1, ay1 = a["x"] - a["w"] / 2.0, a["y"] - a["h"] / 2.0, a["x"] + a["w"] / 2.0, a["y"] + a["h"] / 2.0
        for j in range(i + 1, len(ks)):
            b = nodes[ks[j]]
            bx0, by0, bx1, by1 = b["x"] - b["w"] / 2.0, b["y"] - b["h"] / 2.0, b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0
            dx = max(0.0, max(bx0 - ax1, ax0 - bx1))
            dy = max(0.0, max(by0 - ay1, ay0 - by1))
            best = min(best, math.hypot(dx, dy))
    return round(best, 1) if best < float("inf") else None


def cmd_deliver(a):
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    plan = json.load(open(a.plan, encoding="utf-8"))
    brief_path = os.path.join(a.work, "case_brief.json")
    brief = json.load(open(brief_path, encoding="utf-8")) if os.path.exists(brief_path) else {}
    case_json_path = os.path.join(a.input, "case.json")
    case_id = str(plan.get("case_id") or brief.get("case_id") or "unknown")
    is_edit = (plan.get("mode") == "edit") or bool(plan.get("edit_svg"))
    task_type = plan.get("task_type") or ("edit" if is_edit else "generate")
    dpi = int(plan.get("dpi", 300))

    audit_path = os.path.join(a.work, "audit.json")
    checks_path = os.path.join(a.work, "checks.json")
    geom_path = os.path.join(a.work, "geometry.json")
    spec_path = os.path.join(a.work, "figure_spec.json")
    audit_rep = {"status": "not_run", "errors": [], "warnings": [], "n_errors": 0}
    checks_rep = {"status": "not_run", "errors": [], "n_errors": 0}
    build_info = {}
    edit_info = {}
    deliverables = {"editable_source": None, "exports": []}
    limits = list(plan.get("limits", []))
    change_records = list(plan.get("change_records", []))

    if is_edit:
        src_svg = plan["edit_svg"]
        if not os.path.isabs(src_svg) and not os.path.exists(src_svg):
            cand = os.path.join(a.input, src_svg)
            if os.path.exists(cand):
                src_svg = cand
        stem = plan.get("stem") or (os.path.splitext(os.path.basename(src_svg))[0] + "_edited")
        ops_path = os.path.join(a.work, "ops.json")
        json.dump({"ops": plan.get("ops", [])}, open(ops_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        rc, sout, serr = _run_py("edit_svg.py", [
            src_svg, ops_path, "--out-dir", a.out, "--stem", stem, "--dpi", str(dpi)
        ])
        try:
            edit_info = json.loads(sout)
        except Exception:
            edit_info = {"errors": ["edit_svg failed (rc=%d): %s" % (rc, (serr or sout)[:300])]}
        ed_svg = edit_info.get("edited_svg")
        rend = edit_info.get("render") or {}
        deliverables["editable_source"] = {
            "path": ed_svg, "format": "svg",
            "original_preserved": edit_info.get("original_copy"),
        }
        for fmt, key in (("pdf", "pdf"), ("png", "png"), ("png_preview", "preview")):
            if rend.get(key) and os.path.exists(rend[key]):
                item = {"path": rend[key], "format": "png" if fmt.startswith("png") else fmt}
                if fmt == "png":
                    item["dpi"] = dpi
                elif fmt == "png_preview":
                    item["dpi"] = 100
                    item["role"] = "preview"
                deliverables["exports"].append(item)
        if edit_info.get("original_copy") and os.path.exists(edit_info["original_copy"]):
            deliverables["exports"].append({
                "path": edit_info["original_copy"], "format": "svg", "role": "original_preserved"
            })
        if edit_info.get("errors"):
            limits.extend("edit_svg: %s" % e for e in edit_info["errors"])
        for op_log in edit_info.get("applied_ops", []):
            change_records.append({"step": "deliver_edit", "what": op_log, "why": "requested source-preserving edit"})
        # Export compliance check on edited outputs (no width_mm strict check on external SVG)
        ec_args = ["--dpi", str(dpi), "--out", checks_path]
        if ed_svg and os.path.exists(ed_svg):
            ec_args += ["--svg", ed_svg]
        if rend.get("pdf") and os.path.exists(rend["pdf"]):
            ec_args += ["--pdf", rend["pdf"]]
        if rend.get("png") and os.path.exists(rend["png"]):
            ec_args += ["--png", rend["png"]]
        if plan.get("probe"):
            ec_args += ["--probe", str(plan["probe"])]
        _, cout, _ = _run_py("export_check.py", ec_args)
        if os.path.exists(checks_path):
            checks_rep = json.load(open(checks_path, encoding="utf-8"))
        audit_rep = {"status": "pass" if not edit_info.get("errors") else "fail",
                     "errors": edit_info.get("errors", []),
                     "warnings": edit_info.get("audit_warnings", []),
                     "n_errors": len(edit_info.get("errors", []))}
        json.dump(audit_rep, open(audit_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    else:
        stem = plan.get("stem", "figure1")
        spec = {
            "canvas": plan.get("canvas", {"width_mm": 180}),
            "panels": plan.get("panels", []),
        }
        if plan.get("footnote"):
            spec["footnote"] = plan["footnote"]
        if plan.get("preset"):
            spec["preset"] = plan["preset"]
        # Auto-synthesize legend if a schematic panel has edges but omitted legend (rubric guarantee)
        _KIND_LABELS = {
            "activates": "Activation / Promotion",
            "catalyzes": "Catalysis",
            "inhibits": "Inhibition / Blockade",
            "inhibits_dashed": "Indirect inhibition",
            "translocates": "Translocation / Transport",
            "binds": "Binding / Complex",
            "flows": "Process flow",
            "assoc": "Association",
            "compare": "Comparison",
        }
        import fig_style as _FS
        # Pre-normalize LLM schema variations BEFORE auto-legend & spec_path write so make_result/audit see canonical keys!
        _DIR_AL = {
            "VERTICAL": "TB", "TOP-DOWN": "TB", "TOP_DOWN": "TB", "TOP_TO_BOTTOM": "TB", "TD": "TB", "DOWN": "TB",
            "HORIZONTAL": "LR", "LEFT-TO-RIGHT": "LR", "LEFT_TO_RIGHT": "LR", "RIGHT": "LR",
        }
        _CH_TYPES = {"bar", "barh", "stacked_bar", "line", "scatter", "box", "heatmap"}
        for p in spec.get("panels", []):
            pt_l = str(p.get("type", "schematic")).strip().lower()
            if pt_l in _CH_TYPES:
                p["type"] = "chart"
                p.setdefault("chart", {}).setdefault("kind", pt_l)
            if p.get("direction"):
                d_u = str(p["direction"]).strip().upper()
                p["direction"] = _DIR_AL.get(d_u, d_u)
            id_map, lbl_map = {}, {}
            for ni, n in enumerate(p.get("nodes", [])):
                if not n.get("id"):
                    raw_i = n.get("entity") or n.get("name") or n.get("label") or ("node_%d" % ni)
                    n["id"] = re.sub(r"\s+", "_", str(raw_i).strip())[:32]
                if not n.get("label"):
                    n["label"] = str(n.get("entity") or n.get("name") or n["id"])
                n["id"] = str(n["id"])
                id_map[n["id"].lower()] = n["id"]
                lbl_map[str(n["label"]).strip().lower()] = n["id"]
            for e in p.get("edges", []):
                if "from" not in e:
                    if isinstance(e.get("source"), str):
                        e["from"] = e["source"]
                    else:
                        for fk in ("src", "subject", "from_id", "source_id", "start"):
                            if e.get(fk):
                                e["from"] = e[fk]; break
                if "to" not in e:
                    for tk in ("target", "dst", "object", "to_id", "target_id", "end"):
                        if e.get(tk):
                            e["to"] = e[tk]; break
                if not e.get("kind"):
                    e["kind"] = e.get("relation") or e.get("type") or "activates"
                e["kind"] = _FS.canonical_edge_kind(e["kind"])
                for ek in ("from", "to"):
                    v0 = str(e.get(ek, "")).strip()
                    if v0 and v0.lower() in id_map:
                        e[ek] = id_map[v0.lower()]
                    elif v0 and v0.lower() in lbl_map:
                        e[ek] = lbl_map[v0.lower()]
            for g in p.get("groups", []):
                if isinstance(g.get("members"), list):
                    g["members"] = [
                        id_map.get(str(m).strip().lower()) or lbl_map.get(str(m).strip().lower()) or str(m).strip()
                        for m in g["members"]
                    ]
            if p.get("type", "schematic") != "chart" and p.get("edges") and not p.get("legend"):
                seen_k = []
                for e in p["edges"]:
                    k = _FS.canonical_edge_kind(e.get("kind", "activates"))
                    if k not in seen_k:
                        seen_k.append(k)
                if seen_k:
                    p["legend"] = {
                        "title": "Legend",
                        "items": [{"kind": k, "label": _KIND_LABELS.get(k, k)} for k in seen_k],
                    }
        # Resolve data_file against work/input_dir (incl. smart basename & unique-ext fallback)
        input_files = []
        if os.path.isdir(a.input):
            for rr, _, fns in os.walk(a.input):
                for fn in fns:
                    input_files.append(os.path.join(rr, fn))
        for p in spec.get("panels", []):
            ch = p.get("chart")
            if isinstance(ch, dict) and ch.get("data_file"):
                df = ch["data_file"]
                if not os.path.exists(df):
                    resolved = None
                    for root_dir in (os.path.dirname(os.path.abspath(a.plan)), a.input):
                        cand = os.path.join(root_dir, os.path.basename(df))
                        if os.path.exists(cand):
                            resolved = os.path.abspath(cand)
                            break
                    if not resolved:
                        want_base = os.path.basename(df).lower()
                        want_ext = os.path.splitext(df)[1].lower()
                        sub_hits = [fp for fp in input_files if want_base in os.path.basename(fp).lower()]
                        if len(sub_hits) == 1:
                            resolved = os.path.abspath(sub_hits[0])
                        elif want_ext:
                            ext_hits = [fp for fp in input_files if fp.lower().endswith(want_ext)]
                            if len(ext_hits) == 1:
                                resolved = os.path.abspath(ext_hits[0])
                    if resolved:
                        ch["data_file"] = resolved
        if plan.get("style"):
            spec["style"] = plan["style"]
        if plan.get("units_ok"):
            spec["units_ok"] = plan["units_ok"]
        json.dump(spec, open(spec_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        bf_args = [spec_path, "--out-dir", a.out, "--stem", stem, "--geom", geom_path, "--dpi", str(dpi)]
        if plan.get("tiff"):
            bf_args.append("--tiff")
        rc, sout, serr = _run_py("build_figure.py", bf_args)
        if rc != 0:
            limits.append("build_figure failed: %s" % (serr or sout)[:300])
        else:
            try:
                build_info = json.loads(sout)
            except Exception:
                limits.append("build_figure JSON parse error")
        if build_info.get("svg"):
            deliverables["editable_source"] = {
                "path": build_info["svg"], "format": "svg",
                "layers": ["panel-*", "node-*", "edge-*", "group-*", "legend-*"],
            }
        for key, fmt, extra in (
            ("pdf", "pdf", {}),
            ("png", "png", {"dpi": dpi}),
            ("preview", "png", {"dpi": 100, "role": "preview"}),
            ("tiff", "tiff", {"dpi": dpi}),
        ):
            if build_info.get(key) and os.path.exists(build_info[key]):
                deliverables["exports"].append({"path": build_info[key], "format": fmt, **extra})
        # Audit geometry
        if os.path.exists(geom_path):
            _run_py("audit_figure.py", [geom_path, "--spec", spec_path, "--out", audit_path])
            if os.path.exists(audit_path):
                audit_rep = json.load(open(audit_path, encoding="utf-8"))
        # Export compliance (use resolved canvas width from geometry.json when preset applied)
        width_mm = float(spec.get("canvas", {}).get("width_mm", 180.0))
        if os.path.exists(geom_path):
            try:
                g_tmp = json.load(open(geom_path, encoding="utf-8"))
                if g_tmp.get("canvas_mm"):
                    width_mm = float(g_tmp["canvas_mm"][0])
            except Exception:
                pass
        ec_args = ["--width-mm", str(width_mm), "--dpi", str(dpi), "--out", checks_path]
        if build_info.get("png"):
            ec_args += ["--png", build_info["png"]]
        if build_info.get("pdf"):
            ec_args += ["--pdf", build_info["pdf"]]
        if build_info.get("svg"):
            ec_args += ["--svg", build_info["svg"]]
        probe = _auto_probes(plan)
        if probe:
            ec_args += ["--probe", probe]
        _run_py("export_check.py", ec_args)
        if os.path.exists(checks_path):
            checks_rep = json.load(open(checks_path, encoding="utf-8"))
        change_records.append({
            "step": "deliver_generate",
            "what": "rendered %s (%d panel(s)) to SVG/PDF/PNG" % (stem, len(spec.get("panels", []))),
            "why": "deterministic source-bound schematic delivery",
        })
        # Optional post_edit_ops: apply source-preserving revision pass on generated SVG in one shot
        if plan.get("post_edit_ops") and build_info.get("svg") and os.path.exists(build_info["svg"]):
            pe_ops_path = os.path.join(a.work, "post_edit_ops.json")
            json.dump({"ops": plan["post_edit_ops"]}, open(pe_ops_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            pe_stem = stem + "_revised"
            _, pe_out, _ = _run_py("edit_svg.py", [
                build_info["svg"], pe_ops_path, "--out-dir", a.out, "--stem", pe_stem, "--dpi", str(dpi)
            ])
            try:
                pe_info = json.loads(pe_out)
                if pe_info.get("edited_svg") and os.path.exists(pe_info["edited_svg"]):
                    deliverables["exports"].append({"path": pe_info["edited_svg"], "format": "svg", "role": "revised_editable"})
                for k, fmt in (("pdf", "pdf"), ("png", "png"), ("preview", "png")):
                    rp = (pe_info.get("render") or {}).get(k)
                    if rp and os.path.exists(rp):
                        deliverables["exports"].append({"path": rp, "format": fmt, "role": "revised_" + k})
                for op_log in pe_info.get("applied_ops", []):
                    change_records.append({"step": "deliver_post_edit", "what": op_log, "why": "source-preserving revision"})
            except Exception:
                pass

    # Optional PPTX deck if requested
    if plan.get("pptx"):
        png_for_ppt = build_info.get("png") or (edit_info.get("render") or {}).get("png")
        if png_for_ppt and os.path.exists(png_for_ppt):
            _, pout, _ = _run_py("build_pptx.py", [
                "--png", png_for_ppt, "--title", plan.get("pptx_title", stem),
                "--subtitle", plan.get("pptx_subtitle", ""), "--case-id", case_id,
                "--out-dir", a.out, "--stem", stem,
            ])
            try:
                pinfo = json.loads(pout)
                for k, fmt in (("pptx", "pptx"), ("slides_pdf", "pdf"), ("preview", "png")):
                    if pinfo.get(k) and os.path.exists(pinfo[k]):
                        deliverables["exports"].append({"path": pinfo[k], "format": fmt, "role": "slides"})
            except Exception:
                pass

    # Assemble manifest + preserve any extra top-level output_contract fields from plan.json
    sources = list(plan.get("sources") or [
        os.path.basename(m["path"]) for m in brief.get("materials", []) if m.get("path")
    ])
    source_manifest = []
    for m in brief.get("materials", []):
        mp = m.get("path")
        if mp and os.path.isfile(mp):
            try:
                data_m = open(mp, "rb").read()
                source_manifest.append({
                    "file": os.path.basename(mp),
                    "type": m.get("type", "file"),
                    "bytes": len(data_m),
                    "sha256": hashlib.sha256(data_m).hexdigest()[:16],
                })
            except Exception:
                pass
    ent_inv = list(plan.get("entity_inventory", []))
    rel_inv = list(plan.get("relation_inventory", []))
    post_edit_ins = None
    # In edit mode, auto-harvest full post-edit SVG text labels & inferred semantic edge relations when omitted
    if is_edit and edit_info.get("edited_svg") and os.path.exists(edit_info["edited_svg"]):
        src_name = os.path.basename(plan.get("edit_svg", "edited.svg"))
        _, sout_ins, _ = _run_py("edit_svg.py", [edit_info["edited_svg"], "--inspect"])
        try:
            post_edit_ins = json.loads(sout_ins)
        except Exception:
            post_edit_ins = None
        if not ent_inv and post_edit_ins:
            for tx in post_edit_ins.get("texts", []):
                lbl = (tx.get("text") or "").strip()
                if lbl:
                    ent_inv.append({
                        "entity": lbl,
                        "type": "svg_text",
                        "role": "preserved/edited label",
                        "source": {"file": src_name, "locator": tx.get("group_id") or tx.get("id") or "svg"},
                        "confidence": "high",
                    })
        if not rel_inv:
            if post_edit_ins and post_edit_ins.get("edges"):
                for ed in post_edit_ins.get("edges", []):
                    subj = ed.get("from_label") or ed.get("id") or ("edge_%d_src" % ed.get("edge_idx", 0))
                    obj = ed.get("to_label") or ("edge_%d_dst" % ed.get("edge_idx", 0))
                    rel_inv.append({
                        "subject": subj,
                        "object": obj,
                        "kind": ed.get("inferred_kind") or "activates",
                        "evidence": "post-edit SVG connector (%s, mk=%s)" % (
                            ed.get("id") or ed.get("group_id") or ("edge_idx=%d" % ed.get("edge_idx", 0)),
                            ed.get("marker_end") or "none"),
                        "source": {"file": src_name, "locator": ed.get("id") or ed.get("group_id") or ("edge_idx=%d" % ed.get("edge_idx", 0))},
                        "confidence": "high" if (ed.get("from_label") and ed.get("to_label")) else "medium",
                    })
            else:
                for o in plan.get("ops", []):
                    opn = o.get("op")
                    if opn == "add_edge":
                        rel_inv.append({
                            "subject": o.get("from_text") or o.get("id") or "source",
                            "object": o.get("to_text") or "target",
                            "kind": "inhibits" if o.get("marker") == "tbar" else ("translocates" if o.get("marker") == "open" else "activates"),
                            "evidence": o.get("label", "added edge"),
                            "source": {"file": src_name, "locator": o.get("id") or "add_edge"},
                            "confidence": "high",
                        })
                    elif opn in ("set_marker", "swap_edge", "set_dash"):
                        subj = str(o.get("from_text") or o.get("gid") or o.get("by_text") or ("edge_idx=%s" % o.get("edge_idx")))
                        obj = str(o.get("to_text") or subj)
                        rel_inv.append({
                            "subject": subj,
                            "object": obj,
                            "kind": "inhibits" if o.get("marker") == "tbar" else ("translocates" if o.get("marker") == "open" else "edited_relation"),
                            "evidence": "%s(%s)" % (opn, o.get("marker") or o.get("dash") or "reversed"),
                            "source": {"file": src_name, "locator": str(o.get("gid") or ("edge_idx=%s" % o.get("edge_idx")))},
                            "confidence": "high",
                        })
    manifest = {
        "deliverables": deliverables,
        "entity_inventory": ent_inv,
        "relation_inventory": rel_inv,
        "data_mapping": plan.get("data_mapping", {}),
        "sources": sources,
        "source_manifest": source_manifest,
        "uncertainty": plan.get("uncertainty", []),
        "limits": limits,
        "change_records": change_records,
        "notes": plan.get("notes", ""),
    }
    for k, v in plan.items():
        if k not in SPEC_ONLY_KEYS and k not in manifest:
            manifest[k] = v
    man_path = os.path.join(a.work, "manifest.json")
    json.dump(manifest, open(man_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    res_path = os.path.join(a.out, "result.json")
    mr_args = [
        "--case-id", case_id, "--task-type", task_type,
        "--manifest", man_path, "--audit", audit_path,
        "--export-checks", checks_path, "--out", res_path,
    ]
    if os.path.exists(case_json_path):
        mr_args += ["--case-json", case_json_path]
    if not is_edit and os.path.exists(spec_path):
        mr_args += ["--auto-from-spec", spec_path]
    if os.path.exists(geom_path):
        mr_args += ["--geometry", geom_path]
    _, mrout, _ = _run_py("make_result.py", mr_args)
    res_obj = json.load(open(res_path, encoding="utf-8")) if os.path.exists(res_path) else {}

    # Pure-text verification summary (replaces reading binary PNG for text-only evaluators!)
    lines = [
        "== DELIVER SUMMARY ==",
        "case_id: %s | task_type: %s | status: %s" % (case_id, task_type, res_obj.get("status")),
        "result_json: %s (entities=%d, relations=%d, missing_contract_fields=%s)" % (
            res_path, len(res_obj.get("entity_inventory", [])),
            len(res_obj.get("relation_inventory", [])), res_obj.get("missing_fields", [])),
        "audit: %s (errors=%d, warnings=%d)" % (
            audit_rep.get("status"), audit_rep.get("n_errors", 0), len(audit_rep.get("warnings", []))),
        "export_check: %s (errors=%d)" % (checks_rep.get("status"), checks_rep.get("n_errors", 0)),
    ]
    if audit_rep.get("errors"):
        lines.append("  AUDIT_ERRORS: %s" % audit_rep["errors"])
    if audit_rep.get("warnings"):
        lines.append("  AUDIT_WARNINGS: %s" % audit_rep["warnings"])
    if audit_rep.get("provenance"):
        pr = audit_rep["provenance"]
        lines.append("  provenance: nodes %d/%d, edges %d/%d with source locators" % (
            pr.get("nodes_sourced", 0), pr.get("nodes_total", 0),
            pr.get("edges_sourced", 0), pr.get("edges_total", 0)))
    if audit_rep.get("data_verification"):
        dv_items = ["%s:%s(%d vals/%d errs,sha=%s)" % (
            k, "OK" if v.get("verified") else "FAIL",
            v.get("n_values_checked", 0), v.get("n_errors_checked", 0),
            v.get("source_sha256", "?"))
            for k, v in audit_rep["data_verification"].items()]
        lines.append("  data_verification: " + ", ".join(dv_items))
    if checks_rep.get("errors"):
        lines.append("  EXPORT_ERRORS: %s" % checks_rep["errors"])
    if checks_rep.get("png"):
        pg = checks_rep["png"]
        lines.append("  png: %sx%s px @ %s dpi (%.1f mm)" % (
            pg["pixel"][0], pg["pixel"][1], pg.get("dpi_x"), pg.get("physical_mm", 0)))
    if checks_rep.get("pdf"):
        pd = checks_rep["pdf"]
        lines.append("  pdf: page=%s mm, fonts_embedded=%d, not_embedded=%d, text_chars=%d, probes_missing=%s" % (
            pd.get("page_mm"), len(pd.get("fonts_embedded", [])),
            len(pd.get("fonts_not_embedded", [])), pd.get("text_chars", 0), pd.get("probes_missing", [])))
    if checks_rep.get("svg"):
        sv = checks_rep["svg"]
        lines.append("  svg: texts=%d, semantic_layers=%d, oob_est=%d" % (
            sv.get("text_elements", 0), sv.get("semantic_layers", 0),
            sv.get("elements_outside_viewbox_est", 0)))
    if not is_edit and os.path.exists(geom_path):
        G = json.load(open(geom_path, encoding="utf-8"))
        lines.append("canvas_mm: %s" % G.get("canvas_mm"))
        # Detect available table files in /input so we can nudge if a chart omitted data_file
        avail_tables = []
        if os.path.isdir(a.input):
            for rr, _, fns in os.walk(a.input):
                for fn in sorted(fns):
                    if os.path.splitext(fn)[1].lower() in (".xlsx", ".csv", ".tsv"):
                        avail_tables.append(fn)
        for pid, p in G.get("panels", {}).items():
            if p.get("type") == "chart":
                lines.append("  panel[%s] chart: series=%s cats=%s legend=%d unit=%r data_file=%s" % (
                    pid, p.get("series_names"), (p.get("categories") or [])[:12],
                    p.get("legend_entries", 0), p.get("unit", ""), p.get("data_file")))
                # Print exact plotted values (± errors) so text-only agents can audit every number!
                for sd in (p.get("series_data") or [])[:6]:
                    vs = sd.get("values") or []
                    es = sd.get("errors") or []
                    if es and len(es) == len(vs):
                        vstr = ", ".join(
                            ("%s±%s" % (round(v, 3), round(e, 3))) if (v is not None and e is not None) else str(v)
                            for v, e in list(zip(vs, es))[:12])
                    else:
                        vstr = ", ".join(str(round(v, 3) if isinstance(v, float) else v) for v in vs[:12])
                    lines.append("    plotted[%s]: [%s]" % (sd.get("name", "?"), vstr))
                if avail_tables and not p.get("data_file"):
                    lines.append("    HINT: /input has data table(s) %s — bind chart.data_file for SHA-256 verified plotting" % avail_tables[:4])
            else:
                nds = p.get("nodes", {})
                gap = _min_node_gap(nds)
                lines.append("  panel[%s] schematic: scale=%.2f nodes=%d edges=%d groups=%d min_node_gap=%smm" % (
                    pid, p.get("scale", 1.0), len(nds), len(p.get("edges", [])),
                    len(p.get("groups", {})), gap))
                nd_items = list(nds.items())
                nd_str = ", ".join("%s(%.0f,%.0f)" % (k, v["x"], v["y"]) for k, v in nd_items[:24])
                if len(nd_items) > 24:
                    nd_str += " (+%d more)" % (len(nd_items) - 24)
                lines.append("    nodes: %s" % nd_str)
                ed_items = p.get("edges", [])
                ed_str = ", ".join("%s->%s[%s]" % (e["subject"], e["object"], e["kind"])
                                   for e in ed_items[:24])
                if len(ed_items) > 24:
                    ed_str += " (+%d more)" % (len(ed_items) - 24)
                lines.append("    edges: %s" % ed_str)
                comps_p = [c for c in (res_obj.get("compartments") or []) if c.get("panel") == pid]
                if comps_p:
                    c_str = ", ".join("%s[%s]%s" % (
                        c["label"], ",".join(c.get("members", [])[:8]),
                        "(membrane)" if c.get("membrane") else "") for c in comps_p[:8])
                    lines.append("    compartments: %s" % c_str)
    elif is_edit:
        lines.append("  edit: source_preserved=%s, groups=%s->%s, viewBox=%s->%s, applied=%s" % (
            edit_info.get("source_preserved"), edit_info.get("groups_before"),
            edit_info.get("groups_after"), edit_info.get("viewBox_before"),
            edit_info.get("viewBox_after"), edit_info.get("applied_ops", [])))
        if edit_info.get("errors"):
            lines.append("  EDIT_ERRORS: %s" % edit_info["errors"])
        if edit_info.get("texts_added") or edit_info.get("texts_removed"):
            lines.append("  edit_text_diff: added=%s removed=%s" % (
                edit_info.get("texts_added", []), edit_info.get("texts_removed", [])))
        if post_edit_ins and post_edit_ins.get("edges"):
            er_str = ", ".join("%s->%s[%s]" % (
                e.get("from_label") or "?", e.get("to_label") or "?", e.get("inferred_kind") or "edge")
                for e in post_edit_ins["edges"][:20])
            lines.append("  edit_relations (%d): %s" % (len(post_edit_ins["edges"]), er_str))
    has_edit_err = bool(is_edit and edit_info.get("errors"))
    if (audit_rep.get("n_errors", 0) == 0 and checks_rep.get("n_errors", 0) == 0
            and not res_obj.get("missing_fields") and not has_edit_err):
        lines.append("NEXT: ALL CHECKS PASSED — ready to finish unless a primary-source entity/value requirement is still unmet.")
    else:
        lines.append("NEXT: Fix listed AUDIT_ERRORS/EXPORT_ERRORS/EDIT_ERRORS/missing_contract_fields in plan.json and re-run deliver once.")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare")
    p1.add_argument("--input", default="/input")
    p1.add_argument("--work", default="/app/work")
    p1.add_argument("--out", default="/app/output")
    p2 = sub.add_parser("deliver")
    p2.add_argument("plan")
    p2.add_argument("--input", default="/input")
    p2.add_argument("--work", default="/app/work")
    p2.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    if a.cmd == "prepare":
        cmd_prepare(a)
    else:
        cmd_deliver(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
