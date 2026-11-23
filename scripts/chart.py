"""Publication-grade multi-type chart engine (bar, hbar, line, scatter/volcano/dot, heatmap).

All chart types emit the exact same layered primitive IR -> editable SVG + 300 DPI PNG/PDF + 100 DPI preview.
Zero dependencies beyond Python stdlib.
"""
from __future__ import annotations
import csv
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import PALETTES, ramp, contrast_text, text_w
from viz_geom import text_bbox, overlap

def _opt_float(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if math.isnan(float(v)) else float(v)
    s = str(v).strip()
    if not s or s.lower() in ("na", "nan", "none", "null", "-"):
        return None
    try:
        fv = float(s)
        return None if math.isnan(fv) else fv
    except Exception:
        return None

def _sfloat(v, default=0.0):
    fv = _opt_float(v)
    return default if fv is None else fv

def _nice_ticks(lo, hi, n_approx=5):
    span = (hi - lo) or 1.0
    raw = span / max(2.0, float(n_approx))
    k = 10 ** math.floor(math.log10(abs(raw))) if raw > 0 else 1.0
    step = 10 * k
    for mm in (1, 2, 2.5, 5, 10):
        if raw <= mm * k:
            step = mm * k
            break
    t0 = math.floor(lo / step) * step
    t1 = math.ceil(hi / step) * step
    ticks = []
    v = t0
    while v <= t1 + step * 1e-6 and len(ticks) < 25:
        ticks.append(round(v, 10))
        v += step
    return ticks, t0, t1

def _fmt(v):
    if isinstance(v, int):
        return str(v)
    if abs(v) < 1e-10:
        return "0"
    s = f"{v:.4g}"
    if "." in s and "e" not in s and "E" not in s:
        s = s.rstrip("0").rstrip(".")
    return s

def _layout_legend_rows(items, W):
    """Wrap legend items cleanly into 1..N centered rows within canvas width W."""
    if not items:
        return []
    max_w = max(240.0, float(W) - 96.0)
    rows, cur, cur_w = [], [], 0.0
    for item in items:
        lbl = item[0]
        w = 24.0 + text_w(lbl, 12.0) + 18.0
        if cur and (cur_w + w - 18.0) > max_w:
            rows.append((cur, cur_w - 18.0))
            cur, cur_w = [(item, w)], w
        else:
            cur.append((item, w))
            cur_w += w
    if cur:
        rows.append((cur, cur_w - 18.0))
    return rows

def _top_legend(prims, items, W, y):
    """Draw a clean centered horizontal (auto-wrapping) legend above the plot area. Returns n_rows."""
    rows = _layout_legend_rows(items, W)
    if not rows:
        return 0
    for ri, (ritems, row_w) in enumerate(rows):
        ry = y + ri * 22.0
        x = max(48.0, (W - row_w) / 2.0)
        for (lbl, col, mk), w in ritems:
            if mk == "line":
                prims.append({"op": "polyline", "pts": [[x, ry], [x + 18, ry]], "stroke": col,
                              "stroke_w": 2.4, "role": "legend", "layer": "layer-legend"})
                prims.append({"op": "circle", "cx": x + 9, "cy": ry, "r": 3.5, "fill": col,
                              "stroke": "#ffffff", "stroke_w": 0.8, "role": "legend", "layer": "layer-legend"})
            elif mk == "dot":
                prims.append({"op": "circle", "cx": x + 8, "cy": ry, "r": 5.5, "fill": col,
                              "stroke": "#ffffff", "stroke_w": 0.8, "role": "legend", "layer": "layer-legend"})
            else:
                prims.append({"op": "rect", "x": x, "y": ry - 6.5, "w": 14, "h": 13, "rx": 2.5,
                              "fill": col, "stroke": "none", "stroke_w": 0,
                              "role": "legend", "layer": "layer-legend"})
            prims.append({"op": "text", "x": x + 21, "y": ry, "s": str(lbl), "size": 12.0,
                          "anchor": "start", "fill": "#334155", "role": "legend", "layer": "layer-legend"})
            x += w
    return len(rows)

def _marker(prims, x, y, col, idx, r=4.8, role="data_point"):
    kind = idx % 4
    if kind == 0:
        prims.append({"op": "circle", "cx": x, "cy": y, "r": r, "fill": col,
                      "stroke": "#ffffff", "stroke_w": 1.1, "role": role, "layer": "layer-nodes"})
    elif kind == 1:
        prims.append({"op": "rect", "x": x - r, "y": y - r, "w": r * 2, "h": r * 2, "rx": 1,
                      "fill": col, "stroke": "#ffffff", "stroke_w": 1.1, "role": role, "layer": "layer-nodes"})
    elif kind == 2:
        pts = [[x, y - r * 1.2], [x + r * 1.1, y + r], [x - r * 1.1, y + r]]
        prims.append({"op": "poly", "pts": pts, "fill": col, "stroke": "#ffffff",
                      "stroke_w": 1.1, "role": role, "layer": "layer-nodes"})
    else:
        pts = [[x, y - r * 1.2], [x + r * 1.2, y], [x, y + r * 1.2], [x - r * 1.2, y]]
        prims.append({"op": "poly", "pts": pts, "fill": col, "stroke": "#ffffff",
                      "stroke_w": 1.1, "role": role, "layer": "layer-nodes"})

def _wrap_chart(s, maxpx, size):
    words, lines, cur = str(s).split(" "), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(t, size) <= maxpx or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines

def _draw_chrome(prims, spec, ch, W, H, m):
    if spec.get("title"):
        tsize = 18.5
        tstr = str(spec["title"])
        while tsize > 13.0 and text_w(tstr, tsize) > W - 84:
            tsize -= 0.5
        prims.append({"op": "text", "x": W / 2.0, "y": 28, "s": tstr, "size": tsize,
                      "anchor": "middle", "fill": "#0f172a", "weight": "bold",
                      "role": "text", "layer": "layer-chrome"})
    if ch.get("x_label"):
        prims.append({"op": "text", "x": m["l"] + (W - m["l"] - m["r"]) / 2.0, "y": H - 36,
                      "s": ch["x_label"], "size": 13.5, "anchor": "middle", "fill": "#334155",
                      "weight": "bold", "role": "text", "layer": "layer-chrome"})
    if ch.get("y_label"):
        prims.append({"op": "text", "x": 24, "y": m["t"] + (H - m["t"] - m["b"]) / 2.0,
                      "s": ch["y_label"], "size": 13.5, "anchor": "middle", "fill": "#334155",
                      "weight": "bold", "rotate": -90, "role": "text", "layer": "layer-chrome"})
    note = ch.get("y_note") or spec.get("caption")
    if note:
        nsize = 11.0
        nstr = str(note)
        while nsize > 8.5 and text_w(nstr, nsize) > W - m["l"] - 20:
            nsize -= 0.5
        prims.append({"op": "text", "x": m["l"], "y": H - 12, "s": nstr, "size": nsize,
                      "anchor": "start", "fill": "#64748b", "italic": True,
                      "role": "text", "layer": "layer-chrome"})

def _read_table_rows(p: Path, sheet=None, max_rows: int = 50000):
    """Read CSV/TSV/XLSX into list[dict] with UTF-8-BOM support, row cap, and stdlib XLSX fallback."""
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xls"):
        rows_2d = None
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            ws = wb[sheet] if (sheet and sheet in wb.sheetnames) else wb[wb.sheetnames[0]]
            rows_2d = []
            for ri, r in enumerate(ws.iter_rows(values_only=True)):
                if ri > max_rows:
                    break
                rows_2d.append([("" if v is None else v) for v in r])
            wb.close()
        except Exception:
            pass
        if rows_2d is None:
            try:
                from inspect_inputs import _read_xlsx_stdlib
                sh_map = _read_xlsx_stdlib(p)
                if sh_map:
                    rows_2d = sh_map.get(sheet) if (sheet and sheet in sh_map) else next(iter(sh_map.values()))
            except Exception:
                return []
        if not rows_2d:
            return []
        hdr = [str(c).lstrip("\ufeff").strip() for c in rows_2d[0]]
        out = []
        for r in rows_2d[1:max_rows + 1]:
            if not any(str(v) != "" for v in r):
                continue
            out.append({hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))})
        return out
    delim = "\t" if suf == ".tsv" else ","
    try:
        with p.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            rdr = csv.DictReader(fh, delimiter=delim)
            out = []
            for ri, row in enumerate(rdr):
                if ri >= max_rows:
                    break
                out.append(row)
            return out
    except Exception:
        return []

def _resolve_table_path(raw_path: str) -> Path | None:
    p = Path(str(raw_path))
    if p.exists():
        return p
    # Auto-locate relative filenames inside /input or current directory
    for base in (Path("/input"), Path(".")):
        if base.exists():
            cand = base / p.name
            if cand.exists():
                return cand
            hits = list(base.rglob(p.name))
            if hits:
                return hits[0]
    return None

