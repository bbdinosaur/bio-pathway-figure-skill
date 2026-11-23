#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg_ops.py — SVG 源保留编辑与机制图绘制原语：
- 编辑既有 SVG：仅改动目标元素，其余字节结构不动，产出变更日志。
- 新增元素：支持 add_compartment(区室框)、add_box(自动居中换行+多形状)、
  add_arrow(激活/抑制T-bar/双向/虚线/from_id->to_id 自动贴边连线/带底衬标签)、add_text。"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)

DEFAULT_FONT = "Noto Sans CJK SC, WenQuanYi Zen Hei, DejaVu Sans, Arial, sans-serif"


def _q(tag):
    return f"{{{SVG}}}{tag}"


def _full_text(el):
    return "".join(el.itertext())


def _est_text_w(text, font_pt):
    w = 0.0
    for ch in text:
        o = ord(ch)
        if o >= 0x2E80:
            w += 1.02
        elif ch in "iljItf.,:;'|!()[]- ":
            w += 0.36
        elif ch in "mwMW@%":
            w += 0.88
        elif ch.isupper():
            w += 0.72
        else:
            w += 0.56
    return w * float(font_pt)


def _wrap_text(text, max_w, font_pt):
    """按像素宽度和显式换行符将文本拆成多行。"""
    lines = []
    for para in str(text).split("\n"):
        if not para:
            continue
        if _est_text_w(para, font_pt) <= max_w:
            lines.append(para)
            continue
        # 优先按空格分，中文或超长词按字符切
        tokens = re.findall(r"\S+\s*", para) if " " in para else list(para)
        cur = ""
        for tk in tokens:
            cand = (cur + tk).rstrip() if cur else tk.rstrip()
            if cur and _est_text_w(cand, font_pt) > max_w:
                lines.append(cur.rstrip())
                cur = tk.lstrip()
            else:
                cur += tk
        if cur.strip():
            lines.append(cur.strip())
    return lines or [str(text)]


def _set_text(el, new):
    old = _full_text(el)
    tspans = [c for c in el if c.tag.split("}")[-1] == "tspan"]
    if tspans:
        t0 = tspans[0]
        if len(new) != len(old) and t0.get("x") and len(t0.get("x").split()) > 1:
            t0.set("x", t0.get("x").split()[0])
        t0.text = new
        for t in tspans[1:]:
            el.remove(t)
    else:
        if len(new) != len(old) and el.get("x") and len(el.get("x").split()) > 1:
            el.set("x", el.get("x").split()[0])
        el.text = new


def _parent_map(root):
    return {c: p for p in root.iter() for c in p}


def find_target(root, spec):
    """按 id 或文本内容定位元素列表（避免父 <text> 与子 <tspan> 重复命中）。"""
    if spec.get("id"):
        return [el for el in root.iter() if el.get("id") == spec["id"]]
    find = spec.get("find")
    if find is None:
        return []
    m = spec.get("match", "contains")

    def _match(txt):
        if m == "exact":
            return txt == find
        if m == "regex":
            return bool(re.search(find, txt))
        return find in txt

    pmap = _parent_map(root)
    hits, hit_set = [], set()
    # 先查 <text>，父节点已匹配时不再重复收其子 <tspan>
    for el in root.iter():
        if el.tag.split("}")[-1] == "text":
            if _match(_full_text(el)):
                hits.append(el)
                hit_set.add(el)
    for el in root.iter():
        if el.tag.split("}")[-1] == "tspan":
            par = pmap.get(el)
            if par in hit_set:
                continue
            if _match(_full_text(el)):
                hits.append(el)
                hit_set.add(el)
    return hits


