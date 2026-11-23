#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""glyphs.py — 器件图元库（中英文 + 化学/物理/生物学实验器材）：
从 node['icon'] 或 label/attrs 关键词自动匹配造型，绘制在节点盒左侧图标区。
全部为几何近似造型（线/矩形/椭圆），svgfig 与 mirror 双端一致渲染。
"""
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene

ACC = "#2B6CB0"


def _g_pump(x, y, w, h):
    cx, cy, r = x + w / 2, y + h / 2, min(w, h) / 2 - 1.5
    p = [scene.EL(cx, cy, r, r, fill="#ffffff", stroke=ACC, sw=1.4, layer="nodes", tag="glyph")]
    p.append(scene.LN([(cx - r * 0.45, cy - r * 0.5), (cx + r * 0.55, cy),
                       (cx - r * 0.45, cy + r * 0.5), (cx - r * 0.45, cy - r * 0.5)],
                      stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph"))
    return p


def _g_valve(x, y, w, h):
    cx, cy, s = x + w / 2, y + h / 2, min(w, h) / 2 - 1
    return [scene.LN([(cx - s, cy - s * 0.8), (cx, cy), (cx + s, cy - s * 0.8), (cx + s, cy + s * 0.8),
                      (cx, cy), (cx - s, cy + s * 0.8), (cx - s, cy - s * 0.8)],
                     stroke=ACC, sw=1.3, marker="none", layer="nodes", tag="glyph")]


def _g_mix(x, y, w, h):
    cx, cy, r = x + w / 2, y + h / 2, min(w, h) / 2 - 1.5
    p = [scene.EL(cx, cy, r, r, fill="#ffffff", stroke=ACC, sw=1.3, layer="nodes", tag="glyph")]
    for s in (1, -1):
        p.append(scene.LN([(cx - s * r * 0.65, cy - r * 0.65), (cx + s * r * 0.65, cy + r * 0.65)],
                          stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph"))
    return p


def _g_reactor(x, y, w, h):
    cx, top, bot = x + w / 2, y + 2, y + h - 2
    nw, bw = w * 0.28, w * 0.54
    return [scene.LN([(cx - nw / 2, top), (cx - nw / 2, top + h * 0.35), (cx - bw / 2, bot),
                      (cx + bw / 2, bot), (cx + nw / 2, top + h * 0.35), (cx + nw / 2, top)],
                     stroke=ACC, sw=1.3, marker="none", layer="nodes", tag="glyph"),
            scene.LN([(cx - bw / 2 - 2, bot), (cx + bw / 2 + 2, bot)], stroke=ACC,
                     sw=1.5, marker="none", layer="nodes", tag="glyph")]


def _g_coil(x, y, w, h):
    cy, n, step = y + h / 2, 5, w / 6.0
    pts = [(x, cy)]
    for i in range(n):
        pts.append((x + step * (i + 0.5), cy - (h * 0.32 if i % 2 == 0 else -h * 0.32)))
        pts.append((x + step * (i + 1), cy))
    return [scene.LN(pts, stroke=ACC, sw=1.3, marker="none", layer="nodes", tag="glyph")]


def _g_bottle(x, y, w, h):
    cx = x + w / 2
    nw, bw = w * 0.24, w * 0.62
    return [scene.LN([(cx - nw / 2, y + 1), (cx - nw / 2, y + h * 0.3), (cx - bw / 2, y + h * 0.42),
                      (cx - bw / 2, y + h - 1), (cx + bw / 2, y + h - 1), (cx + bw / 2, y + h * 0.42),
                      (cx + nw / 2, y + h * 0.3), (cx + nw / 2, y + 1)],
                     stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph")]


def _g_eye(x, y, w, h):
    cx, cy = x + w / 2, y + h / 2
    return [scene.LN([(x, cy), (x + w * 0.2, cy - h * 0.28), (x + w * 0.8, cy - h * 0.28), (x + w, cy),
                      (x + w * 0.8, cy + h * 0.28), (x + w * 0.2, cy + h * 0.28), (x, cy)],
                     stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph"),
            scene.EL(cx, cy - h * 0.02, w * 0.14, h * 0.14, fill=ACC, stroke=ACC, sw=0.5,
                     layer="nodes", tag="glyph")]


def _g_ctrl(x, y, w, h):
    return [scene.R(x + 2, y + 3, w - 4, h - 9, fill="#ffffff", stroke=ACC, sw=1.2, rx=2,
                    layer="nodes", tag="glyph"),
            scene.LN([(x + 6, y + h - 3), (x + w - 6, y + h - 3)], stroke=ACC, sw=1.2,
                     marker="none", layer="nodes", tag="glyph"),
            scene.EL(x + w * 0.62, y + h * 0.38, w * 0.1, h * 0.12, fill=ACC, stroke=ACC,
                     sw=0.5, layer="nodes", tag="glyph")]


def _g_light(x, y, w, h):
    cx, cy, r = x + w / 2, y + h / 2, min(w, h) * 0.26
    p = [scene.EL(cx, cy, r, r, fill="#FFF4E0", stroke="#C05621", sw=1.2, layer="nodes", tag="glyph")]
    for k in range(8):
        a = math.pi / 4 * k
        p.append(scene.LN([(cx + r * 1.5 * math.cos(a), cy + r * 1.5 * math.sin(a)),
                           (cx + r * 2.4 * math.cos(a), cy + r * 2.4 * math.sin(a))],
                          stroke="#C05621", sw=1.0, marker="none", layer="nodes", tag="glyph"))
    return p


def _g_column(x, y, w, h):
    cx = x + w / 2
    return [scene.R(cx - w * 0.2, y + 2, w * 0.4, h - 8, fill="#ffffff", stroke=ACC, sw=1.2,
                    rx=1, layer="nodes", tag="glyph"),
            scene.LN([(cx - w * 0.3, y + 2), (cx + w * 0.3, y + 2), (cx + w * 0.3, y + h - 6),
                      (cx - w * 0.3, y + h - 6)], stroke=ACC, sw=1.2, marker="none",
                     layer="nodes", tag="glyph")]


def _g_heat(x, y, w, h):
    cy, n = y + h * 0.62, 4
    pts, step = [(x, cy)], w / (n * 2)
    for i in range(n * 2):
        pts.append((x + step * (i + 0.5), cy + (h * 0.22 if i % 2 == 0 else -h * 0.22)))
        pts.append((x + step * (i + 1), cy))
    p = [scene.LN(pts, stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph")]
    p.append(scene.LN([(x + w * 0.5, y + 1), (x + w * 0.5 - w * 0.14, y + h * 0.3),
                       (x + w * 0.5, y + h * 0.22), (x + w * 0.5 + w * 0.14, y + h * 0.3),
                       (x + w * 0.5, y + 1)], stroke="#C05621", sw=1.1, marker="none",
                      layer="nodes", tag="glyph"))
    return p


def _g_filter(x, y, w, h):
    cx, top, bot = x + w / 2, y + 2, y + h - 1
    fw = w * 0.72
    return [scene.LN([(cx - fw / 2, top), (cx + fw / 2, top), (cx + w * 0.06, top + h * 0.55),
                      (cx - w * 0.06, top + h * 0.55), (cx - fw / 2, top)],
                     stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph"),
            scene.LN([(cx, top + h * 0.55), (cx, bot)], stroke=ACC, sw=1.3,
                     marker="none", layer="nodes", tag="glyph")]


def _g_sep(x, y, w, h):
    cx, r = x + w / 2, min(w, h) * 0.32
    return [scene.EL(cx, y + h * 0.62, r, r, fill="#ffffff", stroke=ACC, sw=1.2,
                     layer="nodes", tag="glyph"),
            scene.LN([(cx, y + h * 0.62 - r), (cx, y + 2)], stroke=ACC, sw=1.2,
                     marker="none", layer="nodes", tag="glyph"),
            scene.LN([(cx - r, y + h * 0.62), (cx + r, y + h * 0.62)], stroke=ACC, sw=1.0,
                     marker="none", layer="nodes", tag="glyph")]


def _g_cell(x, y, w, h):
    """生物学：细胞/培养皿（外膜+细胞核）。"""
    cx, cy = x + w / 2, y + h / 2
    return [scene.EL(cx, cy, w * 0.42, h * 0.38, fill="#ffffff", stroke="#2F855A", sw=1.3,
                     layer="nodes", tag="glyph"),
            scene.EL(cx - w * 0.06, cy, w * 0.16, h * 0.15, fill="#E6FFED", stroke="#2F855A", sw=1.1,
                     layer="nodes", tag="glyph")]


def _g_pipette(x, y, w, h):
    """生物学/化学：移液器/微量注射。"""
    return [scene.LN([(x + w * 0.75, y + 2), (x + w * 0.32, y + h * 0.68), (x + w * 0.22, y + h - 2),
                      (x + w * 0.42, y + h * 0.75), (x + w * 0.85, y + 6), (x + w * 0.75, y + 2)],
                     stroke=ACC, sw=1.2, marker="none", layer="nodes", tag="glyph"),
            scene.LN([(x + w * 0.65, y + 4), (x + w * 0.82, y + 10)], stroke=ACC, sw=1.1,
                     marker="none", layer="nodes", tag="glyph")]


def _g_centrifuge(x, y, w, h):
    """生物学：离心机/离心管。"""
    cx, cy, r = x + w / 2, y + h / 2, min(w, h) * 0.4
    return [scene.EL(cx, cy, r, r, fill="#ffffff", stroke=ACC, sw=1.2, layer="nodes", tag="glyph"),
            scene.LN([(cx, cy), (cx + r * 0.72, cy - r * 0.35)], stroke=ACC, sw=1.3,
                     marker="none", layer="nodes", tag="glyph"),
            scene.LN([(cx, cy), (cx - r * 0.72, cy + r * 0.35)], stroke=ACC, sw=1.3,
                     marker="none", layer="nodes", tag="glyph"),
            scene.EL(cx, cy, 2.2, 2.2, fill=ACC, stroke=ACC, sw=0.5, layer="nodes", tag="glyph")]


def _g_microscope(x, y, w, h):
    """生物学/表征：显微镜/荧光成像。"""
    return [scene.LN([(x + w * 0.58, y + 2), (x + w * 0.36, y + h * 0.56)], stroke=ACC, sw=2.0,
                     marker="none", layer="nodes", tag="glyph"),
            scene.LN([(x + w * 0.22, y + h * 0.68), (x + w * 0.68, y + h * 0.68)], stroke=ACC, sw=1.4,
                     marker="none", layer="nodes", tag="glyph"),
            scene.LN([(x + w * 0.56, y + h * 0.28), (x + w * 0.76, y + h * 0.48),
                      (x + w * 0.76, y + h - 3), (x + w * 0.18, y + h - 3)], stroke=ACC, sw=1.3,
                     marker="none", layer="nodes", tag="glyph")]


def _g_seq(x, y, w, h):
    """生物学：测序/PCR/凝胶条带。"""
    p = [scene.R(x + 3, y + 2, w - 6, h - 4, fill="#ffffff", stroke="#6B46C1", sw=1.2, rx=2,
                 layer="nodes", tag="glyph")]
    for yy, frac in ((0.32, 0.55), (0.52, 0.75), (0.72, 0.42)):
        p.append(scene.LN([(x + 7, y + h * yy), (x + 7 + (w - 14) * frac, y + h * yy)],
                          stroke="#6B46C1", sw=1.6, marker="none", layer="nodes", tag="glyph"))
    return p


def _g_antibody(x, y, w, h):
    """生物学：抗体/蛋白/受体 Y 型结合造型。"""
    cx, my = x + w / 2, y + h * 0.52
    c = "#6B46C1"
    return [
        scene.LN([(cx, y + h - 2), (cx, my), (x + w * 0.22, y + 3)], stroke=c, sw=1.6, marker="none", layer="nodes", tag="glyph"),
        scene.LN([(cx, my), (x + w * 0.78, y + 3)], stroke=c, sw=1.6, marker="none", layer="nodes", tag="glyph"),
        scene.EL(x + w * 0.22, y + 3, 2.2, 2.2, fill=c, stroke=c, sw=0.5, layer="nodes", tag="glyph"),
        scene.EL(x + w * 0.78, y + 3, 2.2, 2.2, fill=c, stroke=c, sw=0.5, layer="nodes", tag="glyph"),
    ]


def _g_dna(x, y, w, h):
    """生物学：DNA/基因/CRISPR 双螺旋造型。"""
    c1, c2 = "#2B6CB0", "#2C7A7B"
    p1, p2, rungs = [], [], []
    for i in range(7):
        t = i / 6.0
        px = x + 4 + t * (w - 8)
        dy = math.sin(t * math.pi * 2.0) * (h * 0.30)
        y1, y2 = y + h / 2.0 - dy, y + h / 2.0 + dy
        p1.append((px, y1))
        p2.append((px, y2))
        if i in (1, 3, 5):
            rungs.append(scene.LN([(px, y1), (px, y2)], stroke="#718096", sw=0.9, marker="none", layer="nodes", tag="glyph"))
    return rungs + [
        scene.LN(p1, stroke=c1, sw=1.4, marker="none", layer="nodes", tag="glyph"),
        scene.LN(p2, stroke=c2, sw=1.4, marker="none", layer="nodes", tag="glyph"),
    ]


def _g_wellplate(x, y, w, h):
    """生物学/高通量筛选：96/384 微孔板 3x3 阵列。"""
    p = [scene.R(x + 2, y + 3, w - 4, h - 6, fill="#ffffff", stroke=ACC, sw=1.2, rx=2, layer="nodes", tag="glyph")]
    for ri in range(2):
        for ci in range(3):
            wx = x + 7.5 + ci * ((w - 15.0) / 2.0)
            wy = y + 8.5 + ri * ((h - 17.0))
            p.append(scene.EL(wx, wy, 2.2, 2.2, fill="#E8F1FB", stroke=ACC, sw=0.9, layer="nodes", tag="glyph"))
    return p


def _g_organism(x, y, w, h):
    """生物学/体内实验：模式生物/动物/队列标志。"""
    c = "#2F855A"
    return [
        scene.EL(x + w * 0.44, y + h * 0.56, w * 0.28, h * 0.24, fill="#E6FFED", stroke=c, sw=1.2, layer="nodes", tag="glyph"),
        scene.EL(x + w * 0.72, y + h * 0.44, w * 0.14, h * 0.16, fill="#ffffff", stroke=c, sw=1.2, layer="nodes", tag="glyph"),
        scene.LN([(x + w * 0.16, y + h * 0.58), (x + w * 0.06, y + h * 0.40)], stroke=c, sw=1.1, marker="none", layer="nodes", tag="glyph"),
    ]


def _g_virus(x, y, w, h):
    """生物学/药物递送：病毒载体/AAV/LNP/纳米颗粒囊泡。"""
    cx, cy, r = x + w / 2.0, y + h / 2.0, min(w, h) * 0.30
    c = "#C05621"
    p = [scene.EL(cx, cy, r, r, fill="#FFF4E0", stroke=c, sw=1.3, layer="nodes", tag="glyph")]
    for k in range(6):
        ang = k * math.pi / 3.0
        sx, sy = cx + math.cos(ang) * r, cy + math.sin(ang) * r
        ex, ey = cx + math.cos(ang) * (r + 4.0), cy + math.sin(ang) * (r + 4.0)
        p.append(scene.LN([(sx, sy), (ex, ey)], stroke=c, sw=1.1, marker="none", layer="nodes", tag="glyph"))
        p.append(scene.EL(ex, ey, 1.4, 1.4, fill=c, stroke=c, sw=0.4, layer="nodes", tag="glyph"))
    return p


def _g_spectrum(x, y, w, h):
    """分析化学/表征：质谱/光谱/色谱峰图（LC-MS/NMR/Raman）。"""
    c = "#2C7A7B"
    by = y + h - 4.0
    pts = [
        (x + 2, by), (x + w * 0.22, by), (x + w * 0.30, y + h * 0.38), (x + w * 0.38, by),
        (x + w * 0.52, by), (x + w * 0.60, y + 4.0), (x + w * 0.68, by),
        (x + w * 0.78, by), (x + w * 0.84, y + h * 0.52), (x + w * 0.90, by), (x + w - 2, by),
    ]
    return [
        scene.LN([(x + 2, by), (x + w - 2, by)], stroke="#718096", sw=1.0, marker="none", layer="nodes", tag="glyph"),
        scene.LN(pts, stroke=c, sw=1.4, marker="none", layer="nodes", tag="glyph"),
    ]


# 显式 icon 键 + 中英文关键词匹配表（按优先级排列）
GLYPH_RULES = [
    (("显微", "荧光", "成像", "microscop", "confocal", "fluorescen", "imaging"), _g_microscope),
    (("病毒", "脂质体", "纳米粒", "囊泡", "virus", "viral", "aav", "lenti", "lnp", "liposome", "nanoparticle", "exosome"), _g_virus),
    (("质谱", "光谱", "核磁", "拉曼", "lc-ms", "ms/ms", "mass spec", "nmr", "raman", "ftir", "xrd", "spectrum", "spectroscop"), _g_spectrum),
    (("抗体", "蛋白", "受体", "配体", "antibod", "protein", "receptor", "ligand", "immuno", "igg", "kinase", "enzyme"), _g_antibody),
    (("基因", "质粒", "crispr", "dna", "plasmid", "gene", "genome", "vector", "knockout", "editing"), _g_dna),
    (("孔板", "微孔", "高通量", "96-well", "384-well", "well plate", "microplate", "array", "screen"), _g_wellplate),
    (("小鼠", "大鼠", "动物", "体内", "队列", "患者", "mouse", "mice", "rat", "animal", "in vivo", "cohort", "patient", "xenograft"), _g_organism),
    (("测序", "pcr", "rna", "sequenc", "gel", "blot", "elisa", "facs", "cytom", "qpcr", "电泳"), _g_seq),
    (("离心", "centrifug", "spin", "pellet"), _g_centrifuge),
    (("细胞", "培养", "组织", "样本", "菌", "类器官", "cell", "culture", "plate", "dish", "tissue", "sample", "organoid", "bio"), _g_cell),
    (("移液", "加样", "pipet", "dispens"), _g_pipette),
    (("泵", "pump", "syringe"), _g_pump),
    (("阀", "valve", "bpr", "regulator"), _g_valve),
    (("混合", "mixer", "mix", "vortex"), _g_mix),
    (("盘管", "coil"), _g_coil),
    (("光", "laser", "led", "lamp", "photo"), _g_light),
    (("反应", "reactor", "flask", "vessel"), _g_reactor),
    (("瓶", "管", "bottle", "vial", "tube", "collect"), _g_bottle),
    (("检测", "监测", "表征", "uv", "sensor", "detect", "monitor", "spectrom", "assay", "readout", "analyzer"), _g_eye),
    (("控制", "control", "plc", "computer", "software", "algorithm"), _g_ctrl),
    (("塔", "柱", "罐", "column", "hplc", "chromatog", "tank", "chamber"), _g_column),
    (("滤", "过滤", "filter", "membrane", "sieve"), _g_filter),
    (("分离", "萃", "extract", "separat", "purif"), _g_sep),
    (("热", "换", "冷", "温", "孵育", "heat", "cool", "bath", "oven", "incubat", "thermo", "quench"), _g_heat),
]

GLYPHS = {k: fn for keys, fn in GLYPH_RULES for k in keys}


def match(node):
    """返回 (关键词, 绘制函数) 或 None。优先显式 node['icon']，否则扫 label+attrs 键（不区分大小写）。"""
    kw = str(node.get("icon") or "").strip().lower()
    if kw == "none":
        return None
    if kw:
        for keys, fn in GLYPH_RULES:
            if kw in keys or any(k in kw for k in keys):
                return kw, fn
    text = (str(node.get("label") or "") + " " + " ".join(str(k) for k in (node.get("attrs") or {}).keys())).lower()
    for keys, fn in GLYPH_RULES:
        for k in keys:
            if k in text:
                return k, fn
    return None


def draw(node, gx, gy, gw=34, gh=26):
    m = match(node)
    if not m:
        return None
    return m[0], m[1](gx, gy, gw, gh)
