#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svgfig.py — scene → 分层可编辑 SVG（显式矢量箭头 + 跨引擎虚线路径 + data-prov 溯源）。仅标准库。"""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sir as sirmod

DEFAULT_FONTS = ("Noto Sans CJK SC, Noto Sans SC, Source Han Sans SC, "
                 "WenQuanYi Zen Hei, DejaVu Sans, Arial, sans-serif")


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _prov_attrs(meta):
    out = ""
    if meta.get("prov"):
        out += ' data-prov="%s"' % _esc(meta["prov"])
    if meta.get("prov_loc"):
        out += ' data-prov-loc="%s"' % _esc(meta["prov_loc"])
    return out


def _trim_end(pts, trim_end=0.0, trim_start=0.0):
    """沿首末段切线微微内缩，防止线帽戳出显式箭头尖端。"""
    pts = [tuple(p) for p in pts]
    if len(pts) < 2:
        return pts
    if trim_end > 0:
        x1, y1 = pts[-2]
        x2, y2 = pts[-1]
        d = math.hypot(x2 - x1, y2 - y1)
        if d > trim_end + 1.0:
            r = (d - trim_end) / d
            pts[-1] = (x1 + (x2 - x1) * r, y1 + (y2 - y1) * r)
    if trim_start > 0:
        x1, y1 = pts[0]
        x2, y2 = pts[1]
        d = math.hypot(x2 - x1, y2 - y1)
        if d > trim_start + 1.0:
            r = trim_start / d
            pts[0] = (x1 + (x2 - x1) * r, y1 + (y2 - y1) * r)
    return pts


def _arrow_poly(p1, p2, color, length=9.5, half_w=4.0):
    """生成从 p1 指向 p2（尖端在 p2）的显式矢量三角形 <polygon>。"""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    d = math.hypot(dx, dy)
    if d < 1e-3:
        return ""
    ux, uy = dx / d, dy / d
    bx, by = p2[0] - ux * length, p2[1] - uy * length
    px, py = -uy * half_w, ux * half_w
    pts = "%.2f,%.2f %.2f,%.2f %.2f,%.2f" % (
        p2[0], p2[1], bx + px, by + py, bx - px, by - py
    )
    return '<polygon points="%s" fill="%s" stroke="none" data-role="arrowhead"/>' % (pts, color)


def _tbar_line(p1, p2, color, half_w=5.5, sw=2.4):
    """生成生物学抑制/阻断平头 T-bar 端帽（垂线段，兼容全部 SVG 渲染引擎）。"""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    d = math.hypot(dx, dy)
    if d < 1e-3:
        return ""
    ux, uy = dx / d, dy / d
    px, py = -uy * half_w, ux * half_w
    cx, cy = p2[0] - ux * 1.5, p2[1] - uy * 1.5
    return '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="%g" stroke-linecap="butt" data-role="tbar"/>' % (
        cx + px, cy + py, cx - px, cy - py, color, sw
    )


def _dashed_path_d(pts, dash_str):
    """把折线按 dash_str 离散成单条 <path d="M... L... M... L..."/>，保证跨所有渲染器显示真实虚线。"""
    try:
        pattern = [max(float(x.strip()), 0.8) for x in str(dash_str).replace(" ", ",").split(",") if x.strip()]
    except Exception:
        pattern = [6.0, 4.0]
    if len(pattern) < 2:
        pattern = [pattern[0], pattern[0]] if pattern else [6.0, 4.0]
    if len(pattern) % 2 == 1:
        pattern = pattern * 2
    segs = []
    pi = 0
    rem = pattern[0]
    draw = True
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len < 1e-4:
            continue
        ux, uy = (x2 - x1) / seg_len, (y2 - y1) / seg_len
        pos = 0.0
        while pos < seg_len - 1e-4:
            step = min(rem, seg_len - pos)
            sx, sy = x1 + ux * pos, y1 + uy * pos
            ex, ey = x1 + ux * (pos + step), y1 + uy * (pos + step)
            if draw and step > 0.2:
                segs.append("M%.2f,%.2f L%.2f,%.2f" % (sx, sy, ex, ey))
            pos += step
            rem -= step
            if rem <= 1e-4:
                pi = (pi + 1) % len(pattern)
                rem = pattern[pi]
                draw = (pi % 2 == 0)
    return " ".join(segs)


