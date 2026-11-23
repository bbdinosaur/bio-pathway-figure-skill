#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg_edit.py — 保源 SVG 编辑：info / find / set-text / set-attr / translate / add-text / remove / batch / diff / export。
兼容本 Skill 分层 SVG（data-id/data-node/data-edge）及外部标准 SVG（id/class/tspan/CSS style）。
默认写出到 --out（原件不动），自动保留原有 XML 命名空间，并支持批量原子编辑、结构化变更日志、结构比对与重渲染 PNG/PDF。

用法:
  python3 svg_edit.py info target.svg
  python3 svg_edit.py find target.svg --text "混合器"
  python3 svg_edit.py set-text target.svg --old "旧文本" --value "新文本" --out edited.svg --log changes.json
  python3 svg_edit.py set-attr target.svg --id pump_a --attr fill --value "#FFF4E0" --out edited.svg
  python3 svg_edit.py translate target.svg --id legend --dx 0 --dy 24 --out edited.svg
  python3 svg_edit.py add-text target.svg --x 100 --y 50 --value "p < 0.01" --id ann1 --out edited.svg
  python3 svg_edit.py batch target.svg --ops edits.json --out edited.svg --log changes.json --export-dir /app/output
  python3 svg_edit.py diff orig.svg edited.svg
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
SVGNS = "http://www.w3.org/2000/svg"
STYLE_PROPS = {"fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "fill-opacity",
               "stroke-opacity", "font-size", "font-weight", "font-family", "visibility", "display"}


def _tag(e):
    return e.tag.split("}")[-1] if isinstance(e.tag, str) else ""


def _load(path):
    """加载 SVG 并预先注册文件中出现的所有命名空间，避免写回时出现 ns0: 破坏源结构。"""
    seen = {}
    try:
        for _ev, (prefix, uri) in ET.iterparse(str(path), events=["start-ns"]):
            if prefix not in seen:
                seen[prefix] = uri
    except Exception:
        pass
    if "" not in seen:
        ET.register_namespace("", SVGNS)
    for prefix, uri in seen.items():
        try:
            ET.register_namespace(prefix, uri)
        except Exception:
            pass
    if "xlink" not in seen:
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.parse(str(path))


def _parent_map(root):
    return {c: p for p in root.iter() for c in p}


def _elem_id(e):
    for k in ("data-id", "id", "data-node", "data-edge"):
        v = e.get(k)
        if v:
            return v
    return ""


def _matches_id(e, target_id):
    if not target_id:
        return False
    return any(e.get(k) == target_id for k in ("data-id", "id", "data-node", "data-edge"))


def _full_text(e):
    """智能拼接 <text> 及其 <tspan> 子节点文本，相邻 tspan 之间无空白时自动补单空格防粘连。"""
    parts = []
    if e.text and e.text.strip():
        parts.append(e.text.strip())
    for ch in e:
        t = "".join(ch.itertext()).strip()
        if t:
            parts.append(t)
        if ch.tail and ch.tail.strip():
            parts.append(ch.tail.strip())
    return " ".join(parts) if parts else "".join(e.itertext()).strip()


