"""Geometry helpers: node boundary anchors, port offsets, marker polygons, text bboxes."""
from __future__ import annotations
import math

def norm(dx, dy):
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d

def perp(dx, dy):
    return -dy, dx

def boundary_point(node, tx, ty, port_offset=0.0):
    """Point on node border along ray center->(tx,ty).
    Optional port_offset slides the anchor strictly ALONG the contacted border edge
    (clamped inside the edge) so parallel edges stay 100% attached to the node boundary."""
    cx, cy = node["cx"], node["cy"]
    hw, hh = node["w"] / 2.0, node["h"] / 2.0
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx + hw, cy
    shape = node.get("shape", "rect")
    if shape == "ellipse":
        if port_offset:
            # Shift in fixed canvas axis (+y for horizontal rays, +x for vertical rays) so parallel ellipse edges never cross
            if abs(dx) >= abs(dy):
                py_cl = max(-hh * 0.72, min(hh * 0.72, (dy * (hw / (abs(dx) or 1.0))) + port_offset))
                sx_s = 1.0 if dx >= 0 else -1.0
                px_e = sx_s * hw * math.sqrt(max(0.05, 1.0 - (py_cl / max(hh, 1.0)) ** 2))
                return cx + px_e, cy + py_cl
            px_cl = max(-hw * 0.72, min(hw * 0.72, (dx * (hh / (abs(dy) or 1.0))) + port_offset))
            sy_s = 1.0 if dy >= 0 else -1.0
            py_e = sy_s * hh * math.sqrt(max(0.05, 1.0 - (px_cl / max(hw, 1.0)) ** 2))
            return cx + px_cl, cy + py_e
        ang = math.atan2(dy, dx)
        return cx + hw * math.cos(ang), cy + hh * math.sin(ang)
    ts = abs(hw / dx) if dx else float("inf")
    tt = abs(hh / dy) if dy else float("inf")
    if ts < tt:
        # hits left or right vertical edge
        px = cx + (hw if dx > 0 else -hw)
        py = cy + dy * ts
        if port_offset:
            py = max(cy - hh + 6.0, min(cy + hh - 6.0, py + port_offset))
        return px, py
    else:
        # hits top or bottom horizontal edge
        px = cx + dx * tt
        py = cy + (hh if dy > 0 else -hh)
        if port_offset:
            px = max(cx - hw + 8.0, min(cx + hw - 8.0, px + port_offset))
        return px, py

MARKER_LEN = {"arrow": 13, "open": 13, "bar": 2.5, "circle": 15, "open_dot": 9, "diamond": 9, "cross": 7}

def arrow_poly(tip, dirv, length=13, half=5.2):
    bx, by = tip[0] - dirv[0] * length, tip[1] - dirv[1] * length
    nx, ny = perp(*dirv)
    return [[tip[0], tip[1]], [bx + nx * half, by + ny * half], [bx - nx * half, by - ny * half]]

def diamond_poly(tip, dirv, r=5.2):
    cx, cy = tip[0] - dirv[0] * r, tip[1] - dirv[1] * r
    nx, ny = perp(*dirv)
    return [[cx + nx * r, cy + ny * r], [cx + dirv[0] * r, cy + dirv[1] * r],
            [cx - nx * r, cy - ny * r], [cx - dirv[0] * r, cy - dirv[1] * r]]

def text_bbox(x, y, s, size, anchor="middle"):
    lines = str(s).split("\n")
    w = 0.0
    for ln in lines:
        lw = 0.0
        for ch in ln:
            lw += size * (1.0 if ord(ch) > 0x2E80 else 0.62)
        w = max(w, lw)
    w = max(w, size * 0.6)
    h = size * (1.24 if len(lines) == 1 else (1.25 * len(lines)))
    if anchor == "start":
        x0 = x
    elif anchor == "end":
        x0 = x - w
    else:
        x0 = x - w / 2.0
    return [x0, y - h / 2.0, x0 + w, y + h / 2.0]

def bbox_of(prim):
    op = prim["op"]
    if op == "rect":
        return [prim["x"], prim["y"], prim["x"] + prim["w"], prim["y"] + prim["h"]]
    if op == "circle":
        r = prim["r"]
        return [prim["cx"] - r, prim["cy"] - r, prim["cx"] + r, prim["cy"] + r]
    if op == "ellipse":
        rx, ry = prim["rx"], prim["ry"]
        return [prim["cx"] - rx, prim["cy"] - ry, prim["cx"] + rx, prim["cy"] + ry]
    if op in ("polyline", "polygon", "poly"):
        pts = prim["pts"]
        if not pts:
            return None
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return [min(xs), min(ys), max(xs), max(ys)]
    if op == "text":
        if prim.get("rotate"):
            tb = text_bbox(0, 0, prim["s"], prim.get("size", 15))
            w = tb[2] - tb[0]
            h = tb[3] - tb[1]
            return [prim["x"] - h / 2.0, prim["y"] - w / 2.0,
                    prim["x"] + h / 2.0, prim["y"] + w / 2.0]
        return text_bbox(prim["x"], prim["y"], prim["s"], prim.get("size", 15),
                         prim.get("anchor", "middle"))
    return None

def overlap(a, b, tol=1.5):
    return not (a[2] <= b[0] + tol or b[2] <= a[0] + tol or
                a[3] <= b[1] + tol or b[3] <= a[1] + tol)
