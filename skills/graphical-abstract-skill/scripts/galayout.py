#!/usr/bin/env python3
"""Adaptive multi-topology layout engine: row / 2x2 / hero-2x2 + autofit."""
from __future__ import annotations

from gaconfig import (ARROW, EDGE, FOOTER_H, GAP, H, INK, INK2, MARGIN, MUT,
                      ROLE, TITLE_H, W, esc, resolve_role)
from gadoc import canvas_dims
from gaicons import render_icon
from gablocks import render_block
from gaprims import label_bg, line, rrect, seg_arrow, text, text_fit
from textmetrics import text_width

FS_CHOICES = [14.0, 13.0, 12.0, 11.0]
LETTERS = "ABCDEFGH"
_VISUAL_BLOCK_TYPES = {
    "chart", "plot", "graph", "figure", "data",
    "mechanism", "pathway", "diagram", "schematic", "network", "model",
    "row", "columns", "split", "hstack", "side_by_side",
    "svg", "custom_svg", "vector", "graphic",
    "bar", "grouped_bar", "bar_chart", "hbar", "horizontal_bar", "stacked",
    "line", "line_chart", "dot", "dotplot", "strip", "stripplot", "beeswarm", "dot_mean", "swarm",
    "boxplot", "box_plot", "violin",
    "scatter", "volcano", "paired", "slope", "before_after", "heatmap",
    "survival", "kaplan_meier", "km", "forest", "forest_plot",
}