def _parse_transform_2d(tr_str):
    """解析常见 translate(dx[,dy]) / matrix(a,b,c,d,e,f) / scale(sx[,sy])，返回 (a,d,tx,ty)。"""
    a, d, tx, ty = 1.0, 1.0, 0.0, 0.0
    if not tr_str:
        return a, d, tx, ty
    for m in re.finditer(r"(translate|scale|matrix)\s*\(([^)]+)\)", str(tr_str)):
        fn = m.group(1)
        nums = [float(x) for x in re.findall(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", m.group(2))]
        if fn == "translate" and nums:
            dx = nums[0]
            dy = nums[1] if len(nums) > 1 else 0.0
            tx += a * dx
            ty += d * dy
        elif fn == "scale" and nums:
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            a *= sx
            d *= sy
        elif fn == "matrix" and len(nums) == 6:
            ma, _mb, _mc, md, me, mf = nums
            tx += a * me
            ty += d * mf
            a *= ma
            d *= md
    return a, d, tx, ty


def _abs_transform_map(root):
    """返回 {elem: (sx, sy, tx, ty)} 累计坐标变换，供 info/intake 输出画布绝对坐标。"""
    res = {}
    def _walk(node, sx, sy, tx, ty):
        na, nd, ntx, nty = _parse_transform_2d(node.get("transform"))
        csx, csy = sx * na, sy * nd
        ctx, cty = tx + sx * ntx, ty + sy * nty
        res[node] = (csx, csy, ctx, cty)
        for ch in node:
            _walk(ch, csx, csy, ctx, cty)
    _walk(root, 1.0, 1.0, 0.0, 0.0)
    return res


def _text_nodes_in_scope(root, target_id):
    if not target_id:
        return [e for e in root.iter() if _tag(e) == "text"]
    hits, seen = [], set()
    for e in root.iter():
        if _tag(e) == "text" and _matches_id(e, target_id):
            if id(e) not in seen:
                hits.append(e)
                seen.add(id(e))
        elif _matches_id(e, target_id):
            for sub in e.iter():
                if _tag(sub) == "text" and id(sub) not in seen:
                    hits.append(sub)
                    seen.add(id(sub))
    return hits


def _set_multiline_text(elem, tspans, text_val):
    """把单行/多行文本安全写回 <text>（自动处理嵌套 <tspan> 残留与 \\n 真多行换行）。"""
    new_lines = str(text_val).split("\n")
    if len(new_lines) == 1 and not tspans:
        elem.text = new_lines[0]
        return
    base_x = (tspans[0].get("x") if tspans else None) or elem.get("x")
    elem.text = ""
    if tspans:
        for idx_l, ln in enumerate(new_lines):
            if idx_l < len(tspans):
                ts = tspans[idx_l]
                for sub in list(ts):
                    ts.remove(sub)
                ts.text = ln
                ts.tail = ""
            else:
                ts_new = ET.SubElement(elem, "{%s}tspan" % SVGNS)
                if base_x is not None:
                    ts_new.set("x", str(base_x))
                ts_new.set("dy", "1.25em")
                ts_new.text = ln
        for extra in tspans[len(new_lines):]:
            for sub in list(extra):
                extra.remove(sub)
            extra.text = ""
            extra.tail = ""
    else:
        for idx_l, ln in enumerate(new_lines):
            ts_new = ET.SubElement(elem, "{%s}tspan" % SVGNS)
            if base_x is not None:
                ts_new.set("x", str(base_x))
            ts_new.set("dy", "0" if idx_l == 0 else "1.25em")
            ts_new.text = ln


def _replace_text_elem(elem, old, new, exact=False):
    """完整支持纯 <text>、多/嵌套 <tspan> 以及混合 elem.text + tspan.text + tspan.tail。"""
    tspans = [c for c in elem if _tag(c) == "tspan"]
    changed = False
    before = _full_text(elem)
    if old is None:
        if tspans or "\n" in str(new):
            _set_multiline_text(elem, tspans, new)
            return True, before
        elem.text = str(new)
        return True, before
    # 收集所有直接及嵌套文本槽位（先尝试局部精确/子串替换，最大程度保留原有 tspan 样式）
    slots = [(elem, "text")]
    for node in elem.iter():
        if node is elem:
            continue
        if _tag(node) == "tspan":
            slots.append((node, "text"))
            slots.append((node, "tail"))
    for obj, field in slots:
        cur = getattr(obj, field) or ""
        if not cur:
            continue
        if exact:
            if cur.strip() == old.strip():
                if "\n" in str(new) and obj is elem:
                    _set_multiline_text(elem, tspans, new)
                else:
                    setattr(obj, field, new)
                changed = True
        elif old in cur:
            rep = cur.replace(old, new)
            if "\n" in rep and obj is elem and not tspans:
                _set_multiline_text(elem, tspans, rep)
            else:
                setattr(obj, field, rep)
            changed = True
    if not changed and old is not None:
        norm_before = re.sub(r"\s+", " ", before).strip()
        norm_old = re.sub(r"\s+", " ", old).strip()
        if (exact and (before == old.strip() or norm_before == norm_old)) or (
            not exact and (old in before or (norm_old and norm_old in norm_before))
        ):
            if exact:
                replaced = new
            elif old in before:
                replaced = before.replace(old, new)
            else:
                replaced = norm_before.replace(norm_old, new)
            _set_multiline_text(elem, tspans, replaced)
            changed = True
    return changed, before


def _update_attr_or_style(e, attr, value, force_css=False):
    """兼容 XML 属性、内联 style="..." 及外部 <style> CSS（#id / .class / 标签规则均用内联 style 覆盖）。"""
    old_v = e.get(attr)
    style = e.get("style") or ""
    has_css = bool(style) or bool(e.get("class")) or bool(force_css)
    if has_css and attr in STYLE_PROPS:
        pairs = []
        found = False
        for seg in style.split(";"):
            seg = seg.strip()
            if not seg or ":" not in seg:
                continue
            k, v = seg.split(":", 1)
            ks, vs = k.strip(), v.strip()
            if ks == attr:
                if old_v is None:
                    old_v = vs
                pairs.append("%s:%s" % (ks, value))
                found = True
            else:
                pairs.append("%s:%s" % (ks, vs))
        if not found:
            pairs.append("%s:%s" % (attr, value))
        e.set("style", ";".join(pairs))
        if e.get(attr) is not None:
            e.set(attr, value)
        return old_v
    e.set(attr, value)
    return old_v


def _apply_translate(e, dx, dy):
    old_tr = (e.get("transform") or "").strip()
    frag = "translate(%g,%g)" % (float(dx), float(dy))
    new_tr = (frag + " " + old_tr).strip() if old_tr else frag
    e.set("transform", new_tr)
    return old_tr, new_tr


_OP_ALIASES = {
    "set-text": "set-text", "replace-text": "set-text", "edit-text": "set-text", "update-text": "set-text", "text": "set-text",
    "set-attr": "set-attr", "set-attrs": "set-attr", "style": "set-attr", "set-style": "set-attr", "update-attr": "set-attr",
    "translate": "translate", "move": "translate", "shift": "translate",
    "add-text": "add-text", "insert-text": "add-text",
    "add-rect": "add-rect", "add-box": "add-rect",
    "add-arrow": "add-arrow", "add-line": "add-arrow",
    "pad-canvas": "pad-canvas", "expand-canvas": "pad-canvas", "resize-canvas": "pad-canvas",
    "replace-color": "replace-color", "remap-color": "replace-color", "recolor": "replace-color",
    "remove": "remove", "delete": "remove", "del": "remove",
}


def _norm_hex_color(c):
    s = str(c or "").strip().lower()
    m_rgb = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
    if m_rgb:
        return "#%02x%02x%02x" % tuple(min(255, max(0, int(x))) for x in m_rgb.groups())
    if re.fullmatch(r"#[0-9a-f]{3}", s):
        return "#" + "".join(ch * 2 for ch in s[1:])
    return s


def _apply_op(root, op):
    raw_act = str(op.get("action") or op.get("op") or op.get("type") or op.get("cmd") or "").strip().lower().replace("_", "-")
    act = _OP_ALIASES.get(raw_act, raw_act)
    reason = str(op.get("reason") or op.get("note") or "")
    tid_common = op.get("id") or op.get("target_id") or op.get("target")
    if act == "set-text":
        tid = tid_common
        old = op.get("old") if "old" in op else (op.get("find") if "find" in op else (op.get("match") if "match" in op else op.get("old_text")))
        raw_v = op.get("value") if "value" in op else (op.get("new") if "new" in op else (op.get("text") if "text" in op else op.get("new_text", "")))
        val = str(raw_v)
        exact = bool(op.get("exact", False))
        first_only = bool(op.get("first_only", False))
        if old is None and not tid:
            raise ValueError("set-text 至少需要 id 或 old")
        cands = _text_nodes_in_scope(root, tid)
        changes = []
        for e in cands:
            ok, before = _replace_text_elem(e, old, val, exact=exact)
            if ok:
                changes.append({"id": _elem_id(e) or tid or "", "old": before, "new": _full_text(e)})
                if first_only:
                    break
        if not changes:
            raise LookupError("set-text 未命中目标（id=%r old=%r）" % (tid, old))
        return {"action": "set-text", "target_id": tid, "old": old, "value": val,
                "matches": len(changes), "changes": changes, "reason": reason}
    if act == "set-attr":
        tid = tid_common
        attr_pairs = []
        if isinstance(op.get("attrs"), dict) and op["attrs"]:
            attr_pairs = [(str(k), str(v)) for k, v in op["attrs"].items()]
        else:
            attr_k = op.get("attr") or op.get("attribute")
            if attr_k:
                raw_v = op.get("value") if "value" in op else op.get("new", "")
                attr_pairs = [(str(attr_k), str(raw_v))]
        recursive = bool(op.get("recursive", False))
        tag_flt = str(op.get("tag") or "").strip().lower()
        if not tid or not attr_pairs:
            raise ValueError("set-attr 需要 id 与 attr/attrs")
        has_style_tag = any(_tag(x) == "style" for x in root.iter())
        changes = []
        for e in root.iter():
            if _matches_id(e, tid):
                targets = list(e.iter()) if (recursive or tag_flt) else [e]
                for sub in targets:
                    if tag_flt and _tag(sub).lower() != tag_flt:
                        continue
                    if recursive and not tag_flt and _tag(sub) == "g" and sub is e:
                        continue
                    for ak, av in attr_pairs:
                        old_v = _update_attr_or_style(sub, ak, av, force_css=has_style_tag)
                        changes.append({"tag": _tag(sub), "id": _elem_id(sub) or tid, "attr": ak, "old": old_v, "new": av})
        if not changes:
            raise LookupError("set-attr 未找到 id/data-id=%s (tag=%r)" % (tid, tag_flt or "*"))
        return {"action": "set-attr", "target_id": tid, "attr": attr_pairs[0][0] if len(attr_pairs) == 1 else [k for k, _ in attr_pairs],
                "value": attr_pairs[0][1] if len(attr_pairs) == 1 else dict(attr_pairs),
                "matches": len(changes), "changes": changes, "reason": reason}
    if act == "translate":
        tid, dx, dy = tid_common, float(op.get("dx", 0)), float(op.get("dy", 0))
        if not tid:
            raise ValueError("translate 需要 id")
        changes = []
        for e in root.iter():
            if _matches_id(e, tid):
                old_tr, new_tr = _apply_translate(e, dx, dy)
                changes.append({"tag": _tag(e), "id": _elem_id(e), "old_transform": old_tr, "new_transform": new_tr})
        if not changes:
            raise LookupError("translate 未找到 id/data-id=%s" % tid)
        return {"action": "translate", "target_id": tid, "dx": dx, "dy": dy,
                "matches": len(changes), "changes": changes, "reason": reason}
    if act == "add-text":
        parent_id = op.get("parent")
        parent = root
        if parent_id:
            found = next((e for e in root.iter() if _matches_id(e, parent_id)), None)
            if found is None:
                raise LookupError("add-text 未找到 parent id=%s" % parent_id)
            parent = found
        el = ET.SubElement(parent, "{%s}text" % SVGNS)
        x_val = str(op.get("x", 0))
        sz_val = float(op.get("size", 12))
        el.set("x", x_val)
        el.set("y", str(op.get("y", 0)))
        el.set("font-size", "%g" % sz_val)
        el.set("fill", str(op.get("fill", "#1A202C")))
        el.set("text-anchor", str(op.get("anchor", "start")))
        if op.get("font_family"):
            el.set("font-family", str(op["font_family"]))
        if op.get("weight"):
            el.set("font-weight", str(op["weight"]))
        if op.get("id"):
            el.set("id", str(op["id"]))
        if op.get("prov"):
            el.set("data-prov", str(op["prov"]))
        raw_val = str(op.get("value", ""))
        if "\n" in raw_val:
            lines = raw_val.splitlines()
            for li, ln_txt in enumerate(lines):
                ts = ET.SubElement(el, "{%s}tspan" % SVGNS)
                ts.set("x", x_val)
                ts.set("dy", "0" if li == 0 else ("%.1f" % (sz_val * 1.28)))
                ts.text = ln_txt
        else:
            el.text = raw_val
        return {"action": "add-text", "id": op.get("id", ""), "parent": parent_id or "svg",
                "x": op.get("x", 0), "y": op.get("y", 0), "value": raw_val, "reason": reason}
    if act == "add-rect":
        parent_id = op.get("parent")
        parent = root
        if parent_id:
            found = next((e for e in root.iter() if _matches_id(e, parent_id)), None)
            if found is None:
                raise LookupError("add-rect 未找到 parent id=%s" % parent_id)
            parent = found
        el = ET.SubElement(parent, "{%s}rect" % SVGNS)
        el.set("x", str(op.get("x", 0)))
        el.set("y", str(op.get("y", 0)))
        el.set("width", str(op.get("width", 100)))
        el.set("height", str(op.get("height", 40)))
        el.set("rx", str(op.get("rx", 4)))
        el.set("fill", str(op.get("fill", "none")))
        el.set("stroke", str(op.get("stroke", "#C05621")))
        el.set("stroke-width", str(op.get("sw", 1.8)))
        if op.get("dash"):
            el.set("stroke-dasharray", str(op["dash"]))
        if op.get("opacity") is not None:
            el.set("fill-opacity", str(op["opacity"]))
        if op.get("id"):
            el.set("id", str(op["id"]))
        if op.get("prov"):
            el.set("data-prov", str(op["prov"]))
        return {"action": "add-rect", "id": op.get("id", ""), "parent": parent_id or "svg",
                "bbox": [op.get("x", 0), op.get("y", 0), op.get("width", 100), op.get("height", 40)], "reason": reason}
    if act == "add-arrow":
        import math as _m
        parent_id = op.get("parent")
        parent = root
        if parent_id:
            found = next((e for e in root.iter() if _matches_id(e, parent_id)), None)
            if found is None:
                raise LookupError("add-arrow 未找到 parent id=%s" % parent_id)
            parent = found
        raw_pts = op.get("pts")
        if isinstance(raw_pts, list) and len(raw_pts) >= 2:
            pts = [(float(pt[0]), float(pt[1])) for pt in raw_pts]
        else:
            pts = [(float(op.get("x1", 0)), float(op.get("y1", 0))),
                   (float(op.get("x2", 40)), float(op.get("y2", 0)))]
        col = str(op.get("stroke", "#C05621"))
        sw = float(op.get("sw", 2.0))
        grp = ET.SubElement(parent, "{%s}g" % SVGNS)
        if op.get("id"):
            grp.set("id", str(op["id"]))
        if op.get("prov"):
            grp.set("data-prov", str(op["prov"]))
        mk = str(op.get("marker") or "arrow").lower()
        # 末段方向向量
        x_p, y_p = pts[-2]
        x2, y2 = pts[-1]
        dx, dy = x2 - x_p, y2 - y_p
        d = _m.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        # 首段方向向量
        x1, y1 = pts[0]
        x_n, y_n = pts[1]
        dx0, dy0 = x_n - x1, y_n - y1
        d0 = _m.hypot(dx0, dy0) or 1.0
        ux0, uy0 = dx0 / d0, dy0 / d0
        draw_pts = list(pts)
        if mk == "arrowboth" and d0 > 16:
            draw_pts[0] = (x1 + ux0 * 6.5, y1 + uy0 * 6.5)
        if mk in ("arrow", "arrowboth") and d > 10:
            draw_pts[-1] = (x2 - ux * 6.5, y2 - uy * 6.5)
        elif mk == "tbar" and d > 4:
            draw_pts[-1] = (x2 - ux * 1.5, y2 - uy * 1.5)
        if len(draw_pts) == 2:
            ln = ET.SubElement(grp, "{%s}line" % SVGNS)
            ln.set("x1", "%.2f" % draw_pts[0][0])
            ln.set("y1", "%.2f" % draw_pts[0][1])
            ln.set("x2", "%.2f" % draw_pts[1][0])
            ln.set("y2", "%.2f" % draw_pts[1][1])
            ln.set("stroke", col)
            ln.set("stroke-width", "%g" % sw)
            if op.get("dash"):
                ln.set("stroke-dasharray", str(op["dash"]))
        else:
            pl = ET.SubElement(grp, "{%s}polyline" % SVGNS)
            pl.set("points", " ".join("%.2f,%.2f" % pt for pt in draw_pts))
            pl.set("fill", "none")
            pl.set("stroke", col)
            pl.set("stroke-width", "%g" % sw)
            pl.set("stroke-linejoin", "round")
            if op.get("dash"):
                pl.set("stroke-dasharray", str(op["dash"]))
        px, py = -uy * 3.8, ux * 3.8
        if mk in ("arrow", "arrowboth"):
            bx, by = x2 - ux * 9.0, y2 - uy * 9.0
            poly = ET.SubElement(grp, "{%s}polygon" % SVGNS)
            poly.set("points", "%.2f,%.2f %.2f,%.2f %.2f,%.2f" % (x2, y2, bx + px, by + py, bx - px, by - py))
            poly.set("fill", col)
        if mk == "arrowboth":
            px0, py0 = -uy0 * 3.8, ux0 * 3.8
            bx0, by0 = x1 + ux0 * 9.0, y1 + uy0 * 9.0
            poly0 = ET.SubElement(grp, "{%s}polygon" % SVGNS)
            poly0.set("points", "%.2f,%.2f %.2f,%.2f %.2f,%.2f" % (x1, y1, bx0 + px0, by0 + py0, bx0 - px0, by0 - py0))
            poly0.set("fill", col)
        elif mk == "tbar":
            tb = ET.SubElement(grp, "{%s}line" % SVGNS)
            tx, ty = x2 - ux * 1.5, y2 - uy * 1.5
            tb.set("x1", "%.2f" % (tx - uy * 5.5))
            tb.set("y1", "%.2f" % (ty + ux * 5.5))
            tb.set("x2", "%.2f" % (tx + uy * 5.5))
            tb.set("y2", "%.2f" % (ty - ux * 5.5))
            tb.set("stroke", col)
            tb.set("stroke-width", "%g" % max(sw + 0.4, 2.2))
        if op.get("label"):
            # 优先选取折线中最长水平段（或整体最长段），并将标签置于折线最高段上方避开折线
            segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
            h_segs = [s for s in segs if abs(s[0][1] - s[1][1]) <= 1.5]
            if len(pts) >= 3 and len(h_segs) >= 2:
                mx = (pts[0][0] + pts[-1][0]) / 2.0
                my = min(pt[1] for pt in pts) - 8.0
            else:
                best = max(h_segs or segs, key=lambda s: _m.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]))
                mx = (best[0][0] + best[1][0]) / 2.0
                my = min(best[0][1], best[1][1]) - 8.0
            lb_el = ET.SubElement(grp, "{%s}text" % SVGNS)
            lb_el.set("x", "%.2f" % mx)
            lb_el.set("y", "%.2f" % my)
            lb_el.set("font-size", str(op.get("label_size", 11)))
            lb_el.set("fill", str(op.get("label_fill", col)))
            lb_el.set("text-anchor", "middle")
            lb_el.text = str(op["label"])
        return {"action": "add-arrow", "id": op.get("id", ""), "marker": mk,
                "from": list(pts[0]), "to": list(pts[-1]), "n_pts": len(pts), "reason": reason}
    if act == "pad-canvas":
        pt, pr = float(op.get("top", 0)), float(op.get("right", 0))
        pb, pl = float(op.get("bottom", 0)), float(op.get("left", 0))
        vb = (root.get("viewBox") or "").replace(",", " ").split()
        if len(vb) == 4:
            vx, vy, vw, vh = [float(x) for x in vb]
        else:
            vx, vy = 0.0, 0.0
            vw = float(re.sub(r"[^0-9.]", "", root.get("width") or "800") or 800)
            vh = float(re.sub(r"[^0-9.]", "", root.get("height") or "600") or 600)
        nx, ny, nw, nh = vx - pl, vy - pt, vw + pl + pr, vh + pt + pb
        old_vb = root.get("viewBox")
        root.set("viewBox", "%g %g %g %g" % (nx, ny, nw, nh))
        root.set("width", "%g" % nw)
        root.set("height", "%g" % nh)
        bg_expanded = False
        for ch in list(root):
            if _tag(ch) != "rect":
                continue
            try:
                rx0 = float(ch.get("x") or 0)
                ry0 = float(ch.get("y") or 0)
                rw0 = float(re.sub(r"[^0-9.]", "", ch.get("width") or "0") or 0)
                rh0 = float(re.sub(r"[^0-9.]", "", ch.get("height") or "0") or 0)
            except Exception:
                continue
            if ch.get("id") == "canvas_bg" or (abs(rx0 - vx) <= 2 and abs(ry0 - vy) <= 2 and abs(rw0 - vw) <= 2 and abs(rh0 - vh) <= 2):
                ch.set("x", "%g" % nx)
                ch.set("y", "%g" % ny)
                ch.set("width", "%g" % nw)
                ch.set("height", "%g" % nh)
                bg_expanded = True
                break
        return {"action": "pad-canvas", "old_viewBox": old_vb, "new_viewBox": root.get("viewBox"),
                "bg_expanded": bg_expanded, "reason": reason}
    if act == "replace-color":
        cmap_raw = op.get("map") if isinstance(op.get("map"), dict) else {}
        if not cmap_raw and op.get("old") and (op.get("value") or op.get("new")):
            cmap_raw = {str(op["old"]): str(op.get("value") or op.get("new"))}
        if not cmap_raw:
            raise ValueError("replace-color 需要 old+value 或 map 颜色映射表")
        cmap = {_norm_hex_color(k): str(v).strip() for k, v in cmap_raw.items() if str(k).strip()}
        props = tuple(op.get("attrs") or ("fill", "stroke", "stop-color", "color"))
        scope_id = op.get("scope_id") or op.get("id")
        if scope_id:
            targets = []
            for e in root.iter():
                if _matches_id(e, scope_id):
                    targets.extend(list(e.iter()))
        else:
            targets = list(root.iter())
        hits = 0
        for e in targets:
            if _tag(e) == "style" and e.text and not scope_id:
                txt = e.text
                for k_old, v_new in cmap.items():
                    pat = re.compile(re.escape(k_old), re.I)
                    txt, n_sub = pat.subn(v_new, txt)
                    hits += n_sub
                e.text = txt
                continue
            for ak in props:
                cur = e.get(ak)
                if cur and _norm_hex_color(cur) in cmap:
                    e.set(ak, cmap[_norm_hex_color(cur)])
                    hits += 1
            st = e.get("style") or ""
            if st:
                pairs, mod = [], False
                for seg in st.split(";"):
                    seg = seg.strip()
                    if not seg or ":" not in seg:
                        continue
                    k, v = seg.split(":", 1)
                    ks, vs = k.strip(), v.strip()
                    if ks in props and _norm_hex_color(vs) in cmap:
                        pairs.append("%s:%s" % (ks, cmap[_norm_hex_color(vs)]))
                        hits += 1
                        mod = True
                    else:
                        pairs.append("%s:%s" % (ks, vs))
                if mod:
                    e.set("style", ";".join(pairs))
        if not hits:
            raise LookupError("replace-color 未匹配到目标颜色: %s" % list(cmap.keys()))
        return {"action": "replace-color", "scope_id": scope_id, "map": cmap_raw,
                "hits": hits, "reason": reason}
    if act == "remove":
        tid = op.get("id")
        if not tid:
            raise ValueError("remove 需要 id")
        pmap = _parent_map(root)
        removed = []
        for e in list(root.iter()):
            if _matches_id(e, tid) and e in pmap:
                pmap[e].remove(e)
                removed.append({"tag": _tag(e), "id": _elem_id(e)})
        if not removed:
            raise LookupError("remove 未找到可删除元素 id/data-id=%s" % tid)
        return {"action": "remove", "target_id": tid, "removed": removed, "reason": reason}
    raise ValueError("未知操作 action=%r（支持 set-text/set-attr/translate/add-text/add-rect/add-arrow/pad-canvas/remove）" % (act,))


