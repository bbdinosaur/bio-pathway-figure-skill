"""Edge rendering: border-anchored parallel edges, PTM-aware port clamping, universal
obstacle-avoiding cross-row & same-row routing, outer-rail feedback, semantic markers,
and pill-backed collision-free edge labels."""
from __future__ import annotations
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import EDGE_STYLES
from viz_geom import norm, perp, boundary_point, arrow_poly, diamond_poly, MARKER_LEN

def _seg_hits_boxes(p0, p1, boxes, skip, pad=-2.0):
    """True if segment p0-p1 enters any non-skipped node box expanded by `pad`."""
    for nid, bb in boxes:
        if nid in skip:
            continue
        x0, y0, x1, y1 = bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad
        if x0 >= x1 or y0 >= y1:
            continue
        for i in range(1, 44):
            t = i / 44.0
            px = p0[0] + (p1[0] - p0[0]) * t
            py = p0[1] + (p1[1] - p0[1]) * t
            if x0 < px < x1 and y0 < py < y1:
                return True
    return False

def _poly_hits_boxes(pts, boxes, skip, pad=2.0):
    for i in range(len(pts) - 1):
        if _seg_hits_boxes(pts[i], pts[i + 1], boxes, skip, pad=pad):
            return True
    return False

def _round_corners(pts, radius=10.0):
    """Replace sharp orthogonal bends with smooth 4-step quadratic corner fillets."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        v1x, v1y = p0[0] - p1[0], p0[1] - p1[1]
        v2x, v2y = p2[0] - p1[0], p2[1] - p1[1]
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 < 4.0 or l2 < 4.0:
            out.append(p1)
            continue
        r = min(radius, l1 * 0.38, l2 * 0.38)
        a = [p1[0] + v1x * (r / l1), p1[1] + v1y * (r / l1)]
        b = [p1[0] + v2x * (r / l2), p1[1] + v2y * (r / l2)]
        for t in (0.0, 0.33, 0.67, 1.0):
            omt = 1.0 - t
            qx = omt * omt * a[0] + 2.0 * omt * t * p1[0] + t * t * b[0]
            qy = omt * omt * a[1] + 2.0 * omt * t * p1[1] + t * t * b[1]
            out.append([qx, qy])
    out.append(pts[-1])
    return out

def _poly_len(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))

def _avoid_mod_corner(pt, node):
    """Keep border port clear of all top-right PTM pill/circle badges while staying strictly on node border."""
    mods = node.get("mods") or []
    if not mods:
        return list(pt)
    shape = node.get("shape", "rect")
    if shape in ("ellipse", "hex"):
        return list(pt)
    cx, cy, hw, hh = node["cx"], node["cy"], node["w"] / 2.0, node["h"] / 2.0
    px, py = float(pt[0]), float(pt[1])
    # Match viz_nodes.py dynamic pill span starting at cx + hw + 4.0
    mod_span = 4.0
    for ms in (str(m) for m in mods):
        mod_span += (max(24.0, len(ms) * 6.2 + 9.0) if len(ms) >= 2 else 19.0) + 3.0
    if abs(py - (cy - hh)) < 2.5 and px > cx + hw - mod_span:
        px = max(cx - hw + 10.0, cx + hw - mod_span - 4.0)
    elif abs(px - (cx + hw)) < 2.5 and py < cy - hh + 18.0:
        py = min(cy + hh - 8.0, cy - hh + 20.0)
    return [px, py]

def _side_channel_y(node, boxes, skip, rail_x, prefer_above=True, used_ys=None):
    """Find a clear horizontal channel above or below `node` to reach `rail_x` without hitting boxes, PTMs, or sibling markers."""
    y_top = node["cy"] - node["h"] / 2.0
    y_bot = node["cy"] + node["h"] / 2.0
    used_ys = used_ys if used_ys is not None else []
    order = (
        [(y_top, y_top - d) for d in (18, 26, 34, 42)] + [(y_bot, y_bot + d) for d in (18, 26, 34)]
        if prefer_above else
        [(y_bot, y_bot + d) for d in (18, 26, 34, 42)] + [(y_top, y_top - d) for d in (18, 26, 34)]
    )
    for pad_try in (10.0, 4.0):
        for y_border, y_chan in order:
            if any(abs(y_chan - uy) < 7.0 for uy in used_ys):
                continue
            if not _seg_hits_boxes([node["cx"], y_chan], [rail_x, y_chan], boxes, skip, pad=pad_try):
                used_ys.append(y_chan)
                return y_border, y_chan
    for y_border, y_chan in order:
        if not _seg_hits_boxes([node["cx"], y_chan], [rail_x, y_chan], boxes, skip, pad=2.0):
            used_ys.append(y_chan)
            return y_border, y_chan
    return order[0]

def _stagger_x(bx, used_xs, step=14.0):
    """Nudge a vertical corridor x slightly if another detour already uses that lane."""
    if not used_xs:
        return bx
    for k in range(8):
        for sgn in (1.0, -1.0) if k > 0 else (1.0,):
            cand = bx + sgn * k * step
            if all(abs(cand - ux) >= step * 0.85 for ux in used_xs):
                return cand
    return bx

def _route_cross_detour(n_from, n_to, boxes, skip, plot_left, plot_right, used_xs):
    """Compute shortest obstacle-free orthogonal detour between nodes on different rows."""
    going_down = n_to["cy"] >= n_from["cy"]
    y_lo = min(n_from["cy"], n_to["cy"])
    y_hi = max(n_from["cy"], n_to["cy"])

    # Identify all non-endpoint boxes overlapping the vertical span between n_from and n_to
    inter = []
    for nid, bb in boxes:
        if nid in skip:
            continue
        if bb[3] > y_lo - 10 and bb[1] < y_hi + 10:
            inter.append(bb)

    cand_xs = []
    # 1. Left & right flanks of each obstacle and of their union
    if inter:
        min_x = min(bb[0] for bb in inter)
        max_x = max(bb[2] for bb in inter)
        cand_xs.extend([min_x - 22.0, max_x + 22.0])
        for bb in inter:
            cand_xs.extend([bb[0] - 20.0, bb[2] + 20.0])
        # Midpoints of horizontal gaps between sorted obstacles
        s_inter = sorted(inter, key=lambda b: b[0])
        for i in range(len(s_inter) - 1):
            gap_l = s_inter[i][2]
            gap_r = s_inter[i + 1][0]
            if gap_r - gap_l >= 28.0:
                cand_xs.append((gap_l + gap_r) / 2.0)
    # 2. Inner plot gutters as guaranteed escape corridors
    if plot_left is not None:
        cand_xs.append(plot_left + 16.0)
    if plot_right is not None:
        cand_xs.append(plot_right - 16.0)

    # Deduplicate candidate x values within 4px
    uniq_xs = []
    for x in cand_xs:
        if not any(abs(x - ux) < 4.0 for ux in uniq_xs):
            uniq_xs.append(x)

    best_pts = None
    best_score = 1e18

    for raw_bx in uniq_xs:
        bx = _stagger_x(raw_bx, used_xs, step=14.0)
        # Departure from n_from: prefer direct side exit if clear, else top/bottom channel
        dep_opts = []
        s_right = n_from["cx"] + n_from["w"] / 2.0
        s_left = n_from["cx"] - n_from["w"] / 2.0
        sy_side = n_from["cy"]
        if bx > s_right + 8.0:
            p_side = _avoid_mod_corner([s_right, sy_side], n_from)
            dep_opts.append([p_side, [bx, p_side[1]]])
        elif bx < s_left - 8.0:
            dep_opts.append([[s_left, sy_side], [bx, sy_side]])
        yb_f = (n_from["cy"] + n_from["h"] / 2.0) if going_down else (n_from["cy"] - n_from["h"] / 2.0)
        dy_f = 16.0 if going_down else -16.0
        sx_c = max(n_from["cx"] - n_from["w"] / 2.0 + 12.0,
                   min(n_from["cx"] + n_from["w"] / 2.0 - 12.0,
                       n_from["cx"] + (10.0 if bx > n_from["cx"] else -10.0)))
        p_tb = _avoid_mod_corner([sx_c, yb_f], n_from)
        dep_opts.append([p_tb, [p_tb[0], yb_f + dy_f], [bx, yb_f + dy_f]])

        # Arrival at n_to: prefer direct side entry if clear, else top/bottom channel
        arr_opts = []
        t_right = n_to["cx"] + n_to["w"] / 2.0
        t_left = n_to["cx"] - n_to["w"] / 2.0
        ty_side = n_to["cy"]
        if bx > t_right + 8.0:
            p_side = _avoid_mod_corner([t_right, ty_side], n_to)
            arr_opts.append([[bx, p_side[1]], p_side])
        elif bx < t_left - 8.0:
            arr_opts.append([[bx, ty_side], [t_left, ty_side]])
        yb_t = (n_to["cy"] - n_to["h"] / 2.0) if going_down else (n_to["cy"] + n_to["h"] / 2.0)
        dy_t = -16.0 if going_down else 16.0
        tx_c = max(n_to["cx"] - n_to["w"] / 2.0 + 12.0,
                   min(n_to["cx"] + n_to["w"] / 2.0 - 12.0,
                       n_to["cx"] + (10.0 if bx > n_to["cx"] else -10.0)))
        p_tb_t = _avoid_mod_corner([tx_c, yb_t], n_to)
        arr_opts.append([[bx, yb_t + dy_t], [p_tb_t[0], yb_t + dy_t], p_tb_t])

        for dep in dep_opts:
            for arr in arr_opts:
                pts = dep + arr
                # Collapse near-duplicate consecutive vertices
                clean = [pts[0]]
                for q in pts[1:]:
                    if math.hypot(q[0] - clean[-1][0], q[1] - clean[-1][1]) > 1.5:
                        clean.append(q)
                if len(clean) < 2:
                    continue
                if _poly_hits_boxes(clean, boxes, skip, pad=3.0):
                    continue
                # Also ensure segments don't cross through source/target interior
                if _poly_hits_boxes(clean[1:-1], boxes, set(), pad=1.0):
                    continue
                score = _poly_len(clean) + 18.0 * max(0, len(clean) - 4)
                if plot_left is not None and bx < plot_left + 4.0:
                    score += 80.0
                if plot_right is not None and bx > plot_right - 4.0:
                    score += 80.0
                if score < best_score:
                    best_score = score
                    best_pts = (clean, bx)

    if best_pts is not None:
        used_xs.append(best_pts[1])
        return best_pts[0]
    return None

def _segs_cross(a0, a1, b0, b1):
    """True if open segments a0-a1 and b0-b1 properly intersect."""
    def _ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = _ccw(a0, a1, b0), _ccw(a0, a1, b1)
    d3, d4 = _ccw(b0, b1, a0), _ccw(b0, b1, a1)
    return (d1 * d2 < -1e-6) and (d3 * d4 < -1e-6)

def _poly_edge_crossings(pts, routed_records):
    if not routed_records:
        return 0
    cnt = 0
    for rec in routed_records:
        rpts = rec.get("pts") or []
        for i in range(len(pts) - 1):
            for j in range(len(rpts) - 1):
                if _segs_cross(pts[i], pts[i + 1], rpts[j], rpts[j + 1]):
                    cnt += 1
    return cnt

def _node_top_occupied(node, routed_records):
    """True if any already-routed edge attaches near the top border of `node`."""
    if not routed_records:
        return False
    y_top = node["cy"] - node["h"] / 2.0
    x0, x1 = node["cx"] - node["w"] / 2.0 - 4.0, node["cx"] + node["w"] / 2.0 + 4.0
    for rec in routed_records:
        rpts = rec.get("pts") or []
        if len(rpts) >= 2:
            for ep in (rpts[0], rpts[-1]):
                if x0 <= ep[0] <= x1 and abs(ep[1] - y_top) <= 6.0:
                    return True
    return False

def route_points(n_from, n_to, route, gap, m_override=None, port_offset=0.0,
                 rail_x=None, node_boxes=None, used_fb_ys=None, min_y=60.0,
                 routed_records=None):
    skip = {n_from["id"], n_to["id"]}
    boxes = node_boxes or []
    if route == "feedback_side" and rail_x is not None:
        sx_r = n_from["cx"] + n_from["w"] / 2.0
        sy_r = max(n_from["cy"] - n_from["h"] / 2 + 6,
                   min(n_from["cy"] + n_from["h"] / 2 - 6, n_from["cy"] + port_offset))
        tx_r = n_to["cx"] + n_to["w"] / 2.0
        ty_r = max(n_to["cy"] - n_to["h"] / 2 + 6,
                   min(n_to["cy"] + n_to["h"] / 2 - 6, n_to["cy"] + port_offset))
        p_fr = _avoid_mod_corner([sx_r, sy_r], n_from)
        p_tr = _avoid_mod_corner([tx_r, ty_r], n_to)

        from_clear = not _seg_hits_boxes(p_fr, [rail_x, p_fr[1]], boxes, skip, pad=2.0)
        to_clear = not _seg_hits_boxes([rail_x, p_tr[1]], p_tr, boxes, skip, pad=2.0)

        pts = []
        if from_clear:
            pts.extend([p_fr, [rail_x, p_fr[1]]])
        else:
            sx_c = max(n_from["cx"] - n_from["w"] / 2 + 10,
                       min(n_from["cx"] + n_from["w"] / 2 - 10, n_from["cx"] + port_offset))
            prefer_up = (n_from["cy"] >= n_to["cy"]) and not _node_top_occupied(n_from, routed_records)
            yb, yc = _side_channel_y(n_from, boxes, skip, rail_x, prefer_above=prefer_up, used_ys=used_fb_ys)
            p_fc = _avoid_mod_corner([sx_c, yb], n_from)
            pts.extend([p_fc, [p_fc[0], yc], [rail_x, yc]])

        if to_clear:
            pts.extend([[rail_x, p_tr[1]], p_tr])
        else:
            tx_c = max(n_to["cx"] - n_to["w"] / 2 + 10,
                       min(n_to["cx"] + n_to["w"] / 2 - 10, n_to["cx"] + port_offset))
            prefer_up = (n_to["cy"] <= n_from["cy"]) and not _node_top_occupied(n_to, routed_records)
            yb, yc = _side_channel_y(n_to, boxes, skip, rail_x, prefer_above=prefer_up, used_ys=used_fb_ys)
            p_tc = _avoid_mod_corner([tx_c, yb], n_to)
            pts.extend([[rail_x, yc], [p_tc[0], yc], p_tc])
        return pts

    if route in ("feedback", "arc"):
        m = m_override if m_override else (max(26.0, gap * 0.42) if route == "feedback" else 26.0)
        sx = max(n_from["cx"] - n_from["w"] / 2 + 10,
                 min(n_from["cx"] + n_from["w"] / 2 - 10, n_from["cx"] + port_offset))
        tx = max(n_to["cx"] - n_to["w"] / 2 + 10,
                 min(n_to["cx"] + n_to["w"] / 2 - 10, n_to["cx"] + port_offset))
        sy_top = n_from["cy"] - n_from["h"] / 2.0
        ty_top = n_to["cy"] - n_to["h"] / 2.0
        sy_bot = n_from["cy"] + n_from["h"] / 2.0
        ty_bot = n_to["cy"] + n_to["h"] / 2.0
        p0_up = _avoid_mod_corner([sx, sy_top], n_from)
        p1_up = _avoid_mod_corner([tx, ty_top], n_to)
        p0_dn = [sx, sy_bot]
        p1_dn = [tx, ty_bot]
        # Prefer obstacle-free arc with fewest edge crossings strictly below title safe zone (min_y)
        cand_arcs = []
        for dm in (0.0, 14.0, 28.0):
            yl_u = min(p0_up[1], p1_up[1]) - (m + dm)
            if yl_u >= float(min_y):
                cand_arcs.append((dm, 0, [p0_up, [p0_up[0], yl_u], [p1_up[0], yl_u], p1_up]))
            yl_d = max(p0_dn[1], p1_dn[1]) + (m + dm)
            cand_arcs.append((dm, 1, [p0_dn, [p0_dn[0], yl_d], [p1_dn[0], yl_d], p1_dn]))
        best_arc = None
        best_key = None
        for dm, side_i, arc in cand_arcs:
            hit = 1 if (boxes and _poly_hits_boxes(arc, boxes, skip, pad=2.0)) else 0
            cr = _poly_edge_crossings(arc, routed_records)
            k_sc = (hit, cr, dm, side_i)
            if best_key is None or k_sc < best_key:
                best_key = k_sc
                best_arc = arc
        return best_arc or cand_arcs[0][2]

    if n_from["id"] == n_to["id"]:
        # Clean autophosphorylation / autoregulation self-loop strictly anchored on node boundary
        hw = n_from["w"] / 2.0
        hh = n_from["h"] / 2.0
        cx, cy = n_from["cx"], n_from["cy"]
        dx_l = min(18.0, max(10.0, hw * 0.32))
        dy_l = min(14.0, max(8.0, hh * 0.34))
        y_top = cy - hh
        y_bot = cy + hh
        x_left = cx - hw
        p0_u = [cx - dx_l, y_top]
        p1_u = _avoid_mod_corner([cx + dx_l, y_top], n_from)
        if abs(p1_u[0] - p0_u[0]) < 12.0:
            p0_u = [max(cx - hw + 8.0, p1_u[0] - 18.0), y_top]
        m_loop = max(24.0, float(m_override or 26.0))
        left_loop = [[x_left, cy - dy_l], [x_left - m_loop, cy - dy_l],
                     [x_left - m_loop, cy + dy_l], [x_left, cy + dy_l]]
        top_loop = [p0_u, [p0_u[0], y_top - m_loop], [p1_u[0], y_top - m_loop], p1_u]
        bot_loop = [[cx - dx_l, y_bot], [cx - dx_l, y_bot + m_loop],
                    [cx + dx_l, y_bot + m_loop], [cx + dx_l, y_bot]]
        has_above = any(
            oid != n_from["id"] and bb[3] < y_top + 4.0 and bb[0] < cx + hw and bb[2] > cx - hw
            for oid, bb in boxes
        )
        cand_loops = []
        if (n_from.get("mods") or has_above) and x_left - m_loop >= 44.0:
            cand_loops.append(left_loop)
        if y_top - m_loop >= float(min_y):
            cand_loops.append(top_loop)
        cand_loops.append(bot_loop)
        if left_loop not in cand_loops and x_left - m_loop >= 44.0:
            cand_loops.append(left_loop)
        if boxes:
            for lp in cand_loops:
                if not _poly_hits_boxes(lp, boxes, skip, pad=2.0):
                    return lp
        return cand_loops[0]

    sx, sy = n_from["cx"], n_from["cy"]
    tx, ty = n_to["cx"], n_to["cy"]
    a = _avoid_mod_corner(boundary_point(n_from, tx, ty, port_offset=port_offset), n_from)
    b = _avoid_mod_corner(boundary_point(n_to, sx, sy, port_offset=port_offset), n_to)
    return [a, b]

def draw_edges(edges, placed, gap, prims, node_boxes=None, avoid_boxes=None,
               opts=None, plot_right=None, plot_left=None, width_map=None, min_y=60.0):
    """Draw edges and return (used_types, routed_records, max_rail_x)."""
    nmap = {n["id"]: n for n in placed}
    used = []
    arc_by_comp = {}
    side_rail_i = 0
    max_rail_x = plot_right or 0.0
    # Compute weight range if edges carry numeric weight/confidence or width_map is given
    wvals = [float(e["weight"] if e.get("weight") is not None else e["confidence"])
             for e in edges
             if isinstance(e.get("weight") if e.get("weight") is not None else e.get("confidence"), (int, float))]
    wm = width_map or {}
    w_lo = float(wm["min"]) if wm.get("min") is not None else (min(wvals) if wvals else 0.0)
    w_hi = float(wm["max"]) if wm.get("max") is not None else (max(wvals) if wvals else 1.0)
    have_wmap = bool(wvals) or (wm.get("min") is not None and wm.get("max") is not None)
    used_detour_xs = []
    used_fb_ys = []
    opts = opts or {}
    auto_dash = bool(opts.get("evidence_auto_style", True))
    routed_records = []
    lbl_avoid = list(node_boxes or []) + list(avoid_boxes or [])

    pair_totals = {}
    for e in edges:
        key = tuple(sorted((str(e.get("from")), str(e.get("to")))))
        pair_totals[key] = pair_totals.get(key, 0) + 1
    pair_seen = {}

    for e in edges:
        a, b = nmap.get(e.get("from")), nmap.get(e.get("to"))
        if not a or not b:
            continue
        et = e.get("type", "other")
        st = EDGE_STYLES.get(et, EDGE_STYLES["other"])
        if et not in used:
            used.append(et)

        key = tuple(sorted((str(e.get("from")), str(e.get("to")))))
        k = pair_seen.get(key, 0)
        pair_seen[key] = k + 1
        tot = pair_totals[key]
        same_row = abs(a["cy"] - b["cy"]) <= (a["h"] + b["h"]) / 2.0 + 12
        max_poff = (max(7.0, min(a["h"], b["h"]) / 2.0 - 8.0) if same_row
                    else min(24.0, max(12.0, min(a["w"], b["w"]) / 2.0 - 12.0)))
        step_cap = 18.0 if same_row else 24.0
        step_poff = min(step_cap, (2.0 * max_poff) / max(1, tot - 1)) if tot > 1 else 0.0
        port_off = ((k - (tot - 1) / 2.0) * step_poff) if tot > 1 else 0.0

        req_route = e.get("route", "direct")
        eff_route = req_route

        if a["id"] == b["id"]:
            eff_route = "self_loop"
            pts = route_points(a, b, "direct", gap, m_override=26.0, node_boxes=node_boxes, min_y=min_y, routed_records=routed_records)
        elif eff_route == "feedback" and not same_row:
            if plot_right is not None:
                eff_route = "feedback_side"
                rail_x = plot_right + 28.0 + 42.0 * side_rail_i
                side_rail_i += 1
                max_rail_x = max(max_rail_x, rail_x + 28.0)
                pts = route_points(a, b, "feedback_side", gap, port_offset=port_off,
                                   rail_x=rail_x, node_boxes=node_boxes, used_fb_ys=used_fb_ys, min_y=min_y, routed_records=routed_records)
            else:
                eff_route = "direct"
                pts = route_points(a, b, "direct", gap, port_offset=port_off, min_y=min_y, routed_records=routed_records)
        elif eff_route == "arc" and not same_row:
            eff_route = "direct"
            pts = route_points(a, b, "direct", gap, port_offset=port_off, min_y=min_y, routed_records=routed_records)
        elif eff_route in ("feedback", "arc"):
            cid = a.get("compartment") or "_"
            arc_by_comp[cid] = arc_by_comp.get(cid, 0) + 1
            m_ov = 26.0 + 20.0 * (arc_by_comp[cid] - 1)
            pts = route_points(a, b, eff_route, gap, m_override=m_ov, port_offset=port_off, node_boxes=node_boxes, min_y=min_y, routed_records=routed_records)
        else:
            pts = route_points(a, b, "direct", gap, port_offset=port_off, min_y=min_y, routed_records=routed_records)
            skip_ids = {e.get("from"), e.get("to")}
            if node_boxes and opts.get("auto_arc", True):
                if _seg_hits_boxes(pts[0], pts[-1], node_boxes, skip=skip_ids, pad=2.0):
                    if same_row:
                        cid = a.get("compartment") or "_"
                        arc_by_comp[cid] = arc_by_comp.get(cid, 0) + 1
                        m_ov = 26.0 + 20.0 * (arc_by_comp[cid] - 1)
                        pts = route_points(a, b, "arc", gap, m_override=m_ov, port_offset=port_off, node_boxes=node_boxes, min_y=min_y, routed_records=routed_records)
                        eff_route = "arc"
                    else:
                        det = _route_cross_detour(
                            a, b, node_boxes, skip_ids,
                            plot_left=plot_left, plot_right=plot_right,
                            used_xs=used_detour_xs
                        )
                        if det is not None:
                            pts = det
                            eff_route = "detour"
                            max_rail_x = max(max_rail_x, max(q[0] for q in pts) + 12.0)

        # Keep incoming top-edge arrival clear of destination node's top-right PTM badges
        b_mods = b.get("mods") or []
        if b_mods and len(pts) == 2 and b.get("shape", "rect") != "ellipse":
            b_top = b["cy"] - b["h"] / 2.0
            b_right = b["cx"] + b["w"] / 2.0
            from_right = pts[0][0] > pts[-1][0]
            badge_span = (34.0 if from_right else 22.0) + 19.0 * max(0, len(b_mods) - 1)
            if abs(pts[-1][1] - b_top) < 3.0 and pts[-1][0] > b_right - badge_span:
                pts = [pts[0], [max(b["cx"] - b["w"] / 2.0 + 12.0, b_right - badge_span - 8.0), b_top]]

        routed_records.append({"from": e.get("from"), "to": e.get("to"), "pts": pts, "route": eff_route})

        dashed = bool(e.get("dashed")) or bool(st.get("default_dashed") and e.get("dashed") is not False)
        if auto_dash and not dashed:
            ev = str(e.get("evidence") or "").lower()
            if ev in ("reported", "inferred", "indirect", "putative", "predicted", "uncertain", "weak"):
                dashed = True
        dotted = bool(e.get("dotted")) or (
            auto_dash and str(e.get("evidence") or "").lower() == "weak")
        col = e.get("color") or st["color"]

        tip = pts[-1]
        seg_dir = norm(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        mlen = MARKER_LEN.get(st["end"], 12)
        line_end = [tip[0] - seg_dir[0] * mlen, tip[1] - seg_dir[1] * mlen]
        start_pt = pts[0]
        if st.get("both"):
            d0 = norm(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            start_pt = [pts[0][0] + d0[0] * mlen, pts[0][1] + d0[1] * mlen]
        body = [start_pt] + pts[1:-1] + [line_end]
        if len(body) >= 3:
            body = _round_corners(body, radius=10.0)

        ew = e.get("stroke_w")
        if ew is None:
            raw_w = e.get("weight") if e.get("weight") is not None else e.get("confidence")
            if have_wmap and isinstance(raw_w, (int, float)):
                tw = (float(raw_w) - w_lo) / ((w_hi - w_lo) or 1.0)
                tw = min(1.0, max(0.0, tw))
                ew = round(1.5 + 3.1 * tw, 2)
            else:
                ew = 2.3
        edge_meta = {
            "edge-type": et,
            "from": e.get("from"),
            "to": e.get("to"),
            "evidence": e.get("evidence"),
            "source": e.get("source"),
            "weight": e.get("weight") if e.get("weight") is not None else e.get("confidence"),
        }
        prims.append({"op": "polyline", "pts": body, "stroke": col, "stroke_w": float(ew),
                      "dashed": dashed, "dotted": dotted, "role": "edge", "layer": "layer-edges",
                      "_etype": et, "_id": f"edge-{len(prims)}-{e.get('from')}-{e.get('to')}",
                      "_meta": edge_meta})
        _draw_marker(prims, st, tip, seg_dir, col)
        if st.get("both"):
            d0 = norm(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            _draw_marker(prims, st, pts[0], (-d0[0], -d0[1]), col)
        elif st.get("start_dot"):
            d0 = norm(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            cx0, cy0 = pts[0][0] + d0[0] * 4.5, pts[0][1] + d0[1] * 4.5
            prims.append({"op": "circle", "cx": cx0, "cy": cy0, "r": 3.8, "fill": "#ffffff",
                          "stroke": col, "stroke_w": 1.8, "role": "edge_marker", "layer": "layer-edges"})
        elif st.get("start_bar"):
            d0 = norm(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            nx0, ny0 = perp(*d0)
            cx0, cy0 = pts[0][0] + d0[0] * 4.5, pts[0][1] + d0[1] * 4.5
            prims.append({"op": "polyline",
                          "pts": [[cx0 + nx0 * 5.5, cy0 + ny0 * 5.5], [cx0 - nx0 * 5.5, cy0 - ny0 * 5.5]],
                          "stroke": col, "stroke_w": 2.4, "role": "edge_marker", "layer": "layer-edges"})

        lbl = e.get("label") or ""
        ev_raw = str(e.get("evidence") or "").strip()
        _IGN_EV = {"direct", "solid", "confirmed", "experimental", "strong", "validated", "verified", "known", "canonical"}
        if not lbl and ev_raw and ev_raw.lower() not in _IGN_EV:
            lbl = f"[{ev_raw}]"
        _edge_label(prims, pts, lbl, e, col, route=eff_route,
                    tip_style=False,
                    node_boxes=lbl_avoid, port_off=port_off, min_y=min_y)
    return used, routed_records, max_rail_x

def _draw_marker(prims, st, tip, dirv, col, role="edge_marker", layer="layer-edges"):
    end = st["end"]
    if end == "arrow":
        prims.append({"op": "poly", "pts": arrow_poly(tip, dirv), "fill": col,
                      "stroke": "none", "stroke_w": 0, "role": role, "layer": layer})
    elif end == "open":
        prims.append({"op": "poly", "pts": arrow_poly(tip, dirv), "fill": "#ffffff",
                      "stroke": col, "stroke_w": 2.0, "role": role, "layer": layer})
    elif end == "bar":
        c = [tip[0] - dirv[0] * 1.5, tip[1] - dirv[1] * 1.5]
        nx, ny = perp(*dirv)
        prims.append({"op": "polyline", "pts": [[c[0] + nx * 7, c[1] + ny * 7],
                     [c[0] - nx * 7, c[1] - ny * 7]], "stroke": col, "stroke_w": 3.5,
                     "role": role, "layer": layer})
    elif end == "circle":
        tag = st.get("tag")
        r = 7.5 if tag else 5.2
        c = [tip[0] - dirv[0] * (r + 0.5), tip[1] - dirv[1] * (r + 0.5)]
        prims.append({"op": "circle", "cx": c[0], "cy": c[1], "r": r, "fill": col,
                      "stroke": "#ffffff", "stroke_w": 1.2, "role": role, "layer": layer})
        if tag:
            prims.append({"op": "text", "x": c[0], "y": c[1], "s": str(tag),
                          "size": 8.5 if len(str(tag)) > 1 else 9.5,
                          "anchor": "middle", "fill": "#ffffff", "weight": "bold",
                          "halo": False, "role": "mod", "layer": layer})
    elif end == "open_dot":
        c = [tip[0] - dirv[0] * 4.5, tip[1] - dirv[1] * 4.5]
        prims.append({"op": "circle", "cx": c[0], "cy": c[1], "r": 4.2, "fill": "#ffffff",
                      "stroke": col, "stroke_w": 1.8, "role": role, "layer": layer})
    elif end == "diamond":
        prims.append({"op": "poly", "pts": diamond_poly(tip, dirv), "fill": "#ffffff",
                      "stroke": col, "stroke_w": 2.0, "role": role, "layer": layer})
    elif end == "cross":
        c = [tip[0] - dirv[0] * 5.0, tip[1] - dirv[1] * 5.0]
        r = 5.5
        prims.append({"op": "polyline", "pts": [[c[0] - r, c[1] - r], [c[0] + r, c[1] + r]],
                      "stroke": col, "stroke_w": 2.4, "role": role, "layer": layer})
        prims.append({"op": "polyline", "pts": [[c[0] - r, c[1] + r], [c[0] + r, c[1] - r]],
                      "stroke": col, "stroke_w": 2.4, "role": role, "layer": layer})

def _find_vertical_rail(pts):
    best_i, best_len = 0, -1.0
    for i in range(len(pts) - 1):
        if abs(pts[i][0] - pts[i + 1][0]) < 1.5:
            dy = abs(pts[i + 1][1] - pts[i][1])
            if dy > best_len:
                best_len = dy
                best_i = i
    mx = pts[best_i][0]
    my = (pts[best_i][1] + pts[best_i + 1][1]) / 2.0
    return mx, my

def _longest_segment(pts):
    best_i, best_len = 0, -1.0
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if d > best_len:
            best_len = d
            best_i = i
    return pts[best_i], pts[best_i + 1]

def _edge_label(prims, pts, lbl, e, col, route="direct", tip_style=False, node_boxes=None, port_off=0.0, min_y=56.0):
    if not lbl:
        return
    txt = str(lbl)
    ev = str(e.get("evidence") or "").strip()
    _IGN_EV = {"direct", "solid", "confirmed", "experimental", "strong", "validated", "verified", "known", "canonical"}
    if ev and ev.lower() not in _IGN_EV and ev.lower() not in txt.lower():
        txt += f" [{ev}]"

    if route == "feedback_side":
        mx, my = _find_vertical_rail(pts)
        anchors = [(mx + 13.0, my), (mx + 13.0, my - 38.0), (mx + 13.0, my + 38.0),
                   (mx + 13.0, my - 76.0), (mx + 13.0, my + 76.0)]
    elif route in ("feedback", "arc", "self_loop"):
        if route == "self_loop" and abs(pts[1][0] - pts[2][0]) < 2.0:
            # Side-mounted self-loop: place label cleanly beside the outer vertical arm
            is_left = pts[1][0] < pts[0][0]
            lx_off = -28.0 if is_left else 28.0
            my_lp = (pts[1][1] + pts[2][1]) / 2.0
            anchors = [(pts[1][0] + lx_off, my_lp), (pts[1][0] + lx_off, my_lp - 20.0), (pts[1][0] + lx_off, my_lp + 20.0)]
        else:
            is_below = pts[1][1] > pts[0][1]
            anchors = [((pts[1][0] + pts[2][0]) / 2.0, pts[1][1] + (13.0 if is_below else -11.0))]
    elif route == "detour":
        p0, p1 = _longest_segment(pts)
        anchors = []
        for t in (0.30, 0.70, 0.50):
            ax = p0[0] + (p1[0] - p0[0]) * t
            ay = p0[1] + (p1[1] - p0[1]) * t
            if abs(p1[0] - p0[0]) < 12.0:  # vertical corridor segment -> place cleanly beside or on pill
                anchors.extend([(ax, ay), (ax - 34, ay), (ax + 34, ay)])
            else:
                anchors.append((ax, ay - 11))
    elif tip_style:
        dirv = norm(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        nx, ny = perp(*dirv)
        anchors = [(pts[-1][0] - dirv[0] * 16 + nx * 14,
                    pts[-1][1] - dirv[1] * 16 + ny * 14)]
    else:
        dx = abs(pts[1][0] - pts[0][0])
        dy = abs(pts[1][1] - pts[0][1])
        if dx < 24.0 and dy > 24.0:
            # Near-vertical edge: centered pill on midpoint works cleanly, plus side offsets if needed
            mx = (pts[0][0] + pts[1][0]) / 2.0
            my = (pts[0][1] + pts[1][1]) / 2.0
            side_x = 28.0 if port_off >= 0 else -28.0
            anchors = [(mx + side_x, my), (mx, my), (mx - side_x, my),
                       (mx, pts[0][1] + (pts[1][1] - pts[0][1]) * 0.38),
                       (mx, pts[0][1] + (pts[1][1] - pts[0][1]) * 0.62)] if port_off else [
                       (mx, my), (mx + 26, my), (mx - 26, my),
                       (mx, pts[0][1] + (pts[1][1] - pts[0][1]) * 0.38),
                       (mx, pts[0][1] + (pts[1][1] - pts[0][1]) * 0.62)]
        else:
            # Symmetric label offset for bidirectional/parallel horizontal edges (lower edge -> below)
            y_off = 13.0 if port_off > 0 else -11.0
            alt_off = -11.0 if port_off > 0 else 13.0
            anchors = [(pts[0][0] + (pts[1][0] - pts[0][0]) * t,
                        pts[0][1] + (pts[1][1] - pts[0][1]) * t + y_off) for t in (0.5, 0.35, 0.65)] + [
                       (pts[0][0] + (pts[1][0] - pts[0][0]) * 0.5,
                        pts[0][1] + (pts[1][1] - pts[0][1]) * 0.5 + alt_off)]
    _label_no_overlap(prims, anchors, txt, col, node_boxes=node_boxes or [],
                      rotate=(-90 if route == "feedback_side" else None), min_y=min_y)

def _label_no_overlap(prims, anchors, txt, col, node_boxes=None, rotate=None, min_y=56.0):
    """Place label near the first clear anchor; shifts until clear of texts, markers, and node boxes."""
    from viz_geom import text_bbox, overlap, bbox_of
    existing = []
    for p in prims:
        if p["op"] == "text":
            bb_p = bbox_of(p)
            if bb_p:
                existing.append(bb_p)
        elif p.get("role") == "edge_marker":
            mb = bbox_of(p)
            if mb:
                existing.append([mb[0] - 4, mb[1] - 4, mb[2] + 4, mb[3] + 4])
    nodes = [nb[1] if isinstance(nb, tuple) and len(nb) == 2 and isinstance(nb[1], list)
             else nb for nb in (node_boxes or [])]
    if rotate:
        for ax, ay in anchors:
            tb = text_bbox(0, 0, txt, 12.0, "middle")
            rw, rh = tb[2] - tb[0], tb[3] - tb[1]
            rbb = [ax - rh / 2.0, ay - rw / 2.0, ax + rh / 2.0, ay + rw / 2.0]
            if not any(overlap(rbb, eb, tol=-2.0) for eb in existing):
                _emit_label(prims, ax, ay, txt, col, rotate=rotate)
                return
        ax, ay = anchors[0]
        _emit_label(prims, ax, ay, txt, col, rotate=rotate)
        return
    shifts = ((0, 0), (0, -18), (0, 18), (-26, 0), (26, 0), (0, -36), (0, 36),
              (-44, 0), (44, 0), (-26, -20), (26, -20), (-26, 20), (26, 20),
              (0, -54), (0, 54), (-62, 0), (62, 0), (-44, -20), (44, -20),
              (-44, 20), (44, 20), (0, -72), (0, 72))
    best = None
    for ax, ay in anchors:
        for dx, dy in shifts:
            bb = text_bbox(ax + dx, ay + dy, txt, 12.0, "middle")
            oob = (10 if (bb[0] < 8.0 or bb[1] < float(min_y)) else 0)
            hits = oob + sum(1 for eb in existing if overlap(bb, eb, tol=-3.0)) + \
                   sum(1 for nb in nodes if overlap(bb, nb, tol=-2.0))
            if hits == 0:
                _emit_label(prims, ax + dx, ay + dy, txt, col)
                return
            if best is None or hits < best[0]:
                best = (hits, ax + dx, ay + dy)
    _emit_label(prims, best[1], best[2], txt, col)

def _emit_label(prims, x, y, txt, col, rotate=None):
    from viz_geom import text_bbox
    if not rotate:
        bb = text_bbox(x, y, txt, 12.0, "middle")
        prims.append({
            "op": "rect", "x": bb[0] - 4.0, "y": bb[1] - 1.5,
            "w": (bb[2] - bb[0]) + 8.0, "h": (bb[3] - bb[1]) + 3.0,
            "rx": 4.0, "fill": "#ffffff", "stroke": "none", "stroke_w": 0,
            "opacity": 0.90, "role": "edge_label_bg", "layer": "layer-annotations"
        })
    d = {"op": "text", "x": x, "y": y, "s": txt, "size": 12.0, "anchor": "middle",
         "fill": col, "weight": "bold", "role": "edge_label", "layer": "layer-annotations",
         "_id": f"edgelabel-{len(prims)}"}
    if rotate:
        d["rotate"] = rotate
    prims.append(d)
