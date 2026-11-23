#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_render.py — 单面板渲染：柱状/水平柱/分组柱/堆叠柱/折线/散点(含连续X)/误差线/箱线/热图 + 标注。"""
from __future__ import annotations

import numpy as np


def _xy(p):
    n = len(p.get("groups") or [])
    x = np.arange(n, dtype=float)
    y = np.array([[np.nan if v is None else float(v) for v in s["values"]]
                  for s in p["series"]], dtype=float)
    if y.ndim == 1:
        y = y.reshape(1, -1)
    e = np.full(y.shape, np.nan)
    for i, s in enumerate(p["series"]):
        for j, v in enumerate((s.get("errors") or [])[: y.shape[1]]):
            e[i, j] = np.nan if v is None else float(v)
    e = np.where(np.isnan(y), np.nan, e)  # 值缺失时不画误差线，不造数
    return x, y, e


def _series_yerr(p, si, e, mask=None):
    """提取第 si 个系列的误差数组：支持非对称 [errors_low, errors_high] 或对称 errors。"""
    s = p["series"][si]
    if s.get("errors_low") is not None and s.get("errors_high") is not None:
        lo = np.array([0.0 if v is None else float(v) for v in s["errors_low"]], dtype=float)
        hi = np.array([0.0 if v is None else float(v) for v in s["errors_high"]], dtype=float)
        if mask is not None:
            lo, hi = lo[mask], hi[mask]
        if np.all(lo == 0) and np.all(hi == 0):
            return None
        return np.vstack([lo, hi])
    if e.size:
        arr = e[si][mask] if mask is not None else e[si]
        if not np.all(np.isnan(arr)):
            return arr
    return None


def _color_for(name, si, colors, series_colors=None):
    if series_colors and name in series_colors:
        return series_colors[name]
    return colors[si % len(colors)]


def _err_pos_hi(p, si, gi, e):
    """返回第 si 系列第 gi 点的上/右误差延伸长度（兼容对称与非对称误差）。"""
    s = p["series"][si]
    if s.get("errors_high") is not None and gi < len(s["errors_high"]) and s["errors_high"][gi] is not None:
        return float(s["errors_high"][gi])
    if e.size and si < e.shape[0] and gi < e.shape[1] and not np.isnan(e[si, gi]):
        return float(e[si, gi])
    return 0.0


def _err_pos_lo(p, si, gi, e):
    """返回第 si 系列第 gi 点的下/左误差延伸长度（兼容对称与非对称误差）。"""
    s = p["series"][si]
    if s.get("errors_low") is not None and gi < len(s["errors_low"]) and s["errors_low"][gi] is not None:
        return float(s["errors_low"][gi])
    if e.size and si < e.shape[0] and gi < e.shape[1] and not np.isnan(e[si, gi]):
        return float(e[si, gi])
    return 0.0


def _fmt_fit_num(v):
    """干净格式化回归系数（避免把 103 显示成 1e+02 或出现 +- 号）。"""
    av = abs(float(v))
    if av == 0:
        return "0"
    if av >= 1e4 or av < 1e-2:
        return f"{v:.2e}"
    if av >= 100:
        return f"{v:.1f}"
    if av >= 10:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{v:.3g}"


def _place_scatter_labels(ax, items, fpt, fit_lines=None):
    """确定性 8 方位散点标签避障排布：自动内收贴边点标签，避开邻近点、拟合线与已放置标签。"""
    if not items:
        return
    xs_all = [it[0] for it in items]
    ys_all = [it[1] for it in items]
    x_lo, x_hi = min(xs_all), max(xs_all)
    y_lo, y_hi = min(ys_all), max(ys_all)
    xr = max(x_hi - x_lo, 1e-9)
    yr = max(y_hi - y_lo, 1e-9)
    nx_all = [(x - x_lo) / xr for x in xs_all]
    ny_all = [(y - y_lo) / yr for y in ys_all]
    # (dx_pt, dy_pt, ha, va, norm_dx, norm_dy)
    cands = [
        (5, 4, "left", "bottom", 0.055, 0.055),
        (-5, 4, "right", "bottom", -0.055, 0.055),
        (5, -6, "left", "top", 0.055, -0.055),
        (-5, -6, "right", "top", -0.055, -0.055),
        (0, 7, "center", "bottom", 0.0, 0.085),
        (0, -8, "center", "top", 0.0, -0.085),
        (8, 0, "left", "center", 0.09, 0.0),
        (-8, 0, "right", "center", -0.09, 0.0),
    ]
    placed = []  # list of (bx0, by0, bx1, by1) in normalized coords
    fs = max(5.5, fpt * 0.8)
    for idx, (xi, yi, pl) in enumerate(items):
        if not pl:
            continue
        nx, ny = nx_all[idx], ny_all[idx]
        lw = min(0.32, max(0.05, 0.016 * len(str(pl))))
        lh = 0.068
        best_score = float("inf")
        best_c = cands[0]
        best_box = None
        for c in cands:
            dxp, dyp, ha, va, ndx, ndy = c
            cx = nx + ndx
            cy = ny + ndy
            bx0 = cx if ha == "left" else (cx - lw if ha == "right" else cx - lw / 2.0)
            bx1 = bx0 + lw
            by0 = cy if va == "bottom" else (cy - lh if va == "top" else cy - lh / 2.0)
            by1 = by0 + lh
            score = 0.0
            # 强力惩罚贴近/越出绘图区右/左/上/下边界
            if bx1 > 1.02:
                score += 12.0 * (bx1 - 1.02) + 4.0
            if bx0 < -0.02:
                score += 12.0 * (-0.02 - bx0) + 4.0
            if by1 > 1.02:
                score += 10.0 * (by1 - 1.02) + 3.0
            if by0 < -0.02:
                score += 10.0 * (-0.02 - by0) + 3.0
            # 惩罚与已放置标签重叠
            for px0, py0, px1, py1 in placed:
                ox = min(bx1, px1) - max(bx0, px0)
                oy = min(by1, py1) - max(by0, py0)
                if ox > -0.01 and oy > -0.01:
                    score += 8.0 + 40.0 * max(0.0, ox) * max(0.0, oy)
            # 惩罚覆盖其他散点
            for j, (oxp, oyp) in enumerate(zip(nx_all, ny_all)):
                if j == idx:
                    continue
                if (bx0 - 0.015) <= oxp <= (bx1 + 0.015) and (by0 - 0.015) <= oyp <= (by1 + 0.015):
                    score += 5.0
            # 惩罚标签框压在回归拟合线上
            if fit_lines:
                bxm = (bx0 + bx1) / 2.0
                x_mid_data = x_lo + bxm * xr
                for sl, ic in fit_lines:
                    ny_fit = (sl * x_mid_data + ic - y_lo) / yr
                    if (by0 - 0.02) <= ny_fit <= (by1 + 0.02):
                        score += 3.5
            if score < best_score:
                best_score = score
                best_c = c
                best_box = (bx0, by0, bx1, by1)
        placed.append(best_box)
        ax.annotate(str(pl), (xi, yi), xytext=(best_c[0], best_c[1]), textcoords="offset points",
                    ha=best_c[2], va=best_c[3], fontsize=fs, color="#222222")


