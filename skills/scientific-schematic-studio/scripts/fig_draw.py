"""Draw schematic elements into an mm-space axes; every artist gets a semantic gid."""
import math
import os, sys
from matplotlib.patches import FancyBboxPatch, Ellipse, Polygon, Rectangle
from matplotlib.lines import Line2D
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fig_style as S

CURRENT = dict(S.STYLE)  # per-panel scaled style, set by build_figure


def _border_point(cx, cy, w, h, tx, ty, shape):
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    if shape == "ellipse":
        t = 1.0 / math.hypot(dx / (w / 2.0), dy / (h / 2.0))
        return cx + dx * t, cy + dy * t
    if shape == "diamond":
        denom = abs(dx) / (w / 2.0) + abs(dy) / (h / 2.0)
        t = 1.0 / denom if denom > 0 else 0.0
        return cx + dx * t, cy + dy * t
    tx_ = (w / 2.0) / abs(dx) if dx else float("inf")
    ty_ = (h / 2.0) / abs(dy) if dy else float("inf")
    t = min(tx_, ty_)
    return cx + dx * t, cy + dy * t


def draw_node(ax, node, cx, cy, w, h, fill, gid, size_info=None):
    shape = S.canonical_shape(node.get("shape", "round"))
    stroke = node.get("stroke", S.STYLE["node_stroke"])
    fc = node.get("fill", fill or S.STYLE["node_fill"])
    lw = S.STYLE["node_lw"] + (0.8 if node.get("double") else 0.0)
    if shape == "ellipse":
        art = Ellipse((cx, cy), w, h, fc=fc, ec=stroke, lw=lw, zorder=2.0)
    elif shape == "diamond":
        art = Polygon([(cx, cy + h / 2.0), (cx + w / 2.0, cy),
                       (cx, cy - h / 2.0), (cx - w / 2.0, cy)],
                      closed=True, fc=fc, ec=stroke, lw=lw, zorder=2.0)
    elif shape == "hexagon":
        dx_h = min(w * 0.16, h * 0.42)
        art = Polygon([
            (cx - w / 2.0 + dx_h, cy + h / 2.0),
            (cx + w / 2.0 - dx_h, cy + h / 2.0),
            (cx + w / 2.0, cy),
            (cx + w / 2.0 - dx_h, cy - h / 2.0),
            (cx - w / 2.0 + dx_h, cy - h / 2.0),
            (cx - w / 2.0, cy),
        ], closed=True, fc=fc, ec=stroke, lw=lw, zorder=2.0)
    elif shape == "complex":
        art = FancyBboxPatch((cx - w / 2.0, cy - h / 2.0), w, h,
                             boxstyle="round,pad=0,rounding_size=1.8",
                             fc=fc, ec=stroke, lw=lw, zorder=2.0)
        ins = 1.0
        inner = FancyBboxPatch((cx - w / 2.0 + ins, cy - h / 2.0 + ins),
                               max(w - 2.0 * ins, 2.0), max(h - 2.0 * ins, 2.0),
                               boxstyle="round,pad=0,rounding_size=1.1",
                               fc="none", ec=stroke, lw=max(lw * 0.65, 0.7),
                               ls="-", alpha=0.75, zorder=2.1)
        ax.add_patch(inner)
        inner.set_gid("node-%s-inner" % gid)
    elif shape == "gene":
        art = FancyBboxPatch((cx - w / 2.0, cy - h / 2.0), w, h,
                             boxstyle="square,pad=0",
                             fc=fc, ec=stroke, lw=lw, zorder=2.0)
        bar_h = min(1.5, h * 0.16)
        bar = Rectangle((cx - w / 2.0, cy + h / 2.0 - bar_h), w, bar_h,
                        fc=stroke, ec="none", alpha=0.85, zorder=2.15)
        ax.add_patch(bar)
        bar.set_gid("node-%s-accent" % gid)
    else:
        if shape == "stadium":
            boxstyle = "round,pad=0,rounding_size=%.2f" % (h / 2.0)
        elif shape == "round":
            boxstyle = "round,pad=0,rounding_size=1.5"
        else:
            boxstyle = "square,pad=0"
        art = FancyBboxPatch((cx - w / 2.0, cy - h / 2.0), w, h, boxstyle=boxstyle,
                             fc=fc, ec=stroke, lw=lw, zorder=2.0)
    # Subtle publication-grade elevation shadow (keeps crisp vector look without clutter)
    if shape in ("round", "rect", "stadium", "complex", "gene"):
        sh_rad = (h / 2.0) if shape == "stadium" else (1.5 if shape in ("round", "complex") else 0.0)
        sh_bs = ("round,pad=0,rounding_size=%.2f" % sh_rad) if sh_rad > 0 else "square,pad=0"
        sh = FancyBboxPatch((cx - w / 2.0 + 0.55, cy - h / 2.0 - 0.55), w, h,
                            boxstyle=sh_bs, fc="#10243B", ec="none", alpha=0.07, zorder=1.85)
        ax.add_patch(sh)
        sh.set_gid("node-%s-shadow" % gid)
    elif shape == "ellipse":
        sh = Ellipse((cx + 0.55, cy - 0.55), w, h, fc="#10243B", ec="none", alpha=0.07, zorder=1.85)
        ax.add_patch(sh)
        sh.set_gid("node-%s-shadow" % gid)
    ax.add_patch(art)
    art.set_gid("node-%s" % gid)

    fs = float(node.get("fontsize", CURRENT["fontsize"]))
    txt_col = node.get("text_color") or S.contrast_text_color(fc, S.STYLE["node_text"], "#FFFFFF")
    sub_col = "#E6EEF8" if txt_col == "#FFFFFF" else S.STYLE["sublabel_text"]
    lbl_txt = S.wrap_label(node.get("label", gid))
    has_sub = bool(node.get("sublabel"))
    y_shift = -0.5 if shape == "gene" else 0.0
    if has_sub:
        sub_txt = S.wrap_label(node["sublabel"], max_chars=28)
        fs_s = fs * 0.8
        h_l = (size_info or {}).get("h_l") or (len(lbl_txt.split("\n")) * S.line_height_mm(fs))
        h_s = (size_info or {}).get("h_s") or (len(sub_txt.split("\n")) * S.line_height_mm(fs_s))
        gap = 0.8
        block_h = h_l + gap + h_s
        y_top = cy + y_shift + block_h / 2.0
        y_lbl = y_top - h_l / 2.0
        y_sub = y_top - h_l - gap - h_s / 2.0
        t1 = ax.text(cx, y_lbl, lbl_txt, ha="center", va="center",
                     fontsize=fs, fontweight="bold", color=txt_col, zorder=2.5)
        t1.set_gid("text-%s" % gid)
        t2 = ax.text(cx, y_sub, sub_txt, ha="center", va="center",
                     fontsize=fs_s, color=sub_col, zorder=2.5)
        t2.set_gid("sublabel-%s" % gid)
    else:
        t1 = ax.text(cx, cy + y_shift, lbl_txt, ha="center", va="center",
                     fontsize=fs, fontweight="bold", color=txt_col, zorder=2.5)
        t1.set_gid("text-%s" % gid)

    # Optional quantitative callout badge tucked cleanly onto top-right corner
    if node.get("badge"):
        btxt = str(node["badge"]).strip()
        bfill = node.get("badge_fill", "#D55E00")
        bcol = S.contrast_text_color(bfill, "#10243B", "#FFFFFF")
        tb = ax.text(cx + w / 2.0 - 0.6, cy + h / 2.0 + 0.3, btxt,
                     ha="right", va="center", fontsize=max(fs * 0.66, 5.2),
                     fontweight="bold", color=bcol, zorder=4.2,
                     bbox=dict(boxstyle="round,pad=0.22", fc=bfill, ec="#FFFFFF", lw=0.6))
        tb.set_gid("badge-%s" % gid)


