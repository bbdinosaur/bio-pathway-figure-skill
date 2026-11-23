#!/usr/bin/env python3
"""Compact digest of /input/case.json, task.md, and material inventory.

Usage: python3 ga_intake.py [--case /input/case.json] [--input-dir /input]
Prints bounded JSON: contract fields, task head, CSV/TSV/XLSX headers, SVG
summary (detects source-preserving edit targets on Turn 1), and PDF page-1 +
Figure/Table caption hits.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gaconfig import parse_svg_dims  # noqa: E402


def bound(v, n=240):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s[:n] + (f"...(+{len(s)-n}ch)" if len(s) > n else "")


ROLE_HINTS = {
    "question": ["question", "问题", "背景", "hypothesis", "aim", "目标", "挑战"],
    "method": ["method", "方法", "workflow", "protocol", "screen", "实验", "路线", "mechanism"],
    "results": ["result", "结果", "finding", "data", "数据", "效果", "chart", "figure"],
    "conclusion": ["conclusion", "结论", "takeaway", "implication", "意义", "影响"],
}


def suggest_roles(text: str):
    t = text.lower()
    return [role for role, kws in ROLE_HINTS.items() if any(k in t for k in kws)]


def digest_case(case: dict):
    out = {"keys": sorted(case.keys())}
    for k in ("case_id", "id", "task", "task_type", "workorder", "objective",
              "description", "instructions", "mode"):
        if k in case:
            out[k] = bound(case[k], 2000)
    meta_labels = {k: bound(case[k], 240)
                   for k in ("domain", "field", "topic", "category", "subject", "discipline", "label")
                   if k in case}
    if meta_labels:
        out["_metadata_labels"] = meta_labels
    for k in ("output_contract", "required_outputs", "output_schema",
              "result_contract"):
        if k in case:
            v = case[k]
            if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                out[k] = list(v["properties"].keys())
            else:
                out[k] = (list(v.keys()) if isinstance(v, dict) else
                          (v[:20] if isinstance(v, list) else bound(v, 500)))
    for k in ("materials", "files", "inputs", "attachments", "sources"):
        if k in case and isinstance(case[k], list):
            out[f"_{k}"] = [bound(x, 220) for x in case[k][:16]]
    blob = json.dumps(case, ensure_ascii=False)
    out["_suggested_roles"] = suggest_roles(blob[:5000])
    return out


def _quantile(svals: list[float], q: float) -> float:
    if not svals:
        return 0.0
    if len(svals) == 1:
        return svals[0]
    pos = q * (len(svals) - 1)
    lo = int(math.floor(pos))
    hi = min(len(svals) - 1, lo + 1)
    frac = pos - lo
    return svals[lo] * (1.0 - frac) + svals[hi] * frac


def _num_summary(vals: list[float]) -> dict:
    n = len(vals)
    svals = sorted(vals)
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if n >= 2 else 0.0
    sem = sd / math.sqrt(n) if n >= 2 else 0.0
    out = {
        "n": n,
        "mean": round(mean, 4),
        "sd": round(sd, 4),
        "sem": round(sem, 4),
        "median": round(_quantile(svals, 0.5), 4),
        "q1": round(_quantile(svals, 0.25), 4),
        "q3": round(_quantile(svals, 0.75), 4),
        "min": round(svals[0], 4),
        "max": round(svals[-1], 4),
    }
    if 2 <= n <= 12:
        out["replicates"] = [round(v, 4) for v in vals]
    return out


_REP_COL_RE = re.compile(
    r"^(?:(.+?)(?:[_\s-]+(?:rep(?:licate)?\s*)?|[_\s#-]+)|([A-Za-z][A-Za-z_ -]{0,20}?))(\d+)$",
    re.IGNORECASE,
)
_NON_REP_PREFIXES = {
    "day", "days", "d", "hour", "hours", "hr", "hrs", "h", "min", "mins", "minute",
    "week", "weeks", "wk", "wks", "month", "months", "mo", "year", "years", "yr",
    "time", "t", "tp", "timepoint", "dose", "conc", "concentration", "group", "grp",
    "stage", "phase", "cluster", "pc", "dim", "fig", "figure", "panel", "ch", "channel",
    "bin", "step", "level", "tier", "class", "cohort", "arm", "var", "feat", "feature",
    "col", "column", "row", "gene", "cell", "patient", "donor", "subject", "id",
}


def _parse_num(s: str) -> float | None:
    t = str(s or "").strip()
    if not t:
        return None
    if t.endswith("%"):
        t = t[:-1].strip()
    t = t.replace(",", "")
    try:
        fv = float(t)
        return fv if math.isfinite(fv) else None
    except ValueError:
        return None


_SUMMARY_ROW_RE = re.compile(
    r"^(?:mean|average|avg|sd|std|stdev|sem|se|median|iqr|min|max|sum|total|count|n|"
    r"p[\s._-]?val(?:ue)?s?|padj|p[\s._-]?adj|fdr|q[\s._-]?val(?:ue)?s?|"
    r"t[\s._-]?test|anova|sig(?:nificance)?)$",
    re.IGNORECASE,
)


def _summarize_block(rows: list[list[str]]) -> dict:
    """Summarize a single contiguous table block (auto-skipping 1-cell banners, summary rows & 2-row headers)."""
    if len(rows) < 2:
        return {}
    banner = ""
    start = 0
    while start < min(4, len(rows) - 2):
        non_empty = [c for c in rows[start] if c != ""]
        nxt_non_empty = [c for c in rows[start + 1] if c != ""]
        if len(non_empty) <= 1 and len(nxt_non_empty) >= 2:
            if non_empty:
                banner = (banner + " | " + non_empty[0]).strip(" |")
            start += 1
        else:
            break
    hdr = list(rows[start])
    body = rows[start + 1:]
    if len(body) < 2 or len(hdr) < 2:
        return {}

    # Detect 2-row hierarchical merged headers (e.g. Row 0: ['', 'WT', '', '', 'KO', '', '']; Row 1: ['Day', 'Rep 1', ...])
    if len(body) >= 3:
        r1 = body[0]
        r2 = body[1]
        r1_nonempty = [c for c in r1 if c != ""]
        r1_nums = sum(1 for c in r1_nonempty if _parse_num(c) is not None)
        r2_nums = sum(1 for c in r2 if c != "" and _parse_num(c) is not None)
        hdr_blanks = sum(1 for c in hdr[:max(len(hdr), len(r1))] if c == "")
        if len(r1_nonempty) >= 2 and r1_nums <= max(0, int(0.25 * len(r1_nonempty))) and r2_nums >= 1 and (hdr_blanks >= 1 or len(set(c for c in hdr if c)) < len(r1_nonempty)):
            width = max(len(hdr), len(r1))
            merged_hdr = []
            last_p = ""
            for ci in range(width):
                p_val = hdr[ci] if ci < len(hdr) else ""
                c_val = r1[ci] if ci < len(r1) else ""
                if p_val:
                    last_p = p_val
                elif ci > 0 and last_p and c_val:
                    p_val = last_p
                if p_val and c_val and p_val.lower() != c_val.lower():
                    merged_hdr.append(f"{p_val}_{c_val}")
                else:
                    merged_hdr.append(c_val or p_val or f"col_{ci + 1}")
            hdr = merged_hdr
            body = body[1:]
            if len(body) < 2:
                return {}

    # Separate trailing/embedded statistical summary rows (Mean, SD, SEM, p-value) so they never corrupt replicate stats
    reported_summary: dict[str, dict] = {}
    clean_body = []
    for r in body:
        first_c = next((c.strip() for c in r[:2] if c.strip()), "")
        if first_c and _SUMMARY_ROW_RE.match(first_c):
            row_map = {}
            for ci in range(1, min(len(r), len(hdr))):
                if r[ci] != "":
                    nm = hdr[ci] or f"col_{ci + 1}"
                    fv = _parse_num(r[ci])
                    row_map[nm] = round(fv, 6) if fv is not None else r[ci][:40]
            if row_map:
                reported_summary[first_c] = row_map
            continue
        clean_body.append(r)
    if len(clean_body) >= 2:
        body = clean_body

    num_cols, group_cols, id_cols = [], [], []
    for ci, raw_name in enumerate(hdr[:24]):
        name = raw_name or f"col_{ci + 1}"
        vals = [r[ci] for r in body if ci < len(r) and r[ci] != ""]
        if not vals:
            continue
        fvals = [fv for v in vals if (fv := _parse_num(v)) is not None]
        if len(fvals) >= max(2, int(0.8 * len(vals))):
            num_cols.append((ci, name, fvals))
        else:
            uniq = list(dict.fromkeys(vals))
            if 2 <= len(uniq) <= 16:
                if len(uniq) < len(vals):
                    group_cols.append((ci, name, uniq))
                else:
                    id_cols.append((ci, name, uniq))

    out = {}
    if banner:
        out["banner"] = banner[:120]
    if reported_summary:
        out["reported_summary_rows"] = reported_summary

    cat_cols = group_cols or id_cols
    # Detect wide-format replicate columns (e.g. Vehicle_1..3, Rep1..5; consecutive indices avoid Day 0/7/14)
    rep_groups_raw: dict[str, list[tuple[int, int]]] = {}
    for ci, name, _ in num_cols:
        m = _REP_COL_RE.match(name.strip())
        if m:
            grp_k = (m.group(1) or m.group(2) or "").strip()
            tok = re.split(r"[\s_\-]+", grp_k.lower())[-1] if grp_k else ""
            if grp_k and grp_k.lower() not in _NON_REP_PREFIXES and tok not in _NON_REP_PREFIXES:
                rep_groups_raw.setdefault(grp_k, []).append((int(m.group(3)), ci))
    rep_groups: dict[str, list[int]] = {}
    for k, pairs in rep_groups_raw.items():
        if len(pairs) >= 2:
            nums_s = sorted(p[0] for p in pairs)
            if nums_s == list(range(nums_s[0], nums_s[0] + len(nums_s))):
                rep_groups[k] = [ci for _, ci in sorted(pairs)]
    if rep_groups and len(body) <= 24:
        key_cols = [c[0] for c in cat_cols[:2]] if cat_cols else [0]
        rg_out = {}
        for ri, r in enumerate(body):
            parts = [r[kc] for kc in key_cols if kc < len(r) and r[kc]]
            rkey = " | ".join(parts) if parts else f"row_{ri+1}"
            if rkey in rg_out:
                rkey = f"{rkey} #{ri+1}"
            row_stats = {}
            for gname, idxs in list(rep_groups.items())[:8]:
                xs = [fv for ci in idxs if ci < len(r) and (fv := _parse_num(r[ci])) is not None]
                if xs:
                    row_stats[gname] = _num_summary(xs)
            if row_stats:
                rg_out[rkey] = row_stats
        if rg_out:
            out["wide_replicate_stats"] = rg_out

    if group_cols and num_cols:
        # Support 2-factor biological designs (e.g. Genotype x Treatment) cleanly
        if len(group_cols) >= 2:
            c0, c1 = group_cols[0], group_cols[1]
            combos = list(dict.fromkeys(
                f"{r[c0[0]]} | {r[c1[0]]}"
                for r in body
                if c0[0] < len(r) and c1[0] < len(r) and r[c0[0]] and r[c1[0]]
            ))
            if len(combos) > len(c0[2]) and len(combos) <= 16:
                gname = f"{c0[1]} | {c1[1]}"
                grouped = {}
                for gv in combos:
                    v0, v1 = gv.split(" | ", 1)
                    gdict = {}
                    for nci, nname, _ in num_cols[:6]:
                        xs = [fv for r in body
                              if c0[0] < len(r) and c1[0] < len(r) and nci < len(r)
                              and r[c0[0]] == v0 and r[c1[0]] == v1
                              and (fv := _parse_num(r[nci])) is not None]
                        if xs:
                            gdict[nname] = _num_summary(xs)
                    if gdict:
                        grouped[gv] = gdict
                if grouped:
                    out["grouped_by"] = gname
                    out["group_stats"] = grouped
        if "group_stats" not in out:
            gci, gname, gunique = group_cols[0]
            grouped = {}
            for gv in gunique:
                gdict = {}
                for nci, nname, _ in num_cols[:6]:
                    xs = []
                    for r in body:
                        if gci < len(r) and nci < len(r) and r[gci] == gv:
                            fv = _parse_num(r[nci])
                            if fv is not None:
                                xs.append(fv)
                    if xs:
                        gdict[nname] = _num_summary(xs)
                if gdict:
                    grouped[gv] = gdict
            if grouped:
                out["grouped_by"] = gname
                out["group_stats"] = grouped
    elif num_cols:
        out["col_stats"] = {nname: _num_summary(fv) for _, nname, fv in num_cols[:8]}
        if id_cols:
            out["row_labels"] = id_cols[0][2][:16]
    return out


def _summarize_rows(parsed: list[list[str]]) -> dict:
    """Compute grouped/column/wide-replicate numeric stats, splitting stacked subtables on blank rows."""
    norm = [[str(c).strip() if c is not None else "" for c in r] for r in parsed]
    blocks: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for r in norm:
        if any(r):
            cur.append(r)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    if not blocks:
        return {}
    if len(blocks) == 1:
        return _summarize_block(blocks[0])
    subs = [sb for blk in blocks[:8] if (sb := _summarize_block(blk))]
    if not subs:
        return {}
    if len(subs) == 1:
        return subs[0]
    return {"subtables": subs}


def table_preview(p: Path, max_rows: int = 4, bound_ch: int = 180):
    try:
        raw_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        non_empty = [ln for ln in raw_lines if ln.strip()]
        if not non_empty:
            return None
        rows_txt = non_empty[: max_rows + 1]
        out_str = " | ".join(r[:bound_ch] for r in rows_txt)
        tail = f" ...(+{len(non_empty)-max_rows-1} rows)" if len(non_empty) > max_rows + 1 else ""
        info = {"rows": len(non_empty), "head": out_str[: bound_ch * (max_rows + 1)] + tail}
        if 2 <= len(non_empty) <= 2005:
            delim = "\t" if p.suffix.lower() == ".tsv" else ","
            parsed = [list(csv.reader([ln], delimiter=delim))[0] if ln.strip() else [] for ln in raw_lines[:2010]]
            info.update(_summarize_rows(parsed))
        return info
    except Exception:
        return None


def _col_letters_to_idx(ref: str) -> int:
    col = 0
    for ch in ref:
        if "A" <= ch <= "Z":
            col = col * 26 + (ord(ch) - 64)
        elif "a" <= ch <= "z":
            col = col * 26 + (ord(ch) - 96)
        else:
            break
    return max(0, col - 1)


def _read_xlsx_stdlib(p: Path, max_sheets: int = 10, max_rows: int = 505, max_cols: int = 14) -> dict[str, list[list[str]]]:
    """Zero-dependency pure-stdlib XLSX reader (zipfile + ElementTree)."""
    sheets_out: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(p, "r") as zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.iter():
                if si.tag.endswith("}si") or si.tag == "si":
                    shared.append("".join(
                        t.text or "" for t in si.iter()
                        if t.tag.endswith("}t") or t.tag == "t"
                    ))
        # Map sheet display names -> target worksheet paths
        rel_map: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rr = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rr:
                rid, tgt = rel.get("Id"), rel.get("Target")
                if rid and tgt:
                    tgt = tgt.lstrip("/")
                    if not tgt.startswith("xl/"):
                        tgt = "xl/" + tgt
                    rel_map[rid] = tgt
        sheet_entries: list[tuple[str, str]] = []
        if "xl/workbook.xml" in names:
            wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
            for sh in wb_root.iter():
                if sh.tag.endswith("}sheet") or sh.tag == "sheet":
                    sname = sh.get("name") or f"Sheet{len(sheet_entries)+1}"
                    rid = None
                    for k, v in sh.attrib.items():
                        if k.endswith("}id") or k == "r:id":
                            rid = v
                            break
                    tgt = rel_map.get(rid or "")
                    if tgt and tgt in names:
                        sheet_entries.append((sname, tgt))
        if not sheet_entries:
            ws_files = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            sheet_entries = [(Path(wf).stem, wf) for wf in ws_files]

        for sname, tgt in sheet_entries[:max_sheets]:
            ws_root = ET.fromstring(zf.read(tgt))
            # Parse horizontal merged header ranges (rows 1..4) so merged group banners stay exact
            h_merges: dict[tuple[int, int], tuple[int, int]] = {}  # (rnum, ci) -> (rnum, start_ci)
            for mc in ws_root.iter():
                if not (mc.tag.endswith("}mergeCell") or mc.tag == "mergeCell"):
                    continue
                mref = mc.get("ref", "")
                mm = re.fullmatch(r"([A-Za-z]+)(\d+):([A-Za-z]+)(\d+)", mref.strip())
                if mm:
                    r0, r1 = int(mm.group(2)), int(mm.group(4))
                    c0, c1 = _col_letters_to_idx(mm.group(1)), _col_letters_to_idx(mm.group(3))
                    if r0 == r1 and r0 <= 6 and c1 > c0:
                        for cc in range(c0 + 1, min(c1 + 1, max_cols)):
                            h_merges[(r0, cc)] = (r0, c0)
            rows_parsed: list[list[str]] = []
            prev_rnum: int | None = None
            for row_el in ws_root.iter():
                if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
                    continue
                if len(rows_parsed) >= max_rows:
                    break
                r_attr = row_el.get("r", "")
                rnum = int(r_attr) if r_attr.isdigit() else None
                if rnum is not None and prev_rnum is not None and rnum > prev_rnum + 1:
                    rows_parsed.append([])
                row_vals: dict[int, str] = {}
                cur_col = 0
                for c_el in row_el:
                    if not (c_el.tag.endswith("}c") or c_el.tag == "c"):
                        continue
                    ref = c_el.get("r", "")
                    ci = _col_letters_to_idx(ref) if ref else cur_col
                    cur_col = ci + 1
                    if ci >= max_cols:
                        continue
                    ctype = c_el.get("t", "")
                    val = ""
                    if ctype == "inlineStr":
                        val = "".join(t.text or "" for t in c_el.iter()
                                      if t.tag.endswith("}t") or t.tag == "t")
                    else:
                        v_el = next((ch for ch in c_el if ch.tag.endswith("}v") or ch.tag == "v"), None)
                        raw_v = (v_el.text or "").strip() if v_el is not None else ""
                        if ctype == "s" and raw_v.isdigit():
                            idx = int(raw_v)
                            val = shared[idx] if 0 <= idx < len(shared) else raw_v
                        elif ctype == "b":
                            val = "TRUE" if raw_v == "1" else "FALSE"
                        else:
                            val = raw_v
                    row_vals[ci] = val[:80]
                if rnum is not None and row_vals:
                    for (mr, mc_i), (_, src_ci) in h_merges.items():
                        if mr == rnum and src_ci in row_vals and row_vals[src_ci] and not row_vals.get(mc_i):
                            row_vals[mc_i] = row_vals[src_ci]
                if row_vals:
                    width = min(max_cols, max(row_vals.keys()) + 1)
                    rows_parsed.append([row_vals.get(i, "") for i in range(width)])
                    if rnum is not None:
                        prev_rnum = rnum
            sheets_out[sname] = rows_parsed
    return sheets_out


def read_xlsx_sheets(p: Path, max_sheets: int = 16, max_rows: int = 505, max_cols: int = 24) -> dict[str, list[list[str]]]:
    """Read XLSX sheets with merged-header support (stdlib XML primary, openpyxl fallback)."""
    try:
        res = _read_xlsx_stdlib(p, max_sheets=max_sheets, max_rows=max_rows, max_cols=max_cols)
        if res:
            return res
    except Exception:
        pass
    try:
        import openpyxl  # optional fallback for exotic XLSX
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        out = {}
        for name in wb.sheetnames[:max_sheets]:
            ws = wb[name]
            all_rows = []
            for ri, row in enumerate(ws.iter_rows(values_only=True)):
                if ri >= max_rows:
                    break
                all_rows.append([str(c)[:80] if c is not None else "" for c in row[:max_cols]])
            out[name] = all_rows
        wb.close()
        return out
    except Exception:
        return {}


def _compact_sheet_index(sheets_info: dict) -> dict:
    """Tiny per-sheet index (rows, header, group names) for bounded Turn-1 stdout."""
    idx = {}
    for sname, sdata in sheets_info.items():
        if not isinstance(sdata, dict):
            continue
        hd = sdata.get("head") or []
        ent = {"rows": sdata.get("rows", 0), "head": hd[:2]}
        if sdata.get("grouped_by"):
            ent["grouped_by"] = sdata["grouped_by"]
            ent["groups"] = list((sdata.get("group_stats") or {}).keys())[:10]
        elif sdata.get("wide_replicate_stats"):
            ent["wide_rows"] = list(sdata["wide_replicate_stats"].keys())[:10]
        elif sdata.get("subtables"):
            ent["subtables"] = [st.get("banner") or st.get("grouped_by") or f"sub_{i+1}"
                                for i, st in enumerate(sdata["subtables"][:6])]
        idx[sname] = ent
    return idx


def _compact_table_index(tdata: dict) -> dict:
    if not isinstance(tdata, dict):
        return tdata
    ent = {"rows": tdata.get("rows", 0), "cols": tdata.get("cols", 0),
           "head": (tdata.get("head") or [])[:3]}
    if tdata.get("grouped_by"):
        ent["grouped_by"] = tdata["grouped_by"]
        ent["groups"] = list((tdata.get("group_stats") or {}).keys())[:12]
    elif tdata.get("wide_replicate_stats"):
        ent["wide_rows"] = list(tdata["wide_replicate_stats"].keys())[:12]
    elif tdata.get("col_stats"):
        ent["numeric_cols"] = list(tdata["col_stats"].keys())[:12]
    return ent


def _is_target_sheet(sname: str, target_figs: list[int]) -> bool:
    if not target_figs:
        return False
    low = sname.lower()
    for fn in target_figs:
        if re.search(rf"(?:fig(?:ure)?\.?\s*0*{fn}\b|\b0*{fn}[a-h]\b)", low):
            return True
    return False


def _fit_stdout_budget(out: dict, max_bytes: int, saved_path: str | None = None) -> str:
    """Guarantee valid bounded Turn-1 stdout (<= max_bytes) without EVER dropping case/PDF/SVG."""
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    slim = json.loads(json.dumps(out))
    target_figs = slim.get("_target_figures_detected") or []
    compacted_files = []
    # Pass 0.5: if target figures detected, compact ONLY non-target XLSX sheets first
    if target_figs:
        for ent in slim.get("input_files", []):
            if isinstance(ent.get("sheets"), dict):
                keep_s, comp_s = {}, {}
                for sname, sdata in ent["sheets"].items():
                    if _is_target_sheet(sname, target_figs):
                        keep_s[sname] = sdata
                    else:
                        comp_s[sname] = sdata
                if keep_s and comp_s:
                    ent["sheets"] = keep_s
                    ent["other_sheets_index"] = _compact_sheet_index(comp_s)
                    compacted_files.append(ent.get("f", ""))
        if compacted_files:
            slim["_table_hint"] = (
                "Non-target spreadsheet sheets compacted; target-figure sheets kept expanded. "
                "Use `ga_intake.py --table <path> --sheet <name>` for any other sheet."
            )
            if saved_path:
                slim["_full_intake_saved"] = saved_path
        txt = json.dumps(slim, ensure_ascii=False, indent=1)
        if len(txt.encode("utf-8")) <= max_bytes:
            return txt
    # Pass 1: compact all remaining verbose XLSX sheets into concise sheet indices
    for ent in slim.get("input_files", []):
        if isinstance(ent.get("sheets"), dict):
            prev_idx = ent.pop("other_sheets_index", {})
            merged_idx = _compact_sheet_index(ent.pop("sheets"))
            merged_idx.update(prev_idx)
            ent["sheets_index"] = merged_idx
            compacted_files.append(ent.get("f", ""))
    if compacted_files:
        slim["_table_hint"] = (
            "Large spreadsheet(s) compacted to sheets_index to avoid stdout truncation. "
            "Run `ga_intake.py --table <path> --sheet <name>` for exact mean/sd/sem/replicates."
        )
        if saved_path:
            slim["_full_intake_saved"] = saved_path
    txt = json.dumps(slim, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 2: compact large CSV/TSV stats into headers + group names
    for ent in slim.get("input_files", []):
        if isinstance(ent.get("table"), dict) and len(json.dumps(ent["table"], ensure_ascii=False)) > 1200:
            ent["table_index"] = _compact_table_index(ent.pop("table"))
            compacted_files.append(ent.get("f", ""))
    txt = json.dumps(slim, ensure_ascii=False, indent=1)
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 3: tighten secondary PDF captions & task_md while keeping case + target_figure_deep intact
    if isinstance(slim.get("task_md"), str) and len(slim["task_md"]) > 2000:
        slim["task_md"] = slim["task_md"][:2000] + "..."
    for ent in slim.get("input_files", []):
        if isinstance(ent.get("pdf"), dict):
            pv = ent["pdf"]
            if isinstance(pv.get("captions"), list) and len(pv["captions"]) > 6:
                pv["captions"] = pv["captions"][:6]
            if isinstance(pv.get("p1"), str) and len(pv["p1"]) > 600:
                pv["p1"] = pv["p1"][:600] + "..."
    txt = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    # Pass 4: gracefully trim secondary fields while ALWAYS emitting valid JSON
    for ent in slim.get("input_files", []):
        if isinstance(ent.get("pdf"), dict):
            ent["pdf"].pop("captions", None)
            if isinstance(ent["pdf"].get("target_figure_deep"), list):
                for df in ent["pdf"]["target_figure_deep"]:
                    if isinstance(df.get("full_caption"), dict) and len(df["full_caption"].get("text", "")) > 1000:
                        df["full_caption"]["text"] = df["full_caption"]["text"][:1000] + "..."
                    if isinstance(df.get("citing_excerpts"), list):
                        df["citing_excerpts"] = df["citing_excerpts"][:1]
        if isinstance(ent.get("sheets_index"), dict) and len(ent["sheets_index"]) > 12:
            keys_keep = list(ent["sheets_index"].keys())[:12]
            ent["sheets_index"] = {k: ent["sheets_index"][k] for k in keys_keep}
            ent["sheets_truncated"] = True
    txt = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    if len(txt.encode("utf-8")) <= max_bytes:
        return txt
    slim["input_files"] = [{"f": e.get("f"), "kb": e.get("kb"), "kind": e.get("kind")} for e in slim.get("input_files", [])[:30]]
    return json.dumps(slim, ensure_ascii=False, separators=(",", ":"))


def xlsx_preview(p: Path):
    sheets = read_xlsx_sheets(p, max_sheets=16, max_rows=505, max_cols=24)
    if not sheets:
        return None
    info = {}
    for name, all_rows in sheets.items():
        sheet_info = {
            "rows": len(all_rows),
            "head": [r[:12] for r in all_rows[:4]],
        }
        if 2 <= len(all_rows) <= 505:
            sheet_info.update(_summarize_rows(all_rows))
        info[name] = sheet_info
    return info


def svg_preview(p: Path):
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
        cw, ch = parse_svg_dims(raw)
        root = ET.fromstring(raw)
        layers = [el.get("id") for el in root.iter()
                  if (el.tag.endswith("}g") or el.tag == "g") and el.get("id")][:12]
        txts = ["".join(el.itertext()).strip()[:40] for el in root.iter()
                if el.tag.endswith("}text") or el.tag == "text"]
        txts = [t for t in txts if t]
        cols = set()
        for m in re.finditer(r'(?:fill|stroke)\s*[:=]\s*"?(#[0-9a-fA-F]{3,6}|rgb\([^)]+\))', raw[:40000]):
            cols.add(m.group(1))
        return {"dims": [cw, ch], "layers": layers, "n_text": len(txts),
                "sample_texts": txts[:8], "sample_colors": sorted(cols)[:10]}
    except Exception as e:
        return {"error": str(e)[:100]}


def docx_preview(p: Path) -> dict | None:
    """Zero-dependency pure-stdlib DOCX paragraph & table preview."""
    try:
        with zipfile.ZipFile(p, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return None
            root = ET.fromstring(zf.read("word/document.xml"))
        paras = []
        for pel in root.iter():
            if pel.tag.endswith("}p") or pel.tag == "p":
                txt = "".join(t.text or "" for t in pel.iter()
                              if t.tag.endswith("}t") or t.tag == "t").strip()
                if txt:
                    paras.append(txt)
        return {"n_paragraphs": len(paras), "preview": " ".join(paras)[:1200]}
    except Exception:
        return None


def json_file_preview(p: Path) -> dict | None:
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(obj, dict):
            return {"type": "dict", "keys": list(obj.keys())[:24], "sample": bound(obj, 500)}
        if isinstance(obj, list):
            return {"type": "list", "len": len(obj), "head": [bound(x, 180) for x in obj[:4]]}
        return {"type": type(obj).__name__, "value": bound(obj, 240)}
    except Exception:
        return None


_FIG_RE = re.compile(
    r"(?:^|\n)\s*((?:Extended\s+Data\s+|Supplementary\s+)?(?:Figure|Fig\.|Table)\s+\d+[A-Za-z]?"
    r"(?:\s*[:.|–—-]\s*|\s*\n\s*)[^\n]{10,260}(?:\n[^\n]{6,220}){0,8})",
    re.IGNORECASE,
)


def _extract_pdf_text(p: Path) -> tuple[str, int | None]:
    full_txt = ""
    pages = None
    try:
        r = subprocess.run(["pdftotext", str(p), "-"],
                           capture_output=True, text=True, timeout=25)
        if r.returncode == 0 and r.stdout.strip():
            full_txt = r.stdout
            pages = max(1, full_txt.count("\x0c"))
    except Exception:
        pass
    if not full_txt:
        try:
            import fitz  # optional pymupdf fallback
            doc = fitz.open(str(p))
            pages = len(doc)
            full_txt = "\x0c".join(doc[i].get_text() for i in range(min(pages, 40)))
            doc.close()
        except Exception:
            try:
                import pdfplumber  # optional pdfplumber fallback
                with pdfplumber.open(str(p)) as doc:
                    pages = len(doc.pages)
                    full_txt = "\x0c".join((doc.pages[i].extract_text() or "") for i in range(min(pages, 40)))
            except Exception:
                return "", None
    return full_txt, pages


def _img_dims(p: Path) -> list[int] | None:
    """Pure-stdlib PNG/JPEG pixel dimension probe."""
    try:
        raw = p.read_bytes()[:65536]
        if len(raw) >= 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", raw[16:24])
            return [w, h]
        if len(raw) >= 4 and raw[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                m = raw[i + 1]
                if m in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    return [w, h]
                seg = struct.unpack(">H", raw[i + 2:i + 4])[0]
                i += 2 + max(seg, 2)
    except Exception:
        pass
    return None


def _detect_target_figures(text_blob: str) -> list[int]:
    """Detect figure numbers explicitly mentioned in task.md / case.json (e.g. figure03, Fig. 3)."""
    nums = []
    for m in re.finditer(r"\b(?:fig(?:ure)?\.?\s*0*|f)([1-9]\d?)\b", text_blob, re.IGNORECASE):
        raw = m.group(0).lower()
        if raw.startswith("f") and not raw.startswith("fig"):
            continue
        n = int(m.group(1))
        if 1 <= n <= 20 and n not in nums:
            nums.append(n)
    return nums[:4]


def _extract_target_figure_deep(page_chunks: list[str], fig_num: int) -> dict | None:
    """Extract FULL untruncated caption (<=2400 ch) + up to 3 citing Results excerpts for target Fig N."""
    cap_re = re.compile(
        rf"(?:^|\n)\s*((?:Extended\s+Data\s+|Supplementary\s+)?(?:Figure|Fig\.)\s+0*{fig_num}"
        r"(?:\s*[:.|–—-]\s*|\s*\n\s*)[^\n]{8,280}(?:\n(?![ \t]*(?:Figure|Fig\.|Table|Extended\s+Data)\s+\d+)[^\n]{4,240}){0,18})",
        re.IGNORECASE,
    )
    cite_re = re.compile(rf"\b(?:Fig\.|Figure)\s*0*{fig_num}[a-h]?(?:[-–,]\s*[a-h])?\b", re.IGNORECASE)
    full_caption = None
    citations = []
    for pi, chunk in enumerate(page_chunks[:40], start=1):
        if full_caption is None:
            m = cap_re.search(chunk)
            if m:
                full_caption = {"page": pi, "text": " ".join(m.group(1).split())[:2400]}
        if len(citations) < 3:
            for cm in cite_re.finditer(chunk):
                # Skip if inside the caption itself
                if full_caption and full_caption["page"] == pi and cm.start() < 40:
                    continue
                s0 = max(0, cm.start() - 160)
                s1 = min(len(chunk), cm.end() + 360)
                snip = " ".join(chunk[s0:s1].split())
                if full_caption and snip[:60] in full_caption["text"]:
                    continue
                if not any(snip[:50] in prev["text"] for prev in citations):
                    citations.append({"page": pi, "text": snip[:560]})
                    if len(citations) >= 3:
                        break
    if not full_caption and not citations:
        return None
    res = {"figure": fig_num}
    if full_caption:
        res["full_caption"] = full_caption
    if citations:
        res["citing_excerpts"] = citations
    return res


def pdf_preview(p: Path, target_figs: list[int] | None = None):
    """Extract page count, page-1 snippet, section page map, multi-line captions, and target-figure deep digest."""
    full_txt, pages = _extract_pdf_text(p)
    if pages is None:
        return None
    if not full_txt.strip():
        return {"pages": pages, "note": "empty text layer (scanned PDF?)"}
    page_chunks = full_txt.split("\x0c")
    p1 = " ".join(page_chunks[0].split())
    caps = []
    seen = set()
    section_pages = {}
    for pi, chunk in enumerate(page_chunks[:35], start=1):
        low = chunk[:16000].lower()
        for sec, kws in (
            ("abstract", ("abstract",)),
            ("results", ("\nresults", "\n2. results")),
            ("methods", ("\nmethods", "\nmaterials and methods", "\nstar methods")),
            ("discussion", ("\ndiscussion",)),
            ("fig1", ("fig. 1", "figure 1")),
            ("fig2", ("fig. 2", "figure 2")),
            ("fig3", ("fig. 3", "figure 3")),
            ("fig4", ("fig. 4", "figure 4")),
            ("fig5", ("fig. 5", "figure 5")),
            ("fig6", ("fig. 6", "figure 6")),
            ("extended_data", ("extended data", "supplementary figure")),
        ):
            if sec not in section_pages and any(kw in low for kw in kws):
                section_pages[sec] = pi
        for m in _FIG_RE.finditer(chunk[:18000]):
            c = " ".join(m.group(1).split())[:900]
            key = c[:32].lower()
            if key not in seen:
                seen.add(key)
                caps.append({"page": pi, "text": c})
            if len(caps) >= 16:
                break
        if len(caps) >= 16:
            break
    out = {"pages": pages, "p1": p1[:1100] + ("..." if len(p1) > 1100 else "")}
    if section_pages:
        out["section_pages"] = section_pages
    if caps:
        out["captions"] = caps
    if target_figs:
        deep = []
        for fn in target_figs:
            hit = _extract_target_figure_deep(page_chunks, fn)
            if hit:
                deep.append(hit)
        if deep:
            out["target_figure_deep"] = deep
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--input-dir", default="/input")
    ap.add_argument("--pdf", default=None, help="optional single PDF path for --pdf-find or --pdf-pages")
    ap.add_argument("--pdf-find", default=None, help="search regex/term in --pdf and return matching page excerpts")
    ap.add_argument("--pdf-pages", default=None, help="extract specific PDF pages e.g. 2-4 or 3")
    ap.add_argument("--table", default=None, help="extract exact stats/rows from a single CSV/TSV/XLSX file")
    ap.add_argument("--sheet", default=None, help="optional sheet name (or substring) when using --table on XLSX")
    ap.add_argument("--max-bytes", type=int, default=14000, help="hard stdout byte cap for Turn-1 digest (default 14000)")
    ap.add_argument("--save", default=None, help="save full untruncated intake JSON to this path")
    a = ap.parse_args()

    if a.table:
        tp = Path(a.table)
        suf = tp.suffix.lower()
        if not tp.exists():
            print(json.dumps({"error": f"file not found: {tp}"}))
            return 1
        if suf in (".xlsx", ".xlsm"):
            sheets = read_xlsx_sheets(tp, max_sheets=32, max_rows=2000, max_cols=32)
            if not sheets:
                print(json.dumps({"error": f"failed to read sheets from {tp}"}))
                return 1
            if a.sheet:
                q = a.sheet.strip().lower()
                matched = {k: v for k, v in sheets.items() if k.lower() == q}
                if not matched:
                    matched = {k: v for k, v in sheets.items() if q in k.lower()}
                if not matched:
                    print(json.dumps({"error": f"sheet '{a.sheet}' not found", "available": list(sheets.keys())}))
                    return 1
                res_s = {}
                for sname, srows in matched.items():
                    s_info = {"rows": len(srows), "head": [r[:16] for r in srows[:8]]}
                    if len(srows) >= 2:
                        s_info.update(_summarize_rows(srows[:2005]))
                    res_s[sname] = s_info
                print(json.dumps({"file": str(tp), "sheets": res_s}, ensure_ascii=False, indent=1))
            else:
                idx = {}
                for sname, srows in sheets.items():
                    idx[sname] = {"rows": len(srows), "cols": max((len(r) for r in srows[:5]), default=0),
                                  "head": [r[:12] for r in srows[:3]]}
                print(json.dumps({"file": str(tp), "sheets_index": idx,
                                  "hint": "pass --sheet <name> for exact group/replicate stats"},
                                 ensure_ascii=False, indent=1))
            return 0
        else:
            print(json.dumps({"file": str(tp), "table": table_preview(tp)}, ensure_ascii=False, indent=1))
            return 0

    if a.pdf and a.pdf_pages:
        txt, pages = _extract_pdf_text(Path(a.pdf))
        chunks = txt.split("\x0c") if txt else []
        m_rg = re.fullmatch(r"\s*(\d+)(?:\s*[-:,]\s*(\d+))?\s*", str(a.pdf_pages))
        p_lo = int(m_rg.group(1)) if m_rg else 1
        p_hi = int(m_rg.group(2) or p_lo) if m_rg else p_lo
        p_lo, p_hi = max(1, p_lo), min(len(chunks), max(p_lo, p_hi))
        sel = [{"page": pi, "text": bound(" ".join(chunks[pi - 1].split()), 4500)}
               for pi in range(p_lo, p_hi + 1)]
        print(json.dumps({"pdf": a.pdf, "pages": pages, "range": [p_lo, p_hi], "extracted": sel},
                         ensure_ascii=False, indent=1))
        return 0

    if a.pdf and a.pdf_find:
        txt, pages = _extract_pdf_text(Path(a.pdf))
        chunks = txt.split("\x0c") if txt else []
        pat = re.compile(a.pdf_find, re.IGNORECASE)
        hits = []
        for pi, ch in enumerate(chunks, start=1):
            for m in pat.finditer(ch):
                s0, s1 = max(0, m.start() - 250), min(len(ch), m.end() + 550)
                hits.append({"page": pi, "excerpt": " ".join(ch[s0:s1].split())[:900]})
                if len(hits) >= 10:
                    break
            if len(hits) >= 10:
                break
        print(json.dumps({"pdf": a.pdf, "pages": pages, "query": a.pdf_find, "hits": hits},
                         ensure_ascii=False, indent=1))
        return 0

    out = {}
    task_blob_parts = []
    cp = Path(a.case)
    if cp.exists():
        try:
            raw_case = cp.read_text(encoding="utf-8")
            task_blob_parts.append(raw_case[:6000])
            out["case"] = digest_case(json.loads(raw_case))
        except Exception as e:
            out["case_error"] = (f"{type(e).__name__}: {e}; raw head: "
                                 + bound(cp.read_text(encoding="utf-8", errors="ignore"), 300))
    else:
        out["case"] = f"NOT FOUND at {cp}"

    ind = Path(a.input_dir)
    task_md = ind / "task.md"
    if task_md.exists():
        t_raw = task_md.read_text(encoding="utf-8", errors="ignore")
        task_blob_parts.append(t_raw[:6000])
        out["task_md"] = bound(t_raw, 4000)

    target_figs = _detect_target_figures("\n".join(task_blob_parts))
    if target_figs:
        out["_target_figures_detected"] = target_figs

    if ind.exists():
        files = []
        has_svg = False
        has_pdf = False
        for p in sorted(ind.rglob("*")):
            if not p.is_file():
                continue
            kind = p.suffix.lower().lstrip(".") or "?"
            ent = {"f": str(p), "kb": round(p.stat().st_size / 1024, 1), "kind": kind}
            if kind in ("csv", "tsv"):
                ent["table"] = table_preview(p)
            elif kind in ("xlsx", "xlsm"):
                xp = xlsx_preview(p)
                if xp:
                    ent["sheets"] = xp
            elif kind == "svg":
                has_svg = True
                ent["svg_summary"] = svg_preview(p)
            elif kind == "pdf":
                has_pdf = True
                pv = pdf_preview(p, target_figs=target_figs)
                if pv:
                    ent["pdf"] = pv
            elif kind == "docx":
                dp = docx_preview(p)
                if dp:
                    ent["docx"] = dp
            elif kind == "json" and p.resolve() != cp.resolve():
                jp = json_file_preview(p)
                if jp:
                    ent["json"] = jp
            elif kind in ("png", "jpg", "jpeg"):
                dm = _img_dims(p)
                if dm:
                    ent["dims"] = dm
            elif kind in ("txt", "md", "yaml", "yml") and p.name != "task.md":
                ent["preview"] = bound(p.read_text(encoding="utf-8", errors="ignore"), 500)
            files.append(ent)
        out["input_files"] = files[:40]
        out["n_files"] = len(files)
        if has_svg:
            out["_hint"] = "Input contains SVG file(s): check if workorder requests source-preserving edit (use ga_svg_edit.py --inspect)."
        if has_pdf and isinstance(out.get("case"), dict) and out["case"].get("_metadata_labels"):
            out["_grounding_reminder"] = (
                "Verify case._metadata_labels against actual PDF p1/captions; "
                "treat primary PDF & data files as sole source of truth and document any label mismatch in uncertainty."
            )
    saved_path = None
    save_target = Path(a.save) if a.save else (Path("/app/work/_intake_full.json") if Path("/app/work").is_dir() else None)
    if save_target is not None:
        try:
            save_target.parent.mkdir(parents=True, exist_ok=True)
            save_target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            saved_path = str(save_target)
        except Exception:
            saved_path = None
    print(_fit_stdout_budget(out, max(4000, int(a.max_bytes)), saved_path=saved_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