def _append_log(log_path, records):
    if not log_path:
        return
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, list):
                rows = cur
        except Exception:
            rows = []
    if isinstance(records, list):
        rows.extend(records)
    else:
        rows.append(records)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def _export_if_needed(svg_path, a):
    out_png = getattr(a, "export_png", None)
    out_pdf = getattr(a, "export_pdf", None)
    preview = getattr(a, "preview", None)
    if getattr(a, "export_dir", None):
        ed = Path(a.export_dir)
        ed.mkdir(parents=True, exist_ok=True)
        stem = Path(svg_path).stem
        out_png = out_png or str(ed / (stem + ".png"))
        out_pdf = out_pdf or str(ed / (stem + ".pdf"))
    exp = {}
    if out_png or out_pdf or preview:
        import render as rendermod
        dpi = getattr(a, "dpi", 300) or 300
        if out_png:
            Path(out_png).parent.mkdir(parents=True, exist_ok=True)
            try:
                exp["png"] = {"path": str(out_png), "engine": rendermod.svg_to_png(svg_path, out_png, dpi)}
            except Exception as e:
                exp["png"] = {"error": str(e)}
        if out_pdf:
            Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
            try:
                exp["pdf"] = {"path": str(out_pdf), "engine": rendermod.svg_to_pdf(svg_path, out_pdf)}
            except Exception as e:
                exp["pdf"] = {"error": str(e)}
        if preview:
            Path(preview).parent.mkdir(parents=True, exist_ok=True)
            pv_dpi = min(int(getattr(a, "preview_dpi", 96) or 96), 108)
            try:
                exp["preview"] = {"path": str(preview), "dpi": pv_dpi,
                                  "engine": rendermod.svg_to_png(svg_path, preview, pv_dpi)}
            except Exception as e:
                exp["preview"] = {"error": str(e)}
    return exp


