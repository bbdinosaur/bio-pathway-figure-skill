#!/usr/bin/env python3
"""Publication-grade SVG chart renderer: bar / hbar / stacked / line / dot / heatmap.

Pure SVG 1.1 primitives (editable text, crisp gridlines, error bars on ALL
quantitative chart types, distinct markers/linestyles for grayscale & colorblind
accessibility, reference lines, significance brackets, xlabel/ylabel/note).
"""
from __future__ import annotations

import math

from gaconfig import (DIV_RAMP, GRID, GRID_MINOR, HEAT_RAMP, INK, INK2, MUT,
                      SERIES, esc, interp_ramp, luminance)
from gaprims import line, marker_shape, rrect, swatch, text, text_fit
from textmetrics import fit_font, text_width, wrap_text

MARKERS = ["circle", "square", "triangle", "diamond"]
DASHES = [None, "6 3", "2 2", "8 3 2 3"]


def _f(v, default=0.0) -> float:
    """Self-healing float parser accepting strings like '75%' or '1,234'."""
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else default
    s = str(v or "").strip().rstrip("%").replace(",", "").strip()
    try:
        fv = float(s)
        return fv if math.isfinite(fv) else default
    except ValueError:
        return default


def nice_ticks(lo, hi, n=5):
    """Return nice tick values spanning <= lo and >= hi with minimal dead headroom."""
    if hi <= lo:
        hi = lo + 1.0
    span = hi - lo
    best = None
    for target in (n, n - 1, n + 1):
        raw = span / max(target, 2)
        mag = 10 ** math.floor(math.log10(raw))
        for m in (1, 2, 2.5, 5, 10):
            step = m * mag
            t0 = math.floor(lo / step + 1e-9) * step
            t1 = math.ceil(hi / step - 1e-9) * step
            cnt = int(round((t1 - t0) / step))
            if 3 <= cnt <= 6:
                waste = ((t1 - hi) + (lo - t0)) / max(span, 1e-9)
                score = waste + 0.04 * abs(cnt - 4.5)
                if best is None or score < best[0]:
                    best = (score, step, t0, t1)
    if best is None:
        raw = span / max(n, 2)
        mag = 10 ** math.floor(math.log10(raw))
        step = mag
        for m in (1, 2, 2.5, 5, 10):
            if raw <= m * mag:
                step = m * mag
                break
        t0 = math.floor(lo / step + 1e-9) * step
        t1 = math.ceil(hi / step - 1e-9) * step
    else:
        _, step, t0, t1 = best
    out, v = [], t0
    while v <= t1 + step * 0.01 and len(out) < 12:
        out.append(round(v, 10))
        v += step
    return out or [lo, hi]


_SUP_MAP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def _fmt_log_tick(v: float) -> str:
    if v <= 0:
        return "0"
    exp = round(math.log10(v))
    if abs(v - 10 ** exp) / max(v, 1e-12) < 1e-4:
        if -2 <= exp <= 3:
            return _fmt_num(10 ** exp)
        return "10" + str(exp).translate(_SUP_MAP)
    return _fmt_num(v)


def _log_ticks(lo_v: float, hi_v: float) -> tuple[list[float], float, float]:
    """Generate clean decade ticks for log10 axes."""
    lo_e = int(math.floor(math.log10(max(lo_v, 1e-12))))
    hi_e = int(math.ceil(math.log10(max(hi_v, 1e-12))))
    if hi_e <= lo_e:
        hi_e = lo_e + 1
    step = 1 if (hi_e - lo_e) <= 6 else 2
    ticks = [10.0 ** e for e in range(lo_e, hi_e + 1, step)]
    if ticks[-1] < 10.0 ** hi_e:
        ticks.append(10.0 ** hi_e)
    return ticks, ticks[0], ticks[-1]


def _fmt_num(v):
    if v == 0:
        return "0"
    av = abs(v)
    if av >= 1e6:
        return f"{v:.2e}"
    if av >= 1000:
        return f"{v:,.0f}"
    if av >= 100:
        return f"{round(v, 1):g}"
    if av >= 1:
        return f"{round(v, 2):g}"
    if av >= 0.01:
        return f"{round(v, 3):g}"
    return f"{v:.2g}"


def _legend(x, y, w, entries, fs):
    """Horizontal wrapped legend. Returns (svg, height_used)."""
    out, cx, cy, rows = [], x, y, 1
    for name, color, shape, mk, dash in entries:
        item_w = 24 + text_width(name, fs) + 14
        if cx + item_w > x + w and cx > x:
            cx, rows = x, rows + 1
            cy += fs * 1.45
        out.append(swatch(cx, cy + fs * 0.3, name, color, fs, shape,
                          marker=mk, dash=dash))
        cx += item_w
    return "".join(out), rows * fs * 1.45 + 4


def _render_heatmap(b, x, y, w, h, fs):
    """Matrix heatmap with sequential colorblind-safe ramp + colorbar + cell values."""
    rows = [str(r) for r in b.get("ylabels", b.get("rows", []))]
    cols = [str(c) for c in b.get("xlabels", b.get("cols", []))]
    mat = b.get("values", [])
    if not mat or not isinstance(mat[0], list):
        return text(x, y + fs, "Empty heatmap data", fs, MUT), fs * 2
    nr, nc = len(mat), len(mat[0])
    if not rows:
        rows = [f"R{i+1}" for i in range(nr)]
    if not cols:
        cols = [f"C{j+1}" for j in range(nc)]
    flat = [_f(v) for row in mat for v in row if v is not None]
    vmin = _f(b.get("vmin"), min(flat) if flat else 0.0) if "vmin" in b else (min(flat) if flat else 0.0)
    vmax = _f(b.get("vmax"), max(flat) if flat else 1.0) if "vmax" in b else (max(flat) if flat else 1.0)
    if vmax <= vmin:
        vmax = vmin + 1.0
    ramp_mode = str(b.get("ramp", "auto")).lower()
    use_div = (ramp_mode == "diverging") or (ramp_mode == "auto" and vmin < 0.0 < vmax)
    ramp = DIV_RAMP if use_div else HEAT_RAMP
    if use_div and "vmin" not in b and "vmax" not in b:
        abs_m = max(abs(vmin), abs(vmax), 1e-6)
        vmin, vmax = -abs_m, abs_m
    note = str(b.get("note", "")).strip()
    note_h = fs * 1.3 if note else 0
    cbar_h = 26
    left = min(w * 0.34, max((text_width(r, fs - 1) for r in rows), default=40) + 14)
    top_pad = fs * 1.6
    gx, gy = x + left, y + top_pad
    gw = max(60.0, w - left - 8)
    gh = max(60.0, h - top_pad - cbar_h - note_h - 10)
    cw, ch = gw / max(nc, 1), gh / max(nr, 1)
    out = []
    for j, c in enumerate(cols[:nc]):
        out.append(text_fit(gx + (j + 0.5) * cw, gy - 6, c, cw * 0.94,
                            fs - 1, INK2, "middle", weight="bold"))
    for i, r in enumerate(rows[:nr]):
        out.append(text_fit(gx - 6, gy + (i + 0.5) * ch + (fs - 1) * 0.35, r,
                            left - 10, fs - 1, INK2, "end"))
        for j in range(nc):
            raw_v = mat[i][j]
            if raw_v is None:
                out.append(rrect(gx + j * cw + 1, gy + i * ch + 1,
                                 cw - 2, ch - 2, rx=3, fill="#F1F5F9", stroke="#FFFFFF", sw=1.0))
                if b.get("value_labels", True) and cw >= 28 and ch >= 16:
                    out.append(text(gx + (j + 0.5) * cw,
                                    gy + (i + 0.5) * ch + (fs - 2) * 0.35,
                                    "—", max(10.0, fs - 2), MUT, "middle"))
                continue
            val = _f(raw_v)
            t = (val - vmin) / (vmax - vmin)
            fill = interp_ramp(t, ramp=ramp)
            out.append(rrect(gx + j * cw + 1, gy + i * ch + 1,
                             cw - 2, ch - 2, rx=3, fill=fill, stroke="#FFFFFF", sw=1.0))
            if b.get("value_labels", True) and cw >= 28 and ch >= 16:
                fg = "#FFFFFF" if luminance(fill) < 0.32 else INK
                out.append(text(gx + (j + 0.5) * cw,
                                gy + (i + 0.5) * ch + (fs - 2) * 0.35,
                                _fmt_num(val), max(10.0, fs - 2), fg, "middle",
                                weight="bold"))
    # Colorbar
    cby = gy + gh + 10
    steps = 12
    cbw = min(gw, 200.0)
    cbx = gx + (gw - cbw) / 2
    for k in range(steps):
        out.append(rrect(cbx + k * cbw / steps, cby, cbw / steps + 0.6, 10, rx=0,
                         fill=interp_ramp(k / (steps - 1), ramp=ramp)))
    out.append(rrect(cbx, cby, cbw, 10, rx=2, fill="none", stroke="#94A3B8", sw=0.8))
    out.append(text(cbx - 5, cby + 9, _fmt_num(vmin), max(10.0, fs - 2), MUT, "end"))
    out.append(text(cbx + cbw + 5, cby + 9, _fmt_num(vmax), max(10.0, fs - 2), MUT, "start"))
    if b.get("unit") or b.get("ylabel"):
        out.append(text(cbx + cbw / 2, cby + 22,
                        str(b.get("unit") or b.get("ylabel")),
                        max(10.0, fs - 2), MUT, "middle"))
    if note:
        out.append(text_fit(x + w / 2, y + h - 3, note, w - 8,
                            max(10.0, fs - 2), MUT, "middle"))
    return "".join(out), h