def badge_bbox(node, cx, cy, w, h, meas=None):
    """Estimate bounding box of a node's optional quantitative badge for collision avoidance."""
    if not node.get("badge"):
        return None
    fs = float(node.get("fontsize", CURRENT["fontsize"]))
    bfs = max(fs * 0.66, 5.2)
    bw, bh = _estimate_label_size(str(node["badge"]).strip(), bfs, meas)
    bw += 1.8
    bh += 1.2
    rx = cx + w / 2.0 - 0.2
    ry = cy + h / 2.0 + 0.3
    return (rx - bw, ry - bh / 2.0, rx, ry + bh / 2.0)


def _arrow_head(ax, x, y, dx, dy, gid, style="arrow", color=None, zorder=4.0):
    L, Wd = CURRENT["arrow_len"], CURRENT["arrow_w"]
    col = color or S.STYLE["edge_color"]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    px, py = -uy, ux
    if style == "tbar":
        tlen = CURRENT["tbar_len"]
        seg = Line2D([x - px * tlen / 2.0, x + px * tlen / 2.0],
                     [y - py * tlen / 2.0, y + py * tlen / 2.0],
                     lw=S.STYLE["edge_w"] + 0.7, color=col,
                     solid_capstyle="butt", zorder=zorder)
        ax.add_line(seg)
        seg.set_gid(gid)
        return
    open_head = style in ("arrow_open", "arrow_both_open")
    tipx, tipy = x, y
    bx, by = tipx - ux * L, tipy - uy * L
    pts = [(tipx, tipy),
           (bx + px * Wd / 2.0, by + py * Wd / 2.0),
           (bx - px * Wd / 2.0, by - py * Wd / 2.0)]
    if open_head:
        for idx, (a, b) in enumerate([(pts[1], pts[0]), (pts[2], pts[0])]):
            ln = Line2D([a[0], b[0]], [a[1], b[1]], lw=S.STYLE["edge_w"],
                        color=col, solid_capstyle="round", zorder=zorder)
            ax.add_line(ln)
            ln.set_gid(gid if idx == 0 else "%s-b" % gid)
    else:
        tri = Polygon(pts, closed=True, fc=col, ec="none", zorder=zorder)
        ax.add_patch(tri)
        tri.set_gid(gid)


def _seg_hits_box(p, q, box, pad=0.6):
    """Exact slab intersection of segment p-q against expanded AABB."""
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    dx, dy = q[0] - p[0], q[1] - p[1]
    tmin, tmax = 0.0, 1.0
    for start, delta, lo, hi in ((p[0], dx, x0, x1), (p[1], dy, y0, y1)):
        if abs(delta) < 1e-9:
            if start < lo or start > hi:
                return False
        else:
            t1 = (lo - start) / delta
            t2 = (hi - start) / delta
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def _poly_hits_any(pts, obstacles, ignore_ids, pad=0.6):
    if not obstacles:
        return []
    hits = []
    for k, box in obstacles.items():
        if k in ignore_ids:
            continue
        for i in range(len(pts) - 1):
            if _seg_hits_box(pts[i], pts[i + 1], box, pad=pad):
                hits.append((k, box))
                break
    return hits


