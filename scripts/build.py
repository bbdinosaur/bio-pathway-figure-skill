"""Build mechanism & multi-panel composite figure primitives from spec."""
from __future__ import annotations
import sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import SCALES, text_w
from viz_layout import (auto_compartment_bands, draw_compartments, draw_groups,
                        place_nodes, tighten_bands, LEFT)
from viz_nodes import draw_nodes
from viz_edges import draw_edges
from viz_legend import build_legend
from viz_geom import bbox_of, text_bbox

def _wrap(s, maxpx, size):
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

def _estimate_arc_pad(spec):
    """Estimate top padding per compartment so same-row feedback/auto_arc rails stay inside the band."""
    comp_of = {n["id"]: (n.get("compartment") or "_") for n in spec.get("nodes", [])}
    idx_in_comp = {}
    counts = {}
    for n in spec.get("nodes", []):
        cid = n.get("compartment") or "_"
        idx_in_comp[n["id"]] = counts.get(cid, 0)
        counts[cid] = counts.get(cid, 0) + 1
    arcs = {}
    for e in spec.get("edges", []):
        u, v = e.get("from"), e.get("to")
        if u not in comp_of or v not in comp_of:
            continue
        if comp_of[u] == comp_of[v]:
            cid = comp_of[u]
            if u == v or e.get("route") in ("feedback", "arc") or abs(idx_in_comp[u] - idx_in_comp[v]) > 1:
                arcs[cid] = arcs.get(cid, 0) + 1
    return {cid: min(92.0, 24.0 + 22.0 * k) for cid, k in arcs.items()}