def _jitter_offsets(n: int, max_span: float) -> list[float]:
    """Deterministic symmetric offsets in [-max_span, +max_span] for replicate dots."""
    if n <= 1:
        return [0.0]
    # Balanced symmetric positions without RNG
    step = (2.0 * max_span) / max(n - 1, 1)
    # Interleave from center outward: 0, -1, +1, -2, +2 ...
    vals = [(-max_span + i * step) for i in range(n)]
    order = sorted(range(n), key=lambda k: (abs(k - (n - 1) / 2.0), k))
    return [vals[k] for k in order]


def _is_pct_axis(label: str, vsuf: str = "") -> bool:
    lb = (label or "").lower()
    return ("%" in lb) or ("percent" in lb) or ("survival" in lb) or (vsuf.strip() == "%")


def _bound_axis_ticks(lo_v: float, hi_v: float, lo_pad: float, hi_pad: float,
                      b: dict, label: str, vsuf: str = "",
                      has_top_annot: bool = False) -> tuple[list[float], float, float]:
    """Compute nice axis ticks with explicit ymin/ymax support & scientific 100% cap."""
    exp_lo = _f(b["ymin"]) if b.get("ymin") is not None else None
    exp_hi = _f(b["ymax"]) if b.get("ymax") is not None else None
    if exp_lo is not None or exp_hi is not None:
        t_lo = exp_lo if exp_lo is not None else lo_pad
        t_hi = exp_hi if exp_hi is not None else hi_pad
        ticks = nice_ticks(t_lo, t_hi, 5)
        vlo = exp_lo if exp_lo is not None else ticks[0]
        vhi = exp_hi if exp_hi is not None else ticks[-1]
        ticks = [t for t in ticks if vlo - 1e-6 <= t <= vhi + 1e-6]
        return ticks or [vlo, vhi], vlo, vhi
    # Scientific percentage / survival / viability cap: NEVER draw bogus 120% or 125% ticks!
    if _is_pct_axis(label, vsuf) and lo_v >= -1e-6 and 50.0 <= hi_v <= 106.0:
        ticks = [0.0, 25.0, 50.0, 75.0, 100.0]
        vlo = 0.0
        vhi = max(hi_v + 4.0, 112.0 if has_top_annot else 104.0)
        return ticks, vlo, vhi
    ticks = nice_ticks(lo_pad, hi_pad, 5)
    return ticks, ticks[0], ticks[-1]


def _render_hbar(b, x, y, w, h, fs):
    """Horizontal grouped bar chart — ideal for long biological/chemical labels."""
    series = b.get("series", [])
    xlabels = [str(lb) for lb in b.get("xlabels", b.get("ylabels", []))]
    colors = b.get("colors") or [SERIES[i % len(SERIES)] for i in range(len(series))]
    nsv = max(len(series), 1)
    lh, legend_svg = 0.0, ""
    if b.get("legend", len(series) > 1) and series:
        legend_svg, lh = _legend(
            x, y + fs, w,
            [(s.get("name", f"S{i+1}"), colors[i % len(colors)], "rect", "circle", None)
             for i, s in enumerate(series)], max(10.0, fs - 1))
    allv = [_f(v) for s in series for v in s.get("values", [])] or [0.0, 1.0]
    all_hi, all_lo = [], []
    for s in series:
        vals, err = s.get("values", []), s.get("err") or []
        pts_list = s.get("points") or []
        for i, v in enumerate(vals):
            fv = _f(v)
            e = _f(err[i]) if i < len(err) else 0.0
            all_hi.append(fv + e)
            all_lo.append(fv - e)
            if i < len(pts_list) and isinstance(pts_list[i], list):
                for pv in pts_list[i]:
                    if pv is not None:
                        all_hi.append(_f(pv))
                        all_lo.append(_f(pv))
    hi_v = max(all_hi) if all_hi else max(allv)
    lo_v = min(min(all_lo), 0.0) if all_lo else 0.0
    head = 1.16 if b.get("value_labels", True) else 1.06
    span0 = max(hi_v - lo_v, 1e-6)
    hi_pad = hi_v + span0 * (head - 1.0)
    lo_pad = lo_v - (span0 * 0.12 if lo_v < 0 and b.get("value_labels", True) else 0.0)
    xlab_raw = str(b.get("xlabel", b.get("ylabel", ""))).strip()
    ticks, vlo, vhi = _bound_axis_ticks(
        lo_v, hi_v, lo_pad, hi_pad,
        {"ymin": b.get("xmin"), "ymax": b.get("xmax")},
        xlab_raw, str(b.get("value_suffix", "")),
        has_top_annot=bool(b.get("value_labels", True)),
    )
    left = min(w * 0.42, max((text_width(lb, fs - 1) for lb in xlabels), default=50) + 12)
    note = str(b.get("note", "")).strip()
    xlab = str(b.get("xlabel", b.get("ylabel", ""))).strip()
    bot = fs * 1.5 + (fs * 1.4 if xlab else 0) + (fs * 1.25 if note else 0) + 4
    px, py = x + left, y + lh + 6
    gw = max(60.0, w - left - 12)
    gh = max(60.0, h - lh - 6 - bot)

    def sx(v):
        return px + (v - vlo) / max(vhi - vlo, 1e-9) * gw

    out = [legend_svg]
    for i, t in enumerate(ticks):
        tx = sx(t)
        if i > 0:
            tm = (ticks[i - 1] + t) / 2
            out.append(line(sx(tm), py, sx(tm), py + gh, GRID_MINOR, 0.8))
        out.append(line(tx, py, tx, py + gh, GRID, 1.0))
        out.append(text(tx, py + gh + fs * 1.15, _fmt_num(t),
                        max(10.0, fs - 1), MUT, "middle"))
    out.append(line(px, py + gh, px + gw, py + gh, "#94A3B8", 1.3))
    out.append(line(px, py, px, py + gh, "#94A3B8", 1.3))
    if vlo < 0 < vhi:
        out.append(line(sx(0.0), py, sx(0.0), py + gh, "#64748B", 1.2))

    ng = max(len(xlabels), max((len(s.get("values", [])) for s in series), default=1), 1)
    slot = gh / ng
    bh = min((slot * 0.72) / nsv, 32.0)
    group_h = bh * nsv
    vsuf = str(b.get("value_suffix", ""))
    for gi in range(ng):
        if gi < len(xlabels):
            out.append(text_fit(px - 7, py + slot * (gi + 0.5) + (fs - 1) * 0.35,
                                xlabels[gi], left - 10, max(10.0, fs - 1), INK2, "end"))
    for si, s in enumerate(series):
        col = colors[si % len(colors)]
        vals = s.get("values", [])
        err = s.get("err") or []
        pts_list = s.get("points") or []
        for i, v in enumerate(vals):
            v = float(v)
            cy = py + slot * (i + 0.5) - group_h / 2 + si * bh
            x0, x1 = sx(min(v, 0.0)), sx(max(v, 0.0))
            out.append(rrect(x0, cy, max(x1 - x0, 1.0), bh * 0.84, rx=2.5, fill=col))
            if i < len(pts_list) and isinstance(pts_list[i], list) and pts_list[i]:
                rpts = [float(pv) for pv in pts_list[i] if isinstance(pv, (int, float))]
                offs = _jitter_offsets(len(rpts), min(bh * 0.28, 7.0))
                midy = cy + bh * 0.42
                for pv, dy in zip(rpts, offs):
                    out.append(f'<circle cx="{sx(pv):.1f}" cy="{midy+dy:.1f}" r="2.7" '
                               f'fill="#FFFFFF" fill-opacity="0.88" stroke="{INK}" stroke-width="1.15"/>')
            e = float(err[i]) if i < len(err) else 0.0
            if e > 0:
                ey = cy + bh * 0.42
                out.append(line(sx(v - e), ey, sx(v + e), ey, "#374151", 1.3))
                for sgn in (-1, 1):
                    ex2 = sx(v + sgn * e)
                    out.append(line(ex2, ey - 3.5, ex2, ey + 3.5, "#374151", 1.3))
            if b.get("value_labels", True):
                vtxt = _fmt_num(v) + vsuf
                lfs = max(10.0, fs - 2)
                vw = text_width(vtxt, lfs)
                rpts_i = [float(pv) for pv in (pts_list[i] if i < len(pts_list) and isinstance(pts_list[i], list) else []) if isinstance(pv, (int, float))]
                if v < 0:
                    edge_v = min([v - e] + rpts_i)
                    vx = sx(edge_v) - 5
                    if vx - vw > px + 2:
                        out.append(text(vx, cy + bh * 0.42 + lfs * 0.35,
                                        vtxt, lfs, INK, "end"))
                else:
                    edge_v = max([v + e] + rpts_i)
                    vx = sx(edge_v) + 5
                    if vx + vw < px + gw + 10:
                        out.append(text(vx, cy + bh * 0.42 + lfs * 0.35,
                                        vtxt, lfs, INK, "start"))
    hbar_refs = []
    if isinstance(b.get("ref_line") or b.get("refline"), dict):
        hbar_refs.append(b.get("ref_line") or b.get("refline"))
    if isinstance(b.get("reflines"), list):
        hbar_refs.extend(r for r in b["reflines"] if isinstance(r, dict))
    for ref in hbar_refs:
        rv = ref.get("x", ref.get("value", ref.get("y")))
        if rv is not None:
            rx = sx(_f(rv))
            if px <= rx <= px + gw:
                rc = ref.get("color", "#64748B")
                out.append(line(rx, py, rx, py + gh, rc, 1.3, dash=ref.get("dash", "5 3")))
                if ref.get("label"):
                    rlab = str(ref["label"])
                    rfs = max(10.0, fs - 2)
                    rw = text_width(rlab, rfs)
                    if rx + 4 + rw > px + gw:
                        out.append(rrect(rx - rw - 8, py + 1, rw + 6, rfs + 4, rx=2.5,
                                         fill="#FFFFFF", extra='fill-opacity="0.9"'))
                        out.append(text(rx - 5, py + rfs + 1.5, rlab, rfs, rc, "end", weight="bold"))
                    else:
                        out.append(rrect(rx + 2, py + 1, rw + 6, rfs + 4, rx=2.5,
                                         fill="#FFFFFF", extra='fill-opacity="0.9"'))
                        out.append(text(rx + 5, py + rfs + 1.5, rlab, rfs, rc, "start", weight="bold"))
    if xlab:
        out.append(text_fit(px + gw / 2, py + gh + fs * 2.5, xlab, gw,
                            max(10.0, fs - 1), MUT, "middle"))
    if note:
        out.append(text_fit(x + w / 2, y + h - 3, note, w - 8,
                            max(10.0, fs - 2), MUT, "middle"))
    return "".join(out), h


