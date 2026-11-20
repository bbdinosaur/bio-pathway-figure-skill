"""Geometry helpers: node boundary anchors, marker polygons, perp vectors."""
from __future__ import annotations
import math

def norm(dx, dy):
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d

def perp(dx, dy):
    return -dy, dx

def boundary_point(node, tx, ty):
    """Point on node border along ray center->(tx,ty)."""
    cx, cy = node["cx"], node["cy"]
    hw, hh = node["w"] / 2.0, node["h"] / 2.0
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx + hw, cy
    if node.get("shape") == "ellipse":
        t = 1.0 / math.sqrt((dx / hw) ** 2 + (dy / hh) ** 2)
    else:
        ts = abs(hw / dx) if dx else float("inf")
        tt = abs(hh / dy) if dy else float("inf")
        t = min(ts, tt)
    return cx + dx * t, cy + dy * t

MARKER_LEN = {"arrow": 14, "open": 14, "bar": 2, "circle": 6, "diamond": 9}

def arrow_poly(tip, dirv, length=14, half=5.5):
    bx, by = tip[0] - dirv[0] * length, tip[1] - dirv[1] * length
    nx, ny = perp(*dirv)
    return [[tip[0], tip[1]], [bx + nx * half, by + ny * half], [bx - nx * half, by - ny * half]]

def diamond_poly(tip, dirv, r=5.5):
    cx, cy = tip[0] - dirv[0] * r, tip[1] - dirv[1] * r
    nx, ny = perp(*dirv)
    return [[cx + nx * r, cy + ny * r], [cx + dirv[0] * r, cy + dirv[1] * r],
            [cx - nx * r, cy - ny * r], [cx - dirv[0] * r, cy - dirv[1] * r]]

def text_bbox(x, y, s, size, anchor="middle"):
    w = 0.62 * size * max(1, len(str(s)))
    if anchor == "start":
        x0 = x
    elif anchor == "end":
        x0 = x - w
    else:
        x0 = x - w / 2.0
    return [x0, y - size * 0.62, x0 + w, y + size * 0.62]

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
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return [min(xs), min(ys), max(xs), max(ys)]
    if op == "text":
        if prim.get("rotate"):
            w = text_bbox(0, 0, prim["s"], prim.get("size", 15))[2]
            return [prim["x"] - prim.get("size", 15), prim["y"] - w / 2,
                    prim["x"] + prim.get("size", 15), prim["y"] + w / 2]
        return text_bbox(prim["x"], prim["y"], prim["s"], prim.get("size", 15),
                         prim.get("anchor", "middle"))
    return None

def overlap(a, b, tol=1.5):
    return not (a[2] <= b[0] + tol or b[2] <= a[0] + tol or
                a[3] <= b[1] + tol or b[3] <= a[1] + tol)