def _rect_perimeter_pts(x, y, w, h, rx=0.0):
    r = min(max(rx, 0.0), w / 2.0, h / 2.0)
    if r <= 0.5:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    return [
        (x + r, y), (x + w - r, y), (x + w, y + r), (x + w, y + h - r),
        (x + w - r, y + h), (x + r, y + h), (x, y + h - r), (x, y + r), (x + r, y),
    ]


def _dedup_fonts(ff):
    seen, out = set(), []
    for part in str(ff or DEFAULT_FONTS).split(","):
        p = part.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    if "sans-serif" not in seen:
        out.append("sans-serif")
    return ", ".join(out)


def render(scene, font_family=None):
    W, H = scene["w"], scene["h"]
    ff = _dedup_fonts(font_family or DEFAULT_FONTS)
    ff_esc = _esc(ff)
    prims = scene["prims"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%g" height="%g" '
        'viewBox="0 0 %g %g" font-family="%s">' % (W, H, W, H, ff_esc),
        '<rect id="canvas_bg" x="0" y="0" width="%g" height="%g" fill="#FFFFFF" stroke="none"/>' % (W, H),
    ]
    order = ["frame", "nodes", "links", "labels", "legend", "footer"]
    for lay in order:
        grp = [p for p in prims if p.get("layer") == lay]
        if not grp:
            continue
        out.append('<g id="layer_%s" data-layer="%s">' % (lay, lay))
        for p in grp:
            meta = p.get("meta") or {}
            pv = _prov_attrs(meta)
            if p["op"] == "rect":
                extra = ' data-id="%s"' % _esc(meta.get("id")) if meta.get("id") else ""
                if meta.get("tag") in ("title_bar",):
                    extra += ' data-role="%s"' % _esc(meta["tag"])
                stroke = p["stroke"] if p["stroke"] != "none" else "none"
                if p.get("dash") and stroke != "none" and p["sw"] > 0:
                    # 虚线框拆成无描边背景 + 几何虚线边框，保证跨引擎清晰显示虚线
                    out.append('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" '
                               'stroke="none"%s%s/>'
                               % (p["x"], p["y"], p["w"], p["h"], p["rx"], p["fill"], extra, pv))
                    d = _dashed_path_d(_rect_perimeter_pts(p["x"], p["y"], p["w"], p["h"], p["rx"]), p["dash"])
                    if d:
                        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%g" '
                                   'data-dash="%s"%s/>' % (d, stroke, p["sw"], _esc(p["dash"]), extra))
                else:
                    out.append('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" '
                               'stroke="%s" stroke-width="%g"%s%s/>'
                               % (p["x"], p["y"], p["w"], p["h"], p["rx"], p["fill"],
                                  stroke, p["sw"], extra, pv))
            elif p["op"] == "ellipse":
                out.append('<ellipse cx="%g" cy="%g" rx="%g" ry="%g" fill="%s" '
                           'stroke="%s" stroke-width="%g"/>'
                           % (p["cx"], p["cy"], p["rx"], p["ry"], p["fill"], p["stroke"], p["sw"]))
            elif p["op"] == "line":
                raw_pts = p["pts"]
                mk_mode = p.get("marker", "none")
                arw_len = 8.5 if meta.get("tag") == "legend" else (7.0 if meta.get("tag") == "glyph" else 9.5)
                arw_hw = 3.4 if meta.get("tag") == "legend" else (2.8 if meta.get("tag") == "glyph" else 4.0)
                trim_e = arw_len * 0.72 if mk_mode in ("arrow", "arrowboth") else (1.5 if mk_mode == "tbar" else 0.0)
                trim_s = arw_len * 0.72 if mk_mode == "arrowboth" else 0.0
                draw_pts = _trim_end(raw_pts, trim_end=trim_e, trim_start=trim_s)
                extra = ""
                if meta.get("id"):
                    extra += ' data-id="%s"' % _esc(meta["id"])
                if meta.get("tag") in ("header_rule",):
                    extra += ' data-role="%s"' % _esc(meta["tag"])
                if meta.get("from"):
                    extra += ' data-from="%s"' % _esc(meta["from"])
                if meta.get("to"):
                    extra += ' data-to="%s"' % _esc(meta["to"])
                if meta.get("kind"):
                    extra += ' data-kind="%s"' % _esc(meta["kind"])
                wrap_g = bool(extra or pv) and mk_mode != "none"
                if wrap_g:
                    out.append('<g%s%s>' % (extra, pv))
                    line_extra, line_pv = "", ""
                else:
                    line_extra, line_pv = extra, pv
                if p.get("dash"):
                    d = _dashed_path_d(draw_pts, p["dash"])
                    if d:
                        out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%g" '
                                   'stroke-linecap="butt" data-dash="%s"%s%s/>'
                                   % (d, p["stroke"], p["sw"], _esc(p["dash"]), line_extra, line_pv))
                else:
                    pts_s = " ".join("%.2f,%.2f" % (q[0], q[1]) for q in draw_pts)
                    out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%g" '
                               'stroke-linejoin="round"%s%s/>'
                               % (pts_s, p["stroke"], p["sw"], line_extra, line_pv))
                if mk_mode in ("arrow", "arrowboth") and len(raw_pts) >= 2:
                    ap = _arrow_poly(raw_pts[-2], raw_pts[-1], p["stroke"], arw_len, arw_hw)
                    if ap:
                        out.append(ap)
                if mk_mode == "tbar" and len(raw_pts) >= 2:
                    tb = _tbar_line(raw_pts[-2], raw_pts[-1], p["stroke"],
                                    half_w=4.6 if meta.get("tag") == "legend" else 5.8,
                                    sw=max(p["sw"] + 0.4, 2.2))
                    if tb:
                        out.append(tb)
                if mk_mode == "arrowboth" and len(raw_pts) >= 2:
                    ap_s = _arrow_poly(raw_pts[1], raw_pts[0], p["stroke"], arw_len, arw_hw)
                    if ap_s:
                        out.append(ap_s)
                if wrap_g:
                    out.append('</g>')
            elif p["op"] == "text":
                lines = str(p["s"]).split("\n")
                anchor = p["anchor"]
                t_extra = ""
                if meta.get("node"):
                    t_extra += ' data-node="%s"' % _esc(meta["node"])
                if meta.get("tag") in ("title", "subtitle", "prov_footer"):
                    t_extra += ' data-role="%s"' % _esc(meta["tag"])
                if meta.get("edge"):
                    t_extra += ' data-edge="%s"' % _esc(meta["edge"])
                if meta.get("tag"):
                    t_extra += ' data-tag="%s"' % _esc(meta["tag"])
                if meta.get("halo"):
                    for k, ln in enumerate(lines):
                        w = sirmod.est_w(ln, p["size"], p["weight"] == "bold") + 6.0
                        x0 = p["x"] - w + 3.0 if anchor == "end" else (p["x"] - w / 2 if anchor == "middle" else p["x"] - 3.0)
                        out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="2" fill="#FFFFFF" '
                                   'fill-opacity="0.92" stroke="none"/>'
                                   % (x0, p["y"] + k * p["size"] * 1.3 - p["size"] * 0.86,
                                      w, p["size"] * 1.28))
                for k, ln in enumerate(lines):
                    fw = ' font-weight="bold"' if p["weight"] == "bold" else ""
                    out.append('<text x="%.2f" y="%.2f" font-family="%s" font-size="%g"%s fill="%s" '
                               'text-anchor="%s" xml:space="preserve"%s>%s</text>'
                               % (p["x"], p["y"] + k * p["size"] * 1.3, ff_esc, p["size"], fw,
                                  p["fill"], anchor, t_extra, _esc(ln)))
        out.append('</g>')
    out.append('</svg>')
    return "\n".join(out)


def save(scene, path, font_family=None):
    Path(path).write_text(render(scene, font_family), encoding="utf-8")
    return str(path)
