#!/usr/bin/env python3
"""Source-preserving SVG inspector & surgical batch editor.

Modes:
  1. Inspect any SVG (dims, layers, text nodes incl. multi-tspan, named shapes, colors):
     python3 ga_svg_edit.py --svg in.svg --inspect
  2. Single deterministic text replacement (handles multi-tspan safely):
     python3 ga_svg_edit.py --svg in.svg --out out.svg --old "old" --new "new" [--all]
  3. Batch surgical edits (replace_text, set_text_by_index, set_attr, replace_color,
     translate, hide, add_overlay):
     python3 ga_svg_edit.py --svg in.svg --out out.svg --edits edits.json

Preserves 100% of untouched DOM, layers, IDs, coordinates, inline styles, and namespaces.
Outputs structured change records suitable for result.json change_log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gaconfig import FONT, INK, MUT, parse_svg_dims, parse_svg_viewbox  # noqa: E402
from textmetrics import text_width, wrap_text  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
NS = f"{{{SVG_NS}}}"
_STYLE_PROPS = {
    "fill", "stroke", "stroke-width", "stroke-dasharray", "opacity",
    "fill-opacity", "stroke-opacity", "font-size", "font-weight",
    "font-family", "visibility", "display",
}


def _strip(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _full_text(el) -> str:
    return "".join(el.itertext())


def _parse_style(style_str: str) -> dict[str, str]:
    out = {}
    for chunk in (style_str or "").split(";"):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k:
                out[k] = v
    return out


def _format_style(st: dict[str, str]) -> str:
    return ";".join(f"{k}:{v}" for k, v in st.items())


def _get_eff_attr(el, name: str) -> str:
    st = _parse_style(el.get("style", ""))
    if name in st:
        return st[name]
    return (el.get(name) or "").strip()


def _set_eff_attr(el, name: str, val: str) -> str:
    """Update attribute AND keep inline style=... consistent so CSS/<style> classes never shadow XML."""
    prev = _get_eff_attr(el, name)
    nl = name.lower()
    if nl in _STYLE_PROPS and (el.get("style") is not None or el.get("class") is not None):
        st = _parse_style(el.get("style", ""))
        if nl in st or el.get("class") is not None:
            st[nl] = val
            el.set("style", _format_style(st))
            el.set(name, val)
            return prev
    el.set(name, val)
    return prev


_NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "gray": "#808080", "grey": "#808080", "orange": "#ffa500",
    "purple": "#800080", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "navy": "#000080", "teal": "#008080", "maroon": "#800000", "silver": "#c0c0c0",
}


def _norm_color(c: str) -> str:
    """Normalize named colors, #abc, #AABBCC, and rgb(r,g,b) to lowercase #rrggbb."""
    s = (c or "").strip().lower()
    if s in _NAMED_COLORS:
        return _NAMED_COLORS[s]
    if re.fullmatch(r"#[0-9a-f]{3}", s):
        return "#" + "".join(ch * 2 for ch in s[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", s):
        return s
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)", s)
    if m:
        r, g, b = (max(0, min(255, int(m.group(i)))) for i in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return s


def _norm_ws_dash(s: str) -> str:
    """Normalize Unicode minus/en-dash/nbsp for tolerant fallback matching in Illustrator/Prism SVGs."""
    return (s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
             .replace("\u00a0", " "))


def _replace_el_text(el, old_s: str, new_s: str) -> bool:
    """Replace text cleanly on plain <text> or multi-<tspan> elements (with Unicode dash/nbsp fallback)."""
    for node in el.iter():
        if node.text and old_s in node.text:
            node.text = node.text.replace(old_s, new_s, 1)
            return True
    full = _full_text(el)
    if old_s in full:
        replaced = full.replace(old_s, new_s, 1)
        tspans = [c for c in el if _strip(c.tag) == "tspan"]
        if tspans:
            tspans[0].text = replaced
            for extra in tspans[1:]:
                extra.text = ""
                extra.tail = ""
        else:
            el.text = replaced
        return True
    # Normalized dash/nbsp fallback
    old_n = _norm_ws_dash(old_s)
    if old_n in _norm_ws_dash(full):
        for node in el.iter():
            if node.text and old_n in _norm_ws_dash(node.text):
                idx = _norm_ws_dash(node.text).index(old_n)
                node.text = node.text[:idx] + new_s + node.text[idx + len(old_n):]
                return True
        idx = _norm_ws_dash(full).index(old_n)
        replaced = full[:idx] + new_s + full[idx + len(old_n):]
        tspans = [c for c in el if _strip(c.tag) == "tspan"]
        if tspans:
            tspans[0].text = replaced
            for extra in tspans[1:]:
                extra.text = ""
                extra.tail = ""
        else:
            el.text = replaced
        return True
    return False


def _set_el_text(el, new_s: str):
    tspans = [c for c in el if _strip(c.tag) == "tspan"]
    if tspans:
        tspans[0].text = new_s
        for extra in tspans[1:]:
            extra.text = ""
            extra.tail = ""
    else:
        el.text = new_s


def _rect_geom_from_el(el) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) for <rect>, or axis-aligned rectangular <polygon>/<path> (matplotlib/Prism bars)."""
    tag = _strip(el.tag)
    if tag == "rect":
        try:
            return (float(el.get("x", 0)), float(el.get("y", 0)),
                    float(el.get("width", 0)), float(el.get("height", 0)))
        except ValueError:
            return None
    pts = []
    if tag == "polygon":
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", el.get("points", ""))]
        pts = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    elif tag == "path":
        d = (el.get("d") or "").strip()
        # Only rewrite clean straight-edge absolute M/L/H/V/Z paths (never touch curves!)
        if d and not re.search(r"[CcSsQqTtAa]", d):
            cx, cy = 0.0, 0.0
            for tok in re.finditer(r"([MmLlHhVvZz])\s*([^MmLlHhVvZz]*)", d):
                cmd = tok.group(1)
                nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", tok.group(2))]
                if cmd == "M":
                    for i in range(0, len(nums) - 1, 2):
                        cx, cy = nums[i], nums[i + 1]
                        pts.append((cx, cy))
                elif cmd == "m":
                    for i in range(0, len(nums) - 1, 2):
                        cx, cy = cx + nums[i], cy + nums[i + 1]
                        pts.append((cx, cy))
                elif cmd == "L":
                    for i in range(0, len(nums) - 1, 2):
                        cx, cy = nums[i], nums[i + 1]
                        pts.append((cx, cy))
                elif cmd == "l":
                    for i in range(0, len(nums) - 1, 2):
                        cx, cy = cx + nums[i], cy + nums[i + 1]
                        pts.append((cx, cy))
                elif cmd == "H":
                    for v in nums:
                        cx = v
                        pts.append((cx, cy))
                elif cmd == "h":
                    for v in nums:
                        cx += v
                        pts.append((cx, cy))
                elif cmd == "V":
                    for v in nums:
                        cy = v
                        pts.append((cx, cy))
                elif cmd == "v":
                    for v in nums:
                        cy += v
                        pts.append((cx, cy))
    if len(pts) >= 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if (x1 - x0) > 1e-3 and (y1 - y0) > 1e-3:
            # Verify all vertices lie on the axis-aligned rectangle perimeter
            tol = 0.25
            if all((abs(px - x0) <= tol or abs(px - x1) <= tol) and (abs(py - y0) <= tol or abs(py - y1) <= tol)
                   for px, py in pts):
                return (x0, y0, x1 - x0, y1 - y0)
    return None


def inspect_svg(svg_path: Path, query: str | None = None) -> dict:
    raw = svg_path.read_text(encoding="utf-8", errors="ignore")
    cw, ch = parse_svg_dims(raw)
    root = ET.fromstring(raw)
    layers = []
    texts = []
    named_shapes = []
    colors = set()
    css_classes = set()
    shapes = {}
    parent_map = {c: p for p in root.iter() for c in p}

    def _nearest_layer(el):
        cur = el
        while cur in parent_map:
            cur = parent_map[cur]
            if _strip(cur.tag) == "g" and cur.get("id"):
                return cur.get("id")
        return ""

    layer_labels = {}
    t_idx = 0
    for el in root.iter():
        tag = _strip(el.tag)
        if tag == "g" and el.get("id"):
            lid = el.get("id")
            layers.append(lid)
            ilbl = el.get("{http://www.inkscape.org/namespaces/inkscape}label") or el.get("data-name")
            if ilbl and ilbl != lid:
                layer_labels[lid] = ilbl
            # Surface matplotlib-style <g id="patch_3"><path d="M...Z"/></g> single-rect containers
            if query or len(named_shapes) < 80:
                sh_ch = [ch for ch in el if _strip(ch.tag) in ("rect", "path", "polygon")]
                if len(sh_ch) == 1 and not sh_ch[0].get("id"):
                    rb = _rect_geom_from_el(sh_ch[0])
                    if rb is not None:
                        named_shapes.append({
                            "id": lid,
                            "tag": f"g>{_strip(sh_ch[0].tag)}",
                            "layer": _nearest_layer(el),
                            "fill": _get_eff_attr(sh_ch[0], "fill"),
                            "stroke": _get_eff_attr(sh_ch[0], "stroke"),
                            "geom": {"x": f"{rb[0]:g}", "y": f"{rb[1]:g}",
                                     "width": f"{rb[2]:g}", "height": f"{rb[3]:g}", "rect_like": True},
                        })
        elif tag == "text":
            txt = _full_text(el).strip()
            tx_v = el.get("x", "")
            ty_v = el.get("y", "")
            if not tx_v or not ty_v:
                for child in el:
                    if _strip(child.tag) == "tspan":
                        tx_v = tx_v or child.get("x", "")
                        ty_v = ty_v or child.get("y", "")
                        if tx_v and ty_v:
                            break
            ent_t = {
                "index": t_idx,
                "id": el.get("id", ""),
                "layer": _nearest_layer(el),
                "text": txt[:140],
                "x": tx_v,
                "y": ty_v,
                "font_size": _get_eff_attr(el, "font-size"),
                "fill": _get_eff_attr(el, "fill"),
            }
            if el.get("transform"):
                ent_t["transform"] = el.get("transform")
            texts.append(ent_t)
            t_idx += 1
        elif tag in ("rect", "circle", "ellipse", "line", "polygon", "polyline", "path"):
            shapes[tag] = shapes.get(tag, 0) + 1
            if el.get("id") and (query or len(named_shapes) < 80):
                geom = {k: el.get(k) for k in ("x", "y", "width", "height", "cx", "cy", "r", "x1", "y1", "x2", "y2")
                        if el.get(k) is not None}
                if not geom and tag in ("path", "polygon"):
                    rb = _rect_geom_from_el(el)
                    if rb is not None:
                        geom = {"x": f"{rb[0]:g}", "y": f"{rb[1]:g}",
                                "width": f"{rb[2]:g}", "height": f"{rb[3]:g}", "rect_like": True}
                ent = {
                    "id": el.get("id"),
                    "tag": tag,
                    "layer": _nearest_layer(el),
                    "fill": _get_eff_attr(el, "fill"),
                    "stroke": _get_eff_attr(el, "stroke"),
                }
                if el.get("class"):
                    ent["class"] = el.get("class")
                if geom:
                    ent["geom"] = geom
                named_shapes.append(ent)
        elif tag == "style" and el.text:
            for m in re.finditer(r'(?:fill|stroke)\s*:\s*(#[0-9a-fA-F]{3,6}|rgba?\([^)]+\))', el.text):
                colors.add(m.group(1))
            for cm in re.finditer(r'\.([A-Za-z_][A-Za-z0-9_-]*)\s*\{', el.text):
                css_classes.add(cm.group(1))
        for k in ("fill", "stroke"):
            v = _get_eff_attr(el, k)
            if v and v.lower() not in ("none", "transparent") and not v.lower().startswith("url("):
                colors.add(v)
    n_text_total = len(texts)
    if query:
        q = query.lower()
        texts = [t for t in texts
                 if q in t.get("text", "").lower() or q in t.get("id", "").lower() or q in t.get("layer", "").lower()]
        named_shapes = [s for s in named_shapes
                        if q in s.get("id", "").lower() or q in s.get("layer", "").lower() or q in str(s.get("class", "")).lower()]
    res_insp = {
        "svg": str(svg_path),
        "dims": [cw, ch],
        "viewBox": root.get("viewBox", ""),
        "layers": layers[:40],
        "n_text": n_text_total,
        "text_nodes": texts[:80],
        "named_shapes": named_shapes[:80],
        "shape_counts": shapes,
        "colors_used": sorted(colors)[:30],
    }
    if query:
        res_insp["filter"] = query
    if layer_labels:
        res_insp["layer_labels"] = layer_labels
    if css_classes:
        res_insp["css_classes"] = sorted(css_classes)[:40]
    return res_insp


def _add_overlay(root, spec: dict, vb: tuple[float, float, float, float]) -> list[str]:
    """Append a non-destructive overlay layer (scalebar / legend / arrows / footer / note)."""
    vx0, vy0, vw, vh = vb
    g = ET.SubElement(root, f"{NS}g", {
        "id": spec.get("id", "layer-ga-edits"),
        "{http://www.inkscape.org/namespaces/inkscape}label": "GA edits",
    })
    added = []
    sb = spec.get("scalebar")
    if isinstance(sb, dict):
        x = float(sb.get("x", vx0 + 40))
        y = float(sb.get("y", vy0 + vh - 52))
        px = float(sb.get("px", 100))
        lab = str(sb.get("length", "20 um"))
        box_w = px + text_width(lab, 12.0) + 28.0
        ET.SubElement(g, f"{NS}rect", {
            "x": f"{x-8:.1f}", "y": f"{y-14:.1f}",
            "width": f"{box_w:.1f}", "height": "26",
            "rx": "4", "fill": "#FFFFFF", "fill-opacity": "0.9",
            "stroke": "#CBD5E1", "stroke-width": "0.8",
        })
        ET.SubElement(g, f"{NS}line", {"x1": f"{x:.1f}", "y1": f"{y:.1f}",
                                       "x2": f"{x+px:.1f}", "y2": f"{y:.1f}",
                                       "stroke": INK, "stroke-width": "2.4"})
        for ex in (x, x + px):
            ET.SubElement(g, f"{NS}line", {"x1": f"{ex:.1f}", "y1": f"{y-4:.1f}",
                                           "x2": f"{ex:.1f}", "y2": f"{y+4:.1f}",
                                           "stroke": INK, "stroke-width": "2.0"})
        t = ET.SubElement(g, f"{NS}text", {
            "x": f"{x+px+8:.1f}", "y": f"{y+4:.1f}",
            "font-family": FONT, "font-size": "12", "font-weight": "bold", "fill": INK,
        })
        t.text = lab
        added.append(f"overlay scalebar '{lab}' ({px:.0f}px)")

    leg = spec.get("legend")
    if isinstance(leg, dict) and leg.get("items"):
        items = leg["items"]
        max_lw = max((text_width(str(it.get("label", "")), 11.5) for it in items), default=80.0)
        bw = float(leg.get("width", max(160.0, max_lw + 44.0)))
        lx = float(leg.get("x", vx0 + vw - bw - 20))
        ly = float(leg.get("y", vy0 + 24))
        bh = 14 + len(items) * 20
        ET.SubElement(g, f"{NS}rect", {
            "x": f"{lx:.1f}", "y": f"{ly:.1f}", "width": f"{bw:.1f}", "height": f"{bh:.1f}",
            "rx": "6", "fill": "#FFFFFF", "fill-opacity": "0.94",
            "stroke": "#CBD5E1", "stroke-width": "0.9",
        })
        for idx, it in enumerate(items):
            iy = ly + 18 + idx * 20
            ET.SubElement(g, f"{NS}rect", {
                "x": f"{lx+10:.1f}", "y": f"{iy-10:.1f}", "width": "12", "height": "12",
                "rx": "2", "fill": str(it.get("color", "#0072B2")),
            })
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{lx+28:.1f}", "y": f"{iy:.1f}",
                "font-family": FONT, "font-size": "11.5", "fill": INK,
            })
            t.text = str(it.get("label", ""))
        added.append(f"overlay legend ({len(items)} items)")

    arrows = spec.get("arrows") or ([spec["arrow"]] if spec.get("arrow") else [])
    for ar in arrows:
        if not isinstance(ar, dict):
            continue
        x1, y1 = float(ar.get("x1", vx0 + 50)), float(ar.get("y1", vy0 + 50))
        x2, y2 = float(ar.get("x2", vx0 + 120)), float(ar.get("y2", vy0 + 50))
        akind = str(ar.get("kind", "activate")).lower()
        col = str(ar.get("color", "#DC2626" if akind == "inhibit" else "#D55E00"))
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        px2, py2 = -uy, ux
        sz = 8.0
        line_attrs = {
            "x1": f"{x1:.1f}", "y1": f"{y1:.1f}",
            "stroke": col, "stroke-width": "2.0",
        }
        if ar.get("dash"):
            line_attrs["stroke-dasharray"] = str(ar["dash"])
        if akind == "inhibit":
            line_attrs["x2"] = f"{x2:.1f}"
            line_attrs["y2"] = f"{y2:.1f}"
            ET.SubElement(g, f"{NS}line", line_attrs)
            ET.SubElement(g, f"{NS}line", {
                "x1": f"{x2+px2*sz*0.65:.1f}", "y1": f"{y2+py2*sz*0.65:.1f}",
                "x2": f"{x2-px2*sz*0.65:.1f}", "y2": f"{y2-py2*sz*0.65:.1f}",
                "stroke": col, "stroke-width": "2.4", "stroke-linecap": "round",
            })
        else:
            bx, by = x2 - ux * sz, y2 - uy * sz
            line_attrs["x2"] = f"{bx:.1f}"
            line_attrs["y2"] = f"{by:.1f}"
            ET.SubElement(g, f"{NS}line", line_attrs)
            pts = (f"{x2:.1f},{y2:.1f} {bx+px2*sz*0.45:.1f},{by+py2*sz*0.45:.1f} "
                   f"{bx-px2*sz*0.45:.1f},{by-py2*sz*0.45:.1f}")
            ET.SubElement(g, f"{NS}polygon", {"points": pts, "fill": col})
        if ar.get("label"):
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{x1:.1f}", "y": f"{y1-6:.1f}", "font-family": FONT,
                "font-size": "11.5", "font-weight": "bold", "fill": col,
            })
            t.text = str(ar["label"])
        added.append(f"overlay arrow[{akind}] ({x1:.0f},{y1:.0f})->({x2:.0f},{y2:.0f})")

    ft = spec.get("footer")
    if isinstance(ft, dict):
        src = str(ft.get("sources", "")).strip()
        ver = str(ft.get("version", "")).strip()
        fy = vy0 + vh - 12
        if src:
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{vx0+18:.1f}", "y": f"{fy:.1f}", "font-family": FONT,
                "font-size": "11", "fill": MUT,
            })
            t.text = "Sources: " + src
            added.append("overlay footer sources")
        if ver:
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{vx0+vw-18:.1f}", "y": f"{fy:.1f}", "font-family": FONT,
                "font-size": "11", "fill": MUT, "text-anchor": "end",
            })
            t.text = ver
            added.append(f"overlay footer version '{ver}'")

    sbr = spec.get("sig_brackets") or []
    for sb_it in sbr:
        if not isinstance(sb_it, dict):
            continue
        x1, x2, y = float(sb_it.get("x1", vx0 + 100)), float(sb_it.get("x2", vx0 + 200)), float(sb_it.get("y", vy0 + 80))
        col = str(sb_it.get("color", INK))
        ET.SubElement(g, f"{NS}line", {"x1": f"{x1:.1f}", "y1": f"{y+6:.1f}", "x2": f"{x1:.1f}", "y2": f"{y:.1f}", "stroke": col, "stroke-width": "1.3"})
        ET.SubElement(g, f"{NS}line", {"x1": f"{x1:.1f}", "y1": f"{y:.1f}", "x2": f"{x2:.1f}", "y2": f"{y:.1f}", "stroke": col, "stroke-width": "1.3"})
        ET.SubElement(g, f"{NS}line", {"x1": f"{x2:.1f}", "y1": f"{y:.1f}", "x2": f"{x2:.1f}", "y2": f"{y+6:.1f}", "stroke": col, "stroke-width": "1.3"})
        lab = str(sb_it.get("label", "*"))
        t = ET.SubElement(g, f"{NS}text", {
            "x": f"{(x1+x2)/2:.1f}", "y": f"{y-4:.1f}", "font-family": FONT,
            "font-size": "12", "font-weight": "bold", "fill": col, "text-anchor": "middle",
        })
        t.text = lab
        added.append(f"overlay sig_bracket '{lab}' ({x1:.0f}..{x2:.0f})")

    cb = spec.get("callout_box")
    if isinstance(cb, dict):
        cx = float(cb.get("x", vx0 + 24))
        cy = float(cb.get("y", vy0 + 24))
        cw_box = float(cb.get("w", 240))
        acc = str(cb.get("color", "#0072B2"))
        title = str(cb.get("title", "")).strip()
        body = str(cb.get("text", cb.get("body", ""))).strip()
        t_lns = wrap_text(title, 12.0, cw_box - 20) if title else []
        b_lns = wrap_text(body, 11.0, cw_box - 20) if body else []
        bh_box = max(32.0, 14 + len(t_lns) * 15.5 + (4 if t_lns and b_lns else 0) + len(b_lns) * 14.5)
        ET.SubElement(g, f"{NS}rect", {
            "x": f"{cx:.1f}", "y": f"{cy:.1f}", "width": f"{cw_box:.1f}", "height": f"{bh_box:.1f}",
            "rx": "6", "fill": "#FFFFFF", "fill-opacity": "0.95", "stroke": acc, "stroke-width": "1.2",
        })
        ET.SubElement(g, f"{NS}rect", {
            "x": f"{cx:.1f}", "y": f"{cy+4:.1f}", "width": "4", "height": f"{bh_box-8:.1f}",
            "rx": "2", "fill": acc,
        })
        ty = cy + 16
        for ln in t_lns:
            t = ET.SubElement(g, f"{NS}text", {"x": f"{cx+12:.1f}", "y": f"{ty:.1f}", "font-family": FONT, "font-size": "12", "font-weight": "bold", "fill": INK})
            t.text = ln
            ty += 15.5
        if t_lns and b_lns:
            ty += 3
        for ln in b_lns:
            t = ET.SubElement(g, f"{NS}text", {"x": f"{cx+12:.1f}", "y": f"{ty:.1f}", "font-family": FONT, "font-size": "11", "fill": INK})
            t.text = ln
            ty += 14.5
        added.append(f"overlay callout_box '{title or body[:24]}'")

    notes = spec.get("notes") or ([spec["note"]] if spec.get("note") else [])
    for nt in notes:
        if not isinstance(nt, dict):
            continue
        nx, ny = float(nt.get("x", vx0 + 30)), float(nt.get("y", vy0 + 30))
        txt = str(nt.get("text", ""))
        t = ET.SubElement(g, f"{NS}text", {
            "x": f"{nx:.1f}", "y": f"{ny:.1f}", "font-family": FONT,
            "font-size": str(nt.get("font_size", 12)),
            "fill": str(nt.get("fill", INK)),
            "font-weight": str(nt.get("weight", "normal")),
        })
        t.text = txt
        added.append(f"overlay note '{txt[:40]}'")
    for bd in (spec.get("panel_badges") or []):
        if not isinstance(bd, dict):
            continue
        bx, by = float(bd.get("x", vx0 + 16)), float(bd.get("y", vy0 + 28))
        lbl = str(bd.get("label", "a"))
        col = str(bd.get("color", "#0F172A"))
        bg = bd.get("bg")
        if bg:
            bw = max(20.0, text_width(lbl, 13.0) + 10.0)
            ET.SubElement(g, f"{NS}rect", {
                "x": f"{bx:.1f}", "y": f"{by-16:.1f}", "width": f"{bw:.1f}", "height": "22",
                "rx": "4", "fill": str(bg),
            })
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{bx+bw/2:.1f}", "y": f"{by-1:.1f}", "font-family": FONT,
                "font-size": "13", "font-weight": "bold", "fill": "#FFFFFF", "text-anchor": "middle",
            })
        else:
            t = ET.SubElement(g, f"{NS}text", {
                "x": f"{bx:.1f}", "y": f"{by:.1f}", "font-family": FONT,
                "font-size": str(bd.get("font_size", 16)), "font-weight": "bold", "fill": col,
            })
        t.text = lbl
        added.append(f"overlay panel_badge '{lbl}' at ({bx:.0f},{by:.0f})")
    return added


def apply_edits(root, edits: list[dict], vb: tuple[float, float, float, float],
                deleted_ids_out: set | None = None) -> tuple[list[str], list[str]]:
    changes, errors = [], []
    text_els = [el for el in root.iter() if _strip(el.tag) == "text"]
    id_map = {el.get("id"): el for el in root.iter() if el.get("id")}
    label_map = {}
    for el in root.iter():
        il = el.get("{http://www.inkscape.org/namespaces/inkscape}label") or el.get("data-name")
        if il and il not in label_map:
            label_map[il] = el

    def _resolve(key):
        if not key:
            return None
        ks = str(key)
        return id_map.get(ks) if ks in id_map else label_map.get(ks)

    for ei, op in enumerate(edits):
        kind = op.get("op", "replace_text")
        if kind == "replace_text":
            old_s = str(op.get("old", "")).strip()
            new_s = str(op.get("new", ""))
            allow_all = bool(op.get("all", False))
            use_re = bool(op.get("regex", False))
            if op.get("id") and _resolve(op["id"]) is not None:
                pool = [_resolve(op["id"])]
            elif op.get("layer"):
                lroot = _resolve(op["layer"])
                if lroot is None:
                    errors.append(f"edit[{ei}]: layer '{op['layer']}' not found")
                    continue
                pool = [el for el in lroot.iter() if _strip(el.tag) == "text"]
            else:
                pool = text_els
            if use_re:
                pat = re.compile(old_s)
                hits = [el for el in pool if pat.search(_full_text(el))]
            else:
                exact = [el for el in pool if _full_text(el).strip() == old_s]
                hits = exact or [el for el in pool if old_s in _full_text(el)]
                if not hits:
                    old_n = _norm_ws_dash(old_s)
                    hits = [el for el in pool if old_n in _norm_ws_dash(_full_text(el))]
            if not hits:
                errors.append(f"edit[{ei}]: text not found: '{old_s}'")
                continue
            if len(hits) > 1 and not allow_all:
                errors.append(f"edit[{ei}]: ambiguous ({len(hits)} hits) for '{old_s}'; pass all:true or target by layer/index/id")
                continue
            cnt = 0
            for el in hits:
                changed_el = False
                if use_re:
                    prev_t = _full_text(el)
                    repl_t = re.sub(old_s, new_s, prev_t, count=0 if allow_all else 1)
                    if repl_t != prev_t:
                        _set_el_text(el, repl_t)
                        changed_el = True
                elif _replace_el_text(el, old_s, new_s):
                    changed_el = True
                if changed_el:
                    for st_k, svg_k in (("font_size", "font-size"), ("fill", "fill"), ("font_weight", "font-weight")):
                        if op.get(st_k) is not None:
                            _set_eff_attr(el, svg_k, str(op[st_k]))
                    cnt += 1
            changes.append(f"replace_text ({cnt}x): '{old_s}' -> '{new_s}'")

        elif kind in ("set_text_by_id", "set_text"):
            target = _resolve(op.get("id")) if op.get("id") else None
            if target is not None and _strip(target.tag) == "g":
                t_desc = [ch for ch in target.iter() if _strip(ch.tag) == "text"]
                if len(t_desc) == 1:
                    target = t_desc[0]
            if target is None or _strip(target.tag) != "text":
                errors.append(f"edit[{ei}]: text id '{op.get('id')}' not found")
                continue
            prev = _full_text(target).strip()
            _set_el_text(target, str(op.get("new", "")))
            for st_k, svg_k in (("font_size", "font-size"), ("fill", "fill"), ("font_weight", "font-weight")):
                if op.get(st_k) is not None:
                    _set_eff_attr(target, svg_k, str(op[st_k]))
            changes.append(f"set_text_by_id[{op.get('id')}]: '{prev}' -> '{op.get('new', '')}'")

        elif kind in ("add_text", "insert_text"):
            txt_val = str(op.get("text", op.get("new", ""))).strip()
            if not txt_val:
                errors.append(f"edit[{ei}]: add_text missing 'text'")
                continue
            parent = _resolve(op.get("layer")) if op.get("layer") else None
            if parent is None:
                parent = id_map.get("layer-edits")
                if parent is None:
                    parent = ET.SubElement(root, f"{NS}g", {"id": "layer-edits"})
                    id_map["layer-edits"] = parent
            t_attrs = {
                "x": str(float(op.get("x", 20))),
                "y": str(float(op.get("y", 20))),
                "font-family": str(op.get("font_family", FONT)),
                "font-size": str(op.get("font_size", 12)),
                "fill": str(op.get("fill", "#0F172A")),
            }
            if op.get("anchor") or op.get("text_anchor"):
                t_attrs["text-anchor"] = str(op.get("anchor") or op.get("text_anchor"))
            if op.get("font_weight") or op.get("bold"):
                t_attrs["font-weight"] = str(op.get("font_weight") or "bold")
            if op.get("id"):
                t_attrs["id"] = str(op["id"])
            tel = ET.SubElement(parent, f"{NS}text", t_attrs)
            tel.text = txt_val
            if op.get("id"):
                id_map[str(op["id"])] = tel
            text_els.append(tel)
            changes.append(f"add_text '{txt_val[:40]}' at ({t_attrs['x']},{t_attrs['y']})")

        elif kind == "set_text_by_index":
            idx = int(op.get("index", -1))
            if 0 <= idx < len(text_els):
                prev = _full_text(text_els[idx]).strip()
                _set_el_text(text_els[idx], str(op.get("new", "")))
                for st_k, svg_k in (("font_size", "font-size"), ("fill", "fill"), ("font_weight", "font-weight")):
                    if op.get(st_k) is not None:
                        _set_eff_attr(text_els[idx], svg_k, str(op[st_k]))
                changes.append(f"set_text[{idx}]: '{prev}' -> '{op.get('new', '')}'")
            else:
                errors.append(f"edit[{ei}]: text index {idx} out of range (0..{len(text_els)-1})")

        elif kind == "set_attr":
            target = None
            if op.get("id") and _resolve(op["id"]) is not None:
                target = _resolve(op["id"])
            elif op.get("index") is not None:
                idx = int(op["index"])
                if 0 <= idx < len(text_els):
                    target = text_els[idx]
            elif op.get("text"):
                matches = [el for el in text_els if op["text"].strip() == _full_text(el).strip()]
                if len(matches) == 1:
                    target = matches[0]
            if target is None:
                errors.append(f"edit[{ei}]: set_attr target not uniquely found")
                continue
            attr = str(op["attr"])
            val = str(op["value"])
            prev = _set_eff_attr(target, attr, val)
            changes.append(f"set_attr {target.get('id') or _strip(target.tag)}.{attr}: '{prev}' -> '{val}'")

        elif kind == "replace_color":
            old_c = _norm_color(str(op.get("old", "")))
            new_c = str(op.get("new", ""))
            attrs = op.get("attrs") or ["fill", "stroke"]
            scope_root = _resolve(op["layer"]) if op.get("layer") else root
            if scope_root is None:
                errors.append(f"edit[{ei}]: layer '{op.get('layer')}' not found")
                continue
            cnt = 0
            css_pat = re.compile(
                r'((?:' + "|".join(re.escape(a) for a in attrs) + r')\s*:\s*)(#[0-9a-fA-F]{3,6}|rgba?\([^)]+\)|[a-zA-Z]+)',
                re.IGNORECASE,
            )
            for el in scope_root.iter():
                if _strip(el.tag) == "style" and el.text:
                    def _sub_css(m):
                        nonlocal cnt
                        if _norm_color(m.group(2)) == old_c:
                            cnt += 1
                            return m.group(1) + new_c
                        return m.group(0)
                    el.text = css_pat.sub(_sub_css, el.text)
                for a_name in attrs:
                    cur = _get_eff_attr(el, a_name)
                    if cur and _norm_color(cur) == old_c:
                        _set_eff_attr(el, a_name, new_c)
                        cnt += 1
            if cnt == 0:
                errors.append(f"edit[{ei}]: color '{op.get('old')}' not found")
            else:
                changes.append(f"replace_color ({cnt}x): '{op.get('old')}' -> '{new_c}'")

        elif kind == "translate":
            target = _resolve(op.get("id")) if op.get("id") else None
            if target is None:
                errors.append(f"edit[{ei}]: translate id '{op.get('id')}' not found")
                continue
            dx, dy = float(op.get("dx", 0)), float(op.get("dy", 0))
            prev = (target.get("transform") or "").strip()
            tr = f"translate({dx:g},{dy:g})"
            target.set("transform", f"{prev} {tr}".strip() if prev else tr)
            changes.append(f"translate {op.get('id')}: dx={dx:g}, dy={dy:g}")

        elif kind == "hide":
            target = _resolve(op.get("id")) if op.get("id") else None
            if target is None:
                errors.append(f"edit[{ei}]: hide id '{op.get('id')}' not found")
                continue
            _set_eff_attr(target, "display", "none")
            changes.append(f"hide {op.get('id')}")

        elif kind == "delete":
            target = _resolve(op.get("id")) if op.get("id") else None
            if target is None:
                errors.append(f"edit[{ei}]: delete id '{op.get('id')}' not found")
                continue
            parent = next((p for p in root.iter() if target in list(p)), None)
            if parent is None:
                errors.append(f"edit[{ei}]: parent not found for delete '{op.get('id')}'")
                continue
            if deleted_ids_out is not None:
                for sub in target.iter():
                    if sub.get("id"):
                        deleted_ids_out.add(sub.get("id"))
            parent.remove(target)
            if target.get("id"):
                id_map.pop(target.get("id"), None)
            changes.append(f"delete {op.get('id')}")

        elif kind == "scale_rect":
            target = _resolve(op.get("id")) if op.get("id") else None
            if target is not None and _strip(target.tag) == "g":
                sh_ch = [ch for ch in target if _strip(ch.tag) in ("rect", "path", "polygon")]
                if len(sh_ch) == 1:
                    target = sh_ch[0]
            t_tag = _strip(target.tag) if target is not None else ""
            rb = _rect_geom_from_el(target) if target is not None else None
            if target is None or rb is None:
                errors.append(f"edit[{ei}]: scale_rect target rect/rect-like path '{op.get('id')}' not found")
                continue
            rx, ry, rw, rh = rb
            nx, ny, nw, nh = rx, ry, rw, rh
            anchor = str(op.get("anchor", "bottom")).lower()
            if "height" in op:
                nh = float(op["height"])
                if anchor == "bottom":
                    ny = ry + rh - nh
                msg_sc = f"scale_rect {op.get('id')} ({t_tag}): height {rh:g} -> {nh:g} (anchor={anchor})"
            elif "width" in op:
                nw = float(op["width"])
                if anchor == "right":
                    nx = rx + rw - nw
                msg_sc = f"scale_rect {op.get('id')} ({t_tag}): width {rw:g} -> {nw:g} (anchor={anchor})"
            else:
                errors.append(f"edit[{ei}]: scale_rect requires 'height' or 'width'")
                continue
            if t_tag == "rect":
                target.set("x", f"{nx:g}")
                target.set("y", f"{ny:g}")
                target.set("width", f"{nw:g}")
                target.set("height", f"{nh:g}")
            elif t_tag == "polygon":
                target.set("points", f"{nx:g},{ny:g} {nx+nw:g},{ny:g} {nx+nw:g},{ny+nh:g} {nx:g},{ny+nh:g}")
            elif t_tag == "path":
                target.set("d", f"M {nx:g} {ny:g} L {nx+nw:g} {ny:g} L {nx+nw:g} {ny+nh:g} L {nx:g} {ny+nh:g} Z")
            changes.append(msg_sc)

        elif kind == "insert_svg":
            frag = str(op.get("xml", "")).strip()
            if not frag:
                errors.append(f"edit[{ei}]: insert_svg missing 'xml'")
                continue
            try:
                wrapper = ET.fromstring(f'<g xmlns="{SVG_NS}">{frag}</g>')
            except ET.ParseError as exc:
                errors.append(f"edit[{ei}]: insert_svg XML parse error: {exc}")
                continue
            parent = id_map.get(op["parent_id"]) if op.get("parent_id") else None
            if parent is None:
                parent = id_map.get("layer-ga-edits")
                if parent is None:
                    parent = ET.SubElement(root, f"{NS}g", {
                        "id": "layer-ga-edits",
                        "{http://www.inkscape.org/namespaces/inkscape}label": "GA edits",
                    })
                    id_map["layer-ga-edits"] = parent
            for child in list(wrapper):
                parent.append(child)
                if child.get("id"):
                    id_map[child.get("id")] = child
            changes.append(f"insert_svg ({len(wrapper)} node(s)) into {parent.get('id','root')}")

        elif kind == "restyle_class":
            cls_name = str(op.get("class", "")).lstrip(".").strip()
            attr = str(op.get("attr", "")).strip()
            val = str(op.get("value", "")).strip()
            if not (cls_name and attr):
                errors.append(f"edit[{ei}]: restyle_class requires 'class' and 'attr'")
                continue
            updated_css = 0
            rule_pat = re.compile(rf"(\.{re.escape(cls_name)}\s*\{{)([^}}]*)(\}})")
            prop_pat = re.compile(rf"({re.escape(attr)}\s*:\s*)([^;}}]+)", re.IGNORECASE)
            for el in root.iter():
                if _strip(el.tag) == "style" and el.text and f".{cls_name}" in el.text:
                    def _upd_rule(m):
                        nonlocal updated_css
                        body = m.group(2)
                        if prop_pat.search(body):
                            body = prop_pat.sub(lambda pm: pm.group(1) + val, body, count=1)
                        else:
                            sep = "" if (not body.strip() or body.strip().endswith(";")) else ";"
                            body = body + f"{sep}{attr}:{val};"
                        updated_css += 1
                        return m.group(1) + body + m.group(3)
                    el.text = rule_pat.sub(_upd_rule, el.text)
            if updated_css == 0:
                errors.append(f"edit[{ei}]: CSS class '.{cls_name}' not found in <style>")
            else:
                changes.append(f"restyle_class .{cls_name}.{attr} -> '{val}'")

        elif kind == "expand_canvas":
            pad_t = float(op.get("top", 0))
            pad_b = float(op.get("bottom", 0))
            pad_l = float(op.get("left", 0))
            pad_r = float(op.get("right", 0))
            vx0, vy0, vw, vh = vb
            nvx0, nvy0 = vx0 - pad_l, vy0 - pad_t
            nvw, nvh = max(10.0, vw + pad_l + pad_r), max(10.0, vh + pad_t + pad_b)
            vb = (nvx0, nvy0, nvw, nvh)
            root.set("viewBox", f"{nvx0:g} {nvy0:g} {nvw:g} {nvh:g}")
            root.set("width", f"{nvw:g}")
            root.set("height", f"{nvh:g}")
            bg_col = op.get("bg", "#FFFFFF")
            if bg_col:
                bg_rect = ET.Element(f"{NS}rect", {
                    "id": "ga-expanded-bg",
                    "x": f"{nvx0:g}", "y": f"{nvy0:g}",
                    "width": f"{nvw:g}", "height": f"{nvh:g}",
                    "fill": str(bg_col),
                })
                ins_i = 0
                for ci, ch in enumerate(list(root)):
                    if _strip(ch.tag) in ("defs", "style", "metadata", "title", "desc"):
                        ins_i = ci + 1
                    else:
                        break
                root.insert(ins_i, bg_rect)
            changes.append(f"expand_canvas: viewBox -> '{nvx0:g} {nvy0:g} {nvw:g} {nvh:g}'")

        elif kind == "add_overlay":
            added = _add_overlay(root, op, vb)
            changes.extend(added)
        else:
            errors.append(f"edit[{ei}]: unknown op '{kind}'")
    return changes, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--inspect", action="store_true", help="print SVG structure JSON")
    ap.add_argument("--find", default=None, help="with --inspect, filter text_nodes & named_shapes by substring")
    ap.add_argument("--out", default=None)
    ap.add_argument("--old", default=None)
    ap.add_argument("--new", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--edits", default=None, help="JSON file with list of edit ops")
    ap.add_argument("--deliver", default=None,
                    help="one-shot Path B: render PNG+PDF, external audit, copy to DIR, write result.json if --case set")
    ap.add_argument("--case", default=None, help="/input/case.json path for writing result.json")
    ap.add_argument("--report", default=None, help="optional report.json path")
    a = ap.parse_args()
    svg_path = Path(a.svg)

    if a.inspect:
        print(json.dumps(inspect_svg(svg_path, query=a.find), ensure_ascii=False, indent=1))
        return 0

    raw = svg_path.read_text(encoding="utf-8")
    src_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    vb = parse_svg_viewbox(raw)
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
    ET.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("cc", "http://creativecommons.org/ns#")
    ET.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    tree = ET.ElementTree(ET.fromstring(raw))
    root = tree.getroot()
    dom_before = sum(1 for _ in root.iter())
    layers_before = [el.get("id") for el in root.iter() if _strip(el.tag) == "g" and el.get("id")]

    if a.edits:
        edits = json.loads(Path(a.edits).read_text(encoding="utf-8"))
        if isinstance(edits, dict):
            edits = edits.get("edits") or edits.get("operations") or edits.get("ops") or [edits]
    elif a.old is not None and a.new is not None:
        edits = [{"op": "replace_text", "old": a.old, "new": a.new, "all": a.all}]
    else:
        print(json.dumps({"error": "specify --inspect, --edits FILE, or --old/--new"}))
        return 1

    deleted_ids: set[str] = set()
    changes, errors = apply_edits(root, edits, vb, deleted_ids_out=deleted_ids)
    if errors and not changes:
        print(json.dumps({"replaced": 0, "changes": changes, "errors": errors}, ensure_ascii=False))
        return 2 if any("ambiguous" in e for e in errors) else 1

    if a.out:
        out_path = Path(a.out)
    elif str(svg_path.resolve()).startswith("/input/") and Path("/app/work").is_dir():
        out_path = Path("/app/work") / svg_path.name
    else:
        out_path = svg_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="unicode", xml_declaration=False)
    out_raw = out_path.read_text(encoding="utf-8")
    out_sha = hashlib.sha256(out_raw.encode("utf-8")).hexdigest()[:16]
    dom_after = sum(1 for _ in root.iter())
    layers_after = [el.get("id") for el in root.iter() if _strip(el.tag) == "g" and el.get("id")]
    preserved = all(ly in layers_after for ly in layers_before if ly not in deleted_ids)
    edit_rep = {
        "source_svg": str(svg_path.name),
        "edited_svg": str(out_path.name),
        "source_sha256_16": src_sha,
        "edited_sha256_16": out_sha,
        "dom_elements_before": dom_before,
        "dom_elements_after": dom_after,
        "layers_before": layers_before,
        "layers_after": layers_after,
        "untouched_layers_preserved": preserved,
        "changes": changes,
        "errors": errors,
    }
    try:
        (out_path.parent / "_edit_report.json").write_text(
            json.dumps(edit_rep, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    out_summary = {"replaced": len(changes), "changes": changes,
                   "errors": errors, "out": str(out_path),
                   "untouched_layers_preserved": preserved}
    if a.deliver and not errors:
        from ga_check import audit as run_audit
        from ga_pipeline import render, verify_exports
        work_dir = out_path.parent.resolve()
        png = work_dir / f"{out_path.stem}.png"
        pdf = work_dir / f"{out_path.stem}.pdf"
        rlog = []
        eng = render(out_path, png, pdf, rlog)
        cw, ch = parse_svg_dims(out_raw)
        brep = {"svg": str(out_path), "canvas": [cw, ch], "render_engine": eng, "render_log": rlog}
        ec = verify_exports(png, pdf, brep) if png.exists() else {}
        br_path = work_dir / "_build_report.json"
        br_path.write_text(json.dumps(brep, ensure_ascii=False, indent=1), encoding="utf-8")
        ck = run_audit(out_path, brief=None, report=None, external=True)
        (work_dir / "_check_report.json").write_text(
            json.dumps(ck, ensure_ascii=False, indent=1), encoding="utf-8")
        deliv = Path(a.deliver).resolve()
        deliv.mkdir(parents=True, exist_ok=True)
        copied = []
        for fsrc in (out_path, png, pdf):
            if fsrc.exists():
                dst = deliv / fsrc.name
                if fsrc.resolve() != dst.resolve():
                    shutil.copy2(fsrc, dst)
                copied.append(fsrc.name)
        out_summary["engine"] = eng
        out_summary["canvas"] = [cw, ch]
        out_summary["audit_pass"] = ck["pass"]
        out_summary["audit_warnings"] = ck["warnings"]
        out_summary["delivered"] = copied
        if ec:
            p_ec = ec.get("png") or {}
            f_ec = ec.get("pdf") or {}
            out_summary["export_check"] = {
                "dpi": p_ec.get("dpi"),
                "dpi_ok": p_ec.get("dpi_ok"),
                "ink_ratio": p_ec.get("ink_ratio"),
                "edge_clip_px": p_ec.get("edge_clip_px"),
                "non_blank": p_ec.get("non_blank"),
                "searchable_text": f_ec.get("searchable_text"),
            }
        if a.case and Path(a.case).exists():
            from ga_result import build_result
            out_summary["result"] = build_result(
                case_path=Path(a.case),
                out_path=deliv / "result.json",
                outdir=deliv,
                work=work_dir,
                report_path=Path(a.report) if a.report else None,
                build_report_path=br_path,
                main_svg=out_path.name,
            )
    print(json.dumps(out_summary, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
