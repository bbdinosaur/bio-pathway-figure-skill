#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inspect_input.py — 步骤 0 一步式输入全景侦查引擎（支持首轮保底落盘 result.json）。
用法:
  python3 inspect_input.py /input [--max-sample 3] [--json /app/work/input_summary.json] \
      [--init-output /app/output/result.json]
一次输出: case_id、output_contract 必需字段、环境字体与工具、所有表格列/范围/唯一值/缺失统计、
PDF 页数/Figure 命中/高频科学实体词表、SVG 尺寸/文本/色板，以及推荐路由，减少试探轮次。"""
from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kit_common import detect_cjk_font, dump_json, load_json, read_table, to_num, _import_fitz  # noqa: E402
from make_result import find_contract, contract_fields  # noqa: E402

_ENTITY_PAT = re.compile(
    r"\b(?:[A-Z][A-Z0-9]{1,8}(?:[-/][A-Za-z0-9α-ωΑ-Ω]{1,6})?|"
    r"[A-Za-z]{1,4}[-]?[0-9]{1,3}[a-zA-Z]?|"
    r"p[0-9]{2,3}|mTORC[12]|NF-[κk]B|TGF-[βb][0-9]?|IL-[0-9]{1,2}|TNF-[αa]|IFN-[γg])\b"
)
_ENTITY_STOP = {
    "THE", "AND", "FOR", "WITH", "FROM", "THAT", "THIS", "FIG", "FIGURE", "TABLE",
    "DATA", "CELL", "CELLS", "PDF", "SVG", "PNG", "DPI", "USA", "DOI", "HTTP", "HTTPS",
    "ALL", "NOT", "ARE", "WAS", "WERE", "HAVE", "HAS", "CAN", "MAY", "USE", "USED",
    "MEAN", "SEM", "STD", "MAX", "MIN", "LOG", "PCT", "VS", "OR", "OF", "IN", "TO", "BY",
}


def _summarize_rows(cols, rows, max_sample=3):
    col_stats = []
    for c in cols[:30]:
        vals = [r.get(c, "") for r in rows]
        nums = [to_num(v) for v in vals]
        valid_nums = [x for x in nums if x is not None]
        non_empty = [str(v).strip() for v in vals if str(v).strip() != ""]
        n_miss = len(vals) - len(non_empty)
        uniq = list(dict.fromkeys(non_empty))
        st = {"col": c, "non_empty": len(non_empty), "missing": n_miss, "n_unique": len(uniq)}
        if valid_nums and len(valid_nums) >= max(1, int(len(non_empty) * 0.7)):
            st["type"] = "numeric"
            st["min"] = round(min(valid_nums), 6)
            st["max"] = round(max(valid_nums), 6)
            nz = [abs(x) for x in valid_nums if x != 0]
            if nz and max(nz) / min(nz) > 1e4:
                st["scale_warn"] = ">4_orders_of_magnitude"
        else:
            st["type"] = "categorical"
            st["unique_sample"] = uniq[:12]
        col_stats.append(st)
    samples = [{k: v for k, v in r.items() if k in cols or k == "__line__"} for r in rows[:max_sample]]
    return {"n_rows": len(rows), "columns": cols, "col_stats": col_stats, "sample_rows": samples}


def _inspect_xlsx(path, max_sample=3):
    import zipfile
    import xml.etree.ElementTree as ET
    from chart_spec import _read_xlsx_stdlib, _extract_xlsx_table
    sheets = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        names = list(wb.sheetnames)
        for nm in names[:5]:
            ws = wb[nm]
            indexed = [(idx, list(r)) for idx, r in enumerate(ws.iter_rows(values_only=True), start=1)]
            cols, rows, hline = _extract_xlsx_table(indexed)
            sheets.append({"sheet": nm, "header_line": hline, **_summarize_rows(cols, rows, max_sample)})
        wb.close()
        return {"sheets": names, "preview": sheets}
    except ImportError:
        sheet_names = []
        with zipfile.ZipFile(str(path)) as zf:
            if "xl/workbook.xml" in zf.namelist():
                wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
                sheet_names = [s.get("name") for s in wb_root.iter() if s.tag.split("}")[-1] == "sheet" and s.get("name")]
        for nm in (sheet_names[:4] or [None]):
            title, indexed = _read_xlsx_stdlib(path, sheet_name=nm)
            cols, rows, hline = _extract_xlsx_table(indexed)
            sheets.append({"sheet": title, "header_line": hline, **_summarize_rows(cols, rows, max_sample)})
        return {"sheets": sheet_names, "preview": sheets}


def _inspect_pdf_summary(path):
    try:
        fitz = _import_fitz()
        doc = fitz.open(str(path))
        n_pages = doc.page_count
        fig_hits = []
        fig_index = {}
        ent_counter = collections.Counter()
        first_lines = []
        for i in range(n_pages):
            txt = re.sub(r"-\s*\n\s*", "", doc[i].get_text("text") or "")
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            first_lines.append({"page": i, "head": lines[0][:100] if lines else ""})
            for m in re.finditer(r"(?:Extended\s+Data\s+|Supplementary\s+)?(?:Figure|Fig\.?)\s*(\d+)[A-Za-z]?[^\n]{0,120}", txt):
                fnum = f"Fig.{m.group(1)}"
                fig_index.setdefault(fnum, [])
                if i not in fig_index[fnum]:
                    fig_index[fnum].append(i)
                    fig_hits.append({"fig": fnum, "page": i, "snippet": m.group(0).strip()})
            for tok in _ENTITY_PAT.findall(txt):
                if tok.upper() not in _ENTITY_STOP and not tok.isdigit():
                    ent_counter[tok] += 1
        page0_spans = len(doc[0].get_text("dict").get("blocks", [])) if n_pages else 0
        doc.close()
        return {
            "n_pages": n_pages,
            "page0_blocks": page0_spans,
            "page_heads": first_lines[:10],
            "figure_pages": fig_index,
            "figure_mentions": fig_hits[:24],
            "candidate_entities_top30": [k for k, _ in ent_counter.most_common(30)],
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _inspect_svg_summary(path):
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(path)).getroot()
        vb = root.get("viewBox") or f"0 0 {root.get('width', '?')} {root.get('height', '?')}"
        texts = []
        colors = set()
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "text":
                t = "".join(el.itertext()).strip()
                if t:
                    texts.append(t)
            for attr in ("fill", "stroke"):
                v = el.get(attr)
                if v and v not in ("none", "transparent"):
                    colors.add(v)
        return {
            "viewBox": vb,
            "n_texts": len(texts),
            "sample_texts": texts[:25],
            "palette_sample": sorted(colors)[:20],
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _inspect_pptx_summary(path):
    """零依赖或 python-pptx 提取 PPTX 幻灯片数量与文本摘要。"""
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            slides = sorted(n for n in zf.namelist()
                            if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            samples = []
            for sn in slides[:5]:
                root = ET.fromstring(zf.read(sn))
                txts = [t.text.strip() for t in root.iter()
                        if t.tag.split("}")[-1] == "t" and t.text and t.text.strip()]
                samples.append({"slide": sn.rsplit("/", 1)[-1], "text_count": len(txts), "sample": txts[:8]})
            return {"n_slides": len(slides), "slides": samples}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _inspect_image_summary(path):
    try:
        from PIL import Image
        im = Image.open(path)
        dpi = im.info.get("dpi")
        return {
            "size_px": [im.width, im.height],
            "mode": im.mode,
            "dpi": [round(float(dpi[0]), 1), round(float(dpi[1]), 1)] if dpi else None,
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _inspect_docx_summary(path):
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(str(path), "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return {"error": "missing word/document.xml"}
            root = ET.fromstring(zf.read("word/document.xml"))
            paras = []
            for p_el in root.iter():
                if p_el.tag.split("}")[-1] == "p":
                    t = "".join(x.text for x in p_el.iter() if x.tag.split("}")[-1] == "t" and x.text).strip()
                    if t:
                        paras.append(t)
            return {"n_paragraphs": len(paras), "sample": paras[:6]}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def _probe_env():
    tools = {t: bool(shutil.which(t)) for t in ("rsvg-convert", "inkscape", "chromium", "google-chrome", "gs", "pdftoppm")}
    mods = {}
    for m in ("matplotlib", "numpy", "PIL", "pptx", "openpyxl"):
        try:
            __import__(m)
            mods[m] = True
        except Exception:
            mods[m] = False
    try:
        _import_fitz()
        mods["pymupdf"] = True
    except Exception:
        mods["pymupdf"] = False
    return {"cjk_font": detect_cjk_font(), "python_modules": mods, "cli_tools": tools}


def _looks_like_delimited_txt(path):
    """严格判断 .txt 是否为结构化表格（至少 2 行一致分隔列数，表头为短字段名而非自然语言长句）。"""
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")][:8]
        if len(lines) < 2:
            return False
        for sep in ("\t", ","):
            counts = [len(ln.split(sep)) for ln in lines]
            if counts[0] >= 2 and all(c == counts[0] for c in counts[:min(4, len(counts))]):
                hdr_toks = [tok.strip() for tok in lines[0].split(sep)]
                if any(t.endswith(".") or len(t.split()) > 3 for t in hdr_toks):
                    continue
                if sep == "\t":
                    return True
                # 逗号分隔 .txt 额外要求：至少有一列含数值或单元格词数极短
                body_toks = [tok.strip() for ln in lines[1:4] for tok in ln.split(sep)]
                has_num = any(to_num(t) is not None for t in body_toks)
                avg_words = sum(len(t.split()) for t in body_toks) / max(1, len(body_toks))
                if has_num or avg_words <= 1.8:
                    return True
    except Exception:
        pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir", nargs="?", default="/input")
    ap.add_argument("--max-sample", type=int, default=3)
    ap.add_argument("--json", help="可选：同时写入完整 JSON 报告文件")
    ap.add_argument("--compact", action="store_true",
                    help="stdout 仅输出精简摘要（≤1.5KB），完整明细写入 --json 文件")
    ap.add_argument("--init-output",
                    help="可选：步骤 0 立即写出含 case_id、status=partial、全部 output_contract 键与初步 limits 的保底 result.json")
    args = ap.parse_args()

    root = Path(args.input_dir)
    if not root.exists():
        print(json.dumps({"ok": False, "error": f"input_dir not found: {root}"}, ensure_ascii=False))
        sys.exit(1)

    case_path = root / "case.json"
    task_path = root / "task.md"
    case = load_json(case_path) if case_path.exists() else {}
    case_id = case.get("case_id") or case.get("id") or case.get("caseId") or None
    got_c = find_contract(case)
    c_fields = contract_fields(got_c[0]) if got_c else []

    files = sorted(p for p in root.rglob("*") if p.is_file())
    file_reports = []
    has_table = has_pdf = has_svg = False
    for p in files:
        rel = str(p.relative_to(root))
        sfx = p.suffix.lower()
        rec = {"path": str(p), "rel": rel, "size_bytes": p.stat().st_size, "ext": sfx}
        if p.name in ("case.json", "task.md"):
            rec["role"] = "workorder"
        elif sfx in (".csv", ".tsv", ".txt"):
            try:
                is_tbl = (sfx in (".csv", ".tsv")) or _looks_like_delimited_txt(p)
                if is_tbl:
                    cols, rows, hline = read_table(p, return_meta=True)
                    if cols and rows:
                        has_table = True
                        rec["role"] = "table"
                        rec["header_line"] = hline
                        rec["summary"] = _summarize_rows(cols, rows, args.max_sample)
                    else:
                        rec["role"] = "text"
                        rec["head"] = p.read_text(encoding="utf-8", errors="ignore")[:400]
                else:
                    rec["role"] = "text"
                    rec["head"] = p.read_text(encoding="utf-8", errors="ignore")[:400]
            except Exception as ex:
                rec["role"] = "table_error"
                rec["error"] = f"{type(ex).__name__}: {ex}"
        elif sfx in (".xlsx", ".xlsm"):
            has_table = True
            rec["role"] = "spreadsheet"
            try:
                rec["summary"] = _inspect_xlsx(p, args.max_sample)
            except Exception as ex:
                rec["error"] = f"{type(ex).__name__}: {ex}"
        elif sfx == ".json":
            try:
                obj = load_json(p)
                if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                    has_table = True
                    cols = list(dict.fromkeys(k for r in obj for k in r.keys()))
                    rows = [{c: ("" if r.get(c) is None else str(r.get(c))) for c in cols} for r in obj]
                    rec["role"] = "json_table"
                    rec["summary"] = _summarize_rows(cols, rows, args.max_sample)
                else:
                    rec["role"] = "json"
                    rec["keys"] = list(obj.keys())[:20] if isinstance(obj, dict) else type(obj).__name__
            except Exception as ex:
                rec["role"] = "json_error"
                rec["error"] = str(ex)
        elif sfx == ".pdf":
            has_pdf = True
            rec["role"] = "pdf"
            rec["summary"] = _inspect_pdf_summary(p)
        elif sfx == ".svg":
            has_svg = True
            rec["role"] = "svg"
            rec["summary"] = _inspect_svg_summary(p)
        elif sfx == ".pptx":
            rec["role"] = "pptx"
            rec["summary"] = _inspect_pptx_summary(p)
        elif sfx == ".docx":
            rec["role"] = "docx"
            rec["summary"] = _inspect_docx_summary(p)
        elif sfx in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"):
            rec["role"] = "image"
            rec["summary"] = _inspect_image_summary(p)
        elif sfx in (".md", ".rst"):
            rec["role"] = "text"
            rec["head"] = p.read_text(encoding="utf-8", errors="ignore")[:350]
        else:
            rec["role"] = "other"
        file_reports.append(rec)

    routes = []
    if has_table:
        routes.append("A:chart_tool.py (data chart)")
    if has_svg:
        routes.append("B:svg_edit.py --input (source-preserving edit)")
    if has_pdf:
        routes.append("B/C:svg_edit.py (--inspect/--extract-pdf -> edit or --diagram)")

    init_output_info = None
    if args.init_output:
        init_p = Path(args.init_output)
        preserve = False
        if init_p.exists():
            try:
                existing = load_json(init_p)
                if isinstance(existing, dict):
                    deliv = existing.get("deliverables") or {}
                    has_deliv = bool(
                        (isinstance(deliv, dict) and (deliv.get("editable_source") or deliv.get("exports")))
                        or existing.get("status") in ("complete", "ok")
                    )
                    if has_deliv:
                        preserve = True
            except Exception:
                pass
        if preserve:
            init_output_info = {"path": str(init_p), "action": "preserved_existing"}
        else:
            init_doc = {
                "case_id": case_id or "unknown",
                "status": "partial",
                "deliverables": {"editable_source": [], "exports": [], "previews": []},
                "checks": {},
                "change_log": [],
                "uncertainty": [],
                "limits": [
                    "Step-0 bootstrap partial record: input inspected; figure generation and verification pending."
                ],
                "recommended_routes": routes,
            }
            if got_c:
                init_doc["output_contract_source"] = got_c[1]
                for cf in c_fields:
                    if cf not in init_doc:
                        if cf == "limitations":
                            init_doc[cf] = list(init_doc["limits"])
                        elif cf == "uncertainties":
                            init_doc[cf] = list(init_doc["uncertainty"])
                        else:
                            init_doc[cf] = None
            dump_json(init_doc, init_p)
            init_output_info = {"path": str(init_p), "action": "initialized_partial",
                                "contract_fields": c_fields}

    summary = {
        "ok": True,
        "skill_dir": str(HERE.parent),
        "input_dir": str(root),
        "case_id": case_id,
        "output_contract_fields": c_fields,
        "output_contract_key": got_c[1] if got_c else None,
        "case_json_keys": list(case.keys()),
        "has_task_md": task_path.exists(),
        "recommended_routes": routes,
        "environment": _probe_env(),
        "files": file_reports,
    }
    if init_output_info is not None:
        summary["init_output"] = init_output_info
    if args.json:
        dump_json(summary, args.json)
    if args.compact:
        brief_files = []
        for fr in file_reports:
            b = {"rel": fr["rel"], "role": fr["role"], "bytes": fr["size_bytes"]}
            sm = fr.get("summary") or {}
            if fr["role"] in ("table", "json_table"):
                b["rows"] = sm.get("n_rows")
                b["cols"] = (sm.get("columns") or [])[:12]
                tot_miss = sum(int(cs.get("missing", 0)) for cs in (sm.get("col_stats") or []))
                if tot_miss:
                    b["missing"] = tot_miss
                if sm.get("sample_rows"):
                    b["row1"] = {k: v for k, v in sm["sample_rows"][0].items() if k != "__line__"}
            elif fr["role"] == "spreadsheet":
                shs = sm.get("sheets") or []
                prevs = sm.get("preview") or []
                b["sheets"] = [s.get("sheet") if isinstance(s, dict) else s for s in shs]
                first_prev = prevs[0] if prevs and isinstance(prevs[0], dict) else (shs[0] if shs and isinstance(shs[0], dict) else None)
                if first_prev:
                    b["first_sheet_cols"] = (first_prev.get("columns") or [])[:12]
                    b["first_sheet_rows"] = first_prev.get("n_rows")
            elif fr["role"] == "pdf":
                b["pages"] = sm.get("n_pages")
                b["figure_pages"] = sm.get("figure_pages") or {}
            elif fr["role"] == "svg":
                b["viewBox"] = sm.get("viewBox")
                b["n_texts"] = sm.get("n_texts")
            elif fr["role"] == "pptx":
                b["slides"] = sm.get("n_slides")
            elif fr["role"] == "image":
                b["size_px"] = sm.get("size_px")
                b["mode"] = sm.get("mode")
            elif fr["role"] == "docx":
                b["paragraphs"] = sm.get("n_paragraphs")
            brief_files.append(b)
        compact_out = {
            "ok": True, "skill_dir": str(HERE.parent), "case_id": case_id,
            "output_contract_fields": c_fields,
            "cjk_font": summary["environment"].get("cjk_font"),
            "recommended_routes": routes,
            "files": brief_files,
            "full_report": args.json,
        }
        if init_output_info is not None:
            compact_out["init_output"] = init_output_info
        print(json.dumps(compact_out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
