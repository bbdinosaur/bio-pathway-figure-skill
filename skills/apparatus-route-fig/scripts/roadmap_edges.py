#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roadmap_edges.py — roadmap 时间轴、阶段交付箭头、反馈回路布线。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene
import sir as sirmod


def build_links(rg, sird):
    prims, labels = [], []
    ys = []
    geom, W, H = rg["geom"], rg["W"], rg["H"]
    T_TOP = rg["bottom"] - H
    skip_pad = float(rg.get("skip_pad") or 0.0)
    phases = sird.get("phases", [])
    colw_l, gap = rg.get("widths") or [rg["colw"]] * rg["n"], rg["gap"]
    # 时间轴（当存在跨阶段长边时自动抬升至顶通道上方，杜绝与跨阶箭头/标签碰撞）
    axis_y = T_TOP - 38.0 - skip_pad
    if phases:
        prims.append(scene.LN([(geom[phases[0]["id"]]["x"], axis_y),
                               (W - 30, axis_y)], stroke="#4A5568", sw=1.6,
                              marker="arrow", layer="frame", tag="axis"))
    for i, p in enumerate(phases):
        gg = geom[p["id"]]
        prims.append(scene.LN([(gg["cx"], axis_y - 5), (gg["cx"], axis_y + 5)],
                              stroke="#4A5568", sw=1.4, marker="none", layer="frame", tag="tick"))
        dur = str(p.get("duration") or "").strip()
        if dur:
            pw = colw_l[i] if i < len(colw_l) else 260
            dlines = sirmod.wrap_text(dur, 11.5, pw - 16)[:2]
            y_d0 = axis_y - 12.0 - 14.0 * (len(dlines) - 1)
            for li, ln in enumerate(dlines):
                labels.append(scene.TX(gg["cx"], y_d0 + 14.0 * li, ln,
                                       size=11.5, fill="#4A5568", layer="labels",
                                       node=p["id"], boxw=pw - 16))
    per_fb = {}
    per_top = {}
    for j, e in enumerate(rg["plinks"]):
        a, b = geom[e["from"]], geom[e["to"]]
        kind = e.get("kind", "handoff")
        ls = sirmod.LINK_STYLES.get(kind, sirmod.LINK_STYLES["handoff"])
        color, dash = ls[0], ls[1]
        meta = {"tag": "edge", "id": "pe%d" % j, "from": e["from"], "to": e["to"], "kind": kind}
        src = e.get("source") or {}
        if src.get("quote"):
            meta["prov"] = src["quote"]
        if src.get("loc"):
            meta["prov_loc"] = src["loc"]
        lab = str(e.get("label") or "").strip()
        mk = "tbar" if kind == "inhibit" else "arrow"
        if kind in ("feedback", "loop") or b["col"] < a["col"]:
            k = per_fb.get(0, 0)
            per_fb[0] = k + 1
            fy = rg["bottom"] + 28.0 + (k % 4) * 30.0
            ys.append(fy)
            dx = (0.0, 18.0, -18.0, 34.0)[k % 4]
            sx, tx = a["cx"] + dx, b["cx"] + dx
            prims.append(scene.LN([(sx, rg["bottom"]), (sx, fy),
                                   (tx, fy), (tx, rg["bottom"])],
                                  stroke=color, sw=1.8, dash=dash, marker=mk,
                                  layer="links", **meta))
            if lab:
                frac = (0.50, 0.34, 0.66, 0.42)[k % 4]
                labels.append(scene.TX(sx + (tx - sx) * frac, fy - 7, lab, size=11.5,
                                       fill="#2D3748", layer="labels", halo=True, edge="pe%d" % j))
        elif b["col"] == a["col"] + 1:
            hy = a["y"] + 19
            prims.append(scene.LN([(a["x"] + a["w"], hy), (b["x"], hy)],
                                  stroke=color, sw=2.0, dash=dash, marker=mk,
                                  layer="links", **meta))
            if lab:
                lines = sirmod.wrap_text(lab, 11.0, max(gap - 12.0, 74.0))[:2]
                y_start = hy - 8.0 - (len(lines) - 1) * 13.0
                for li, ln in enumerate(lines):
                    labels.append(scene.TX((a["x"] + a["w"] + b["x"]) / 2, y_start + li * 13.0, ln,
                                           size=11.0, fill="#2D3748", layer="labels",
                                           halo=True, edge="pe%d" % j))
        elif b["col"] > a["col"] + 1:
            k = per_top.get(0, 0)
            per_top[0] = k + 1
            ty = T_TOP - 28.0 - (k % 3) * 26.0
            dx = (0.0, 18.0, -18.0)[k % 3]
            sx, tx = a["cx"] + dx, b["cx"] + dx
            prims.append(scene.LN([(sx, T_TOP), (sx, ty), (tx, ty), (tx, T_TOP)],
                                  stroke=color, sw=1.8, dash=dash, marker=mk,
                                  layer="links", **meta))
            if lab:
                frac = 0.34 if (k % 2 == 0) else 0.64
                labels.append(scene.TX(sx + (tx - sx) * frac, ty - 7, lab, size=11.0,
                                       fill="#2D3748", layer="labels", halo=True, edge="pe%d" % j))
    return {"edge_prims": prims, "labels": labels, "bus_ys": ys}
