#!/usr/bin/env python3
"""build_figure.py — spec JSON -> layered SVG + embedded-font PDF + PNG + geometry.json.

Usage: python3 build_figure.py spec.json --out-dir DIR --stem name [--geom geometry.json]
Spec schema: see references/result_schema.md (section "figure spec").
"""
import argparse, json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, FancyBboxPatch, Ellipse, Polygon
import fig_style as S
import fig_layout as L
import fig_draw as D
import fig_chart as C

SCALE_KEYS = ("fontsize", "node_gap_x", "node_gap_y", "pad_x", "pad_y",
              "arrow_len", "arrow_w", "tbar_len")


def scaled_style(style, s):
    st = dict(style)
    for k in SCALE_KEYS:
        st[k] = style[k] * s
    return st


def _classify_edges(panel, rank, back, layers=None):
    """Determine edge routing without mutating caller's spec unnecessarily."""
    edges = panel.get("edges", [])
    routes = []
    pos_in_layer = {}
    for r, members in (layers or {}).items():
        for i, nid in enumerate(members):
            pos_in_layer[nid] = i
    # Count parallel/bidirectional pairs
    pair_list = {}
    for idx, e in enumerate(edges):
        key = tuple(sorted((e["from"], e["to"])))
        pair_list.setdefault(key, []).append(idx)

    detour_count = 0
    bypass_count = 0
    for idx, e in enumerate(edges):
        r = e.get("route")
        u, v = e["from"], e["to"]
        key = tuple(sorted((u, v)))
        mates = pair_list[key]
        if not r:
            rk = rank.get(v, 0) - rank.get(u, 0)
            if u == v:
                r = "self_loop"
            elif rk == 0 and abs(pos_in_layer.get(u, 0) - pos_in_layer.get(v, 0)) == 1:
                # Directly adjacent nodes in the same rank -> clean straight edge
                r = "straight"
            elif abs(rk) == 1 and len(mates) >= 2:
                # Adjacent-rank mutual/parallel pair (e.g. p53 <-> MDM2) -> tight parallel arrows, no outer detour!
                r = "straight"
            elif (u, v) in back or rk <= 0:
                r = "detour"
            elif rk >= 2:
                r = "elbow"
            else:
                r = "straight"
        if len(mates) > 1 and r == "straight":
            pos_i = mates.index(idx)
            poff = (pos_i - (len(mates) - 1) / 2.0) * 2.6
        else:
            poff = 0.0
        dlane = detour_count if r == "detour" else None
        if r == "detour":
            detour_count += 1
        blane = bypass_count if r == "elbow" else 0
        if r == "elbow":
            bypass_count += 1
        routes.append({"route": r, "detour_lane": dlane, "bypass_lane": blane,
                       "parallel_off": poff})
    return routes, detour_count, bypass_count


def layout_schematic(panel, meas, style, wrap_w=None):
    nodes, edges = panel.get("nodes", []), panel.get("edges", [])
    rank, back = L.build_graph(nodes, edges)
    layers = L.order_layers(nodes, edges, rank, groups=panel.get("groups"))
    sizes = L.size_nodes(nodes, meas, style)
    pos, tw, th = L.assign_xy(nodes, edges, layers, sizes,
                              panel.get("direction", "LR"),
                              style["node_gap_x"], style["node_gap_y"], wrap_w,
                              groups=panel.get("groups"), meas=meas)
    routes, n_detour, n_bypass = _classify_edges(panel, rank, back, layers=layers)
    return pos, sizes, tw, th, back, routes, n_detour, n_bypass


def _group_nest_depths(groups, pos):
    """Compute nesting depth per group (0 = innermost, >0 = encloses inner group(s))."""
    mems = []
    for g in groups:
        m = {x for x in g.get("members", []) if x in pos}
        mems.append(m)
    depths = [0] * len(groups)
    # Fixed-point depth propagation so outer > inner strictly
    for _ in range(len(groups)):
        changed = False
        for i in range(len(groups)):
            if not mems[i]:
                continue
            for j in range(len(groups)):
                if i != j and mems[j] and mems[j] < mems[i]:
                    if depths[i] < depths[j] + 1:
                        depths[i] = depths[j] + 1
                        changed = True
        if not changed:
            break
    return depths


def _group_padding(panel, pos, sizes, meas=None):
    """Compute extra margins (left, right, bottom, top) required by group boxes (incl. nesting)."""
    if not pos:
        return 0.0, 0.0, 0.0, 0.0
    nx0 = min(pos[k][0] - sizes[k]["w"] / 2.0 for k in pos)
    nx1 = max(pos[k][0] + sizes[k]["w"] / 2.0 for k in pos)
    ny0 = min(pos[k][1] - sizes[k]["h"] / 2.0 for k in pos)
    ny1 = max(pos[k][1] + sizes[k]["h"] / 2.0 for k in pos)
    pl = pr = pb = pt = 0.0
    groups = panel.get("groups", [])
    depths = _group_nest_depths(groups, pos)
    for g, nd in zip(groups, depths):
        mem = [m for m in g.get("members", []) if m in pos]
        if not mem:
            continue
        pad = 2.6 + nd * 2.5
        hdr = 3.8 + nd * 3.8 + (1.4 if g.get("membrane") else 0.0)
        x0 = min(pos[m][0] - sizes[m]["w"] / 2.0 for m in mem)
        x1 = max(pos[m][0] + sizes[m]["w"] / 2.0 for m in mem)
        y0 = min(pos[m][1] - sizes[m]["h"] / 2.0 for m in mem)
        y1 = max(pos[m][1] + sizes[m]["h"] / 2.0 for m in mem)
        lbl = str(g.get("label", g.get("id", "")))
        lbl_w, _ = D._estimate_label_size(lbl, 7.2, meas)
        gw = max((x1 - x0) + 2.0 * pad, lbl_w * 1.12 + 4.4)
        cx = (x0 + x1) / 2.0
        gx0, gx1 = cx - gw / 2.0, cx + gw / 2.0
        gy0, gy1 = y0 - pad, y1 + pad + hdr
        pl = max(pl, nx0 - gx0)
        pr = max(pr, gx1 - nx1)
        pb = max(pb, ny0 - gy0)
        pt = max(pt, gy1 - ny1)
    return pl, pr, pb, pt


def legend_space(panel, meas, avail_w):
    lm = S.legend_dims(panel, meas, avail_w)
    return (lm["h"] + 4.0) if lm else 0.0