def _render_scatter(b, x, y, w, h, fs):
    """Numeric XY scatter / log-X dose-response plot (series: [{name, x, y, err?, labels?}])."""
    series = b.get("series", [])
    colors = b.get("colors") or [SERIES[i % len(SERIES)] for i in range(len(series))]
    connect = bool(b.get("connect"))
    lh, legend_svg = 0.0, ""
    if b.get("legend", len(series) > 1) and series:
        legend_svg, lh = _legend(
            x, y + fs, w,
            [(s.get("name", f"S{i+1}"), colors[i % len(colors)],
              "line" if connect else "dot",
              MARKERS[i % len(MARKERS)], DASHES[i % len(DASHES)] if connect else None)
             for i, s in enumerate(series)],
            max(10.0, fs - 1))
    xs_all = [_f(v) for s in series for v in s.get("x", [])] or [0.0, 1.0]
    ys_all = []
    for s in series:
        yv = [_f(v) for v in s.get("y", [])]
        ev = [_f(e) for e in (s.get("err") or [])]
        for i, v in enumerate(yv):
            e = ev[i] if i < len(ev) else 0.0
            ys_all.extend([v - e, v + e])
    if not ys_all:
        ys_all = [0.0, 1.0]
    use_xlog = bool(b.get("xlog")) and min(xs_all) > 0
    use_ylog = bool(b.get("ylog")) and min(ys_all) > 0
    if use_xlog:
        xlo_c = _f(b["xmin"]) if (b.get("xmin") is not None and _f(b["xmin"]) > 0) else min(xs_all)
        xhi_c = _f(b["xmax"]) if (b.get("xmax") is not None and _f(b["xmax"]) > 0) else max(xs_all)
        xticks, xlo, xhi = _log_ticks(xlo_c, xhi_c)
    else:
        xspan = max(max(xs_all) - min(xs_all), 1e-6)
        xlo_raw = _f(b["xmin"]) if b.get("xmin") is not None else min(xs_all) - xspan * 0.06
        xhi_raw = _f(b["xmax"]) if b.get("xmax") is not None else max(xs_all) + xspan * 0.06
        if b.get("xmin") is None and min(xs_all) >= 0 and xlo_raw < 0:
            xlo_raw = 0.0
        xticks = nice_ticks(xlo_raw, xhi_raw, 5)
        xlo = _f(b["xmin"]) if b.get("xmin") is not None else xticks[0]
        xhi = _f(b["xmax"]) if b.get("xmax") is not None else xticks[-1]
        xticks = [t for t in xticks if xlo - 1e-6 <= t <= xhi + 1e-6] or [xlo, xhi]
    if use_ylog:
        ylo_c = _f(b["ymin"]) if (b.get("ymin") is not None and _f(b["ymin"]) > 0) else min(ys_all)
        yhi_c = _f(b["ymax"]) if (b.get("ymax") is not None and _f(b["ymax"]) > 0) else max(ys_all)
        yticks, ylo, yhi = _log_ticks(ylo_c, yhi_c)
    else:
        yspan = max(max(ys_all) - min(ys_all), 1e-6)
        ylo_raw = _f(b["ymin"]) if b.get("ymin") is not None else min(ys_all) - yspan * 0.08
        yhi_raw = _f(b["ymax"]) if b.get("ymax") is not None else max(ys_all) + yspan * 0.10
        if b.get("ymin") is None and min(ys_all) >= 0 and ylo_raw < 0:
            ylo_raw = 0.0
        yticks, ylo, yhi = _bound_axis_ticks(
            min(ys_all), max(ys_all), ylo_raw, yhi_raw, b,
            str(b.get("ylabel", "")), str(b.get("value_suffix", "")),
            has_top_annot=False,
        )
    fmt_x = _fmt_log_tick if use_xlog else _fmt_num
    fmt_y = _fmt_log_tick if use_ylog else _fmt_num
    maxtw = max((text_width(fmt_y(t), max(10.0, fs - 1)) for t in yticks), default=20.0)
    left = (28.0 + maxtw if b.get("ylabel") else 10.0 + maxtw)
    note = str(b.get("note", "")).strip()
    xlab = str(b.get("xlabel", "")).strip()
    bot = fs * 1.5 + (fs * 1.4 if xlab else 0) + (fs * 1.25 if note else 0) + 4
    px, py = x + left, y + lh + 6
    gw = max(60.0, w - left - 10)
    gh = max(60.0, h - lh - 6 - bot)

    def sx(v):
        if use_xlog:
            lx0, lx1 = math.log10(max(xlo, 1e-12)), math.log10(max(xhi, 1e-12))
            return px + (math.log10(max(v, xlo)) - lx0) / max(lx1 - lx0, 1e-9) * gw
        return px + (v - xlo) / max(xhi - xlo, 1e-9) * gw

    def sy(v):
        if use_ylog:
            ly0, ly1 = math.log10(max(ylo, 1e-12)), math.log10(max(yhi, 1e-12))
            return py + gh - (math.log10(max(v, ylo)) - ly0) / max(ly1 - ly0, 1e-9) * gh
        return py + gh - (v - ylo) / max(yhi - ylo, 1e-9) * gh

    out = [legend_svg]
    for t in yticks:
        ty = sy(t)
        out.append(line(px, ty, px + gw, ty, GRID, 1.0))
        out.append(text(px - 6, ty + (fs - 1) * 0.35, fmt_y(t),
                        max(10.0, fs - 1), MUT, "end"))
    for ti, t in enumerate(xticks):
        tx = sx(t)
        out.append(line(tx, py, tx, py + gh, GRID_MINOR, 0.9))
        anc = "start" if ti == 0 else ("end" if ti == len(xticks) - 1 else "middle")
        out.append(text(tx, py + gh + fs * 1.25, fmt_x(t),
                        max(10.0, fs - 1), MUT, anc))
    out.append(line(px, py + gh, px + gw, py + gh, "#94A3B8", 1.3))
    out.append(line(px, py, px, py + gh, "#94A3B8", 1.3))
    if not use_xlog and xlo < 0 < xhi:
        out.append(line(sx(0.0), py, sx(0.0), py + gh, "#94A3B8", 1.0, dash="3 3"))
    if not use_ylog and ylo < 0 < yhi:
        out.append(line(px, sy(0.0), px + gw, sy(0.0), "#94A3B8", 1.0, dash="3 3"))

    # Optional reference lines (dict or list of dicts with x and/or y/value)
    raw_refs = b.get("ref_line") or b.get("refline") or b.get("reflines")
    refs = raw_refs if isinstance(raw_refs, list) else ([raw_refs] if isinstance(raw_refs, dict) else [])
    placed_sc = []  # [(x0, y0, x1, y1)] for collision-free scatter labels
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        rc = ref.get("color", "#64748B")
        rdash = ref.get("dash", "5 3")
        rfs = max(10.0, fs - 2)
        if ref.get("y") is not None or (ref.get("value") is not None and ref.get("x") is None):
            ry = sy(float(ref.get("y", ref.get("value"))))
            if py <= ry <= py + gh:
                out.append(line(px, ry, px + gw, ry, rc, 1.3, dash=rdash))
                if ref.get("label"):
                    rl = str(ref["label"])
                    rw = text_width(rl, rfs)
                    out.append(text(px + gw - 3, ry - 4, rl, rfs, rc, "end", weight="bold"))
                    placed_sc.append((px + gw - 3 - rw, ry - 4 - rfs, px + gw - 3, ry - 2))
        if ref.get("x") is not None:
            rx = sx(float(ref["x"]))
            if px <= rx <= px + gw:
                out.append(line(rx, py, rx, py + gh, rc, 1.3, dash=rdash))
                if ref.get("label") and ref.get("y") is None:
                    rl = str(ref["label"])
                    rw = text_width(rl, rfs)
                    if rx + 4 + rw > px + gw:
                        out.append(text(rx - 4, py + 12, rl, rfs, rc, "end", weight="bold"))
                        placed_sc.append((rx - 4 - rw, py + 2, rx - 4, py + 14))
                    else:
                        out.append(text(rx + 4, py + 12, rl, rfs, rc, "start", weight="bold"))
                        placed_sc.append((rx + 4, py + 2, rx + 4 + rw, py + 14))

    # Optional OLS linear trend line + R^2 badge
    if b.get("trend") and len(xs_all) >= 2:
        n_tr = min(len(xs_all), len(ys_all))
        mx_t = sum(xs_all[:n_tr]) / n_tr
        my_t = sum(ys_all[:n_tr]) / n_tr
        sxx = sum((xv - mx_t) ** 2 for xv in xs_all[:n_tr])
        syy = sum((yv - my_t) ** 2 for yv in ys_all[:n_tr])
        sxy = sum((xs_all[i] - mx_t) * (ys_all[i] - my_t) for i in range(n_tr))
        if sxx > 1e-12:
            slp = sxy / sxx
            icp = my_t - slp * mx_t
            r2 = (sxy * sxy) / (sxx * syy) if syy > 1e-12 else 1.0
            xa, xb = min(xs_all), max(xs_all)
            ya, yb = max(ylo, min(yhi, slp * xa + icp)), max(ylo, min(yhi, slp * xb + icp))
            out.append(line(sx(xa), sy(ya), sx(xb), sy(yb), "#475569", 1.5, dash="6 3"))
            rtxt = f"R² = {r2:.2f}"
            rfs = max(10.0, fs - 2)
            rw = text_width(rtxt, rfs)
            out.append(text(px + gw - 4, py + 13, rtxt, rfs, INK2, "end", weight="bold"))
            placed_sc.append((px + gw - 4 - rw, py + 2, px + gw - 4, py + 15))

    for si, s in enumerate(series):
        col = colors[si % len(colors)]
        mk = MARKERS[si % len(MARKERS)]
        dsh = DASHES[si % len(DASHES)] if connect else None
        xs, ys = s.get("x", []), s.get("y", [])
        errs = s.get("err") or []
        labs = s.get("labels", [])
        n_pts = min(len(xs), len(ys))
        pts_xy = [(sx(_f(xs[i])), sy(_f(ys[i]))) for i in range(n_pts)]
        if connect and len(pts_xy) >= 2:
            pl = " ".join(f"{a:.1f},{c:.1f}" for a, c in pts_xy)
            d_attr = f' stroke-dasharray="{dsh}"' if dsh else ""
            out.append(f'<polyline points="{pl}" fill="none" stroke="{col}" stroke-width="2.2"{d_attr}/>')
        for i in range(n_pts):
            xv, yv = _f(xs[i]), _f(ys[i])
            cx, cy = pts_xy[i]
            e = _f(errs[i]) if i < len(errs) else 0.0
            if e > 0:
                ylo_e = max(ylo, yv - e) if use_ylog else (yv - e)
                out.append(line(cx, sy(yv + e), cx, sy(ylo_e), col, 1.3))
                for ey_v in (sy(yv + e), sy(ylo_e)):
                    out.append(line(cx - 3.5, ey_v, cx + 3.5, ey_v, col, 1.3))
            out.append(marker_shape(cx, cy, 4.4, col, mk))
            if i < len(labs) and labs[i]:
                lb = str(labs[i])
                lfs = max(10.0, fs - 2)
                lw = text_width(lb, lfs)
                # Try 4 quadrants (NE, NW, SE, SW) to avoid label collisions
                cands = [
                    (cx + 6, cy - 4, "start"),
                    (cx - 6, cy - 4, "end"),
                    (cx + 6, cy + lfs + 2, "start"),
                    (cx - 6, cy + lfs + 2, "end"),
                ]
                chosen_l = None
                for lx, ly, anc in cands:
                    bx0 = lx if anc == "start" else lx - lw
                    bx1 = bx0 + lw
                    by0, by1 = ly - lfs * 0.85, ly + lfs * 0.25
                    if bx0 < px + 1 or bx1 > x + w - 2 or by0 < py + 1 or by1 > py + gh - 1:
                        continue
                    if any(bx0 < rx1 + 2 and bx1 > rx0 - 2 and by0 < ry1 + 2 and by1 > ry0 - 2
                           for rx0, ry0, rx1, ry1 in placed_sc):
                        continue
                    chosen_l = (lx, ly, anc, (bx0, by0, bx1, by1))
                    break
                if chosen_l:
                    lx, ly, anc, lbox = chosen_l
                    placed_sc.append(lbox)
                    out.append(text(lx, ly, lb, lfs, INK2, anc))

    if b.get("ylabel"):
        yl_raw = str(b["ylabel"])
        yl_fs = fit_font(yl_raw, max(60.0, gh - 4), max(10.0, fs - 1), 10.0)
        ylx, yly = x + 11.0, py + gh / 2
        out.append(f'<text x="{ylx:.1f}" y="{yly:.1f}" font-size="{yl_fs:.1f}" '
                   f'fill="{MUT}" text-anchor="middle" '
                   f'transform="rotate(-90 {ylx:.1f} {yly:.1f})">{esc(yl_raw)}</text>')
    if xlab:
        out.append(text_fit(px + gw / 2, py + gh + fs * 2.5, xlab, gw,
                            max(10.0, fs - 1), MUT, "middle"))
    if note:
        out.append(text_fit(x + w / 2, y + h - 3, note, w - 8,
                            max(10.0, fs - 2), MUT, "middle"))
    return "".join(out), h


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _render_paired(b, x, y, w, h, fs):
    """Paired before-after / slope comparison chart (connects matched samples + group means)."""
    raw_series = b.get("series", [])
    pairs = b.get("pairs")
    xlabels = [str(lb) for lb in b.get("xlabels", [])]
    conds = []
    if isinstance(pairs, list) and pairs and isinstance(pairs[0], list):
        nc = len(pairs[0])
        for ci in range(nc):
            cn = xlabels[ci] if ci < len(xlabels) else f"Cond {ci+1}"
            conds.append((cn, [_f(row[ci]) for row in pairs if ci < len(row) and row[ci] is not None]))
    elif len(raw_series) >= 2 and all(isinstance(s, dict) and s.get("values") for s in raw_series):
        for ci, s in enumerate(raw_series):
            cn = xlabels[ci] if ci < len(xlabels) else str(s.get("name", f"Cond {ci+1}"))
            conds.append((cn, [_f(v) for v in s.get("values", []) if v is not None]))
    elif len(raw_series) == 1 and isinstance(raw_series[0].get("points"), list):
        pts_l = raw_series[0]["points"]
        for ci, grp in enumerate(pts_l):
            if isinstance(grp, list):
                cn = xlabels[ci] if ci < len(xlabels) else f"Cond {ci+1}"
                conds.append((cn, [_f(v) for v in grp if v is not None]))
    if len(conds) < 2:
        return text(x + 4, y + fs, "Paired chart requires >=2 conditions", fs, MUT), fs * 2

    colors = b.get("colors") or [SERIES[i % len(SERIES)] for i in range(len(conds))]
    allv = [v for _, vs in conds for v in vs] or [0.0, 1.0]
    lo_v, hi_v = min(allv), max(allv)
    span0 = max(hi_v - lo_v, 1e-6)
    sigs = b.get("sig", [])
    has_sig = bool(sigs)
    hi_pad = hi_v + span0 * (0.28 if has_sig else 0.14)
    lo_pad = lo_v - span0 * 0.10
    if lo_v >= 0 and lo_pad < 0:
        lo_pad = 0.0
    ticks, vlo, vhi = _bound_axis_ticks(
        lo_v, hi_v, lo_pad, hi_pad, b,
        str(b.get("ylabel", "")), str(b.get("value_suffix", "")),
        has_top_annot=has_sig,
    )
    maxtw = max((text_width(_fmt_num(t), max(10.0, fs - 1)) for t in ticks), default=20.0)
    left = (28.0 + maxtw if b.get("ylabel") else 10.0 + maxtw)
    note = str(b.get("note", "")).strip()
    xlab = str(b.get("xlabel", "")).strip()
    bot = fs * 1.6 + (fs * 1.35 if xlab else 0) + (fs * 1.25 if note else 0) + 6
    px, py = x + left, y + 10
    gw = max(60.0, w - left - 12)
    gh = max(60.0, h - 10 - bot)

    def sy(v):
        return py + gh - (v - vlo) / max(vhi - vlo, 1e-9) * gh

    out = []
    for i, t in enumerate(ticks):
        ty = sy(t)
        if i > 0:
            tm = (ticks[i - 1] + t) / 2
            out.append(line(px, sy(tm), px + gw, sy(tm), GRID_MINOR, 0.8))
        out.append(line(px, ty, px + gw, ty, GRID, 1.0))
        out.append(text(px - 6, ty + (fs - 1) * 0.35, _fmt_num(t),
                        max(10.0, fs - 1), MUT, "end"))
    out.append(line(px, py + gh, px + gw, py + gh, "#94A3B8", 1.3))
    out.append(line(px, py, px, py + gh, "#94A3B8", 1.3))

    nc = len(conds)
    slot = gw / nc
    xs_c = [px + slot * (ci + 0.5) for ci in range(nc)]
    n_pairs = min(len(vs) for _, vs in conds)
    for pi in range(n_pairs):
        for ci in range(nc - 1):
            out.append(line(xs_c[ci], sy(conds[ci][1][pi]), xs_c[ci + 1], sy(conds[ci + 1][1][pi]),
                            "#94A3B8", 1.25, extra='stroke-opacity="0.72"'))
    for ci, (cname, vs) in enumerate(conds):
        col = colors[ci % len(colors)]
        cx = xs_c[ci]
        for v in vs:
            out.append(f'<circle cx="{cx:.1f}" cy="{sy(v):.1f}" r="4.0" '
                       f'fill="{col}" fill-opacity="0.86" stroke="#FFFFFF" stroke-width="1.1"/>')
        if vs:
            mv = sum(vs) / len(vs)
            out.append(line(cx - 15, sy(mv), cx + 15, sy(mv), INK, 2.6))
        out.append(text_fit(cx, py + gh + fs * 1.25, cname, slot * 0.92,
                            max(10.0, fs - 1), INK2, "middle", weight="bold"))

    for sg in sigs:
        try:
            g1, g2 = int(sg["x1"]), int(sg["x2"])
            sx1, sx2 = xs_c[max(0, min(nc - 1, g1))], xs_c[max(0, min(nc - 1, g2))]
            by = sy(float(sg["y"])) if "y" in sg else max(py + 14, sy(hi_v) - 16)
            out.append(line(sx1, by + 5, sx1, by, INK2, 1.1))
            out.append(line(sx1, by, sx2, by, INK2, 1.1))
            out.append(line(sx2, by, sx2, by + 5, INK2, 1.1))
            out.append(text((sx1 + sx2) / 2, by - 3.5, str(sg.get("label", "*")),
                            max(10.0, fs - 2), INK, "middle", weight="bold"))
        except Exception:
            continue

    if b.get("ylabel"):
        yl_raw = str(b["ylabel"])
        yl_fs = fit_font(yl_raw, max(60.0, gh - 4), max(10.0, fs - 1), 10.0)
        ylx, yly = x + 11.0, py + gh / 2
        out.append(f'<text x="{ylx:.1f}" y="{yly:.1f}" font-size="{yl_fs:.1f}" '
                   f'fill="{MUT}" text-anchor="middle" '
                   f'transform="rotate(-90 {ylx:.1f} {yly:.1f})">{esc(yl_raw)}</text>')
    if xlab:
        out.append(text_fit(px + gw / 2, py + gh + fs * 2.55, xlab, gw,
                            max(10.0, fs - 1), MUT, "middle"))
    if note:
        out.append(text_fit(x + w / 2, y + h - 3, note, w - 8,
                            max(10.0, fs - 2), MUT, "middle"))
    return "".join(out), h


