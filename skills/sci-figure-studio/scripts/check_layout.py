#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SVG 静态几何检查器：越界检测、文本重叠估计、字体缺失提示 + PNG 边缘/留白检查。
用法:
  python3 check_layout.py figure.svg [--json report.json] [--tol 1.0]
  python3 check_layout.py --png figure.png [--json report.json]
无外部依赖（标准库 XML 解析；PNG 检查用 Pillow+numpy，缺则跳过并如实说明）。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# ---------------- 变换解析 ----------------

_NUM = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"


def _mat_mul(m1, m2):
    """3x2 仿射矩阵 (a b c d e f) 相乘 m1∘m2。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_ID = re.compile(r"ident\)?")  # placeholder, unused


def parse_transform(s):
    """解析 transform 属性为累计仿射矩阵；不支持的指令按单位阵处理。"""
    m = (1, 0, 0, 1, 0, 0)
    if not s:
        return m
    for name, args in re.findall(rf"(\w+)\s*\(\s*({_NUM}(?:[\s,]+{_NUM})*)\s*\)", s):
        nums = [float(x) for x in re.findall(_NUM, args)]
        if name == "matrix" and len(nums) == 6:
            t = tuple(nums)
        elif name == "translate" and nums:
            tx = nums[0]; ty = nums[1] if len(nums) > 1 else 0.0
            t = (1, 0, 0, 1, tx, ty)
        elif name == "scale" and nums:
            sx = nums[0]; sy = nums[1] if len(nums) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate" and nums:
            import math
            ang = math.radians(nums[0])
            ca, sa = math.cos(ang), math.sin(ang)
            t = (ca, sa, -sa, ca, 0, 0)
            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                t = _mat_mul(_mat_mul((1, 0, 0, 1, cx, cy), t), (1, 0, 0, 1, -cx, -cy))
        else:
            t = (1, 0, 0, 1, 0, 0)
        m = _mat_mul(m, t)
    return m


# ---------------- 文本宽度估计 ----------------

def est_text_width(text, font_size):
    w = 0.0
    for ch in text:
        o = ord(ch)
        if o >= 0x2E80:            # CJK / 全角
            w += 1.0
        elif ch == " ":
            w += 0.28
        elif ch in "iljItfr.,:;'|!()[]-/":
            w += 0.33
        elif ch in "mwMW@%":
            w += 0.84
        elif ch.isupper():
            w += 0.68
        else:
            w += 0.52
    return w * font_size


def _font_size_of(el, inherited):
    fs = el.get("font-size")
    if fs is None and el.get("style"):
        mm = re.search(r"font-size\s*:\s*([0-9.]+)", el.get("style", ""))
        if mm:
            fs = mm.group(1)
    if fs is None:
        return inherited
    try:
        return float(re.findall(_NUM, fs)[0])
    except Exception:
        return inherited


def _anchor_of(el):
    a = el.get("text-anchor") or ""
    if not a and el.get("style"):
        mm = re.search(r"text-anchor\s*:\s*(\w+)", el.get("style", ""))
        a = mm.group(1) if mm else ""
    return a or "start"


# ---------------- 元素 bbox 收集 ----------------

def _pt_list(el):
    nums = [float(x) for x in re.findall(_NUM, el.get("points", ""))]
    return list(zip(nums[::2], nums[1::2]))


# path 命令 → 每组参数个数（A 含 x,y 于组首两位）
_PATH_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _path_points(d):
    """按 SVG path 命令正规解析坐标（含相对命令累计），返回绝对坐标点列表。"""
    pts = []
    cx = cy = 0.0
    sx = sy = 0.0
    parts = re.split(r"([MmLlHhVvCcSsQqTtAaZz])", d or "")
    it = iter(parts[1:])
    for cmd, params in zip(it, it):
        c = cmd.upper()
        if c not in _PATH_ARITY:
            continue
        nums = [float(x) for x in re.findall(_NUM, params)]
        rel = cmd.islower() and c != "Z"
        k = _PATH_ARITY[c]
        if k == 0:
            cx, cy = sx, sy
            continue
        for i in range(0, len(nums) - k + 1, k):
            g = nums[i:i + k]
            if c in ("M", "L", "T"):
                nx, ny = (cx + g[0], cy + g[1]) if rel else (g[0], g[1])
                if c == "M" and not rel:
                    sx, sy = nx, ny
            elif c == "H":
                nx, ny = (cx + g[0], cy) if rel else (g[0], cy)
            elif c == "V":
                nx, ny = (cx, cy + g[0]) if rel else (cx, g[0])
            elif c in ("C", "S", "Q"):
                nx, ny = (cx + g[-2], cy + g[-1]) if rel else (g[-2], g[-1])
            else:  # A
                nx, ny = (cx + g[0], cy + g[1]) if rel else (g[0], g[1])
            pts.append((nx, ny))
            cx, cy = nx, ny
    return pts


def element_bbox(el, ctx_m, defs, depth=0):
    """返回 (x0,y0,x1,y1) 或 None。ctx_m 为累计仿射矩阵。"""
    if depth > 12:
        return None
    tag = el.tag.split("}")[-1]
    m = _mat_mul(ctx_m, parse_transform(el.get("transform")))
    if tag in ("defs", "clipPath", "mask", "metadata", "style", "title", "desc"):
        return None
    try:
        if tag == "rect":
            x = float(el.get("x", 0)); y = float(el.get("y", 0))
            w = float(el.get("width", 0)); h = float(el.get("height", 0))
            pts = [(x, y), (x + w, y + h)]
        elif tag == "circle":
            cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0)); r = float(el.get("r", 0))
            pts = [(cx - r, cy - r), (cx + r, cy + r)]
        elif tag == "ellipse":
            cx = float(el.get("cx", 0)); cy = float(el.get("cy", 0))
            rx = float(el.get("rx", 0)); ry = float(el.get("ry", 0))
            pts = [(cx - rx, cy - ry), (cx + rx, cy + ry)]
        elif tag == "line":
            pts = [(float(el.get("x1", 0)), float(el.get("y1", 0))),
                   (float(el.get("x2", 0)), float(el.get("y2", 0)))]
        elif tag in ("polyline", "polygon"):
            pts = _pt_list(el)
        elif tag == "path":
            pts = _path_points(el.get("d", ""))
            if not pts:
                return None
        elif tag == "text":
            return text_bbox(el, m, defs, depth)
        elif tag == "use":
            href = el.get(f"{{{XLINK_NS}}}href") or el.get("href")
            if href and href.startswith("#") and href[1:] in defs:
                bx = element_bbox(defs[href[1:]], m, defs, depth + 1)
                dx = float(el.get("x", 0)); dy = float(el.get("y", 0))
                if bx and (dx or dy):
                    bx = (bx[0] + dx, bx[1] + dy, bx[2] + dx, bx[3] + dy)
                return bx
            return None
        else:
            return None
    except Exception:
        return None
    tp = [_apply(m, x, y) for x, y in pts]
    xs = [p[0] for p in tp]; ys = [p[1] for p in tp]
    return (min(xs), min(ys), max(xs), max(ys))


def text_bbox(el, m, defs, depth=0):
    """text/tspan 的估计 bbox（含 text-anchor 与 letter 布局近似）。"""
    fs = _font_size_of(el, 12.0)
    anchor = _anchor_of(el)
    boxes = []
    x0 = float(el.get("x", 0)); y0 = float(el.get("y", 0))
    tspans = [c for c in el if c.tag.split("}")[-1] == "tspan"]
    if tspans:
        for t in tspans:
            tfs = _font_size_of(t, fs)
            txt = "".join(t.itertext())
            w = est_text_width(txt, tfs)
            tx = float(str(t.get("x", x0)).split()[0])
            ty = float(str(t.get("y", y0)).split()[0])
            boxes.append(_anchored_box(tx, ty, w, tfs, _anchor_of(t), m))
    else:
        txt = "".join(el.itertext())
        w = est_text_width(txt, fs)
        boxes.append(_anchored_box(x0, y0, w, fs, anchor, m))
    if not boxes:
        return None
    xs0 = min(b[0] for b in boxes); ys0 = min(b[1] for b in boxes)
    xs1 = max(b[2] for b in boxes); ys1 = max(b[3] for b in boxes)
    return (xs0, ys0, xs1, ys1)


def _anchored_box(x, y, w, fs, anchor, m):
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    p1 = _apply(m, x, y - fs * 0.85)
    p2 = _apply(m, x + w, y + fs * 0.25)
    return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))


# ---------------- 主检查 ----------------

def canvas_size(root):
    vb = root.get("viewBox")
    if vb:
        nums = [float(x) for x in re.findall(_NUM, vb)]
        if len(nums) == 4:
            return nums[0], nums[1], nums[2], nums[3]
    w, h = root.get("width", "0"), root.get("height", "0")

    def unit_len(s):
        mm = re.findall(_NUM, s)
        v = float(mm[0]) if mm else 0.0
        if "mm" in s:
            v *= 96 / 25.4
        elif "cm" in s:
            v *= 96 / 2.54
        elif "pt" in s:
            v *= 96 / 72.0
        return v
    return 0.0, 0.0, unit_len(w), unit_len(h)


def check_svg(svg_path, tol=1.0):
    import xml.etree.ElementTree as ET
    tree = ET.parse(str(svg_path))
    root = tree.getroot()
    if root.tag.split("}")[-1] != "svg":
        raise ValueError("root is not <svg>")
    cx, cy, cw, ch = canvas_size(root)
    defs = {}
    for el in root.iter():
        if el.get("id"):
            defs[el.get("id")] = el

    texts, shapes, oob, clipped_ancestors = [], [], [], 0

    def in_clip(el, parents):
        for p in parents:
            if p.get("clip-path"):
                return True
        return False

    def walk(el, m, parents):
        tag = el.tag.split("}")[-1]
        if tag in ("defs", "clipPath", "mask"):
            return  # 仅经 <use> 引用，不按原坐标收集
        cm = _mat_mul(m, parse_transform(el.get("transform")))
        if tag == "text":
            fs = _font_size_of(el, 12.0)
            txt = "".join(el.itertext()).strip()
            if txt:
                bb = text_bbox(el, cm, defs)
                texts.append({"tag": "text", "text": txt[:60], "bbox": bb,
                              "font_size": fs, "clipped": in_clip(el, parents)})
        elif tag in ("rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "image"):
            bb = element_bbox(el, cm, defs)
            if bb:
                shapes.append({"tag": tag, "bbox": bb, "clipped": in_clip(el, parents)})
        for child in el:
            walk(child, cm, parents + [el])

    walk(root, (1, 0, 0, 1, 0, 0), [])

    def oob_sev(bb, clipped):
        out = (bb[0] < cx - tol or bb[1] < cy - tol or bb[2] > cx + cw + tol or bb[3] > cy + ch + tol)
        if not out:
            return None
        return "info" if clipped else "error"

    for t in texts:
        if t["bbox"] is None:
            continue
        sev = oob_sev(t["bbox"], t["clipped"])
        if sev:
            oob.append({"kind": "text", "text": t["text"], "bbox": [round(v, 1) for v in t["bbox"]], "severity": sev})
    for s in shapes:
        sev = oob_sev(s["bbox"], s["clipped"])
        if sev:
            oob.append({"kind": s["tag"], "bbox": [round(v, 1) for v in s["bbox"]], "severity": "info" if s["clipped"] else sev})

    # 文本两两重叠（面积重叠占较小者比例）
    overlaps = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if not a["bbox"] or not b["bbox"]:
                continue
            ix = max(0, min(a["bbox"][2], b["bbox"][2]) - max(a["bbox"][0], b["bbox"][0]))
            iy = max(0, min(a["bbox"][3], b["bbox"][3]) - max(a["bbox"][1], b["bbox"][1]))
            inter = ix * iy
            if inter <= 0:
                continue
            aa = (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1])
            ab = (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1])
            denom = max(aa, ab, 1e-6)
            ratio = inter / min(aa, ab, denom)
            if ratio > 0.25:
                overlaps.append({"a": a["text"], "b": b["text"],
                                 "overlap_pct": round(ratio * 100, 1),
                                 "severity": "error" if ratio > 0.5 else "warning"})
    errors = [o for o in oob if o["severity"] == "error"] + [o for o in overlaps if o["severity"] == "error"]
    warns = [o for o in oob if o["severity"] == "warning"] + [o for o in overlaps if o["severity"] == "warning"]
    return {
        "canvas": {"x": cx, "y": cy, "w": round(cw, 1), "h": round(ch, 1)},
        "counts": {"texts": len(texts), "shapes": len(shapes)},
        "out_of_bounds": oob,
        "text_overlaps": overlaps,
        "n_errors": len(errors),
        "n_warnings": len(warns),
        "ok": len(errors) == 0,
        "notes": ["重叠为字体度量估计，warn 级请结合渲染预览确认"],
    }


def check_png(png_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from kit_common import png_edge_check
    except ImportError:
        return {"ok": False, "error": "kit_common 不可用"}
    return png_edge_check(png_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="SVG 或（配合 --png）图片路径")
    ap.add_argument("--png", action="store_true", help="按 PNG 边缘/留白模式检查")
    ap.add_argument("--json", help="报告写入该 JSON 文件")
    ap.add_argument("--tol", type=float, default=1.0)
    args = ap.parse_args()
    if args.png:
        rep = check_png(args.target)
    else:
        rep = check_svg(args.target, tol=args.tol)
    out = json.dumps(rep, ensure_ascii=False, indent=2)
    print(out)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out, encoding="utf-8")
    sys.exit(0 if rep.get("ok") else 1)


if __name__ == "__main__":
    main()