def draw_panel_legend(ax, panel, meas, avail_w):
    lm = S.legend_dims(panel, meas, avail_w)
    if not lm:
        return None
    fs, lh, w, h = lm["fs"], lm["lh"], lm["w"], lm["h"]
    glyph_w, item_gap = lm["glyph_w"], lm["item_gap"]
    x0, y0 = 1.0, 0.6
    r = Rectangle((x0, y0), w, h, fc=S.STYLE["legend_bg"],
                  ec=S.STYLE["legend_stroke"], lw=0.8, zorder=3.0)
    ax.add_patch(r)
    r.set_gid("legend-box")
    tl = ax.text(x0 + 2.2, y0 + h - 2.2, panel["legend"].get("title", "Legend"),
                 fontsize=fs, fontweight="bold", va="center",
                 color=S.STYLE["title_color"], zorder=4.0)
    tl.set_gid("legend-title")
    items = panel["legend"].get("items", [])
    inner_w = w - 4.4
    xi, yi = x0 + 2.2, y0 + h - 2.2 - lh
    for i, it in enumerate(items):
        lab = it.get("label", "")
        lab_w = meas.text_mm(lab, fontsize=fs)[0]
        need = glyph_w + lab_w + item_gap
        if xi > x0 + 2.3 and (xi - (x0 + 2.2)) + glyph_w + lab_w > inner_w:
            xi = x0 + 2.2
            yi -= lh
        if (it.get("fill") or it.get("shape")) and not it.get("kind"):
            # Node shape/color swatch legend item
            sw_fill = it.get("fill", "#EAF2FB")
            sw_ec = it.get("stroke", S.STYLE["node_stroke"])
            sw_shape = S.canonical_shape(it.get("shape", "round"))
            sx0, sy0, sw_w, sw_h = xi + 1.2, yi - 1.45, 7.8, 2.9
            scx, scy = sx0 + sw_w / 2.0, yi
            if sw_shape == "ellipse":
                sw = Ellipse((scx, scy), sw_w, sw_h * 1.08, fc=sw_fill, ec=sw_ec, lw=0.9, zorder=5.0)
            elif sw_shape == "hexagon":
                bevel = 1.6
                sw = Polygon([(sx0 + bevel, sy0), (sx0 + sw_w - bevel, sy0), (sx0 + sw_w, scy),
                              (sx0 + sw_w - bevel, sy0 + sw_h), (sx0 + bevel, sy0 + sw_h), (sx0, scy)],
                             closed=True, fc=sw_fill, ec=sw_ec, lw=0.9, zorder=5.0)
            elif sw_shape == "diamond":
                sw = Polygon([(scx, sy0 + sw_h * 1.15), (sx0 + sw_w, scy),
                              (scx, sy0 - sw_h * 0.15), (sx0, scy)],
                             closed=True, fc=sw_fill, ec=sw_ec, lw=0.9, zorder=5.0)
            elif sw_shape in ("round", "stadium", "complex"):
                r_sz = sw_h / 2.0 if sw_shape == "stadium" else 0.8
                sw = FancyBboxPatch((sx0, sy0), sw_w, sw_h,
                                    boxstyle="round,pad=0,rounding_size=%.2f" % r_sz,
                                    fc=sw_fill, ec=sw_ec, lw=0.9, zorder=5.0)
                ax.add_patch(sw)
                sw.set_gid("legend-item-%d-swatch" % i)
                if sw_shape == "complex":
                    sw2 = FancyBboxPatch((sx0 + 0.55, sy0 + 0.45), sw_w - 1.1, sw_h - 0.9,
                                         boxstyle="round,pad=0,rounding_size=0.45",
                                         fc="none", ec=sw_ec, lw=0.55, zorder=5.1)
                    ax.add_patch(sw2)
                    sw2.set_gid("legend-item-%d-swatch-inner" % i)
            else:
                sw = Rectangle((sx0, sy0), sw_w, sw_h, fc=sw_fill, ec=sw_ec, lw=0.9, zorder=5.0)
                ax.add_patch(sw)
                sw.set_gid("legend-item-%d-swatch" % i)
                if sw_shape == "gene":
                    bar_g = Rectangle((sx0, sy0 + sw_h - 0.7), sw_w, 0.7,
                                      fc=sw_ec, ec="none", zorder=5.1)
                    ax.add_patch(bar_g)
                    bar_g.set_gid("legend-item-%d-swatch-accent" % i)
            if sw_shape not in ("round", "stadium", "complex", "rect", "gene"):
                ax.add_patch(sw)
                sw.set_gid("legend-item-%d-swatch" % i)
        else:
            ck = S.canonical_edge_kind(it.get("kind", "activates"))
            ek = S.EDGE_KINDS.get(ck, S.EDGE_KINDS["activates"])
            col = S.edge_color(it)
            x_a, x_b = xi, xi + 10.5
            head = {"arrow": "arrow", "tbar": "tbar", "arrow_open": "arrow_open",
                    "arrow_both": "arrow", "none": None}[ek["head"]]
            lx_a = x_a + (1.6 if ek["head"] == "arrow_both" else 0.0)
            lx_b = x_b - (1.6 if head == "arrow" else 0.0)
            ln = Line2D([lx_a, lx_b], [yi, yi], lw=1.4, color=col,
                        ls=ek["ls"], solid_capstyle="round", zorder=5.0)
            ax.add_line(ln)
            ln.set_gid("legend-item-%d-line" % i)
            if head:
                D._arrow_head(ax, x_b, yi, 1.0, 0.0,
                              "legend-item-%d-head" % i, head, color=col, zorder=6.0)
            if ek["head"] == "arrow_both":
                D._arrow_head(ax, x_a, yi, -1.0, 0.0,
                              "legend-item-%d-head2" % i, "arrow", color=col, zorder=6.0)
        t2 = ax.text(xi + glyph_w, yi, lab, fontsize=fs, va="center",
                     color=S.STYLE["node_text"], zorder=5.0)
        t2.set_gid("legend-item-%d" % i)
        xi += need
    return [round(x0, 2), round(y0, 2), round(x0 + w, 2), round(y0 + h, 2)]