def _save(tree, a):
    dst = Path(a.out) if getattr(a, "out", None) else Path(a.svg)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst), encoding="utf-8", xml_declaration=True)
    return dst


def _write_diff(orig_path, edited_path):
    t1, t2 = _load(orig_path), _load(edited_path)
    r1, r2 = t1.getroot(), t2.getroot()
    c1, c2 = {}, {}
    for e in r1.iter():
        c1[_tag(e)] = c1.get(_tag(e), 0) + 1
    for e in r2.iter():
        c2[_tag(e)] = c2.get(_tag(e), 0) + 1
    tx1 = [_full_text(e) for e in r1.iter() if _tag(e) == "text" and _full_text(e)]
    tx2 = [_full_text(e) for e in r2.iter() if _tag(e) == "text" and _full_text(e)]
    removed_t = [x for x in tx1 if x not in tx2]
    added_t = [x for x in tx2 if x not in tx1]
    id1 = {_elem_id(e): dict(e.attrib) for e in r1.iter() if _elem_id(e)}
    id2 = {_elem_id(e): dict(e.attrib) for e in r2.iter() if _elem_id(e)}
    attr_diffs = []
    for k in sorted(set(id1) & set(id2)):
        if id1[k] != id2[k]:
            chg = {ak: [id1[k].get(ak), id2[k].get(ak)] for ak in sorted(set(id1[k]) | set(id2[k])) if id1[k].get(ak) != id2[k].get(ak)}
            attr_diffs.append({"id": k, "changes": chg})
    shared_ids = set(id1) & set(id2)
    untouched = len(shared_ids) - len(attr_diffs)
    return {
        "orig": str(orig_path),
        "edited": str(edited_path),
        "preserved_root_viewBox": r1.get("viewBox") == r2.get("viewBox"),
        "tag_count_delta": {k: c2.get(k, 0) - c1.get(k, 0) for k in sorted(set(c1) | set(c2)) if c2.get(k, 0) != c1.get(k, 0)},
        "removed_ids": sorted(set(id1) - set(id2)),
        "added_ids": sorted(set(id2) - set(id1)),
        "attr_diffs": attr_diffs,
        "text_removed": removed_t,
        "text_added": added_t,
        "untouched_id_count": untouched,
        "untouched_ratio": round(untouched / float(len(id1)), 4) if id1 else 1.0,
    }


