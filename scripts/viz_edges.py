"""Edge rendering with semantic markers (arrow/bar/diamond/circle/open) + feedback routing."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import EDGE_STYLES
from viz_geom import norm, perp, boundary_point, arrow_poly, diamond_poly, MARKER_LEN

def route_points(n_from, n_to, route, gap, m_override=None):
    if route in ("feedback", "arc"):
        m = m_override if m_override else (max(30.0, gap * 0.55) if route == "feedback" else 30.0)
        sx, sy = n_from["cx"], n_from["cy"] - n_from["h"] / 2.0
        tx, ty = n_to["cx"], n_to["cy"] - n_to["h"] / 2.0
        yl = min(sy, ty) - m
        return [[sx, sy], [sx, yl], [tx, yl], [tx, ty]]
    sx, sy = n_from["cx"], n_from["cy"]
    tx, ty = n_to["cx"], n_to["cy"]
    a = boundary_point(n_from, tx, ty)
    b = boundary_point(n_to, sx, sy)
    return [list(a), list(b)]

def _seg_hits_boxes(p0, p1, boxes, skip):
    """True if segment p0-p1 passes strictly inside any non-skipped node box."""
    for nid, bb in boxes:
        if nid in skip:
            continue
        x0, y0, x1, y1 = bb[0] + 2, bb[1] + 2, bb[2] - 2, bb[3] - 2
        for i in range(1, 40):
            t = i / 40.0
            px = p0[0] + (p1[0] - p0[0]) * t
            py = p0[1] + (p1[1] - p0[1]) * t
            if x0 < px < x1 and y0 < py < y1:
                return True
    return False

def draw_edges(edges, placed, gap, prims, node_boxes=None, opts=None):
    nmap = {n["id"]: n for n in placed}
    used = []
    arc_i = [0]
    opts = opts or {}
    auto_dash = bool(opts.get("evidence_auto_style"))
    for e in edges:
        a, b = nmap.get(e.get("from")), nmap.get(e.get("to"))
        if not a or not b:
            continue
        et = e.get("type", "other")
        st = EDGE_STYLES.get(et, EDGE_STYLES["other"])
        if et not in used:
            used.append(et)
        pts = route_points(a, b, e.get("route", "direct"), gap)
        eff_route = e.get("route", "direct")
        if eff_route == "direct" and node_boxes and opts.get("auto_arc", True):
            same_row = abs(a["cy"] - b["cy"]) <= (a["h"] + b["h"]) / 2.0 + 12
            if same_row and _seg_hits_boxes(pts[0], pts[-1], node_boxes,
                                            skip={e.get("from"), e.get("to")}):
                arc_i[0] += 1
                pts = route_points(a, b, "arc", gap,
                                   m_override=26.0 + 15.0 * (arc_i[0] - 1))
                eff_route = "arc"
        dashed = bool(e.get("dashed"))
        if auto_dash and not e.get("dashed"):
            ev = str(e.get("evidence") or "").lower()
            if ev in ("reported", "inferred", "indirect", "putative", "weak"):
                dashed = True
        dotted = bool(e.get("dotted")) or (
            auto_dash and str(e.get("evidence") or "").lower() == "weak")
        col = e.get("color") or st["color"]
        tip = pts[-1]
        seg_dir = norm(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        back = seg_dir[0] * MARKER_LEN[st["end"]] * -1, seg_dir[1] * MARKER_LEN[st["end"]] * -1
        line_end = [tip[0] + back[0], tip[1] + back[1]]
        body = pts[:-1] + [line_end]
        prims.append({"op": "polyline", "pts": body, "stroke": col, "stroke_w": 2.4,
                      "dashed": dashed, "dotted": dotted, "role": "edge",
                      "_id": f"edge-{len(prims)}-{e.get('from')}-{e.get('to')}"})
        _draw_marker(prims, st, tip, seg_dir, col, et, e)
        if st.get("both"):
            d0 = norm(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            _draw_marker(prims, st, pts[0], d0, col, et, e, start=True)
        lbl = e.get("label") or st.get("tag") or ""
        _edge_label(prims, pts, lbl, e, col, route=eff_route,
                    tip_style=(st.get("tag") and not e.get("label")),
                    node_boxes=node_boxes or [])
    return used

def _draw_marker(prims, st, tip, dirv, col, et, e, start=False):
    end = st["end"]
    if end == "arrow":
        prims.append({"op": "poly", "pts": arrow_poly(tip, dirv), "fill": col,
                      "stroke": "none", "stroke_w": 0, "role": "edge"})
    elif end == "open":
        prims.append({"op": "poly", "pts": arrow_poly(tip, dirv), "fill": "#ffffff",
                      "stroke": col, "stroke_w": 2.0, "role": "edge"})
    elif end == "bar":
        c = [tip[0] - dirv[0] * 1.5, tip[1] - dirv[1] * 1.5]
        nx, ny = perp(*dirv)
        prims.append({"op": "polyline", "pts": [[c[0] + nx * 7, c[1] + ny * 7],
                     [c[0] - nx * 7, c[1] - ny * 7]], "stroke": col, "stroke_w": 3.6, "role": "edge"})
    elif end == "circle":
        c = [tip[0] - dirv[0] * 6, tip[1] - dirv[1] * 6]
        prims.append({"op": "circle", "cx": c[0], "cy": c[1], "r": 5.5, "fill": col,
                      "stroke": "none", "stroke_w": 0, "role": "edge"})
    elif end == "diamond":
        prims.append({"op": "poly", "pts": diamond_poly(tip, dirv), "fill": "#ffffff",
                      "stroke": col, "stroke_w": 2.0, "role": "edge"})

def _edge_label(prims, pts, lbl, e, col, route="direct", tip_style=False, node_boxes=None):
    if not lbl:
        return
    if route in ("feedback", "arc"):
        anchors = [((pts[1][0] + pts[2][0]) / 2.0, pts[1][1] - 12)]
    elif tip_style:
        dirv = norm(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        nx, ny = perp(*dirv)
        anchors = [(pts[-1][0] - dirv[0] * 14 + nx * 15,
                    pts[-1][1] - dirv[1] * 14 + ny * 15)]
    else:
        anchors = [(pts[0][0] + (pts[1][0] - pts[0][0]) * t,
                    pts[0][1] + (pts[1][1] - pts[0][1]) * t - 11) for t in (0.5, 0.32)]
    txt = str(lbl)
    if e.get("evidence"):
        txt += f" [{e['evidence']}]"
    _label_no_overlap(prims, anchors, txt, col, node_boxes=node_boxes or [])

def _label_no_overlap(prims, anchors, txt, col, node_boxes=None):
    """Place label near the first clear anchor; shifts until clear of texts and node boxes."""
    from viz_geom import text_bbox, overlap
    existing = [text_bbox(p["x"], p["y"], p["s"], p.get("size", 15), p.get("anchor", "middle"))
                for p in prims if p["op"] == "text"]
    nodes = [nb[1] if isinstance(nb, tuple) and len(nb) == 2 and isinstance(nb[1], list)
             else nb for nb in (node_boxes or [])]
    shifts = ((0, 0), (0, -15), (0, 15), (-22, 0), (22, 0), (0, -30), (0, 30),
              (-40, 0), (40, 0), (0, -45), (0, 45), (-22, -22), (22, 22), (22, -22), (-22, 22),
              (-22, -30), (22, -30), (-40, -15), (40, -15), (0, -60), (0, 60), (-60, 0), (60, 0),
              (-40, 15), (40, 15), (-22, 30), (22, 30))
    best = None
    for ax, ay in anchors:
        for dx, dy in shifts:
            bb = text_bbox(ax + dx, ay + dy, txt, 12.5, "middle")
            hits = sum(1 for eb in existing if overlap(bb, eb, tol=0.5)) + \
                   sum(1 for nb in nodes if overlap(bb, nb, tol=2))
            if hits == 0:
                _emit_label(prims, ax + dx, ay + dy, txt, col)
                return
            if best is None or hits < best[0]:
                best = (hits, ax + dx, ay + dy)
    _emit_label(prims, best[1], best[2], txt, col)

def _emit_label(prims, x, y, txt, col):
    prims.append({"op": "text", "x": x, "y": y, "s": txt, "size": 12.5, "anchor": "middle",
                  "fill": col, "weight": "bold", "role": "edge_label",
                  "_id": f"edgelabel-{len(prims)}"})