def _boxes_overlap(a, b, pad=0.4):
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or
                a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _shorten_end(p_prev, p_end, dist):
    dx, dy = p_end[0] - p_prev[0], p_end[1] - p_prev[1]
    d = math.hypot(dx, dy)
    if d <= dist * 1.5 or d < 1e-6:
        return p_end
    return (p_end[0] - dx / d * dist, p_end[1] - dy / d * dist)


def _estimate_label_size(lab, fs, meas=None):
    if meas is not None:
        w, h, _ = meas.text_mm(lab, fontsize=fs)
        return max(w, 2.0), max(h, S.line_height_mm(fs))
    # CJK-aware fallback
    eff_chars = sum(1.8 if ord(ch) > 127 else 1.0 for ch in lab)
    return max(fs * 0.56 * eff_chars * S.PT_TO_MM, 2.0), S.line_height_mm(fs)


def draw_edge(ax, e, src_c, dst_c, src_shape, dst_shape, src_sz, dst_sz, gid,
              obstacles=None, meas=None, placed_labels=None, placed_segs=None,
              detour_y=None, bypass_base_y=None, bypass_counter=None,
              parallel_off=0.0, corridor_x_off=0.0, corridor_y=None,
              defer_label=False, direction="LR",
              tb_right_x=None, tb_left_x=None, tb_side_counter=None):
    kind = S.EDGE_KINDS.get(S.canonical_edge_kind(e.get("kind", "activates")), S.EDGE_KINDS["activates"])
    col = S.edge_color(e)
    ignore = {e["from"], e["to"]}
    route = e.get("route")
    is_tb = str(direction or "LR").upper() == "TB"

    def _next_bypass_y(hits):
        lane = bypass_counter[0] if bypass_counter is not None else 0
        if bypass_counter is not None:
            bypass_counter[0] += 1
        base = bypass_base_y if bypass_base_y is not None else (max(b[3] for _, b in hits) + 3.6)
        return max(base, max(b[3] for _, b in hits) + 3.4) + lane * 3.2

    def _tb_side_channel(prefer_side="right"):
        if tb_side_counter is None:
            lane_r, lane_l = 0, 0
        else:
            lane_r, lane_l = tb_side_counter[0], tb_side_counter[1]
        if prefer_side == "left":
            if tb_side_counter is not None:
                tb_side_counter[1] += 1
            base_l = tb_left_x if tb_left_x is not None else (
                min((b[0] for b in (obstacles or {}).values()), default=min(src_c[0], dst_c[0]) - 20.0) - 4.5)
            chan_x = base_l - lane_l * 4.4
        else:
            if tb_side_counter is not None:
                tb_side_counter[0] += 1
            base_r = tb_right_x if tb_right_x is not None else (
                max((b[2] for b in (obstacles or {}).values()), default=max(src_c[0], dst_c[0]) + 20.0) + 4.5)
            chan_x = base_r + lane_r * 4.4
        sx, sy = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                               chan_x, src_c[1], src_shape)
        dx, dy = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                               chan_x, dst_c[1], dst_shape)
        return [(sx, sy), (chan_x, sy), (chan_x, dy), (dx, dy)]

    def _pick_tb_side():
        mid_x = ((tb_left_x or 0.0) + (tb_right_x or 100.0)) / 2.0
        avg_x = (src_c[0] + dst_c[0]) / 2.0
        if avg_x < mid_x - 4.0:
            return "left"
        if avg_x > mid_x + 4.0:
            return "right"
        # Centered edge: balance left/right channels by lane count
        if tb_side_counter is not None and tb_side_counter[0] > tb_side_counter[1]:
            return "left"
        return "right"

    if e["from"] == e["to"]:
        # Clean 4-point U self-regulation loop; score top vs bottom against obstacles, badges & headers
        cx, cy = src_c
        hw, hh = src_sz["w"] / 2.0, src_sz["h"] / 2.0
        yl0_a, yl1_a = ax.get_ylim()
        span_x = min(max(hw * 0.42, 3.2), 6.5)
        xa, xb = cx - span_x, cx + span_x
        top_y = cy + hh + 3.6
        bot_y = cy - hh - 3.6
        p_t0 = _border_point(cx, cy, src_sz["w"], src_sz["h"], xa, top_y, src_shape)
        p_t3 = _border_point(cx, cy, src_sz["w"], src_sz["h"], xb, top_y, src_shape)
        loop_top = [p_t0, (p_t0[0], top_y), (p_t3[0], top_y), p_t3]
        p_b0 = _border_point(cx, cy, src_sz["w"], src_sz["h"], xa, bot_y, src_shape)
        p_b3 = _border_point(cx, cy, src_sz["w"], src_sz["h"], xb, bot_y, src_shape)
        loop_bot = [p_b0, (p_b0[0], bot_y), (p_b3[0], bot_y), p_b3]

        def _loop_score(lpts, is_top):
            sc = 0.0
            y_ext = lpts[1][1]
            if y_ext > yl1_a - 2.0 or y_ext < yl0_a + 2.0:
                sc += 60.0
            lbb = (min(p[0] for p in lpts) - 1.5, min(p[1] for p in lpts) - (0.5 if is_top else 3.2),
                   max(p[0] for p in lpts) + 1.5, max(p[1] for p in lpts) + (3.2 if is_top else 0.5))
            for k, box in (obstacles or {}).items():
                if k not in ignore and _boxes_overlap(lbb, box, pad=0.5):
                    sc += 50.0
            for ob in (placed_labels or []):
                if _boxes_overlap(lbb, ob, pad=0.6):
                    sc += 40.0
            return sc

        pts = loop_top if _loop_score(loop_top, True) <= _loop_score(loop_bot, False) else loop_bot
        route = "self_loop"
    elif route == "detour" and is_tb:
        if abs(src_c[1] - dst_c[1]) < 1.5:
            # Same-rank non-adjacent nodes in TB mode: arc cleanly above/below row (NEVER slice through middle node!)
            row_hi = max(src_c[1] + src_sz["h"] / 2.0, dst_c[1] + dst_sz["h"] / 2.0)
            row_lo = min(src_c[1] - src_sz["h"] / 2.0, dst_c[1] - dst_sz["h"] / 2.0)
            mid_boxes = [b for k, b in (obstacles or {}).items()
                         if k not in ignore and min(src_c[0], dst_c[0]) < (b[0] + b[2]) / 2.0 < max(src_c[0], dst_c[0])
                         and abs((b[1] + b[3]) / 2.0 - src_c[1]) < max(src_sz["h"], dst_sz["h"])]
            if mid_boxes:
                row_hi = max(row_hi, max(b[3] for b in mid_boxes))
                row_lo = min(row_lo, min(b[1] for b in mid_boxes))
            arc_top = row_hi + 3.8
            arc_bot = row_lo - 3.8
            p_t1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"], src_c[0], arc_top, src_shape)
            p_t2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], dst_c[0], arc_top, dst_shape)
            cand_top = [p_t1, (p_t1[0], arc_top), (p_t2[0], arc_top), p_t2]
            p_b1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"], src_c[0], arc_bot, src_shape)
            p_b2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], dst_c[0], arc_bot, dst_shape)
            cand_bot = [p_b1, (p_b1[0], arc_bot), (p_b2[0], arc_bot), p_b2]
            hits_t = len(_poly_hits_any(cand_top, obstacles, ignore, pad=0.4))
            hits_b = len(_poly_hits_any(cand_bot, obstacles, ignore, pad=0.4))
            pts = cand_bot if hits_b < hits_t else cand_top
            route = "top_detour"
        else:
            # Vertical outer feedback channel for TB pathways (clean Nature Reviews feedback loop)
            pts = _tb_side_channel(_pick_tb_side())
            route = "tb_side"
    elif route == "detour":
        drop = detour_y if detour_y is not None else (
            min(src_c[1] - src_sz["h"] / 2.0, dst_c[1] - dst_sz["h"] / 2.0) - 6.0)
        bx1, by1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                 src_c[0], drop, src_shape)
        bx2, by2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                 dst_c[0], drop, dst_shape)
        pts_bot = [(bx1, by1), (bx1, drop), (bx2, drop), (bx2, by2)]
        hits_bot = _poly_hits_any(pts_bot, obstacles, ignore, pad=0.5)
        if not hits_bot:
            pts = pts_bot
        else:
            # Try clean top bypass if bottom drop hits lower nodes in the same column
            top_y = _next_bypass_y(hits_bot)
            tx1, ty1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                     src_c[0], top_y, src_shape)
            tx2, ty2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                     dst_c[0], top_y, dst_shape)
            pts_top = [(tx1, ty1), (tx1, top_y), (tx2, top_y), (tx2, ty2)]
            hits_top = _poly_hits_any(pts_top, obstacles, ignore, pad=0.5)
            if hits_top and (abs(src_c[1] - dst_c[1]) > 4.0):
                # Multi-row wrapped LR feedback: route cleanly via outer left/right side channel (0 crossings!)
                c_r = _tb_side_channel("right")
                c_l = _tb_side_channel("left")
                hr = len(_poly_hits_any(c_r, obstacles, ignore, pad=0.4))
                hl = len(_poly_hits_any(c_l, obstacles, ignore, pad=0.4))
                # Pick side with fewer hits, breaking ties by shorter horizontal travel
                def _plen(pp):
                    return sum(math.hypot(pp[k + 1][0] - pp[k][0], pp[k + 1][1] - pp[k][1]) for k in range(len(pp) - 1))
                best_side = c_r if (hr < hl or (hr == hl and _plen(c_r) <= _plen(c_l))) else c_l
                if min(hr, hl) < min(len(hits_top), len(hits_bot)):
                    pts = best_side
                    route = "tb_side"
                elif len(hits_top) < len(hits_bot):
                    pts = pts_top
                    route = "top_detour"
                else:
                    pts = pts_bot
            elif len(hits_top) < len(hits_bot):
                pts = pts_top
                route = "top_detour"
            else:
                # Side-exit corridor around stacked column obstacles
                side = 1.0 if src_c[0] >= dst_c[0] else -1.0
                sx_out = src_c[0] + side * (src_sz["w"] / 2.0 + 3.2)
                dx_out = dst_c[0] - side * (dst_sz["w"] / 2.0 + 3.2)
                ex1, ey1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                         sx_out, src_c[1], src_shape)
                ex2, ey2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                         dx_out, dst_c[1], dst_shape)
                pts_side = [(ex1, ey1), (sx_out, ey1), (sx_out, drop),
                            (dx_out, drop), (dx_out, ey2), (ex2, ey2)]
                hits_side = _poly_hits_any(pts_side, obstacles, ignore, pad=0.4)
                pts = pts_side if len(hits_side) < len(hits_bot) else pts_bot
    else:
        # Offset parallel/bidirectional edges perpendicularly
        dx0, dy0 = dst_c[0] - src_c[0], dst_c[1] - src_c[1]
        d0 = math.hypot(dx0, dy0) or 1.0
        nx, ny = -dy0 / d0 * parallel_off, dx0 / d0 * parallel_off
        sc = (src_c[0] + nx, src_c[1] + ny)
        dc = (dst_c[0] + nx, dst_c[1] + ny)
        x1, y1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                               dc[0], dc[1], src_shape)
        x2, y2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                               sc[0], sc[1], dst_shape)
        if abs(parallel_off) > 0.01:
            x1, y1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                   src_c[0] + dx0 + nx * 2.5, src_c[1] + dy0 + ny * 2.5, src_shape)
            x2, y2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                   dst_c[0] - dx0 + nx * 2.5, dst_c[1] - dy0 + ny * 2.5, dst_shape)

        pts = [(x1, y1), (x2, y2)]
        # Cross-row downward step (e.g. wrapped LR row 1 -> row 2): search clear horizontal corridor levels
        src_bot = src_c[1] - src_sz["h"] / 2.0
        dst_top = dst_c[1] + dst_sz["h"] / 2.0
        if route in ("straight", "elbow") and src_bot > dst_top + 4.0 and abs(dx0) > 12.0:
            upper_bots = [b[1] for k, b in (obstacles or {}).items()
                          if k not in ignore and b[1] > dst_top + 2.0]
            eff_row_bot = min(upper_bots + [src_bot])
            base_mid = corridor_y if corridor_y is not None else ((eff_row_bot + dst_top) / 2.0)
            cand_ys = [base_mid, (src_bot + dst_top) / 2.0, src_bot - 3.6, dst_top + 3.6]
            # Also try clearing just above/below any obstacle sitting in the vertical band between src and dst
            for k_ob, b_ob in (obstacles or {}).items():
                if k_ob not in ignore and dst_top < b_ob[3] < src_bot:
                    cand_ys.append(b_ob[3] + 3.2)
                if k_ob not in ignore and dst_top < b_ob[1] < src_bot:
                    cand_ys.append(b_ob[1] - 3.2)
            cand_ys = [cy for cy in cand_ys if dst_top + 1.5 <= cy <= src_bot - 1.5]
            max_off = dst_sz["w"] * 0.28
            dx_c = max(-max_off, min(max_off, corridor_x_off))
            tx_clamped = dst_c[0] + dx_c
            if dst_shape == "ellipse":
                rx, ry = dst_sz["w"] / 2.0, dst_sz["h"] / 2.0
                by2 = dst_c[1] + ry * math.sqrt(max(0.0, 1.0 - (dx_c / max(rx, 1e-6)) ** 2))
            elif dst_shape == "diamond":
                rx, ry = dst_sz["w"] / 2.0, dst_sz["h"] / 2.0
                by2 = dst_c[1] + ry * max(0.0, 1.0 - abs(dx_c) / max(rx, 1e-6))
            else:
                by2 = dst_c[1] + dst_sz["h"] / 2.0
            found_corr = False
            for mid_y in cand_ys:
                bx1, by1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                         src_c[0], mid_y, src_shape)
                corridor = [(bx1, by1), (bx1, mid_y), (tx_clamped, mid_y), (tx_clamped, by2)]
                if not _poly_hits_any(corridor, obstacles, ignore, pad=0.5):
                    pts = corridor
                    route = "corridor"
                    found_corr = True
                    break
            if not found_corr:
                for mid_y in cand_ys[:4]:
                    for side in (-1.0, 1.0):
                        sx_out = src_c[0] + side * (src_sz["w"] / 2.0 + 2.8)
                        ex1, ey1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                                 sx_out, src_c[1], src_shape)
                        cand_c = [(ex1, ey1), (sx_out, ey1), (sx_out, mid_y),
                                  (tx_clamped, mid_y), (tx_clamped, by2)]
                        if not _poly_hits_any(cand_c, obstacles, ignore, pad=0.45):
                            pts = cand_c
                            route = "corridor"
                            found_corr = True
                            break
                    if found_corr:
                        break

        if route == "elbow":
            if is_tb:
                # In TB mode, long rank-skipping edges route cleanly via outer vertical side channel
                # whenever intermediate nodes lie between src and dst (avoids squeezing/crossing siblings)
                y_lo, y_hi = min(src_c[1], dst_c[1]), max(src_c[1], dst_c[1])
                has_mid_rank = any(
                    k not in ignore and (y_lo + 1.0) < ((b[1] + b[3]) / 2.0) < (y_hi - 1.0)
                    for k, b in (obstacles or {}).items()
                )
                if has_mid_rank or _poly_hits_any(pts, obstacles, ignore, pad=2.5):
                    pts = _tb_side_channel(_pick_tb_side())
                    route = "tb_side"
                else:
                    route = "straight"
            else:
                def _bypass_lr(hits_in):
                    top_y = _next_bypass_y(hits_in)
                    bx1, by1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                             src_c[0], top_y, src_shape)
                    bx2, by2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                             dst_c[0], top_y, dst_shape)
                    cand_top = [(bx1, by1), (bx1, top_y), (bx2, top_y), (bx2, by2)]
                    if not _poly_hits_any(cand_top, obstacles, ignore, pad=0.4):
                        return cand_top, route
                    obs_x0 = min(b[0] for _, b in hits_in)
                    obs_x1 = max(b[2] for _, b in hits_in)
                    for x_step in (obs_x1 + 3.8, obs_x0 - 3.8):
                        if (src_c[0] - src_sz["w"] / 2.0) <= x_step <= (src_c[0] + src_sz["w"] / 2.0):
                            sy_e = (src_c[1] - src_sz["h"] / 2.0) if dst_c[1] < src_c[1] else (src_c[1] + src_sz["h"] / 2.0)
                            p_s = (x_step, sy_e)
                            p_d = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], x_step, dst_c[1], dst_shape)
                            c_step = [p_s, (x_step, p_d[1]), p_d]
                        else:
                            p_s = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"], x_step, src_c[1], src_shape)
                            p_d = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], x_step, dst_c[1], dst_shape)
                            c_step = [p_s, (x_step, p_s[1]), (x_step, p_d[1]), p_d]
                        if not _poly_hits_any(c_step, obstacles, ignore, pad=0.4):
                            return c_step, route
                    c_r = _tb_side_channel("right")
                    c_l = _tb_side_channel("left")
                    hr = len(_poly_hits_any(c_r, obstacles, ignore, pad=0.4))
                    hl = len(_poly_hits_any(c_l, obstacles, ignore, pad=0.4))
                    return (c_r if hr <= hl else c_l), "tb_side"

                mx = (x1 + x2) / 2.0
                cand = [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
                hits = _poly_hits_any(cand, obstacles, ignore, pad=0.7)
                if hits:
                    pts, route = _bypass_lr(hits)
                else:
                    pts = cand
        elif route == "straight":
            hits = _poly_hits_any(pts, obstacles, ignore, pad=0.5)
            if hits:
                if is_tb:
                    mid_x = ((tb_left_x or 0.0) + (tb_right_x or 100.0)) / 2.0
                    prefer = "left" if (src_c[0] + dst_c[0]) / 2.0 < mid_x else "right"
                    pts = _tb_side_channel(prefer)
                    route = "tb_side"
                else:
                    top_y = _next_bypass_y(hits)
                    bx1, by1 = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"],
                                             src_c[0], top_y, src_shape)
                    bx2, by2 = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"],
                                             dst_c[0], top_y, dst_shape)
                    cand_top = [(bx1, by1), (bx1, top_y), (bx2, top_y), (bx2, by2)]
                    if not _poly_hits_any(cand_top, obstacles, ignore, pad=0.4):
                        pts = cand_top
                    else:
                        obs_x0 = min(b[0] for _, b in hits)
                        obs_x1 = max(b[2] for _, b in hits)
                        solved = False
                        for x_step in (obs_x1 + 3.8, obs_x0 - 3.8):
                            if (src_c[0] - src_sz["w"] / 2.0) <= x_step <= (src_c[0] + src_sz["w"] / 2.0):
                                sy_e = (src_c[1] - src_sz["h"] / 2.0) if dst_c[1] < src_c[1] else (src_c[1] + src_sz["h"] / 2.0)
                                p_s = (x_step, sy_e)
                                p_d = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], x_step, dst_c[1], dst_shape)
                                c_step = [p_s, (x_step, p_d[1]), p_d]
                            else:
                                p_s = _border_point(src_c[0], src_c[1], src_sz["w"], src_sz["h"], x_step, src_c[1], src_shape)
                                p_d = _border_point(dst_c[0], dst_c[1], dst_sz["w"], dst_sz["h"], x_step, dst_c[1], dst_shape)
                                c_step = [p_s, (x_step, p_s[1]), (x_step, p_d[1]), p_d]
                            if not _poly_hits_any(c_step, obstacles, ignore, pad=0.4):
                                pts = c_step
                                solved = True
                                break
                        if not solved:
                            c_r = _tb_side_channel("right")
                            c_l = _tb_side_channel("left")
                            hr = len(_poly_hits_any(c_r, obstacles, ignore, pad=0.4))
                            hl = len(_poly_hits_any(c_l, obstacles, ignore, pad=0.4))
                            pts = c_r if hr <= hl else c_l
                            route = "tb_side"

    # Pull back slightly for T-bar so perpendicular bar stands cleanly outside node stroke
    line_pts = list(pts)
    head_pos = pts[-1]
    head_style = {"arrow": "arrow", "tbar": "tbar", "arrow_open": "arrow_open",
                  "arrow_both": "arrow", "none": None}[kind["head"]]
    if head_style == "tbar":
        head_pos = _shorten_end(pts[-2], pts[-1], 0.9)
        line_pts[-1] = head_pos
    elif head_style == "arrow":
        # Stop stroke at base of filled triangle so round cap never pokes past tip
        line_pts[-1] = _shorten_end(pts[-2], pts[-1], CURRENT["arrow_len"] * 0.7)
    if kind["head"] == "arrow_both":
        line_pts[0] = _shorten_end(pts[1], pts[0], CURRENT["arrow_len"] * 0.7)

    xs, ys = zip(*line_pts)
    ln = Line2D(xs, ys, lw=S.STYLE["edge_w"], color=col,
                ls=kind["ls"], solid_capstyle="round", zorder=3.0)
    ax.add_line(ln)
    ln.set_gid("edge-%s-line" % gid)

    if head_style:
        _arrow_head(ax, head_pos[0], head_pos[1],
                    pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1],
                    "edge-%s-head" % gid, head_style, color=col, zorder=3.5)
    if kind["head"] == "arrow_both":
        _arrow_head(ax, pts[0][0], pts[0][1],
                    pts[0][0] - pts[1][0], pts[0][1] - pts[1][1],
                    "edge-%s-head2" % gid, "arrow", color=col, zorder=3.5)

    out_geom = {"points": [[round(p[0], 2), round(p[1], 2)] for p in pts]}
    if not defer_label and e.get("label"):
        place_edge_label(
            ax, e, pts, src_c, dst_c, src_sz, dst_sz, gid, route, col,
            out_geom, obstacles=obstacles, meas=meas,
            placed_labels=placed_labels,
            other_segs=list(placed_segs or []))
    if placed_segs is not None:
        for si in range(len(pts) - 1):
            placed_segs.append((pts[si], pts[si + 1]))
    return out_geom