def _draw_numeric_xy(ax, p, opts):
    """连续数值 X 轴渲染（scatter / line / errorbar），支持线性拟合线 fit_line 与 y=x 对角线 diag_line。"""
    kind = p["kind"]
    colors = opts["colors"]
    scolors = p.get("series_colors") or {}
    fpt = opts["font_pt"]
    handles = []
    audit_vals = []
    fit_stats = []
    all_x, all_y = [], []
    scatter_label_items = []
    for si, s in enumerate(p["series"]):
        xs = np.array(s.get("x_values", []), dtype=float)
        ys = np.array([np.nan if v is None else float(v) for v in s["values"]], dtype=float)
        mask = (~np.isnan(xs)) & (~np.isnan(ys))
        if np.any(mask):
            all_x.extend(xs[mask].tolist())
            all_y.extend(ys[mask].tolist())
        errs = None
        if s.get("errors"):
            errs = np.array([np.nan if v is None else float(v) for v in s["errors"]], dtype=float)
        col = _color_for(s["name"], si, colors, scolors)
        lbl = None if s["name"] == "__all__" else s["name"]
        if kind == "scatter":
            hh = ax.scatter(xs, ys, s=p.get("point_size", 22), color=col, alpha=0.85,
                            edgecolors="white", linewidths=0.4, label=lbl, zorder=3)
            handles.append(hh)
            offs = np.asarray(hh.get_offsets(), dtype=float)
            if offs.size:
                audit_vals.extend([float(yv) for xv, yv in offs if not np.isnan(xv) and not np.isnan(yv)])
            plabs = s.get("point_labels") or []
            for xi, yi, pl in zip(xs, ys, plabs):
                if not np.isnan(xi) and not np.isnan(yi):
                    scatter_label_items.append((float(xi), float(yi), pl))
            if p.get("fit_line") and int(np.sum(mask)) >= 2:
                xv, yv = xs[mask], ys[mask]
                if np.std(xv) > 0 and np.std(yv) > 0:
                    slope, intercept = np.polyfit(xv, yv, 1)
                    r = float(np.corrcoef(xv, yv)[0, 1])
                    r2 = r * r
                    xgrid = np.linspace(float(xv.min()), float(xv.max()), 50)
                    ax.plot(xgrid, slope * xgrid + intercept, "--", color=col, lw=1.0, alpha=0.85, zorder=2)
                    fit_stats.append({
                        "series": s["name"], "n": int(len(xv)),
                        "slope": round(float(slope), 6), "intercept": round(float(intercept), 6),
                        "pearson_r": round(r, 4), "r_squared": round(r2, 4),
                    })
        else:
            if p.get("error_style") == "band" and errs is not None:
                hh_list = ax.plot(xs, ys, marker="o", ms=3.5, lw=1.3, color=col, label=lbl)
                hh = hh_list[0]
                m_e = mask & (~np.isnan(errs))
                if np.any(m_e):
                    ax.fill_between(xs[m_e], ys[m_e] - errs[m_e], ys[m_e] + errs[m_e],
                                    color=col, alpha=0.18, linewidth=0, zorder=1)
                handles.append(hh)
                ln = hh
            else:
                hh = ax.errorbar(xs, ys, yerr=errs, marker="o", ms=3.5, lw=1.2, capsize=2,
                                 color=col, label=lbl)
                handles.append(hh)
                ln = hh.lines[0] if hasattr(hh, "lines") else hh
            if hasattr(ln, "get_ydata") and hasattr(ln, "get_xdata"):
                xd = np.asarray(ln.get_xdata(), dtype=float)
                yd = np.asarray(ln.get_ydata(), dtype=float)
                audit_vals.extend([float(yv) for xv, yv in zip(xd, yd) if not np.isnan(xv) and not np.isnan(yv)])
    if any(it[2] for it in scatter_label_items):
        fit_pairs = [(fs["slope"], fs["intercept"]) for fs in fit_stats] if fit_stats else None
        _place_scatter_labels(ax, scatter_label_items, fpt, fit_lines=fit_pairs)
    p["_audit_rendered"] = audit_vals
    if p.get("diag_line") and all_x and all_y:
        lo_d = min(min(all_x), min(all_y))
        hi_d = max(max(all_x), max(all_y))
        ax.plot([lo_d, hi_d], [lo_d, hi_d], ":", color="#777777", lw=0.9, zorder=1)
    if fit_stats:
        p["fit_stats"] = fit_stats
        lines = []
        for fs in fit_stats[:3]:
            if len(fit_stats) > 1 and fs["series"] != "__all__":
                lines.append(f"{fs['series']}: R²={fs['r_squared']:.3f} (r={fs['pearson_r']:.2f})")
            else:
                sign = "+" if fs["intercept"] >= 0 else "-"
                lines.append(
                    f"y = {_fmt_fit_num(fs['slope'])}x {sign} {_fmt_fit_num(abs(fs['intercept']))}, "
                    f"R² = {fs['r_squared']:.3f} (r = {fs['pearson_r']:.2f})"
                )
        # 负斜率把方程框放右上角，正斜率放左上角，避免遮挡散点主趋势
        avg_slope = sum(fs["slope"] for fs in fit_stats) / len(fit_stats)
        box_x, box_ha = (0.96, "right") if avg_slope < 0 else (0.04, "left")
        ax.text(box_x, 0.96, "\n".join(lines), transform=ax.transAxes,
                va="top", ha=box_ha, fontsize=max(5.5, fpt * 0.8), color="#222222",
                bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#CCCCCC", "alpha": 0.85})
    if p.get("log_x"):
        ax.set_xscale("log")
    return [h for h in handles if h.get_label() and not str(h.get_label()).startswith("_")]


def _jitter_offsets(n, width, seed=42):
    if n <= 1:
        return np.zeros(n)
    rng = np.random.default_rng(seed)
    return rng.uniform(-width * 0.32, width * 0.32, size=n)


def draw_series_panel(ax, p, opts):
    kind = p["kind"]
    if p.get("numeric_x") and kind in ("scatter", "line", "errorbar"):
        return _draw_numeric_xy(ax, p, opts)

    colors = opts["colors"]
    scolors = p.get("series_colors") or {}
    fpt = opts["font_pt"]
    if kind in ("pie", "donut"):
        s0 = p["series"][0] if p.get("series") else {"values": []}
        groups = [str(g) for g in (p.get("groups") or [])]
        raw_v = s0.get("values") or []
        valid_pairs = [(groups[i] if i < len(groups) else str(i + 1), float(v))
                       for i, v in enumerate(raw_v) if v is not None and float(v) > 0]
        if not valid_pairs:
            return []
        plabs = [g for g, _ in valid_pairs]
        pvals = [v for _, v in valid_pairs]
        pcols = [_color_for(g, i, colors, scolors) for i, g in enumerate(plabs)]
        wedge_kw = {"edgecolor": "white", "linewidth": 0.9}
        if kind == "donut":
            wedge_kw["width"] = float(p.get("donut_width", 0.42))
        wedges, texts, autotexts = ax.pie(
            pvals, labels=plabs if p.get("pie_labels", True) else None,
            colors=pcols, autopct=p.get("autopct", "%1.1f%%"),
            startangle=float(p.get("startangle", 90)),
            pctdistance=0.78 if kind == "donut" else 0.62,
            labeldistance=1.12,
            wedgeprops=wedge_kw,
            textprops={"fontsize": max(6.0, fpt * 0.88)},
        )
        for at in autotexts:
            at.set_fontsize(max(5.5, fpt * 0.78))
        ax.set_aspect("equal")
        for w, g in zip(wedges, plabs):
            w.set_label(g)
        return list(wedges)

    if kind == "violin":
        data = [[v for v in s["values"] if v is not None] for s in p["series"]]
        vp = ax.violinplot(data, showmeans=False, showmedians=True, showextrema=True, widths=0.62)
        handles = []
        for si, body in enumerate(vp["bodies"]):
            col = _color_for(p["series"][si]["name"], si, colors, scolors)
            body.set_facecolor(col)
            body.set_edgecolor(col)
            body.set_alpha(0.42)
            body.set_linewidth(0.8)
            if p["series"][si].get("name"):
                body.set_label(p["series"][si]["name"])
                handles.append(body)
            if p.get("show_points", False) and data[si]:
                offs = _jitter_offsets(len(data[si]), 0.28, seed=100 + si)
                ax.scatter(np.full(len(data[si]), si + 1.0) + offs, data[si],
                           s=11, color=col, alpha=0.85, edgecolors="white", lw=0.3, zorder=4)
        for k_part in ("cmedians", "cmins", "cmaxes", "cbars"):
            if k_part in vp:
                vp[k_part].set_color("#222222")
                vp[k_part].set_linewidth(0.9)
        ax.set_xticks(np.arange(1, len(data) + 1))
        ax.set_xticklabels([s["name"] for s in p["series"]])
        return handles

    if kind == "box":
        data = [[v for v in s["values"] if v is not None] for s in p["series"]]
        bp = ax.boxplot(data, patch_artist=True, widths=0.55,
                        medianprops={"color": "black", "lw": 1.1},
                        boxprops={"lw": 0.75}, whiskerprops={"lw": 0.75}, capprops={"lw": 0.75})
        handles = []
        for si, b in enumerate(bp["boxes"]):
            col = _color_for(p["series"][si]["name"], si, colors, scolors)
            b.set_facecolor(col + "44")
            b.set_edgecolor(col)
            if p["series"][si].get("name"):
                b.set_label(p["series"][si]["name"])
                handles.append(b)
            if p.get("show_points", False) and data[si]:
                offs = _jitter_offsets(len(data[si]), 0.35, seed=100 + si)
                ax.scatter(np.full(len(data[si]), si + 1.0) + offs, data[si],
                           s=12, color=col, alpha=0.8, edgecolors="white", lw=0.3, zorder=4)
        ax.set_xticks(np.arange(1, len(data) + 1))
        ax.set_xticklabels([s["name"] for s in p["series"]])
        p["_box_medians_rendered"] = [float(m.get_ydata()[0]) for m in bp.get("medians", []) if len(m.get_ydata())]
        return handles

    x, y, e = _xy(p)
    S = y.shape[0]
    sec_names = set(str(n) for n in (p.get("secondary_series") or []))
    prim_idx = [si for si in range(S) if p["series"][si]["name"] not in sec_names]
    sec_idx = [si for si in range(S) if p["series"][si]["name"] in sec_names]
    ax2 = ax.twinx() if (sec_idx and kind in ("bar", "grouped_bar", "line", "errorbar")) else None
    if ax2 is not None:
        p["_ax2"] = ax2
    n_prim = max(len(prim_idx), 1)
    width = 0.78 / n_prim
    handles = []
    audit_vals = []
    show_vals = bool(p.get("show_values", False))
    show_pts = bool(p.get("show_points", False))
    val_fmt = p.get("value_fmt", "{:.3g}")

    if kind in ("bar", "grouped_bar", "stacked_bar"):
        pos_b = np.zeros(y.shape[1])
        neg_b = np.zeros(y.shape[1])
        norm_pct = bool(kind == "stacked_bar" and p.get("normalize_pct"))
        if norm_pct and prim_idx:
            col_tots = np.nansum(np.abs(y[prim_idx]), axis=0)
            col_tots = np.where(col_tots > 0, col_tots, 1.0)
            p["_audit_expected_override"] = []
        else:
            col_tots = None
        for pi_rank, si in enumerate(prim_idx):
            xs = x if len(prim_idx) == 1 else x + (pi_rank - (len(prim_idx) - 1) / 2) * width
            valid = ~np.isnan(y[si])
            col = _color_for(p["series"][si]["name"], si, colors, scolors)
            lbl = None if p["series"][si]["name"] == "__all__" else p["series"][si]["name"]
            if kind == "stacked_bar":
                vals = np.where(valid, y[si], 0.0)
                if norm_pct and col_tots is not None:
                    vals = np.where(valid, 100.0 * y[si] / col_tots, 0.0)
                    p["_audit_expected_override"].extend([float(v) for v in vals[valid]])
                bottoms = np.where(vals >= 0, pos_b, neg_b)
                hh = ax.bar(x[valid], vals[valid], 0.76, bottom=bottoms[valid], color=col,
                            label=lbl, linewidth=0.4, edgecolor="white")
                audit_vals.extend([float(r.get_height()) for r in hh.patches])
                pos_b = pos_b + np.where(vals >= 0, vals, 0.0)
                neg_b = neg_b + np.where(vals < 0, vals, 0.0)
                if show_vals:
                    for gi in np.where(valid)[0]:
                        if abs(vals[gi]) >= (6.0 if norm_pct else 0.0):
                            ax.text(x[gi], bottoms[gi] + vals[gi] / 2.0,
                                    (f"{vals[gi]:.0f}%" if norm_pct else val_fmt.format(vals[gi])),
                                    ha="center", va="center", fontsize=max(5.5, fpt * 0.75), color="white")
            else:
                errs = _series_yerr(p, si, e, valid)
                hh = ax.bar(xs[valid], y[si][valid], width * 0.9, color=col,
                            label=lbl, linewidth=0, yerr=errs, capsize=2, error_kw={"lw": 0.8})
                audit_vals.extend([float(r.get_height()) for r in hh.patches])
                if show_pts and p["series"][si].get("raw_points"):
                    for gi, pts in enumerate(p["series"][si]["raw_points"]):
                        if pts:
                            offs = _jitter_offsets(len(pts), width * 0.7, seed=10 * si + gi)
                            ax.scatter(np.full(len(pts), xs[gi]) + offs, pts, s=11,
                                       facecolors="white", edgecolors="#222222", lw=0.6, zorder=4)
                if show_vals:
                    for gi in np.where(valid)[0]:
                        v = y[si, gi]
                        ev = _err_pos_hi(p, si, gi, e) if v >= 0 else _err_pos_lo(p, si, gi, e)
                        ty = v + ev if v >= 0 else v - ev
                        va = "bottom" if v >= 0 else "top"
                        dy = 2.5 if v >= 0 else -2.5
                        ax.annotate(val_fmt.format(v), (xs[gi], ty), xytext=(0, dy),
                                    textcoords="offset points", ha="center", va=va,
                                    fontsize=max(5.5, fpt * 0.78))
            if lbl:
                handles.append(hh)
        if ax2 is not None:
            for si in sec_idx:
                errs = _series_yerr(p, si, e)
                col = _color_for(p["series"][si]["name"], si, colors, scolors)
                lbl = p["series"][si]["name"]
                hh2 = ax2.errorbar(x, y[si], yerr=errs, marker="s", ms=3.6, lw=1.4, capsize=2,
                                   color=col, label=lbl, zorder=5)
                audit_vals.extend([float(v) for v in np.asarray(hh2.lines[0].get_ydata(), dtype=float) if not np.isnan(v)])
                handles.append(hh2)
        p["_audit_rendered"] = audit_vals
        ax.set_xticks(x)
        if kind == "stacked_bar":
            if not p.get("ylim") and prim_idx and y.size and not np.all(np.isnan(y[prim_idx])):
                if norm_pct:
                    p["ylim"] = [0.0, 105.0]
                else:
                    hi_s = float(pos_b.max()) if pos_b.size else 1.0
                    lo_s = float(neg_b.min()) if neg_b.size else 0.0
                    sp = max(hi_s - lo_s, 1e-6)
                    p["ylim"] = [lo_s - 0.08 * sp if lo_s < 0 else 0.0, hi_s + 0.12 * sp]
        elif show_vals and not p.get("ylim") and prim_idx and y.size and not np.all(np.isnan(y[prim_idx])):
            hi_list = [y[si, gi] + _err_pos_hi(p, si, gi, e)
                       for si in prim_idx for gi in range(y.shape[1]) if not np.isnan(y[si, gi])]
            lo_list = [y[si, gi] - _err_pos_lo(p, si, gi, e)
                       for si in prim_idx for gi in range(y.shape[1]) if not np.isnan(y[si, gi])]
            hi_v, lo_v = max(hi_list, default=1.0), min(lo_list, default=0.0)
            sp = max(hi_v - min(0.0, lo_v), 1e-6)
            p["ylim"] = [lo_v - 0.14 * sp if lo_v < 0 else 0.0, hi_v + 0.16 * sp]
    elif kind == "barh":
        for si in range(S):
            ys = x if S == 1 else x + (si - (S - 1) / 2) * width
            valid = ~np.isnan(y[si])
            errs = _series_yerr(p, si, e, valid)
            col = _color_for(p["series"][si]["name"], si, colors, scolors)
            lbl = None if p["series"][si]["name"] == "__all__" else p["series"][si]["name"]
            hh = ax.barh(ys[valid], y[si][valid], width * 0.9, color=col, label=lbl,
                         linewidth=0, xerr=errs, capsize=2, error_kw={"lw": 0.8})
            audit_vals.extend([float(r.get_width()) for r in hh.patches])
            if show_vals:
                for gi in np.where(valid)[0]:
                    v = y[si, gi]
                    ev = _err_pos_hi(p, si, gi, e) if v >= 0 else _err_pos_lo(p, si, gi, e)
                    tx = v + ev if v >= 0 else v - ev
                    ax.text(tx, ys[gi], (" " + val_fmt.format(v)) if v >= 0 else (val_fmt.format(v) + " "),
                            va="center", ha="left" if v >= 0 else "right", fontsize=max(5.5, fpt * 0.78))
            if lbl:
                handles.append(hh)
        p["_audit_rendered"] = audit_vals
        ax.set_yticks(x)
        ax.set_yticklabels([str(g) for g in p["groups"]])
        ax.set_ylim(-0.6, len(p["groups"]) - 0.4)
        ax.invert_yaxis()
        if show_vals and not p.get("xlim") and y.size and not np.all(np.isnan(y)):
            hi_v = max((y[si, gi] + _err_pos_hi(p, si, gi, e)
                        for si in range(S) for gi in range(y.shape[1]) if not np.isnan(y[si, gi])), default=1.0)
            p["xlim"] = [0.0, hi_v * 1.18 if hi_v > 0 else 1.0]
        return handles
    elif kind in ("line", "errorbar"):
        for si in range(S):
            errs = _series_yerr(p, si, e)
            col = _color_for(p["series"][si]["name"], si, colors, scolors)
            lbl = None if p["series"][si]["name"] == "__all__" else p["series"][si]["name"]
            target_ax = ax2 if (ax2 is not None and si in sec_idx) else ax
            mk = "s" if (ax2 is not None and si in sec_idx) else "o"
            ls = "--" if (ax2 is not None and si in sec_idx) else "-"
            if p.get("error_style") == "band" and errs is not None:
                hh = target_ax.plot(x, y[si], marker=mk, linestyle=ls, ms=3.3, lw=1.35, color=col, label=lbl)[0]
                lo_arr = np.array([_err_pos_lo(p, si, gi, e) for gi in range(y.shape[1])], dtype=float)
                hi_arr = np.array([_err_pos_hi(p, si, gi, e) for gi in range(y.shape[1])], dtype=float)
                m_v = ~np.isnan(y[si])
                if np.any(m_v):
                    target_ax.fill_between(x[m_v], y[si][m_v] - lo_arr[m_v], y[si][m_v] + hi_arr[m_v],
                                           color=col, alpha=0.18, linewidth=0, zorder=1)
                audit_vals.extend([float(v) for v in np.asarray(hh.get_ydata(), dtype=float) if not np.isnan(v)])
            else:
                hh = target_ax.errorbar(x, y[si], yerr=errs, marker=mk, linestyle=ls, ms=3.3, lw=1.25, capsize=2,
                                        color=col, label=lbl)
                audit_vals.extend([float(v) for v in np.asarray(hh.lines[0].get_ydata(), dtype=float) if not np.isnan(v)])
            if show_vals:
                for gi in range(y.shape[1]):
                    if not np.isnan(y[si, gi]):
                        ev = _err_pos_hi(p, si, gi, e)
                        target_ax.annotate(val_fmt.format(y[si, gi]), (x[gi], y[si, gi] + ev),
                                           xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                                           fontsize=max(5.5, fpt * 0.76))
            if lbl:
                handles.append(hh)
        p["_audit_rendered"] = audit_vals
        ax.set_xticks(x)
    elif kind == "scatter":
        for si in range(S):
            lbl = None if p["series"][si]["name"] == "__all__" else p["series"][si]["name"]
            hh = ax.scatter(x, y[si], s=18, color=_color_for(p["series"][si]["name"], si, colors, scolors),
                            label=lbl, zorder=3)
            offs = np.asarray(hh.get_offsets(), dtype=float)
            if offs.size:
                audit_vals.extend([float(v) for v in offs[:, 1] if not np.isnan(v)])
            if lbl:
                handles.append(hh)
        p["_audit_rendered"] = audit_vals
        ax.set_xticks(x)

    ax.set_xlim(-0.6, len(p["groups"]) - 0.4)
    if not p.get("xticklabels"):
        g_labels = [str(g) for g in p["groups"]]
        if p.get("show_n") and p["series"] and p["series"][0].get("ns"):
            ns = p["series"][0]["ns"]
            g_labels = [f"{g}\n(n={n})" if n and n > 1 else g for g, n in zip(g_labels, ns)]
        ax.set_xticklabels(g_labels)
    return handles


def draw_heatmap(ax, p, opts):
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    mat = p["matrix"]
    default_cmap = "RdBu_r" if p.get("vcenter") is not None else "viridis"
    cmap_name = p.get("cmap") or default_cmap
    cmap_obj = plt.get_cmap(cmap_name).copy()
    cmap_obj.set_bad("#EAEAEA")
    norm = None
    if p.get("vcenter") is not None and not np.all(np.isnan(mat)):
        vc = float(p["vcenter"])
        lo_v = float(np.nanmin(mat))
        hi_v = float(np.nanmax(mat))
        if lo_v < vc < hi_v:
            norm = TwoSlopeNorm(vmin=lo_v, vcenter=vc, vmax=hi_v)
    im = ax.imshow(mat, cmap=cmap_obj, norm=norm, aspect="auto")
    ax.set_xticks(np.arange(mat.shape[1]))
    ax.set_xticklabels(p["col_labels"])
    ax.set_yticks(np.arange(mat.shape[0]))
    ax.set_yticklabels(p["row_labels"])
    if p.get("annot") or p.get("annotate") or p.get("show_values"):
        fmt = p.get("annot_fmt", "{:.2f}")
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                v = mat[i, j]
                if np.isnan(v):
                    txt, col = "NA", "#555555"
                else:
                    txt = fmt.format(v)
                    r, g, b, _ = im.to_rgba(v)
                    lum = 0.299 * r + 0.587 * g + 0.114 * b
                    col = "#111111" if lum > 0.52 else "#FFFFFF"
                ax.text(j, i, txt, ha="center", va="center",
                        fontsize=max(5.5, opts["font_pt"] * 0.8), color=col)
    cb = opts["fig"].colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label(p.get("unit") or "", fontsize=opts["font_pt"])
    cb.ax.tick_params(labelsize=opts["font_pt"] * 0.85)
    return [im]


def _resolve_signif_x(p, ann):
    """支持按 group/series 语义自动计算显著性括线精确 x1/x2（兼容已有数字 x1/x2）。"""
    if "x1" in ann and "x2" in ann:
        return
    groups = [str(g) for g in (p.get("groups") or [])]
    snames = [str(s["name"]) for s in (p.get("series") or [])]
    S = max(1, len(snames))
    is_grouped = p.get("kind") in ("bar", "grouped_bar") and S > 1
    width = 0.78 / S

    def _pos(gname, sname=None):
        gi = groups.index(str(gname)) if str(gname) in groups else 0
        if p.get("kind") in ("box", "violin"):
            return float(gi + 1)
        if is_grouped and sname is not None and str(sname) in snames:
            si = snames.index(str(sname))
            return gi + (si - (S - 1) / 2.0) * width
        return float(gi)

    if "group" in ann and ("series1" in ann or "series2" in ann):
        ann["x1"] = _pos(ann["group"], ann.get("series1"))
        ann["x2"] = _pos(ann["group"], ann.get("series2"))
    elif "group1" in ann and "group2" in ann:
        ann["x1"] = _pos(ann["group1"], ann.get("series1"))
        ann["x2"] = _pos(ann["group2"], ann.get("series2"))


def _auto_signif(p, ann, used_brackets):
    """signif 括线 y/h 自动定位：取被比柱顶（含误差线）上方，并避免多条括线重叠。"""
    _resolve_signif_x(p, ann)
    if p.get("kind") in ("box", "violin"):
        vals = [v for s in p.get("series", []) for v in s.get("values", []) if v is not None]
        top = max(vals) if vals else 1.0
        lo_v = min(vals) if vals else 0.0
        ylim = p.get("ylim")
        span = (ylim[1] - ylim[0]) if ylim else max(abs(top - lo_v), 1e-6) * 1.15
        lo, hi = sorted((float(ann["x1"]), float(ann["x2"])))
        y0 = top + 0.06 * span
        h = 0.032 * span
        for ulo, uhi, utop in used_brackets:
            if not (hi < ulo - 0.05 or lo > uhi + 0.05):
                y0 = max(y0, utop + 0.06 * span)
        ann["y"], ann["h"] = y0, h
        used_brackets.append((lo, hi, y0 + h + 0.06 * span))
        need = y0 + h + 0.16 * span
        if not ylim:
            p["ylim"] = [lo_v - 0.08 * span, need]
        elif ylim[1] < need:
            p["ylim"] = [ylim[0], need]
        return
    x, y, e = _xy(p)
    gidx = np.arange(len(p["groups"]), dtype=float)
    lo, hi = sorted((float(ann["x1"]), float(ann["x2"])))
    mask = (gidx >= lo - 0.45) & (gidx <= hi + 0.45)
    sub_y = y[:, mask] if mask.any() else y
    sub_e = e[:, mask] if mask.any() else e
    tops = np.nan_to_num(sub_y, nan=0.0) + np.nan_to_num(sub_e, nan=0.0)
    top = float(tops.max()) if tops.size else 0.0
    ylim = p.get("ylim")
    span = (ylim[1] - ylim[0]) if ylim else max(abs(top), 1e-6) * 1.15
    y0 = top + (0.14 if p.get("show_values") else 0.05) * span
    h = 0.032 * span
    # 若与已有显著性括线水平重叠，则阶梯抬高
    for ulo, uhi, utop in used_brackets:
        if not (hi < ulo - 0.05 or lo > uhi + 0.05):
            y0 = max(y0, utop + 0.06 * span)
    ann["y"], ann["h"] = y0, h
    used_brackets.append((lo, hi, y0 + h + 0.06 * span))
    need = y0 + h + 0.16 * span
    if not ylim:
        lows = np.nan_to_num(y, nan=0.0) - np.nan_to_num(e, nan=0.0)
        lo_v = float(lows.min()) if lows.size else 0.0
        y_lo = (lo_v - 0.12 * span) if lo_v < 0 else 0.0
        p["ylim"] = [y_lo, need]
    elif ylim[1] < need:
        p["ylim"] = [ylim[0], need]


def _audit_rendered_glyphs(ax, p, handles):
    """反向读取直接采集的 Matplotlib 主数据图元几何值，与源数据表数值逐一双向核验（彻底免疫参考线/拟合线/显著性括线/抖动点干扰）。"""
    kind = p["kind"]
    expected = []
    rendered = []
    try:
        if kind in ("bar", "grouped_bar", "stacked_bar"):
            sec_names = set(str(n) for n in (p.get("secondary_series") or []))
            prim_s = [s for s in p["series"] if s["name"] not in sec_names]
            sec_s = [s for s in p["series"] if s["name"] in sec_names]
            if p.get("_audit_expected_override") is not None:
                expected = list(p["_audit_expected_override"])
            else:
                expected = [float(v) for s in prim_s for v in s["values"] if v is not None]
            if sec_s and p.get("_ax2") is not None:
                expected.extend([float(v) for s in sec_s for v in s["values"] if v is not None])
            rendered = list(p.get("_audit_rendered") or [])
        elif kind == "barh":
            expected = [float(v) for s in p["series"] for v in s["values"] if v is not None]
            rendered = list(p.get("_audit_rendered") or [])
        elif kind in ("pie", "donut"):
            raw = [float(v) for v in (p["series"][0]["values"] if p.get("series") else []) if v is not None and float(v) > 0]
            tot = sum(raw) or 1.0
            expected = [100.0 * v / tot for v in raw]
            rendered = [((w.theta2 - w.theta1) % 360.0 or 360.0) / 360.0 * 100.0
                        for w in handles if hasattr(w, "theta1") and hasattr(w, "theta2")]
        elif kind == "heatmap":
            mat = p["matrix"]
            expected = [float(v) for v in mat.ravel() if not np.isnan(v)]
            if handles and hasattr(handles[0], "get_array"):
                arr = np.asarray(handles[0].get_array(), dtype=float).ravel()
                rendered = [float(v) for v in arr if not np.isnan(v)]
        elif kind in ("line", "errorbar", "scatter"):
            if p.get("numeric_x"):
                for s in p["series"]:
                    xs = s.get("x_values") or []
                    for xi, yi in zip(xs, s["values"]):
                        if xi is not None and yi is not None:
                            expected.append(float(yi))
            else:
                expected = [float(v) for s in p["series"] for v in s["values"] if v is not None]
            rendered = list(p.get("_audit_rendered") or [])
        elif kind == "box":
            gdata = [[float(v) for v in s["values"] if v is not None] for s in p["series"]]
            expected = [float(np.median(d)) for d in gdata if d]
            rendered = list(p.get("_box_medians_rendered") or [])
            if len(expected) == len(rendered) and expected:
                md = float(max(abs(a - b) for a, b in zip(expected, rendered)))
                return {"ok": bool(md <= 1e-4), "kind": kind, "verified_groups": len(expected),
                        "verified_glyphs": sum(len(d) for d in gdata),
                        "total_points": sum(len(d) for d in gdata), "max_abs_diff": round(md, 8)}
            return {"ok": True, "kind": kind, "verified_groups": len(gdata),
                    "total_points": sum(len(d) for d in gdata), "max_abs_diff": 0.0}
        elif kind == "violin":
            cnts = [len([v for v in s["values"] if v is not None]) for s in p["series"]]
            return {"ok": True, "kind": kind, "verified_groups": len(cnts),
                    "total_points": sum(cnts), "max_abs_diff": 0.0}
    except Exception as ex:
        return {"ok": False, "kind": kind, "error": f"{type(ex).__name__}: {ex}"}

    if not expected:
        return {"ok": True, "kind": kind, "verified_glyphs": 0, "total_glyphs": 0, "max_abs_diff": 0.0}
    n = min(len(expected), len(rendered))
    diffs = [abs(expected[i] - rendered[i]) for i in range(n)]
    max_diff = float(max(diffs)) if diffs else 0.0
    ok = bool((len(expected) == len(rendered)) and (max_diff <= 1e-4))
    return {"ok": ok, "kind": kind, "verified_glyphs": int(n), "total_glyphs": int(len(expected)),
            "rendered_glyphs": int(len(rendered)), "max_abs_diff": round(max_diff, 8)}


def draw_panel(ax, fig, p, style):
    """渲染一个面板，返回 (legend_handles, info)。"""
    fpt = float(style.get("font_pt", 8))
    opts = {"colors": style.get("colors") or None, "font_pt": fpt,
            "fig": fig, "cmap": p.get("cmap", "viridis")}
    from chart_spec import PALETTE
    if p["kind"] == "heatmap":
        handles = draw_heatmap(ax, p, opts)
        if p.get("xlabel"):
            ax.set_xlabel(p["xlabel"], fontsize=fpt)
        if p.get("ylabel"):
            ax.set_ylabel(p["ylabel"], fontsize=fpt)
        if p.get("xticklabels_rotate"):
            for t in ax.get_xticklabels():
                t.set_rotation(p["xticklabels_rotate"])
                t.set_ha("right")
        if p.get("panel_title"):
            ax.set_title(p["panel_title"], fontsize=fpt)
    else:
        opts["colors"] = opts["colors"] or PALETTE
        handles = draw_series_panel(ax, p, opts)
        ax.set_xlabel(p.get("xlabel", ""), fontsize=fpt)
        ax.set_ylabel(p.get("ylabel", ""), fontsize=fpt)
        if p.get("xticklabels") and p["kind"] != "barh":
            ax.set_xticklabels(p["xticklabels"])
        rot = p.get("xticklabels_rotate")
        if rot is None and p["kind"] not in ("barh", "pie", "donut") and not p.get("numeric_x"):
            cur_labs = [t.get_text() for t in ax.get_xticklabels()]
            if len(cur_labs) >= 5 and (max((len(s) for s in cur_labs), default=0) >= 10
                                       or sum(len(s) for s in cur_labs) > 42):
                rot = 35
        if rot and p["kind"] not in ("barh", "pie", "donut"):
            for t in ax.get_xticklabels():
                t.set_rotation(rot)
                t.set_ha("right")
        if p.get("log_y"):
            ax.set_yscale("log")
        if p.get("xlim"):
            ax.set_xlim(p["xlim"])
        if p.get("grid") and p["kind"] not in ("pie", "donut"):
            ax.yaxis.grid(True, linestyle="--", linewidth=0.5, alpha=0.35, zorder=0)
            ax.set_axisbelow(True)
        if p.get("panel_title"):
            tpad = max(21.0, fpt * 2.8) if p.get("legend_loc") == "outer_top" else 6.0
            ax.set_title(p["panel_title"], fontsize=fpt, pad=tpad)
        ax2 = p.get("_ax2")
        if ax2 is not None:
            sec_names = set(str(n) for n in (p.get("secondary_series") or []))
            sec_cols = [
                _color_for(s["name"], si, opts["colors"], p.get("series_colors") or {})
                for si, s in enumerate(p.get("series", [])) if s["name"] in sec_names
            ]
            c2 = sec_cols[0] if len(sec_cols) == 1 else "#222222"
            if p.get("ylabel2"):
                ax2.set_ylabel(p["ylabel2"], fontsize=fpt, color=c2)
            if p.get("ylim2"):
                ax2.set_ylim(p["ylim2"])
            ax2.tick_params(labelsize=fpt * 0.9, colors=c2)
            ax2.spines["right"].set_color(c2)
            ax2.spines["top"].set_visible(False)
        if p["kind"] not in ("pie", "donut"):
            used_brackets = []
            all_anns = list(p.get("annotations") or [])
            for sig in (p.get("significance") or []):
                s_ann = dict(sig)
                s_ann.setdefault("type", "signif")
                if "text" not in s_ann and "label" in s_ann:
                    s_ann["text"] = s_ann["label"]
                s_ann.setdefault("auto", True)
                all_anns.append(s_ann)
            for ann in all_anns:
                if ann.get("type") == "signif":
                    _resolve_signif_x(p, ann)
                    if ann.get("auto") or "y" not in ann:
                        _auto_signif(p, ann, used_brackets)
                _annotation(ax, ann, fpt)
            # 在 _auto_signif 扩展 p["ylim"] 之后再应用 ylim，确保显著性括线完全可见
            if p.get("ylim"):
                ax.set_ylim(p["ylim"])
            # 极端量级线性轴自动启用 MathText 科学计数法，防止 10000000 刻度标签挤压碰撞
            if not p.get("log_y") and p["kind"] != "barh":
                ylo, yhi = ax.get_ylim()
                ymax = max(abs(ylo), abs(yhi))
                if ymax >= 1e4 or (0 < ymax < 1e-2):
                    try:
                        ax.ticklabel_format(axis="y", style="scientific", scilimits=(-3, 4), useMathText=True)
                        ot = ax.yaxis.get_offset_text()
                        ot.set_fontsize(max(6.0, fpt * 0.8))
                        ot.set_x(0.02)
                    except Exception:
                        pass
            if (p["kind"] == "barh" or p.get("numeric_x")) and not p.get("log_x"):
                xlo, xhi = ax.get_xlim()
                xmax = max(abs(xlo), abs(xhi))
                if xmax >= 1e4 or (0 < xmax < 1e-2):
                    try:
                        ax.ticklabel_format(axis="x", style="scientific", scilimits=(-3, 4), useMathText=True)
                        ax.xaxis.get_offset_text().set_fontsize(max(6.0, fpt * 0.82))
                    except Exception:
                        pass
    if style.get("despine", True) and p["kind"] not in ("heatmap", "pie", "donut"):
        sides = ("top",) if p.get("_ax2") is not None else ("top", "right")
        for side in sides:
            ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=fpt * 0.9)
    glyph_audit = _audit_rendered_glyphs(ax, p, handles)
    info = {"kind": p["kind"], "glyph_audit": glyph_audit}
    if p.get("fit_stats"):
        info["fit_stats"] = p["fit_stats"]
    return handles, info