def _write_result_skel(a, dst, records, exp, diff_rep, raw_spec=None):
    dst_res = getattr(a, "result_out", None) or getattr(a, "result_skel", None)
    if not dst_res:
        return
    raw_spec = raw_spec if isinstance(raw_spec, dict) else {}
    contract = {}
    if getattr(a, "contract", None) and Path(a.contract).exists():
        try:
            import audit_delivery as auditmod
            cj = json.loads(Path(a.contract).read_text(encoding="utf-8"))
            keys = auditmod._extract_contract_keys(cj)
            stem = Path(dst).stem
            for k in keys:
                kl = k.strip().lower()
                if kl in ("editable_svg", "svg", "svg_file", "svg_path", "output_svg", "editable_source", "editable_source_path") or kl.endswith("_svg") or kl.endswith("_svg_path"):
                    contract[k] = Path(dst).name
                elif kl in ("png", "png_file", "png_path", "preview_png", "rendered_png", "output_png", "image_path") or kl.endswith("_png") or kl.endswith("_png_path"):
                    contract[k] = stem + ".png"
                elif kl in ("pdf", "pdf_file", "pdf_path", "output_pdf", "vector_pdf") or kl.endswith("_pdf") or kl.endswith("_pdf_path"):
                    contract[k] = stem + ".pdf"
                elif kl in ("status", "run_status"):
                    contract[k] = "ok"
                elif kl in ("case_id", "id"):
                    contract[k] = a.case_id or "CASE_ID"
                elif kl in ("change_log", "edit_log", "change_records"):
                    contract[k] = records
                elif kl in ("diff", "diff_report", "svg_diff"):
                    contract[k] = diff_rep
                else:
                    contract[k] = "<待填：依据保源编辑实况与 diff 如实撰写>"
        except Exception:
            pass
    sk = {
        "case_id": getattr(a, "case_id", None) or "CASE_ID",
        "status": "ok" if not any("error" in v for v in exp.values()) else "partial",
        "deliverables": {
            "editable_source": {"path": Path(dst).name, "format": "svg", "source_svg": str(a.svg)},
            "exports": [v for k, v in exp.items() if k != "preview" and "path" in v],
        },
        "sources": [str(a.svg)],
        "diff": diff_rep,
        "change_records": records,
        "output_contract": contract,
        "output_contract_fields": list(contract.keys()),
        "uncertainty": list(raw_spec.get("uncertainty") or []),
    }
    for k, v in contract.items():
        if k not in sk:
            sk[k] = v
    if isinstance(raw_spec.get("result_fields"), dict):
        for k, v in raw_spec["result_fields"].items():
            sk[k] = v
    p = Path(dst_res)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sk, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_info(a):
    t = _load(a.svg)
    root = t.getroot()
    pmap = _parent_map(root)
    tmap = _abs_transform_map(root)
    counts, layers, texts, boxes, shapes = {}, [], [], [], []
    has_style_tag = False
    for e in root.iter():
        tg = _tag(e)
        counts[tg] = counts.get(tg, 0) + 1
        if tg == "style":
            has_style_tag = True
        if tg == "g":
            gid = _elem_id(e)
            if gid:
                layers.append(gid)
        if tg in ("circle", "ellipse") and len(shapes) < 12:
            sid = _elem_id(e) or _elem_id(pmap.get(e, root))
            sh = {"tag": tg, "id": sid, "cx": e.get("cx"), "cy": e.get("cy"),
                  "r": e.get("r") or e.get("rx")}
            sx, sy, ox, oy = tmap.get(e, (1.0, 1.0, 0.0, 0.0))
            if abs(ox) > 0.1 or abs(oy) > 0.1 or abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01:
                try:
                    sh["abs_xy"] = [round(ox + sx * float(e.get("cx") or 0), 1),
                                    round(oy + sy * float(e.get("cy") or 0), 1)]
                except Exception:
                    pass
            shapes.append(sh)
        if tg == "rect" and len(boxes) < 16:
            rid = _elem_id(e) or _elem_id(pmap.get(e, root))
            if e.get("width") and e.get("height"):
                bx = {"id": rid, "x": e.get("x"), "y": e.get("y"),
                      "w": e.get("width"), "h": e.get("height")}
                sx, sy, ox, oy = tmap.get(e, (1.0, 1.0, 0.0, 0.0))
                if abs(ox) > 0.1 or abs(oy) > 0.1 or abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01:
                    try:
                        bx["abs_xy"] = [round(ox + sx * float(e.get("x") or 0), 1),
                                        round(oy + sy * float(e.get("y") or 0), 1)]
                    except Exception:
                        pass
                boxes.append(bx)
        if tg == "text":
            txt = _full_text(e)
            if not txt:
                continue
            eid = _elem_id(e) or _elem_id(pmap.get(e, root))
            tx = e.get("x")
            ty = e.get("y")
            if tx is None or ty is None:
                for ch in e:
                    if _tag(ch) == "tspan":
                        tx = tx if tx is not None else ch.get("x")
                        ty = ty if ty is not None else ch.get("y")
                        if tx is not None and ty is not None:
                            break
            rec = {"id": eid, "x": tx, "y": ty, "text": txt[:70]}
            sx, sy, ox, oy = tmap.get(e, (1.0, 1.0, 0.0, 0.0))
            if abs(ox) > 0.1 or abs(oy) > 0.1 or abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01:
                try:
                    rec["abs_xy"] = [round(ox + sx * float(tx or 0), 1),
                                     round(oy + sy * float(ty or 0), 1)]
                except Exception:
                    pass
            texts.append(rec)
    info = {
        "svg": str(a.svg),
        "width": root.get("width"),
        "height": root.get("height"),
        "viewBox": root.get("viewBox"),
        "has_css_style_tag": has_style_tag,
        "counts": {k: counts.get(k, 0) for k in ("g", "rect", "path", "polyline", "line", "circle", "ellipse", "text")},
        "groups": layers[:32],
        "rect_boxes": boxes,
        "shapes": shapes,
        "text_samples": texts[:60],
        "text_total": len(texts),
    }
    if len(texts) == 0 and counts.get("path", 0) > 20:
        info["warning"] = "未检测到 <text> 节点但存在大量 <path>，原图文字可能已转曲；请结合坐标用 add-text/add-rect 叠加标注并在 uncertainty 说明"
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_find(a):
    t = _load(a.svg)
    root = t.getroot()
    pmap = _parent_map(root)
    tmap = _abs_transform_map(root)

    def _abs_pt(el):
        sx, sy, ox, oy = tmap.get(el, (1.0, 1.0, 0.0, 0.0))
        lx = el.get("x") or el.get("cx")
        ly = el.get("y") or el.get("cy")
        if lx is None or ly is None:
            for ch in el:
                if _tag(ch) == "tspan":
                    lx = lx if lx is not None else ch.get("x")
                    ly = ly if ly is not None else ch.get("y")
                    if lx is not None and ly is not None:
                        break
        try:
            if lx is not None and ly is not None:
                return [round(ox + sx * float(lx), 1), round(oy + sy * float(ly), 1)]
            if abs(ox) > 0.1 or abs(oy) > 0.1:
                return [round(ox, 1), round(oy, 1)]
        except Exception:
            pass
        return None

    hits = []
    for e in root.iter():
        tg = _tag(e)
        eid = _elem_id(e)
        if a.id and _matches_id(e, a.id):
            h = {"match": "id", "tag": tg, "id": eid,
                 "attrs": {k: v for k, v in e.attrib.items() if k in ("id", "data-id", "data-node", "data-edge", "x", "y", "cx", "cy", "width", "height", "fill", "stroke", "style", "transform")},
                 "text": _full_text(e)[:60] if tg == "text" else ""}
            ap = _abs_pt(e)
            if ap:
                h["abs_xy"] = ap
            hits.append(h)
        elif a.text:
            if tg == "text" and a.text in _full_text(e):
                pid = eid or _elem_id(pmap.get(e, root))
                h = {"match": "text", "tag": "text", "id": pid, "text": _full_text(e)}
                ap = _abs_pt(e)
                if ap:
                    h["abs_xy"] = ap
                hits.append(h)
            elif eid and tg != "text" and a.text in ET.tostring(e, encoding="unicode") and tg in ("rect", "g", "polyline", "path"):
                h = {"match": "elem", "tag": tg, "id": eid,
                     "attrs": {k: v for k, v in e.attrib.items() if k in ("x", "y", "width", "height", "fill", "stroke", "style")}}
                ap = _abs_pt(e)
                if ap:
                    h["abs_xy"] = ap
                hits.append(h)
    hits.sort(key=lambda x: (0 if x.get("match") in ("id", "text") else 1))
    print(json.dumps({"svg": str(a.svg), "count": len(hits), "hits": hits[:50]}, ensure_ascii=False, indent=1))
    return 0 if hits else 1