def _is_visual_block(b: dict) -> bool:
    rt = str(b.get("type", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if rt in _VISUAL_BLOCK_TYPES:
        return True
    if rt == "box" and (b.get("series") or b.get("xlabels")):
        return True
    return False


def _panel_svg(p, box, diag, theme="card", default_border=True):
    x0, y0, pw, ph = box
    role = resolve_role(p.get("role", "neutral"))
    cfg = ROLE.get(role, ROLE["neutral"])
    acc = p.get("accent") or cfg["accent"]
    fill = "#FFFFFF" if theme == "journal" else cfg["fill"]
    show_border = bool(p.get("border", default_border))
    pad = 13
    inner_x = x0 + pad + (2 if theme == "journal" else 4)
    inner_w = pw - 2 * pad - (2 if theme == "journal" else 4)
    head_h = 38
    top = y0 + head_h + 7
    avail_h = y0 + ph - 12 - top

    if theme == "journal":
        stroke_c = "#E2E8F0" if show_border else "none"
        out = [rrect(x0, y0, pw, ph, rx=4, fill=fill, stroke=stroke_c, sw=0.85 if show_border else 0.0)]
    else:
        out = [rrect(x0, y0, pw, ph, rx=11, fill=fill, stroke=EDGE, sw=1.15),
               rrect(x0, y0, 5.5, ph, rx=2.8, fill=acc)]
    idx = int(str(p.get("idx", 0)))
    badge = str(p.get("badge", LETTERS[idx % len(LETTERS)])).strip() or LETTERS[idx % len(LETTERS)]
    bw_badge = max(22.0, text_width(badge, 12.5) + 10.0)
    if theme == "journal":
        out.append(text(x0 + 13, y0 + 25, badge, 16.5, "#0F172A", "start", weight="bold"))
        title_x = x0 + 13 + max(18.0, text_width(badge, 16.5) + 8.0)
    else:
        out.append(f'<rect x="{x0+14:.1f}" y="{y0+9:.1f}" width="{bw_badge:.1f}" height="22" '
                   f'rx="5" fill="{acc}"/>')
        out.append(text(x0 + 14 + bw_badge / 2, y0 + 24.5, badge, 13, "#FFFFFF", "middle", weight="bold"))
        title_x = x0 + 22 + bw_badge

    icon = p.get("icon", "")
    right_res = (38 if icon else 14)
    title_maxw = max(60.0, x0 + pw - right_res - title_x)
    ttl = str(p.get("title", ""))
    out.append(text_fit(title_x, y0 + 25, ttl, title_maxw, 15.0, INK, weight="bold"))
    if icon:
        out.append(render_icon(icon, x0 + pw - 22, y0 + 20, r=10.5, color=acc, bg=fill))
    out.append(line(x0 + 13, y0 + head_h - 2, x0 + pw - 13, y0 + head_h - 2,
                    "#E2E8F0" if theme == "journal" else acc, 0.9 if theme == "journal" else 1.5))

    blocks = p.get("blocks", [])

    def _render_blocks(fs, dy=0.0, bgap=9.0):
        parts, cy = [], top + dy
        trial_diag = {"warnings": []}
        # Pre-measure exact trailing heights for non-visual blocks so charts/mechanisms/svgs never overflow
        tail_exact = [0.0] * len(blocks)
        for bi in range(len(blocks) - 1, -1, -1):
            b_i = blocks[bi]
            if _is_visual_block(b_i):
                h_i = float(b_i.get("height", 140.0))
            else:
                _, h_i = render_block(dict(b_i), inner_x, top, inner_w, 220.0, fs, acc)
            tail_exact[bi] = h_i
        for bi, b in enumerate(blocks):
            ah = top + avail_h - cy
            if _is_visual_block(b) and "height" not in b and bi < len(blocks) - 1:
                rem_h = sum(tail_exact[bi + 1:]) + bgap * (len(blocks) - 1 - bi)
                ah = max(110.0, ah - rem_h)
            svg_b, used = render_block(dict(b), inner_x, cy, inner_w,
                                       ah, fs, acc, diag=trial_diag)
            parts.append(svg_b)
            cy += used + bgap
        return parts, cy - bgap, trial_diag["warnings"]

    chosen, hh, overflow, win_warns = FS_CHOICES[-1], 0.0, False, []
    has_visual = any(_is_visual_block(b) for b in blocks)
    for fs in FS_CHOICES:
        parts, cy, warns = _render_blocks(fs)
        hh = cy - top
        if cy <= top + avail_h + 0.5:
            chosen, overflow, win_warns = fs, False, warns
            slack = (avail_h - hh) / max(avail_h, 1.0)
            if slack > 0.32 and fs < 15.0 and not has_visual:
                parts2, cy2, warns2 = _render_blocks(15.0)
                if cy2 <= top + avail_h + 0.5:
                    chosen, parts, hh, win_warns = 15.0, parts2, cy2 - top, warns2
                    slack = (avail_h - hh) / max(avail_h, 1.0)
            bgap = 15.0 if (slack > 0.30 and len(blocks) >= 2 and not has_visual) else 9.0
            if bgap > 9.0:
                parts_g, cy_g, warns_g = _render_blocks(chosen, dy=0.0, bgap=bgap)
                if cy_g <= top + avail_h + 0.5:
                    parts, hh, win_warns = parts_g, cy_g - top, warns_g
                else:
                    bgap = 9.0
            off = max(0.0, (avail_h - hh) * (0.28 if not has_visual else 0.20))
            if off > 2:
                parts, cy, win_warns = _render_blocks(chosen, dy=off, bgap=bgap)
            out.extend(parts)
            break
    else:
        # Last-resort compact fit (still >= 10.0 px font floor) before declaring overflow
        parts_c, cy_c, warns_c = _render_blocks(10.5, dy=0.0, bgap=5.0)
        if cy_c <= top + avail_h + 0.5:
            chosen, overflow, hh, win_warns = 10.5, False, cy_c - top, warns_c
            out.extend(parts_c)
        else:
            overflow = True
            parts, cy, win_warns = _render_blocks(FS_CHOICES[-1])
            out.extend(parts)
    if win_warns:
        diag["warnings"].extend(win_warns)

    diag["panels"][p.get("id", f"P{idx+1}")] = {
        "fs": chosen, "overflow": overflow,
        "content_h": round(hh, 1), "avail_h": round(avail_h, 1),
        "fill_ratio": round(hh / max(avail_h, 1.0), 2),
        "box": [round(x0, 1), round(y0, 1), round(pw, 1), round(ph, 1)],
    }
    return "".join(out)


def _pick_layout(brief, n):
    req = str(brief.get("layout", "auto")).lower().replace("_", "-")
    valid = ("row", "2x2", "hero-2x2", "hero-1+2", "1+2", "hero-2+1", "2+1",
             "1+3", "hero-1+3", "1+4", "hero-1+4", "2+3", "3+2", "2x3", "3x2",
             "left-hero", "stack", "2x1", "grid")
    if req in valid:
        # Graceful reconciliation when panel count disagrees with named layout (never squish 5+ panels into row)
        if req in ("1+3", "hero-1+3"):
            if n == 3:
                return "hero-1+2"
            if n == 5:
                return "1+4"
            if n >= 6:
                return "grid"
        elif req in ("1+4", "hero-1+4"):
            if n == 4:
                return "1+3"
            if n == 3:
                return "hero-1+2"
            if n >= 6:
                return "grid"
        elif req in ("2x2", "hero-2x2"):
            if n == 3:
                return "hero-1+2"
            if n >= 5:
                return "grid"
        elif req in ("hero-1+2", "1+2", "hero-2+1", "2+1"):
            if n == 4:
                return "1+3" if "1+2" in req else "hero-2x2"
            if n >= 5:
                return "grid"
        elif req in ("2+3", "3+2") and n != 5:
            return "grid" if n >= 6 else ("hero-2x2" if n == 4 else ("hero-1+2" if n == 3 else "row"))
        elif req in ("2x3", "3x2") and n != 6:
            return "grid" if n >= 5 else ("hero-2x2" if n == 4 else ("hero-1+2" if n == 3 else "row"))
        return req
    if not brief.get("panel_weights"):
        if n == 4:
            for p in brief.get("panels", []):
                for b in p.get("blocks", []):
                    if b.get("type") in ("mechanism", "row", "chart"):
                        return "hero-2x2"
        elif n >= 5:
            return "grid"
    return "row"


def _compute_boxes(brief, n, cw, ch, layout):
    top = TITLE_H + 6
    usable_w = cw - 2 * MARGIN
    usable_h = ch - FOOTER_H - 12 - top

    if layout in ("stack", "2x1") and n >= 2:
        rw = brief.get("row_weights") or [1.0 / n] * n
        s = sum(rw[:n]) or 1.0
        boxes, cy = [], top
        for wt in rw[:n]:
            ph = (usable_h - GAP * (n - 1)) * (wt / s)
            boxes.append((MARGIN, cy, usable_w, ph))
            cy += ph + GAP
        return boxes

    if layout == "left-hero" and n >= 3:
        cw_r = brief.get("col_weights") or [0.44, 0.56]
        sc = sum(cw_r[:2]) or 1.0
        w_l = (usable_w - GAP) * (cw_r[0] / sc)
        w_r = (usable_w - GAP) * (cw_r[1] / sc)
        nr = n - 1
        rw = brief.get("right_weights") or [1.0 / nr] * nr
        sr = sum(rw[:nr]) or 1.0
        boxes = [(MARGIN, top, w_l, usable_h)]
        cy = top
        for wt in rw[:nr]:
            ph = (usable_h - GAP * (nr - 1)) * (wt / sr)
            boxes.append((MARGIN + w_l + GAP, cy, w_r, ph))
            cy += ph + GAP
        return boxes

    if layout in ("hero-1+2", "1+2") and n == 3:
        rw = brief.get("row_weights") or [0.50, 0.50]
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        bw = brief.get("bottom_weights") or [0.55, 0.45]
        sb = sum(bw) or 1.0
        w0 = (usable_w - GAP) * (bw[0] / sb)
        w1 = (usable_w - GAP) * (bw[1] / sb)
        return [
            (MARGIN, top, usable_w, h_top),
            (MARGIN, top + h_top + GAP, w0, h_bot),
            (MARGIN + w0 + GAP, top + h_top + GAP, w1, h_bot),
        ]

    if layout in ("hero-2+1", "2+1") and n == 3:
        rw = brief.get("row_weights") or [0.50, 0.50]
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        tw = brief.get("top_weights") or [0.50, 0.50]
        st = sum(tw) or 1.0
        w0 = (usable_w - GAP) * (tw[0] / st)
        w1 = (usable_w - GAP) * (tw[1] / st)
        return [
            (MARGIN, top, w0, h_top),
            (MARGIN + w0 + GAP, top, w1, h_top),
            (MARGIN, top + h_top + GAP, usable_w, h_bot),
        ]

    if layout in ("1+3", "hero-1+3") and n == 4:
        rw = brief.get("row_weights") or [0.46, 0.54]
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        bw = brief.get("bottom_weights") or [1.0, 1.0, 1.0]
        sb = sum(bw[:3]) or 1.0
        boxes = [(MARGIN, top, usable_w, h_top)]
        cx = MARGIN
        for wt in bw[:3]:
            pw = (usable_w - GAP * 2) * (wt / sb)
            boxes.append((cx, top + h_top + GAP, pw, h_bot))
            cx += pw + GAP
        return boxes

    if layout in ("1+4", "hero-1+4") and n == 5:
        rw = brief.get("row_weights") or [0.46, 0.54]
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        bw = brief.get("bottom_weights") or [1.0, 1.0, 1.0, 1.0]
        sb = sum(bw[:4]) or 1.0
        boxes = [(MARGIN, top, usable_w, h_top)]
        cx = MARGIN
        for wt in bw[:4]:
            pw = (usable_w - GAP * 3) * (wt / sb)
            boxes.append((cx, top + h_top + GAP, pw, h_bot))
            cx += pw + GAP
        return boxes

    if layout in ("grid", "2+3", "3+2", "2x3", "3x2") and n >= 5:
        if layout == "2+3" and n == 5:
            n_top, n_bot = 2, 3
        elif layout == "3+2" and n == 5:
            n_top, n_bot = 3, 2
        else:
            n_top = (n + 1) // 2
            n_bot = n - n_top
        rw = brief.get("row_weights") or [0.50, 0.50]
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        tw = brief.get("top_weights") or [1.0 / n_top] * n_top
        bw = brief.get("bottom_weights") or [1.0 / n_bot] * n_bot
        st, sb = sum(tw[:n_top]) or 1.0, sum(bw[:n_bot]) or 1.0
        boxes = []
        cx = MARGIN
        for wt in tw[:n_top]:
            pw = (usable_w - GAP * (n_top - 1)) * (wt / st)
            boxes.append((cx, top, pw, h_top))
            cx += pw + GAP
        cx = MARGIN
        for wt in bw[:n_bot]:
            pw = (usable_w - GAP * (n_bot - 1)) * (wt / sb)
            boxes.append((cx, top + h_top + GAP, pw, h_bot))
            cx += pw + GAP
        return boxes

    if layout in ("2x2", "hero-2x2") and n == 4:
        rw = brief.get("row_weights") or ([0.48, 0.52] if layout == "hero-2x2" else [0.5, 0.5])
        s = sum(rw) or 1.0
        h_top = (usable_h - GAP) * (rw[0] / s)
        h_bot = (usable_h - GAP) * (rw[1] / s)
        tw = brief.get("top_weights") or ([0.31, 0.69] if layout == "hero-2x2" else [0.5, 0.5])
        bw = brief.get("bottom_weights") or ([0.64, 0.36] if layout == "hero-2x2" else [0.5, 0.5])
        st, sb = sum(tw) or 1.0, sum(bw) or 1.0
        w0 = (usable_w - GAP) * (tw[0] / st)
        w1 = (usable_w - GAP) * (tw[1] / st)
        w2 = (usable_w - GAP) * (bw[0] / sb)
        w3 = (usable_w - GAP) * (bw[1] / sb)
        return [
            (MARGIN, top, w0, h_top),
            (MARGIN + w0 + GAP, top, w1, h_top),
            (MARGIN, top + h_top + GAP, w2, h_bot),
            (MARGIN + w2 + GAP, top + h_top + GAP, w3, h_bot),
        ]

    # Default single row
    weights = brief.get("panel_weights") or [1.0 / n] * n
    s = sum(weights) or 1.0
    weights = [w / s for w in weights]
    boxes = []
    cx = MARGIN
    for wgt in weights[:n]:
        pw = (usable_w - GAP * (n - 1)) * wgt
        boxes.append((cx, top, pw, usable_h))
        cx += pw + GAP
    return boxes


def _render_panel_link(b1, b2, label, cw=W):
    """Draw a clean directional connector (LR / RL / TB / BT) + optional pill badge between panels."""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    out = []
    # Same row: left -> right
    if abs(y1 - y2) < 20 and x2 > x1 + w1 - 2:
        ax1, ax2 = x1 + w1 + 2, x2 - 2
        ym = max(y1, y2) + min(h1, h2) * 0.50
        out.append(seg_arrow(ax1, ym, ax2, ym, ARROW, 2.2, 8.5))
        if label:
            out.append(label_bg((ax1 + ax2) / 2, ym - 15, str(label), 10.0,
                                pad=2.5, bg="#FFFFFF", fg=INK2,
                                weight="bold", stroke=EDGE))
    # Same row: right -> left (feedback)
    elif abs(y1 - y2) < 20 and x1 > x2 + w2 - 2:
        ax1, ax2 = x1 - 2, x2 + w2 + 2
        ym = max(y1, y2) + min(h1, h2) * 0.50
        out.append(seg_arrow(ax1, ym, ax2, ym, ARROW, 2.2, 8.5, dash="5 3"))
        if label:
            out.append(label_bg((ax1 + ax2) / 2, ym - 15, str(label), 10.0,
                                pad=2.5, bg="#FFFFFF", fg=INK2,
                                weight="bold", stroke=EDGE))
    # Vertical: top -> bottom
    elif y2 > y1 + h1 - 2:
        ay1, ay2 = y1 + h1 + 2, y2 - 2
        ox0, ox1 = max(x1, x2), min(x1 + w1, x2 + w2)
        xm = (ox0 + ox1) / 2 if ox1 > ox0 + 30 else (x1 + w1 / 2 + x2 + w2 / 2) / 2
        out.append(seg_arrow(xm, ay1, xm, ay2, ARROW, 2.2, 8.5))
        if label:
            lbl = str(label)
            lw = text_width(lbl, 10.0) + 8
            lx = xm + 10 + lw / 2
            if lx + lw / 2 > cw - MARGIN:
                lx = xm - 10 - lw / 2
            out.append(label_bg(lx, (ay1 + ay2) / 2, lbl, 10.0,
                                pad=2.5, bg="#FFFFFF", fg=INK2,
                                weight="bold", stroke=EDGE))
    # Vertical: bottom -> top (feedback loop)
    elif y1 > y2 + h2 - 2:
        ay1, ay2 = y1 - 2, y2 + h2 + 2
        ox0, ox1 = max(x1, x2), min(x1 + w1, x2 + w2)
        xm = (ox0 + ox1) / 2 if ox1 > ox0 + 30 else (x1 + w1 / 2 + x2 + w2 / 2) / 2
        out.append(seg_arrow(xm, ay1, xm, ay2, ARROW, 2.2, 8.5, dash="5 3"))
        if label:
            lbl = str(label)
            lw = text_width(lbl, 10.0) + 8
            lx = xm + 10 + lw / 2
            if lx + lw / 2 > cw - MARGIN:
                lx = xm - 10 - lw / 2
            out.append(label_bg(lx, (ay1 + ay2) / 2, lbl, 10.0,
                                pad=2.5, bg="#FFFFFF", fg=INK2,
                                weight="bold", stroke=EDGE))
    return "".join(out)


def build_svg(brief):
    cw, ch = canvas_dims(brief)
    diag = {"panels": {}, "warnings": [], "layout": None, "canvas": [cw, ch]}
    panels = brief.get("panels") or brief.get("panel") or []
    n = max(len(panels), 1)
    layout = _pick_layout(brief, n)
    diag["layout"] = layout
    boxes = _compute_boxes(brief, n, cw, ch, layout)

    theme = str(brief.get("theme", "card")).strip().lower()
    if theme not in ("card", "journal"):
        theme = "card"
    diag["theme"] = theme
    default_border = bool(brief.get("border", brief.get("panel_border", True)))
    body = []
    for i, p in enumerate(panels[:n]):
        p = dict(p)
        p["idx"] = i
        pid = p.get("id", f"P{i+1}")
        bx = boxes[i]
        bstr = f"{bx[0]:.1f},{bx[1]:.1f},{bx[2]:.1f},{bx[3]:.1f}"
        body.append(f'<g id="panel-{esc(pid)}" data-panel-box="{bstr}" '
                    f'inkscape:label="panel {esc(pid)} {esc(p.get("role",""))}">'
                    + _panel_svg(p, bx, diag, theme=theme, default_border=default_border) + "</g>")

    links = []
    for lk in brief.get("panel_links", []):
        try:
            i = next(k for k, p in enumerate(panels) if p.get("id") == lk["from"])
            j = next(k for k, p in enumerate(panels) if p.get("id") == lk["to"])
        except StopIteration:
            continue
        links.append(_render_panel_link(boxes[i], boxes[j], lk.get("label"), cw=cw))
    return ("".join(body), "".join(links), boxes, diag)