def _agg_replicates(vals, mode="mean_sd"):
    """Summarize replicate list into (center, err). Single value returns (val, 0.0)."""
    if len(vals) == 1:
        return vals[0], 0.0
    m = str(mode or "mean_sd").lower()
    if m == "median":
        sv = sorted(vals)
        mid = len(sv) // 2
        med = sv[mid] if len(sv) % 2 else 0.5 * (sv[mid - 1] + sv[mid])
        q1 = sv[len(sv) // 4]
        q3 = sv[(3 * len(sv)) // 4]
        return med, 0.5 * (q3 - q1)
    mu = sum(vals) / len(vals)
    var = sum((x - mu) ** 2 for x in vals) / max(1, len(vals) - 1)
    sd = math.sqrt(max(0.0, var))
    if m in ("mean_sem", "sem"):
        return mu, sd / math.sqrt(len(vals))
    return mu, sd

def _apply_num_transform(val, tf):
    if not tf:
        return val
    t = str(tf).strip().lower()
    if t in ("neg_log10", "-log10", "neglog10"):
        return -math.log10(max(float(val), 1e-300))
    if t == "log10":
        return math.log10(max(float(val), 1e-300))
    if t == "log2":
        return math.log2(max(float(val), 1e-300))
    return val

def _load_from_table(ch):
    """Bind chart directly to a CSV/TSV/XLSX source file with alias tolerance & clear diagnostics."""
    ft = ch.get("from_table")
    if not isinstance(ft, dict):
        return ch
    raw_file = ft.get("file") or ft.get("path") or ft.get("csv") or ft.get("xlsx")
    if not raw_file:
        ch["_table_error"] = "missing 'file' key in from_table"
        return ch
    p = _resolve_table_path(str(raw_file))
    if p is None:
        ch["_table_error"] = f"table file not found: {raw_file}"
        return ch
    # Normalize common LLM shorthand keys (x -> x_col, label -> label_col, etc.)
    ft = dict(ft)
    for short, canon in (
        ("label", "label_col"), ("value", "value_col"), ("x", "x_col"), ("y", "y_col"),
        ("err", "err_col"), ("sd", "err_col"), ("sem", "err_col"),
        ("group", "group_col"), ("hue", "group_col"),
        ("category", "category_col"), ("cat_col", "category_col"),
        ("series", "series_cols"), ("values", "value_cols"),
        ("size", "size_col"), ("color", "color_col"), ("row", "row_col"),
    ):
        if short in ft and canon not in ft:
            ft[canon] = ft[short]
    rows = _read_table_rows(p, sheet=ft.get("sheet"))
    if not rows:
        ch["_table_error"] = f"table {p.name} has 0 readable data rows"
        return ch
    avail_cols = list(rows[0].keys())
    # Verify any explicitly named column exists (case-insensitive fallback match)
    col_map = {str(c).strip().lower(): c for c in avail_cols}
    for ck in ("label_col", "value_col", "x_col", "y_col", "p_col", "err_col", "group_col", "category_col", "size_col", "color_col", "row_col"):
        if ft.get(ck) and ft[ck] not in avail_cols:
            low = str(ft[ck]).strip().lower()
            if low in col_map:
                ft[ck] = col_map[low]
            else:
                ch["_table_error"] = f"{p.name}: column {ft[ck]!r} not found; available={avail_cols[:12]}"
                return ch
    for cks in ("series_cols", "value_cols"):
        if isinstance(ft.get(cks), list):
            fixed = []
            for cn in ft[cks]:
                if cn in avail_cols:
                    fixed.append(cn)
                elif str(cn).strip().lower() in col_map:
                    fixed.append(col_map[str(cn).strip().lower()])
                else:
                    ch["_table_error"] = f"{p.name}: column {cn!r} not found; available={avail_cols[:12]}"
                    return ch
            ft[cks] = fixed
    flt = ft.get("filter")
    if isinstance(flt, dict) and flt.get("col"):
        fcol = str(flt["col"])
        if fcol not in avail_cols and fcol.lower() in col_map:
            fcol = col_map[fcol.lower()]
        if "eq" in flt:
            rows = [r for r in rows if str(r.get(fcol, "")).strip() == str(flt["eq"]).strip()]
        elif "in" in flt and isinstance(flt["in"], list):
            allowed = {str(v).strip() for v in flt["in"]}
            rows = [r for r in rows if str(r.get(fcol, "")).strip() in allowed]
    if not rows:
        ch["_table_error"] = f"{p.name}: 0 rows after filter"
        return ch
    if ft.get("sort_by"):
        scol = ft["sort_by"]
        def _skey(r):
            try:
                return float(r.get(scol, 0))
            except Exception:
                return 0.0
        rows.sort(key=_skey, reverse=bool(ft.get("descending", True)))
    if ft.get("top_n"):
        rows = rows[:int(ft["top_n"])]
    fname = p.name
    ch.setdefault("source", fname)
    ch.setdefault("y_note", f"Source: {fname}")
    kind = str(ch.get("kind") or "bar").strip().lower()
    if kind in ("dotplot", "enrichment_dot", "bubble_enrichment") or (ft.get("size_col") and ft.get("label_col")):
        ch["kind"] = "dotplot"
        ccol = ft.get("color_col")
        ctrans = str(ft.get("color_transform") or "").lower().strip()
        # Auto-detect raw padj/fdr/p_val column and convert via -log10(p) so high significance = hot color
        raw_cvals = []
        if ccol:
            for r in rows:
                v = _opt_float(r.get(ccol))
                if v is not None:
                    raw_cvals.append(v)
        auto_neglog = False
        if ccol and ctrans in ("-log10", "neglog10", "neg_log10"):
            auto_neglog = True
        elif ccol and not ctrans and raw_cvals:
            cl = str(ccol).lower()
            looks_p = any(k in cl for k in ("padj", "p_adj", "fdr", "qval", "q_val", "pval", "p_val", "pvalue"))
            if looks_p and all(0.0 <= v <= 1.0 for v in raw_cvals) and any(0.0 < v < 0.05 for v in raw_cvals):
                auto_neglog = True
                if not ch.get("color_caption"):
                    ch["color_caption"] = f"-log10({ccol})"
        items = []
        for idx, r in enumerate(rows, start=2):
            xv = _opt_float(r.get(ft.get("x_col") or ft.get("value_col")))
            if xv is None:
                continue
            it = {"label": str(r.get(ft["label_col"], f"Row {idx}")), "x": xv, "source": f"{fname} row {idx}"}
            if ft.get("size_col") and r.get(ft["size_col"]) not in (None, ""):
                sv = _opt_float(r.get(ft["size_col"]))
                if sv is not None:
                    it["size"] = sv
            if ccol and r.get(ccol) not in (None, ""):
                cv = _opt_float(r.get(ccol))
                if cv is not None:
                    if auto_neglog:
                        it["color"] = round(-math.log10(max(cv, 1e-300)), 5)
                    else:
                        it["color"] = cv
            items.append(it)
        ch["items"] = items
    elif kind in ("heatmap", "matrix") or (ft.get("row_col") and ft.get("value_cols")):
        rcol = ft.get("row_col") or ft.get("label_col") or (avail_cols[0] if avail_cols else "")
        vcols = list(ft.get("value_cols") or [])
        if not vcols and avail_cols:
            # Auto-detect all numeric columns other than row_col for wide matrix CSVs
            for h in avail_cols:
                if h == rcol:
                    continue
                if any(_opt_float(r.get(h)) is not None for r in rows[:20]):
                    vcols.append(h)
        rnames, mat = [], []
        for r in rows:
            vals = []
            has_num = False
            for c in vcols:
                raw = r.get(c, "")
                if str(raw).strip().lower() in ("", "na", "nan", "none", "null"):
                    vals.append(None)
                else:
                    try:
                        vals.append(float(raw)); has_num = True
                    except Exception:
                        vals.append(None)
            if has_num:
                rnames.append(str(r.get(rcol, "")))
                mat.append(vals)
        ch["rows"] = rnames; ch["cols"] = vcols; ch["values"] = mat
    elif kind in ("box", "boxplot", "box_plot", "strip") and ft.get("group_col") and ft.get("value_col"):
        gcol, vcol = ft["group_col"], ft["value_col"]
        g_order, g_vals = [], {}
        for r in rows:
            try:
                fv = float(r[vcol])
            except Exception:
                continue
            gn = str(r.get(gcol, "Group"))
            if gn not in g_vals:
                g_order.append(gn); g_vals[gn] = []
            g_vals[gn].append(fv)
        ch["groups"] = [{"label": gn, "values": g_vals[gn], "source": f"{fname} ({gcol}={gn})"} for gn in g_order]
    elif kind in ("grouped_bar", "stacked_bar", "stacked", "composition") and ft.get("category_col") and ft.get("group_col") and ft.get("value_col"):
        ccol, gcol, vcol, ecol = ft["category_col"], ft["group_col"], ft["value_col"], ft.get("err_col")
        agg_mode = ft.get("agg", "mean_sd")
        cats, grps = [], []
        vlist_map, emap = {}, {}
        for r in rows:
            cat = str(r.get(ccol, ""))
            grp = str(r.get(gcol, ""))
            fv = _opt_float(r.get(vcol))
            if fv is None:
                continue
            if cat not in cats:
                cats.append(cat)
            if grp not in grps:
                grps.append(grp)
            vlist_map.setdefault((grp, cat), []).append(fv)
            if ecol:
                ev = _opt_float(r.get(ecol))
                if ev is not None:
                    emap[(grp, cat)] = ev
        ch["categories"] = cats
        series = []
        has_any_err = bool(emap) or any(len(vs) >= 2 for vs in vlist_map.values())
        for g in grps:
            vals_g, errs_g = [], []
            for c in cats:
                vs = vlist_map.get((g, c), [])
                if not vs:
                    vals_g.append(0.0); errs_g.append(0.0)
                else:
                    mu, sd = _agg_replicates(vs, agg_mode)
                    vals_g.append(round(mu, 6))
                    errs_g.append(emap[(g, c)] if (g, c) in emap else round(sd, 6))
            s_obj = {"name": g, "values": vals_g, "source": f"{fname} ({gcol}={g})"}
            if has_any_err and kind == "grouped_bar":
                s_obj["errs"] = errs_g
            series.append(s_obj)
        ch["series"] = series
    elif kind in ("line", "line_chart", "timecourse", "time_course") and ft.get("x_col") and ft.get("group_col") and (ft.get("y_col") or ft.get("value_col")):
        xcol, gcol, ycol, ecol = ft["x_col"], ft["group_col"], (ft.get("y_col") or ft.get("value_col")), ft.get("err_col")
        agg_mode = ft.get("agg", "mean_sd")
        grps, g_xorder, g_vals, g_errs = [], {}, {}, {}
        for r in rows:
            yv = _opt_float(r.get(ycol))
            if yv is None:
                continue
            gn = str(r.get(gcol, "Series"))
            xv = r.get(xcol, len(g_xorder.get(gn, [])))
            if gn not in g_xorder:
                grps.append(gn); g_xorder[gn] = []
            if xv not in g_xorder[gn]:
                g_xorder[gn].append(xv)
            g_vals.setdefault((gn, xv), []).append(yv)
            if ecol:
                ev = _opt_float(r.get(ecol))
                if ev is not None:
                    g_errs[(gn, xv)] = ev
        series = []
        for gn in grps:
            xs_g, ys_g, es_g = [], [], []
            for xv in g_xorder[gn]:
                vs = g_vals[(gn, xv)]
                mu, sd = _agg_replicates(vs, agg_mode)
                xs_g.append(xv)
                ys_g.append(round(mu, 6))
                es_g.append(g_errs[(gn, xv)] if (gn, xv) in g_errs else round(sd, 6))
            s_obj = {"name": gn, "x": xs_g, "y": ys_g, "source": f"{fname} ({gcol}={gn})"}
            if any(ev > 0 for ev in es_g):
                s_obj["err"] = es_g
            series.append(s_obj)
        ch["series"] = series
    elif kind in ("line", "line_chart", "timecourse", "time_course") or ft.get("series_cols"):
        xcol = ft.get("x_col") or ft.get("label_col")
        xs = [r.get(xcol, i) for i, r in enumerate(rows)]
        series = []
        for scol in (ft.get("series_cols") or []):
            ys = [_opt_float(r.get(scol)) for r in rows]
            series.append({"name": scol, "x": xs, "y": ys, "source": f"{fname} col {scol}"})
        ch["series"] = series
    elif kind in ("scatter", "volcano", "xy") and ft.get("x_col") and (ft.get("y_col") or ft.get("p_col")):
        ycol = ft.get("y_col") or ft.get("p_col")
        ytf = ft.get("y_transform")
        if not ytf and ft.get("p_col"):
            ytf = "neg_log10"
        if not ytf and kind == "volcano":
            yl_low = str(ch.get("y_label") or "").lower()
            yc_low = str(ycol).lower()
            if ("log10" in yl_low or "padj" in yc_low or "fdr" in yc_low or "pval" in yc_low or "p_val" in yc_low or "qval" in yc_low) and "log" not in yc_low:
                raw_ys = [fv for r in rows if (fv := _opt_float(r.get(ycol))) is not None]
                if raw_ys and all(0.0 <= fv <= 1.0 for fv in raw_ys):
                    ytf = "neg_log10"
        pts = []
        for idx, r in enumerate(rows, start=2):
            xv = _opt_float(r.get(ft["x_col"]))
            yv = _opt_float(r.get(ycol))
            if xv is None or yv is None:
                continue
            yv = _apply_num_transform(yv, ytf)
            pt = {"x": xv, "y": round(yv, 6), "source": f"{fname} row {idx}"}
            if ft.get("label_col") and r.get(ft["label_col"]):
                pt["label"] = str(r[ft["label_col"]])
            if ft.get("group_col") and r.get(ft["group_col"]):
                pt["group"] = str(r[ft["group_col"]])
            pts.append(pt)
        ch["points"] = pts
    elif ft.get("label_col") and ft.get("value_col"):
        lcol, vcol, ecol, gcol = ft["label_col"], ft["value_col"], ft.get("err_col"), ft.get("group_col")
        agg_mode = ft.get("agg", "mean_sd")
        lbl_order, lbl_vals, lbl_meta = [], {}, {}
        for idx, r in enumerate(rows, start=2):
            fv = _opt_float(r.get(vcol))
            if fv is None:
                continue
            lb = str(r.get(lcol, f"Row {idx}"))
            if lb not in lbl_vals:
                lbl_order.append(lb)
                lbl_vals[lb] = []
                lbl_meta[lb] = {"source": f"{fname} row {idx}"}
                if gcol and r.get(gcol):
                    lbl_meta[lb]["group"] = str(r[gcol])
                if ecol:
                    ev = _opt_float(r.get(ecol))
                    if ev is not None:
                        lbl_meta[lb]["err"] = ev
            lbl_vals[lb].append(fv)
        bars = []
        for lb in lbl_order:
            vs = lbl_vals[lb]
            mu, sd = _agg_replicates(vs, agg_mode)
            b = {"label": lb, "value": round(mu, 6), **lbl_meta[lb]}
            if len(vs) >= 2:
                b.setdefault("err", round(sd, 6))
                b["points"] = vs
                b["source"] = f"{fname} ({lcol}={lb}, n={len(vs)})"
            bars.append(b)
        ch["bars"] = bars
    return ch

def _normalize_chart_spec(ch):
    """Normalize common LLM shorthand chart structures into canonical fields without losing data."""
    ch = _load_from_table(dict(ch or {}))
    # 1. Parallel labels + values shorthand for bar/hbar
    if not ch.get("bars") and ch.get("labels") and ch.get("values") and not ch.get("rows"):
        lbls = ch["labels"]
        vals = ch["values"]
        errs = ch.get("errs") or ch.get("errors") or []
        grps = ch.get("groups") or []
        src = ch.get("source") or ch.get("y_note") or ""
        bars = []
        for i, (lb, vl) in enumerate(zip(lbls, vals)):
            b = {"label": str(lb), "value": vl}
            if i < len(errs) and errs[i] is not None:
                b["err"] = errs[i]
            if i < len(grps) and grps[i]:
                b["group"] = grps[i]
            if src:
                b["source"] = src
            bars.append(b)
        ch["bars"] = bars
    # 2. Shared top-level x array for line series
    if ch.get("series") and ch.get("x") and not ch.get("categories"):
        new_series = []
        for s in ch["series"]:
            s2 = dict(s)
            if "x" not in s2:
                s2["x"] = ch["x"]
            if "y" not in s2 and "values" in s2:
                s2["y"] = s2["values"]
            new_series.append(s2)
        ch["series"] = new_series
    # 3. Parallel x + y arrays shorthand for scatter/volcano
    if not ch.get("points") and isinstance(ch.get("x"), list) and isinstance(ch.get("y"), list) and not ch.get("series"):
        xs, ys = ch["x"], ch["y"]
        lbls = ch.get("labels") or []
        grps = ch.get("groups") or []
        src = ch.get("source") or ch.get("y_note") or ""
        pts = []
        for i, (xv, yv) in enumerate(zip(xs, ys)):
            pt = {"x": xv, "y": yv}
            if i < len(lbls) and lbls[i]:
                pt["label"] = lbls[i]
            if i < len(grps) and grps[i]:
                pt["group"] = grps[i]
            if src:
                pt["source"] = src
            pts.append(pt)
        ch["points"] = pts
    return ch

def build_chart(spec, scale_name="regular"):
    ch = _normalize_chart_spec(spec.get("chart") or {})
    kind = str(ch.get("kind") or ("box" if ch.get("groups") and isinstance(ch["groups"][0], dict) and ch["groups"][0].get("values")
                                  else "dotplot" if ch.get("items")
                                  else "heatmap" if ch.get("values") and ch.get("rows")
                                  else "grouped_bar" if ch.get("categories") and ch.get("series")
                                  else "line" if ch.get("series")
                                  else "scatter" if ch.get("points")
                                  else "bar")).strip().lower()
    if kind in ("box", "boxplot", "box_plot", "strip", "violin"):
        return _build_box(spec, ch)
    if kind in ("stacked_bar", "stacked", "composition", "proportion_bar"):
        return _build_stacked_bar(spec, ch)
    if kind in ("dotplot", "enrichment_dot", "bubble_enrichment") or ch.get("items"):
        return _build_dotplot(spec, ch)
    if kind in ("heatmap", "matrix", "expression_heatmap", "heatmap_chart"):
        return _build_heatmap(spec, ch)
    if (kind in ("grouped_bar", "grouped", "multibar", "multi_bar", "clustered_bar")
            or (kind in ("bar", "bar_chart", "column") and ch.get("categories") and ch.get("series"))):
        return _build_grouped_bar(spec, ch)
    if kind in ("line", "line_chart", "curve", "timecourse", "time_course", "dose_response"):
        return _build_line(spec, ch)
    if kind in ("scatter", "volcano", "dot", "dotplot", "bubble", "xy"):
        return _build_scatter(spec, ch)
    if ch.get("horizontal") or kind in ("hbar", "horizontal_bar", "barh", "enrichment"):
        return _build_hbar(spec, ch)
    return _build_bar(spec, ch)

def _fit_xlabel(lbl, max_w, base_size=12.5):
    """Wrap into 2 lines if needed and shrink gently so long biological labels never collide."""
    s = str(lbl)
    if text_w(s, base_size) <= max_w:
        return s, base_size
    if " " in s and "\n" not in s:
        words = s.split(" ")
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            w = max(text_w(a, base_size), text_w(b, base_size))
            if best is None or w < best[0]:
                best = (w, a + "\n" + b)
        if best:
            s = best[1]
    sz = base_size
    while sz > 8.5 and text_w(s, sz) > max_w:
        sz -= 0.5
    return s, sz

def _build_grouped_bar(spec, ch):
    cats = list(ch.get("categories") or [])
    series = list(ch.get("series") or [])
    q = PALETTES["qual"]
    n_c = max(1, len(cats))
    n_s = max(1, len(series))
    W = int(ch.get("width") or max(860, 180 + n_c * max(115, n_s * 42 + 40)))
    leg_items = [(str(s.get("name", f"S{i+1}")), s.get("color") or q[i % len(q)], "box")
                 for i, s in enumerate(series)]
    n_leg_rows = max(1, len(_layout_legend_rows(leg_items, W)))
    brks = list(ch.get("sig_brackets") or [])
    H = int(ch.get("height") or (540 + max(0, n_leg_rows - 1) * 22 + (22 if brks else 0)))
    m = {"l": 88, "r": 36, "t": 64 + n_leg_rows * 22 + (22 if brks else 0), "b": 98}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    _top_legend(prims, leg_items, W, 56)

    all_hi = [0.0]; all_lo = [0.0]
    for s in series:
        vs = [float(v) for v in (s.get("values") or [])]
        es = [abs(float(e or 0)) for e in (s.get("errs") or [0] * len(vs))]
        for v, e in zip(vs, es):
            all_hi.append(v + e); all_lo.append(v - e)
        for pts_i in (s.get("points") or []):
            if isinstance(pts_i, (list, tuple)):
                all_hi.extend(float(p) for p in pts_i)
                all_lo.extend(float(p) for p in pts_i)
    hi_pad = max(all_hi) * 1.18 if max(all_hi) > 0 else 1.0
    lo_pad = min(all_lo) * 1.12 if min(all_lo) < 0 else 0.0
    ticks, bot, top = _nice_ticks(lo_pad, hi_pad, 5)
    if min(all_lo) >= 0:
        bot = 0.0
        ticks = [t for t in ticks if t >= -1e-9]
    span = (top - bot) or 1.0
    y_px = lambda val: m["t"] + gh * (1.0 - (val - bot) / span)
    y0line = y_px(0.0)

    for yv in ticks:
        gy = y_px(yv)
        if gy < m["t"] - 2 or gy > m["t"] + gh + 2:
            continue
        prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                      "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "polyline", "pts": [[m["l"] - 5, gy], [m["l"], gy]],
                      "stroke": "#475569", "stroke_w": 1.3, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": _fmt(yv),
                      "size": 11.5, "anchor": "end", "fill": "#475569",
                      "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], y0line], [m["l"] + gw, y0line]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    slot = gw / n_c
    grp_w = slot * 0.74
    bw = min(grp_w / n_s - 4.0, 54.0)
    bw = max(14.0, bw)
    used_w = bw * n_s + 4.0 * max(0, n_s - 1)
    for ci, cat in enumerate(cats):
        g_left = m["l"] + slot * (ci + 0.5) - used_w / 2.0
        for si, s in enumerate(series):
            vs = s.get("values") or []
            if ci >= len(vs):
                continue
            val = float(vs[ci])
            es = s.get("errs") or []
            err = abs(float(es[ci])) if ci < len(es) and es[ci] is not None else 0.0
            col = s.get("color") or q[si % len(q)]
            bx = g_left + si * (bw + 4.0)
            cx = bx + bw / 2.0
            yv = y_px(val)
            by = min(yv, y0line)
            bh = max(1.0, abs(y0line - yv))
            prims.append({"op": "rect", "x": bx, "y": by, "w": bw, "h": bh, "rx": 3,
                          "fill": col, "stroke": "#ffffff", "stroke_w": 0.6,
                          "role": "node", "layer": "layer-nodes", "_id": f"gbar-{ci}-{si}"})
            if err > 0:
                ey0, ey1 = y_px(val + err), y_px(val - err)
                prims.append({"op": "polyline", "pts": [[cx, ey0], [cx, ey1]], "stroke": "#1e293b",
                              "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
                for yy in (ey0, ey1):
                    prims.append({"op": "polyline", "pts": [[cx - 4.5, yy], [cx + 4.5, yy]],
                                  "stroke": "#1e293b", "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
            pts_list = s.get("points") or []
            if ci < len(pts_list) and isinstance(pts_list[ci], (list, tuple)):
                rpts = pts_list[ci]
                for pi, pv in enumerate(rpts):
                    px = cx + (pi - (len(rpts) - 1) / 2.0) * min(7.0, bw * 0.45 / max(1, len(rpts)))
                    prims.append({"op": "circle", "cx": px, "cy": y_px(float(pv)), "r": 3.0,
                                  "fill": "#1e293b", "stroke": "#ffffff", "stroke_w": 0.8,
                                  "role": "data_point", "layer": "layer-nodes"})
        lbl_txt, lbl_sz = _fit_xlabel(cat, slot - 8, 12.5)
        prims.append({"op": "text", "x": m["l"] + slot * (ci + 0.5),
                      "y": m["t"] + gh + (25 if "\n" in lbl_txt else 20),
                      "s": lbl_txt, "size": lbl_sz, "anchor": "middle", "fill": "#1e293b",
                      "weight": "bold", "italic": bool(ch.get("italic_x")),
                      "role": "text", "layer": "layer-chrome", "_id": f"label-cat-{ci}"})
    for bi, br in enumerate(brks):
        ci = int(br.get("cat", 0))
        sa, sb = int(br.get("a", 0)), int(br.get("b", min(1, n_s - 1)))
        if 0 <= ci < n_c and 0 <= sa < n_s and 0 <= sb < n_s:
            g_left = m["l"] + slot * (ci + 0.5) - used_w / 2.0
            xa = g_left + sa * (bw + 4.0) + bw / 2.0
            xb = g_left + sb * (bw + 4.0) + bw / 2.0
            va = float((series[sa].get("values") or [0])[ci]) + abs(float((series[sa].get("errs") or [0] * n_c)[ci] or 0))
            vb = float((series[sb].get("values") or [0])[ci]) + abs(float((series[sb].get("errs") or [0] * n_c)[ci] or 0))
            by = max(m["t"] + 12.0, y_px(max(va, vb)) - 16.0 - bi * 18.0)
            prims.append({"op": "polyline", "pts": [[xa, by + 5], [xa, by], [xb, by], [xb, by + 5]],
                          "stroke": "#1e293b", "stroke_w": 1.3, "role": "bracket", "layer": "layer-edges"})
            if br.get("label"):
                prims.append({"op": "text", "x": (xa + xb) / 2.0, "y": by - 8.5, "s": str(br["label"]),
                              "size": 11.0, "anchor": "middle", "fill": "#0f172a", "weight": "bold",
                              "role": "text", "layer": "layer-annotations"})
    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_bar(spec, ch):
    bars = ch.get("bars") or []
    stars = ch.get("stars") or []
    q = PALETTES["qual"]
    groups = []
    for b in bars:
        if b.get("group") and b["group"] not in groups:
            groups.append(b["group"])
    has_leg = len(groups) >= 1
    # Allocate non-overlapping tiers for significance brackets
    star_tiers = []
    placed_spans = []  # list of (tier, min_i, max_i)
    for st in stars:
        pair = st.get("pair") or [0, 1]
        a, b = min(int(pair[0]), int(pair[1])), max(int(pair[0]), int(pair[1]))
        tier = 0
        while any(t == tier and not (b < pa or a > pb) for t, pa, pb in placed_spans):
            tier += 1
        placed_spans.append((tier, a, b))
        star_tiers.append((tier, a, b, str(st.get("text", "ns"))))
    n_tiers = (max((t for t, _, _, _ in star_tiers), default=-1) + 1) if star_tiers else 0

    W = int(ch.get("width") or max(860, 180 + len(bars) * 115))
    top_m = 56 + (26 if has_leg else 0) + n_tiers * 28
    H = int(ch.get("height") or (540 + n_tiers * 24))
    m = {"l": 88, "r": 36, "t": top_m, "b": 98}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]

    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    if has_leg:
        _top_legend(prims, [(g, q[i % len(q)], "box") for i, g in enumerate(groups)], W, 56)

    vals = [_sfloat(b.get("value"), 0.0) for b in bars]
    errs = [abs(_sfloat(b.get("err"), 0.0)) for b in bars]
    has_sig = any(str(b.get("sig") or b.get("star") or "").strip() for b in bars)
    pts_all = [fv for b in bars for pv in (b.get("points") or []) if (fv := _opt_float(pv)) is not None]
    lo_raw = min([0.0] + [v - e for v, e in zip(vals, errs)] + pts_all)
    hi_raw = max([0.0] + [v + e for v, e in zip(vals, errs)] + pts_all)
    hi_pad = hi_raw * (1.28 if has_sig else 1.18) if hi_raw > 0 else 1.0
    lo_pad = (lo_raw * 1.12) if lo_raw < 0 else 0.0
    ticks, bot, top = _nice_ticks(lo_pad, hi_pad, 5)
    if lo_raw >= 0:
        bot = 0.0
        ticks = [t for t in ticks if t >= -1e-9]
    span = (top - bot) or 1.0

    def y_px(val):
        return m["t"] + gh * (1.0 - (val - bot) / span)

    y0line = y_px(0.0)
    # Gridlines & Y ticks
    for yv in ticks:
        gy = y_px(yv)
        if gy < m["t"] - 2 or gy > m["t"] + gh + 2:
            continue
        prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                      "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "polyline", "pts": [[m["l"] - 5, gy], [m["l"], gy]],
                      "stroke": "#475569", "stroke_w": 1.3, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": _fmt(yv),
                      "size": 11.5, "anchor": "end", "fill": "#475569",
                      "role": "deco", "layer": "layer-compartments"})
    # Clean L-shaped axis spines
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], y0line], [m["l"] + gw, y0line]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    n = max(1, len(bars))
    slot = gw / n
    bw = min(slot * 0.62, 92.0)
    bar_top_y = []  # top-most pixel (bar + err + value label) for each bar

    for i, b in enumerate(bars):
        val = _sfloat(b.get("value"), 0.0)
        err = abs(_sfloat(b.get("err"), 0.0))
        cx = m["l"] + slot * (i + 0.5)
        bx = cx - bw / 2.0
        yv = y_px(val)
        by = min(yv, y0line)
        bh = max(1.0, abs(y0line - yv))
        col = b.get("fill") or (q[groups.index(b["group"]) % len(q)] if b.get("group") in groups else q[0])
        prims.append({"op": "rect", "x": bx, "y": by, "w": bw, "h": bh, "rx": 3,
                      "fill": col, "stroke": "#ffffff", "stroke_w": 0.6,
                      "role": "node", "layer": "layer-nodes", "_id": f"bar-{i}"})
        top_pt = by
        if err > 0:
            ey0 = y_px(val + err)
            ey1 = y_px(val - err)
            top_pt = min(top_pt, ey0)
            prims.append({"op": "polyline", "pts": [[cx, ey0], [cx, ey1]], "stroke": "#1e293b",
                          "stroke_w": 1.6, "role": "error_bar", "layer": "layer-edges"})
            for yy in (ey0, ey1):
                prims.append({"op": "polyline", "pts": [[cx - 5.5, yy], [cx + 5.5, yy]],
                              "stroke": "#1e293b", "stroke_w": 1.6, "role": "error_bar", "layer": "layer-edges"})
        # Optional individual replicate points
        rpts = b.get("points") or []
        if rpts:
            k_p = len(rpts)
            for pi, pv in enumerate(rpts):
                px = cx + ((pi - (k_p - 1) / 2.0) * min(9.0, bw * 0.5 / max(1, k_p)))
                py = y_px(float(pv))
                top_pt = min(top_pt, py - 4)
                prims.append({"op": "circle", "cx": px, "cy": py, "r": 3.4, "fill": "#ffffff",
                              "stroke": "#1e293b", "stroke_w": 1.3, "role": "data_point", "layer": "layer-nodes"})
        vy = (top_pt - 12) if val >= 0 else (y_px(val - err) + 14)
        sig_txt = str(b.get("sig") or b.get("star") or "").strip()
        prims.append({"op": "text", "x": cx, "y": vy, "s": _fmt(val), "size": 12.0,
                      "anchor": "middle", "fill": "#0f172a", "weight": "bold",
                      "role": "text", "layer": "layer-annotations", "_id": f"val-{i}"})
        if sig_txt:
            sy = (vy - 16) if val >= 0 else (vy + 16)
            bar_top_y.append(min(top_pt - 36, sy - 10) if val >= 0 else m["t"] + 12)
            prims.append({"op": "text", "x": cx, "y": sy, "s": sig_txt, "size": 13.0,
                          "anchor": "middle", "fill": "#b91c1c" if "*" in sig_txt else "#475569",
                          "weight": "bold", "role": "text", "layer": "layer-annotations", "_id": f"sig-{i}"})
        else:
            bar_top_y.append(min(top_pt - 22, vy - 10) if val >= 0 else m["t"] + 12)
        lbl, size = _fit_xlabel(b.get("label", f"#{i+1}"), slot - 8, 12.5)
        prims.append({"op": "text", "x": cx, "y": m["t"] + gh + (25 if "\n" in lbl else 20),
                      "s": lbl, "size": size,
                      "anchor": "middle", "fill": "#1e293b", "weight": "bold" if b.get("bold") else "normal",
                      "italic": bool(b.get("italic")), "role": "text", "layer": "layer-chrome",
                      "_id": f"xlabel-{i}"})

    # Proper inverted-U significance brackets, stacked cleanly on tiers ABOVE bars
    if star_tiers:
        # Base bracket rail starts above the tallest bar/label in the chart
        base_rail = min(min(bar_top_y) - 6, m["t"] - 4)
        # Ensure base_rail never goes below title/legend; anchor from m["t"] upward cleanly
        for tier, i, j, txt in star_tiers:
            if i < len(bars) and j < len(bars):
                x0 = m["l"] + slot * (i + 0.5)
                x1 = m["l"] + slot * (j + 0.5)
                ybar = m["t"] - 10 - tier * 26
                prims.append({"op": "polyline",
                              "pts": [[x0, ybar + 7], [x0, ybar], [x1, ybar], [x1, ybar + 7]],
                              "stroke": "#334155", "stroke_w": 1.3, "role": "bracket", "layer": "layer-edges"})
                prims.append({"op": "text", "x": (x0 + x1) / 2.0, "y": ybar - 8, "s": txt,
                              "size": 13.0, "anchor": "middle", "fill": "#0f172a", "weight": "bold",
                              "role": "text", "layer": "layer-annotations"})

    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_hbar(spec, ch):
    bars = ch.get("bars") or []
    q = PALETTES["qual"]
    groups = []
    for b in bars:
        if b.get("group") and b["group"] not in groups:
            groups.append(b["group"])
    has_leg = len(groups) >= 1
    max_lbl_w = max((text_w(str(b.get("label", "")), 12.0) for b in bars), default=120)
    left_m = int(min(440, max(120, max_lbl_w + 28)))
    W = int(ch.get("width") or max(900, left_m + 560))
    H = int(ch.get("height") or max(440, 150 + len(bars) * 48))
    max_val_w = max((text_w(_fmt(float(b.get("value", 0))), 11.5) for b in bars), default=36)
    m = {"l": left_m, "r": int(max(68, max_val_w + 26)),
         "t": 62 + (24 if has_leg else 0), "b": 78}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    if has_leg:
        _top_legend(prims, [(g, q[i % len(q)], "box") for i, g in enumerate(groups)], W, 56)

    vals = [float(b.get("value", 0)) for b in bars]
    errs = [abs(float(b.get("err") or 0)) for b in bars]
    has_neg = any(v - e < 0 for v, e in zip(vals, errs))
    hi_raw = max([0.0] + [v + e for v, e in zip(vals, errs)])
    lo_raw = min([0.0] + [v - e for v, e in zip(vals, errs)]) if has_neg else 0.0
    ticks, left, right = _nice_ticks(
        lo_raw * 1.28 if lo_raw < 0 else 0.0,
        hi_raw * 1.18 if hi_raw > 0 else (0.0 if lo_raw < 0 else 1.0),
        5
    )
    if not has_neg:
        left = 0.0
    span = (right - left) or 1.0

    def x_px(val):
        return m["l"] + gw * ((val - left) / span)

    x0line = x_px(0.0)
    for xv in ticks:
        if not has_neg and xv < -1e-9:
            continue
        gx = x_px(xv)
        if gx < m["l"] - 2 or gx > m["l"] + gw + 2:
            continue
        prims.append({"op": "polyline", "pts": [[gx, m["t"]], [gx, m["t"] + gh]],
                      "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "text", "x": gx, "y": m["t"] + gh + 16, "s": _fmt(xv),
                      "size": 11.5, "anchor": "middle", "fill": "#475569",
                      "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"] + gh], [m["l"] + gw, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[x0line, m["t"]], [x0line, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.6, "role": "deco", "layer": "layer-compartments"})

    n = max(1, len(bars))
    slot = gh / n
    bh = min(slot * 0.64, 34.0)
    for i, b in enumerate(bars):
        val = _sfloat(b.get("value"), 0.0)
        err = abs(_sfloat(b.get("err"), 0.0))
        cy = m["t"] + slot * (i + 0.5)
        xv = x_px(val)
        bx0 = min(x0line, xv)
        bw = max(1.0, abs(xv - x0line))
        if b.get("fill"):
            col = b["fill"]
        elif b.get("group") in groups:
            col = q[groups.index(b["group"]) % len(q)]
        elif has_neg:
            col = "#dc2626" if val >= 0 else "#2563eb"
        else:
            col = q[0]
        prims.append({"op": "rect", "x": bx0, "y": cy - bh / 2.0, "w": bw, "h": bh, "rx": 3,
                      "fill": col, "stroke": "#ffffff", "stroke_w": 0.5,
                      "role": "node", "layer": "layer-nodes", "_id": f"hbar-{i}"})
        if err > 0:
            ex0 = x_px(val - err if has_neg else max(0.0, val - err))
            ex1 = x_px(val + err)
            prims.append({"op": "polyline", "pts": [[ex0, cy], [ex1, cy]], "stroke": "#1e293b",
                          "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
        if val >= 0:
            tx, tanc = x_px(val + err) + 8, "start"
        else:
            tx, tanc = x_px(val - err) - 8, "end"
        prims.append({"op": "text", "x": tx, "y": cy, "s": _fmt(val), "size": 11.5,
                      "anchor": tanc, "fill": "#0f172a", "weight": "bold",
                      "role": "text", "layer": "layer-annotations", "_id": f"hval-{i}"})
        hlbl, hsz = _fit_xlabel(b.get("label", f"#{i+1}"), m["l"] - 18, 12.0)
        prims.append({"op": "text", "x": m["l"] - 10, "y": cy, "s": hlbl,
                      "size": hsz, "anchor": "end", "fill": "#1e293b",
                      "role": "text", "layer": "layer-chrome", "_id": f"ylabel-{i}"})
    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_line(spec, ch):
    series = ch.get("series") or []
    q = PALETTES["qual"]
    W = int(ch.get("width") or 920)
    has_leg = len(series) >= 1
    leg_items = [(s.get("name", f"S{i+1}"), s.get("color") or q[i % len(q)], "line")
                 for i, s in enumerate(series)]
    n_leg_rows = len(_layout_legend_rows(leg_items, W)) if has_leg else 0
    H = int(ch.get("height") or (560 + max(0, n_leg_rows - 1) * 22))
    m = {"l": 88, "r": 36, "t": 62 + (4 + 22 * n_leg_rows if has_leg else 0), "b": 90}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    if has_leg:
        _top_legend(prims, leg_items, W, 56)

    # Detect numeric vs categorical/string X coordinates (e.g. ["0h", "6h", "12h", "24h"])
    raw_xs = [v for s in series for v in (s.get("x") or [])]
    cat_labels = []
    is_cat_x = False
    for v in raw_xs:
        try:
            float(v)
        except Exception:
            is_cat_x = True
            break
    if is_cat_x:
        for s in series:
            for v in (s.get("x") or []):
                sv = str(v)
                if sv not in cat_labels:
                    cat_labels.append(sv)
    cat_idx = {lbl: float(i) for i, lbl in enumerate(cat_labels)}

    xs_all, ys_lo, ys_hi = [], [], []
    parsed_series = []
    for s in series:
        raw_ys = list(s.get("y") or s.get("values") or [])
        raw_xlist = list(s.get("x") or range(len(raw_ys)))
        raw_es = list(s.get("err") or s.get("errs") or [0.0] * len(raw_ys))
        xs, ys, es = [], [], []
        for idx_p, ry in enumerate(raw_ys):
            yv = _opt_float(ry)
            if yv is None:
                continue
            rx = raw_xlist[idx_p] if idx_p < len(raw_xlist) else idx_p
            xv = cat_idx.get(str(rx), float(idx_p)) if is_cat_x else _opt_float(rx)
            if xv is None:
                continue
            ev = abs(_sfloat(raw_es[idx_p] if idx_p < len(raw_es) else 0.0, 0.0))
            xs.append(xv); ys.append(yv); es.append(ev)
        if not xs:
            continue
        parsed_series.append((s, xs, ys, es))
        xs_all.extend(xs)
        ys_lo.extend(y - e for y, e in zip(ys, es))
        ys_hi.extend(y + e for y, e in zip(ys, es))
    if is_cat_x:
        x0, x1 = -0.35, max(0.35, len(cat_labels) - 1 + 0.35)
        xticks = list(range(len(cat_labels)))
    else:
        xticks, x0, x1 = _nice_ticks(min(xs_all or [0]), max(xs_all or [1]), 6)
    yticks, y0, y1 = _nice_ticks(min(0.0, min(ys_lo or [0])), max(ys_hi or [1]) * 1.12, 5)
    if min(ys_lo or [0]) >= 0:
        y0 = 0.0
        yticks = [t for t in yticks if t >= -1e-9]
    xspan = (x1 - x0) or 1.0
    yspan = (y1 - y0) or 1.0

    def x_px(v): return m["l"] + gw * ((v - x0) / xspan)
    def y_px(v): return m["t"] + gh * (1.0 - (v - y0) / yspan)

    for yv in yticks:
        gy = y_px(yv)
        if m["t"] - 2 <= gy <= m["t"] + gh + 2:
            prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                          "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": _fmt(yv), "size": 11.5,
                          "anchor": "end", "fill": "#475569", "role": "deco", "layer": "layer-compartments"})
    for ti, xv in enumerate(xticks):
        gx = x_px(xv)
        if m["l"] - 2 <= gx <= m["l"] + gw + 2:
            prims.append({"op": "polyline", "pts": [[gx, m["t"] + gh], [gx, m["t"] + gh + 5]],
                          "stroke": "#475569", "stroke_w": 1.3, "role": "deco", "layer": "layer-compartments"})
            xlbl = cat_labels[ti] if (is_cat_x and ti < len(cat_labels)) else _fmt(xv)
            prims.append({"op": "text", "x": gx, "y": m["t"] + gh + 18, "s": xlbl, "size": 11.5,
                          "anchor": "middle", "fill": "#475569", "role": "deco", "layer": "layer-compartments",
                          "_id": f"xtick-{ti}"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh], [m["l"] + gw, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    for hl in ch.get("hlines") or []:
        gy = y_px(float(hl["y"]))
        prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]], "stroke": "#94a3b8",
                      "stroke_w": 1.3, "dashed": True, "role": "deco", "layer": "layer-compartments"})
        if hl.get("label"):
            prims.append({"op": "text", "x": m["l"] + gw - 4, "y": gy - 10, "s": str(hl["label"]),
                          "size": 10.5, "anchor": "end", "fill": "#64748b", "italic": True,
                          "role": "text", "layer": "layer-annotations"})
    for vl in ch.get("vlines") or []:
        vx_raw = vl["x"] if isinstance(vl, dict) else vl
        vx_num = cat_idx.get(str(vx_raw)) if is_cat_x else None
        if vx_num is None:
            try:
                vx_num = float(vx_raw)
            except Exception:
                continue
        gx = x_px(vx_num)
        if m["l"] - 2 <= gx <= m["l"] + gw + 2:
            prims.append({"op": "polyline", "pts": [[gx, m["t"]], [gx, m["t"] + gh]], "stroke": "#dc2626",
                          "stroke_w": 1.3, "dashed": True, "role": "deco", "layer": "layer-compartments"})
            if isinstance(vl, dict) and vl.get("label"):
                vl_txt = str(vl["label"])
                flip_l = (gx + 5 + text_w(vl_txt, 10.5)) > (m["l"] + gw - 2)
                prims.append({"op": "text", "x": (gx - 5 if flip_l else gx + 5), "y": m["t"] + 12,
                              "s": vl_txt, "size": 10.5, "anchor": ("end" if flip_l else "start"),
                              "fill": "#b91c1c", "italic": True,
                              "role": "text", "layer": "layer-annotations"})

    for si, (s, xs, ys, es) in enumerate(parsed_series):
        col = s.get("color") or q[si % len(q)]
        pts = [[x_px(xv), y_px(yv)] for xv, yv in zip(xs, ys)]
        if any(ev > 0 for ev in es) and len(xs) >= 2:
            upper = [[x_px(xv), y_px(yv + ev)] for xv, yv, ev in zip(xs, ys, es)]
            lower = [[x_px(xv), y_px(yv - ev)] for xv, yv, ev in reversed(list(zip(xs, ys, es)))]
            prims.append({"op": "poly", "pts": upper + lower, "fill": col, "stroke": "none",
                          "stroke_w": 0, "opacity": 0.14, "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "polyline", "pts": pts, "stroke": col, "stroke_w": 2.5,
                      "dashed": bool(s.get("dashed")), "role": "edge", "layer": "layer-edges",
                      "_id": f"series-{si}"})
        for xv, yv, ev in zip(xs, ys, es):
            px, py = x_px(xv), y_px(yv)
            if ev > 0:
                ey0, ey1 = y_px(yv + ev), y_px(yv - ev)
                prims.append({"op": "polyline", "pts": [[px, ey0], [px, ey1]], "stroke": col,
                              "stroke_w": 1.3, "role": "error_bar", "layer": "layer-edges"})
                for yy in (ey0, ey1):
                    prims.append({"op": "polyline", "pts": [[px - 4, yy], [px + 4, yy]], "stroke": col,
                                  "stroke_w": 1.3, "role": "error_bar", "layer": "layer-edges"})
            _marker(prims, px, py, col, si, r=5.0, role="node")

    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_scatter(spec, ch):
    raw_pts = ch.get("points") or []
    pts = []
    for pt in raw_pts:
        xv, yv = _opt_float(pt.get("x")), _opt_float(pt.get("y"))
        if xv is not None and yv is not None:
            pts.append({**pt, "x": xv, "y": yv})
    q = PALETTES["qual"]
    # Auto-classify volcano quadrants if x_thresh / y_thresh provided without explicit groups
    x_thr = ch.get("x_thresh")
    y_thr = ch.get("y_thresh")
    hlines = list(ch.get("hlines") or [])
    vlines = list(ch.get("vlines") or [])
    if (x_thr is not None or y_thr is not None) and pts:
        xt = abs(float(x_thr)) if x_thr is not None else 0.0
        yt = float(y_thr) if y_thr is not None else 0.0
        if y_thr is not None and not hlines:
            hlines.append(yt)
        if x_thr is not None and not vlines:
            vlines.extend([-xt, xt])
        if not any(pt.get("group") for pt in pts):
            for pt in pts:
                xv, yv = float(pt["x"]), float(pt["y"])
                if yv >= yt and xv >= xt:
                    pt["group"] = "Up"
                elif yv >= yt and xv <= -xt:
                    pt["group"] = "Down"
                else:
                    pt["group"] = "NS"
    groups = []
    gcounts = {}
    for pt in pts:
        g = pt.get("group")
        if g:
            gcounts[g] = gcounts.get(g, 0) + 1
            if g not in groups:
                groups.append(g)
    gcolors = {"Up": "#dc2626", "Down": "#2563eb", "NS": "#94a3b8", "Significant": "#dc2626"}
    has_leg = len(groups) >= 1
    W = int(ch.get("width") or 900)
    H = int(ch.get("height") or 580)
    m = {"l": 88, "r": 42, "t": 62 + (26 if has_leg else 0), "b": 90}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    if has_leg:
        show_n = (str(ch.get("kind", "")).lower() == "volcano" or x_thr is not None or y_thr is not None)
        leg_items = [(f"{g} (n={gcounts[g]})" if show_n else g, gcolors.get(g, q[i % len(q)]), "dot")
                     for i, g in enumerate(groups)]
        _top_legend(prims, leg_items, W, 56)

    xs = [float(p["x"]) for p in pts] or [0.0, 1.0]
    ys = [float(p["y"]) for p in pts] or [0.0, 1.0]
    xpad = ((max(xs) - min(xs)) or 1.0) * 0.12
    ypad = ((max(ys) - min(ys)) or 1.0) * 0.14
    xticks, x0, x1 = _nice_ticks(min(xs) - xpad, max(xs) + xpad, 6)
    yticks, y0, y1 = _nice_ticks(max(0.0, min(ys) - ypad) if min(ys) >= 0 else min(ys) - ypad,
                                 max(ys) + ypad, 5)
    xspan, yspan = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    def x_px(v): return m["l"] + gw * ((v - x0) / xspan)
    def y_px(v): return m["t"] + gh * (1.0 - (v - y0) / yspan)

    for yv in yticks:
        gy = y_px(yv)
        if m["t"] - 2 <= gy <= m["t"] + gh + 2:
            prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                          "stroke": "#eef2f7", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": _fmt(yv), "size": 11.5,
                          "anchor": "end", "fill": "#475569", "role": "deco", "layer": "layer-compartments"})
    for xv in xticks:
        gx = x_px(xv)
        if m["l"] - 2 <= gx <= m["l"] + gw + 2:
            prims.append({"op": "polyline", "pts": [[gx, m["t"]], [gx, m["t"] + gh]],
                          "stroke": "#eef2f7", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            prims.append({"op": "text", "x": gx, "y": m["t"] + gh + 18, "s": _fmt(xv), "size": 11.5,
                          "anchor": "middle", "fill": "#475569", "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh], [m["l"] + gw, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    for hl in hlines:
        val = float(hl["y"] if isinstance(hl, dict) else hl)
        gy = y_px(val)
        prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]], "stroke": "#94a3b8",
                      "stroke_w": 1.2, "dashed": True, "role": "deco", "layer": "layer-compartments"})
    for vl in vlines:
        val = float(vl["x"] if isinstance(vl, dict) else vl)
        gx = x_px(val)
        prims.append({"op": "polyline", "pts": [[gx, m["t"]], [gx, m["t"] + gh]], "stroke": "#94a3b8",
                      "stroke_w": 1.2, "dashed": True, "role": "deco", "layer": "layer-compartments"})

    dot_boxes = []
    for pt in pts:
        px0, py0 = x_px(float(pt["x"])), y_px(float(pt["y"]))
        r0 = float(pt.get("size") or 5.2)
        dot_boxes.append([px0 - r0 - 2.0, py0 - r0 - 2.0, px0 + r0 + 2.0, py0 + r0 + 2.0])

    # Guard against label explosion on dense omics CSVs (e.g. 50-200 DEG volcano tables)
    lbl_indices = [i for i, pt in enumerate(pts) if pt.get("label")]
    explicit_genes = set(str(g) for g in (ch.get("label_genes") or []))
    hl_genes = set(str(g) for g in (ch.get("highlight_labels") or ch.get("highlight_genes") or []))
    if explicit_genes and not hl_genes:
        keep_lbl = {i for i in lbl_indices if str(pts[i].get("label")) in explicit_genes}
    else:
        # In volcano plots with thresholds, avoid cluttering with non-significant (NS) labels
        is_volc = str(ch.get("kind") or "").lower() == "volcano"
        sig_indices = [i for i in lbl_indices if pts[i].get("group") in ("Up", "Down", "Significant")]
        cand_indices = sig_indices if (is_volc and sig_indices and not ch.get("label_ns")) else lbl_indices
        if len(cand_indices) > int(ch.get("label_top_n") or 16):
            top_n = int(ch.get("label_top_n") or 12)
            scored_lbl = []
            for i in cand_indices:
                pt = pts[i]
                sig_bonus = 100.0 if pt.get("group") in ("Up", "Down", "Significant") else 0.0
                score = sig_bonus + abs(float(pt["x"])) * max(0.5, float(pt["y"])) + float(pt["y"])
                scored_lbl.append((score, i))
            scored_lbl.sort(reverse=True)
            keep_lbl = {i for _, i in scored_lbl[:top_n]}
        else:
            keep_lbl = set(cand_indices)
        must_hl = explicit_genes | hl_genes
        if must_hl:
            keep_lbl |= {i for i in lbl_indices if str(pts[i].get("label")) in must_hl}

    # Draw all point circles first, then place labels in priority order (highlight_labels FIRST!)
    for i, pt in enumerate(pts):
        px, py = x_px(float(pt["x"])), y_px(float(pt["y"]))
        g = pt.get("group")
        col = pt.get("color") or (gcolors.get(g, q[groups.index(g) % len(q)]) if g in groups else q[0])
        r = float(pt.get("size") or 5.2)
        is_hl = bool(pt.get("label") and str(pt.get("label")) in (explicit_genes | hl_genes))
        prims.append({"op": "circle", "cx": px, "cy": py, "r": (r + 1.2 if is_hl else r), "fill": col,
                      "opacity": 0.92 if is_hl else 0.85,
                      "stroke": ("#0f172a" if is_hl else "#ffffff"), "stroke_w": (1.4 if is_hl else 0.9),
                      "role": "node", "layer": "layer-nodes", "_id": f"pt-{i}"})

    placed_lbls = []
    must_set = explicit_genes | hl_genes
    lbl_order = sorted(
        [i for i in keep_lbl if pts[i].get("label")],
        key=lambda i: (
            1 if str(pts[i].get("label")) in must_set else 0,
            1 if pts[i].get("group") in ("Up", "Down", "Significant") else 0,
            abs(float(pts[i]["x"])) * max(0.5, float(pts[i]["y"])) + float(pts[i]["y"]),
        ),
        reverse=True,
    )
    for i in lbl_order:
        pt = pts[i]
        px, py = x_px(float(pt["x"])), y_px(float(pt["y"]))
        r = float(pt.get("size") or 5.2)
        lbl = str(pt["label"])
        is_hl = lbl in must_set
        chosen = None
        offsets = (
            (0, -r - 12), (r + 18, -10), (-r - 18, -10), (0, r + 13),
            (r + 22, 11), (-r - 22, 11), (0, -r - 26), (32, -20), (-32, -20),
            (32, 20), (-32, 20), (0, r + 27), (48, -12), (-48, -12),
            (48, 14), (-48, 14), (0, -r - 40), (46, -32), (-46, -32),
            (46, 32), (-46, 32), (66, -20), (-66, -20), (0, r + 42),
            (66, 22), (-66, 22), (0, -r - 56), (0, r + 56),
            (84, -26), (-84, -26), (84, 26), (-84, 26)
        )
        for dx, dy in offsets:
            tx, ty = px + dx, py + dy
            bb = text_bbox(tx, ty, lbl, 11.0, "middle")
            if bb[0] < m["l"] or bb[2] > m["l"] + gw or bb[1] < m["t"] or bb[3] > m["t"] + gh:
                continue
            if any(overlap(bb, ob, tol=4.0) for ob in placed_lbls):
                continue
            if any(overlap(bb, db, tol=2.0) for db in dot_boxes):
                continue
            chosen = (tx, ty, bb)
            break
        if chosen is None and (is_hl or len(keep_lbl) <= 10):
            # Guaranteed placement for highlighted genes: pick lowest-overlap in-bounds slot
            best_c = None
            for dx, dy in offsets:
                tx, ty = px + dx, py + dy
                bb = text_bbox(tx, ty, lbl, 11.0, "middle")
                if bb[0] < m["l"] or bb[2] > m["l"] + gw or bb[1] < m["t"] or bb[3] > m["t"] + gh:
                    continue
                if any(overlap(bb, ob, tol=1.0) for ob in placed_lbls):
                    continue
                hits = sum(1 for db in dot_boxes if overlap(bb, db, tol=1.0))
                if best_c is None or hits < best_c[0]:
                    best_c = (hits, tx, ty, bb)
            if best_c is not None:
                chosen = (best_c[1], best_c[2], best_c[3])
        if chosen is None:
            continue
        placed_lbls.append(chosen[2])
        if math.hypot(chosen[0] - px, chosen[1] - py) > r + 18.0:
            prims.append({"op": "polyline", "pts": [[px, py], [chosen[0], chosen[1]]],
                          "stroke": ("#475569" if is_hl else "#94a3b8"), "stroke_w": 0.9,
                          "role": "deco", "layer": "layer-edges"})
        prims.append({"op": "text", "x": chosen[0], "y": chosen[1], "s": lbl, "size": 11.0,
                      "anchor": "middle", "fill": "#0f172a", "weight": "bold",
                      "role": "text", "layer": "layer-annotations", "_id": f"ptlabel-{i}"})

    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_heatmap(spec, ch):
    rows = ch.get("rows") or []
    cols = ch.get("cols") or []
    vals = ch.get("values") or []
    pal = ch.get("palette", "fold")
    flat = []
    for row in vals:
        for v in row:
            if v is not None and str(v).strip().lower() not in ("", "na", "nan", "none"):
                try:
                    fv = float(v)
                    if not math.isnan(fv):
                        flat.append(fv)
                except Exception:
                    pass
    flat = flat or [0.0, 1.0]
    vmin = float(ch.get("vmin") if ch.get("vmin") is not None else min(flat))
    vmax = float(ch.get("vmax") if ch.get("vmax") is not None else max(flat))
    max_rw = max((text_w(str(r), 12.0) for r in rows), default=80)
    max_cw = max((text_w(str(c), 11.5) for c in cols), default=56)
    cell_w = max(62, min(116, max(int(560 / max(1, len(cols))), int(min(max_cw + 12, 116)))))
    cell_h = max(34, min(52, int(360 / max(1, len(rows)))))
    cbar_lbl_w = text_w(str(ch.get("cbar_label") or ""), 11.0)
    m = {"l": int(max(100, max_rw + 24)), "r": int(max(120, 48 + cbar_lbl_w / 2.0 + 18)), "t": 72, "b": 92}
    gw, gh = cell_w * max(1, len(cols)), cell_h * max(1, len(rows))
    W = int(ch.get("width") or (m["l"] + gw + m["r"]))
    H = int(ch.get("height") or (m["t"] + gh + m["b"]))
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]

    for ri, rlbl in enumerate(rows):
        cy = m["t"] + (ri + 0.5) * cell_h
        prims.append({"op": "text", "x": m["l"] - 10, "y": cy, "s": str(rlbl), "size": 12.0,
                      "anchor": "end", "fill": "#1e293b", "italic": bool(ch.get("italic_rows")),
                      "role": "text", "layer": "layer-chrome", "_id": f"rowlabel-{ri}"})
        for ci, clbl in enumerate(cols):
            raw_v = vals[ri][ci] if ci < len(vals[ri]) else None
            is_na = raw_v is None or str(raw_v).strip().lower() in ("", "na", "nan", "none")
            v = None
            if not is_na:
                try:
                    fv = float(raw_v)
                    if not math.isnan(fv):
                        v = fv
                except Exception:
                    v = None
            x0, y0 = m["l"] + ci * cell_w, m["t"] + ri * cell_h
            if v is None:
                prims.append({"op": "rect", "x": x0, "y": y0, "w": cell_w, "h": cell_h, "rx": 2,
                              "fill": "#f1f5f9", "stroke": "#ffffff", "stroke_w": 1.5,
                              "role": "node", "layer": "layer-nodes", "_id": f"cell-{ri}-{ci}"})
                if ch.get("annotate", True):
                    prims.append({"op": "text", "x": x0 + cell_w / 2.0, "y": y0 + cell_h / 2.0,
                                  "s": "NA", "size": 10.5, "anchor": "middle", "fill": "#64748b",
                                  "italic": True, "halo": False, "role": "node_label", "layer": "layer-nodes"})
            else:
                t = (v - vmin) / ((vmax - vmin) or 1.0)
                col = ramp(pal, t)
                prims.append({"op": "rect", "x": x0, "y": y0, "w": cell_w, "h": cell_h, "rx": 2,
                              "fill": col, "stroke": "#ffffff", "stroke_w": 1.5,
                              "role": "node", "layer": "layer-nodes", "_id": f"cell-{ri}-{ci}"})
                if ch.get("annotate", True):
                    ink = contrast_text(col)
                    prims.append({"op": "text", "x": x0 + cell_w / 2.0, "y": y0 + cell_h / 2.0,
                                  "s": _fmt(v), "size": 11.5, "anchor": "middle", "fill": ink,
                                  "weight": "bold", "halo": False, "role": "node_label", "layer": "layer-nodes"})
    for ci, clbl in enumerate(cols):
        cx = m["l"] + (ci + 0.5) * cell_w
        c_txt, c_sz = _fit_xlabel(clbl, cell_w - 6, 11.5)
        prims.append({"op": "text", "x": cx, "y": m["t"] + gh + (24 if "\n" in c_txt else 18),
                      "s": c_txt, "size": c_sz,
                      "anchor": "middle", "fill": "#1e293b", "weight": "bold",
                      "role": "text", "layer": "layer-chrome", "_id": f"collabel-{ci}"})
    # Colorbar legend on right
    cbx = m["l"] + gw + 28
    cbh = min(gh, 200)
    cby = m["t"] + (gh - cbh) / 2.0
    nsteps = 20
    sh = cbh / nsteps
    for i in range(nsteps):
        t = 1.0 - i / (nsteps - 1)
        prims.append({"op": "rect", "x": cbx, "y": cby + i * sh, "w": 18, "h": sh + 0.5,
                      "fill": ramp(pal, t), "stroke": "none", "stroke_w": 0,
                      "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "rect", "x": cbx, "y": cby, "w": 18, "h": cbh,
                  "fill": "none", "stroke": "#94a3b8", "stroke_w": 0.9,
                  "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "text", "x": cbx + 25, "y": cby + 4, "s": _fmt(vmax), "size": 11.0,
                  "anchor": "start", "fill": "#334155", "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "text", "x": cbx + 25, "y": cby + cbh - 4, "s": _fmt(vmin), "size": 11.0,
                  "anchor": "start", "fill": "#334155", "role": "legend", "layer": "layer-legend"})
    if ch.get("cbar_label"):
        prims.append({"op": "text", "x": cbx + 9, "y": cby - 14, "s": str(ch["cbar_label"]),
                      "size": 11.0, "anchor": "middle", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_dotplot(spec, ch):
    """Pathway enrichment bubble dot plot (Y=pathway, X=ratio/NES, size=count, color=-log10 padj)."""
    items = ch.get("items") or []
    pal = ch.get("palette", "reds")
    max_lbl_w = max((text_w(str(it.get("label", "")), 12.0) for it in items), default=140)
    left_m = int(min(430, max(130, max_lbl_w + 28)))
    right_m = 165
    W = int(ch.get("width") or max(960, left_m + 440 + right_m))
    H = int(ch.get("height") or max(460, 150 + len(items) * 44))
    m = {"l": left_m, "r": right_m, "t": 68, "b": 82}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    if not items:
        _draw_chrome(prims, spec, ch, W, H, m)
        return prims, W, H, [], []

    xs = [float(it.get("x", 0)) for it in items]
    szs = [float(it.get("size", 10)) for it in items]
    cols = [float(it.get("color", it.get("x", 1))) for it in items]
    x_lo, x_hi = min(xs), max(xs)
    x_pad = max(0.08 * (x_hi - x_lo), 0.15 * max(abs(x_hi), 1.0))
    xticks, left, right = _nice_ticks(x_lo - x_pad if x_lo < 0 else max(0.0, x_lo - x_pad), x_hi + x_pad, 5)
    xspan = (right - left) or 1.0
    def x_px(v): return m["l"] + gw * ((v - left) / xspan)

    smin, smax = min(szs), max(szs)
    cmin = float(ch.get("vmin")) if ch.get("vmin") is not None else min(cols)
    cmax = float(ch.get("vmax")) if ch.get("vmax") is not None else max(cols)

    # Vertical gridlines & axis frame
    for xv in xticks:
        gx = x_px(xv)
        if m["l"] - 2 <= gx <= m["l"] + gw + 2:
            prims.append({"op": "polyline", "pts": [[gx, m["t"]], [gx, m["t"] + gh]],
                          "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            prims.append({"op": "text", "x": gx, "y": m["t"] + gh + 16, "s": _fmt(xv),
                          "size": 11.5, "anchor": "middle", "fill": "#475569",
                          "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "rect", "x": m["l"], "y": m["t"], "w": gw, "h": gh,
                  "fill": "none", "stroke": "#334155", "stroke_w": 1.3,
                  "role": "deco", "layer": "layer-compartments"})

    n = max(1, len(items))
    slot = gh / n
    for i, it in enumerate(items):
        cy = m["t"] + slot * (i + 0.5)
        prims.append({"op": "polyline", "pts": [[m["l"], cy], [m["l"] + gw, cy]],
                      "stroke": "#f1f5f9", "stroke_w": 1.0, "dashed": True,
                      "role": "deco", "layer": "layer-compartments"})
        xv = float(it.get("x", 0))
        sv = float(it.get("size", 10))
        cv = float(it.get("color", xv))
        ts = (sv - smin) / ((smax - smin) or 1.0)
        tc = (cv - cmin) / ((cmax - cmin) or 1.0)
        r = 6.5 + 9.0 * min(1.0, max(0.0, ts))
        col = ramp(pal, tc)
        prims.append({"op": "circle", "cx": x_px(xv), "cy": cy, "r": r, "fill": col,
                      "stroke": "#334155", "stroke_w": 1.0, "opacity": 0.92,
                      "role": "node", "layer": "layer-nodes", "_id": f"dot-{i}"})
        hlbl, hsz = _fit_xlabel(it.get("label", f"#{i+1}"), m["l"] - 18, 12.0)
        prims.append({"op": "text", "x": m["l"] - 10, "y": cy, "s": hlbl,
                      "size": hsz, "anchor": "end", "fill": "#1e293b",
                      "role": "text", "layer": "layer-chrome", "_id": f"ylabel-{i}"})

    # Right-side dual legend: Colorbar (top) + Bubble size scale (bottom)
    lx = m["l"] + gw + 26
    cby = m["t"] + 16
    cbh = min(130.0, max(80.0, gh * 0.42))
    prims.append({"op": "text", "x": lx, "y": cby - 14,
                  "s": str(ch.get("color_label") or ch.get("cbar_label") or "-log10(padj)"),
                  "size": 11.0, "anchor": "start", "fill": "#334155", "weight": "bold",
                  "role": "legend", "layer": "layer-legend"})
    nsteps = 16
    sh = cbh / nsteps
    for i in range(nsteps):
        t = 1.0 - i / (nsteps - 1)
        prims.append({"op": "rect", "x": lx, "y": cby + i * sh, "w": 16, "h": sh + 0.5,
                      "fill": ramp(pal, t), "stroke": "none", "stroke_w": 0,
                      "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "rect", "x": lx, "y": cby, "w": 16, "h": cbh,
                  "fill": "none", "stroke": "#94a3b8", "stroke_w": 0.9,
                  "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "text", "x": lx + 22, "y": cby + 4, "s": _fmt(cmax), "size": 10.5,
                  "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
    prims.append({"op": "text", "x": lx + 22, "y": cby + cbh - 4, "s": _fmt(cmin), "size": 10.5,
                  "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})

    # Bubble size scale below colorbar
    sy = cby + cbh + 32
    prims.append({"op": "text", "x": lx, "y": sy, "s": str(ch.get("size_label") or "Gene count"),
                  "size": 11.0, "anchor": "start", "fill": "#334155", "weight": "bold",
                  "role": "legend", "layer": "layer-legend"})
    smid = 0.5 * (smin + smax)
    samples = [(smin, 6.5), (smid, 11.0), (smax, 15.5)] if smax > smin else [(smin, 10.0)]
    cur_y = sy + 20
    for sv, sr in samples:
        prims.append({"op": "circle", "cx": lx + 16, "cy": cur_y, "r": sr,
                      "fill": "#cbd5e1", "stroke": "#475569", "stroke_w": 1.0,
                      "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "text", "x": lx + 38, "y": cur_y, "s": _fmt(sv), "size": 10.5,
                      "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        cur_y += max(24.0, sr * 2.0 + 8.0)

    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _build_stacked_bar(spec, ch):
    """Stacked (or 100% normalized) composition bar chart for cell-type/pathway fractions."""
    cats = list(ch.get("categories") or [])
    series = list(ch.get("series") or [])
    norm = bool(ch.get("normalize"))
    q = PALETTES["qual"]
    n_c = max(1, len(cats))
    W = int(ch.get("width") or max(840, 200 + n_c * 118))
    leg_items = [(str(s.get("name", f"S{i+1}")), s.get("color") or q[i % len(q)], "box")
                 for i, s in enumerate(series)]
    n_leg_rows = max(1, len(_layout_legend_rows(leg_items, W)))
    H = int(ch.get("height") or (540 + max(0, n_leg_rows - 1) * 22))
    m = {"l": 88, "r": 36, "t": 64 + n_leg_rows * 22, "b": 98}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    _top_legend(prims, leg_items, W, 56)

    totals = []
    for ci in range(n_c):
        tot = sum(max(0.0, float((s.get("values") or [0])[ci])) if ci < len(s.get("values") or []) else 0.0 for s in series)
        totals.append(tot or 1.0)
    ymax = 100.0 if norm else max(totals or [1.0]) * 1.12
    ticks, bot, top = _nice_ticks(0.0, ymax, 5)
    bot = 0.0
    ticks = [t for t in ticks if t >= -1e-9]
    span = (top - bot) or 1.0
    def y_px(val): return m["t"] + gh * (1.0 - (val - bot) / span)

    for yv in ticks:
        gy = y_px(yv)
        if m["t"] - 2 <= gy <= m["t"] + gh + 2:
            prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                          "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            lbl_y = f"{_fmt(yv)}%" if norm else _fmt(yv)
            prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": lbl_y, "size": 11.5,
                          "anchor": "end", "fill": "#475569", "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh], [m["l"] + gw, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    slot = gw / n_c
    bw = min(slot * 0.56, 76.0)
    for ci, cat in enumerate(cats):
        cx = m["l"] + slot * (ci + 0.5)
        acc = 0.0
        for si, s in enumerate(series):
            vs = s.get("values") or []
            raw_v = max(0.0, float(vs[ci])) if ci < len(vs) else 0.0
            v = (100.0 * raw_v / totals[ci]) if norm else raw_v
            if v <= 0:
                continue
            col = s.get("color") or q[si % len(q)]
            y_hi = y_px(acc + v)
            y_lo = y_px(acc)
            bh = max(1.0, y_lo - y_hi)
            prims.append({"op": "rect", "x": cx - bw / 2.0, "y": y_hi, "w": bw, "h": bh, "rx": 1.5,
                          "fill": col, "stroke": "#ffffff", "stroke_w": 0.8,
                          "role": "node", "layer": "layer-nodes", "_id": f"sbar-{ci}-{si}"})
            if bh >= 22.0 and ch.get("show_segment_labels", True):
                s_lbl = f"{v:.0f}%" if norm else _fmt(v)
                prims.append({"op": "text", "x": cx, "y": (y_hi + y_lo) / 2.0, "s": s_lbl, "size": 10.0,
                              "anchor": "middle", "fill": contrast_text(col), "weight": "bold", "halo": False,
                              "role": "text", "layer": "layer-annotations"})
            acc += v
        xlbl, xsz = _fit_xlabel(cat, slot - 10.0, 12.0)
        prims.append({"op": "text", "x": cx, "y": m["t"] + gh + 24, "s": xlbl, "size": xsz,
                      "anchor": "middle", "fill": "#1e293b", "role": "text",
                      "layer": "layer-chrome", "_id": f"xlabel-{ci}"})
    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []

def _quantile(sorted_vals, q_prob):
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    pos = (n - 1) * q_prob
    lo = int(math.floor(pos))
    hi = min(n - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac

def _build_box(spec, ch):
    """Box-and-whisker + overlaid individual replicate points + significance brackets."""
    groups = list(ch.get("groups") or [])
    q = PALETTES["qual"]
    n_g = max(1, len(groups))
    W = int(ch.get("width") or max(840, 200 + n_g * 130))
    H = int(ch.get("height") or 540)
    brks = list(ch.get("sig_brackets") or [])
    m = {"l": 88, "r": 36, "t": 68 + (22 if brks else 0), "b": 98}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}]
    all_v = [float(v) for g in groups for v in (g.get("values") or [])] or [0.0, 1.0]
    lo_v, hi_v = min(all_v), max(all_v)
    pad = max((hi_v - lo_v) * 0.14, 0.5)
    y_max_need = hi_v + pad * (1.0 + 0.6 * len(brks))
    y_min_need = 0.0 if lo_v >= 0 and lo_v < hi_v * 0.25 else (lo_v - pad)
    ticks, bot, top = _nice_ticks(y_min_need, y_max_need, 5)
    span = (top - bot) or 1.0
    def y_px(val): return m["t"] + gh * (1.0 - (val - bot) / span)

    for yv in ticks:
        gy = y_px(yv)
        if m["t"] - 2 <= gy <= m["t"] + gh + 2:
            prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                          "stroke": "#e5e7eb", "stroke_w": 1.0, "role": "deco", "layer": "layer-compartments"})
            prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": _fmt(yv), "size": 11.5,
                          "anchor": "end", "fill": "#475569", "role": "deco", "layer": "layer-compartments"})
    prims.append({"op": "polyline", "pts": [[m["l"], m["t"]], [m["l"], m["t"] + gh], [m["l"] + gw, m["t"] + gh]],
                  "stroke": "#334155", "stroke_w": 1.5, "role": "deco", "layer": "layer-compartments"})

    slot = gw / n_g
    bw = min(slot * 0.44, 64.0)
    cxs, tops_y = [], []
    for i, g in enumerate(groups):
        vs = sorted(float(v) for v in (g.get("values") or []))
        cx = m["l"] + slot * (i + 0.5)
        cxs.append(cx)
        col = g.get("color") or q[i % len(q)]
        if vs:
            q1, med, q3 = _quantile(vs, 0.25), _quantile(vs, 0.50), _quantile(vs, 0.75)
            iqr = q3 - q1
            wlo = min(v for v in vs if v >= q1 - 1.5 * iqr)
            whi = max(v for v in vs if v <= q3 + 1.5 * iqr)
            y_q1, y_med, y_q3 = y_px(q1), y_px(med), y_px(q3)
            y_wlo, y_whi = y_px(wlo), y_px(whi)
            tops_y.append(y_px(max(vs)))
            # Whiskers
            prims.append({"op": "polyline", "pts": [[cx, y_q3], [cx, y_whi]], "stroke": "#334155",
                          "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
            prims.append({"op": "polyline", "pts": [[cx, y_q1], [cx, y_wlo]], "stroke": "#334155",
                          "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
            for wy in (y_whi, y_wlo):
                prims.append({"op": "polyline", "pts": [[cx - bw * 0.26, wy], [cx + bw * 0.26, wy]],
                              "stroke": "#334155", "stroke_w": 1.5, "role": "error_bar", "layer": "layer-edges"})
            # Box
            prims.append({"op": "rect", "x": cx - bw / 2.0, "y": y_q3, "w": bw, "h": max(2.0, y_q1 - y_q3),
                          "rx": 4, "fill": col, "stroke": "#1e293b", "stroke_w": 1.5, "opacity": 0.45,
                          "role": "node", "layer": "layer-nodes", "_id": f"box-{i}"})
            # Median line
            prims.append({"op": "polyline", "pts": [[cx - bw / 2.0, y_med], [cx + bw / 2.0, y_med]],
                          "stroke": "#0f172a", "stroke_w": 2.4, "role": "error_bar", "layer": "layer-nodes"})
            # Overlaid deterministic jitter points
            for pi, pv in enumerate(vs):
                jx = cx + (((pi % 5) - 2) * (bw * 0.12))
                prims.append({"op": "circle", "cx": jx, "cy": y_px(pv), "r": 3.4, "fill": col,
                              "stroke": "#1e293b", "stroke_w": 0.9, "role": "data_point", "layer": "layer-nodes"})
        else:
            tops_y.append(m["t"] + gh)
        xlbl, xsz = _fit_xlabel(g.get("label", f"G{i+1}"), slot - 10.0, 12.0)
        prims.append({"op": "text", "x": cx, "y": m["t"] + gh + 24, "s": xlbl, "size": xsz,
                      "anchor": "middle", "fill": "#1e293b", "role": "text",
                      "layer": "layer-chrome", "_id": f"xlabel-{i}"})

    lbl_to_idx = {str(g.get("label", "")).strip(): gi for gi, g in enumerate(groups)}
    def _resolve_gidx(val, default):
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            s = val.strip()
            if s.isdigit():
                return int(s)
            if s in lbl_to_idx:
                return lbl_to_idx[s]
        return default
    placed_spans = []
    for br in brks:
        if isinstance(br.get("pair"), (list, tuple)) and len(br["pair"]) >= 2:
            ia = _resolve_gidx(br["pair"][0], 0)
            ib = _resolve_gidx(br["pair"][1], min(1, n_g - 1))
        else:
            ia = _resolve_gidx(br.get("a"), 0)
            ib = _resolve_gidx(br.get("b"), min(1, n_g - 1))
        if ia > ib:
            ia, ib = ib, ia
        if 0 <= ia < len(cxs) and 0 <= ib < len(cxs) and ia != ib:
            tier = 0
            while any(t == tier and not (ib < pa or ia > pb) for t, pa, pb in placed_spans):
                tier += 1
            placed_spans.append((tier, ia, ib))
            span_top = min(tops_y[k] for k in range(ia, ib + 1))
            by = max(m["t"] + 16.0, span_top - 18.0 - tier * 24.0)
            prims.append({"op": "polyline",
                          "pts": [[cxs[ia], by + 6], [cxs[ia], by], [cxs[ib], by], [cxs[ib], by + 6]],
                          "stroke": "#1e293b", "stroke_w": 1.3, "role": "bracket", "layer": "layer-edges"})
            btxt = br.get("text") if br.get("text") is not None else br.get("label")
            if btxt:
                prims.append({"op": "text", "x": (cxs[ia] + cxs[ib]) / 2.0, "y": by - 9,
                              "s": str(btxt), "size": 11.5, "anchor": "middle",
                              "fill": "#0f172a", "weight": "bold", "role": "text", "layer": "layer-annotations"})
    _draw_chrome(prims, spec, ch, W, H, m)
    return prims, W, H, [], []
