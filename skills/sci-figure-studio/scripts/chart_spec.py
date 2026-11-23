#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_spec.py — 面板 spec 解析与数据准备（无 pandas 依赖）。
支持 tidy CSV/TSV/JSON/内联表、原始重复观测自动聚合(mean±SD/SEM)、连续数值 X 轴、箱线图 tidy 表与热图；
统一产出 payload + 元素级 provenance 映射，缺失值如实记录不编造。"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_common import read_table, to_num, sha256_of  # noqa: E402

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#F0E442", "#000000"]

PRESETS = {  # 宽度(mm), 基准字号(pt), 面板高(mm)
    "journal_single": {"width_mm": 89, "font_pt": 8, "panel_h_mm": 55},
    "journal_double": {"width_mm": 183, "font_pt": 8, "panel_h_mm": 55},
    "thesis":         {"width_mm": 140, "font_pt": 10.5, "panel_h_mm": 70},
    "ppt_16x9":       {"width_mm": 254, "font_pt": 14, "panel_h_mm": 95},
}


def _read_xlsx_stdlib(fpath, sheet_name=None):
    """零外部依赖纯标准库读取 .xlsx（zipfile + XML），在无 openpyxl 时兜底。"""
    import re
    import zipfile
    import xml.etree.ElementTree as ET

    def _col_idx(ref):
        m = re.match(r"([A-Za-z]+)", ref or "")
        if not m:
            return 0
        idx = 0
        for ch in m.group(1).upper():
            idx = idx * 26 + (ord(ch) - 64)
        return idx - 1

    with zipfile.ZipFile(str(fpath), "r") as zf:
        names = set(zf.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot:
                if si.tag.endswith("si"):
                    shared.append("".join(si.itertext()))
        # 解析工作表名称与 target 路径
        sheet_targets = []
        if "xl/workbook.xml" in names:
            wbroot = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rroot = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                for rel in rroot:
                    rid = rel.get("Id")
                    tgt = rel.get("Target", "").lstrip("/")
                    if rid:
                        rels[rid] = tgt if tgt.startswith("xl/") else f"xl/{tgt}"
            for el in wbroot.iter():
                if el.tag.endswith("sheet"):
                    nm = el.get("name", "Sheet1")
                    rid = next((v for k, v in el.attrib.items() if k.endswith("id")), None)
                    tgt = rels.get(rid, "")
                    if tgt in names:
                        sheet_targets.append((nm, tgt))
        if not sheet_targets:
            cands = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
            sheet_targets = [(f"Sheet{i+1}", c) for i, c in enumerate(cands)]
        chosen_nm, chosen_path = sheet_targets[0]
        if sheet_name:
            for nm, tgt in sheet_targets:
                if nm == sheet_name:
                    chosen_nm, chosen_path = nm, tgt
                    break
        wsroot = ET.fromstring(zf.read(chosen_path))
        grid = []
        for row_el in wsroot.iter():
            if not row_el.tag.endswith("row"):
                continue
            row_vals = {}
            for c_el in row_el:
                if not c_el.tag.endswith("c"):
                    continue
                ci = _col_idx(c_el.get("r", ""))
                ctype = c_el.get("t", "")
                val = ""
                if ctype == "inlineStr":
                    val = "".join(c_el.itertext())
                else:
                    v_el = next((ch for ch in c_el if ch.tag.endswith("v")), None)
                    if v_el is not None and v_el.text is not None:
                        if ctype == "s":
                            si_i = int(v_el.text)
                            val = shared[si_i] if 0 <= si_i < len(shared) else ""
                        else:
                            val = v_el.text
                row_vals[ci] = val
            if row_vals:
                max_c = max(row_vals.keys())
                grid.append([row_vals.get(i, "") for i in range(max_c + 1)])
        return chosen_nm, grid


def _apply_filter(rows, flt, src):
    """按 data.filter 精确过滤行，同时 100% 保留每行原始物理行号 __line__。"""
    if not flt or not isinstance(flt, dict):
        return rows, src
    kept = []
    for r in rows:
        ok = True
        for k, want in flt.items():
            val = str(r.get(k, "")).strip()
            if isinstance(want, (list, tuple, set)):
                if val not in {str(w).strip() for w in want}:
                    ok = False
                    break
            else:
                if val != str(want).strip():
                    ok = False
                    break
        if ok:
            kept.append(r)
    src = dict(src)
    src["filter"] = flt
    src["n_rows_filtered"] = len(kept)
    return kept, src


def _load_rows(data):
    """统一读取 file(CSV/TSV/XLSX) / json_file / inline columns+rows，支持 data.filter 保留原始行号。"""
    flt = data.get("filter")
    if data.get("json_file"):
        obj = json.loads(Path(data["json_file"]).read_text(encoding="utf-8"))
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            cols = []
            for r in obj:
                for k in r.keys():
                    if k not in cols:
                        cols.append(k)
            rows = [{c: "" if r.get(c) is None else str(r.get(c)) for c in cols} for r in obj]
        elif isinstance(obj, dict) and "columns" in obj and "rows" in obj:
            cols = [str(c) for c in obj["columns"]]
            rows = [{cols[i]: ("" if r[i] is None else str(r[i])) for i in range(min(len(cols), len(r)))}
                    for r in obj["rows"]]
        else:
            cols, rows = [], []
        for i, r in enumerate(rows, start=2):
            r["__line__"] = i
        src = {"file": str(data["json_file"]), "sha256": sha256_of(data["json_file"]),
               "columns": cols, "n_rows": len(rows)}
        rows, src = _apply_filter(rows, flt, src)
        return cols, rows, src
    if data.get("file"):
        fpath = Path(data["file"])
        if fpath.suffix.lower() in (".xlsx", ".xlsm"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(fpath), data_only=True, read_only=True)
                ws = wb[data["sheet"]] if data.get("sheet") and data["sheet"] in wb.sheetnames else wb.active
                raw_rows = list(ws.iter_rows(values_only=True))
                sheet_title = ws.title
                wb.close()
            except ImportError:
                sheet_title, raw_rows = _read_xlsx_stdlib(fpath, sheet_name=data.get("sheet"))
            cols = [str(c).strip() if c is not None else "" for c in (raw_rows[0] if raw_rows else [])]
            rows = []
            for idx, r in enumerate(raw_rows[1:], start=2):
                if all(v is None or str(v).strip() == "" for v in r):
                    continue
                rec = {cols[i]: ("" if (i >= len(r) or r[i] is None) else str(r[i]))
                       for i in range(len(cols))}
                rec["__line__"] = idx
                rows.append(rec)
            src = {"file": str(fpath), "sheet": sheet_title, "sha256": sha256_of(fpath),
                   "header_line": 1, "columns": cols, "n_rows": len(rows)}
            rows, src = _apply_filter(rows, flt, src)
            return cols, rows, src
        cols, rows, hline = read_table(data["file"], return_meta=True)
        src = {"file": str(data["file"]), "sha256": sha256_of(data["file"]),
               "header_line": hline, "columns": cols, "n_rows": len(rows)}
        rows, src = _apply_filter(rows, flt, src)
        return cols, rows, src
    cols = list(data.get("columns", []))
    rows = []
    for idx, r in enumerate(data.get("rows", []), start=2):
        rec = {cols[i]: (r[i] if i < len(r) else "") for i in range(len(cols))}
        rec["__line__"] = idx
        rows.append(rec)
    src = {"inline": True, "columns": cols, "n_rows": len(rows)}
    rows, src = _apply_filter(rows, flt, src)
    return cols, rows, src


def _agg_values(vals, mode):
    """聚合原始重复观测值：返回 (center, spread, n)。"""
    n = len(vals)
    if n == 0:
        return None, None, 0
    if n == 1:
        return vals[0], None, 1
    if mode == "median_iqr":
        sv = sorted(vals)
        med = statistics.median(sv)
        q1 = sv[n // 4]
        q3 = sv[(3 * n) // 4]
        return med, (q3 - q1) / 2.0, n
    mean = sum(vals) / n
    sd = statistics.stdev(vals)
    if mode == "mean_sem":
        return mean, sd / math.sqrt(n), n
    return mean, sd, n


def _from_xy_points(panel):
    """连续数值 X 轴模式（scatter 或 numeric_x=true 的 line/errorbar）：保留每个原始 (x,y) 点不覆盖。"""
    data = panel.get("data", {})
    mp = panel.get("mapping", {})
    cols, rows, src = _load_rows(data)
    xcol = mp.get("x", "x")
    ycol = mp.get("y", "y")
    scol = mp.get("series")
    ecol = mp.get("error")
    lcol = mp.get("label")
    by_s, order, missing, elements = {}, [], [], []
    for r in rows:
        sname = str(r.get(scol, "__all__")) if scol else "__all__"
        xv = to_num(r.get(xcol))
        yv = to_num(r.get(ycol))
        ev = to_num(r.get(ecol)) if ecol else None
        lbl = str(r.get(lcol, "")).strip() if lcol else ""
        if sname not in by_s:
            by_s[sname] = {"xs": [], "ys": [], "errs": [], "labels": [], "lines": []}
            order.append(sname)
        if xv is None or yv is None:
            missing.append({"series": sname, "line": r.get("__line__"),
                            "raw_x": r.get(xcol), "raw_y": r.get(ycol)})
            continue
        by_s[sname]["xs"].append(xv)
        by_s[sname]["ys"].append(yv)
        by_s[sname]["errs"].append(ev)
        by_s[sname]["labels"].append(lbl)
        by_s[sname]["lines"].append(r.get("__line__"))
        elements.append({"glyph": "point", "series": sname, "x": xv, "value": yv,
                         "error": ev, "label": lbl or None, "source_line": r.get("__line__"),
                         "col_x": xcol, "col_y": ycol, "col_err": ecol})
    series = []
    for s in order:
        d = by_s[s]
        # 折线/误差棒按 x 升序排列以便连线
        if panel.get("kind") in ("line", "errorbar"):
            idx = sorted(range(len(d["xs"])), key=lambda i: d["xs"][i])
            d = {k: [v[i] for i in idx] for k, v in d.items()}
        series.append({"name": s, "x_values": d["xs"], "values": d["ys"],
                       "errors": d["errs"] if any(e is not None for e in d["errs"]) else None,
                       "point_labels": d["labels"], "lines": d["lines"]})
    return {"kind": panel["kind"], "numeric_x": True, "groups": [], "series": series,
            "missing": missing, "source": src, "elements": elements, "warnings": []}


def _from_tidy_box(panel):
    """box 图支持 tidy 表：按 mapping.x（或 series）分组收集所有观测值。"""
    data = panel.get("data", {})
    mp = panel.get("mapping", {})
    cols, rows, src = _load_rows(data)
    gcol = mp.get("x") or mp.get("series") or (cols[0] if cols else "group")
    ycol = mp.get("y") or (cols[1] if len(cols) > 1 else "y")
    buckets, order, missing, elements = {}, [], [], []
    for r in rows:
        g = str(r.get(gcol, ""))
        v = to_num(r.get(ycol))
        if g not in buckets:
            buckets[g] = {"vals": [], "lines": []}
            order.append(g)
        if v is None:
            missing.append({"group": g, "line": r.get("__line__"), "raw": r.get(ycol)})
            continue
        buckets[g]["vals"].append(v)
        buckets[g]["lines"].append(r.get("__line__"))
        elements.append({"glyph": "box_point", "group": g, "series": g, "value": v,
                         "source_line": r.get("__line__"), "col_y": ycol})
    series = [{"name": g, "values": buckets[g]["vals"], "errors": None,
               "lines": buckets[g]["lines"], "n": len(buckets[g]["vals"])}
              for g in order]
    return {"kind": panel.get("kind", "box"), "groups": order, "series": series,
            "missing": missing, "source": src, "elements": elements, "warnings": []}


def _from_tidy(panel):
    """tidy 长表或宽表(mapping.y_cols)：file(CSV/TSV/XLSX)/json_file 或 inline columns/rows。
    若同一 (series, group) 含多个重复观测且无 error 列，自动聚合 mean±SD（可设 aggregate），保留 raw_points 与全部行号。"""
    data = panel.get("data", {})
    mp = panel.get("mapping", {})
    cols, rows, src = _load_rows(data)
    xcol = mp.get("x", "x")
    ycol = mp.get("y", "y")
    scol = mp.get("series")
    ecol = mp.get("error")
    elo_col = mp.get("error_low")
    ehi_col = mp.get("error_high")
    agg_mode = panel.get("aggregate", "mean_sd")

    # 宽表自动转长表（如 mapping={"x":"Gene", "y_cols":["WT","KO"]}）
    y_cols = mp.get("y_cols")
    if y_cols:
        unpivoted = []
        for r in rows:
            for yc in y_cols:
                unpivoted.append({xcol: r.get(xcol, ""), "__series__": yc,
                                  "__val__": r.get(yc, ""), "__col_y__": yc,
                                  "__line__": r.get("__line__")})
        rows = unpivoted
        scol = "__series__"
        ycol = "__val__"

    cells, order_s, gnames, missing, warnings = {}, [], [], [], []
    for r in rows:
        g = str(r.get(xcol, ""))
        s = str(r.get(scol, "__all__")) if scol else "__all__"
        if s not in cells:
            cells[s] = {}
            order_s.append(s)
        if g not in gnames:
            gnames.append(g)
        v = to_num(r.get(ycol))
        e = to_num(r.get(ecol)) if ecol else None
        elo = to_num(r.get(elo_col)) if elo_col else None
        ehi = to_num(r.get(ehi_col)) if ehi_col else None
        ln = r.get("__line__")
        actual_ycol = r.get("__col_y__", ycol)
        if v is None:
            missing.append({"group": g, "series": s, "line": ln, "col": actual_ycol, "raw": r.get(ycol)})
        cells[s].setdefault(g, []).append({"value": v, "error": e, "err_lo": elo, "err_hi": ehi,
                                           "line": ln, "col_y": actual_ycol})

    # 可选显式锁定分组/系列顺序，或按分类名/数值排序（保留每个单元格真实源行号）
    x_order = panel.get("x_order")
    if x_order and gnames:
        wanted = [str(x) for x in x_order]
        gnames = [g for g in wanted if g in gnames] + [g for g in gnames if g not in wanted]
    series_order = panel.get("series_order")
    if series_order and order_s:
        wanted_s = [str(x) for x in series_order]
        order_s = [s for s in wanted_s if s in order_s] + [s for s in order_s if s not in wanted_s]

    sort_x = panel.get("sort_x")
    if sort_x and gnames:
        if sort_x == "asc":
            gnames = sorted(gnames)
        elif sort_x == "desc":
            gnames = sorted(gnames, reverse=True)
        elif sort_x in ("by_value_desc", "by_value_asc"):
            def _gscore(g):
                vs = [c["value"] for s in order_s for c in cells[s].get(g, []) if c["value"] is not None]
                return (sum(vs) / len(vs)) if vs else float("-inf")
            gnames = sorted(gnames, key=_gscore, reverse=(sort_x == "by_value_desc"))

    # 检测是否存在重复观测
    has_replicates = any(len(lst) > 1 for s in order_s for lst in cells[s].values())
    series, elements = [], []
    for s in order_s:
        s_vals, s_errs, s_elo, s_ehi, s_lines, s_raw, s_ns = [], [], [], [], [], [], []
        for g in gnames:
            lst = cells[s].get(g) or []
            valid = [c for c in lst if c["value"] is not None]
            if not valid:
                s_vals.append(None); s_errs.append(None); s_elo.append(None); s_ehi.append(None)
                s_lines.append(lst[0]["line"] if lst else None)
                s_raw.append([]); s_ns.append(0)
                elements.append({"glyph": "point", "group": g, "series": s,
                                 "value": None, "error": None, "source_line": lst[0]["line"] if lst else None,
                                 "col_y": (lst[0].get("col_y", ycol) if lst else ycol), "col_err": ecol})
            elif len(valid) == 1:
                c = valid[0]
                s_vals.append(c["value"]); s_errs.append(c["error"])
                # 若给定非对称 error_low/error_high：区分绝对界限(low<=v<=high)与差值
                lo_d = (max(0.0, c["value"] - c["err_lo"]) if (c["err_lo"] is not None and c["err_lo"] <= c["value"])
                        else c["err_lo"])
                hi_d = (max(0.0, c["err_hi"] - c["value"]) if (c["err_hi"] is not None and c["err_hi"] >= c["value"])
                        else c["err_hi"])
                s_elo.append(lo_d); s_ehi.append(hi_d)
                s_lines.append(c["line"])
                s_raw.append([c["value"]]); s_ns.append(1)
                el_rec = {"glyph": "point", "group": g, "series": s,
                          "value": c["value"], "error": c["error"], "source_line": c["line"],
                          "col_y": c.get("col_y", ycol), "col_err": ecol}
                if elo_col or ehi_col:
                    el_rec.update(error_low=c["err_lo"], error_high=c["err_hi"],
                                  col_err_low=elo_col, col_err_high=ehi_col)
                elements.append(el_rec)
            else:
                if ecol and any(c["error"] is not None for c in valid):
                    warnings.append(f"({s}, {g}) 存在 {len(valid)} 行重复且已有 error 列，已按 {agg_mode} 聚合均值")
                raw_v = [c["value"] for c in valid]
                raw_l = [c["line"] for c in valid]
                val, err, n = _agg_values(raw_v, agg_mode)
                s_vals.append(val); s_errs.append(err); s_elo.append(None); s_ehi.append(None)
                s_lines.append(raw_l); s_raw.append(raw_v); s_ns.append(n)
                elements.append({"glyph": "point", "group": g, "series": s,
                                 "value": round(val, 6), "error": round(err, 6) if err is not None else None,
                                 "n": n, "aggregation": agg_mode, "raw_values": raw_v,
                                 "source_line": raw_l[0], "source_lines": raw_l,
                                 "col_y": valid[0].get("col_y", ycol), "col_err": ecol or agg_mode})
        rec_s = {"name": s, "values": s_vals, "errors": s_errs,
                 "lines": s_lines, "raw_points": s_raw, "ns": s_ns}
        if any(v is not None for v in s_elo) and any(v is not None for v in s_ehi):
            rec_s["errors_low"] = s_elo
            rec_s["errors_high"] = s_ehi
        series.append(rec_s)

    if has_replicates and not ecol:
        warnings.append(f"检测到原始重复观测，已自动按 {agg_mode} 聚合（各组 n 见 provenance）")
    return {"kind": panel["kind"], "groups": gnames, "series": series,
            "missing": missing, "source": src, "elements": elements,
            "aggregated": bool(has_replicates and not ecol),
            "aggregation_mode": agg_mode if (has_replicates and not ecol) else None,
            "warnings": warnings}


def _from_explicit(panel):
    """显式 series：data.series=[{name,y[],x[]?,error[]?}] (+x_labels)。"""
    data = panel.get("data", {})
    gnames = list(data.get("x_labels", []))
    numeric_x = bool(panel.get("numeric_x")) or any(s.get("x") is not None for s in data.get("series", []))
    series, elements, missing = [], [], []
    for si, s in enumerate(data.get("series", [])):
        vals = [to_num(v) for v in s.get("y", [])]
        xvals = [to_num(v) for v in s.get("x", [])] if s.get("x") is not None else None
        errs = [to_num(v) for v in s.get("error", [])] if s.get("error") else None
        for gi, v in enumerate(vals):
            if v is None:
                missing.append({"series": s.get("name", f"s{si}"), "index": gi, "raw": s.get("y", [])[gi]})
            el = {"glyph": "point",
                  "group": gnames[gi] if gi < len(gnames) else (str(xvals[gi]) if xvals and gi < len(xvals) else str(gi)),
                  "series": s.get("name", f"series{si}"), "value": v,
                  "error": errs[gi] if errs and gi < len(errs) else None,
                  "ref": f"data.series[{si}].y[{gi}]"}
            if xvals and gi < len(xvals):
                el["x"] = xvals[gi]
            elements.append(el)
        rec = {"name": str(s.get("name", f"series{si}")), "values": vals,
               "errors": errs, "lines": None}
        if xvals is not None:
            rec["x_values"] = xvals
        series.append(rec)
    if not gnames and not numeric_x:
        n = max((len(s["values"]) for s in series), default=0)
        gnames = [str(i + 1) for i in range(n)]
    return {"kind": panel["kind"], "numeric_x": numeric_x, "groups": gnames, "series": series,
            "missing": missing, "source": {"inline": True, "spec": "data.series"},
            "elements": elements, "warnings": []}


def _from_heatmap(panel):
    data = panel.get("data", {})
    missing = []
    cell_lines = {}
    if data.get("matrix"):
        mat_raw = data["matrix"]
        rlab = list(data.get("row_labels", [str(i) for i in range(len(mat_raw))]))
        clab = list(data.get("col_labels", [str(j) for j in range(len(mat_raw[0]) if mat_raw else 0)]))
        src = {"inline": True, "spec": "data.matrix"}
    else:
        cols, rows, src = _load_rows(data)
        mp = panel.get("mapping", {})
        rk, ck, vk = mp.get("row", "row"), mp.get("col", "col"), mp.get("value", "value")
        is_tidy = (rk in cols and ck in cols and vk in cols)
        if is_tidy:
            rlab, clab, m = [], [], {}
            for r in rows:
                ri = str(r.get(rk))
                ci = str(r.get(ck))
                v = to_num(r.get(vk))
                m[(ri, ci)] = v
                cell_lines[(ri, ci)] = (r.get("__line__"), vk)
                if ri not in rlab:
                    rlab.append(ri)
                if ci not in clab:
                    clab.append(ci)
            mat_raw = [[m.get((r, c)) for c in clab] for r in rlab]
        else:
            # 宽矩阵表自动识别（首列为行标签，其余列为热图数值列，并逐单元格保留源行号与列名）
            row_col = mp.get("row") if mp.get("row") in cols else (cols[0] if cols else None)
            val_cols = mp.get("value_cols") or mp.get("cols") or [c for c in cols if c != row_col]
            rlab = [str(r.get(row_col, i)) for i, r in enumerate(rows)]
            clab = list(val_cols)
            mat_raw = []
            for ri_lbl, r in zip(rlab, rows):
                row_vals = []
                for c in clab:
                    row_vals.append(to_num(r.get(c)))
                    cell_lines[(ri_lbl, c)] = (r.get("__line__"), c)
                mat_raw.append(row_vals)
    import numpy as np
    mat = np.array([[float("nan") if to_num(v) is None else to_num(v) for v in row]
                    for row in mat_raw], dtype=float)
    elements = []
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            is_nan = bool(mat[i, j] != mat[i, j])
            ln_info = cell_lines.get((rlab[i], clab[j]))
            if is_nan:
                missing.append({"row": rlab[i], "col": clab[j],
                                **({"line": ln_info[0], "col_src": ln_info[1]} if ln_info else {})})
            el = {"glyph": "cell", "row": rlab[i], "col": clab[j],
                  "value": None if is_nan else float(mat[i, j]),
                  "ref": f"matrix[{i}][{j}]"}
            if ln_info:
                el["source_line"] = ln_info[0]
                el["source_col"] = ln_info[1]
            elements.append(el)
    return {"kind": "heatmap", "matrix": mat, "row_labels": rlab, "col_labels": clab,
            "unit": panel.get("unit", ""), "missing": missing, "source": src,
            "elements": elements, "warnings": []}


def resolve_panel(panel):
    """入口：按 data 形态与图型分派，返回统一 payload（含 provenance elements）。"""
    data = panel.get("data", {})
    kind = panel.get("kind", "bar")
    if kind == "heatmap":
        return _from_heatmap(panel)
    if data.get("series") is not None:
        res = _from_explicit(panel)
        if kind in ("pie", "donut") and res["series"]:
            vals = [v for v in res["series"][0]["values"] if v is not None and v >= 0]
            tot = sum(vals) or 1.0
            for el in res["elements"]:
                if el.get("value") is not None:
                    el["glyph"] = "wedge"
                    el["pct"] = round(100.0 * el["value"] / tot, 3)
        return res
    if kind in ("box", "violin"):
        return _from_tidy_box(panel)
    if kind in ("pie", "donut"):
        res = _from_tidy(panel)
        if res["series"]:
            vals = [v for v in res["series"][0]["values"] if v is not None and v >= 0]
            tot = sum(vals) or 1.0
            for el in res["elements"]:
                if el.get("value") is not None:
                    el["glyph"] = "wedge"
                    el["pct"] = round(100.0 * el["value"] / tot, 3)
        return res
    if kind == "scatter" or panel.get("numeric_x"):
        # 若 x 列全是数值则走连续 X 轴；否则仍回退分类 tidy
        cols, rows, _ = _load_rows(data)
        xcol = panel.get("mapping", {}).get("x", "x")
        sample_x = [r.get(xcol) for r in rows[:20] if str(r.get(xcol, "")).strip() != ""]
        if sample_x and all(to_num(v) is not None for v in sample_x):
            return _from_xy_points(panel)
    return _from_tidy(panel)


def resolve_style(style):
    st = dict(style or {})
    presets = dict(PRESETS)
    pfile = Path(__file__).resolve().parent.parent / "assets" / "journal_presets.json"
    if pfile.exists():
        try:
            presets.update(json.loads(pfile.read_text(encoding="utf-8")))
        except Exception:
            pass
    pname = st.get("preset")
    if pname and Path(str(pname)).exists():
        try:
            preset = json.loads(Path(str(pname)).read_text(encoding="utf-8"))
        except Exception:
            preset = presets["journal_single"]
    else:
        preset = presets.get(pname, presets["journal_single"])
    st.setdefault("width_mm", preset["width_mm"])
    st.setdefault("font_pt", preset["font_pt"])
    st.setdefault("panel_h_mm", preset["panel_h_mm"])
    return st