def _compute_panel_metrics(panel, meas, style, avail_w, wrap_w=None):
    """Single source of truth for schematic panel offsets & total inner height."""
    direction = str(panel.get("direction", "LR")).upper()
    pos, sizes, tw, th, back, routes, n_detour, n_bypass = layout_schematic(
        panel, meas, style, wrap_w)
    pl, pr, pb, pt = _group_padding(panel, pos, sizes, meas=meas)
    leg_h = legend_space(panel, meas, avail_w)
    is_tb = (direction == "TB")
    # TB routes feedback/skip edges along balanced left/right vertical outer side channels;
    # wrapped multi-row LR panels also reserve symmetric side channels for cross-row feedback/bypass!
    is_wrapped_lr = (not is_tb) and bool(wrap_w)
    side_lanes = (n_detour + n_bypass) if (is_tb or is_wrapped_lr) else 0
    if side_lanes > 0:
        if is_tb:
            r_lanes = (side_lanes + 1) // 2
            l_lanes = side_lanes // 2
            pr += 5.8 + max(r_lanes - 1, 0) * 4.2
            if l_lanes > 0:
                pl += 5.8 + max(l_lanes - 1, 0) * 4.2
        else:
            pr += 6.2
            pl += 6.2
    detour_band = 0.0 if is_tb else ((6.0 + max(n_detour - 1, 0) * 4.2) if n_detour else 0.0)
    has_labels = any(e.get("label") for e in panel.get("edges", []))
    has_badges = any(n.get("badge") for n in panel.get("nodes", []))
    top_lanes = 0 if is_tb else (n_bypass + (1 if n_detour else 0))
    top_pad = max(pt, 4.5 if (has_labels or has_badges) else 2.0) + (
        5.5 + max(top_lanes - 1, 0) * 3.2 if top_lanes else 0.0)
    bot_pad = max(pb, 2.0) + detour_band + leg_h
    content_w = tw + pl + pr
    x_shift = max((avail_w - content_w) / 2.0, 0.0) + pl
    y_shift = bot_pad
    total_inner_h = th + bot_pad + top_pad
    return {
        "pos": pos, "sizes": sizes, "tw": tw, "th": th,
        "content_w": content_w, "total_inner_h": total_inner_h,
        "x_shift": x_shift, "y_shift": y_shift, "leg_h": leg_h,
        "detour_band": detour_band, "routes": routes, "direction": direction,
        "n_detour": n_detour, "n_bypass": n_bypass, "pt": pt, "pb": pb,
        "pl": pl, "pr": pr,
    }