def build_mechanism(spec, scale_name="regular"):
    gap = SCALES.get(scale_name, 88)
    lgap = 0
    for e in spec.get("edges", []):
        t = str(e.get("label") or "")
        if e.get("evidence") and str(e["evidence"]).lower() not in t.lower():
            t = (t + f" [{e['evidence']}]").strip()
        if t and e.get("route", "direct") == "direct":
            lgap = max(lgap, text_w(t, 12.0) + 16)
    gap = max(gap, min(lgap, 185))

    prims = []
    comps = spec.get("compartments", [])
    comp_kind = {c["id"]: c.get("kind", "custom") for c in comps}
    lopts = spec.get("layout") or {}
    arc_pad = _estimate_arc_pad(spec)
    group_comps = set()
    comp_of = {n["id"]: n.get("compartment") for n in spec.get("nodes", [])}
    for g in spec.get("groups") or []:
        for mid in g.get("members") or []:
            if comp_of.get(mid):
                group_comps.add(comp_of[mid])

    # Dynamic top safe zone when long title wraps to 2 lines (prevents title/arc/PTM collisions)
    title = spec.get("title", "")
    title_2line = bool(title and text_w(str(title), 20.5) > 760)
    top_y = 96.0 if title_2line else 74.0

    # Pass 1: initial placement to measure needed band heights
    bands0, _ = auto_compartment_bands(comps, top_y=top_y)
    placed0, row_w0 = place_nodes(spec, bands0, comp_kind, gap, 0, extra_top_pad=arc_pad, top_y=top_y)
    bands = (tighten_bands(comps, bands0, placed0, extra_top_pad=arc_pad,
                           group_pad_comps=group_comps)
             if lopts.get("tighten_bands", True) else bands0)
    # Pass 2: final placement inside tightened bands
    placed, row_w = place_nodes(spec, bands, comp_kind, gap, row_w0, extra_top_pad=arc_pad, top_y=top_y)
    plot_w = max(row_w, 560)

    if comps:
        draw_compartments(comps, bands, plot_w, prims, placed=placed)
    if spec.get("groups"):
        draw_groups(spec["groups"], placed, prims)

    node_boxes = []
    avoid_boxes = []
    for n in placed:
        if n.get("shape") == "ellipse":
            nb = {"op": "ellipse", "role": "node", "cx": n["cx"], "cy": n["cy"],
                  "rx": n["w"] / 2, "ry": n["h"] / 2}
        else:
            nb = {"op": "rect", "role": "node", "x": n["cx"] - n["w"] / 2,
                  "y": n["cy"] - n["h"] / 2, "w": n["w"], "h": n["h"]}
        node_boxes.append((n["id"], bbox_of(nb)))
        # Reserve exact PTM pill/circle badge boxes matching viz_nodes.py so edge labels never clip them
        cur_right = n["cx"] + n["w"] / 2.0 + 4.0
        my = n["cy"] - n["h"] / 2.0 + 2.0
        for i, m in enumerate(n.get("mods", []) or []):
            ms = str(m)
            if len(ms) >= 2:
                bw_m = max(24.0, len(ms) * 6.2 + 9.0)
                bh_m = 18.0
                avoid_boxes.append((f"mod-{n['id']}-{i}", [cur_right - bw_m - 1.5, my - bh_m / 2.0 - 1.5, cur_right + 1.5, my + bh_m / 2.0 + 1.5]))
                cur_right -= (bw_m + 3.0)
            else:
                r = 9.5
                mx = cur_right - r
                avoid_boxes.append((f"mod-{n['id']}-{i}", [mx - r - 1.5, my - r - 1.5, mx + r + 1.5, my + r + 1.5]))
                cur_right -= (r * 2.0 + 3.0)

    plot_left = LEFT - 24
    plot_right = LEFT + plot_w + 24
    used, routed, max_rail_x = draw_edges(
        spec.get("edges", []), placed, gap, prims,
        node_boxes=node_boxes, avoid_boxes=avoid_boxes,
        opts=lopts, plot_right=plot_right, plot_left=plot_left,
        width_map=spec.get("width_map"), min_y=top_y - 4.0
    )
    draw_nodes(placed, prims, spec=spec)

    legend_w = 0
    legend_bottom = 0
    if spec.get("legend") is not False and (used or spec.get("data_map") or len(placed) >= 2):
        lx = max(plot_right, max_rail_x) + 34
        legend_bottom = build_legend(prims, used, placed, spec, lx, top_y + 12.0, opts=lopts)
        legend_w = 326
    else:
        lx = max(plot_right, max_rail_x)

    W = int(max((lx + legend_w + 18) if legend_w else (lx + 30), 780))
    tlines = _wrap(title, W - 112, 20.5) if title else []
    for i, ln in enumerate(tlines[:2]):
        prims.append({"op": "text", "x": LEFT - 24, "y": 28 + i * 25, "s": ln, "size": 20.5,
                      "anchor": "start", "fill": "#0f172a", "weight": "bold",
                      "role": "text", "layer": "layer-chrome"})
    caption = spec.get("caption", "")
    bands_bottom = (bands[-1]["y1"] + 12) if bands else 0
    node_bottom = max((n["cy"] + n["h"] / 2 for n in placed), default=400)
    cap_y = int(max(bands_bottom if comps else node_bottom, legend_bottom) + (22 if caption else 20))
    clines = _wrap(caption, W - 96, 12.0) if caption else []
    for i, ln in enumerate(clines):
        prims.append({"op": "text", "x": LEFT - 24, "y": cap_y + i * 17, "s": ln, "size": 12.0,
                      "anchor": "start", "fill": "#64748b", "italic": True,
                      "role": "text", "layer": "layer-chrome"})
    H = int(cap_y + 17 * len(clines) + 18)
    return prims, W, H, placed, used, routed

def _shift_prims(prims, dx, dy):
    out = []
    for p in prims:
        q = deepcopy(p)
        if "x" in q:
            q["x"] = q["x"] + dx
        if "y" in q:
            q["y"] = q["y"] + dy
        if "cx" in q:
            q["cx"] = q["cx"] + dx
        if "cy" in q:
            q["cy"] = q["cy"] + dy
        if "pts" in q:
            q["pts"] = [[pt[0] + dx, pt[1] + dy] for pt in q["pts"]]
        out.append(q)
    return out

