#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""table_probe.py — 零依赖数据表探针与加载器（支持 CSV / TSV / JSON / XLSX）。
供 Agent 一键摸清源数据列名、行数、前几行样本与数值摘要，并被 chart_kit.py 复用实现直连源表绘图。
XLSX 优先尝试 openpyxl，无依赖时自动降级纯标准库 zipfile+XML 解析。

用法: python3 table_probe.py /input/data.xlsx [--sheet Sheet1] [--head 5]
"""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _col_idx(cell_ref):
    m = re.match(r"([A-Za-z]+)", str(cell_ref or ""))
    if not m:
        return 0
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _read_xlsx_stdlib(path, sheet=None, skip_rows=0):
    """纯标准库读取 .xlsx（支持 sharedStrings、inlineStr、多 sheet）。"""
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if si.tag.endswith("}si") or si.tag == "si":
                    shared.append("".join(t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t"))
        sheets = []
        if "xl/workbook.xml" in names:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rr = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                for rel in rr:
                    rid = rel.get("Id")
                    tgt = rel.get("Target", "")
                    if rid:
                        clean = tgt.lstrip("/")
                        rels[rid] = clean if clean.startswith("xl/") else "xl/" + clean
            for sh in wb.iter():
                if sh.tag.endswith("}sheet") or sh.tag == "sheet":
                    sname = sh.get("name", "Sheet1")
                    rid = None
                    for k, v in sh.attrib.items():
                        if k.endswith("}id") or k == "r:id":
                            rid = v
                    target = rels.get(rid) or ("xl/worksheets/sheet%d.xml" % (len(sheets) + 1))
                    sheets.append((sname, target))
        if not sheets:
            ws = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            sheets = [("Sheet%d" % (i + 1), w) for i, w in enumerate(ws)]
        chosen_name, chosen_xml = sheets[0]
        if sheet is not None:
            for idx, (sn, sx) in enumerate(sheets):
                if sn == str(sheet) or str(idx) == str(sheet):
                    chosen_name, chosen_xml = sn, sx
                    break
        raw_rows = []
        if chosen_xml in names:
            ws_root = ET.fromstring(zf.read(chosen_xml))
            for row in ws_root.iter():
                if not (row.tag.endswith("}row") or row.tag == "row"):
                    continue
                vals = {}
                col_cursor = 0
                for c in row:
                    if not (c.tag.endswith("}c") or c.tag == "c"):
                        continue
                    cref = c.get("r")
                    ci = _col_idx(cref) if cref else col_cursor
                    col_cursor = ci + 1
                    ct = c.get("t", "")
                    v_el = next((ch for ch in c if ch.tag.endswith("}v") or ch.tag == "v"), None)
                    is_el = next((ch for ch in c if ch.tag.endswith("}is") or ch.tag == "is"), None)
                    val = ""
                    if ct == "s" and v_el is not None and (v_el.text or "").isdigit():
                        si = int(v_el.text)
                        val = shared[si] if si < len(shared) else ""
                    elif ct == "inlineStr" and is_el is not None:
                        val = "".join(t.text or "" for t in is_el.iter() if t.tag.endswith("}t") or t.tag == "t")
                    elif ct == "e":
                        val = ""
                    elif v_el is not None and v_el.text is not None:
                        val = v_el.text
                    vals[ci] = val
                if vals:
                    mx = max(vals.keys())
                    raw_rows.append([vals.get(i, "") for i in range(mx + 1)])
        return _rows_to_records(raw_rows, skip_rows=skip_rows), [s[0] for s in sheets], chosen_name


MISSING_TOKENS = {
    "", "na", "n/a", "nan", "nd", "n.d.", "null", "none", "-", "--", "—", "missing",
    "#n/a", "#div/0!", "#value!", "#ref!", "#name?", "#num!", "#null!",
}


def is_missing(v):
    if v is None:
        return True
    s = str(v).strip()
    if s.lower() in MISSING_TOKENS:
        return True
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return True
    return False


_PM_PAT = re.compile(
    r"^\s*([+-]?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(?:±|\+/-|\+\-)\s*(\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(%?)\s*$"
)


def _norm_num_str(s):
    return (
        str(s).strip()
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\uff0d", "-")
        .replace("\uff0b", "+")
        .replace("\uff05", "%")
    )


def parse_val_err(v):
    """ faithful 解析科研表格中的 '均值 ± 误差'（如 '42.5 ± 3.1' 或 '−2.3 +/- 0.4%'），返回 (val, err, is_pct) 或 (None, None, False)。"""
    if is_missing(v) or isinstance(v, (int, float, bool)):
        return None, None, False
    m = _PM_PAT.match(_norm_num_str(v))
    if not m:
        return None, None, False
    a, _ = parse_num(m.group(1))
    b, _ = parse_num(m.group(2))
    if a is None or b is None or b < 0:
        return None, None, False
    return a, b, bool(m.group(3))


_SUP_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_SCI_PAT = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*(?:[×xX\*]|·)\s*10\s*\^?\s*([+-]?\d+)\s*$"
)
_POW10_PAT = re.compile(r"^\s*10\s*\^?\s*([+-]?\d+)\s*$")


def parse_num(v):
    """宽容解析科研数值（支持 Unicode 负号 −/–、科学计数 3.4×10⁻⁴ / 10^-5、千分位逗号、尾随%），缺失/非法返回 (None, False)。"""
    if is_missing(v):
        return None, False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        fv = float(v)
        return (None, False) if (math.isnan(fv) or math.isinf(fv)) else (fv, False)
    s = _norm_num_str(v).translate(_SUP_MAP)
    pct = False
    if s.endswith("%") and len(s) > 1:
        s = s[:-1].strip()
        pct = True
    if "," in s and re.match(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$", s):
        s = s.replace(",", "")
    m_sci = _SCI_PAT.match(s)
    if m_sci:
        s = "%se%s" % (m_sci.group(1), m_sci.group(2))
    else:
        m_p10 = _POW10_PAT.match(s)
        if m_p10:
            s = "1e%s" % m_p10.group(1)
    try:
        fv = float(s)
        if math.isnan(fv) or math.isinf(fv):
            return None, False
        return fv, pct
    except Exception:
        return None, False


def resolve_col(columns, wanted, allow_none=False):
    """容错解析源表列名：精确匹配 → 去空白大小写匹配 → 唯一字母数字归一化匹配；缺失时抛出含真实列名清单的 ValueError。"""
    if wanted is None or str(wanted).strip() == "":
        return None if allow_none else ""
    w = str(wanted)
    cols = [str(c) for c in (columns or [])]
    if w in cols:
        return w
    ws = w.strip().lower()
    ci = [c for c in cols if c.strip().lower() == ws]
    if len(ci) == 1:
        return ci[0]
    wn = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", ws)
    if wn:
        nm = [c for c in cols if re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", c.strip().lower()) == wn]
        if len(nm) == 1:
            return nm[0]
    raise ValueError("源表不存在列 %r，可用列: %s" % (wanted, cols))


_FOOTNOTE_PREFIXES = ("note", "notes", "source", "注", "说明", "备注", "*", "†", "‡", "#")


def _rows_to_records(raw_rows, skip_rows=0):
    cleaned = [r for r in raw_rows if any(str(x).strip() != "" for x in r)]
    if skip_rows and skip_rows > 0:
        cleaned = cleaned[skip_rows:]
    banners = []
    # 论文补充材料表格常见前1-3行为 # 注释或单格表题/单位说明，后接真正多列表头
    for _ in range(3):
        if len(cleaned) < 2:
            break
        nz0 = [str(x).strip() for x in cleaned[0] if str(x).strip() != ""]
        nz1 = [str(x).strip() for x in cleaned[1] if str(x).strip() != ""]
        if (nz0 and nz0[0].startswith("#")) or (len(nz0) == 1 and len(nz1) >= 2):
            banners.append(" ".join(nz0))
            cleaned = cleaned[1:]
        else:
            break
    banner = " | ".join(banners) if banners else None
    if not cleaned:
        return [], [], banner, [], []
    raw_h = [str(h).strip() or ("col_%d" % i) for i, h in enumerate(cleaned[0])]
    seen, headers, renamed = {}, [], []
    for h in raw_h:
        cnt = seen.get(h, 0) + 1
        seen[h] = cnt
        if cnt == 1:
            headers.append(h)
        else:
            nh = "%s_%d" % (h, cnt)
            headers.append(nh)
            renamed.append("%s->%s" % (h, nh))
    data_rows = cleaned[1:]
    # 剥离多列表格末尾单格表注/来源说明行，避免混入数据序列
    footnotes = []
    if len(headers) >= 2:
        while data_rows:
            nz = [str(x).strip() for x in data_rows[-1] if str(x).strip() != ""]
            if len(nz) == 1 and nz[0].lower().startswith(_FOOTNOTE_PREFIXES):
                footnotes.insert(0, nz[0])
                data_rows.pop()
            else:
                break
    recs = []
    for r in data_rows:
        d = {}
        for i, h in enumerate(headers):
            d[h] = r[i] if i < len(r) else ""
        recs.append(d)
    return headers, recs, banner, renamed, footnotes


def load_table(path, sheet=None, skip_rows=0):
    """加载 CSV/TSV/JSON/XLSX，返回 dict(columns, rows, sheets, sheet, sha256, banner, renamed_headers)。"""
    p = Path(path)
    ext = p.suffix.lower()
    sha = file_sha256(p)
    if ext in (".csv", ".tsv", ".txt"):
        txt = p.read_text(encoding="utf-8-sig", errors="replace")
        lines = txt.splitlines()
        if not lines:
            return {"columns": [], "rows": [], "sheets": [], "sheet": None, "sha256": sha, "banner": None, "renamed_headers": []}
        sample_lines = [ln for ln in lines[:10] if ln.strip() and not ln.strip().startswith("#")]
        # 取首个包含常见分隔符的候选行（避开前1-2行单格表题）
        probe_line = next((ln for ln in sample_lines if any(d in ln for d in ("\t", ",", ";"))), sample_lines[0] if sample_lines else lines[0])
        if ext == ".tsv":
            delim = "\t"
        elif "\t" in probe_line and "," not in probe_line:
            delim = "\t"
        elif "," in probe_line:
            delim = ","
        elif "\t" in probe_line:
            delim = "\t"
        elif ";" in probe_line:
            delim = ";"
        else:
            delim = ","
        reader = csv.reader(lines, delimiter=delim)
        cols, rows, banner, renamed, footnotes = _rows_to_records(list(reader), skip_rows=skip_rows)
        return {"columns": cols, "rows": rows, "sheets": [], "sheet": None, "sha256": sha,
                "banner": banner, "renamed_headers": renamed, "footnotes": footnotes}
    if ext == ".json":
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            cols = list(obj[0].keys())
            return {"columns": cols, "rows": obj, "sheets": [], "sheet": None, "sha256": sha, "banner": None, "renamed_headers": [], "footnotes": []}
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return {"columns": list(v[0].keys()), "rows": v, "sheets": [], "sheet": None, "sha256": sha, "banner": None, "renamed_headers": [], "footnotes": []}
        raise ValueError("JSON 顶层不是记录数组")
    if ext == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
            snames = list(wb.sheetnames)
            sname = str(sheet) if (sheet and str(sheet) in snames) else snames[0]
            ws = wb[sname]
            raw = [[("" if v is None else v) for v in row] for row in ws.iter_rows(values_only=True)]
            wb.close()
            cols, rows, banner, renamed, footnotes = _rows_to_records(raw, skip_rows=skip_rows)
            return {"columns": cols, "rows": rows, "sheets": snames, "sheet": sname, "sha256": sha,
                    "banner": banner, "renamed_headers": renamed, "footnotes": footnotes}
        except Exception:
            (cols, rows, banner, renamed, footnotes), snames, sname = _read_xlsx_stdlib(p, sheet=sheet, skip_rows=skip_rows)
            return {"columns": cols, "rows": rows, "sheets": snames, "sheet": sname, "sha256": sha,
                    "banner": banner, "renamed_headers": renamed, "footnotes": footnotes}
    raise ValueError("不支持的表格格式: %s" % ext)


def summarize(tbl, head=5):
    cols, rows = tbl["columns"], tbl["rows"]
    col_stats = {}
    for c in cols:
        nums, pm_vals, non_empty, missing, pct_cnt = [], [], 0, 0, 0
        for r in rows:
            v = r.get(c, "")
            if is_missing(v):
                missing += 1
                continue
            non_empty += 1
            fv, is_pct = parse_num(v)
            if fv is not None:
                nums.append(fv)
                if is_pct:
                    pct_cnt += 1
            else:
                pv, pe, pp = parse_val_err(v)
                if pv is not None:
                    pm_vals.append((pv, pe))
                    if pp:
                        pct_cnt += 1
        if pm_vals and (len(nums) + len(pm_vals)) >= max(1, int(non_empty * 0.6)):
            all_v = nums + [x[0] for x in pm_vals]
            st = {"type": "numeric_pm", "n": len(all_v), "pm_cells": len(pm_vals),
                  "missing": missing, "min": min(all_v), "max": max(all_v),
                  "note": "含 均值±误差 单元格，chart_kit 可直连自动拆分为 y 与 yerr"}
            if pct_cnt:
                st["percent_stripped"] = pct_cnt
            col_stats[c] = st
        elif nums and len(nums) >= max(1, int(non_empty * 0.6)):
            snums = sorted(nums)
            mid = len(snums) // 2
            med = snums[mid] if len(snums) % 2 == 1 else (snums[mid - 1] + snums[mid]) / 2.0
            mu = sum(nums) / len(nums)
            sd = math.sqrt(sum((x - mu) ** 2 for x in nums) / (len(nums) - 1)) if len(nums) > 1 else 0.0
            st = {"type": "numeric", "n": len(nums), "missing": missing,
                  "min": min(nums), "max": max(nums), "mean": round(mu, 6),
                  "median": round(med, 6), "sd": round(sd, 6)}
            if pct_cnt:
                st["percent_stripped"] = pct_cnt
            col_stats[c] = st
        else:
            uniq = list(dict.fromkeys(str(r.get(c, "")).strip() for r in rows if not is_missing(r.get(c, ""))))
            col_stats[c] = {"type": "categorical", "n": non_empty, "missing": missing,
                            "unique": len(uniq), "sample": uniq[:6]}
    out = {
        "sha256_12": tbl["sha256"][:12],
        "sheets": tbl["sheets"],
        "sheet": tbl["sheet"],
        "banner_skipped": tbl.get("banner"),
        "n_rows": len(rows),
        "columns": cols,
        "col_stats": col_stats,
        "head": rows[:head],
    }
    if tbl.get("renamed_headers"):
        out["duplicate_headers_renamed"] = tbl["renamed_headers"]
    if tbl.get("footnotes"):
        out["footnotes_skipped"] = tbl["footnotes"]
    return out


def summarize_workbook(path, skip_rows=0, head=3, max_sheets=16):
    """一次探查多工作表 XLSX：返回全部工作表的行列索引或详细统计，免去逐表多次探查。"""
    t0 = load_table(path, sheet=None, skip_rows=skip_rows)
    snames = t0.get("sheets") or []
    if len(snames) <= 1:
        return summarize(t0, head=head)
    idx = {}
    for sn in snames[:max_sheets]:
        try:
            ts = t0 if sn == t0.get("sheet") else load_table(path, sheet=sn, skip_rows=skip_rows)
            idx[sn] = {"n_rows": len(ts["rows"]), "columns": ts["columns"],
                       "banner_skipped": ts.get("banner")}
        except Exception as e:
            idx[sn] = {"error": str(e)}
    out = summarize(t0, head=head)
    out["sheet_index"] = idx
    return out


def main():
    ap = argparse.ArgumentParser(description="探查 CSV/TSV/JSON/XLSX 源数据表")
    ap.add_argument("path", help="表格文件路径")
    ap.add_argument("--sheet", default=None, help="XLSX 工作表名")
    ap.add_argument("--all-sheets", action="store_true", help="一次性输出 XLSX 全部工作表完整统计")
    ap.add_argument("--skip-rows", type=int, default=0, help="跳过前 N 行非空标题行")
    ap.add_argument("--head", type=int, default=5)
    a = ap.parse_args()
    if a.all_sheets:
        t0 = load_table(a.path, sheet=None, skip_rows=a.skip_rows)
        snames = t0.get("sheets") or [t0.get("sheet")]
        res = {"sha256_12": t0["sha256"][:12], "sheets": snames, "details": {}}
        for sn in snames[:16]:
            ts = t0 if sn == t0.get("sheet") else load_table(a.path, sheet=sn, skip_rows=a.skip_rows)
            res["details"][sn or "default"] = summarize(ts, head=a.head)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if not a.sheet and Path(a.path).suffix.lower() in (".xlsx", ".xlsm"):
        print(json.dumps(summarize_workbook(a.path, skip_rows=a.skip_rows, head=a.head), ensure_ascii=False, indent=1))
        return 0
    tbl = load_table(a.path, sheet=a.sheet, skip_rows=a.skip_rows)
    print(json.dumps(summarize(tbl, head=a.head), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