def _expand_volcano_brief(b: dict) -> dict:
    """Auto-partition flat volcano points/arrays into Up / Down / NS colorblind-safe series + cutoffs."""
    if b.get("series"):
        return b
    fc_t = abs(_f(b.get("fc_thresh", 1.0), 1.0))
    p_t = _f(b.get("p_thresh", 1.301), 1.301)
    pts = b.get("points")
    xs, ys, lbs = [], [], []
    if isinstance(pts, list) and pts and isinstance(pts[0], dict):
        for pt in pts:
            if pt.get("x") is not None and pt.get("y") is not None:
                xs.append(_f(pt["x"]))
                ys.append(_f(pt["y"]))
                lbs.append(str(pt.get("label", "")))
    elif b.get("x") and b.get("y"):
        xs = [_f(v) for v in b["x"]]
        ys = [_f(v) for v in b["y"]]
        raw_l = b.get("labels") or []
        lbs = [str(raw_l[i]) if i < len(raw_l) else "" for i in range(min(len(xs), len(ys)))]
    if not xs:
        return b
    up = {"name": "Up", "x": [], "y": [], "labels": []}
    dn = {"name": "Down", "x": [], "y": [], "labels": []}
    ns = {"name": "NS", "x": [], "y": [], "labels": []}
    for xv, yv, lb in zip(xs, ys, lbs):
        if yv >= p_t and xv >= fc_t:
            up["x"].append(xv); up["y"].append(yv); up["labels"].append(lb)
        elif yv >= p_t and xv <= -fc_t:
            dn["x"].append(xv); dn["y"].append(yv); dn["labels"].append(lb)
        else:
            ns["x"].append(xv); ns["y"].append(yv); ns["labels"].append(lb)
    ser, cols = [], []
    if ns["x"]:
        ns["name"] = f"NS ({len(ns['x'])})"
        ser.append(ns); cols.append("#94A3B8")
    if dn["x"]:
        dn["name"] = f"Down ({len(dn['x'])})"
        ser.append(dn); cols.append("#0072B2")
    if up["x"]:
        up["name"] = f"Up ({len(up['x'])})"
        ser.append(up); cols.append("#D55E00")
    nb = dict(b)
    nb["series"] = ser
    nb["colors"] = b.get("colors") or cols
    nb.setdefault("xlabel", "log2 Fold Change")
    nb.setdefault("ylabel", "-log10(p)")
    refs = list(b.get("reflines") or [])
    if not refs:
        refs = [
            {"x": fc_t, "color": "#94A3B8", "dash": "4 3"},
            {"x": -fc_t, "color": "#94A3B8", "dash": "4 3"},
            {"y": p_t, "label": "p=0.05" if abs(p_t - 1.301) < 0.05 else f"-log10p={p_t:g}",
             "color": "#64748B", "dash": "4 3"},
        ]
    nb["reflines"] = refs
    return nb