def build_composite(spec, scale_name="regular"):
    """Build multi-panel composite figure (panels = [{id:'A', spec:{...}}, ...]).
    Returns (flat_prims, chrome_prims, panel_groups, W, H, panel_meta)."""
    from chart import build_chart
    panels = spec.get("panels") or []
    lopts = spec.get("layout") or {}
    cols = int(lopts.get("cols") or (1 if len(panels) <= 1 else min(2, len(panels))))
    gap = float(lopts.get("panel_gap", 28))
    pad_x = 24.0
    title = spec.get("title", "")
    # Pre-estimate title lines using typical composite width
    est_w = max(900, int(pad_x * 2 + 800 * cols))
    tlines_est = _wrap(title, est_w - 80, 22.0) if title else []
    top_y = (76.0 if len(tlines_est) >= 2 else 56.0) if title else 24.0

    def _build_one(idx, pdef, span_target_w=None):
        pid = str(pdef.get("id") or chr(65 + idx))
        pspec = dict(pdef.get("spec") or pdef)
        if pdef.get("title") and not pspec.get("title"):
            pspec["title"] = pdef["title"]
        if pspec.get("mode") == "chart":
            ch_raw = pspec.get("chart")
            if span_target_w and isinstance(ch_raw, dict) and not ch_raw.get("width"):
                ch_kind = str(ch_raw.get("kind") or "").lower()
                if ch_kind not in ("heatmap", "matrix", "expression_heatmap", "heatmap_chart"):
                    pspec = {**pspec, "chart": {**ch_raw, "width": int(span_target_w)}}
            sub_prims, pw, ph, placed, used = build_chart(pspec, scale_name)
            routed = []
        else:
            sub_prims, pw, ph, placed, used, routed = build_mechanism(pspec, scale_name)
        # Bold publication-style panel badge (A, B, C...) at top-left of panel; clear sub-panel title
        badge_w = text_w(pid, 20.0)
        badge_x = 6.0
        for sp_p in sub_prims:
            if (sp_p.get("op") == "text" and sp_p.get("layer") == "layer-chrome"
                    and sp_p.get("y", 999) <= 44 and sp_p.get("anchor") == "start"
                    and sp_p.get("x", 999) < badge_x + badge_w + 12.0):
                sp_p["x"] = badge_x + badge_w + 14.0
        badge = {"op": "text", "x": badge_x, "y": 24.0, "s": pid, "size": 20.0,
                 "anchor": "start", "fill": "#0f172a", "weight": "bold",
                 "role": "text", "layer": "layer-chrome", "_id": f"panel-badge-{pid}"}
        sub_prims = list(sub_prims) + [badge]
        span = max(1, min(cols, int(pdef.get("span") or pdef.get("colspan") or 1)))
        return {"id": pid, "prims": sub_prims, "W": pw, "H": ph, "span": span,
                "placed": placed, "used": used, "routed": routed, "spec": pspec}

    # Pass 1: build non-spanning panels first to learn natural multi-column grid width
    built_map = {}
    est_col_w = [0.0] * cols
    cur_c = 0
    for idx, pdef in enumerate(panels):
        sp = max(1, min(cols, int(pdef.get("span") or pdef.get("colspan") or 1)))
        if sp == 1:
            b = _build_one(idx, pdef)
            built_map[idx] = b
            est_col_w[cur_c % cols] = max(est_col_w[cur_c % cols], b["W"])
            cur_c += 1
        else:
            cur_c = 0
    est_grid_w = sum(est_col_w) + gap * max(0, cols - 1) if any(est_col_w) else 0.0
    span_w = min(int(est_grid_w), 1440) if est_grid_w >= 1000 else None

    built = []
    for idx, pdef in enumerate(panels):
        if idx in built_map:
            built.append(built_map[idx])
        else:
            built.append(_build_one(idx, pdef, span_target_w=span_w))

    # Row-packing grid layout with full-width span support (e.g., Panel A span=2 above B + C)
    rows_grid = []
    cur_row, cur_span = [], 0
    for b in built:
        sp = b["span"]
        if cur_row and cur_span + sp > cols:
            rows_grid.append(cur_row)
            cur_row, cur_span = [], 0
        cur_row.append((cur_span, sp, b))
        cur_span += sp
        if cur_span >= cols:
            rows_grid.append(cur_row)
            cur_row, cur_span = [], 0
    if cur_row:
        rows_grid.append(cur_row)

    col_w = [0.0] * cols
    row_h = [0.0] * len(rows_grid)
    min_total_w = 0.0
    for r, ritems in enumerate(rows_grid):
        for c0, sp, b in ritems:
            row_h[r] = max(row_h[r], b["H"])
            if sp == 1:
                col_w[c0] = max(col_w[c0], b["W"])
            else:
                min_total_w = max(min_total_w, b["W"])
    grid_inner_w = sum(col_w) + gap * max(0, cols - 1)
    if min_total_w > grid_inner_w and cols > 0:
        extra = (min_total_w - grid_inner_w) / cols
        col_w = [w + extra for w in col_w]
        grid_inner_w = sum(col_w) + gap * max(0, cols - 1)

    W = int(pad_x * 2 + grid_inner_w)
    flat_prims = []
    panel_groups = []
    panel_meta = []
    y_cur = top_y
    for r, ritems in enumerate(rows_grid):
        for c0, sp, b in ritems:
            slot_x = pad_x + sum(col_w[:c0]) + gap * c0
            slot_w = sum(col_w[c0:c0 + sp]) + gap * max(0, sp - 1)
            dx = slot_x + (max(0.0, (slot_w - b["W"]) / 2.0) if sp > 1 else 0.0)
            dy = y_cur
            panel_groups.append((b["id"], dx, dy, b["prims"]))
            flat_prims.extend(_shift_prims(b["prims"], dx, dy))
            panel_meta.append({
                "id": b["id"], "dx": dx, "dy": dy, "W": b["W"], "H": b["H"], "prims": b["prims"],
                "placed": b["placed"], "used": b["used"], "routed": b["routed"], "spec": b["spec"],
            })
        y_cur += row_h[r] + gap

    chrome_prims = [
        {"op": "rect", "x": 0, "y": 0, "w": W, "h": 0, "fill": "#ffffff",
         "stroke": "none", "stroke_w": 0, "role": "bg", "layer": "layer-backdrop"}
    ]
    if title:
        tlines = _wrap(title, W - 80, 22.0)
        for i, ln in enumerate(tlines[:2]):
            chrome_prims.append({"op": "text", "x": pad_x, "y": 26 + i * 26, "s": ln,
                                 "size": 22.0, "anchor": "start", "fill": "#0f172a",
                                 "weight": "bold", "role": "text", "layer": "layer-chrome"})
    caption = spec.get("caption", "")
    cap_y = int(y_cur - gap + (22 if caption else 12))
    clines = _wrap(caption, W - 80, 12.0) if caption else []
    for i, ln in enumerate(clines):
        chrome_prims.append({"op": "text", "x": pad_x, "y": cap_y + i * 17, "s": ln,
                             "size": 12.0, "anchor": "start", "fill": "#64748b",
                             "italic": True, "role": "text", "layer": "layer-chrome"})
    H = int(cap_y + 17 * len(clines) + 18)
    chrome_prims[0]["h"] = H
    flat_prims = [chrome_prims[0]] + flat_prims + chrome_prims[1:]
    return flat_prims, chrome_prims, panel_groups, W, H, panel_meta
