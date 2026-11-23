"""Automatic geometry & consistency checker for generated primitives."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_geom import bbox_of, overlap

def check(prims, W, H):
    v = []
    edge_types = set()
    legend_samples = 0
    node_boxes = []
    for p in prims:
        role = p.get("role", "")
        if role in ("bg", "deco", "group", "edge_label_bg"):
            continue
        bb = bbox_of(p)
        if bb is None:
            continue
        if bb[0] < -2 or bb[1] < -2 or bb[2] > W + 2 or bb[3] > H + 2:
            v.append({"code": "out_of_canvas", "op": p["op"],
                      "detail": f"{p.get('s', role or p['op'])} bbox={[round(x, 1) for x in bb]} canvas=0,0,{W},{H}"})
        if role == "node":
            node_boxes.append(bb)
        if role in ("legend_edge", "legend"):
            legend_samples += 1
        if role == "edge" and p.get("_etype"):
            edge_types.add(p["_etype"])

    # Text overlap detection across visible text roles (including legend texts!)
    texts = [(p, bbox_of(p)) for p in prims
             if p["op"] == "text" and p.get("role") in ("text", "edge_label", "node_label", "legend")]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if overlap(texts[i][1], texts[j][1], tol=0.5):
                v.append({"code": "text_overlap",
                          "detail": f"'{texts[i][0].get('s')}' vs '{texts[j][0].get('s')}'"})

    # Edge labels must not sit on node bodies
    for p in prims:
        if p.get("role") == "edge_label":
            tb = bbox_of(p)
            for nb in node_boxes:
                if overlap(tb, nb, tol=2.0):
                    v.append({"code": "edge_label_on_node", "detail": f"'{p.get('s')}' overlaps a node box"})
                    break

    if len(edge_types) >= 2 and legend_samples < 2:
        v.append({"code": "legend_missing", "detail": f"{len(edge_types)} edge types used but legend missing"})
    if not any(p.get("role") == "node" for p in prims):
        v.append({"code": "no_nodes", "detail": "figure contains no nodes"})
    return v

def attach_check(placed, edges, routed=None):
    """Verify each edge's endpoints lie on the two node boundaries (within 3.0px)."""
    from viz_edges import route_points
    v = []
    nmap = {n["id"]: n for n in placed}
    if routed is not None:
        items = [(r["from"], r["to"], r["pts"]) for r in routed]
    else:
        items = []
        for e in edges:
            a, b = nmap.get(e.get("from")), nmap.get(e.get("to"))
            if not a or not b:
                v.append({"code": "edge_missing_node", "detail": f"edge {e.get('from')}->{e.get('to')}"})
                continue
            items.append((e.get("from"), e.get("to"), route_points(a, b, e.get("route", "direct"), 88)))
    for u, w, pts in items:
        a, b = nmap.get(u), nmap.get(w)
        if not a or not b:
            v.append({"code": "edge_missing_node", "detail": f"edge {u}->{w}"})
            continue
        for pt, n in ((pts[0], a), (pts[-1], b)):
            shape = n.get("shape", "rect")
            if shape == "ellipse":
                val = ((pt[0] - n["cx"]) / (n["w"] / 2.0)) ** 2 + ((pt[1] - n["cy"]) / (n["h"] / 2.0)) ** 2
                ok = abs(val - 1.0) < 0.12
            else:
                on_x = (any(abs(pt[0] - x) < 3.0 for x in (n["cx"] - n["w"] / 2, n["cx"] + n["w"] / 2))
                        and (n["cy"] - n["h"] / 2 - 3.0 <= pt[1] <= n["cy"] + n["h"] / 2 + 3.0))
                on_y = (any(abs(pt[1] - y) < 3.0 for y in (n["cy"] - n["h"] / 2, n["cy"] + n["h"] / 2))
                        and (n["cx"] - n["w"] / 2 - 3.0 <= pt[0] <= n["cx"] + n["w"] / 2 + 3.0))
                ok = on_x or on_y
            if not ok:
                v.append({"code": "edge_unattached", "detail": f"edge {u}->{w} endpoint off boundary"})
        # Also verify routed polyline does not cut through any intermediate non-endpoint node
        for nid, on in nmap.items():
            if nid in (u, w):
                continue
            ox0, oy0 = on["cx"] - on["w"] / 2.0 + 4.0, on["cy"] - on["h"] / 2.0 + 4.0
            ox1, oy1 = on["cx"] + on["w"] / 2.0 - 4.0, on["cy"] + on["h"] / 2.0 - 4.0
            if ox0 >= ox1 or oy0 >= oy1:
                continue
            hit = False
            for si in range(len(pts) - 1):
                p0, p1 = pts[si], pts[si + 1]
                for ti in range(1, 32):
                    t = ti / 32.0
                    px = p0[0] + (p1[0] - p0[0]) * t
                    py = p0[1] + (p1[1] - p0[1]) * t
                    if ox0 < px < ox1 and oy0 < py < oy1:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                v.append({"code": "edge_through_node",
                          "detail": f"edge {u}->{w} cuts through intermediate node {nid}"})
                break
    return v