def place_edge_label(ax, e, pts, src_c, dst_c, src_sz, dst_sz, gid, route, col,
                     out_geom, obstacles=None, meas=None, placed_labels=None,
                     other_segs=None):
    """Place an edge label avoiding nodes, group headers, other labels, and edge segments."""
    if not e.get("label"):
        return
    ignore = {e["from"], e["to"]}
    lab = str(e["label"])
    fs = CURRENT["fontsize"] * 0.78
    if len(pts) == 4:
        p_a, p_b = pts[1], pts[2]
    elif len(pts) == 6:
        p_a, p_b = pts[2], pts[3]
    else:
        best_i = max(range(len(pts) - 1),
                     key=lambda i: math.hypot(pts[i + 1][0] - pts[i][0],
                                              pts[i + 1][1] - pts[i][1]))
        p_a, p_b = pts[best_i], pts[best_i + 1]
    seg_len = math.hypot(p_b[0] - p_a[0], p_b[1] - p_a[1])
    lw_mm, lh_mm = _estimate_label_size(lab, fs, meas)
    max_w = max(seg_len + 8.0, 18.0)
    if lw_mm > max_w:
        fs = max(5.4, fs * max_w / lw_mm)
        lw_mm, lh_mm = _estimate_label_size(lab, fs, meas)

    mx, my = (p_a[0] + p_b[0]) / 2.0, (p_a[1] + p_b[1]) / 2.0
    is_horiz = abs(p_b[1] - p_a[1]) <= abs(p_b[0] - p_a[0])
    xl0, xl1 = ax.get_xlim()
    yl0, yl1 = ax.get_ylim()

    cands = []
    if route == "detour":
        cands = [
            (mx, my + 1.2 + lh_mm / 2.0),
            (mx, my - 1.2 - lh_mm / 2.0),
            (p_a[0] * 0.72 + p_b[0] * 0.28, my + 1.2 + lh_mm / 2.0),
            (p_a[0] * 0.28 + p_b[0] * 0.72, my + 1.2 + lh_mm / 2.0),
            (p_a[0] * 0.72 + p_b[0] * 0.28, my - 1.2 - lh_mm / 2.0),
            (p_a[0] * 0.28 + p_b[0] * 0.72, my - 1.2 - lh_mm / 2.0),
        ]
    elif len(pts) == 4:  # top bypass / corridor / elbow
        if is_horiz:
            cands = []
            for t_pos in (0.5, 0.26, 0.74, 0.16, 0.84):
                cx_t = p_a[0] * (1.0 - t_pos) + p_b[0] * t_pos
                cy_t = p_a[1] * (1.0 - t_pos) + p_b[1] * t_pos
                cands.append((cx_t, cy_t + 1.2 + lh_mm / 2.0))
                cands.append((cx_t, cy_t - 1.2 - lh_mm / 2.0))
            cands.append((mx, my + 2.8 + lh_mm / 2.0))
            cands.append((mx, my - 2.8 - lh_mm / 2.0))
            cands.append((mx, my + 4.4 + lh_mm / 2.0))
        else:
            cands = []
            for t_pos in (0.5, 0.30, 0.70, 0.18, 0.82):
                cx_t = p_a[0] * (1.0 - t_pos) + p_b[0] * t_pos
                cy_t = p_a[1] * (1.0 - t_pos) + p_b[1] * t_pos
                cands.append((cx_t + lw_mm / 2.0 + 1.4, cy_t))
                cands.append((cx_t - lw_mm / 2.0 - 1.4, cy_t))
            cands.append((mx, my))
    elif is_horiz:
        base_up = my + 1.1 + lh_mm / 2.0
        base_dn = my - 1.1 - lh_mm / 2.0
        top_pair = max(src_c[1] + src_sz["h"] / 2.0, dst_c[1] + dst_sz["h"] / 2.0)
        bot_pair = min(src_c[1] - src_sz["h"] / 2.0, dst_c[1] - dst_sz["h"] / 2.0)
        cands = [
            (mx, base_up),
            (mx, base_dn),
            (p_a[0] * 0.65 + p_b[0] * 0.35, base_up),
            (p_a[0] * 0.35 + p_b[0] * 0.65, base_up),
            (p_a[0] * 0.65 + p_b[0] * 0.35, base_dn),
            (p_a[0] * 0.35 + p_b[0] * 0.65, base_dn),
            (mx, top_pair + 1.0 + lh_mm / 2.0),
            (mx, bot_pair - 1.0 - lh_mm / 2.0),
            (mx, top_pair + 3.8 + lh_mm / 2.0),
        ]
    else:
        cands = []
        for t_pos in (0.5, 0.30, 0.70, 0.20, 0.80):
            cx_t = p_a[0] * (1.0 - t_pos) + p_b[0] * t_pos
            cy_t = p_a[1] * (1.0 - t_pos) + p_b[1] * t_pos
            cands.append((cx_t + lw_mm / 2.0 + 1.5, cy_t))
            cands.append((cx_t - lw_mm / 2.0 - 1.5, cy_t))
        cands.append((mx, my))

    other_labels = placed_labels if placed_labels is not None else []
    segs_to_avoid = list(other_segs or [])
    for si in range(len(pts) - 1):
        sp, sq = pts[si], pts[si + 1]
        if not (sp == p_a and sq == p_b):
            segs_to_avoid.append((sp, sq))
    best_cx, best_cy = cands[0]
    best_score = float("inf")
    for cx_c, cy_c in cands:
        cx_c = min(max(cx_c, xl0 + lw_mm / 2.0 + 0.6), xl1 - lw_mm / 2.0 - 0.6)
        cy_c = min(max(cy_c, yl0 + lh_mm / 2.0 + 0.4), yl1 - lh_mm / 2.0 - 0.4)
        bb = (cx_c - lw_mm / 2.0, cy_c - lh_mm / 2.0,
              cx_c + lw_mm / 2.0, cy_c + lh_mm / 2.0)
        score = 0.0
        for k, box in (obstacles or {}).items():
            if _boxes_overlap(bb, box, pad=0.3):
                score += 5.0 if k in ignore else 50.0
        for ob in other_labels:
            if _boxes_overlap(bb, ob, pad=0.8):
                score += 40.0
        for sp, sq in segs_to_avoid:
            if _seg_hits_box(sp, sq, bb, pad=0.5):
                score += 18.0
        if score < best_score:
            best_score = score
            best_cx, best_cy = cx_c, cy_c
            if score == 0.0:
                break

    bb_final = (best_cx - lw_mm / 2.0, best_cy - lh_mm / 2.0,
                best_cx + lw_mm / 2.0, best_cy + lh_mm / 2.0)
    if placed_labels is not None:
        placed_labels.append(bb_final)
    t = ax.text(best_cx, best_cy, lab, ha="center", va="center", fontsize=fs,
                color=col, zorder=4.5,
                bbox=dict(boxstyle="round,pad=0.24", fc=S.STYLE["edge_label_bg"],
                          ec="#DCE4EC", lw=0.55, alpha=0.95))
    t.set_gid("elabel-%s" % gid)
    out_geom["label_bbox"] = [round(v, 2) for v in bb_final]
    out_geom["label_fs"] = round(fs, 2)