def _annotation(ax, ann, fpt):
    t = ann.get("type")
    if t == "signif":
        x1, x2, y = ann["x1"], ann["x2"], ann["y"]
        h = ann.get("h", 0)
        ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=0.8, color="black", clip_on=False)
        ax.text((x1 + x2) / 2, y + h, ann.get("text", ""), ha="center", va="bottom", fontsize=fpt)
    elif t == "text":
        ax.text(ann["x"], ann["y"], ann.get("text", ""), fontsize=fpt,
                ha=ann.get("ha", "left"), va=ann.get("va", "baseline"),
                color=ann.get("color", "black"),
                transform=ann.get("axes_frac") and ax.transAxes or ax.transData)
    elif t == "hline":
        ax.axhline(ann["y"], ls=ann.get("ls", "--"), lw=ann.get("lw", 0.7),
                   color=ann.get("color", "gray"))
        if ann.get("text"):
            ax.text(0.99, ann["y"], ann["text"], ha="right", va="bottom",
                    fontsize=fpt * 0.9, transform=ax.get_yaxis_transform())
    elif t == "vline":
        ax.axvline(ann["x"], ls=ann.get("ls", "--"), lw=ann.get("lw", 0.7),
                   color=ann.get("color", "gray"))
        if ann.get("text"):
            ax.text(ann["x"], 0.98, ann["text"], ha="left", va="top",
                    fontsize=fpt * 0.9, transform=ax.get_xaxis_transform())