def draw_schematic(ax, panel, meas, style, avail_w, wrap_w=None):
    met = _compute_panel_metrics(panel, meas, style, avail_w, wrap_w)
    xs, ys = met["x_shift"], met["y_shift"]
    pos = {k: (v[0] + xs, v[1] + ys) for k, v in met["pos"].items()}
    sizes = met["sizes"]
    shapes = {n["id"]: n.get("shape", "round") for n in panel.get("nodes", [])}

    # Draw groups outer-first (zorder 0.25-0.60); register headers so edge labels avoid them
    group_geoms = {}
    placed_labels = []
    groups_raw = panel.get("groups", [])
    depths = _group_nest_depths(groups_raw, pos)
    for g, nd in sorted(zip(groups_raw, depths), key=lambda t: -t[1]):
        mem = [m for m in g.get("members", []) if m in pos]
        if not mem:
            continue
        x0 = min(pos[m][0] - sizes[m]["w"] / 2.0 for m in mem)
        x1 = max(pos[m][0] + sizes[m]["w"] / 2.0 for m in mem)
        y0 = min(pos[m][1] - sizes[m]["h"] / 2.0 for m in mem)
        y1 = max(pos[m][1] + sizes[m]["h"] / 2.0 for m in mem)
        gbox, hbox = D.draw_group(ax, g, x0, y0, x1, y1, meas=meas, nest_depth=nd)
        group_geoms[g["id"]] = gbox
        placed_labels.append(hbox)

    obstacles = {k: (v[0] - sizes[k]["w"] / 2.0, v[1] - sizes[k]["h"] / 2.0,
                     v[0] + sizes[k]["w"] / 2.0, v[1] + sizes[k]["h"] / 2.0)
                 for k, v in pos.items()}
    # Register node badge bounding boxes so edge labels never collide with quantitative callouts
    for n in panel.get("nodes", []):
        nid = n["id"]
        if nid in pos and n.get("badge"):
            bb_b = D.badge_bbox(n, pos[nid][0], pos[nid][1], sizes[nid]["w"], sizes[nid]["h"], meas=meas)
            if bb_b:
                placed_labels.append(bb_b)
    min_node_y = min((b[1] for b in obstacles.values()), default=ys) - met["pb"]
    max_node_y = max((b[3] for b in obstacles.values()), default=ys) + met["pt"]
    max_node_x = max(
        [b[2] for b in obstacles.values()] + [gb[2] for gb in group_geoms.values()],
        default=xs + met["tw"],
    )
    min_node_x = min(
        [b[0] for b in obstacles.values()] + [gb[0] for gb in group_geoms.values()],
        default=xs,
    )
    tb_side_counter = [0, 0]

    # Draw edges with multi-lane detours strictly above legend box & unique top bypass lanes
    edges = panel.get("edges", [])
    routes = met["routes"]
    # Pre-assign staggered ports for cross-row corridor edges targeting the same node
    corridor_by_dst = {}
    for idx, e in enumerate(edges):
        u, v = e.get("from"), e.get("to")
        if u not in pos or v not in pos:
            continue
        r = routes[idx]["route"]
        src_bot = pos[u][1] - sizes[u]["h"] / 2.0
        dst_top = pos[v][1] + sizes[v]["h"] / 2.0
        if r in ("straight", "elbow") and src_bot > dst_top + 4.0 and abs(pos[v][0] - pos[u][0]) > 12.0:
            corridor_by_dst.setdefault(v, []).append((pos[u][0], idx))
    corridor_offs = {}
    for dst_id, items in corridor_by_dst.items():
        if len(items) > 1:
            # Sort left-to-right by source x for non-crossing target ports;
            # compute shared inter-row base_y from lowest source bottom so lanes never invert
            items.sort(key=lambda t: t[0])
            k_n = len(items)
            dst_top = pos[dst_id][1] + sizes[dst_id]["h"] / 2.0
            min_src_bot = min(pos[edges[eidx]["from"]][1] - sizes[edges[eidx]["from"]]["h"] / 2.0
                              for _, eidx in items)
            base_mid_y = (min_src_bot + dst_top) / 2.0
            dist_order = sorted(range(k_n), key=lambda i: abs(items[i][0] - pos[dst_id][0]))
            y_rank = {idx_in_items: r_i for r_i, idx_in_items in enumerate(dist_order)}
            for rank_i, (sx, eidx) in enumerate(items):
                x_off = (rank_i - (k_n - 1) / 2.0) * min(6.0, sizes[dst_id]["w"] * 0.48 / max(k_n - 1, 1))
                # Closest source (y_rank=0) gets highest lane; furthest gets lowest lane
                cy_abs = base_mid_y + ((k_n - 1) / 2.0 - y_rank[rank_i]) * 2.4
                corridor_offs[eidx] = (x_off, cy_abs)

    edge_records = []
    seen_eids = {}
    bypass_counter = [0]
    deferred_edges = []
    edge_segs_by_i = []
    for idx, e in enumerate(edges):
        if e["from"] not in pos or e["to"] not in pos:
            continue
        rc = routes[idx]
        e_draw = dict(e)
        e_draw["route"] = rc["route"]
        base_eid = "%s-%s" % (e["from"], e["to"])
        cnt = seen_eids.get(base_eid, 0)
        seen_eids[base_eid] = cnt + 1
        gid = base_eid if cnt == 0 else "%s-%d" % (base_eid, cnt)

        detour_y = None
        if rc["route"] == "detour":
            lane = rc["detour_lane"] or 0
            floor_y = met["leg_h"] + 1.5
            detour_y = max(min_node_y - 4.8 - lane * 4.2, floor_y)

        cx_off, cy_abs = corridor_offs.get(idx, (0.0, None))
        eg = D.draw_edge(
            ax, e_draw, pos[e["from"]], pos[e["to"]],
            shapes[e["from"]], shapes[e["to"]],
            sizes[e["from"]], sizes[e["to"]],
            gid, obstacles=obstacles, meas=meas,
            placed_labels=placed_labels,
            detour_y=detour_y, bypass_base_y=max_node_y + 3.4,
            bypass_counter=bypass_counter,
            parallel_off=rc["parallel_off"],
            corridor_x_off=cx_off, corridor_y=cy_abs,
            defer_label=True,
            direction=met["direction"],
            tb_right_x=max_node_x + 4.2,
            tb_left_x=min_node_x - 4.2,
            tb_side_counter=tb_side_counter)
        rec = {
            "id": gid, "label": e.get("label", ""),
            "kind": e.get("kind", "activates"),
            "subject": e["from"], "object": e["to"],
            "source": e.get("source"), **eg
        }
        edge_records.append(rec)
        pts_i = [tuple(p) for p in eg["points"]]
        edge_segs_by_i.append([(pts_i[k], pts_i[k + 1]) for k in range(len(pts_i) - 1)])
        deferred_edges.append((len(edge_records) - 1, e_draw, pts_i, gid, rc["route"],
                               S.edge_color(e), rec))

    # Pass 2: place edge labels with full visibility of ALL edge segments & compartment borders
    group_border_segs = []
    for gb in group_geoms.values():
        gx0, gy0, gx1, gy1 = gb
        group_border_segs.extend([
            ((gx0, gy0), (gx1, gy0)), ((gx1, gy0), (gx1, gy1)),
            ((gx1, gy1), (gx0, gy1)), ((gx0, gy1), (gx0, gy0)),
        ])
    for ei, e_draw, pts_i, gid, r_kind, col_i, rec in deferred_edges:
        if not e_draw.get("label"):
            continue
        other_segs = [seg for j, segs in enumerate(edge_segs_by_i) if j != ei for seg in segs]
        D.place_edge_label(
            ax, e_draw, pts_i, pos[e_draw["from"]], pos[e_draw["to"]],
            sizes[e_draw["from"]], sizes[e_draw["to"]], gid, r_kind, col_i,
            rec, obstacles=obstacles, meas=meas,
            placed_labels=placed_labels, other_segs=other_segs,
            group_borders=group_border_segs)

    # Draw nodes (zorder 2.0-2.5)
    for n in panel.get("nodes", []):
        D.draw_node(ax, n, pos[n["id"]][0], pos[n["id"]][1],
                    sizes[n["id"]]["w"], sizes[n["id"]]["h"],
                    n.get("fill"), n["id"], size_info=sizes[n["id"]])

    # Optional free annotations
    for ai, ann in enumerate(panel.get("annotations", [])):
        t = ax.text(ann.get("x", 2.0), ann.get("y", 2.0) + met["leg_h"],
                    ann.get("text", ""), fontsize=ann.get("fs", 7.5),
                    style=ann.get("style", "normal"),
                    color=ann.get("color", "#33404F"),
                    ha=ann.get("ha", "left"), va="bottom", zorder=4.0)
        t.set_gid("annotation-%s" % ann.get("id", str(ai)))

    leg_bbox = draw_panel_legend(ax, panel, meas, avail_w) if panel.get("legend") else None

    nmap = {n["id"]: n for n in panel.get("nodes", [])}
    return {
        "nodes": {
            k: {"x": round(v[0], 2), "y": round(v[1], 2),
                "w": round(sizes[k]["w"], 2), "h": round(sizes[k]["h"], 2),
                "shape": shapes[k],
                "label": nmap.get(k, {}).get("label", k),
                "sublabel": nmap.get(k, {}).get("sublabel", ""),
                "source": nmap.get(k, {}).get("source")}
            for k, v in pos.items()
        },
        "edges": edge_records,
        "groups": group_geoms,
        "legend_bbox": leg_bbox,
        "w": round(met["content_w"], 2),
        "h": round(met["total_inner_h"], 2),
        "legend_offset": round(met["leg_h"], 2),
    }


def panel_layout_pass(p, meas, style, avail_w, prefer_cjk=False):
    """Returns (inner_h, scale, wrapped) without drawing.

    Prefers mild single-row scaling (s >= 0.70) before wrapping onto 2 rows so horizontal
    multi-compartment cascades stay intact on one clean axis whenever readable.
    """
    met = _compute_panel_metrics(p, meas, style, avail_w)
    wrapped = False
    s = 1.0
    if met["content_w"] > avail_w:
        # First try clean unwrapped scaling while preserving legible >= 6.0 pt print text
        s_floor = 0.74 if float(style.get("fontsize", 9.0)) <= 8.0 else 0.70
        s_try = max(min(avail_w / met["content_w"] * 0.96, 0.95), s_floor)
        for _ in range(3):
            st_u = scaled_style(style, s_try)
            m_u = S.Measurer(st_u["fontsize"], prefer_cjk=prefer_cjk)
            met_u = _compute_panel_metrics(p, m_u, st_u, avail_w, wrap_w=None)
            m_u.close()
            if met_u["content_w"] <= avail_w:
                return met_u["total_inner_h"], s_try, False
            if s_try <= s_floor + 0.005:
                break
            s_try = max(s_try * (avail_w / met_u["content_w"]) * 0.97, s_floor)
        # Still too wide -> use group-atomic row wrap
        s = style.get("min_scale", 0.78)
        st2 = scaled_style(style, s)
        m2 = S.Measurer(st2["fontsize"], prefer_cjk=prefer_cjk)
        met = _compute_panel_metrics(p, m2, st2, avail_w, wrap_w=avail_w - 6.0)
        m2.close()
        wrapped = True
        for _ in range(4):
            if met["content_w"] <= avail_w:
                break
            s = max(s * (avail_w / met["content_w"]) * 0.98, 0.42)
            st2 = scaled_style(style, s)
            m2 = S.Measurer(st2["fontsize"], prefer_cjk=prefer_cjk)
            met = _compute_panel_metrics(p, m2, st2, avail_w, wrap_w=avail_w - 6.0)
            m2.close()
    return met["total_inner_h"], s, wrapped


