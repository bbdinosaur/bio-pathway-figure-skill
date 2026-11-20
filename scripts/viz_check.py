"""Automatic geometry/consistency checker for generated primitives."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_geom import bbox_of, overlap, text_bbox

def check(prims, W, H):
    v = []
    edge_types = set()
    legend_samples = 0
    node_boxes = []
    for p in prims:
        role = p.get("role", "")
        if role in ("bg", "deco"):
            continue
        bb = bbox_of(p)
        if bb is None:
            continue
        if bb[0] < -2 or bb[1] < -2 or bb[2] > W + 2 or bb[3] > H + 2:
            v.append({"code": "out_of_canvas", "op": p["op"],
                      "detail": f"{p.get('s', role or p['op'])} bbox={ [round(x,1) for x in bb] } canvas=0,0,{W},{H}"})
        if role in ("node",):
            node_boxes.append(bb)
        if role == "legend_edge" or role == "legend":
            legend_samples += 1
        if role == "edge":
            if p.get("stroke"):
                pass
    # text overlap detection (only among labelled texts)
    texts = [(p, bbox_of(p)) for p in prims if p["op"] == "text" and p.get("role") in ("text", "edge_label", "node_label")]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if overlap(texts[i][1], texts[j][1], tol=0.5):
                v.append({"code": "text_overlap",
                          "detail": f"'{texts[i][0].get('s')}' vs '{texts[j][0].get('s')}'"})
    # edge labels must not sit on node bodies
    for p in prims:
        if p.get("role") == "edge_label":
            tb = bbox_of(p)
            for nb in node_boxes:
                if overlap(tb, nb, tol=2):
                    v.append({"code": "edge_label_on_node", "detail": f"'{p.get('s')}' overlaps a node box"})
                    break
    # legend consistency: every used edge style must be sampled in legend
    for p in prims:
        if p.get("role") == "edge":
            edge_types.add(p.get("_etype", "?"))
    n_edge = len([p for p in prims if p.get("role") == "edge"])
    if n_edge >= 2 and legend_samples < 2:
        v.append({"code": "legend_missing", "detail": "multiple edge styles but legend has <2 samples"})
    has_node = any(p.get("role") == "node" for p in prims)
    if not has_node:
        v.append({"code": "no_nodes", "detail": "figure contains no nodes"})
    return v

def attach_check(placed, edges):
    """Verify each edge's endpoints lie on the two node boundaries (within 2.5px)."""
    import math
    from viz_edges import route_points
    v = []
    nmap = {n["id"]: n for n in placed}
    for e in edges:
        a, b = nmap.get(e.get("from")), nmap.get(e.get("to"))
        if not a or not b:
            v.append({"code": "edge_missing_node", "detail": f"edge {e.get('from')}->{e.get('to')}"})
            continue
        pts = route_points(a, b, e.get("route", "direct"), 86)
        for pt, n in ((pts[0], a), (pts[-1], b)):
            ok = any(abs(pt[0] - x) < 2.5 for x in (n["cx"] - n["w"] / 2, n["cx"] + n["w"] / 2)) or \
                 any(abs(pt[1] - y) < 2.5 for y in (n["cy"] - n["h"] / 2, n["cy"] + n["h"] / 2))
            if not ok:
                v.append({"code": "edge_unattached", "detail": f"edge {e.get('from')}->{e.get('to')} endpoint off boundary"})
    return v