def _parse_color(s):
    """解析 #rgb/#rrggbb/rgb(r,g,b)/rgb(r%,g%,b%) 为 0-255 三元组，失败返回 None。"""
    if not s:
        return None
    s = s.strip().lower()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) >= 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        return None
    m = re.match(r"rgba?\(([^)]+)\)", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            if all(p.endswith("%") for p in parts[:3]):
                return tuple(round(float(p[:-1]) * 2.55) for p in parts[:3])
            return tuple(round(float(p)) for p in parts[:3])
        except ValueError:
            return None
    return None


def _color_close(a, b, tol=3):
    pa, pb = _parse_color(a), _parse_color(b)
    return pa is not None and pb is not None and all(abs(x - y) <= tol for x, y in zip(pa, pb))


def _style_get(el, prop):
    st = el.get("style") or ""
    m = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", st)
    return m.group(1).strip() if m else None


def _collect_boxes(root):
    """扫描已有带 id 的 rect/ellipse，供 from_id/to_id 自动贴边连线。"""
    boxes = {}
    for el in root.iter():
        eid = el.get("id")
        if not eid:
            continue
        tag = el.tag.split("}")[-1]
        try:
            if tag == "rect":
                x, y = float(el.get("x", 0)), float(el.get("y", 0))
                w, h = float(el.get("width", 0)), float(el.get("height", 0))
                boxes[eid] = (x, y, w, h)
            elif tag == "ellipse":
                cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
                rx, ry = float(el.get("rx", 0)), float(el.get("ry", 0))
                boxes[eid] = (cx - rx, cy - ry, 2 * rx, 2 * ry)
        except ValueError:
            pass
    return boxes


def _anchor_pair(b1, b2, dst_bias=0.0):
    """根据两个框 (x,y,w,h) 的相对位置计算最干净的边缘起止点 (x1,y1,x2,y2)。
    dst_bias ∈ [-0.35, 0.35] 用于多条边汇入同一目标框时错开接点，避免箭头重叠。"""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    cx1, cy1 = x1 + w1 / 2.0, y1 + h1 / 2.0
    cx2, cy2 = x2 + w2 / 2.0, y2 + h2 / 2.0
    dx, dy = cx2 - cx1, cy2 - cy1
    same_row = abs(dy) < min(h1, h2) * 0.5
    if same_row and abs(dx) > 1e-3:
        ty = cy2 + dst_bias * h2
        if dx > 0:
            return x1 + w1, cy1, x2, ty
        return x1, cy1, x2 + w2, ty
    # 跨泳道优先用顶边/底边接入，并按相对水平方向微调接入点，避免斜穿节点边缘或撞上水平边起点
    tx = cx2 + dst_bias * w2
    if dy >= 0:
        return cx1, y1 + h1, tx, y2
    return cx1, y1, tx, y2 + h2


def apply_ops(svg_path, ops):
    """返回 (output_svg_path, change_log)。output 与输入同路径（原地更新，调用方先复制）。"""
    tree = ET.parse(str(svg_path))
    root = tree.getroot()
    boxes = _collect_boxes(root)
    log = []
    for op in ops:
        kind = op.get("op")
        entry = {"op": kind, "status": "not_found", "detail": ""}
        try:
            if kind == "replace_text":
                hits = find_target(root, op)
                find = op.get("find", "")
                new = op["replace"]
                mode = op.get("match", "contains")
                applied_pairs = []

                def _do_sub(s):
                    if mode == "exact":
                        return new
                    if mode == "regex":
                        return re.sub(find, new, s)
                    return s.replace(find, new)

                def _span_hit(s):
                    if mode == "exact":
                        return s == find
                    if mode == "regex":
                        return bool(re.search(find, s))
                    return find in s

                for el in hits:
                    old = _full_text(el)
                    tspans = [c for c in el if c.tag.split("}")[-1] == "tspan"]
                    matched_ts = [t for t in tspans if _span_hit("".join(t.itertext()))] if len(tspans) > 1 else []
                    if matched_ts:
                        for t in matched_ts:
                            t_old = "".join(t.itertext())
                            t_new = _do_sub(t_old)
                            if len(t_new) != len(t_old) and t.get("x") and len(t.get("x").split()) > 1:
                                t.set("x", t.get("x").split()[0])
                            t.text = t_new
                        applied_pairs.append((old, _full_text(el)))
                    else:
                        replaced = _do_sub(old)
                        _set_text(el, replaced)
                        applied_pairs.append((old, replaced))
                if hits:
                    entry.update(status="applied", before=applied_pairs[0][0],
                                 after=applied_pairs[0][1], n=len(hits))
            elif kind == "set_text":
                hits = [el for el in root.iter() if el.get("id") == op.get("id")]
                for el in hits:
                    entry.setdefault("before", _full_text(el))
                    _set_text(el, op["text"])
                if hits:
                    entry.update(status="applied", after=op["text"])
            elif kind == "recolor":
                n = 0
                for el in root.iter():
                    if op.get("id") and el.get("id") != op["id"]:
                        continue
                    cur_fill = el.get("fill") or _style_get(el, "fill") or ""
                    cur_stroke = el.get("stroke") or _style_get(el, "stroke") or ""
                    if op.get("fill_from") and _color_close(cur_fill, op["fill_from"]):
                        to = op.get("to_fill", cur_fill)
                        if el.get("fill") is not None:
                            el.set("fill", to)
                        else:
                            el.set("style", re.sub(r"fill\s*:\s*[^;]+", f"fill:{to}", el.get("style", "")))
                        n += 1
                    elif op.get("id") and not op.get("fill_from") and op.get("to_fill"):
                        to = op["to_fill"]
                        if el.get("style") and re.search(r"fill\s*:", el.get("style", "")):
                            el.set("style", re.sub(r"fill\s*:\s*[^;]+", f"fill:{to}", el.get("style", "")))
                        else:
                            el.set("fill", to)
                        n += 1
                    if op.get("stroke_from") and _color_close(cur_stroke, op["stroke_from"]):
                        to = op.get("to_stroke", cur_stroke)
                        if el.get("stroke") is not None:
                            el.set("stroke", to)
                        else:
                            el.set("style", re.sub(r"stroke\s*:\s*[^;]+", f"stroke:{to}", el.get("style", "")))
                        n += 1
                    elif op.get("id") and not op.get("stroke_from") and op.get("to_stroke"):
                        to = op["to_stroke"]
                        if el.get("style") and re.search(r"stroke\s*:", el.get("style", "")):
                            el.set("style", re.sub(r"stroke\s*:\s*[^;]+", f"stroke:{to}", el.get("style", "")))
                        else:
                            el.set("stroke", to)
                        n += 1
                entry.update(status="applied" if n else "not_found", n=n,
                             detail=f"fill={op.get('fill_from')}->{op.get('to_fill')}")
            elif kind == "set_style":
                hits = find_target(root, op)
                style_map = {
                    "font_size": "font-size", "font_weight": "font-weight",
                    "font_style": "font-style", "fill": "fill",
                    "stroke": "stroke", "stroke_width": "stroke-width",
                    "opacity": "opacity",
                }

                def _apply_css(node, attr, val):
                    node.set(attr, val)
                    st = node.get("style")
                    if st is not None:
                        if re.search(rf"(?:^|;)\s*{attr}\s*:", st):
                            node.set("style", re.sub(rf"((?:^|;)\s*){attr}\s*:\s*[^;]+", rf"\1{attr}:{val}", st))
                        else:
                            sep = "" if (not st or st.rstrip().endswith(";")) else ";"
                            node.set("style", f"{st}{sep}{attr}:{val}")

                for el in hits:
                    targets_st = [el] + [c for c in el if c.tag.split("}")[-1] == "tspan"]
                    for k_in, attr in style_map.items():
                        if k_in in op and op[k_in] is not None:
                            val = str(op[k_in])
                            for nd_t in targets_st:
                                _apply_css(nd_t, attr, val)
                entry.update(status="applied" if hits else "not_found", n=len(hits))
            elif kind == "move":
                hits = find_target(root, op)
                for el in hits:
                    tr = el.get("transform", "")
                    el.set("transform", (tr + " " if tr else "") +
                           f"translate({op.get('dx', 0)},{op.get('dy', 0)})")
                entry.update(status="applied" if hits else "not_found", n=len(hits))
            elif kind == "delete":
                hits = find_target(root, op.get("target") or op)
                pmap = _parent_map(root)
                for el in hits:
                    entry.setdefault("before", _full_text(el) or el.get("id", ""))
                    if el in pmap:
                        pmap[el].remove(el)
                entry.update(status="applied" if hits else "not_found", n=len(hits))
            elif kind in ("add_text", "add_box", "add_compartment", "add_arrow", "add_line"):
                _add_new(root, op, boxes)
                entry.update(status="applied")
            else:
                entry.update(status="unknown_op")
        except Exception as e:
            entry.update(status="failed", detail=f"{type(e).__name__}: {e}")
        log.append(entry)
    tree.write(str(svg_path), encoding="unicode", xml_declaration=False)
    return str(svg_path), log


def _draw_head(root, x1, y1, x2, y2, stroke, width, style):
    """在 (x2, y2) 处画箭头或抑制 T-bar。"""
    ang = math.atan2(y2 - y1, x2 - x1)
    if style in ("inhibit", "tbar"):
        L = 5.5
        px, py = -math.sin(ang) * L, math.cos(ang) * L
        bar = ET.Element(_q("line"), {
            "x1": f"{x2 - px:.1f}", "y1": f"{y2 - py:.1f}",
            "x2": f"{x2 + px:.1f}", "y2": f"{y2 + py:.1f}",
            "stroke": stroke, "stroke-width": f"{max(2.0, float(width) * 1.35):.1f}",
            "stroke-linecap": "round",
        })
        root.append(bar)
    elif style in ("activate", "both", "arrow"):
        L, W = 7.5, 3.8
        pts = [
            (x2, y2),
            (x2 - L * math.cos(ang) + W * math.sin(ang), y2 - L * math.sin(ang) - W * math.cos(ang)),
            (x2 - L * math.cos(ang) - W * math.sin(ang), y2 - L * math.sin(ang) + W * math.cos(ang)),
        ]
        poly = ET.Element(_q("polygon"), {
            "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in pts),
            "fill": stroke,
        })
        root.append(poly)


def _insert_background(root, el):
    """把区室背景框插入到底层（canvas-border/defs 之后、所有前景节点之前）。"""
    idx = 0
    for i, c in enumerate(list(root)):
        tag = c.tag.split("}")[-1]
        if tag in ("defs", "title", "desc") or c.get("id") in ("canvas-bg", "canvas-border"):
            idx = i + 1
        elif c.get("data-layer") == "compartment":
            idx = i + 1
    root.insert(idx, el)


def _add_new(root, op, boxes):
    kind = op["op"]
    font_fam = op.get("font_family", DEFAULT_FONT)

    if kind == "add_text":
        el = ET.Element(_q("text"), {
            "x": str(op["x"]), "y": str(op["y"]),
            "font-size": str(op.get("font_pt", 12)),
            "font-family": font_fam,
            "fill": op.get("fill", "#000000"),
            "id": op.get("id", "added-text"),
        })
        if op.get("anchor"):
            el.set("text-anchor", op["anchor"])
        if op.get("bold"):
            el.set("font-weight", "bold")
        el.text = op.get("text", "")
        root.append(el)
        return el

    if kind == "add_compartment":
        x, y, w, h = float(op["x"]), float(op["y"]), float(op["w"]), float(op["h"])
        g = ET.Element(_q("g"), {"id": op.get("id", "compartment"), "data-layer": "compartment"})
        cstyle = op.get("style", "")
        rect = ET.Element(_q("rect"), {
            "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{w:.1f}", "height": f"{h:.1f}",
            "rx": str(op.get("rx", 10)),
            "fill": op.get("fill", "#F5F8FC"),
            "stroke": op.get("stroke", "#8FA6C0"),
            "stroke-width": str(op.get("stroke_w", 1.5 if cstyle == "membrane" else 1.2)),
        })
        if cstyle == "membrane":
            inner = ET.Element(_q("rect"), {
                "x": f"{x + 3.5:.1f}", "y": f"{y + 3.5:.1f}",
                "width": f"{max(4.0, w - 7.0):.1f}", "height": f"{max(4.0, h - 7.0):.1f}",
                "rx": str(max(2, float(op.get("rx", 10)) - 2)),
                "fill": "none", "stroke": op.get("stroke", "#8FA6C0"),
                "stroke-width": "0.9", "stroke-dasharray": "4,3",
            })
            g.append(rect)
            g.append(inner)
        else:
            if op.get("dashed", True):
                rect.set("stroke-dasharray", "6,4")
            g.append(rect)
        if op.get("title"):
            fpt = float(op.get("font_pt", 11))
            tpos = op.get("title_pos", "top_left")
            if tpos == "top_right":
                tx, ty, tanc = x + w - 10, y + fpt + 4, "end"
            elif tpos == "bottom_right":
                tx, ty, tanc = x + w - 10, y + h - 6, "end"
            elif tpos == "bottom_left":
                tx, ty, tanc = x + 10, y + h - 6, "start"
            else:
                tx, ty, tanc = x + 10, y + fpt + 5, "start"
            t = ET.Element(_q("text"), {
                "x": f"{tx:.1f}", "y": f"{ty:.1f}",
                "font-size": str(fpt), "font-family": font_fam,
                "font-weight": "bold", "text-anchor": tanc,
                "fill": op.get("title_fill", op.get("stroke", "#33506B")),
            })
            t.text = op["title"]
            g.append(t)
        _insert_background(root, g)
        return g

    if kind == "add_box":
        x, y, w, h = float(op["x"]), float(op["y"]), float(op["w"]), float(op["h"])
        eid = op.get("id", "added-box")
        boxes[eid] = (x, y, w, h)
        shape = op.get("shape", "rounded")
        fill = op.get("fill", "#EEF3FA")
        stroke = op.get("stroke", "#33506B")
        sw = str(op.get("stroke_w", 1.3))
        if shape == "ellipse":
            el = ET.Element(_q("ellipse"), {
                "cx": f"{x + w / 2:.1f}", "cy": f"{y + h / 2:.1f}",
                "rx": f"{w / 2:.1f}", "ry": f"{h / 2:.1f}",
                "fill": fill, "stroke": stroke, "stroke-width": sw, "id": eid,
            })
        elif shape == "diamond":
            pts = f"{x + w / 2:.1f},{y:.1f} {x + w:.1f},{y + h / 2:.1f} {x + w / 2:.1f},{y + h:.1f} {x:.1f},{y + h / 2:.1f}"
            el = ET.Element(_q("polygon"), {
                "points": pts, "fill": fill, "stroke": stroke, "stroke-width": sw, "id": eid,
            })
        else:
            rx = h / 2.0 if shape == "pill" else float(op.get("rx", 6 if shape == "rounded" else 0))
            el = ET.Element(_q("rect"), {
                "x": f"{x:.1f}", "y": f"{y:.1f}", "width": f"{w:.1f}", "height": f"{h:.1f}",
                "rx": f"{rx:.1f}", "fill": fill, "stroke": stroke, "stroke-width": sw, "id": eid,
            })
        root.append(el)

        # 居中 + 自动多行换行（支持 sublabel；粗体主标题按 1.07x 宽度估算留足内边距）
        label = op.get("label") or ""
        sub = op.get("sublabel") or ""
        if label or sub:
            fpt = float(op.get("font_pt", 11))
            sub_pt = max(8.5, fpt * 0.82)
            pad_x = 14.0 if shape in ("pill", "ellipse") else 12.0
            max_tw = max(24.0, w - 2 * pad_x)
            is_bold = bool(sub or op.get("bold"))
            main_lines = _wrap_text(label, max_tw, fpt * (1.07 if is_bold else 1.0)) if label else []
            sub_lines = _wrap_text(sub, max_tw, sub_pt) if sub else []
            lh_main = fpt * 1.24
            lh_sub = sub_pt * 1.2
            total_h = len(main_lines) * lh_main + len(sub_lines) * lh_sub
            start_y = y + (h - total_h) / 2.0 + fpt * 0.88
            cx = x + w / 2.0
            for idx, ln in enumerate(main_lines):
                t = ET.Element(_q("text"), {
                    "x": f"{cx:.1f}", "y": f"{start_y + idx * lh_main:.1f}",
                    "font-size": f"{fpt:.1f}", "font-family": font_fam,
                    "font-weight": "bold" if is_bold else "normal",
                    "text-anchor": "middle",
                    "fill": op.get("label_fill", "#1A2B3C"),
                    "id": f"{eid}-label" + (f"-{idx}" if idx else ""),
                })
                t.text = ln
                root.append(t)
            sub_y0 = start_y + len(main_lines) * lh_main + (sub_pt - fpt) * 0.4
            for idx, ln in enumerate(sub_lines):
                t = ET.Element(_q("text"), {
                    "x": f"{cx:.1f}", "y": f"{sub_y0 + idx * lh_sub:.1f}",
                    "font-size": f"{sub_pt:.1f}", "font-family": font_fam,
                    "text-anchor": "middle",
                    "fill": op.get("sublabel_fill", "#4A6074"),
                    "id": f"{eid}-sub-{idx}",
                })
                t.text = ln
                root.append(t)

        # 可选生化修饰徽章（如 "P" 磷酸化、"Ub" 泛素化、"Ac" 乙酰化），置于节点右上角且避开右侧连线
        if op.get("badge"):
            btxt = str(op["badge"]).strip()
            br = max(9.5, min(14.0, 5.5 + len(btxt) * 3.0))
            bx = x + w - 8.0
            by = y + 2.0
            circ = ET.Element(_q("circle"), {
                "cx": f"{bx:.1f}", "cy": f"{by:.1f}", "r": f"{br:.1f}",
                "fill": op.get("badge_fill", "#FEF3C7"),
                "stroke": op.get("badge_stroke", "#D97706"),
                "stroke-width": "1.2",
                "id": f"{eid}-badge",
            })
            bt = ET.Element(_q("text"), {
                "x": f"{bx:.1f}", "y": f"{by + 3.2:.1f}",
                "font-size": "8.8", "font-family": font_fam, "font-weight": "bold",
                "text-anchor": "middle", "fill": op.get("badge_text_fill", "#92400E"),
                "id": f"{eid}-badge-txt",
            })
            bt.text = btxt
            root.append(circ)
            root.append(bt)
        return el

    # add_arrow / add_line
    route = op.get("route", "straight")
    style = op.get("style") or ("line" if kind == "add_line" else "activate")
    stroke = op.get("stroke", "#C0392B" if style in ("inhibit", "tbar") else "#33506B")
    width = float(op.get("width", 1.5))

    if route == "detour" and op.get("waypoints") and len(op["waypoints"]) >= 2:
        pts = [(float(px), float(py)) for px, py in op["waypoints"]]
        # 构造圆角正交折线（半径 r<=10），视觉接近手工矢量通道图
        d_parts = [f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"]
        for i in range(1, len(pts) - 1):
            p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
            v1x, v1y = p1[0] - p0[0], p1[1] - p0[1]
            v2x, v2y = p2[0] - p1[0], p2[1] - p1[1]
            l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
            r = min(10.0, l1 * 0.4, l2 * 0.4)
            if r > 1.0:
                ax, ay = p1[0] - v1x / l1 * r, p1[1] - v1y / l1 * r
                bx, by = p1[0] + v2x / l2 * r, p1[1] + v2y / l2 * r
                d_parts.append(f"L {ax:.1f},{ay:.1f} Q {p1[0]:.1f},{p1[1]:.1f} {bx:.1f},{by:.1f}")
            else:
                d_parts.append(f"L {p1[0]:.1f},{p1[1]:.1f}")
        d_parts.append(f"L {pts[-1][0]:.1f},{pts[-1][1]:.1f}")
        el = ET.Element(_q("path"), {
            "d": " ".join(d_parts), "fill": "none", "stroke": stroke,
            "stroke-width": f"{width:.1f}", "id": op.get("id", "added-line"),
        })
        last_p1, last_p2 = pts[-2], pts[-1]
        first_p1, first_p2 = pts[1], pts[0]
        x1, y1 = pts[0]
        x2, y2 = pts[-1]
        lp = op.get("label_pos")
        if lp:
            lx, ly = float(lp[0]), float(lp[1])
        else:
            mid_i = len(pts) // 2
            lx = (pts[mid_i - 1][0] + pts[mid_i][0]) / 2.0
            ly = (pts[mid_i - 1][1] + pts[mid_i][1]) / 2.0
    else:
        if op.get("from_id") and op.get("to_id") and op["from_id"] in boxes and op["to_id"] in boxes:
            if route == "curve":
                b1, b2 = boxes[op["from_id"]], boxes[op["to_id"]]
                side = op.get("curve_side", "right")
                if side == "left":
                    x1, y1 = b1[0], b1[1] + b1[3] / 2.0
                    x2, y2 = b2[0], b2[1] + b2[3] / 2.0
                else:
                    x1, y1 = b1[0] + b1[2], b1[1] + b1[3] / 2.0
                    x2, y2 = b2[0] + b2[2], b2[1] + b2[3] / 2.0
            else:
                x1, y1, x2, y2 = _anchor_pair(boxes[op["from_id"]], boxes[op["to_id"]],
                                              dst_bias=float(op.get("dst_bias", 0.0)))
        else:
            x1, y1 = float(op["x1"]), float(op["y1"])
            x2, y2 = float(op["x2"]), float(op["y2"])

        if route == "curve":
            side = op.get("curve_side", "right")
            offset = float(op.get("curve_offset", 65.0))
            cx = float(op["curve_x"]) if "curve_x" in op else ((min(x1, x2) - offset) if side == "left" else (max(x1, x2) + offset))
            d_str = f"M {x1:.1f},{y1:.1f} C {cx:.1f},{y1:.1f} {cx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
            el = ET.Element(_q("path"), {
                "d": d_str, "fill": "none", "stroke": stroke, "stroke-width": f"{width:.1f}",
                "id": op.get("id", "added-line"),
            })
            last_p1, last_p2 = (cx, y2), (x2, y2)
            first_p1, first_p2 = (cx, y1), (x1, y1)
            lx = 0.125 * x1 + 0.75 * cx + 0.125 * x2
            ly = 0.5 * (y1 + y2)
        elif route == "smooth" and abs(x2 - x1) > 8 and abs(y2 - y1) > 8:
            axis = op.get("smooth_axis")
            if axis not in ("horizontal", "vertical"):
                axis = "horizontal" if abs(x2 - x1) >= abs(y2 - y1) else "vertical"
            if axis == "horizontal":
                xm = (x1 + x2) / 2.0
                d_str = f"M {x1:.1f},{y1:.1f} C {xm:.1f},{y1:.1f} {xm:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
                last_p1, last_p2 = (xm, y2), (x2, y2)
                first_p1, first_p2 = (xm, y1), (x1, y1)
            else:
                ym = (y1 + y2) / 2.0
                d_str = f"M {x1:.1f},{y1:.1f} C {x1:.1f},{ym:.1f} {x2:.1f},{ym:.1f} {x2:.1f},{y2:.1f}"
                last_p1, last_p2 = (x2, ym), (x2, y2)
                first_p1, first_p2 = (x1, ym), (x1, y1)
            el = ET.Element(_q("path"), {
                "d": d_str, "fill": "none", "stroke": stroke, "stroke-width": f"{width:.1f}",
                "id": op.get("id", "added-line"),
            })
            lx, ly = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        elif route == "elbow" and abs(x2 - x1) > 10 and abs(y2 - y1) > 10:
            mx = (x1 + x2) / 2.0
            pts = [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
            el = ET.Element(_q("polyline"), {
                "points": " ".join(f"{px:.1f},{py:.1f}" for px, py in pts),
                "fill": "none", "stroke": stroke, "stroke-width": f"{width:.1f}",
                "id": op.get("id", "added-line"),
            })
            last_p1, last_p2 = pts[-2], pts[-1]
            first_p1, first_p2 = pts[1], pts[0]
            lx, ly = mx, (y1 + y2) / 2.0
        else:
            el = ET.Element(_q("line"), {
                "x1": f"{x1:.1f}", "y1": f"{y1:.1f}", "x2": f"{x2:.1f}", "y2": f"{y2:.1f}",
                "stroke": stroke, "stroke-width": f"{width:.1f}",
                "id": op.get("id", "added-line"),
            })
            last_p1, last_p2 = (x1, y1), (x2, y2)
            first_p1, first_p2 = (x2, y2), (x1, y1)
            lx, ly = (x1 + x2) / 2.0, (y1 + y2) / 2.0

    if op.get("dashed"):
        el.set("stroke-dasharray", "5,3")
    root.append(el)

    if style != "line":
        _draw_head(root, last_p1[0], last_p1[1], last_p2[0], last_p2[1], stroke, width, style)
        if style == "both":
            _draw_head(root, first_p1[0], first_p1[1], first_p2[0], first_p2[1], stroke, width, "activate")

    if op.get("label"):
        fpt = float(op.get("font_pt", 10))
        lbl = str(op["label"])
        if op.get("label_pos"):
            lp = op["label_pos"]
            tx, ty = float(lp[0]), float(lp[1])
            anchor = op.get("label_anchor", "middle")
        else:
            vertical = abs(y2 - y1) > abs(x2 - x1) * 1.2
            tx = lx + (8 if vertical else 0)
            ty = ly + (fpt * 0.35 if vertical else -6)
            anchor = "start" if vertical else "middle"
        tw = _est_text_w(lbl, fpt) + 6
        th = fpt + 4
        if op.get("label_bg", True):
            if anchor == "start":
                bx = tx - 3
            elif anchor == "end":
                bx = tx - tw + 3
            else:
                bx = tx - tw / 2.0
            bg = ET.Element(_q("rect"), {
                "x": f"{bx:.1f}", "y": f"{ty - fpt + 1:.1f}",
                "width": f"{tw:.1f}", "height": f"{th:.1f}",
                "rx": "3", "fill": "#FFFFFF", "fill-opacity": "0.9", "stroke": "none",
            })
            root.append(bg)
        lb = ET.Element(_q("text"), {
            "x": f"{tx:.1f}", "y": f"{ty:.1f}",
            "font-size": f"{fpt:.1f}", "font-family": font_fam,
            "text-anchor": anchor,
            "fill": op.get("label_fill", stroke if style in ("inhibit", "tbar") else "#1A2B3C"),
        })
        lb.text = lbl
        root.append(lb)
    return el
