#!/usr/bin/env python3
"""SVG primitive builders returning strings. Plain SVG 1.1 only
(rect/circle/ellipse/line/polygon/path/text) for universal compatibility."""
from __future__ import annotations

import math

from gaconfig import FONT, INK, esc
from textmetrics import text_width


def text(x, y, s, fs=14, fill=INK, anchor="start", weight="normal",
         family=FONT, extra=""):
    w = f' font-weight="{weight}"' if weight != "normal" else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{esc(family)}" '
            f'font-size="{fs:.1f}" fill="{fill}" text-anchor="{anchor}"{w} '
            f'data-maxw="0"{extra}>{esc(s)}</text>')


def text_fit(x, y, s, maxw, fs, fill=INK, anchor="start", weight="normal",
             extra="", floor=10.0):
    """Single line auto-shrunk (never below floor) to fit maxw."""
    from textmetrics import fit_font
    mw = maxw * 0.94 if weight == "bold" else maxw
    fs2 = fit_font(str(s), mw, fs, floor)
    return text(x, y, s, fs2, fill, anchor, weight, extra=extra)


def rrect(x, y, w, h, rx=10, fill="none", stroke=None, sw=1.0, dash=None, extra=""):
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    ex = f" {extra}" if extra else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" '
            f'height="{max(h, 0):.1f}" rx="{rx}" fill="{fill}"{s}{d}{ex}/>')


def line(x1, y1, x2, y2, stroke, sw=1.2, dash=None, extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    ex = f" {extra}" if extra else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}{ex}/>')


def arrowhead(tipx, tipy, dx, dy, size=8.0, color="#64748B"):
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    bx, by = tipx - ux * size, tipy - uy * size
    p1 = (bx + px * size * 0.44, by + py * size * 0.44)
    p2 = (bx - px * size * 0.44, by - py * size * 0.44)
    pts = f"{tipx:.1f},{tipy:.1f} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return f'<polygon points="{pts}" fill="{color}"/>'


def tbar(tipx, tipy, dx, dy, size=10.5, color="#DC2626", sw=2.6):
    """Inhibition flat T-bar terminator with subtle white halo (BioRender biology notation)."""
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    h = size * 0.78
    return (line(tipx + px * h, tipy + py * h,
                 tipx - px * h, tipy - py * h, "#FFFFFF", sw + 2.4,
                 extra='stroke-linecap="round"')
            + line(tipx + px * h, tipy + py * h,
                   tipx - px * h, tipy - py * h, color, sw,
                   extra='stroke-linecap="round"'))


def seg_arrow(x1, y1, x2, y2, color="#64748B", sw=1.8, head=8.0,
              extra="", kind="activate", dash=None):
    """Directed segment supporting activate / inhibit / bidirectional / dashed."""
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    eff_dash = None if "stroke-dasharray" in extra else (dash or ("5 3" if kind == "dashed" else None))
    if kind == "inhibit":
        bx, by = x2 - ux * 3.2, y2 - uy * 3.2
        return (line(x1, y1, bx, by, color, sw, dash=eff_dash, extra=extra)
                + tbar(bx, by, dx, dy, head * 1.25, color, sw + 0.8))
    if kind == "bidirectional":
        sx, sy = x1 + ux * head, y1 + uy * head
        bx, by = x2 - ux * head, y2 - uy * head
        return (line(sx, sy, bx, by, color, sw, dash=eff_dash, extra=extra)
                + arrowhead(x1, y1, -dx, -dy, head, color)
                + arrowhead(x2, y2, dx, dy, head, color))
    bx, by = x2 - ux * head, y2 - uy * head
    return (line(x1, y1, bx, by, color, sw, dash=eff_dash, extra=extra)
            + arrowhead(x2, y2, dx, dy, head, color))


def quad_arrow(x1, y1, cx, cy, x2, y2, color="#64748B", sw=1.8, head=8.0,
               dash=None, kind="activate"):
    """Curved quadratic Bezier arrow (for skip-edges that arc around nodes)."""
    tx, ty = x2 - cx, y2 - cy
    n = math.hypot(tx, ty) or 1.0
    ux, uy = tx / n, ty / n
    eff_dash = dash or ("5 3" if kind == "dashed" else None)
    d_attr = f' stroke-dasharray="{eff_dash}"' if eff_dash else ""
    if kind == "inhibit":
        ex, ey = x2 - ux * 3.2, y2 - uy * 3.2
        path = (f'<path d="M {x1:.1f},{y1:.1f} Q {cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="{sw}"{d_attr}/>')
        return path + tbar(ex, ey, tx, ty, head * 1.25, color, sw + 0.8)
    ex, ey = x2 - ux * head * 0.85, y2 - uy * head * 0.85
    path = (f'<path d="M {x1:.1f},{y1:.1f} Q {cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{sw}"{d_attr}/>')
    out = path + arrowhead(x2, y2, tx, ty, head, color)
    if kind == "bidirectional":
        out += arrowhead(x1, y1, x1 - cx, y1 - cy, head, color)
    return out


def label_bg(cx, cy, s, fs=11, pad=4, bg="#FFFFFF", fg="#374151",
             weight="normal", stroke=None):
    """Centered text with opaque bg pill (halo substitute, soffice-safe)."""
    w = text_width(s, fs)
    x = cx - w / 2 - pad
    y = cy - fs * 0.72 - pad * 0.5
    h = fs * 1.32 + pad * 0.9
    return (rrect(x, y, w + 2 * pad, h, rx=4, fill=bg, stroke=stroke,
                  sw=0.8 if stroke else 0, extra='data-kind="label-bg"')
            + text(cx, cy + fs * 0.34, s, fs, fg, "middle", weight))


def marker_shape(cx, cy, r, color, shape="circle"):
    """Distinct plot marker for grayscale & colorblind accessibility."""
    if shape == "square":
        return (f'<rect x="{cx-r:.1f}" y="{cy-r:.1f}" width="{2*r:.1f}" '
                f'height="{2*r:.1f}" fill="{color}" stroke="#FFFFFF" stroke-width="0.9"/>')
    if shape == "triangle":
        pts = (f"{cx:.1f},{cy-r*1.25:.1f} {cx+r*1.15:.1f},{cy+r:.1f} "
               f"{cx-r*1.15:.1f},{cy+r:.1f}")
        return f'<polygon points="{pts}" fill="{color}" stroke="#FFFFFF" stroke-width="0.8"/>'
    if shape == "diamond":
        pts = (f"{cx:.1f},{cy-r*1.25:.1f} {cx+r*1.15:.1f},{cy:.1f} "
               f"{cx:.1f},{cy+r*1.25:.1f} {cx-r*1.15:.1f},{cy:.1f}")
        return f'<polygon points="{pts}" fill="{color}" stroke="#FFFFFF" stroke-width="0.8"/>'
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{color}" stroke="#FFFFFF" stroke-width="0.9"/>')


def swatch(x, y, s, color, fs=12, shape="rect", marker="circle", dash=None):
    if shape == "line":
        g = line(x, y - 4, x + 20, y - 4, color, 2.6, dash=dash)
        if marker:
            g += marker_shape(x + 10, y - 4, 3.4, color, marker)
        tx = x + 24
    elif shape == "dot":
        g = marker_shape(x + 7, y - 4, 4.2, color, marker)
        tx = x + 18
    else:
        g = rrect(x, y - 10.5, 13, 11, rx=2, fill=color)
        tx = x + 18
    return g + text(tx, y, s, fs, "#374151")