def _load_journal_preset(preset_name):
    if not preset_name:
        return {}
    p_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "journal_presets.json")
    if not os.path.exists(p_path):
        return {}
    try:
        data = json.load(open(p_path, encoding="utf-8"))
        return (data.get("journal_presets") or {}).get(str(preset_name).strip(), {})
    except Exception:
        return {}


def _organize_svg_layers(svg_path, spec, geoms):
    """Post-process matplotlib SVG into true composite editable layers (node-*, edge-*, group-*, legend-*).

    Groups each node's shadow+shape+inner+accent+text+sublabel+badge into one <g id="node-X">,
    each edge's line+head(s)+elabel into one <g id="edge-X-Y">, each compartment's box+membrane
    into <g id="group-G">, and legend items into <g id="legend-panel-P">. Also attaches data-source
    provenance and enforces W3C XML id uniqueness.
    """
    import xml.etree.ElementTree as ET
    NS = "http://www.w3.org/2000/svg"
    ET.register_namespace("", NS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("cc", "http://creativecommons.org/ns#")
    ET.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    try:
        tree = ET.parse(svg_path)
    except Exception:
        return
    root = tree.getroot()
    q_g = "{%s}g" % NS

    def _fmt_src(src):
        if isinstance(src, dict):
            return " | ".join(str(src[k]) for k in ("file", "locator") if src.get(k))
        return str(src) if src else ""

    # Map panel_id -> provenance dicts
    panel_meta = {}
    for pi, p in enumerate(spec.get("panels", [])):
        pid = str(p.get("id", str(pi)))
        gp = (geoms or {}).get(pid, {})
        nsrc = {str(n["id"]): _fmt_src(n.get("source")) for n in p.get("nodes", [])}
        esrc = {}
        ekind = {}
        for er in gp.get("edges", []):
            eid = str(er.get("id", ""))
            esrc[eid] = _fmt_src(er.get("source"))
            ekind[eid] = str(er.get("kind", "activates"))
        panel_meta[pid] = {
            "node_ids": [str(n["id"]) for n in p.get("nodes", [])],
            "edge_ids": [str(er.get("id", "")) for er in gp.get("edges", [])],
            "group_ids": [str(g.get("id", "")) for g in p.get("groups", []) if g.get("id")],
            "nsrc": nsrc, "esrc": esrc, "ekind": ekind,
        }

    for pel in root.iter(q_g):
        pid_attr = pel.get("id") or ""
        if not pid_attr.startswith("panel-"):
            continue
        pid = pid_attr[6:]
        meta = panel_meta.get(pid)
        if not meta:
            continue

        def _wrap_members(composite_id, member_ids, layer_type, extra_attrs=None, rename_self=None):
            kids = list(pel)
            by_id = {ch.get("id"): ch for ch in kids if ch.get("id")}
            found = [by_id[mid] for mid in member_ids if mid in by_id]
            if not found:
                return
            anchor_idx = min(kids.index(el) for el in found)
            grp = ET.Element(q_g)
            grp.set("id", composite_id)
            grp.set("data-layer", layer_type)
            for ak, av in (extra_attrs or {}).items():
                if av:
                    grp.set(ak, str(av))
            for el in found:
                pel.remove(el)
                if rename_self and el.get("id") == composite_id:
                    el.set("id", rename_self)
                grp.append(el)
            pel.insert(min(anchor_idx, len(pel)), grp)

        # 1) Compartments: box + membrane lines (keep grouplabel at top z-order so edges never paint over it)
        for gid in meta["group_ids"]:
            mids = ["group-%s" % gid, "group-%s-membrane-1" % gid, "group-%s-membrane-2" % gid]
            _wrap_members("group-%s" % gid, mids, "compartment", rename_self="group-%s-box" % gid)

        # 2) Nodes: shadow + shape + inner + accent + text + sublabel + badge
        for nid in meta["node_ids"]:
            mids = [
                "node-%s-shadow" % nid, "node-%s" % nid, "node-%s-inner" % nid,
                "node-%s-accent" % nid, "text-%s" % nid, "sublabel-%s" % nid,
                "badge-%s" % nid,
            ]
            extra = {"data-source": meta["nsrc"].get(nid, "")}
            _wrap_members("node-%s" % nid, mids, "node", extra_attrs=extra,
                          rename_self="node-%s-shape" % nid)

        # 3) Edges: line + arrowheads + edge label
        for eid in meta["edge_ids"]:
            mids = [
                "edge-%s-line" % eid, "edge-%s-head" % eid, "edge-%s-head-b" % eid,
                "edge-%s-head2" % eid, "edge-%s-head2-b" % eid, "elabel-%s" % eid,
            ]
            extra = {"data-kind": meta["ekind"].get(eid, ""),
                     "data-source": meta["esrc"].get(eid, "")}
            _wrap_members("edge-%s" % eid, mids, "edge", extra_attrs=extra)

        # 4) Panel legend: box + title + all legend-item-*
        leg_ids = [ch.get("id") for ch in list(pel)
                   if (ch.get("id") or "").startswith("legend-")]
        if leg_ids:
            _wrap_members("legend-panel-%s" % pid, leg_ids, "legend")

    # Enforce strict W3C XML id uniqueness across entire SVG document
    seen_ids = {}
    for el in root.iter():
        eid = el.get("id")
        if not eid:
            continue
        if eid in seen_ids:
            seen_ids[eid] += 1
            el.set("id", "%s-%d" % (eid, seen_ids[eid]))
        else:
            seen_ids[eid] = 1

    tree.write(svg_path, encoding="utf-8", xml_declaration=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stem", default="figure")
    ap.add_argument("--geom", default=None)
    ap.add_argument("--dpi", type=int, default=300,
                    help="main PNG dpi; 300 is journal-grade and container-safe, pass 600 for print-final")
    ap.add_argument("--tiff", action="store_true",
                    help="also export LZW TIFF (journal raster submission format)")
    a = ap.parse_args()
    spec_dir = os.path.dirname(os.path.abspath(a.spec))
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    try:
        _DIR_ALIASES = {
            "VERTICAL": "TB", "TOP-DOWN": "TB", "TOP_DOWN": "TB", "TOP_TO_BOTTOM": "TB", "TD": "TB", "DOWN": "TB",
            "HORIZONTAL": "LR", "LEFT-TO-RIGHT": "LR", "LEFT_TO_RIGHT": "LR", "RIGHT": "LR",
        }
        _CHART_TYPES = set(C._CHART_KIND_ALIASES.keys())
        for p in spec.get("panels", []):
            ptype_l = str(p.get("type", "schematic")).strip().lower().replace(" ", "_")
            if ptype_l in _CHART_TYPES:
                p["type"] = "chart"
                ch_d = p.setdefault("chart", {})
                ch_d.setdefault("kind", C.canonical_chart_kind(ptype_l))
            elif ptype_l == "chart" and isinstance(p.get("chart"), dict) and p["chart"].get("kind"):
                p["chart"]["kind"] = C.canonical_chart_kind(p["chart"]["kind"])
            if p.get("direction"):
                d_up = str(p["direction"]).strip().upper()
                p["direction"] = _DIR_ALIASES.get(d_up, d_up)
            seen = set()
            ci_id, by_lbl, ci_lbl = {}, {}, {}
            for ni, n in enumerate(p.get("nodes", [])):
                if not n.get("id"):
                    raw_id = n.get("entity") or n.get("name") or n.get("label") or ("node_%d" % ni)
                    n["id"] = re.sub(r"\s+", "_", str(raw_id).strip())[:32]
                if not n.get("label"):
                    n["label"] = str(n.get("entity") or n.get("name") or n["id"])
                n["id"] = str(n["id"])
                if n.get("shape"):
                    n["shape"] = S.canonical_shape(n["shape"])
                if not n.get("fill") and n.get("color"):
                    n["fill"] = n["color"]
                if n["id"] in seen:
                    raise SystemExit("spec error: duplicate node id %r (panel %s)"
                                     % (n["id"], p.get("id")))
                seen.add(n["id"])
                ci_id[n["id"].lower()] = n["id"]
                lbl0 = str(n.get("label", "")).strip()
                if lbl0:
                    by_lbl.setdefault(lbl0, n["id"])
                    ci_lbl.setdefault(lbl0.lower(), n["id"])
            for e in p.get("edges", []):
                if "from" not in e:
                    if isinstance(e.get("source"), str):
                        e["from"] = e["source"]
                    else:
                        for fk in ("src", "subject", "from_id", "source_id", "start"):
                            if e.get(fk):
                                e["from"] = e[fk]
                                break
                if "to" not in e:
                    for tk in ("target", "dst", "object", "to_id", "target_id", "end"):
                        if e.get(tk):
                            e["to"] = e[tk]
                            break
                if not e.get("kind"):
                    e["kind"] = e.get("relation") or e.get("type") or "activates"
                if e.get("kind"):
                    e["kind"] = S.canonical_edge_kind(e["kind"])
                for ek in ("from", "to"):
                    val = str(e.get(ek, "")).strip()
                    if val not in seen:
                        val = ci_id.get(val.lower()) or by_lbl.get(val) or ci_lbl.get(val.lower()) or val
                    e[ek] = val
                for end in (e.get("from"), e.get("to")):
                    if end not in seen:
                        raise SystemExit("spec error: edge %s->%s references unknown node %r"
                                         % (e.get("from"), e.get("to"), end))
            # Resolve group member labels/case-insensitive IDs cleanly so compartments never miss members
            for g in p.get("groups", []):
                if isinstance(g.get("members"), list):
                    resolved_m = []
                    for mv in g["members"]:
                        ms = str(mv).strip()
                        if ms not in seen:
                            ms = ci_id.get(ms.lower()) or by_lbl.get(ms) or ci_lbl.get(ms.lower()) or ms
                        if ms not in resolved_m:
                            resolved_m.append(ms)
                    g["members"] = resolved_m
    except SystemExit:
        raise
    except Exception as ex:
        raise SystemExit("spec error: %s (schema: references/result_schema.md)" % ex)

    preset_name = spec.get("preset") or spec.get("canvas", {}).get("preset")
    preset_cfg = _load_journal_preset(preset_name)
    if preset_cfg:
        if "width_mm" not in spec.get("canvas", {}) and preset_cfg.get("width_mm"):
            spec.setdefault("canvas", {})["width_mm"] = preset_cfg["width_mm"]
        if a.dpi == 300 and preset_cfg.get("dpi"):
            a.dpi = int(preset_cfg["dpi"])
    style = dict(S.STYLE)
    if preset_cfg.get("font_family"):
        style["font_family"] = preset_cfg["font_family"]
    style.update(spec.get("style", {}))
    prefer_cjk = S.has_cjk(json.dumps(spec, ensure_ascii=False))
    S.configure_fonts(style["font_family"], prefer_cjk=prefer_cjk)
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42

    meas = S.Measurer(style.get("fontsize", 9.0), prefer_cjk=prefer_cjk)
    m = style["margin_mm"]
    panels = spec.get("panels", [])
    width_mm = float(spec.get("canvas", {}).get("width_mm", 180.0))
    avail = max(width_mm - 2.0 * m, 20.0)
    gap = style["panel_gap_mm"]

    # Group panels into layout rows (optional panel.row enables side-by-side multi-panel grids;
    # when >=3 panels omit row on a wide canvas, auto-pair consecutive charts 2-per-row for compact publication grids)
    row_groups = []
    row_map = {}
    any_explicit_row = any(p.get("row") is not None for p in panels)
    if (not any_explicit_row) and len(panels) >= 3 and width_mm >= 150.0:
        cur_pair = []
        for i, p in enumerate(panels):
            is_pairable_chart = (
                p.get("type") == "chart"
                and not p.get("full_width")
                and C.canonical_chart_kind((p.get("chart") or {}).get("kind", "bar")) != "barh"
            )
            if is_pairable_chart:
                cur_pair.append(i)
                if len(cur_pair) == 2:
                    row_groups.append(cur_pair)
                    cur_pair = []
            else:
                if cur_pair:
                    row_groups.append(cur_pair)
                    cur_pair = []
                row_groups.append([i])
        if cur_pair:
            row_groups.append(cur_pair)
    else:
        for i, p in enumerate(panels):
            rk = p.get("row")
            if rk is None:
                row_groups.append([i])
            else:
                if rk not in row_map:
                    row_map[rk] = []
                    row_groups.append(row_map[rk])
                row_map[rk].append(i)

    # Compute per-panel horizontal slot (x0_mm, w_mm) within its row
    col_gap = gap
    panel_x0 = {}
    panel_w = {}
    for grp in row_groups:
        weights = [max(float(panels[idx].get("width_weight", 1.0)), 0.1) for idx in grp]
        wsum = sum(weights)
        usable = max(avail - col_gap * max(len(grp) - 1, 0), 20.0)
        cx = m
        for idx, wt in zip(grp, weights):
            pw = usable * (wt / wsum)
            panel_x0[idx] = cx
            panel_w[idx] = pw
            cx += pw + col_gap

    # Prepare deduped & width-fitted panel titles + exact per-panel header band (NEVER collides!)
    title_prep = {}
    hdr_hs, inner_hs, scales, wraps = {}, {}, {}, {}
    row_len_of = {idx: len(grp) for grp in row_groups for idx in grp}
    for i, p in enumerate(panels):
        pid = p.get("id", str(i))
        pw = panel_w[i]
        has_plab = len(panels) > 1 and p.get("panel_label", True)
        plab_ch = chr(65 + i)
        title_txt = str(p.get("title") or "").strip()
        if title_txt and has_plab:
            title_txt = re.sub(
                r"^(?:Panel\s+%s[\.\:\-\)]\s*|\(%s\)\s*|%s[\.\:\)]\s+)" % (plab_ch, plab_ch, plab_ch),
                "", title_txt, flags=re.I
            ).strip() or title_txt
        t_fs = 9.0 if row_len_of[i] > 1 else 9.5
        n_tlines = 1
        if title_txt:
            max_tw = max(pw - (7.5 if has_plab else 1.5), 20.0)
            tw_est = meas.text_mm(title_txt, fontsize=t_fs, weight="bold")[0]
            if tw_est > max_tw:
                if tw_est <= max_tw * 1.18:
                    t_fs = max(7.6, t_fs * (max_tw / tw_est) * 0.96)
                else:
                    t_fs = min(t_fs, 8.2)
                    # Wrap neatly onto 2 lines to fit narrow side-by-side column
                    avg_cw = max(tw_est / max(len(title_txt), 1), 1.4)
                    mc = max(int(max_tw / (avg_cw * (t_fs / 9.0))), 16)
                    title_txt = S.wrap_label(title_txt, max_chars=mc)
                    n_tlines = title_txt.count("\n") + 1
                    tw_w = meas.text_mm(title_txt, fontsize=t_fs, weight="bold")[0]
                    if tw_w > max_tw:
                        t_fs = max(7.0, t_fs * (max_tw / tw_w) * 0.96)
        title_prep[i] = (title_txt, t_fs, has_plab, plab_ch)
        has_hdr = bool(title_txt or has_plab)
        hdr_hs[i] = (10.2 if n_tlines >= 2 else 6.8) if has_hdr else 1.5
        if p.get("type") == "chart":
            inner_hs[i] = float(p.get("height_mm", 54.0))
            scales[pid], wraps[pid] = 1.0, False
        else:
            ih, s, wrapped = panel_layout_pass(p, meas, style, pw, prefer_cjk=prefer_cjk)
            inner_hs[i] = max(ih, 18.0)
            scales[pid], wraps[pid] = s, wrapped

    row_heights = [max(hdr_hs[idx] + inner_hs[idx] for idx in grp) for grp in row_groups]
    fig_title_raw = str(spec.get("title") or spec.get("canvas", {}).get("title") or "").strip()
    fig_sub_raw = str(spec.get("subtitle") or spec.get("canvas", {}).get("subtitle") or "").strip()
    if fig_title_raw and len(panels) == 1 and str(panels[0].get("title") or "").strip().lower() == fig_title_raw.lower():
        fig_title_raw = ""
    fig_title_txt, fig_title_fs, fig_hdr_h = "", 10.8, 0.0
    if fig_title_raw:
        tw_ft = meas.text_mm(fig_title_raw, fontsize=fig_title_fs, weight="bold")[0]
        if tw_ft > avail:
            if tw_ft <= avail * 1.15:
                fig_title_fs = max(9.2, fig_title_fs * (avail / tw_ft) * 0.96)
                fig_title_txt = fig_title_raw
            else:
                fig_title_fs = 9.8
                mc_ft = max(int(avail / 2.0), 28)
                fig_title_txt = S.wrap_label(fig_title_raw, max_chars=mc_ft)
        else:
            fig_title_txt = fig_title_raw
        n_ftl = fig_title_txt.count("\n") + 1
        fig_hdr_h = (5.4 * n_ftl + 2.2) + (4.2 if fig_sub_raw else 0.0)
    footnote = spec.get("footnote") or spec.get("canvas", {}).get("footnote")
    foot_h = 5.0 if footnote else 0.0
    total_h = (2.0 * m + fig_hdr_h + sum(row_heights) + gap * max(len(row_groups) - 1, 0) + foot_h) if panels else 40.0

    fig = plt.figure(figsize=(width_mm / S.MM_PER_INCH, total_h / S.MM_PER_INCH), dpi=100)
    fig.patch.set_facecolor("white")

    geoms = {}
    y_top = total_h - m
    if fig_title_txt:
        y_ft = y_top - (fig_hdr_h - (4.2 if fig_sub_raw else 0.0)) / 2.0
        ft_el = fig.text(m / width_mm, y_ft / total_h, fig_title_txt,
                         fontsize=fig_title_fs, fontweight="bold", color=style["title_color"],
                         va="center", ha="left", linespacing=1.15)
        ft_el.set_gid("figure-title")
        if fig_sub_raw:
            fs_el = fig.text(m / width_mm, (y_top - fig_hdr_h + 1.8) / total_h, fig_sub_raw,
                             fontsize=7.6, color="#4A5568", va="center", ha="left")
            fs_el.set_gid("figure-subtitle")
        y_top -= fig_hdr_h
    for grp, rh in zip(row_groups, row_heights):
        for i in grp:
            p = panels[i]
            pid = p.get("id", str(i))
            px0 = panel_x0[i]
            pw = panel_w[i]
            hdr_h = hdr_hs[i]
            if p.get("type") == "chart":
                ih = min(rh - hdr_h, max(inner_hs[i], pw * 1.12))
                y_hdr_mid = y_top - hdr_h / 2.0
                # Center chart nicely within row slot if neighbor schematic is much taller
                extra_v = max((rh - hdr_h) - ih, 0.0)
                y_panel_bot = y_top - hdr_h - ih - extra_v * 0.35
            else:
                ih = inner_hs[i]
                y_hdr_mid = y_top - hdr_h / 2.0
                y_panel_bot = y_top - hdr_h - ih

            # Draw panel label & title inside dedicated header band (pre-deduped & width-fitted)
            title_txt, t_fs, has_plab, plab_ch = title_prep[i]
            if has_plab:
                t = fig.text(px0 / width_mm, y_hdr_mid / total_h, plab_ch,
                             fontsize=12, fontweight="bold", color=style["panel_label"],
                             va="center", ha="left")
                t.set_gid("panel-label-%s" % pid)
            if title_txt:
                tx_mm = px0 + (6.0 if has_plab else 0.0)
                t = fig.text(tx_mm / width_mm, y_hdr_mid / total_h, title_txt,
                             fontsize=t_fs, fontweight="bold", color=style["title_color"],
                             va="center", ha="left", linespacing=1.15)
                t.set_gid("panel-title-%s" % pid)

            if p.get("type") == "chart":
                ch_pre = p.get("chart", {})
                try:
                    ch_pre = C.load_chart_table(ch_pre, spec_dir=spec_dir)
                except Exception:
                    pass
                cats_pre = ch_pre.get("categories", [])
                max_cat_len = max((len(str(c)) for c in cats_pre), default=0)
                ckind = ch_pre.get("kind", "bar")
                if ckind == "barh":
                    # Account for 2-line auto-wrapping of long barh labels (>22 chars) so labels never bleed across columns!
                    max_wrap_len = max(
                        (max(len(ln) for ln in S.wrap_label(str(c), max_chars=24).splitlines())
                         for c in cats_pre),
                        default=0,
                    )
                    inset_l = min(max(14.0, max_wrap_len * 1.48 + 5.5), pw * 0.42)
                    inset_b = 10.5
                elif ckind == "heatmap":
                    row_lbls = ch_pre.get("row_labels") or [s.get("name", "") for s in ch_pre.get("series", [])]
                    max_rl = max((len(str(r)) for r in row_lbls), default=4)
                    inset_l = min(max(14.0, max_rl * 1.45 + 4.5), pw * 0.34)
                    inset_b = 14.0 if max_cat_len > 8 else 10.0
                else:
                    inset_l = 13.5
                    n_cp = len(cats_pre)
                    need_rot_b = (not ch_pre.get("x_values")) and (
                        max_cat_len > 10 or (n_cp >= 5 and max_cat_len * 1.45 > (pw - 16.5) / max(n_cp, 1) * 0.92))
                    inset_b = 18.5 if (not ch_pre.get("x_values") and (max_cat_len > 14 or (need_rot_b and n_cp >= 6))) else (
                        15.5 if need_rot_b else 10.5)
                inset_r = 12.5 if ckind == "heatmap" else 3.0
                inset_t = 9.8 if C.effective_legend_loc(ch_pre) == "top" else 2.2
                ax_x = px0 + inset_l
                ax_y = y_panel_bot + inset_b
                ax_w = max(pw - inset_l - inset_r, 15.0)
                ax_h = max(ih - inset_b - inset_t, 15.0)
                ax = fig.add_axes([ax_x / width_mm, ax_y / total_h,
                                   ax_w / width_mm, ax_h / total_h])
                ax.set_gid("panel-%s" % pid)
                info = C.draw_chart(ax, p, style["palette"], spec_dir=spec_dir)
                geoms[pid] = {"type": "chart", **info}
            else:
                ax = fig.add_axes([px0 / width_mm, y_panel_bot / total_h,
                                   pw / width_mm, ih / total_h])
                ax.set_gid("panel-%s" % pid)
                ax.set_xlim(0.0, pw)
                ax.set_ylim(0.0, ih)
                ax.axis("off")
                sc = scales[pid]
                pstyle = scaled_style(style, sc) if sc != 1.0 else style
                D.CURRENT = pstyle
                pmeas = S.Measurer(pstyle["fontsize"], prefer_cjk=prefer_cjk) if sc != 1.0 else meas
                geoms[pid] = {
                    "type": "schematic",
                    "scale": round(sc, 3),
                    "origin": [round(px0, 2), round(y_panel_bot, 2)],
                    "panel_box_mm": [round(px0, 2), round(y_panel_bot, 2),
                                     round(px0 + pw, 2), round(y_panel_bot + ih, 2)],
                    **draw_schematic(ax, p, pmeas, pstyle, pw,
                                     wrap_w=(pw - 6.0) if wraps[pid] else None)
                }
                if pmeas is not meas:
                    pmeas.close()

        y_top -= rh + gap

    if footnote:
        ft = fig.text(m / width_mm, (m * 0.45) / total_h, str(footnote),
                      fontsize=6.5, color="#556270", va="bottom", ha="left")
        ft.set_gid("figure-footnote")

    meas.close()
    os.makedirs(a.out_dir, exist_ok=True)
    out = {
        "svg": os.path.join(a.out_dir, a.stem + ".svg"),
        "pdf": os.path.join(a.out_dir, a.stem + ".pdf"),
        "png": os.path.join(a.out_dir, a.stem + ".png"),
        "preview": os.path.join(a.out_dir, a.stem + "_preview.png"),
    }
    with matplotlib.rc_context({"svg.fonttype": "none"}):
        fig.savefig(out["svg"], format="svg", facecolor="white")
    _organize_svg_layers(out["svg"], spec, geoms)
    fig.savefig(out["pdf"], format="pdf", facecolor="white")
    fig.savefig(out["png"], format="png", dpi=a.dpi, facecolor="white")
    fig.savefig(out["preview"], format="png", dpi=100, facecolor="white")
    plt.close(fig)
    if a.tiff:
        try:
            from PIL import Image
            im = Image.open(out["png"])
            out["tiff"] = os.path.join(a.out_dir, a.stem + ".tif")
            im.save(out["tiff"], compression="tiff_lzw", dpi=(a.dpi, a.dpi))
        except Exception as ex:
            out["tiff_error"] = str(ex)
    geom_path = a.geom or os.path.join(a.out_dir, "geometry.json")
    gd = os.path.dirname(geom_path)
    if gd:
        os.makedirs(gd, exist_ok=True)
    with open(geom_path, "w", encoding="utf-8") as f:
        json.dump({"canvas_mm": [round(width_mm, 1), round(total_h, 1)],
                   "panels": geoms}, f, indent=1, ensure_ascii=False)
    out["geometry"] = geom_path
    out["canvas_mm"] = [round(width_mm, 1), round(total_h, 1)]
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
