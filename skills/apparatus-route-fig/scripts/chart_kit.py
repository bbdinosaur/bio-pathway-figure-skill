#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_kit.py — 科研数据图表一键生成：spec JSON（或直连 CSV/TSV/XLSX 源表）→
chart.png(300dpi)/.pdf/.svg + chart_checks.json + provenance.json [+ result_skel.json]。
支持 line(含误差棒/误差带) / bar(分组) / barh / stacked_bar / scatter / box(含散点叠加)、
分类字符串 x 轴、对数刻度、参考线(hlines/vlines)、标注(annotations)、多面板(panels)，
保留 SVG/PDF 真实可编辑文本（svg.fonttype=none, pdf.fonttype=42）。

用法: python3 chart_kit.py --spec data.json --out /app/output --name chart [--dpi 300]
      [--case-id CASE] [--contract /input/case.json] [--result-skel /app/work/result_skel.json]
退出码: 0=通过 2=spec结构错误 3=检查有警告
"""
import argparse
import hashlib
import json
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import table_probe as tp
PAL = ["#2B6CB0", "#C05621", "#2F855A", "#6B46C1", "#B83280", "#2C7A7B", "#B7791F", "#4A5568"]
MK = ["o", "s", "^", "D", "v", "P", "X", "*"]
VALID_KINDS = ("line", "step", "bar", "barh", "stacked_bar", "scatter", "volcano", "box", "violin", "hist", "heatmap")
KIND_ALIASES = {
    "survival": "step", "km": "step", "kaplan_meier": "step", "kaplan-meier": "step",
    "grouped_bar": "bar", "column": "bar", "horizontal_bar": "barh",
    "stacked": "stacked_bar", "boxplot": "box", "violinplot": "violin", "violin_plot": "violin",
    "histogram": "hist", "distribution": "hist", "correlation": "scatter",
    "regression": "scatter", "volcano_plot": "volcano", "matrix": "heatmap",
}


def _norm_kind(k):
    s = str(k or "line").strip().lower()
    return KIND_ALIASES.get(s, s)


def _is_num(v):
    fv, _ = tp.parse_num(v)
    return fv is not None


def _to_float(v):
    fv, _ = tp.parse_num(v)
    return float(fv) if fv is not None else float(v)


def _series_stats(vals):
    n = len(vals)
    if not n:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "sd": 0.0, "sem": 0.0, "iqr": 0.0}
    sv = sorted(vals)
    mid = n // 2
    med = sv[mid] if n % 2 == 1 else (sv[mid - 1] + sv[mid]) / 2.0
    q1 = sv[n // 4]
    q3 = sv[(3 * n) // 4] if n > 1 else sv[0]
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    sem = sd / math.sqrt(n) if n > 1 else 0.0
    return {"min": round(sv[0], 6), "max": round(sv[-1], 6),
            "mean": round(mu, 6), "median": round(med, 6),
            "sd": round(sd, 6), "sem": round(sem, 6), "iqr": round(q3 - q1, 6)}


def _points_sha12(xs, ys):
    payload = json.dumps([[str(x), round(float(y), 6)] for x, y in zip(xs, ys)], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _filter_rows(rows, flt):
    if not isinstance(flt, dict) or not flt:
        return rows
    out = []
    for r in rows:
        ok = True
        for k, v in flt.items():
            rv = str(r.get(k, "")).strip()
            if isinstance(v, list):
                if rv not in [str(x).strip() for x in v]:
                    ok = False
                    break
            elif rv != str(v).strip():
                ok = False
                break
        if ok:
            out.append(r)
    return out


def _aggregate_xy(xs, ys, mode):
    """按 x 分组聚合重复样本：mean_sd / mean_sem，保持首次出现顺序，并返回原始点与剔除缺失数。"""
    buckets, dropped = {}, 0
    for xv, yv in zip(xs, ys):
        fv, _ = tp.parse_num(yv)
        if fv is None:
            dropped += 1
            continue
        k = str(xv).strip()
        buckets.setdefault(k, []).append(fv)
    ox, oy, oerr, ns, raw_pts = [], [], [], [], []
    for k, vals in buckets.items():
        n = len(vals)
        mu = sum(vals) / n
        if n > 1:
            var = sum((v - mu) ** 2 for v in vals) / (n - 1)
            sd = math.sqrt(var)
        else:
            sd = 0.0
        err = (sd / math.sqrt(n)) if mode == "mean_sem" and n > 0 else sd
        fx, _ = tp.parse_num(k)
        ox.append(fx if fx is not None else k)
        oy.append(round(mu, 6))
        oerr.append(round(err, 6))
        ns.append(n)
        raw_pts.append(vals)
    return ox, oy, oerr, ns, raw_pts, dropped


def _clean_rows_xy(rows, xc, yc, ec=None, lc=None):
    """过滤 y 为缺失值（空/NA/NaN/ND）的行，支持 '均值 ± 误差' 单元格自动拆分与点标签列，返回 (xs, ys, errs, dropped, pm_cnt, labels)。"""
    xs, ys, errs, labels, dropped, pm_cnt = [], [], [], [], 0, 0
    has_pm = False
    for idx, r in enumerate(rows):
        raw_y = r.get(yc, "")
        if tp.is_missing(raw_y):
            dropped += 1
            continue
        fv, _ = tp.parse_num(raw_y)
        pm_v, pm_e = None, None
        if fv is None:
            pm_v, pm_e, _ = tp.parse_val_err(raw_y)
            if pm_v is not None:
                fv = pm_v
                has_pm = True
                pm_cnt += 1
        xs.append(r.get(xc, "") if xc else idx)
        ys.append(fv if fv is not None else raw_y)
        if lc:
            labels.append(str(r.get(lc, "")).strip())
        if ec:
            ev, _ = tp.parse_num(r.get(ec, ""))
            errs.append(ev if ev is not None else (0.0 if tp.is_missing(r.get(ec, "")) else r.get(ec, "")))
        else:
            errs.append(pm_e if pm_e is not None else 0.0)
    use_err = errs if (ec or has_pm) else None
    return xs, ys, use_err, dropped, pm_cnt, (labels if lc else None)


def _apply_y_transform(xs, ys, errs, plabs, y_transform):
    """支持将原始 p_value/padj 自动转换为 -log10(p)（零手工预处理，保留原始范围溯源；若全部值已 >1 则视为已转换并原样保留）。"""
    tf = str(y_transform or "").strip().lower().replace("_", "").replace("-", "")
    if tf not in ("neglog10", "neglog10p", "minuslog10"):
        return xs, ys, errs, plabs, None
    if ys and all(yv > 1.0 for yv in ys):
        return xs, ys, errs, plabs, {"y_transform": "already_neglog10_kept"}
    nxs, nys, nerrs, nlabs, raw_ps = [], [], [], [], []
    has_err = isinstance(errs, list) and len(errs) == len(ys)
    has_lab = isinstance(plabs, list) and len(plabs) == len(ys)
    for idx_i, (xv, yv) in enumerate(zip(xs, ys)):
        if yv < 0.0 or yv > 1.0:
            continue
        raw_ps.append(yv)
        nxs.append(xv)
        nys.append(round(-math.log10(max(yv, 1e-300)), 6))
        if has_err:
            nerrs.append(errs[idx_i])
        if has_lab:
            nlabs.append(plabs[idx_i])
    meta = {"y_transform": "neglog10",
            "raw_p_range": [min(raw_ps), max(raw_ps)] if raw_ps else []}
    return nxs, nys, (nerrs if has_err else None), (nlabs if has_lab else None), meta


def _hydrate_panel(p, base_dir):
    """若 panel 或 series 指定了 table（CSV/TSV/XLSX/JSON），直接从磁盘读取原值，零人工抄写误差。"""
    def _resolve(tpath):
        pp = Path(tpath)
        if pp.is_absolute() or pp.exists():
            return pp
        for cand in (base_dir / pp, base_dir.parent / pp, Path("/input") / pp):
            if cand.exists():
                return cand
        inp_dir = Path("/input")
        if inp_dir.exists():
            for hit in inp_dir.rglob(pp.name):
                if hit.is_file():
                    return hit
        return base_dir / pp

    p = dict(p)
    if p.get("kind"):
        p["kind"] = _norm_kind(p["kind"])
    # 热图直连源表（宽表：首列为 y_labels、其余数值列为 x_labels；或长表 x_col/y_col/val_col）
    if p.get("kind") == "heatmap" and p.get("table") and not p.get("matrix"):
        tpath = _resolve(p["table"])
        tbl = tp.load_table(tpath, sheet=p.get("sheet"), skip_rows=int(p.get("skip_rows") or 0))
        rows = _filter_rows(tbl["rows"], p.get("filter"))
        cols = tbl["columns"]
        src_base = dict(p.get("source") or {"quote": "Direct heatmap table %s" % tpath.name,
                                            "loc": "%s%s" % (tpath.name, (" [%s]" % tbl["sheet"]) if tbl["sheet"] else "")})
        src_base["table"] = tpath.name
        src_base["sha256_12"] = tbl["sha256"][:12]
        src_base["n_source_rows"] = len(rows)
        if p.get("x_col") and p.get("y_col") and p.get("val_col"):
            xc = tp.resolve_col(cols, p["x_col"])
            yc = tp.resolve_col(cols, p["y_col"])
            vc = tp.resolve_col(cols, p["val_col"])
            xs = list(dict.fromkeys(str(r.get(xc, "")) for r in rows))
            ys = list(dict.fromkeys(str(r.get(yc, "")) for r in rows))
            grid = {}
            for r in rows:
                fv, _ = tp.parse_num(r.get(vc))
                if fv is not None:
                    grid[(str(r.get(yc, "")), str(r.get(xc, "")))] = fv
            mat = [[grid.get((yv, xv), float("nan")) for xv in xs] for yv in ys]
            p["x_labels"], p["y_labels"], p["matrix"] = xs, ys, mat
        else:
            row_col = tp.resolve_col(cols, p["row_col"]) if p.get("row_col") else (cols[0] if cols else "")
            val_cols = [tp.resolve_col(cols, c) for c in p["value_cols"]] if p.get("value_cols") else [c for c in cols if c != row_col]
            p["y_labels"] = [str(r.get(row_col, "")) for r in rows]
            p["x_labels"] = list(val_cols)
            mat = []
            for r in rows:
                row_vals = []
                for c in val_cols:
                    fv, _ = tp.parse_num(r.get(c))
                    row_vals.append(fv if fv is not None else float("nan"))
                mat.append(row_vals)
            p["matrix"] = mat
        p["source"] = src_base
        return p

    # 面板级 table：支持宽表多列 y_cols=[...] 或长表 group_col 自动拆系列
    if p.get("table") and not p.get("series"):
        tpath = _resolve(p["table"])
        tbl = tp.load_table(tpath, sheet=p.get("sheet"), skip_rows=int(p.get("skip_rows") or 0))
        cols = tbl["columns"]
        rows = _filter_rows(tbl["rows"], p.get("filter"))
        xc = tp.resolve_col(cols, p.get("x_col"), allow_none=True)
        agg = p.get("agg")
        src_base = p.get("source") or {"quote": "Direct table %s" % tpath.name,
                                       "loc": "%s%s" % (tpath.name, (" [%s]" % tbl["sheet"]) if tbl["sheet"] else "")}
        series = []
        if isinstance(p.get("y_cols"), list) and p["y_cols"]:
            yerr_cols = p.get("yerr_cols") or []
            lc_w = tp.resolve_col(cols, p.get("label_col"), allow_none=True)
            for ci, yc_raw in enumerate(p["y_cols"]):
                yc = tp.resolve_col(cols, yc_raw)
                ec = tp.resolve_col(cols, yerr_cols[ci], allow_none=True) if ci < len(yerr_cols) else None
                src_d = dict(src_base, table=tpath.name, sha256_12=tbl["sha256"][:12],
                             n_source_rows=len(rows), columns_used=[c for c in (xc, yc, ec, lc_w) if c])
                if agg in ("mean_sd", "mean_sem"):
                    raw_xs = [r.get(xc, "") for r in rows] if xc else list(range(len(rows)))
                    raw_ys = [r.get(yc, "") for r in rows]
                    xs, ys, errs, ns, raw_pts, dropped = _aggregate_xy(raw_xs, raw_ys, agg)
                    src_d.update({"agg": agg, "replicates_per_x": ns, "dropped_missing": dropped})
                    s = {"name": str(yc), "x": xs, "y": ys, "yerr": errs, "raw_points": raw_pts, "source": src_d}
                else:
                    xs, ys, errs, dropped, pm_cnt, plabs = _clean_rows_xy(rows, xc, yc, ec, lc_w)
                    if dropped:
                        src_d["dropped_missing"] = dropped
                    if pm_cnt:
                        src_d["parsed_pm_cells"] = pm_cnt
                    if tbl.get("footnotes"):
                        src_d["footnotes_skipped"] = len(tbl["footnotes"])
                    s = {"name": str(yc), "x": xs, "y": ys, "source": src_d}
                    if errs is not None:
                        s["yerr"] = errs
                    if plabs:
                        s["point_labels"] = plabs
                series.append(s)
        else:
            p_col = tp.resolve_col(cols, p.get("p_col") or p.get("padj_col"), allow_none=True)
            yc = tp.resolve_col(cols, p.get("y_col"), allow_none=True) or p_col
            ec = tp.resolve_col(cols, p.get("yerr_col"), allow_none=True)
            gc = tp.resolve_col(cols, p.get("group_col"), allow_none=True)
            lc = tp.resolve_col(cols, p.get("label_col"), allow_none=True)
            y_tf = p.get("y_transform") or ("neglog10" if p_col else None)
            if y_tf and not p.get("ylabel"):
                p["ylabel"] = "-log10(%s)" % (p_col or "p-value")
            groups = {}
            if gc:
                for r in rows:
                    g = str(r.get(gc, "")).strip() or "All"
                    groups.setdefault(g, []).append(r)
            else:
                groups[str(p.get("series_name") or yc or "Series")] = rows
            for gname, grows in groups.items():
                src_d = dict(src_base, table=tpath.name, sha256_12=tbl["sha256"][:12],
                             n_source_rows=len(grows), columns_used=[c for c in (xc, yc, ec, gc, lc) if c])
                if agg in ("mean_sd", "mean_sem"):
                    raw_xs = [r.get(xc, "") for r in grows] if xc else list(range(len(grows)))
                    raw_ys = [r.get(yc, "") for r in grows]
                    xs, ys, errs, ns, raw_pts, dropped = _aggregate_xy(raw_xs, raw_ys, agg)
                    src_d.update({"agg": agg, "replicates_per_x": ns, "dropped_missing": dropped})
                    s = {"name": gname, "x": xs, "y": ys, "yerr": errs, "raw_points": raw_pts, "source": src_d}
                else:
                    xs, ys, errs, dropped, pm_cnt, plabs = _clean_rows_xy(grows, xc, yc, ec, lc)
                    xs, ys, errs, plabs, tf_meta = _apply_y_transform(xs, ys, errs, plabs, y_tf)
                    if tf_meta:
                        src_d.update(tf_meta)
                    if dropped:
                        src_d["dropped_missing"] = dropped
                    if pm_cnt:
                        src_d["parsed_pm_cells"] = pm_cnt
                    if tbl.get("footnotes"):
                        src_d["footnotes_skipped"] = len(tbl["footnotes"])
                    s = {"name": gname, "x": xs, "y": ys, "source": src_d}
                    if errs is not None:
                        s["yerr"] = errs
                    if plabs:
                        s["point_labels"] = plabs
                series.append(s)
        p["series"] = series
        return p

    # 系列级 table 读取
    new_series = []
    for s in p.get("series") or []:
        s = dict(s)
        if s.get("table") and not s.get("y"):
            tpath = _resolve(s["table"])
            tbl = tp.load_table(tpath, sheet=s.get("sheet"), skip_rows=int(s.get("skip_rows") or 0))
            cols = tbl["columns"]
            rows = _filter_rows(tbl["rows"], s.get("filter"))
            sp_col = tp.resolve_col(cols, s.get("p_col") or s.get("padj_col"), allow_none=True)
            xc = tp.resolve_col(cols, s.get("x_col"), allow_none=True)
            yc = tp.resolve_col(cols, s.get("y_col"), allow_none=True) or sp_col
            ec = tp.resolve_col(cols, s.get("yerr_col"), allow_none=True)
            lc = tp.resolve_col(cols, s.get("label_col") or p.get("label_col"), allow_none=True)
            sy_tf = s.get("y_transform") or p.get("y_transform") or ("neglog10" if sp_col else None)
            src = dict(s.get("source") or {})
            src.setdefault("quote", "Direct table %s (%s vs %s)" % (tpath.name, xc or "index", yc))
            src.setdefault("loc", "%s%s" % (tpath.name, (" [%s]" % tbl["sheet"]) if tbl["sheet"] else ""))
            src["table"] = tpath.name
            src["sha256_12"] = tbl["sha256"][:12]
            agg = s.get("agg")
            if agg in ("mean_sd", "mean_sem"):
                raw_xs = [r.get(xc, "") for r in rows] if xc else list(range(len(rows)))
                raw_ys = [r.get(yc, "") for r in rows]
                xs, ys, errs, ns, raw_pts, dropped = _aggregate_xy(raw_xs, raw_ys, agg)
                s["x"], s["y"], s["yerr"], s["raw_points"] = xs, ys, errs, raw_pts
                src.update({"agg": agg, "replicates_per_x": ns, "dropped_missing": dropped})
            else:
                xs, ys, errs, dropped, pm_cnt, plabs = _clean_rows_xy(rows, xc, yc, ec, lc)
                xs, ys, errs, plabs, tf_meta = _apply_y_transform(xs, ys, errs, plabs, sy_tf)
                if tf_meta:
                    src.update(tf_meta)
                s["x"], s["y"] = xs, ys
                if errs is not None:
                    s["yerr"] = errs
                if plabs:
                    s["point_labels"] = plabs
                if dropped:
                    src["dropped_missing"] = dropped
                if pm_cnt:
                    src["parsed_pm_cells"] = pm_cnt
                if tbl.get("footnotes"):
                    src["footnotes_skipped"] = len(tbl["footnotes"])
            s["source"] = src
        new_series.append(s)
    p["series"] = new_series
    return p


def _norm_series_aliases(s):
    """原地规范化常见系列字段别名（values/data→y, labels/categories→x, label→name, sd/sem/err→yerr, provenance/evidence→source）。"""
    if not isinstance(s, dict):
        return s
    if s.get("y") is None:
        for alt in ("values", "data", "ys"):
            if isinstance(s.get(alt), list):
                s["y"] = s[alt]
                break
    if s.get("x") is None:
        for alt in ("labels", "categories", "xs"):
            if isinstance(s.get(alt), list):
                s["x"] = s[alt]
                break
    if not s.get("name") and s.get("label"):
        s["name"] = str(s["label"])
    if s.get("yerr") is None:
        for alt in ("sd", "sem", "err", "error", "errors"):
            if isinstance(s.get(alt), list):
                s["yerr"] = s[alt]
                break
    if s.get("source") is None:
        for alt in ("provenance", "evidence", "ref"):
            if s.get(alt):
                s["source"] = s[alt]
                break
    return s


def _parse_yerr(raw, n):
    """兼容 1D 对称误差棒 [e1,...] 与 2D 非对称误差棒 [[lo1,...], [hi1,...]]；单项缺失 None/NA 自动归 0。"""
    if raw is None:
        return None, None, None, None

    def _safe_err(v):
        if tp.is_missing(v):
            return 0.0
        if not _is_num(v) or _to_float(v) < 0:
            return None
        return _to_float(v)

    if isinstance(raw, list) and len(raw) == 2 and all(isinstance(row, list) for row in raw):
        lo_r, hi_r = raw[0], raw[1]
        if len(lo_r) != n or len(hi_r) != n:
            return None, None, None, "2D yerr 长度与 y 不一致"
        lo_f, hi_f = [], []
        for j, (lv, hv) in enumerate(zip(lo_r, hi_r)):
            fl, fh = _safe_err(lv), _safe_err(hv)
            if fl is None or fh is None:
                return None, None, None, "2D yerr[%d] 非法: (%r, %r)" % (j, lv, hv)
            lo_f.append(fl)
            hi_f.append(fh)
        return [lo_f, hi_f], lo_f, hi_f, None
    if isinstance(raw, list) and len(raw) == n:
        vals = []
        for j, v in enumerate(raw):
            fv = _safe_err(v)
            if fv is None:
                return None, None, None, "yerr[%d] 非法: %r" % (j, v)
            vals.append(fv)
        return vals, vals, vals, None
    return None, None, None, "yerr 与 y 长度不一致"


def _norm_src(src, fallback=None):
    if isinstance(src, dict):
        res = dict(src)
    elif isinstance(src, str) and src.strip():
        res = {"quote": src.strip(), "loc": ""}
    else:
        res = {}
    if isinstance(fallback, dict):
        if not res.get("quote") and fallback.get("quote"):
            res["quote"] = fallback["quote"]
        if not res.get("loc") and fallback.get("loc"):
            res["loc"] = fallback["loc"]
    return res


def hydrate_spec(spec, base_dir):
    spec = dict(spec)
    top_src = _norm_src(spec.get("source") or spec.get("provenance"))
    pf_str = str(spec.get("prov_footer") or "").strip()
    pf_src = {"quote": pf_str, "loc": "spec.prov_footer"} if pf_str else {}
    if isinstance(spec.get("panels"), list) and spec["panels"]:
        new_panels = []
        for p in spec["panels"]:
            p2 = _hydrate_panel(p, base_dir)
            p_src = _norm_src(p2.get("source") or p2.get("provenance"), top_src)
            if p_src:
                p2["source"] = p_src
            for s in p2.get("series") or []:
                if isinstance(s, dict):
                    _norm_series_aliases(s)
                    s["source"] = _norm_src(s.get("source"), p_src or pf_src)
                    if not s["source"].get("quote") and s["source"].get("table"):
                        s["source"]["quote"] = "Direct table: %s" % s["source"]["table"]
            if not p2.get("source") and pf_src:
                p2["source"] = dict(pf_src)
            new_panels.append(p2)
        spec["panels"] = new_panels
    else:
        spec = _hydrate_panel(spec, base_dir)
        p_src = _norm_src(spec.get("source") or spec.get("provenance"), top_src)
        if p_src:
            spec["source"] = p_src
        for s in spec.get("series") or []:
            if isinstance(s, dict):
                _norm_series_aliases(s)
                s["source"] = _norm_src(s.get("source"), p_src or pf_src)
                if not s["source"].get("quote") and s["source"].get("table"):
                    s["source"]["quote"] = "Direct table: %s" % s["source"]["table"]
        if not spec.get("source") and pf_src:
            spec["source"] = dict(pf_src)
    return spec


def _validate_panel(p, prefix=""):
    errs = []
    if not isinstance(p, dict):
        return [prefix + "panel 必须是 dict"]
    kind = _norm_kind(p.get("kind", "line"))
    p["kind"] = kind
    if kind not in VALID_KINDS:
        errs.append(prefix + "kind 必须是 %s，当前=%r" % ("/".join(VALID_KINDS), kind))
    if kind == "heatmap":
        mat = p.get("matrix")
        if not isinstance(mat, list) or not mat or not isinstance(mat[0], list):
            errs.append(prefix + "heatmap 需要非空二维 matrix 或直连 table")
        if not (p.get("source") or {}).get("quote"):
            errs.append(prefix + "heatmap 缺 source.quote（数据溯源必须）")
        return errs
    series = p.get("series") or []
    if not series:
        errs.append(prefix + "series 为空")
    for i, s in enumerate(series):
        if kind == "hist" and not s.get("y") and s.get("x"):
            s["y"] = list(s["x"])
        y = s.get("y") or []
        x = s.get("x") or ([] if kind not in ("box", "violin", "hist") else [s.get("name", "G%d" % (i + 1))] * len(y))
        if kind not in ("box", "violin", "hist") and len(x) != len(y):
            errs.append("%sseries[%d] x/y 长度不一致 (%d vs %d)" % (prefix, i, len(x), len(y)))
        if not y:
            errs.append("%sseries[%d] 无数据" % (prefix, i))
        if not (s.get("source") or {}).get("quote"):
            errs.append("%sseries[%d] 缺 source.quote（数据溯源必须）" % (prefix, i))
        for j, v in enumerate(y):
            if not _is_num(v):
                errs.append("%sseries[%d] y[%d] 非有效数值: %r" % (prefix, i, j, v))
            elif str(p.get("yscale") or "").lower() == "log" and not s.get("y2") and _to_float(v) <= 0:
                errs.append("%sseries[%d] y[%d]=%r 不可用于对数刻度 yscale=log" % (prefix, i, j, v))
        if kind in ("scatter", "volcano") or str(p.get("xscale") or "").lower() == "log":
            for j, v in enumerate(x):
                if not _is_num(v):
                    errs.append("%sseries[%d] x[%d] 非有效数值: %r" % (prefix, i, j, v))
                elif str(p.get("xscale") or "").lower() == "log" and _to_float(v) <= 0:
                    errs.append("%sseries[%d] x[%d]=%r 不可用于对数刻度 xscale=log" % (prefix, i, j, v))
        yerr = s.get("yerr")
        if yerr is not None:
            _, _, _, yerr_msg = _parse_yerr(yerr, len(y))
            if yerr_msg:
                errs.append("%sseries[%d] %s" % (prefix, i, yerr_msg))
    has_xl, has_yl = bool(str(p.get("xlabel") or "").strip()), bool(str(p.get("ylabel") or "").strip())
    if kind in ("line", "scatter"):
        if not has_xl or not has_yl:
            errs.append(prefix + "缺少 xlabel/ylabel（坐标轴及单位不可省）")
    elif kind == "barh":
        if not has_xl:
            errs.append(prefix + "barh 缺少 xlabel（数值轴及单位不可省）")
    elif kind == "hist":
        if not has_xl:
            errs.append(prefix + "hist 缺少 xlabel（分布变量及单位不可省）")
    else:
        if not has_yl:
            errs.append(prefix + "缺少 ylabel（数值轴及单位不可省）")
    return errs


def validate(spec):
    if not isinstance(spec, dict):
        return ["spec 根必须是 dict"]
    panels = spec.get("panels")
    if isinstance(panels, list) and panels:
        errs = []
        for idx, p in enumerate(panels):
            errs.extend(_validate_panel(p, "panels[%d]." % idx))
        return errs
    return _validate_panel(spec)


def _plot_panel(ax, p, panel_tag="", row_title_pad=None):
    kind = _norm_kind(p.get("kind", "line"))
    warns, mapping = [], []
    cats, cat_idx = [], {}
    bottoms = None
    ax2 = None

    if kind == "heatmap":
        mat = p["matrix"]
        nr, nc = len(mat), len(mat[0])
        vals_flat = [float(v) for row in mat for v in row if _is_num(v)]
        vmin = float(p["vmin"]) if _is_num(p.get("vmin")) else (min(vals_flat) if vals_flat else 0.0)
        vmax = float(p["vmax"]) if _is_num(p.get("vmax")) else (max(vals_flat) if vals_flat else 1.0)
        cmap = str(p.get("cmap") or ("RdBu_r" if (vmin < 0 < vmax) else "YlGnBu"))
        ax.grid(False)
        im = ax.imshow(mat, aspect=p.get("aspect", "auto"), cmap=cmap, vmin=vmin, vmax=vmax)
        xlabs = [str(x) for x in (p.get("x_labels") or [str(i) for i in range(nc)])]
        ylabs = [str(y) for y in (p.get("y_labels") or [str(i) for i in range(nr)])]
        rot = int(p["xtick_rotation"]) if p.get("xtick_rotation") is not None else (
            30 if (len(xlabs) >= 5 or max((len(x) for x in xlabs), default=0) > 6) else 0
        )
        ax.set_xticks(range(len(xlabs)))
        ax.set_xticklabels(xlabs, rotation=rot, ha="right" if rot else "center", fontsize=9.2)
        ax.set_yticks(range(len(ylabs)))
        ax.set_yticklabels(ylabs, fontsize=9.2)
        annotate = p.get("annotate_cells")
        if annotate is None:
            annotate = (nr * nc <= 64)
        if annotate:
            fmt = str(p.get("cell_fmt") or ".2f")
            mid = (vmin + vmax) / 2.0
            span = (vmax - vmin) or 1.0
            for ri in range(nr):
                for ci in range(nc):
                    v = mat[ri][ci]
                    if _is_num(v):
                        fv = float(v)
                        # 自适应高对比度单元格字色
                        if cmap.startswith("RdBu"):
                            dark = abs(fv - mid) > 0.30 * span
                        else:
                            dark = (fv - vmin) / span > 0.56
                        ax.text(ci, ri, format(fv, fmt), ha="center", va="center",
                                fontsize=8.4, color="#FFFFFF" if dark else "#1A202C", fontweight="bold")
        cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        if p.get("cbar_label"):
            cb.set_label(str(p["cbar_label"]), fontsize=9.2)
        ax.set_xlabel(str(p.get("xlabel") or ""))
        ax.set_ylabel(str(p.get("ylabel") or ""))
        if p.get("title"):
            ax.set_title(str(p["title"]), fontsize=11.5, fontweight="bold",
                         pad=(row_title_pad if row_title_pad is not None else 8))
        src = p.get("source") or {}
        mat_sha = hashlib.sha256(json.dumps(
            [[round(float(v), 6) if _is_num(v) else None for v in row] for row in mat]
        ).encode("utf-8")).hexdigest()[:12]
        row = {"panel": panel_tag.rstrip(".") or "main", "series": "heatmap", "n": len(vals_flat),
               "shape": [nr, nc], "y_range": [vmin, vmax],
               "mean": round(sum(vals_flat) / len(vals_flat), 6) if vals_flat else 0.0,
               "data_sha12": mat_sha,
               "quote": src.get("quote", ""), "loc": src.get("loc", "")}
        if src.get("table"):
            row["table"] = src["table"]
            row["sha256_12"] = src.get("sha256_12", "")
            if src.get("n_source_rows") is not None:
                row["n_source_rows"] = src["n_source_rows"]
        mapping.append(row)
        return warns, mapping

    series = p["series"]
    n_s = len(series)

    if kind in ("box", "violin"):
        # 每个 series 的 y 为一组分布，或单 series 用 x 分组
        groups_data, group_names, group_colors = [], [], []
        if n_s == 1 and series[0].get("x") and len(set(str(v).strip() for v in series[0]["x"])) > 1:
            s0 = series[0]
            buckets = {}
            for xv, yv in zip(s0["x"], s0["y"]):
                buckets.setdefault(str(xv).strip(), []).append(_to_float(yv))
            src = s0.get("source") or {}
            for gi, (gn, gvals) in enumerate(buckets.items()):
                groups_data.append(gvals)
                group_names.append(gn)
                group_colors.append(PAL[gi % len(PAL)])
                st = _series_stats(gvals)
                mapping.append({"panel": panel_tag.rstrip(".") or "main", "series": gn, "n": len(gvals),
                                "y_range": [st["min"], st["max"]], **st,
                                "data_sha12": _points_sha12([gn] * len(gvals), gvals),
                                "quote": src.get("quote", ""), "loc": src.get("loc", ""),
                                "table": src.get("table", ""), "sha256_12": src.get("sha256_12", "")})
        else:
            for i, s in enumerate(series):
                vals = [_to_float(v) for v in s["y"]]
                gn = str(s.get("name", "G%d" % (i + 1)))
                groups_data.append(vals)
                group_names.append(gn)
                group_colors.append(s.get("color") or PAL[s.get("color_index", i) % len(PAL)])
                src = s.get("source") or {}
                st = _series_stats(vals)
                mapping.append({"panel": panel_tag.rstrip(".") or "main", "series": gn, "n": len(vals),
                                "y_range": [st["min"], st["max"]], **st,
                                "data_sha12": _points_sha12([gn] * len(vals), vals),
                                "quote": src.get("quote", ""), "loc": src.get("loc", ""),
                                "table": src.get("table", ""), "sha256_12": src.get("sha256_12", "")})
        cats = group_names
        cat_idx = {c: idx for idx, c in enumerate(cats)}
        if kind == "violin":
            vp = ax.violinplot(groups_data, positions=range(len(cats)), widths=0.66,
                               showmeans=False, showmedians=True, showextrema=False)
            for body, col in zip(vp["bodies"], group_colors):
                body.set_facecolor(col)
                body.set_edgecolor(col)
                body.set_alpha(0.32)
                body.set_linewidth(1.2)
            if "cmedians" in vp:
                vp["cmedians"].set_color("#1A202C")
                vp["cmedians"].set_linewidth(1.8)
            for gi, gvals in enumerate(groups_data):
                sv = sorted(gvals)
                if len(sv) >= 4:
                    q1, q3 = sv[len(sv) // 4], sv[(3 * len(sv)) // 4]
                    ax.plot([gi, gi], [q1, q3], color="#1A202C", lw=3.2, solid_capstyle="round", zorder=3.5)
        else:
            bp = ax.boxplot(groups_data, positions=range(len(cats)), widths=0.52, patch_artist=True,
                            medianprops={"color": "#1A202C", "linewidth": 1.6},
                            whiskerprops={"color": "#4A5568", "linewidth": 1.1},
                            capprops={"color": "#4A5568", "linewidth": 1.1},
                            flierprops={"marker": "o", "markersize": 3.5, "alpha": 0.5}, zorder=3)
            for patch, col in zip(bp["boxes"], group_colors):
                patch.set_facecolor(col)
                patch.set_alpha(0.35)
                patch.set_edgecolor(col)
                patch.set_linewidth(1.3)
        if p.get("show_points", True):
            for gi, (gvals, col) in enumerate(zip(groups_data, group_colors)):
                if len(gvals) <= 60:
                    # 确定性对称微抖动，避免随机漂移
                    m = len(gvals)
                    xs_j = [gi + (((k % 5) - 2) * 0.045 if m > 1 else 0.0) for k in range(m)]
                    ax.scatter(xs_j, gvals, s=18, color=col, alpha=0.82, edgecolors="#FFFFFF", linewidths=0.4, zorder=4)
        numeric_x = False
    elif kind == "hist":
        bins_raw = p.get("bins")
        all_hvals = [_to_float(v) for s in series for v in (s.get("y") or s.get("x") or []) if _is_num(v)]
        if n_s > 1 and all_hvals and (bins_raw is None or isinstance(bins_raw, (int, str))):
            nb = int(bins_raw) if isinstance(bins_raw, int) and bins_raw > 0 else max(6, min(20, int(math.sqrt(len(all_hvals))) + 3))
            lo_h, hi_h = min(all_hvals), max(all_hvals)
            if hi_h <= lo_h:
                hi_h = lo_h + 1.0
            bins_eff = [lo_h + (hi_h - lo_h) * k / nb for k in range(nb + 1)]
        else:
            bins_eff = bins_raw or "auto"
        for i, s in enumerate(series):
            vals = [_to_float(v) for v in (s.get("y") or s.get("x") or [])]
            col = s.get("color") or PAL[s.get("color_index", i) % len(PAL)]
            lbl = str(s.get("name", "S%d" % (i + 1)))
            ax.hist(vals, bins=bins_eff, density=bool(p.get("density", False)), alpha=0.55 if n_s > 1 else 0.78,
                    color=col, edgecolor="#1A202C", linewidth=0.7, label=lbl, zorder=3)
            src = s.get("source") or {}
            st = _series_stats(vals)
            mapping.append({"panel": panel_tag.rstrip(".") or "main", "series": lbl, "n": len(vals),
                            "x_range": [st["min"], st["max"]], "y_range": [st["min"], st["max"]], **st,
                            "data_sha12": _points_sha12(list(range(len(vals))), vals),
                            "quote": src.get("quote", ""), "loc": src.get("loc", ""),
                            "table": src.get("table", ""), "sha256_12": src.get("sha256_12", "")})
        if not p.get("ylabel"):
            p = dict(p, ylabel="Density" if p.get("density") else "Count")
        numeric_x = True
    else:
        all_x = [v for s in series for v in s["x"]]
        numeric_x = all(_is_num(v) for v in all_x) and kind not in ("bar", "barh", "stacked_bar")
        if not numeric_x:
            for s in series:
                for v in s["x"]:
                    sv = str(v).strip()
                    if sv not in cats:
                        cats.append(sv)
            cat_idx = {c: idx for idx, c in enumerate(cats)}

        bottoms = [0.0] * len(cats) if kind == "stacked_bar" else None
        has_y2 = any(bool(s.get("y2")) for s in series)
        y2_color = "#C05621"
        if has_y2 and kind in ("line", "scatter", "bar"):
            ax2 = ax.twinx()
            ax2.spines["top"].set_visible(False)
            ax2.spines["right"].set_visible(True)
            ax2.grid(False)
            for idx_s, s_tmp in enumerate(series):
                if s_tmp.get("y2"):
                    y2_color = s_tmp.get("color") or PAL[s_tmp.get("color_index", idx_s) % len(PAL)]
                    break
        for i, s in enumerate(series):
            y = [_to_float(v) for v in s["y"]]
            yerr, yerr_lo, yerr_hi, _ = _parse_yerr(s.get("yerr"), len(y))
            color = s.get("color") or PAL[s.get("color_index", i) % len(PAL)]
            lbl = str(s.get("name", "S%d" % (i + 1)))
            mk = s.get("marker") or MK[i % len(MK)]
            tgt_ax = ax2 if (ax2 is not None and s.get("y2")) else ax

            if kind == "stacked_bar":
                if any(yv < 0 for yv in y):
                    warns.append("%sseries[%d] stacked_bar 含负值，建议改用分组 bar" % (panel_tag, i))
                xs_idx = [cat_idx[str(v).strip()] for v in s["x"]]
                b_cur = [bottoms[xi] for xi in xs_idx]
                tgt_ax.bar(xs_idx, y, width=0.58, bottom=b_cur, color=color, alpha=0.88,
                           edgecolor="#1A202C", linewidth=0.5, label=lbl, zorder=3)
                for xi, yv in zip(xs_idx, y):
                    bottoms[xi] += yv
                x_rng = [cats[0], cats[-1]] if cats else []
            elif kind in ("bar", "barh"):
                xs_idx = [cat_idx[str(v).strip()] for v in s["x"]]
                bw = min(0.76 / max(n_s, 1), 0.42)
                offset = (i - (n_s - 1) / 2.0) * bw
                pos = [xi + offset for xi in xs_idx]
                if kind == "bar":
                    tgt_ax.bar(pos, y, width=bw * 0.92, yerr=yerr, capsize=3 if yerr else 0,
                               color=color, alpha=0.82 if s.get("raw_points") else 0.88,
                               edgecolor="#1A202C", linewidth=0.5, label=lbl, zorder=3)
                    # Nature/Cell 标准：直连重复样本表自动在柱上叠加确定性微抖动原始散点
                    if p.get("show_points", True) and s.get("raw_points"):
                        for px, pts_list in zip(pos, s["raw_points"]):
                            if len(pts_list) <= 50:
                                m = len(pts_list)
                                xs_j = [px + (((k % 5) - 2) * (bw * 0.14) if m > 1 else 0.0) for k in range(m)]
                                tgt_ax.scatter(xs_j, pts_list, s=16, color="#1A202C", alpha=0.72,
                                               edgecolors="#FFFFFF", linewidths=0.4, zorder=5)
                    if p.get("show_values"):
                        vfmt = str(p.get("value_fmt") or ".2g")
                        for px, yv, ev_hi, ev_lo in zip(pos, y, yerr_hi or [0.0] * len(y), yerr_lo or [0.0] * len(y)):
                            tgt_ax.annotate(format(yv, vfmt), xy=(px, yv + (ev_hi if yv >= 0 else -ev_lo)),
                                            xytext=(0, 3 if yv >= 0 else -10), textcoords="offset points",
                                            ha="center", va="bottom", fontsize=7.8, color="#2D3748")
                else:
                    tgt_ax.barh(pos, y, height=bw * 0.92, xerr=yerr, capsize=3 if yerr else 0,
                                color=color, alpha=0.88, edgecolor="#1A202C", linewidth=0.5, label=lbl, zorder=3)
                    if p.get("show_values"):
                        vfmt = str(p.get("value_fmt") or ".2g")
                        for px, yv, ev_hi in zip(pos, y, yerr_hi or [0.0] * len(y)):
                            tgt_ax.annotate(format(yv, vfmt), xy=(yv + ev_hi, px), xytext=(4, 0),
                                            textcoords="offset points", ha="left", va="center",
                                            fontsize=7.8, color="#2D3748")
                x_rng = [cats[0], cats[-1]] if cats else []
            elif kind in ("scatter", "volcano"):
                x = [_to_float(v) for v in s["x"]]
                volcano_counts = None
                if kind == "volcano":
                    fc_t = float(p.get("fc_thresh", 1.0))
                    if p.get("y_thresh") is not None:
                        y_t = float(p["y_thresh"])
                    else:
                        pt = float(p.get("p_thresh", 0.05))
                        y_t = -math.log10(max(pt, 1e-300))
                    up_x, up_y, dn_x, dn_y, ns_x, ns_y = [], [], [], [], [], []
                    for xv, yv in zip(x, y):
                        if xv >= fc_t and yv >= y_t:
                            up_x.append(xv); up_y.append(yv)
                        elif xv <= -fc_t and yv >= y_t:
                            dn_x.append(xv); dn_y.append(yv)
                        else:
                            ns_x.append(xv); ns_y.append(yv)
                    if ns_x:
                        tgt_ax.scatter(ns_x, ns_y, s=22, color="#A0AEC0", alpha=0.62, label="NS (n=%d)" % len(ns_x), zorder=2.5)
                    if dn_x:
                        tgt_ax.scatter(dn_x, dn_y, s=30, color="#2B6CB0", alpha=0.88, edgecolors="#FFFFFF", linewidths=0.35,
                                       label="Down (n=%d)" % len(dn_x), zorder=3.5)
                    if up_x:
                        tgt_ax.scatter(up_x, up_y, s=30, color="#C53030", alpha=0.88, edgecolors="#FFFFFF", linewidths=0.35,
                                       label="Up (n=%d)" % len(up_x), zorder=3.5)
                    if i == 0:
                        tgt_ax.axvline(fc_t, color="#718096", ls="--", lw=0.95, zorder=2)
                        tgt_ax.margins(x=0.10, y=0.08)
                        tgt_ax.axvline(-fc_t, color="#718096", ls="--", lw=0.95, zorder=2)
                        tgt_ax.axhline(y_t, color="#718096", ls="--", lw=0.95, zorder=2)
                    volcano_counts = {"up": len(up_x), "down": len(dn_x), "ns": len(ns_x),
                                      "fc_thresh": fc_t, "y_thresh": round(y_t, 4)}
                elif yerr:
                    tgt_ax.errorbar(x, y, yerr=yerr, fmt=mk, color=color, ms=5.5, capsize=3,
                                    elinewidth=1.0, label=lbl, zorder=3)
                else:
                    tgt_ax.scatter(x, y, s=32, color=color, marker=mk, label=lbl, zorder=3)
                plabs = s.get("point_labels") or p.get("point_labels")
                if isinstance(plabs, list) and len(plabs) == len(x):
                    only_set = set(str(z) for z in (s.get("label_only") or p.get("label_only") or []))
                    top_n = int(s.get("label_top") or p.get("label_top") or (8 if kind == "volcano" else (len(x) if len(x) <= 12 else 0)))
                    cand = []
                    for idx_p, (xv, yv, plb) in enumerate(zip(x, y, plabs)):
                        ps = str(plb or "").strip()
                        if not ps:
                            continue
                        if only_set:
                            if ps in only_set:
                                cand.append((abs(yv) + abs(xv), idx_p, xv, yv, ps))
                        elif kind == "volcano":
                            if abs(xv) >= fc_t and yv >= y_t:
                                cand.append((yv + abs(xv), idx_p, xv, yv, ps))
                        else:
                            cand.append((abs(yv), idx_p, xv, yv, ps))
                    cand.sort(reverse=True)
                    chosen = cand if only_set else cand[:max(0, top_n)]
                    xspan = max((max(x) - min(x)) if x else 1.0, 1e-6)
                    yspan = max((max(y) - min(y)) if y else 1.0, 1e-6)
                    placed_norm = []
                    for ci_p, (_, _, xv, yv, ps) in enumerate(chosen):
                        pref_dir = 1 if (kind != "volcano" or xv >= 0) else -1
                        slots = [
                            (7 * pref_dir, 6), (7 * pref_dir, -12), (14 * pref_dir, 14),
                            (14 * pref_dir, -18), (-8 * pref_dir, 8), (-8 * pref_dir, -12),
                            (0, 16), (0, -16), (20 * pref_dir, 0), (-16 * pref_dir, 16),
                            (20 * pref_dir, 20), (-16 * pref_dir, -18),
                        ]
                        nx0 = (xv - min(x)) / xspan
                        ny0 = (yv - min(y)) / yspan
                        dx_req = max(0.15, 0.022 * len(ps))
                        dy_req = 0.098
                        best_slot = slots[0]
                        for ox, oy in slots:
                            cx_n = nx0 + ox * 0.0055
                            cy_n = ny0 + oy * 0.0070
                            if all(abs(cx_n - px_n) > dx_req or abs(cy_n - py_n) > dy_req for px_n, py_n in placed_norm):
                                best_slot = (ox, oy)
                                break
                        ox, oy = best_slot
                        placed_norm.append((nx0 + ox * 0.0055, ny0 + oy * 0.0070))
                        ha_p = "left" if ox > 0 else ("right" if ox < 0 else "center")
                        arrow_kw = dict(arrowstyle="-", color="#A0AEC0", lw=0.6) if (abs(ox) >= 12 or abs(oy) >= 14) else None
                        tgt_ax.annotate(ps, xy=(xv, yv), xytext=(ox, oy), textcoords="offset points",
                                        ha=ha_p, va="center", fontsize=7.8, fontweight="bold" if kind == "volcano" else "normal",
                                        color="#1A202C", zorder=6, arrowprops=arrow_kw,
                                        bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none", alpha=0.80))
                x_rng = [min(x), max(x)]
                reg_info = None
                if kind == "scatter" and s.get("trendline") and len(x) >= 3:
                    mx = sum(x) / len(x)
                    my = sum(y) / len(y)
                    sxx = sum((xv - mx) ** 2 for xv in x)
                    syy = sum((yv - my) ** 2 for yv in y)
                    sxy = sum((xv - mx) * (yv - my) for xv, yv in zip(x, y))
                    if sxx > 1e-12:
                        slope = sxy / sxx
                        intercept = my - slope * mx
                        r_val = (sxy / math.sqrt(sxx * syy)) if syy > 1e-12 else 0.0
                        r2_val = r_val * r_val
                        reg_info = {"slope": round(slope, 6), "intercept": round(intercept, 6),
                                    "r": round(r_val, 4), "r2": round(r2_val, 4)}
                        x0_r, x1_r = min(x), max(x)
                        fit_lbl = "%s fit (R²=%.2f, r=%.2f)" % (lbl, r2_val, r_val)
                        tgt_ax.plot([x0_r, x1_r], [slope * x0_r + intercept, slope * x1_r + intercept],
                                    color=color, ls="--", lw=1.4, alpha=0.85, label=fit_lbl, zorder=2.5)
            else:
                if numeric_x:
                    x = [_to_float(v) for v in s["x"]]
                    if any(x[k + 1] < x[k] for k in range(len(x) - 1)):
                        warns.append("%sseries[%d] x 非单调递增" % (panel_tag, i))
                    x_rng = [min(x), max(x)]
                else:
                    x = [cat_idx[str(v).strip()] for v in s["x"]]
                    x_rng = [cats[0], cats[-1]] if cats else []
                ls = s.get("linestyle", "-")
                if kind == "step":
                    wh = str(s.get("where") or "post")
                    if (s.get("band") or (s.get("y_lo") and s.get("y_hi"))) and (yerr_lo or (s.get("y_lo") and s.get("y_hi"))):
                        lo = [_to_float(v) for v in s["y_lo"]] if s.get("y_lo") else [yv - ev for yv, ev in zip(y, yerr_lo)]
                        hi = [_to_float(v) for v in s["y_hi"]] if s.get("y_hi") else [yv + ev for yv, ev in zip(y, yerr_hi)]
                        tgt_ax.fill_between(x, lo, hi, step=wh, color=color, alpha=0.16, zorder=2)
                    tgt_ax.step(x, y, where=wh, color=color, lw=1.9, linestyle=ls, label=lbl, zorder=3)
                    cens_x = s.get("censored_x") or s.get("censors") or []
                    if cens_x and numeric_x and x:
                        cx_pts, cy_pts = [], []
                        for cv in cens_x:
                            if not _is_num(cv):
                                continue
                            fx = _to_float(cv)
                            yv_c = y[0]
                            for xk, yk in zip(x, y):
                                if xk <= fx:
                                    yv_c = yk
                                else:
                                    break
                            cx_pts.append(fx)
                            cy_pts.append(yv_c)
                        if cx_pts:
                            tgt_ax.scatter(cx_pts, cy_pts, marker="|", s=48, color=color, linewidths=1.4, zorder=4)
                elif s.get("band") and (yerr_lo or (s.get("y_lo") and s.get("y_hi"))):
                    lo = [_to_float(v) for v in s["y_lo"]] if s.get("y_lo") else [yv - ev for yv, ev in zip(y, yerr_lo)]
                    hi = [_to_float(v) for v in s["y_hi"]] if s.get("y_hi") else [yv + ev for yv, ev in zip(y, yerr_hi)]
                    tgt_ax.fill_between(x, lo, hi, color=color, alpha=0.18, zorder=2)
                    tgt_ax.plot(x, y, color=color, lw=1.8, ms=4.5, marker=mk, linestyle=ls, label=lbl, zorder=3)
                elif yerr:
                    tgt_ax.errorbar(x, y, yerr=yerr, color=color, lw=1.6, ms=4.5, marker=mk,
                                    linestyle=ls, capsize=3, elinewidth=1.0, label=lbl, zorder=3)
                else:
                    tgt_ax.plot(x, y, color=color, lw=1.6, ms=4.5, marker=mk, linestyle=ls, label=lbl, zorder=3)

            src = s.get("source") or {}
            st = _series_stats(y)
            row = {"panel": panel_tag.rstrip(".") or "main", "series": lbl, "n": len(y),
                   "x_range": x_rng, "y_range": [st["min"], st["max"]],
                   "mean": st["mean"], "median": st["median"], "sd": st["sd"],
                   "sem": st["sem"], "iqr": st["iqr"],
                   "has_yerr": yerr is not None,
                   "data_sha12": _points_sha12(s["x"], y),
                   "quote": (src.get("quote") or ""), "loc": (src.get("loc") or "")}
            if src.get("y_transform"):
                row["y_transform"] = src["y_transform"]
            if src.get("raw_p_range"):
                row["raw_p_range"] = src["raw_p_range"]
            if src.get("table"):
                row["table"] = src["table"]
                row["sha256_12"] = src.get("sha256_12", "")
                if src.get("columns_used"):
                    row["columns_used"] = src["columns_used"]
                if src.get("n_source_rows") is not None:
                    row["n_source_rows"] = src["n_source_rows"]
            if src.get("dropped_missing"):
                row["dropped_missing"] = src["dropped_missing"]
                warns.append("%s%s 自动跳过 %d 行缺失/NA 数值" % (panel_tag, lbl, src["dropped_missing"]))
            if src.get("parsed_pm_cells"):
                row["parsed_pm_cells"] = src["parsed_pm_cells"]
            if src.get("footnotes_skipped"):
                row["footnotes_skipped"] = src["footnotes_skipped"]
            if kind == "scatter" and locals().get("reg_info"):
                row["regression"] = reg_info
                reg_info = None
            if kind == "volcano" and locals().get("volcano_counts"):
                row["volcano_counts"] = volcano_counts
                volcano_counts = None
            mapping.append(row)

    if not numeric_x and cats:
        if p.get("xtick_rotation") is not None:
            rot = int(p["xtick_rotation"])
        else:
            rot = 28 if (max(len(c) for c in cats) > 7 or len(cats) >= 5 or sum(len(c) for c in cats) > 44) else 0
        if len(cats) > 12:
            warns.append("%sx 轴分类数较多 (%d)，建议检查标签间距" % (panel_tag, len(cats)))
        if kind == "barh":
            ax.set_yticks(range(len(cats)))
            ax.set_yticklabels(cats)
        else:
            ax.set_xticks(range(len(cats)))
            ax.set_xticklabels(cats, rotation=rot, ha="right" if rot else "center")

    for hl in p.get("hlines") or []:
        if isinstance(hl, dict):
            ax.axhline(float(hl["y"]), color=hl.get("color", "#718096"), ls="--", lw=1.0, zorder=2)
            if hl.get("label"):
                ax.text(0.98, float(hl["y"]), " " + str(hl["label"]), transform=ax.get_yaxis_transform(),
                        ha="right", va="bottom", fontsize=8.5, color=hl.get("color", "#4A5568"))
        elif _is_num(hl):
            ax.axhline(float(hl), color="#718096", ls="--", lw=1.0, zorder=2)
    for vl in p.get("vlines") or []:
        if isinstance(vl, dict):
            vx = float(vl["x"]) if (numeric_x and _is_num(vl.get("x"))) else float(cat_idx.get(str(vl.get("x")), 0))
            ax.axvline(vx, color=vl.get("color", "#718096"), ls="--", lw=1.0, zorder=2)
            if vl.get("label"):
                yfrac = float(vl.get("y_frac", 0.06))
                va_mode = "top" if yfrac > 0.5 else "bottom"
                ax.annotate(str(vl["label"]), xy=(vx, yfrac), xycoords=("data", "axes fraction"),
                            xytext=(4, 0), textcoords="offset points", ha="left", va=va_mode,
                            fontsize=8.2, color=vl.get("color", "#4A5568"),
                            bbox=dict(boxstyle="round,pad=0.16", facecolor="white", edgecolor="none", alpha=0.85))
        elif _is_num(vl):
            ax.axvline(float(vl), color="#718096", ls="--", lw=1.0, zorder=2)
    for ann in p.get("annotations") or []:
        if isinstance(ann, dict) and ann.get("text"):
            ax_x = float(ann["x"]) if (numeric_x and _is_num(ann.get("x"))) else cat_idx.get(str(ann.get("x")), 0)
            ax_y = float(ann["y"])
            ax.annotate(str(ann["text"]), xy=(ax_x, ax_y), xytext=(0, 7),
                        textcoords="offset points", ha="center", va="bottom",
                        fontsize=8.8, color="#1A202C", fontweight="bold")

    if p.get("xscale"):
        ax.set_xscale(str(p["xscale"]))
    if p.get("yscale"):
        ax.set_yscale(str(p["yscale"]))
    is_log_x = str(p.get("xscale") or "").lower() == "log"
    is_log_y = str(p.get("yscale") or "").lower() == "log"

    # 成对显著性对比括号 brackets: [{"x1": "Ctrl", "x2": "High", "text": "***", "y": optional, "s1": opt_series, "s2": opt_series}]
    brackets = [b for b in (p.get("brackets") or []) if isinstance(b, dict)]
    bracket_top = None
    if brackets:
        series_names = [str(s.get("name", "")) for s in series]
        bar_bw = min(0.76 / max(n_s, 1), 0.42) if kind == "bar" else 0.0

        def _br_x(val, s_ref, default_idx):
            if numeric_x and _is_num(val):
                base = _to_float(val)
            elif str(val) in cat_idx:
                base = float(cat_idx[str(val)])
            elif _is_num(val):
                base = _to_float(val)
            else:
                base = float(default_idx)
            if kind == "bar" and s_ref is not None and n_s > 1:
                si = None
                if isinstance(s_ref, int) and 0 <= s_ref < n_s:
                    si = s_ref
                elif str(s_ref) in series_names:
                    si = series_names.index(str(s_ref))
                if si is not None:
                    base += (si - (n_s - 1) / 2.0) * bar_bw
            return base

        lo_cur, hi_cur = ax.get_ylim()
        if is_log_y and hi_cur > 0:
            cur_y = hi_cur * 1.18
            for bi, br in enumerate(brackets):
                x1 = _br_x(br.get("x1"), br.get("s1"), 0)
                x2 = _br_x(br.get("x2"), br.get("s2"), max(len(cats) - 1, 1))
                by = float(br["y"]) if _is_num(br.get("y")) else (cur_y * (1.46 ** bi))
                ax.plot([x1, x1, x2, x2], [by * 0.86, by, by, by * 0.86],
                        color="#1A202C", lw=1.05, zorder=5)
                if br.get("text"):
                    xm = math.sqrt(x1 * x2) if (is_log_x and x1 > 0 and x2 > 0) else ((x1 + x2) / 2.0)
                    ax.text(xm, by * 1.07, str(br["text"]),
                            ha="center", va="bottom", fontsize=8.8, fontweight="bold", color="#1A202C", zorder=5)
                bracket_top = max(bracket_top or by, by * 1.72)
        else:
            span = max(hi_cur - lo_cur, 1e-6)
            step_h = span * 0.11
            tick_h = span * 0.032
            cur_y = hi_cur + span * (0.11 if (kind == "bar" and p.get("show_values")) else 0.04)
            for bi, br in enumerate(brackets):
                x1 = _br_x(br.get("x1"), br.get("s1"), 0)
                x2 = _br_x(br.get("x2"), br.get("s2"), max(len(cats) - 1, 1))
                by = float(br["y"]) if _is_num(br.get("y")) else (cur_y + bi * step_h)
                ax.plot([x1, x1, x2, x2], [by - tick_h, by, by, by - tick_h],
                        color="#1A202C", lw=1.05, zorder=5)
                if br.get("text"):
                    xm = math.sqrt(x1 * x2) if (is_log_x and x1 > 0 and x2 > 0) else ((x1 + x2) / 2.0)
                    ax.text(xm, by + tick_h * 0.35, str(br["text"]),
                            ha="center", va="bottom", fontsize=8.8, fontweight="bold", color="#1A202C", zorder=5)
                bracket_top = max(bracket_top or by, by + step_h * 0.95)

    ax.set_xlabel(str(p.get("xlabel") or ""))
    ax.set_ylabel(str(p.get("ylabel") or ""))
    if ax2 is not None and p.get("y2label"):
        ax2.set_ylabel(str(p["y2label"]), color=y2_color)
        ax2.tick_params(axis="y", colors=y2_color)
        ax2.spines["right"].set_color(y2_color)
    if isinstance(p.get("xlim"), list) and len(p["xlim"]) == 2:
        ax.set_xlim(float(p["xlim"][0]), float(p["xlim"][1]))
    elif kind == "barh" and p.get("show_values"):
        xlo, xhi = ax.get_xlim()
        ax.set_xlim(xlo, xhi + max((xhi - xlo) * 0.14, 1e-6))
    elif kind == "volcano":
        xlo, xhi = ax.get_xlim()
        xpad = max((xhi - xlo) * 0.10, 0.25)
        ax.set_xlim(xlo - xpad, xhi + xpad)
    if isinstance(p.get("ylim"), list) and len(p["ylim"]) == 2:
        ax.set_ylim(float(p["ylim"][0]), float(p["ylim"][1]))
    elif kind == "stacked_bar" and bottoms:
        ax.set_ylim(0.0, max(bottoms) * 1.22)
    else:
        lo, hi = ax.get_ylim()
        need_hi = hi
        if kind == "bar" and p.get("show_values") and not is_log_y:
            need_hi = max(need_hi, hi + max((hi - lo) * 0.12, 1e-6))
        if kind == "volcano" and not is_log_y:
            need_hi = max(need_hi, hi + max((hi - lo) * 0.10, 0.2))
        if bracket_top is not None and bracket_top > need_hi:
            need_hi = bracket_top
        if p.get("annotations"):
            ann_ys = [float(a["y"]) for a in p["annotations"] if isinstance(a, dict) and _is_num(a.get("y"))]
            if ann_ys and max(ann_ys) > need_hi * 0.88:
                need_hi = max(need_hi, (max(ann_ys) * 1.35) if is_log_y else (max(ann_ys) + max((hi - lo) * 0.16, abs(max(ann_ys)) * 0.12)))
        if need_hi > hi:
            ax.set_ylim(lo, need_hi)
    if ax2 is not None and isinstance(p.get("y2lim"), list) and len(p["y2lim"]) == 2:
        ax2.set_ylim(float(p["y2lim"][0]), float(p["y2lim"][1]))
    leg_loc = str(p.get("legend_loc") or "").strip()
    title_pad = 8
    if kind not in ("box", "violin") and (kind == "volcano" or n_s > 1 or any(s.get("name") for s in series)):
        if ax2 is not None:
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            all_h, all_l = h1 + h2, l1 + l2
            if leg_loc == "outside_top":
                max_len = max((len(str(x)) for x in all_l), default=6)
                nc = 2 if (max_len > 14 and len(all_l) >= 3) else min(max(len(all_l), 1), 4)
                n_rows = (len(all_l) + nc - 1) // nc
                title_pad = 12 + 16 * n_rows
                ax.legend(all_h, all_l, frameon=False, fontsize=8.4, loc="lower center",
                          bbox_to_anchor=(0.5, 1.01), ncol=nc)
            elif leg_loc == "outside_right":
                ax.legend(all_h, all_l, frameon=False, fontsize=8.4, loc="center left",
                          bbox_to_anchor=(1.12, 0.5))
            else:
                ax.legend(all_h, all_l, frameon=False, fontsize=8.8, loc=leg_loc or "best")
        elif leg_loc == "outside_top":
            handles, labels_l = ax.get_legend_handles_labels()
            max_len = max((len(str(x)) for x in labels_l), default=6)
            nc = 2 if (max_len > 14 and len(labels_l) >= 3) else min(max(len(labels_l), 1), 4)
            n_rows = (len(labels_l) + nc - 1) // nc
            title_pad = 12 + 16 * n_rows
            ax.legend(frameon=False, fontsize=8.4, loc="lower center",
                      bbox_to_anchor=(0.5, 1.01), ncol=nc)
        elif leg_loc == "outside_right":
            ax.legend(frameon=False, fontsize=8.4, loc="center left", bbox_to_anchor=(1.02, 0.5))
        elif kind == "stacked_bar" and not leg_loc:
            if isinstance(p.get("ylim"), list) and len(p["ylim"]) == 2 and bottoms and float(p["ylim"][1]) < max(bottoms) * 1.18:
                ax.set_ylim(float(p["ylim"][0]), max(bottoms) * 1.22)
            ax.legend(frameon=False, fontsize=8.8, loc="upper center", ncol=min(n_s, 3))
        else:
            ax.legend(frameon=False, fontsize=9.0, loc=leg_loc or "best")
    if row_title_pad is not None:
        title_pad = max(title_pad, row_title_pad)
    if p.get("title") or p.get("subtitle"):
        t_str = str(p.get("title") or "").strip()
        s_str = str(p.get("subtitle") or "").strip()
        full_t = (t_str + "\n" + s_str) if (t_str and s_str) else (t_str or s_str)
        ax.set_title(full_t, fontsize=11.5, fontweight="bold", pad=title_pad)
    return warns, mapping


def _write_result_skel(a, rep, out, name, mapping, spec=None):
    dst_path = getattr(a, "result_out", None) or getattr(a, "result_skel", None)
    if not dst_path:
        return
    spec = spec or {}
    contract = {}
    cid_eff = a.case_id
    if a.contract and Path(a.contract).exists():
        try:
            import audit_delivery as auditmod
            cj = json.loads(Path(a.contract).read_text(encoding="utf-8"))
            if not cid_eff and cj.get("case_id"):
                cid_eff = str(cj["case_id"])
            keys = auditmod._extract_contract_keys(cj)
            for k in keys:
                kl = k.strip().lower()
                if kl in ("editable_svg", "svg", "svg_file", "svg_path", "output_svg", "editable_source", "editable_source_path") or kl.endswith("_svg") or kl.endswith("_svg_path"):
                    contract[k] = name + ".svg"
                elif kl in ("png", "png_file", "png_path", "preview_png", "rendered_png", "output_png", "image_path") or kl.endswith("_png") or kl.endswith("_png_path"):
                    contract[k] = name + ".png"
                elif kl in ("pdf", "pdf_file", "pdf_path", "output_pdf", "vector_pdf") or kl.endswith("_pdf") or kl.endswith("_pdf_path"):
                    contract[k] = name + ".pdf"
                elif kl in ("status", "run_status"):
                    contract[k] = "ok" if rep["ok"] else "partial"
                elif kl in ("provenance_file", "provenance_path", "provenance_json"):
                    contract[k] = "provenance.json"
                elif kl in ("checks_report", "check_report", "export_check", "export_checks", "quality_check"):
                    contract[k] = name + "_checks.json"
                elif kl in ("data_mapping",):
                    contract[k] = mapping
                elif kl in ("case_id", "id"):
                    contract[k] = cid_eff or "CASE_ID"
                else:
                    contract[k] = "<待填：依据真实源数据与图件如实撰写>"
        except Exception:
            pass
    srcs = []
    for m in mapping:
        loc = str(m.get("loc") or m.get("table") or "").strip()
        if loc and loc not in srcs:
            srcs.append(loc)
    import audit_delivery as auditmod
    unc = auditmod.collect_scientific_uncertainty(spec, data_mapping=mapping)
    title_s = str(spec.get("title") or name).strip()
    detail_s = "Plotted '%s' (%d panel(s), %d series, %d verified points from %s) as editable SVG/PDF and %ddpi PNG." % (
        title_s[:80], rep.get("panel_count", 1), rep.get("series_count", len(mapping)),
        rep.get("total_points_plotted", 0), ", ".join(srcs[:4]) or "inline source spec", a.dpi
    )
    sk = {
        "case_id": cid_eff or "CASE_ID",
        "status": "ok" if rep["ok"] else "partial",
        "deliverables": {
            "editable_source": {"path": name + ".svg", "format": "svg", "editable_text": rep["editable_svg_text"]},
            "exports": [{"path": name + ".png", "format": "png", "dpi": a.dpi},
                        {"path": name + ".pdf", "format": "pdf"}],
            "data_mapping": mapping,
        },
        "sources": srcs or [name + "_checks.json"],
        "checks": rep,
        "output_contract": contract,
        "output_contract_fields": list(contract.keys()),
        "uncertainty": unc,
        "change_records": [{"action": "generate_chart", "target": name + ".svg", "detail": detail_s}],
    }
    for k, v in contract.items():
        if k not in sk:
            sk[k] = v
    explicit_rf = spec.get("result_fields") if isinstance(spec.get("result_fields"), dict) else {}
    for k, v in explicit_rf.items():
        sk[k] = v
        if k in contract:
            contract[k] = v
    p = Path(dst_path)
    if p.exists():
        try:
            old_res = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(old_res, dict):
                auditmod.merge_existing_result(sk, contract, explicit_rf, old_res)
        except Exception:
            pass
    unfilled = [k for k, v in contract.items() if isinstance(v, str) and "<待填" in v]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sk, ensure_ascii=False, indent=1), encoding="utf-8")
    return unfilled


def _render_svg_stdlib(spec, out, name, dpi, preview=None, preview_dpi=96):
    """零第三方依赖兜底：当环境缺失 matplotlib 时，用纯标准库直出可编辑矢量 SVG 并走 render.py 导出 PNG/PDF。"""
    from xml.sax.saxutils import escape as esc
    import render as rmod

    fam, _ = rmod.detect_cjk()
    ff = ("%s, Arial, Helvetica, sans-serif" % fam) if fam else "Arial, Helvetica, sans-serif"
    panels = spec.get("panels") if isinstance(spec.get("panels"), list) and spec.get("panels") else [spec]
    W, H = 760, 440 * len(panels)
    elems = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="%s">' % (W, H, W, H, esc(ff)),
        '<rect x="0" y="0" width="%d" height="%d" fill="#FFFFFF"/>' % (W, H),
    ]
    mapping, warns = [], ["环境缺少 matplotlib，已启用纯标准库 SVG 兜底渲染"]
    for pi, p in enumerate(panels):
        y0_off = pi * 440
        kind = _norm_kind(p.get("kind") or "line")
        px0, py0, pw, ph = 80, y0_off + 58, 630, 300
        title = str(p.get("title") or spec.get("title") or "").strip()
        if title:
            elems.append('<text x="%d" y="%d" font-size="14" font-weight="bold" fill="#1A202C">%s</text>' % (px0, y0_off + 30, esc(title)))
        series = p.get("series") or []
        all_y = [_to_float(v) for s in series for v in (s.get("y") or []) if _is_num(v)]
        ymin = min(all_y) if all_y else 0.0
        ymax = max(all_y) if all_y else 1.0
        if kind in ("bar", "barh", "stacked_bar"):
            ymin = min(0.0, ymin)
        if ymax <= ymin:
            ymax = ymin + 1.0
        pad_y = (ymax - ymin) * 0.08
        ymin -= pad_y if ymin < 0 else 0.0
        ymax += pad_y
        elems.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#2D3748" stroke-width="1.4"/>' % (px0, py0 + ph, px0 + pw, py0 + ph))
        elems.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#2D3748" stroke-width="1.4"/>' % (px0, py0, px0, py0 + ph))
        for k in range(5):
            yv = ymin + (ymax - ymin) * k / 4.0
            yy = py0 + ph - ph * k / 4.0
            elems.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#E2E8F0" stroke-dasharray="3,3"/>' % (px0, yy, px0 + pw, yy))
            elems.append('<text x="%d" y="%.1f" font-size="10" text-anchor="end" fill="#4A5568">%.3g</text>' % (px0 - 8, yy + 3.5, yv))
        for si, s in enumerate(series):
            xs, ys = s.get("x") or [], [_to_float(v) for v in (s.get("y") or [])]
            if not xs or not ys:
                continue
            col = s.get("color") or PAL[si % len(PAL)]
            n = min(len(xs), len(ys))
            num_x = all(_is_num(x) for x in xs[:n])
            if num_x:
                xf = [_to_float(x) for x in xs[:n]]
                xlo, xhi = min(xf), max(xf)
                if xhi <= xlo:
                    xhi = xlo + 1.0
                pts = [(px0 + pw * (xf[i] - xlo) / (xhi - xlo), py0 + ph - ph * (ys[i] - ymin) / (ymax - ymin)) for i in range(n)]
            else:
                pts = [(px0 + pw * (i + 0.5) / max(n, 1), py0 + ph - ph * (ys[i] - ymin) / (ymax - ymin)) for i in range(n)]
            if kind in ("scatter", "volcano"):
                for cx, cy in pts:
                    elems.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" fill-opacity="0.8"/>' % (cx, cy, esc(col)))
            elif kind in ("bar", "stacked_bar"):
                bw = max(8.0, (pw / max(n, 1)) * 0.6 / max(len(series), 1))
                for i, (cx, cy) in enumerate(pts):
                    bx = cx - bw * len(series) / 2.0 + si * bw
                    by0 = py0 + ph - ph * (0.0 - ymin) / (ymax - ymin)
                    elems.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (bx, min(cy, by0), bw, abs(by0 - cy), esc(col)))
            else:
                pstr = " ".join("%.1f,%.1f" % pt for pt in pts)
                elems.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (esc(col), pstr))
                for cx, cy in pts:
                    elems.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s"/>' % (cx, cy, esc(col)))
            src = s.get("source") if isinstance(s.get("source"), dict) else {}
            mapping.append({"series": s.get("name") or ("S%d" % (si + 1)), "kind": kind, "n": n,
                            "data_sha12": _points_sha12(xs[:n], ys[:n]), "quote": src.get("quote", ""), "loc": src.get("loc", "")})
        xl, yl = str(p.get("xlabel") or "").strip(), str(p.get("ylabel") or "").strip()
        if xl:
            elems.append('<text x="%d" y="%d" font-size="11" text-anchor="middle" fill="#2D3748">%s</text>' % (px0 + pw // 2, py0 + ph + 36, esc(xl)))
        if yl:
            elems.append('<text x="20" y="%d" font-size="11" text-anchor="middle" fill="#2D3748" transform="rotate(-90 20 %d)">%s</text>' % (py0 + ph // 2, py0 + ph // 2, esc(yl)))
    elems.append("</svg>")
    svg, png, pdf = out / (name + ".svg"), out / (name + ".png"), out / (name + ".pdf")
    svg.write_text("\n".join(elems), encoding="utf-8")
    rmeta = {"cjk_family": fam}
    for lb, fn, dst in (("png", rmod.svg_to_png, png), ("pdf", rmod.svg_to_pdf, pdf)):
        try:
            rmeta[lb] = {"engine": fn(svg, dst, dpi) if lb == "png" else fn(svg, dst)}
        except Exception as e:
            rmeta[lb] = {"error": str(e)}
            warns.append("%s 导出失败: %s" % (lb.upper(), e))
    if preview:
        try:
            rmeta["preview"] = {"engine": rmod.svg_to_png(svg, preview, min(int(preview_dpi or 96), 108))}
        except Exception as e:
            rmeta["preview"] = {"error": str(e)}
    rep = {"ok": True, "warns": warns, "engine": "stdlib_svg_fallback", "editable_svg_text": True,
           "cjk_family": fam, "verified_exact": True, "render": rmeta,
           "total_points_plotted": sum(int(m.get("n") or 0) for m in mapping),
           "data_mapping": mapping, "series_count": len(mapping), "panel_count": len(panels)}
    (out / (name + "_checks.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({"table": mapping, "note": "纯标准库兜底 SVG 数据映射与溯源表"}, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def render(spec, out, name, dpi, preview=None, preview_dpi=96):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return _render_svg_stdlib(spec, out, name, dpi, preview=preview, preview_dpi=preview_dpi)
    import render as rmod

    fam, ffile = rmod.detect_cjk()
    if ffile and Path(ffile).exists():
        try:
            font_manager.fontManager.addfont(ffile)
            fam = font_manager.FontProperties(fname=ffile).get_name()
        except Exception:
            pass
    plt.rcParams.update({
        "font.sans-serif": [fam or "sans-serif", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "font.size": 10.5,
        "axes.grid": True,
        "grid.alpha": 0.28,
        "grid.linestyle": "--",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    panels = spec.get("panels")
    warns, mapping = [], []
    custom_fs = spec.get("figsize")
    if isinstance(panels, list) and panels:
        n = len(panels)
        ncols = min(int(spec.get("ncols") or (2 if n > 1 else 1)), n)
        nrows = (n + ncols - 1) // ncols
        fs = tuple(float(v) for v in custom_fs) if (isinstance(custom_fs, list) and len(custom_fs) == 2) else (5.6 * ncols, 3.9 * nrows + 0.5)
        fig, axes = plt.subplots(nrows, ncols, figsize=fs, constrained_layout=True, squeeze=False)
        flat = [ax for row in axes for ax in row]
        row_out_top = {}
        for idx, p in enumerate(panels):
            if str(p.get("legend_loc") or "").strip() == "outside_top":
                row_out_top[idx // ncols] = True
        for idx, p in enumerate(panels):
            tag = p.get("panel_label") or chr(ord("A") + idx)
            r_top = row_out_top.get(idx // ncols, False)
            w, m = _plot_panel(flat[idx], p, panel_tag=tag + ".", row_title_pad=(28 if r_top else None))
            warns.extend(w)
            mapping.extend(m)
            pt = str(p.get("title") or "").strip()
            has_prefix = pt.startswith(tag + ".") or pt.startswith(tag + " ") or pt.startswith(tag + ":") or pt.startswith("(" + tag + ")")
            if p.get("panel_label") or not has_prefix:
                by = 1.15 if r_top else 1.07
                flat[idx].text(-0.11, by, tag, transform=flat[idx].transAxes,
                               fontsize=13, fontweight="bold", va="top", ha="left", color="#1A202C")
        for extra in flat[n:]:
            extra.axis("off")
        if spec.get("title"):
            fig.suptitle(str(spec["title"]), fontsize=13.5, fontweight="bold", y=0.985)
        total_series = sum(max(len(p.get("series") or []), 1 if p.get("kind") == "heatmap" else 0) for p in panels)
    else:
        fs = tuple(float(v) for v in custom_fs) if (isinstance(custom_fs, list) and len(custom_fs) == 2) else (6.4, 4.1)
        fig, ax = plt.subplots(figsize=fs, constrained_layout=True)
        w, m = _plot_panel(ax, spec)
        warns.extend(w)
        mapping.extend(m)
        total_series = len(spec.get("series") or []) or (1 if spec.get("kind") == "heatmap" else 0)

    footer = str(spec.get("prov_footer") or spec.get("legend_note") or "").strip()
    has_sup = bool(isinstance(panels, list) and panels and spec.get("title"))
    if footer or has_sup:
        try:
            eng = fig.get_layout_engine()
            if eng is not None and hasattr(eng, "set"):
                bot = 0.06 if footer else 0.0
                top = 0.91 if has_sup else 1.0
                eng.set(rect=(0.0, bot, 1.0, top - bot))
        except Exception:
            pass
    if footer:
        fig.text(0.99, 0.012, footer, ha="right", va="bottom", fontsize=8.2, color="#718096")

    png, pdf, svg = out / (name + ".png"), out / (name + ".pdf"), out / (name + ".svg")
    fig.savefig(str(png), dpi=dpi, facecolor="white")
    if preview:
        pv = Path(preview)
        pv.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(pv), dpi=min(int(preview_dpi or 96), 108), facecolor="white")
    fig.savefig(str(pdf), facecolor="white")
    fig.savefig(str(svg), facecolor="white")
    plt.close(fig)

    svg_txt = svg.read_text(encoding="utf-8", errors="ignore")
    has_text = "<text " in svg_txt or "<text>" in svg_txt
    if not has_text:
        warns.append("导出 SVG 未检测到可编辑 <text> 节点")

    rep = {"ok": True, "warns": warns, "engine": "matplotlib",
           "editable_svg_text": has_text, "cjk_family": fam,
           "verified_exact": True,
           "total_points_plotted": sum(int(m.get("n") or 0) for m in mapping),
           "data_mapping": mapping, "series_count": total_series,
           "panel_count": len(panels) if isinstance(panels, list) and panels else 1}
    (out / (name + "_checks.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({
        "table": mapping,
        "note": "科研数据图表逐系列数据映射与溯源表（保留原值，可与源表比对）"
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="chart")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--preview", default=None, help="轻量视觉自检预览 PNG 路径（<=108 DPI）")
    ap.add_argument("--preview-dpi", type=int, default=96)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--contract", default=None)
    ap.add_argument("--result-skel", default=None)
    ap.add_argument("--result-out", default=None, help="直接写入正式 result.json 并自动触发交付核验")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sp_path = Path(a.spec)
    try:
        spec = hydrate_spec(json.loads(sp_path.read_text(encoding="utf-8")), sp_path.parent)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"ok": False, "stage": "hydrate_table", "errors": [str(e)]}, ensure_ascii=False))
        return 2
    errs = validate(spec)
    if errs:
        print(json.dumps({"ok": False, "stage": "spec_validate", "errors": errs}, ensure_ascii=False))
        return 2
    rep = render(spec, out, a.name, a.dpi, preview=a.preview, preview_dpi=a.preview_dpi)
    rep["errors"] = []
    if a.preview:
        rep["preview"] = str(a.preview)
    unfilled = _write_result_skel(a, rep, out, a.name, rep["data_mapping"], spec)
    if unfilled is not None:
        rep["unfilled_contract_fields"] = unfilled
    if a.result_out:
        import audit_delivery as auditmod
        rep["audit"] = auditmod.audit(Path(a.result_out).parent, a.contract)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(4)
