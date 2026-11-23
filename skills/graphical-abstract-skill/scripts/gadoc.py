#!/usr/bin/env python3
"""Document assembly: root SVG with named layers (bg/title/panels/links/footer)."""
from __future__ import annotations

from gaconfig import (FOOTER_H, H, INK, MARGIN, MUT, ROLE_ACCENTS, VERSION, W, esc)
from gaprims import line, rrect, text, text_fit
from textmetrics import fit_font, text_width, wrap_text


def canvas_dims(brief):
    c = brief.get("canvas")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            cw, ch = int(c[0]), int(c[1])
            if 600 <= cw <= 4000 and 400 <= ch <= 3000:
                return cw, ch
        except Exception:
            pass
    return W, H


def title_layer(brief, cw, ch):
    out, sub = [], str(brief.get("subtitle", "")).strip()
    t = str(brief.get("title", "Untitled study"))
    tw = cw - 2 * MARGIN - 12
    tw_fit = tw * 0.91
    tfs = fit_font(t, tw_fit, 28.0, 18.0)
    lines = [t]
    if text_width(t, tfs) > tw_fit:
        lines = wrap_text(t, tfs, tw_fit)
        if len(lines) > 2:
            mid = len(" ".join(lines[:len(lines) // 2]))
            lines = wrap_text(t[:mid] + " ...", tfs, tw)[:2]
    ty = 34 if sub else 46
    ty0 = ty - (len(lines) - 1) * (tfs * 1.24) / 2
    for i, ln in enumerate(lines):
        out.append(text(MARGIN + 2, ty0 + i * tfs * 1.24, ln, tfs, INK,
                        weight="bold"))
    base = ty + (len(lines) - 1) * tfs * 1.24
    theme = str(brief.get("theme", "card")).strip().lower()
    if theme == "journal":
        out.append(line(MARGIN + 2, base + 12, cw - MARGIN - 2, base + 12, "#0F172A", 1.5))
    else:
        seg = (cw - 2 * MARGIN - 4) / 4
        for i, c in enumerate(ROLE_ACCENTS[:4]):
            out.append(rrect(MARGIN + 2 + i * seg, base + 11, seg - 4, 3.5, rx=1.8,
                             fill=c))
    if sub:
        out.append(text_fit(MARGIN + 2, base + 31, sub, tw, 13.5, MUT))
    return "".join(out)


def footer_layer(brief, cw, ch):
    fy = ch - FOOTER_H
    out = [line(MARGIN, fy, cw - MARGIN, fy, "#CBD5E1", 1.0)]
    src = str(brief.get("sources", "")).strip()
    ver = str(brief.get("version", VERSION)).strip()
    vw = min(300, max(140, text_width(ver, 11) + 20))
    if src:
        out.append(text_fit(MARGIN + 2, ch - 14, "Sources: " + src,
                            cw - 2 * MARGIN - vw - 16, 11, MUT))
    out.append(text(cw - MARGIN - 2, ch - 14, ver, 11, MUT, "end"))
    return "".join(out)


def document(brief, panels_svg, links_svg):
    cw, ch = canvas_dims(brief)
    root = (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'width="{cw}" height="{ch}" viewBox="0 0 {cw} {ch}">')
    layers = [
        ("background", rrect(0, 0, cw, ch, rx=0, fill="#FFFFFF")),
        ("title", title_layer(brief, cw, ch)),
        ("panels", panels_svg),
        ("links", links_svg),
        ("footer", footer_layer(brief, cw, ch)),
    ]
    parts = [root]
    for k, v in layers:
        parts.append(f'<g id="layer-{k}" inkscape:label="{k}">{v}</g>')
    parts.append("</svg>\n")
    return "".join(parts)
