#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_roadmap.py — roadmap SIR → 阶段列布点（中英文双语自适应）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene
import sir as sirmod

MINW = 210.0
MAXW = 340.0
COLGAP = 92.0
T_TOP = 152.0
L_M = 56.0
R_M = 56.0
FS_H = 14.0
FS_B = 11.5
SECTIONS_ZH = [("goals", "目标"), ("tasks", "核心任务"), ("methods", "方法"),
               ("milestones", "里程碑"), ("deliverables", "交付物"),
               ("criteria", "验收标准"), ("inputs", "输入"), ("outputs", "输出")]
SECTIONS_EN = [("goals", "Objectives"), ("tasks", "Key Tasks"), ("methods", "Methods"),
               ("milestones", "Milestones"), ("deliverables", "Deliverables"),
               ("criteria", "Gate Criteria"), ("inputs", "Inputs"), ("outputs", "Outputs")]


def _sections(lang):
    return SECTIONS_EN if lang == "en" else SECTIONS_ZH


def _phase_lines(p, colw=260.0, lang="zh"):
    hlines = sirmod.wrap_text(p.get("name", ""), FS_H, colw - 24, bold=True)
    secs = []
    for key, _cap in _sections(lang):
        items = p.get(key) or []
        if not items:
            continue
        lines = []
        for it in items:
            pre = "◆ " if key == "milestones" else "• "
            lines += sirmod.wrap_text(pre + str(it), FS_B, colw - 34)
        secs.append(lines)
    return hlines, secs


def _need_w(p, lang="zh"):
    w = sirmod.est_w(p.get("name", ""), FS_H, True) + 32
    for key, _cap in _sections(lang):
        for it in p.get(key) or []:
            pre = "◆ " if key == "milestones" else "• "
            w = max(w, sirmod.est_w(pre + str(it), FS_B) + 46)
    return min(max(w, MINW), MAXW)


def build_roadmap(sird):
    lang = sirmod.detect_lang(sird)
    phases = sird.get("phases", [])
    plinks = sird.get("phase_links", [])
    n = len(phases)
    pidx = {p["id"]: i for i, p in enumerate(phases)}
    n_skip = sum(1 for e in plinks if e.get("kind") not in ("feedback", "loop")
                 and pidx.get(e.get("to"), -1) > pidx.get(e.get("from"), -1) + 1)
    skip_pad = (34.0 + 26.0 * min(n_skip, 3)) if n_skip else 0.0
    has_adj_lbl = any(
        e.get("kind") not in ("feedback", "loop") and pidx.get(e.get("to"), -1) == pidx.get(e.get("from"), -1) + 1
        and str(e.get("label") or "").strip()
        for e in plinks
    )
    colgap = 112.0 if has_adj_lbl else COLGAP
    widths = [_need_w(p, lang) for p in phases]
    W = L_M + sum(widths) + max(n - 1, 0) * colgap + R_M if n else 800
    title_s = str(sird.get("title") or "").strip()
    sub_s = str(sird.get("subtitle") or "").strip()
    t_lines = sirmod.wrap_text(title_s, 19.5, W - 56, bold=True)[:2] if title_s else [""]
    sub_lines = sirmod.wrap_text(sub_s, 12.2, W - 56)[:2] if sub_s else []
    header_bot = (38.0 + (len(t_lines) - 1) * 23.0) + (16.0 + len(sub_lines) * 17.0 if sub_lines else 14.0) + 12.0
    max_dur_lines = 1
    for p, wd in zip(phases, widths):
        d = str(p.get("duration") or "").strip()
        if d:
            max_dur_lines = max(max_dur_lines, min(len(sirmod.wrap_text(d, 11.5, wd - 16)), 2))
    dur_h = 26.0 + (max_dur_lines - 1) * 14.0
    t_top = max(T_TOP, header_bot + dur_h + 38.0) + skip_pad
    xs = []
    acc = L_M
    for wd in widths:
        xs.append(acc)
        acc += wd + colgap
    geom, prims = {}, []
    heights = []
    for p, wd in zip(phases, widths):
        hlines, secs = _phase_lines(p, wd, lang)
        hh = 32 + (len(hlines) - 1) * 18
        body = 22 + sum(15 + len(ls) * 15.5 + 5 for ls in secs) + 14
        heights.append(hh + body)
    H = max(heights) if heights else 260.0
    for i, p in enumerate(phases):
        wd = widths[i]
        x = xs[i]
        color = sirmod.PALETTE6[i % len(sirmod.PALETTE6)]
        geom[p["id"]] = {"x": x, "y": t_top, "w": wd, "h": H, "cx": x + wd / 2.0,
                         "cy": t_top + H / 2.0, "col": i, "band": 0, "color": color}
        meta = {"tag": "node", "id": p["id"]}
        src = p.get("source") or {}
        if src.get("quote"):
            meta["prov"] = src["quote"]
        if src.get("loc"):
            meta["prov_loc"] = src["loc"]
        prims.append(scene.R(x + 2.0, t_top + 2.5, wd, H, fill="#E2E8F0", stroke="none",
                             sw=0, rx=10, layer="frame", tag="shadow"))
        prims.append(scene.R(x, t_top, wd, H, fill="#FBFDFF", stroke=color,
                             sw=1.8, rx=10, layer="nodes", **meta))
        hlines, secs = _phase_lines(p, wd, lang)
        hh = 32 + (len(hlines) - 1) * 18
        prims.append(scene.R(x, t_top, wd, hh, fill=color, stroke=color, sw=0, rx=10,
                             layer="nodes", tag="node_header", id=p["id"]))
        prims.append(scene.R(x, t_top + hh - 12, wd, 12, fill=color, stroke="none",
                             sw=0, rx=0, layer="nodes", tag="patch", id=p["id"]))
        ty = t_top + hh / 2.0 - (len(hlines) - 1) * 9.0 + FS_H * 0.36
        prims.append(scene.TX(x + wd / 2.0, ty, "\n".join(hlines), size=FS_H, weight="bold",
                              fill="#FFFFFF", layer="labels", node=p["id"], boxw=wd - 24))
        yy = t_top + hh + 22
        si = 0
        for key, cap in _sections(lang):
            items = p.get(key) or []
            if not items:
                continue
            if si > 0:
                prims.append(scene.LN([(x + 14, yy - 11.5), (x + wd - 14, yy - 11.5)],
                                      stroke="#E2E8F0", sw=0.9, marker="none", layer="nodes", tag="sec_div"))
            ls = secs[si]
            si += 1
            prims.append(scene.TX(x + 17, yy, cap, size=10.5, weight="bold", anchor="start",
                                  fill="#718096", layer="labels", node=p["id"], boxw=wd - 34))
            yy += 15
            for ln in ls:
                prims.append(scene.TX(x + 17, yy, ln, size=FS_B, anchor="start",
                                      fill=("#9C4221" if key == "milestones" else "#2D3748"),
                                      weight=("bold" if key == "milestones" else "normal"),
                                      layer="labels", node=p["id"],
                                      boxw=wd - 34))
                yy += 15.5
            yy += 5
    return {"geom": geom, "node_prims": prims, "W": W, "H": H, "bottom": t_top + H,
            "skip_pad": skip_pad, "n": n, "plinks": plinks,
            "col_x": {i: xs[i] for i in range(n)},
            "colw": max(widths) if widths else 260, "widths": widths, "gap": colgap}