def _normalize_chart_kind(b: dict) -> tuple[str, dict]:
    raw = str(b.get("kind", "bar")).strip().lower().replace("-", "_").replace(" ", "_")
    if raw in ("bar", "grouped_bar", "bar_chart", "column", "columns", "bars", "hist", "histogram"):
        return "bar", b
    if raw in ("hbar", "horizontal_bar", "barh", "forest", "forest_plot"):
        return "hbar", b
    if raw in ("stacked", "stacked_bar", "stacked_bars", "composition"):
        return "stacked", b
    if raw in ("line", "line_chart", "curve", "timecourse", "trajectory", "dose_response"):
        return "line", b
    if raw in ("step", "km", "kaplan_meier", "survival", "survival_curve"):
        nb = dict(b)
        nb.setdefault("step", True)
        return "line", nb
    if raw in ("dot", "dotplot", "strip", "stripplot", "lollipop", "beeswarm"):
        return "dot", b
    if raw in ("box", "boxplot", "box_plot", "whisker", "violin"):
        return "box", b
    if raw in ("paired", "slope", "slopegraph", "before_after"):
        return "paired", b
    if raw in ("volcano", "volcano_plot"):
        return "scatter", _expand_volcano_brief(b)
    if raw in ("scatter", "xy", "correlation", "corr"):
        return "scatter", b
    if raw in ("heatmap", "matrix", "corr_matrix"):
        return "heatmap", b
    if raw in ("heatmap_diverging", "diverging_heatmap", "diverging"):
        nb = dict(b)
        nb.setdefault("ramp", "diverging")
        return "heatmap", nb
    if b.get("rows") or (isinstance(b.get("values"), list) and b["values"]
                         and isinstance(b["values"][0], list)):
        return "heatmap", b
    if any(isinstance(s, dict) and "x" in s and "y" in s for s in b.get("series", [])):
        return "scatter", b
    return "bar", b