def _run_single_op(a, op):
    t = _load(a.svg)
    try:
        rec = _apply_op(t.getroot(), op)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except LookupError as e:
        print(str(e), file=sys.stderr)
        return 1
    dst = _save(t, a)
    exp = _export_if_needed(dst, a)
    diff_rep = _write_diff(a.svg, dst) if Path(a.svg).resolve() != Path(dst).resolve() else {}
    rec["ok"] = True
    rec["source_svg"] = str(a.svg)
    rec["output_svg"] = str(dst)
    rec["exports"] = exp
    if diff_rep:
        rec["diff"] = diff_rep
    _append_log(a.log, rec)
    _write_result_skel(a, dst, [rec], exp, diff_rep)
    if getattr(a, "result_out", None):
        import audit_delivery as auditmod
        rec["audit"] = auditmod.audit(Path(a.result_out).parent, getattr(a, "contract", None))
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


def cmd_batch(a):
    raw = json.loads(Path(a.ops).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        ops = raw.get("ops") or raw.get("edits") or raw.get("operations")
        if ops is None and any(k in raw for k in ("action", "op", "type", "cmd")):
            ops = [raw]
    else:
        ops = raw
    if not isinstance(ops, list) or not ops:
        print("ops 文件必须是非空操作数组或含 ops/edits 数组的对象", file=sys.stderr)
        return 2
    t = _load(a.svg)
    root = t.getroot()
    recs = []
    for idx, op in enumerate(ops):
        try:
            r = _apply_op(root, op)
            r["step"] = idx + 1
            recs.append(r)
        except Exception as e:
            print("batch 第 %d 步失败: %s" % (idx + 1, e), file=sys.stderr)
            return 1
    dst = _save(t, a)
    exp = _export_if_needed(dst, a)
    diff_rep = _write_diff(a.svg, dst) if Path(a.svg).resolve() != Path(dst).resolve() else {}
    _append_log(a.log, recs)
    _write_result_skel(a, dst, recs, exp, diff_rep, raw_spec=raw if isinstance(raw, dict) else None)
    out = {"ok": True, "source_svg": str(a.svg), "output_svg": str(dst),
           "ops_applied": len(recs), "exports": exp, "diff": diff_rep, "records": recs}
    if getattr(a, "result_out", None):
        import audit_delivery as auditmod
        out["audit"] = auditmod.audit(Path(a.result_out).parent, getattr(a, "contract", None))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_diff(a):
    rep = _write_diff(a.svg, a.other)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def cmd_export(a):
    exp = _export_if_needed(a.svg, a)
    if not exp:
        print("export 需要 --export-dir 或 --export-png / --export-pdf", file=sys.stderr)
        return 2
    print(json.dumps({"svg": str(a.svg), "exports": exp}, ensure_ascii=False, indent=1))
    return 0 if not any("error" in v for v in exp.values()) else 1


def _add_common(ap):
    ap.add_argument("--out", help="输出 SVG 路径（强烈建议另存，原件不动）")
    ap.add_argument("--reason", default="", help="修改依据（写入变更日志）")
    ap.add_argument("--log", default=None, help="变更日志 JSON 文件（自动追加）")
    ap.add_argument("--export-dir", default=None, help="同步导出 PNG/PDF 的目录")
    ap.add_argument("--export-png", default=None)
    ap.add_argument("--export-pdf", default=None)
    ap.add_argument("--preview", default=None, help="轻量视觉自检预览 PNG 路径（<=108 DPI）")
    ap.add_argument("--preview-dpi", type=int, default=96)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--contract", default=None)
    ap.add_argument("--result-skel", default=None)
    ap.add_argument("--result-out", default=None, help="直接写入正式 result.json 并自动触发交付核验")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    p1 = sp.add_parser("info")
    p1.add_argument("svg")

    p2 = sp.add_parser("find")
    p2.add_argument("svg")
    p2.add_argument("--text", default=None)
    p2.add_argument("--id", default=None)

    p3 = sp.add_parser("set-text")
    p3.add_argument("svg")
    p3.add_argument("--id", default=None)
    p3.add_argument("--old", default=None)
    p3.add_argument("--value", required=True)
    p3.add_argument("--exact", action="store_true")
    p3.add_argument("--first-only", action="store_true")
    _add_common(p3)

    p4 = sp.add_parser("set-attr")
    p4.add_argument("svg")
    p4.add_argument("--id", required=True)
    p4.add_argument("--attr", required=True)
    p4.add_argument("--value", required=True)
    p4.add_argument("--recursive", action="store_true")
    p4.add_argument("--tag", default=None)
    _add_common(p4)

    p5 = sp.add_parser("translate")
    p5.add_argument("svg")
    p5.add_argument("--id", required=True)
    p5.add_argument("--dx", type=float, default=0.0)
    p5.add_argument("--dy", type=float, default=0.0)
    _add_common(p5)

    p6 = sp.add_parser("add-text")
    p6.add_argument("svg")
    p6.add_argument("--x", type=float, required=True)
    p6.add_argument("--y", type=float, required=True)
    p6.add_argument("--value", required=True)
    p6.add_argument("--id", default=None)
    p6.add_argument("--parent", default=None)
    p6.add_argument("--size", type=float, default=12.0)
    p6.add_argument("--fill", default="#1A202C")
    p6.add_argument("--anchor", default="start")
    p6.add_argument("--weight", default=None)
    p6.add_argument("--prov", default=None)
    _add_common(p6)

    p7 = sp.add_parser("remove")
    p7.add_argument("svg")
    p7.add_argument("--id", required=True)
    _add_common(p7)

    p8 = sp.add_parser("batch")
    p8.add_argument("svg")
    p8.add_argument("--ops", required=True, help="批量编辑 JSON 文件路径")
    _add_common(p8)

    p9 = sp.add_parser("diff")
    p9.add_argument("svg")
    p9.add_argument("other")

    p10 = sp.add_parser("export")
    p10.add_argument("svg")
    p10.add_argument("--export-dir", default=None)
    p10.add_argument("--export-png", default=None)
    p10.add_argument("--export-pdf", default=None)
    p10.add_argument("--preview", default=None)
    p10.add_argument("--preview-dpi", type=int, default=96)
    p10.add_argument("--dpi", type=int, default=300)

    p11 = sp.add_parser("replace-color")
    p11.add_argument("svg")
    p11.add_argument("--old", required=True)
    p11.add_argument("--value", required=True)
    p11.add_argument("--id", default=None)
    _add_common(p11)

    a = p.parse_args()
    if a.cmd == "info":
        return cmd_info(a)
    if a.cmd == "find":
        return cmd_find(a)
    if a.cmd == "set-text":
        return _run_single_op(a, {"action": "set-text", "id": a.id, "old": a.old, "value": a.value,
                                  "exact": a.exact, "first_only": a.first_only, "reason": a.reason})
    if a.cmd == "set-attr":
        return _run_single_op(a, {"action": "set-attr", "id": a.id, "attr": a.attr, "value": a.value,
                                  "recursive": a.recursive, "tag": a.tag, "reason": a.reason})
    if a.cmd == "translate":
        return _run_single_op(a, {"action": "translate", "id": a.id, "dx": a.dx, "dy": a.dy,
                                  "reason": a.reason})
    if a.cmd == "add-text":
        return _run_single_op(a, {"action": "add-text", "x": a.x, "y": a.y, "value": a.value,
                                  "id": a.id, "parent": a.parent, "size": a.size, "fill": a.fill,
                                  "anchor": a.anchor, "weight": a.weight, "prov": a.prov, "reason": a.reason})
    if a.cmd == "remove":
        return _run_single_op(a, {"action": "remove", "id": a.id, "reason": a.reason})
    if a.cmd == "replace-color":
        return _run_single_op(a, {"action": "replace-color", "old": a.old, "value": a.value,
                                  "scope_id": a.id, "reason": a.reason})
    if a.cmd == "batch":
        return cmd_batch(a)
    if a.cmd == "diff":
        return cmd_diff(a)
    return cmd_export(a)


if __name__ == "__main__":
    sys.exit(main())
