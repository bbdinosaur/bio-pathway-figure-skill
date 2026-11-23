#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene.py — 图面场景原语（primitives）与包围盒计算。

scene 是一个 dict: {"w": int, "h": int, "prims": [prim, ...]}
prim 是纯 dict（可 JSON 序列化），由 svgfig.py / mirror.py / checks.py 共享。
仅依赖 Python 标准库。
"""
from __future__ import annotations
import json


def R(x, y, w, h, fill="#ffffff", stroke="#333333", sw=1.5, rx=8, dash=None,
      layer="nodes", **meta):
    """圆角矩形。"""
    return {"op": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill,
            "stroke": stroke, "sw": sw, "rx": rx, "dash": dash,
            "layer": layer, "meta": meta}


def LN(pts, stroke="#2B6CB0", sw=1.8, dash=None, marker="arrow",
       layer="links", **meta):
    """折线（polyline），可带末端箭头 marker: arrow|arrowboth|none。"""
    return {"op": "line", "pts": [[float(px), float(py)] for px, py in pts],
            "stroke": stroke, "sw": sw, "dash": dash, "marker": marker,
            "layer": layer, "meta": meta}


def TX(x, y, s, size=13, anchor="middle", weight="normal", fill="#1A202C",
       layer="labels", **meta):
    """文本。anchor: start|middle|end。可附 meta: boxw(所在盒宽), node(归属节点id)"""
    return {"op": "text", "x": float(x), "y": float(y), "s": s, "size": size,
            "anchor": anchor, "weight": weight, "fill": fill, "layer": layer,
            "meta": meta}


def EL(cx, cy, rx, ry, fill="#ffffff", stroke="#333333", sw=1.2, dash=None,
       layer="nodes", **meta):
    """椭圆/圆（图元 glyph 用）。"""
    return {"op": "ellipse", "cx": float(cx), "cy": float(cy), "rx": float(rx),
            "ry": float(ry), "fill": fill, "stroke": stroke, "sw": sw,
            "dash": dash, "layer": layer, "meta": meta}


def line_bbox(p):
    xs = [pt[0] for pt in p["pts"]]
    ys = [pt[1] for pt in p["pts"]]
    return min(xs), min(ys), max(xs), max(ys)


def bbox(p):
    """返回 (x0, y0, x1, y1)。"""
    if p["op"] == "rect":
        return (p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"])
    if p["op"] == "ellipse":
        return (p["cx"] - p["rx"], p["cy"] - p["ry"], p["cx"] + p["rx"], p["cy"] + p["ry"])
    if p["op"] == "line":
        return line_bbox(p)
    if p["op"] == "text":
        return text_bbox(p)
    raise ValueError("unknown op: %r" % p["op"])


def text_bbox(p):
    """基于估算宽度的文本包围盒（需 text_metrics；由调用方注入 est_w 函数）。"""
    est = p.get("_est_w")  # 由 checks/svgfig 在内存中注入的函数
    lines = p["s"].split("\n")
    w = max((est(ln, p["size"], p["weight"] == "bold") if est else len(ln) * p["size"])
            for ln in lines) if lines else p["size"]
    h = p["size"] * 1.35 * len(lines)
    x0 = p["x"] - w if p["anchor"] == "end" else (p["x"] - w / 2 if p["anchor"] == "middle" else p["x"])
    return (x0, p["y"] - p["size"] * 1.05, x0 + w, p["y"] + p["size"] * 0.32 * len(lines) + p["size"] * 0.15 * (len(lines) - 1))


def to_json(scene):
    return json.dumps(scene, ensure_ascii=False, indent=1)


def from_json(s):
    return json.loads(s)