def render_chart(b, x, y, w, h, fs=12):
    title_svg = ""
    chart_title = str(b.get("title", "")).strip()
    if chart_title:
        tfs = max(11.0, fs)
        title_svg = text_fit(x + 2, y + tfs * 0.95, chart_title, w - 4, tfs, INK, weight="bold")
        th = tfs * 1.45
        y, h = y + th, max(80.0, h - th)

    kind, b = _normalize_chart_kind(b)
    if kind == "heatmap":
        s_svg, used = _render_heatmap(b, x, y, w, h, fs)
        return title_svg + s_svg, used + (tfs * 1.45 if chart_title else 0.0)
    if kind == "hbar":
        s_svg, used = _render_hbar(b, x, y, w, h, fs)
        return title_svg + s_svg, used + (tfs * 1.45 if chart_title else 0.0)
    if kind == "paired":
        s_svg, used = _render_paired(b, x, y, w, h, fs)
        return title_svg + s_svg, used + (tfs * 1.45 if chart_title else 0.0)
    if kind == "scatter":
        s_svg, used = _render_scatter(b, x, y, w, h, fs)
        return title_svg + s_svg, used + (tfs * 1.45 if chart_title else 0.0)

    series = b.get("series", [])
    xlabels = [str(lb) for lb in b.get("xlabels", [])]
    colors = b.get("colors") or [SERIES[i % len(SERIES)] for i in range(len(series))]
    nsv = max(len(series), 1)
    lh, legend_svg = 0.0, ""
    if b.get("legend", True) and series:
        entries = []
        for i, s in enumerate(series):
            is_st_leg = (kind == "line") and bool(b.get("step") or s.get("step"))
            mk = None if is_st_leg else MARKERS[i % len(MARKERS)]
            dsh = DASHES[i % len(DASHES)] if kind == "line" else None
            entries.append((s.get("name", f"S{i+1}"), colors[i % len(colors)],
                            "line" if kind == "line" else ("dot" if kind == "dot" else "rect"),
                            mk, dsh))
        legend_svg, lh = _legend(x, y + fs, w, entries, max(10.0, fs - 1))

    # Determine data bounds cleanly
    if kind == "stacked":
        ng = max((len(s.get("values", [])) for s in series), default=1)
        totals = [sum(_f(s.get("values", [0] * ng)[i])
                      for s in series if i < len(s.get("values", [])))
                  for i in range(ng)]
        hi_v = max(totals) if totals else 1.0
        lo_v = 0.0
    else:
        allv = [_f(v) for s in series for v in s.get("values", [])] or [0.0, 1.0]
        all_hi = []
        all_lo = []
        for s in series:
            vals = s.get("values", [])
            err = s.get("err") or []
            pts_list = s.get("points") or []
            n_items = max(len(vals), len(pts_list), len(s.get("q3") or []))
            for i in range(n_items):
                if i < len(vals) and vals[i] is not None:
                    fv = _f(vals[i])
                    e = _f(err[i]) if i < len(err) else 0.0
                    all_hi.append(fv + e)
                    all_lo.append(fv - e)
                for k_ext in ("q1", "q3", "low", "high", "min", "max", "ci_lo", "ci_hi"):
                    arr = s.get(k_ext) or []
                    if i < len(arr) and arr[i] is not None:
                        all_hi.append(_f(arr[i]))
                        all_lo.append(_f(arr[i]))
                if i < len(pts_list) and isinstance(pts_list[i], list):
                    for pv in pts_list[i]:
                        if pv is not None:
                            fpv = _f(pv)
                            all_hi.append(fpv)
                            all_lo.append(fpv)
        hi_v = max(all_hi) if all_hi else max(allv)
        pos_vals = [x for x in all_lo if x > 0]
        if b.get("ylog") and pos_vals and all(_f(v) > 0 for s in series for v in (s.get("values") or []) if v is not None):
            lo_v = min(pos_vals)
        else:
            lo_v = min(min(all_lo), 0.0) if kind == "bar" else (min(all_lo) if all_lo else 0.0)
            if kind in ("line", "dot", "box"):
                span = max(hi_v - lo_v, 1e-6)
                lo_v = lo_v - span * 0.08
                if all_lo and min(all_lo) >= 0 and lo_v < 0:
                    lo_v = 0.0

    sigs = b.get("sig") or []
    sig_ys = [_f(sg["y"]) for sg in sigs if isinstance(sg, dict) and "y" in sg]
    if sig_ys:
        hi_v = max(hi_v, max(sig_ys))
    has_sig = bool(sigs) or bool(b.get("sig_points"))
    if sig_ys:
        head = 1.10
    elif has_sig:
        head = 1.24 + 0.06 * max(0, len(sigs) - 1)
    else:
        head = 1.15 if b.get("value_labels") else 1.08
    use_ylog = bool(b.get("ylog")) and kind in ("bar", "line", "dot", "box") and all(
        _f(v) > 0 for s in series for v in (s.get("values") or []) if v is not None
    ) and lo_v > 0
    cart_refs = []
    if isinstance(b.get("ref_line") or b.get("refline"), dict):
        cart_refs.append(b.get("ref_line") or b.get("refline"))
    if isinstance(b.get("reflines"), list):
        cart_refs.extend(r for r in b["reflines"] if isinstance(r, dict))
    if use_ylog:
        ref_pos = [_f(r.get("y", r.get("value"))) for r in cart_refs
                   if r.get("y", r.get("value")) is not None and _f(r.get("y", r.get("value"))) > 0]
        lo_log_base = min([lo_v] + ref_pos) if ref_pos else lo_v
        yl_c = _f(b["ymin"]) if (b.get("ymin") is not None and _f(b["ymin"]) > 0) else lo_log_base
        yh_c = _f(b["ymax"]) if (b.get("ymax") is not None and _f(b["ymax"]) > 0) else hi_v * (1.8 if has_sig else 1.2)
        ticks, vlo, vhi = _log_ticks(yl_c, yh_c)
    else:
        span0 = max(hi_v - lo_v, 1e-6)
        hi_pad = hi_v + span0 * (head - 1.0)
        lo_pad = lo_v - (span0 * 0.10 if lo_v < 0 and b.get("value_labels") else 0.0)
        ticks, vlo, vhi = _bound_axis_ticks(
            lo_v, hi_v, lo_pad, hi_pad, b,
            str(b.get("ylabel", "")), str(b.get("value_suffix", "")),
            has_top_annot=(has_sig or bool(b.get("value_labels"))),
        )

    fmt_y = _fmt_log_tick if use_ylog else _fmt_num
    maxtw = max((text_width(fmt_y(t), max(10.0, fs - 1)) for t in ticks), default=20.0)
    # Dedicated gutter so rotated ylabel NEVER collides with tick numbers
    left = (28.0 + maxtw if b.get("ylabel") else 10.0 + maxtw)
    note = str(b.get("note", "")).strip()
    xlab = str(b.get("xlabel", "")).strip()

    # Check if x-labels need 2 wrapped lines
    nx = max(len(xlabels), max((max(len(s.get("values", [])), len(s.get("points") or []))
                                for s in series), default=1), 1)
    gw = max(60.0, w - left - 8)
    slot = gw / nx
    x_wrapped = [wrap_text(lb, max(10.0, fs - 1), slot * 0.94)[:2] for lb in xlabels]
    max_xl = max((len(lines) for lines in x_wrapped), default=1) if xlabels else 0
    x_h = (max_xl * (fs * 1.18) + 6) if xlabels else fs * 0.5
    bot = x_h + (fs * 1.35 if xlab else 0) + (fs * 1.25 if note else 0) + 4

    px, py = x + left, y + lh + 8
    gh = max(60.0, h - lh - 8 - bot)

    def sy(v):
        if use_ylog:
            ly0, ly1 = math.log10(max(vlo, 1e-12)), math.log10(max(vhi, 1e-12))
            return py + gh - (math.log10(max(v, vlo)) - ly0) / max(ly1 - ly0, 1e-9) * gh
        return py + gh - (v - vlo) / max(vhi - vlo, 1e-9) * gh

    out = [legend_svg]
    # Gridlines + y-ticks
    for i, t in enumerate(ticks):
        ty = sy(t)
        if i > 0 and not use_ylog:
            tm = (ticks[i - 1] + t) / 2
            out.append(line(px, sy(tm), px + gw, sy(tm), GRID_MINOR, 0.8))
        out.append(line(px, ty, px + gw, ty, GRID, 1.0))
        out.append(text(px - 6, ty + (fs - 1) * 0.35, fmt_y(t),
                        max(10.0, fs - 1), MUT, "end"))

    # Axes (+ crisp zero baseline when data crosses 0)
    out.append(line(px, py + gh, px + gw, py + gh, "#94A3B8", 1.3))
    out.append(line(px, py, px, py + gh, "#94A3B8", 1.3))
    if vlo < 0 < vhi:
        out.append(line(px, sy(0.0), px + gw, sy(0.0), "#64748B", 1.2))

    # X-labels (wrapped cleanly up to 2 lines)
    for gi, lns in enumerate(x_wrapped):
        cx = px + slot * (gi + 0.5)
        for li, ln in enumerate(lns):
            out.append(text_fit(cx, py + gh + fs * 1.15 + li * (fs * 1.15),
                                ln, slot * 0.94, max(10.0, fs - 1), INK2, "middle"))

    # Data marks (clamped Prism/Nature bar proportions + tracked bar rects for zero-collision reflines)
    bw = min((slot * 0.70) / nsv, 54.0)
    group_w = bw * nsv
    bar_rects = []  # [(x0, y0, x1, y1)]
    vsuf = str(b.get("value_suffix", ""))
    if kind == "stacked":
        bar_w = min(slot * 0.56, 62.0)
        bases = [0.0] * nx
        for si, s in enumerate(series):
            col = colors[si % len(colors)]
            for i, v in enumerate(s.get("values", [])):
                v = float(v)
                y_bot, y_top = sy(bases[i]), sy(bases[i] + v)
                bx = px + slot * (i + 0.5) - bar_w / 2
                bh_st = max(y_bot - y_top, 0.5)
                bar_rects.append((bx, y_top, bx + bar_w, y_top + bh_st))
                out.append(rrect(bx, y_top, bar_w, bh_st,
                                 rx=1.5, fill=col, stroke="#FFFFFF", sw=0.8))
                if b.get("value_labels") and (y_bot - y_top) > fs * 1.1:
                    fg = "#FFFFFF" if luminance(col) < 0.36 else INK
                    out.append(text(bx + bar_w / 2, (y_bot + y_top) / 2 + (fs - 2) * 0.35,
                                    _fmt_num(v) + vsuf, max(10.0, fs - 2), fg, "middle",
                                    weight="bold"))
                bases[i] += v
    else:
        placed_line_y = {}  # x_idx -> list of placed label y coords
        for si, s in enumerate(series):
            col = colors[si % len(colors)]
            vals = [_f(v) for v in s.get("values", [])]
            err = [_f(e) for e in (s.get("err") or [])]
            mk = MARKERS[si % len(MARKERS)]
            dsh = DASHES[si % len(DASHES)] if kind == "line" else None

            if kind == "line":
                pts = [(px + slot * (i + 0.5), sy(v)) for i, v in enumerate(vals)]
                is_step = bool(b.get("step") or s.get("step"))
                ci_lo = s.get("ci_lo") or []
                ci_hi = s.get("ci_hi") or []
                if (b.get("band") or s.get("band")) and len(pts) >= 2 and (err or (ci_lo and ci_hi)):
                    if ci_lo and ci_hi:
                        up = [(px + slot * (i + 0.5), sy(_f(ci_hi[i]) if i < len(ci_hi) else vals[i]))
                              for i in range(len(vals))]
                        dn = [(px + slot * (i + 0.5), sy(_f(ci_lo[i]) if i < len(ci_lo) else vals[i]))
                              for i in range(len(vals) - 1, -1, -1)]
                    else:
                        up = [(px + slot * (i + 0.5), sy(vals[i] + (err[i] if i < len(err) else 0.0)))
                              for i in range(len(vals))]
                        dn = [(px + slot * (i + 0.5), sy(vals[i] - (err[i] if i < len(err) else 0.0)))
                              for i in range(len(vals) - 1, -1, -1)]
                    poly = " ".join(f"{a:.1f},{c:.1f}" for a, c in up + dn)
                    out.append(f'<polygon points="{poly}" fill="{col}" fill-opacity="0.16" stroke="none"/>')
                if is_step and len(pts) >= 2:
                    spts = [pts[0]]
                    for k in range(1, len(pts)):
                        spts.append((pts[k][0], pts[k - 1][1]))
                        spts.append(pts[k])
                    pl = " ".join(f"{a:.1f},{c:.1f}" for a, c in spts)
                else:
                    pl = " ".join(f"{a:.1f},{c:.1f}" for a, c in pts)
                d_attr = f' stroke-dasharray="{dsh}"' if dsh else ""
                out.append(f'<polyline points="{pl}" fill="none" stroke="{col}" '
                           f'stroke-width="2.3"{d_attr}/>')
                for i, e in enumerate(err):
                    if i < len(vals) and e > 0:
                        ex = px + slot * (i + 0.5)
                        out.append(line(ex, sy(vals[i] + e), ex, sy(vals[i] - e), col, 1.3))
                        for sgn in (1, -1):
                            ey = sy(vals[i] + sgn * e)
                            out.append(line(ex - 3.5, ey, ex + 3.5, ey, col, 1.3))
                if is_step:
                    for ci_idx in (s.get("censored") or []):
                        ci_i = int(ci_idx)
                        if 0 <= ci_i < len(pts):
                            cx_c, cy_c = pts[ci_i]
                            # Place censor crosshatch clearly without colliding with vertical step drop
                            out.append(line(cx_c, cy_c - 4.5, cx_c, cy_c + 4.5, col, 1.8))
                            out.append(line(cx_c - 3.0, cy_c, cx_c + 3.0, cy_c, col, 1.4))
                else:
                    for a, c in pts:
                        out.append(marker_shape(a, c, 4.0, col, mk))
                if b.get("value_labels"):
                    lfs = max(10.0, fs - 2)
                    for i, v in enumerate(vals):
                        e = err[i] if i < len(err) else 0.0
                        vy = sy(v + e) - 8
                        used = placed_line_y.setdefault(i, [])
                        if any(abs(vy - uy) < lfs * 1.15 for uy in used):
                            alt = sy(v - e) + lfs + 6
                            if alt < py + gh - 2 and not any(abs(alt - uy) < lfs * 1.15 for uy in used):
                                vy = alt
                            else:
                                vy -= lfs * 1.2
                        if py + 6 < vy < py + gh - 2:
                            used.append(vy)
                            out.append(text(px + slot * (i + 0.5), vy, _fmt_num(v) + vsuf,
                                            lfs, col, "middle", weight="bold"))
            elif kind == "box":
                pts_list = s.get("points") or []
                q1_l, q3_l = s.get("q1") or [], s.get("q3") or []
                lo_l = s.get("low") or s.get("min") or []
                hi_l = s.get("high") or s.get("max") or []
                n_it = max(len(vals), len(pts_list), len(q1_l))
                for i in range(n_it):
                    cx = px + slot * (i + 0.5) - group_w / 2 + si * bw
                    midx = cx + bw * 0.42
                    box_w = min(bw * 0.72, 34.0)
                    bx0 = midx - box_w / 2
                    rpts = sorted(_f(pv) for pv in (pts_list[i] if i < len(pts_list) and isinstance(pts_list[i], list) else []) if pv is not None)
                    if rpts:
                        vlo_b, q1, med, q3, vhi_b = (rpts[0], _quantile(rpts, 0.25),
                                                     _quantile(rpts, 0.50), _quantile(rpts, 0.75), rpts[-1])
                    else:
                        med = vals[i] if i < len(vals) else 0.0
                        e = err[i] if i < len(err) else 0.0
                        q1 = _f(q1_l[i]) if i < len(q1_l) else med - e * 0.65
                        q3 = _f(q3_l[i]) if i < len(q3_l) else med + e * 0.65
                        vlo_b = _f(lo_l[i]) if i < len(lo_l) else med - e * 1.25
                        vhi_b = _f(hi_l[i]) if i < len(hi_l) else med + e * 1.25
                    out.append(line(midx, sy(vhi_b), midx, sy(q3), "#374151", 1.35))
                    out.append(line(midx, sy(q1), midx, sy(vlo_b), "#374151", 1.35))
                    cap_w = box_w * 0.34
                    out.append(line(midx - cap_w, sy(vhi_b), midx + cap_w, sy(vhi_b), "#374151", 1.35))
                    out.append(line(midx - cap_w, sy(vlo_b), midx + cap_w, sy(vlo_b), "#374151", 1.35))
                    y_q3, y_q1 = sy(q3), sy(q1)
                    out.append(f'<rect x="{bx0:.1f}" y="{min(y_q3, y_q1):.1f}" width="{box_w:.1f}" '
                               f'height="{max(abs(y_q1 - y_q3), 2.0):.1f}" rx="2.5" '
                               f'fill="{col}" fill-opacity="0.28" stroke="{col}" stroke-width="1.6"/>')
                    out.append(line(bx0, sy(med), bx0 + box_w, sy(med), INK, 2.2))
                    if rpts:
                        offs = _jitter_offsets(len(rpts), min(box_w * 0.32, 7.5))
                        for pv, dx in zip(rpts, offs):
                            out.append(f'<circle cx="{midx+dx:.1f}" cy="{sy(pv):.1f}" r="2.6" '
                                       f'fill="{col}" fill-opacity="0.88" stroke="#FFFFFF" stroke-width="0.9"/>')
                    if b.get("value_labels"):
                        lfs = max(10.0, fs - 2)
                        vy = sy(vhi_b) - 8
                        if vy > py + 6:
                            out.append(text(midx, vy, _fmt_num(med) + vsuf, lfs, INK, "middle"))
            else:  # bar or dot
                pts_list = s.get("points") or []
                for i, v in enumerate(vals):
                    cx = px + slot * (i + 0.5) - group_w / 2 + si * bw
                    midx = cx + bw * 0.42
                    if kind == "bar":
                        y0, y1 = sy(v), sy(vlo if use_ylog else max(vlo, 0.0))
                        bar_rects.append((cx, min(y0, y1), cx + bw * 0.84, max(y0, y1)))
                        out.append(rrect(cx, min(y0, y1), bw * 0.84, abs(y1 - y0),
                                         rx=2.5, fill=col))
                    else:
                        out.append(marker_shape(midx, sy(v), min(5.5, max(3.8, bw * 0.28)),
                                                col, mk))
                    rpts = [_f(pv) for pv in (pts_list[i] if i < len(pts_list) and isinstance(pts_list[i], list) else []) if pv is not None]
                    if rpts:
                        offs = _jitter_offsets(len(rpts), min(bw * 0.26, 8.0))
                        for pv, dx in zip(rpts, offs):
                            out.append(f'<circle cx="{midx+dx:.1f}" cy="{sy(pv):.1f}" r="2.7" '
                                       f'fill="#FFFFFF" fill-opacity="0.88" stroke="{INK}" stroke-width="1.15"/>')
                    e = err[i] if i < len(err) else 0.0
                    if e > 0:
                        lo_eb = max(vlo, v - e) if use_ylog else (v - e)
                        out.append(line(midx, sy(v + e), midx, sy(lo_eb), "#374151", 1.35))
                        for ey_v in (sy(v + e), sy(lo_eb)):
                            out.append(line(midx - 3.8, ey_v, midx + 3.8, ey_v, "#374151", 1.35))
                    if b.get("value_labels"):
                        lfs = max(10.0, fs - 2)
                        vtxt = _fmt_num(v) + vsuf
                        if v < 0 and kind == "bar":
                            low_v = min([v - e] + rpts)
                            vy = sy(low_v) + lfs + 5
                            if vy < py + gh - 2:
                                out.append(text(midx, vy, vtxt, lfs, INK, "middle"))
                        else:
                            top_v = max([v + e] + rpts)
                            vy = sy(top_v) - 8
                            if vy > py + 6:
                                out.append(text(midx, vy, vtxt, lfs, INK, "middle"))

    # Reference threshold line(s) rendered ABOVE data marks with smart zero-bar-overlap pill placement
    placed_ref_pills = []
    for ref in cart_refs:
        rv = ref.get("y", ref.get("value"))
        if rv is not None:
            ry = sy(_f(rv))
            if py <= ry <= py + gh:
                rc = ref.get("color", "#64748B")
                out.append(line(px, ry, px + gw, ry, rc, 1.35, dash=ref.get("dash", "5 3")))
                if ref.get("label"):
                    rlab = str(ref["label"])
                    rfs = max(10.0, fs - 2)
                    rw = text_width(rlab, rfs)
                    pw_p, ph_p = rw + 6.0, rfs + 4.0
                    cand_xs = [px + gw - pw_p - 2.0, px + 3.0]
                    for gi in range(nx - 1):
                        gx = px + slot * (gi + 1) - pw_p / 2.0
                        cand_xs.append(max(px + 2.0, min(px + gw - pw_p - 2.0, gx)))
                    cand_ys = [max(py + 1.0, ry - ph_p - 2.0)]
                    if ry + ph_p + 3.0 <= py + gh - 1.0:
                        cand_ys.append(ry + 2.5)
                    best_box, best_pen = None, 1e18
                    for py_c in cand_ys:
                        for px_c in cand_xs:
                            bx0, by0, bx1, by1 = px_c, py_c, px_c + pw_p, py_c + ph_p
                            pen = 0.0
                            for rx0, ry0, rx1, ry1 in bar_rects:
                                ovx = max(0.0, min(bx1, rx1) - max(bx0, rx0))
                                ovy = max(0.0, min(by1, ry1) - max(by0, ry0))
                                pen += ovx * ovy
                            for rx0, ry0, rx1, ry1 in placed_ref_pills:
                                ovx = max(0.0, min(bx1 + 2, rx1 + 2) - max(bx0 - 2, rx0 - 2))
                                ovy = max(0.0, min(by1 + 2, ry1 + 2) - max(by0 - 2, ry0 - 2))
                                pen += ovx * ovy * 10.0
                            if pen < best_pen:
                                best_pen = pen
                                best_box = (bx0, by0, bx1, by1)
                    bx0, by0, bx1, by1 = best_box
                    placed_ref_pills.append(best_box)
                    out.append(rrect(bx0, by0, pw_p, ph_p, rx=2.5,
                                     fill="#FFFFFF", extra='fill-opacity="0.93"'))
                    out.append(text(bx0 + pw_p / 2.0, by0 + rfs + 0.5, rlab,
                                    rfs, rc, "middle", weight="bold"))

    # Point-wise significance markers on line/dot/bar: [{"x": 3, "label": "***"}]
    for sp in (b.get("sig_points") or []):
        try:
            xi = int(sp["x"])
            peaks = []
            for s in series:
                sv = s.get("values", [])
                se = s.get("err") or []
                is_st = bool(b.get("step") or s.get("step"))
                if 0 <= xi < len(sv):
                    pk = _f(sv[xi]) + (_f(se[xi]) if xi < len(se) else 0.0)
                    if is_st and xi > 0:
                        pk = max(pk, _f(sv[xi - 1]))
                    peaks.append(pk)
            if peaks:
                py_top = max(py + 12, sy(max(peaks)) - (18 if b.get("value_labels") else 9))
                out.append(text(px + slot * (xi + 0.5), py_top, str(sp.get("label", "*")),
                                max(10.0, fs - 1), INK, "middle", weight="bold"))
        except Exception:
            continue

    # Significance brackets: [{"x1": 0, "x2": 2, "s1": 0, "s2": 1, "label": "p<0.001", "y": 102}]
    placed_brackets = []  # [(sx_min, sx_max, by)]
    for sg in sigs:
        try:
            g1, g2 = float(sg["x1"]), float(sg["x2"])
            if "s1" in sg and kind in ("bar", "dot", "box"):
                sx1 = px + slot * (g1 + 0.5) - group_w / 2 + float(sg["s1"]) * bw + bw * 0.42
            else:
                sx1 = px + slot * (g1 + 0.5)
            if "s2" in sg and kind in ("bar", "dot", "box"):
                sx2 = px + slot * (g2 + 0.5) - group_w / 2 + float(sg["s2"]) * bw + bw * 0.42
            else:
                sx2 = px + slot * (g2 + 0.5)
            s_lo, s_hi = min(sx1, sx2), max(sx1, sx2)
            if "y" in sg:
                by = sy(float(sg["y"]))
            else:
                # Compute true data peak across spanned groups (bars + err + replicate dots)
                i_lo, i_hi = max(0, int(math.floor(min(g1, g2)))), int(math.ceil(max(g1, g2)))
                span_peaks = []
                for s in series:
                    sv = s.get("values", [])
                    se = s.get("err") or []
                    sp_l = s.get("points") or []
                    n_sp = max(len(sv), len(sp_l))
                    for ii in range(i_lo, min(n_sp, i_hi + 1)):
                        cands = []
                        if ii < len(sv) and sv[ii] is not None:
                            cands.append(_f(sv[ii]) + (_f(se[ii]) if ii < len(se) else 0.0))
                        if ii < len(sp_l) and isinstance(sp_l[ii], list):
                            cands.extend(_f(pv) for pv in sp_l[ii] if pv is not None)
                        if cands:
                            span_peaks.append(max(cands))
                base_y = sy(max(span_peaks)) if span_peaks else (py + 24)
                by = base_y - (24.0 if b.get("value_labels") else 14.0)
                while any(not (s_hi < o_lo - 4 or s_lo > o_hi + 4) and abs(by - o_y) < 17.0
                          for o_lo, o_hi, o_y in placed_brackets):
                    by -= 18.0
            by = max(py + 12, min(py + gh - 12, by))
            placed_brackets.append((s_lo, s_hi, by))
            out.append(line(sx1, by + 5, sx1, by, INK2, 1.1))
            out.append(line(sx1, by, sx2, by, INK2, 1.1))
            out.append(line(sx2, by, sx2, by + 5, INK2, 1.1))
            out.append(text((sx1 + sx2) / 2, by - 3.5, str(sg.get("label", "*")),
                            max(10.0, fs - 2), INK, "middle", weight="bold"))
        except Exception:
            continue

    # Rotated Y-axis label safely fitted to chart height inside dedicated left gutter
    if b.get("ylabel"):
        yl_raw = str(b["ylabel"])
        yl_fs = fit_font(yl_raw, max(60.0, gh - 4), max(10.0, fs - 1), 10.0)
        ylx, yly = x + 11.0, py + gh / 2
        out.append(f'<text x="{ylx:.1f}" y="{yly:.1f}" font-size="{yl_fs:.1f}" '
                   f'fill="{MUT}" text-anchor="middle" '
                   f'transform="rotate(-90 {ylx:.1f} {yly:.1f})">{esc(yl_raw)}</text>')
    if xlab:
        out.append(text_fit(px + gw / 2, py + gh + x_h + fs * 1.1, xlab, gw,
                            max(10.0, fs - 1), MUT, "middle"))
    if note:
        out.append(text_fit(x + w / 2, y + h - 3, note, w - 8,
                            max(10.0, fs - 2), MUT, "middle"))
    return title_svg + "".join(out), h + (tfs * 1.45 if chart_title else 0.0)