def draw_group(ax, g, x0, y0, x1, y1, meas=None, nest_depth=0):
    """Draw compartment/group rounded dashed box with clean top-left header; returns (box, header_box)."""
    pad = 2.6 + nest_depth * 2.5
    hdr = 3.8 + nest_depth * 3.8 + (1.4 if g.get("membrane") else 0.0)
    lbl = str(g.get("label", g["id"]))
    lbl_w, lbl_h = _estimate_label_size(lbl, 7.2, meas)
    lbl_w_bold = lbl_w * 1.12
    gw = max((x1 - x0) + 2.0 * pad, lbl_w_bold + 4.4)
    cx = (x0 + x1) / 2.0
    gx0 = cx - gw / 2.0
    gy0 = y0 - pad
    gh = (y1 - y0) + 2.0 * pad + hdr
    default_fill = "#F8FAFC" if nest_depth > 0 else S.STYLE["group_fill"]
    z_box = max(0.25, 0.55 - nest_depth * 0.12)
    r = FancyBboxPatch((gx0, gy0), gw, gh,
                       boxstyle="round,pad=0,rounding_size=2.2",
                       fc=g.get("fill", default_fill),
                       ec=g.get("stroke", S.STYLE["group_stroke"]),
                       lw=S.STYLE["group_lw"] + (0.2 if nest_depth > 0 else 0.0),
                       ls=(0, (5, 3)) if g.get("dash", True) else "-",
                       zorder=z_box)
    ax.add_patch(r)
    r.set_gid("group-%s" % g["id"])
    # Optional double-line plasma/organelle membrane accent along top boundary (unique SVG IDs)
    if g.get("membrane"):
        m_col = g.get("membrane_color", "#B9770E")
        ym = gy0 + gh
        for mi, dy_m in enumerate((0.0, -0.85), 1):
            ml = Line2D([gx0 + 0.5, gx0 + gw - 0.5], [ym + dy_m, ym + dy_m],
                        lw=1.15, color=m_col, alpha=0.85, zorder=z_box + 0.15)
            ax.add_line(ml)
            ml.set_gid("group-%s-membrane-%d" % (g["id"], mi))
    hy = gy0 + gh - (3.0 if g.get("membrane") else 2.0)
    gfill = g.get("fill", default_fill)
    t = ax.text(gx0 + 1.6, hy, lbl,
                ha="left", va="center", fontsize=7.2, fontweight="bold",
                color=g.get("text_color", S.STYLE["group_text"]), zorder=3.8,
                bbox=dict(fc=gfill, ec="none", alpha=0.9, pad=0.35))
    t.set_gid("grouplabel-%s" % g["id"])
    gbox = [round(gx0, 2), round(gy0, 2), round(gx0 + gw, 2), round(gy0 + gh, 2)]
    htop = (gy0 + gh + 0.8) if g.get("membrane") else (hy + lbl_h / 2.0 + 0.5)
    hbox = (gx0 + 1.2, hy - lbl_h / 2.0 - 0.6, gx0 + 2.0 + lbl_w_bold, htop)
    return gbox, hbox
