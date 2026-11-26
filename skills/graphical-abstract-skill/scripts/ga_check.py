#!/usr/bin/env python3
"""SVG audit: bounds, panel containment, node collisions, text overlap/occlusion,
font floor, colorblind/luminance contrast, and optional provenance coverage.

Usage: python3 ga_check.py --svg file.svg [--brief brief.json] [--report report.json]
Prints JSON report; exit 1 on errors or warnings, 0 on clean pass.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gaconfig import H, SERIES, W, lum_delta, luminance, parse_svg_viewbox  # noqa: E402
from textmetrics import SAFETY, text_width  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"
FLOOR = 10.0
_SKIP_CONTAINERS = {
    "defs", "clipPath", "mask", "marker", "pattern", "symbol",
    "metadata", "style", "title", "desc",
}
# Machado et al. 2009 deuteranopia (severity 1.0)
_DEUT = ((0.367322, 0.860646, -0.227968),
         (0.280085, 0.672501, 0.047414),
         (-0.011820, 0.042940, 0.968881))


def _sim_lum(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    sim = [max(0.0, min(1.0, sum(m * c for m, c in zip(row, lin)))) for row in _DEUT]
    return 0.2126 * sim[0] + 0.7152 * sim[1] + 0.0722 * sim[2]


def _strip(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _style_prop(el, prop: str) -> str:
    st = el.attrib.get("style", "")
    if st:
        for chunk in st.split(";"):
            if ":" in chunk:
                k, v = chunk.split(":", 1)
                if k.strip().lower() == prop:
                    return v.strip()
    return (el.attrib.get(prop) or "").strip()


def _parse_fs(val, default=12.0) -> float:
    if val is None or val == "":
        return default
    m = re.match(r"^\s*([\d.]+)", str(val))
    return float(m.group(1)) if m else default


def _parse_opacity(val, default=1.0) -> float:
    if val is None or val == "":
        return default
    s = str(val).strip()
    try:
        if s.endswith("%"):
            return max(0.0, min(1.0, float(s[:-1]) / 100.0))
        return max(0.0, min(1.0, float(s)))
    except ValueError:
        return default


def _bbox(el):
    t = _strip(el.tag)
    a = el.attrib
    if t == "text":
        try:
            xs_raw, ys_raw = a.get("x"), a.get("y")
            if xs_raw is None or ys_raw is None:
                for child in el:
                    if _strip(child.tag) == "tspan":
                        xs_raw = xs_raw if xs_raw is not None else child.attrib.get("x")
                        ys_raw = ys_raw if ys_raw is not None else child.attrib.get("y")
                        if xs_raw is not None and ys_raw is not None:
                            break
            x = float(str(xs_raw or 0).split()[0])
            y = float(str(ys_raw or 0).split()[0])
            fs = _parse_fs(_style_prop(el, "font-size") or 12)
        except (ValueError, IndexError):
            return None
        s = "".join(el.itertext())
        w = text_width(s, fs)
        anchor = a.get("text-anchor", "start")
        x0 = x - w if anchor == "end" else x - w / 2 if anchor == "middle" else x
        rot = a.get("transform", "")
        if "rotate" in rot:
            try:
                ang = float(rot.split("rotate")[1].strip("( ").split(",")[0].split(" ")[0])
            except Exception:
                ang = 0.0
            if abs(abs(ang) - 90) < 5:
                return (x - fs * 0.85, y - w / 2, x + fs * 0.35, y + w / 2)
            if abs(ang) > 5:
                rad = math.radians(ang)
                ca, sa = math.cos(rad), math.sin(rad)
                # Use tight core box around rotated baseline to avoid diagonal false-positive overlaps
                corners = [(x0, y - fs * 0.45), (x0 + w, y - fs * 0.45),
                           (x0 + w, y + fs * 0.2), (x0, y + fs * 0.2)]
                rxs = [x + (cx - x) * ca - (cy - y) * sa for cx, cy in corners]
                rys = [y + (cx - x) * sa + (cy - y) * ca for cx, cy in corners]
                return (min(rxs), min(rys), max(rxs), max(rys))
        return (x0, y - fs * 0.85, x0 + w, y + fs * 0.3)
    if t == "rect":
        try:
            x, y = float(a.get("x", 0)), float(a.get("y", 0))
            return (x, y, x + float(a.get("width", 0)), y + float(a.get("height", 0)))
        except ValueError:
            return None
    if t == "line":
        try:
            xs = [float(a.get("x1", 0)), float(a.get("x2", 0))]
            ys = [float(a.get("y1", 0)), float(a.get("y2", 0))]
            return (min(xs), min(ys), max(xs), max(ys))
        except ValueError:
            return None
    if t in ("circle", "ellipse"):
        try:
            cx, cy = float(a.get("cx", 0)), float(a.get("cy", 0))
            rx = float(a.get("r", a.get("rx", 3)))
            ry = float(a.get("r", a.get("ry", rx)))
            return (cx - rx, cy - ry, cx + rx, cy + ry)
        except ValueError:
            return None
    if t in ("polygon", "polyline"):
        pts = [p.split(",") for p in a.get("points", "").split() if "," in p]
        if not pts:
            return None
        try:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            return (min(xs), min(ys), max(xs), max(ys))
        except ValueError:
            return None
    return None


def _text_obb(el):
    """Return 4 corners [(x,y),...] of a rotated <text> element, or None if unrotated/axis-aligned."""
    a = el.attrib
    rot = a.get("transform", "")
    if "rotate" not in rot:
        return None
    try:
        ang = float(rot.split("rotate")[1].strip("( ").split(",")[0].split(" ")[0])
        if abs(ang) < 5 or abs(abs(ang) - 90) < 5:
            return None
        x = float(str(a.get("x", 0)).split()[0])
        y = float(str(a.get("y", 0)).split()[0])
        fs = _parse_fs(_style_prop(el, "font-size") or 12)
        w = text_width("".join(el.itertext()), fs)
        anchor = a.get("text-anchor", "start")
        x0 = x - w if anchor == "end" else x - w / 2 if anchor == "middle" else x
        rad = math.radians(ang)
        ca, sa = math.cos(rad), math.sin(rad)
        corners = [(x0, y - fs * 0.78), (x0 + w, y - fs * 0.78),
                   (x0 + w, y + fs * 0.25), (x0, y + fs * 0.25)]
        return [(x + (cx - x) * ca - (cy - y) * sa, y + (cx - x) * sa + (cy - y) * ca)
                for cx, cy in corners]
    except Exception:
        return None


def _obb_separated(pa, pb) -> bool:
    """Exact 2D Separating Axis Theorem check for two 4-vertex convex polygons."""
    for poly in (pa, pb):
        for k in range(4):
            x1, y1 = poly[k]
            x2, y2 = poly[(k + 1) % 4]
            nx, ny = -(y2 - y1), (x2 - x1)
            if abs(nx) < 1e-9 and abs(ny) < 1e-9:
                continue
            da = [px * nx + py * ny for px, py in pa]
            db = [px * nx + py * ny for px, py in pb]
            if max(da) <= min(db) + 1e-6 or max(db) <= min(da) + 1e-6:
                return True
    return False


def _inter(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def audit(svg_path: Path, brief=None, report=None, external: bool = False):
    raw = svg_path.read_text(encoding="utf-8")
    root = ET.fromstring(raw)
    vx0, vy0, Wv, Hv = parse_svg_viewbox(raw, default=(0.0, 0.0, float(W), float(H)))
    texts, others, errors, warnings = [], [], [], []
    doc_order = []
    mech_nodes = []  # (panel_id, node_id, bbox)
    parent_map = {c: p for p in root.iter() for c in p}

    def _in_sci_icon(el) -> bool:
        cur = el
        while cur in parent_map:
            if cur.attrib.get("data-kind") == "sci-icon":
                return True
            cur = parent_map[cur]
        return False

    def _is_non_rendered(el) -> bool:
        cur = el
        while True:
            if _strip(cur.tag) in _SKIP_CONTAINERS:
                return True
            if _style_prop(cur, "display").lower() == "none" or _style_prop(cur, "visibility").lower() == "hidden":
                return True
            if cur not in parent_map:
                break
            cur = parent_map[cur]
        return False

    def _has_ancestor_transform(el) -> bool:
        cur = el
        while True:
            if cur.attrib.get("transform"):
                return True
            if cur not in parent_map:
                break
            cur = parent_map[cur]
        return False

    # Check stray literal '[]' serialization artifacts in layers
    for el in root.iter():
        if _strip(el.tag) == "g" and (el.text or "").strip() == "[]":
            errors.append(f"corrupt layer text '[]' in <g id='{el.get('id','')}'>")

    # Map every element to its enclosing panel box if present
    panel_boxes = {}
    for el in root.iter():
        if _strip(el.tag) == "g" and el.get("data-panel-box"):
            try:
                bx = [float(v) for v in el.get("data-panel-box").split(",")]
                if len(bx) == 4:
                    panel_boxes[el] = (el.get("id", "?"), (bx[0], bx[1], bx[0] + bx[2], bx[1] + bx[3]))
            except Exception:
                pass

    def _enclosing_panel(el):
        cur = el
        while cur in parent_map:
            cur = parent_map[cur]
            if cur in panel_boxes:
                return panel_boxes[cur]
        return None, None

    def _apply_ancestor_xform(el, bb):
        """Compose ancestor translate(...) and scale(...) transforms onto element bbox."""
        x0, y0, x1, y1 = bb
        sc_y = 1.0
        cur = el
        chain = []
        while cur in parent_map:
            cur = parent_map[cur]
            tr = cur.attrib.get("transform", "")
            if tr:
                chain.append(tr)
        for tr in chain:
            for op_m in reversed(list(re.finditer(r"(translate|scale)\s*\(([^)]+)\)", tr))):
                kind_op = op_m.group(1)
                nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", op_m.group(2))]
                if kind_op == "scale" and nums:
                    sx = nums[0]
                    sy = nums[1] if len(nums) > 1 else sx
                    x0, x1 = min(x0 * sx, x1 * sx), max(x0 * sx, x1 * sx)
                    y0, y1 = min(y0 * sy, y1 * sy), max(y0 * sy, y1 * sy)
                    sc_y *= abs(sy)
                elif kind_op == "translate" and nums:
                    tx = nums[0]
                    ty = nums[1] if len(nums) > 1 else 0.0
                    x0, x1 = x0 + tx, x1 + tx
                    y0, y1 = y0 + ty, y1 + ty
        return (x0, y0, x1, y1), sc_y

    order = 0
    WHITEISH = {"#ffffff", "#fff", "white", "none", ""}
    font_sizes = []
    fonts_declared = set()
    top_layers = [el.get("id") for el in root if _strip(el.tag) == "g" and el.get("id")]
    for el in root.iter():
        if _is_non_rendered(el):
            continue
        t = _strip(el.tag)
        bb = _bbox(el)
        if bb is None:
            continue
        bb, xform_sy = _apply_ancestor_xform(el, bb)
        order += 1
        pid, pbox = _enclosing_panel(el)
        dk = el.attrib.get("data-kind", "")

        if t == "text":
            fs = _parse_fs(_style_prop(el, "font-size") or 12) * xform_sy
            font_sizes.append(fs)
            ff = _style_prop(el, "font-family")
            if ff:
                fonts_declared.add(ff.split(",")[0].strip().strip("'\""))
            full_s = "".join(el.itertext())
            label = full_s[:40]
            maxw = float(el.attrib.get("data-maxw", 0) or 0)
            if fs < FLOOR:
                (warnings if external else errors).append(
                    f"font {fs}px < {FLOOR}px: '{label}'")
            if maxw > 0:
                wpx = text_width(full_s, fs) / SAFETY
                if wpx > maxw * 1.03:
                    errors.append(f"text overflow {wpx:.0f}>{maxw:.0f}px: '{label}'")
            if not (external and _has_ancestor_transform(el)):
                texts.append((bb, label, _text_obb(el)))
                doc_order.append(("text", bb, order, label))
            if pbox and (bb[0] < pbox[0] - 2 or bb[2] > pbox[2] + 2
                         or bb[1] < pbox[1] - 2 or bb[3] > pbox[3] + 2):
                errors.append(f"panel-overflow text '{label}' outside {pid}")
        else:
            others.append((bb, t))
            if dk == "mech-node":
                mech_nodes.append((pid or "root", el.attrib.get("data-node-id", "?"), bb))
                if pbox and (bb[0] < pbox[0] - 1 or bb[2] > pbox[2] + 1
                             or bb[1] < pbox[1] - 1 or bb[3] > pbox[3] + 1):
                    errors.append(f"panel-overflow mech-node '{el.attrib.get('data-node-id','?')}' outside {pid}")
            fill = _style_prop(el, "fill").lower()
            if t in ("rect", "polygon", "circle") and fill and \
                    fill not in WHITEISH and not fill.startswith("url") and \
                    dk not in ("mech-zone", "label-bg", "sci-icon") and not _in_sci_icon(el):
                is_light_bg = False
                if fill.startswith("#") and len(fill) in (4, 7):
                    try:
                        is_light_bg = luminance(fill) > 0.93
                    except Exception:
                        pass
                op_val = _parse_opacity(_style_prop(el, "fill-opacity"), 1.0)
                if not is_light_bg and op_val >= 0.85 and not (external and _has_ancestor_transform(el)):
                    doc_order.append(("shape", bb, order, fill))

        if not (external and _has_ancestor_transform(el)):
            if bb[0] < vx0 - 2 or bb[1] < vy0 - 2 or bb[2] > vx0 + Wv + 2 or bb[3] > vy0 + Hv + 2:
                errors.append(f"out-of-bounds {t} {tuple(round(v) for v in bb)}")

    # Check mechanism node-node collisions
    for i in range(len(mech_nodes)):
        for j in range(i + 1, len(mech_nodes)):
            if mech_nodes[i][0] != mech_nodes[j][0]:
                continue
            ar = _inter(mech_nodes[i][2], mech_nodes[j][2])
            if ar > 4:
                errors.append(
                    f"mech-node overlap ({ar:.0f}px2): '{mech_nodes[i][1]}' vs '{mech_nodes[j][1]}' in {mech_nodes[i][0]}")

    # Zero-occlusion: opaque colored shape painted AFTER text covering text
    for kind, tbb, o, label in doc_order:
        if kind != "text":
            continue
        for kind2, sbb, o2, fill2 in doc_order:
            if kind2 != "shape" or o2 <= o:
                continue
            ar = _inter(tbb, sbb)
            if ar > 30:
                warnings.append(
                    f"occlusion: text '{label}' covered {ar:.0f}px2 by fill={fill2}")

    # Text-text overlap (uses exact 2D SAT for angled/rotated labels)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            ar = _inter(texts[i][0], texts[j][0])
            if ar > 10:
                oi, oj = texts[i][2], texts[j][2]
                if oi is not None or oj is not None:
                    pi = oi or [(texts[i][0][0], texts[i][0][1]), (texts[i][0][2], texts[i][0][1]),
                                (texts[i][0][2], texts[i][0][3]), (texts[i][0][0], texts[i][0][3])]
                    pj = oj or [(texts[j][0][0], texts[j][0][1]), (texts[j][0][2], texts[j][0][1]),
                                (texts[j][0][2], texts[j][0][3]), (texts[j][0][0], texts[j][0][3])]
                    if _obb_separated(pi, pj):
                        continue
                warnings.append(
                    f"text overlap area {ar:.0f}px2: '{texts[i][1]}' vs '{texts[j][1]}'")

    # Chart palette luminance + deuteranopia contrast
    palette_used = []
    min_luma_d, min_deut_d = None, None
    advisories = []
    _CHART_TYPES_CK = {
        "chart", "plot", "graph", "figure", "data",
        "bar", "grouped_bar", "bar_chart", "hbar", "horizontal_bar", "stacked",
        "line", "line_chart", "dot", "dotplot", "strip", "stripplot", "beeswarm", "dot_mean", "swarm",
        "box", "boxplot", "box_plot", "violin",
        "scatter", "volcano", "paired", "slope", "before_after", "heatmap",
        "survival", "kaplan_meier", "km", "forest", "forest_plot",
    }

    def _is_chart_bl(bl: dict) -> bool:
        bt = str(bl.get("type", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if bt == "box":
            return bool(bl.get("series") or bl.get("xlabels"))
        return bt in _CHART_TYPES_CK

    if brief:
        def _iter_charts(blocks):
            for bl in blocks:
                if _is_chart_bl(bl):
                    yield bl
                elif str(bl.get("type", "")).lower() == "row":
                    yield from _iter_charts(bl.get("blocks", []))

        for b in brief.get("panels", []):
            for bl in _iter_charts(b.get("blocks", [])):
                ckind = str(bl.get("kind") or bl.get("type") or "").lower()
                if not bl.get("note"):
                    advisories.append(f"chart in {b.get('id','?')} lacks 'note' (add unit/n/source)")
                if ckind not in ("heatmap", "volcano", "volcano_plot") and not (bl.get("ylabel") or bl.get("xlabel")):
                    advisories.append(f"chart in {b.get('id','?')} lacks axis label with units")
                if ckind == "heatmap":
                    continue
                ns = len(bl.get("series", []))
                colors = bl.get("colors") or [SERIES[i % len(SERIES)] for i in range(max(ns, 1))]
                for c in colors:
                    if c not in palette_used:
                        palette_used.append(c)
                if ns < 2:
                    continue
                seen = set()
                for i in range(len(colors)):
                    for j in range(i + 1, len(colors)):
                        pair = tuple(sorted((colors[i], colors[j])))
                        if pair in seen:
                            continue
                        seen.add(pair)
                        d = lum_delta(colors[i], colors[j])
                        min_luma_d = d if min_luma_d is None else min(min_luma_d, d)
                        if d < 0.05:
                            warnings.append(
                                f"low luminance contrast {colors[i]} vs {colors[j]} (dL={d:.2f}) in {b.get('id','?')}")
                        dd = abs(_sim_lum(colors[i]) - _sim_lum(colors[j]))
                        min_deut_d = dd if min_deut_d is None else min(min_deut_d, dd)
                        if dd < 0.04:
                            warnings.append(
                                f"deuteranopia-risk pair {colors[i]} vs {colors[j]} (dL'={dd:.2f}) in {b.get('id','?')}")

    # Optional provenance audit against report.json (respecting brief.json inline auto-provenance)
    if isinstance(report, dict):
        has_brief_src = bool(
            brief and (brief.get("sources") or any(p.get("source") for p in brief.get("panels", [])))
        )
        if not report.get("source_map") and not has_brief_src:
            warnings.append("provenance: report.source_map is empty")
        if brief:
            charts_in_brief = []
            def _collect_c(blocks):
                for bl in blocks:
                    if _is_chart_bl(bl):
                        charts_in_brief.append(bl)
                    elif str(bl.get("type", "")).lower() == "row":
                        _collect_c(bl.get("blocks", []))
            for p in brief.get("panels", []):
                _collect_c(p.get("blocks", []))
            has_brief_dmap = any(c.get("ylabel") or c.get("xlabel") or c.get("title") or c.get("note")
                                 for c in charts_in_brief)
            if charts_in_brief and not report.get("data_mapping") and not has_brief_dmap:
                warnings.append("provenance: chart present but report.data_mapping is empty")

    font_audit = {
        "fonts_declared": sorted(fonts_declared)[:8],
        "min_font_px": round(min(font_sizes), 1) if font_sizes else None,
        "max_font_px": round(max(font_sizes), 1) if font_sizes else None,
        "editable_text_elements": len(font_sizes),
        "floor_pass": (min(font_sizes) >= FLOOR) if font_sizes else True,
    }
    color_audit = {
        "palette_hex": palette_used[:12],
        "min_luma_delta": round(min_luma_d, 3) if min_luma_d is not None else None,
        "min_deuteranopia_delta": round(min_deut_d, 3) if min_deut_d is not None else None,
        "grayscale_pass": (min_luma_d >= 0.05) if min_luma_d is not None else True,
        "deuteranopia_pass": (min_deut_d >= 0.04) if min_deut_d is not None else True,
    }
    layer_audit = {
        "layers": top_layers[:20],
        "n_panels": len(panel_boxes),
    }

    return {"pass": not errors, "errors": errors, "warnings": warnings,
            "advisories": advisories,
            "n_text": len(texts), "n_shapes": len(others),
            "n_mech_nodes": len(mech_nodes), "canvas": [Wv, Hv],
            "font_audit": font_audit, "color_audit": color_audit,
            "layer_audit": layer_audit}


_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _collect_source_numbers(data_dir: Path) -> list[float]:
    """Collect raw numbers + computed group/column mean/SD/SEM from source files."""
    nums = set()

    def _add_val(v: float):
        if math.isfinite(v):
            nums.add(v)
            av = abs(v)
            nums.add(av)
            if 1e-300 < v < 0.5:
                nums.add(round(-math.log10(v), 4))
            elif v > 1.0:
                nums.add(round(math.log10(v), 4))
            if v > 0:
                nums.add(round(math.log2(v), 4))

    def _add_text_nums(txt: str):
        for m in _NUM_RE.finditer(txt[:250000]):
            try:
                _add_val(float(m.group(0).replace(",", "")))
            except ValueError:
                pass

    def _add_row_pcts(rows: list[list[str]]):
        """Also record 100%-normalized row shares for stacked composition tables."""
        for row in rows[:200]:
            fvals = []
            for c in row:
                try:
                    fv = float(str(c).strip().rstrip("%").replace(",", ""))
                    if math.isfinite(fv) and fv >= 0:
                        fvals.append(fv)
                except ValueError:
                    pass
            if len(fvals) >= 2:
                tot = sum(fvals)
                if tot > 0:
                    nums.add(tot)
                    for fv in fvals:
                        nums.add(round(100.0 * fv / tot, 3))

    def _add_stats_dict(st: dict):
        if not isinstance(st, dict):
            return
        for sub in (st.get("subtables") or []):
            _add_stats_dict(sub)
        for key in ("group_stats", "wide_replicate_stats"):
            for grp in (st.get(key) or {}).values():
                for metrics in grp.values():
                    for mv in metrics.values():
                        if isinstance(mv, (int, float)):
                            _add_val(float(mv))
                        elif isinstance(mv, list):
                            for item in mv:
                                if isinstance(item, (int, float)):
                                    _add_val(float(item))
        for metrics in (st.get("col_stats") or {}).values():
            for mv in metrics.values():
                if isinstance(mv, (int, float)):
                    _add_val(float(mv))
                elif isinstance(mv, list):
                    for item in mv:
                        if isinstance(item, (int, float)):
                            _add_val(float(item))

    def _add_table_stats(rows: list[list[str]]):
        try:
            from ga_intake import _summarize_rows
            _add_stats_dict(_summarize_rows(rows))
        except Exception:
            pass

    if not data_dir.exists():
        return []
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file() or p.stat().st_size > 15 * 1024 * 1024:
            continue
        suf = p.suffix.lower()
        try:
            if suf in (".csv", ".tsv"):
                raw = p.read_text(encoding="utf-8", errors="ignore")
                raw_lines = raw.splitlines()
                delim = "\t" if suf == ".tsv" else ","
                parsed = [list(csv.reader([ln], delimiter=delim))[0] if ln.strip() else [] for ln in raw_lines[:2000]]
                for row in parsed:
                    for cell in row:
                        _add_text_nums(cell)
                non_empty = [ln for ln in raw_lines if ln.strip()]
                if 2 <= len(non_empty) <= 2005:
                    _add_table_stats(parsed[:2005])
                    _add_row_pcts(parsed[:200])
            elif suf in (".xlsx", ".xlsm"):
                from ga_intake import read_xlsx_sheets
                sheets = read_xlsx_sheets(p, max_sheets=40, max_rows=2005, max_cols=36)
                for srows in sheets.values():
                    for row in srows:
                        for c in row:
                            try:
                                _add_val(float(c))
                            except ValueError:
                                _add_text_nums(c)
                    _add_table_stats(srows[:2005])
                    _add_row_pcts(srows[:200])
            elif suf == ".docx":
                from ga_intake import docx_preview
                dp = docx_preview(p)
                if dp:
                    if dp.get("preview"):
                        _add_text_nums(dp["preview"])
                    for tb in (dp.get("tables") or []):
                        for row in tb:
                            for cell in row:
                                _add_text_nums(str(cell))
                        _add_table_stats(tb)
            elif suf in (".txt", ".md", ".json"):
                _add_text_nums(p.read_text(encoding="utf-8", errors="ignore"))
            elif suf == ".pdf":
                r = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True, timeout=20)
                if r.returncode == 0 and r.stdout:
                    _add_text_nums(r.stdout)
        except Exception:
            continue
    return sorted(nums)


def _audit_data_grounding(brief: dict, data_dir: Path) -> dict:
    """Verify chart numeric values in brief.json against source corpus numbers."""
    src_nums = _collect_source_numbers(data_dir)
    if not src_nums:
        return {"checked": 0, "matched": 0, "note": "no numeric source corpus found"}
    vals = []

    def _walk_blocks(pid, blocks):
        for bl in blocks:
            bt = str(bl.get("type", "")).strip().lower().replace("-", "_").replace(" ", "_")
            if bt == "row":
                _walk_blocks(pid, bl.get("blocks", []))
            elif bt in ("chart", "bar", "hbar", "stacked", "line", "dot", "strip", "stripplot",
                        "beeswarm", "dot_mean", "swarm", "box", "scatter",
                        "volcano", "paired", "slope", "before_after", "heatmap", "survival",
                        "km", "forest", "forest_plot"):
                if bl.get("kind") == "heatmap" or bt == "heatmap":
                    for row in bl.get("values", []):
                        for v in row:
                            if isinstance(v, (int, float)):
                                vals.append((pid, float(v)))
                else:
                    for row in (bl.get("pairs") or []):
                        if isinstance(row, list):
                            for v in row:
                                if isinstance(v, (int, float)):
                                    vals.append((pid, float(v)))
                    for pt in (bl.get("points") or []):
                        if isinstance(pt, dict):
                            for k in ("x", "y"):
                                if isinstance(pt.get(k), (int, float)):
                                    vals.append((pid, float(pt[k])))
                    for k in ("x", "y", "values", "ci_lo", "ci_hi", "low", "high"):
                        for v in (bl.get(k) or []):
                            if isinstance(v, (int, float)):
                                vals.append((pid, float(v)))
                    for s in bl.get("series", []):
                        for k in ("values", "data", "means", "mean", "vals", "x", "y",
                                  "q1", "q3", "low", "high", "min", "max", "ci_lo", "ci_hi", "ci_low", "ci_high"):
                            for v in (s.get(k) or []):
                                if isinstance(v, (int, float)):
                                    vals.append((pid, float(v)))
                        for pts_k in ("points", "replicates", "raw", "dots", "samples"):
                            for grp_pts in (s.get(pts_k) or []):
                                if isinstance(grp_pts, list):
                                    for pv in grp_pts:
                                        if isinstance(pv, (int, float)):
                                            vals.append((pid, float(pv)))

    for p in brief.get("panels", []):
        _walk_blocks(p.get("id", "?"), p.get("blocks", []))
    if not vals:
        return {"checked": 0, "matched": 0}
    matched = 0
    unmatched = []
    n_src = len(src_nums)
    for pid, v in vals:
        tol = max(0.015, abs(v) * 0.015)
        pos = bisect.bisect_left(src_nums, v)
        ok = (pos < n_src and abs(src_nums[pos] - v) <= tol) or (pos > 0 and abs(src_nums[pos - 1] - v) <= tol)
        if ok:
            matched += 1
        elif len(unmatched) < 10:
            unmatched.append({"panel": pid, "value": v})
    return {
        "checked": len(vals),
        "matched": matched,
        "match_rate": round(matched / len(vals), 3),
        "unmatched": unmatched,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--brief", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--data-dir", default=None,
                    help="optional input dir to cross-verify chart values against source files")
    ap.add_argument("--external", action="store_true",
                    help="audit an external source SVG (warnings do not fail exit code)")
    ap.add_argument("--allow-warnings", action="store_true")
    a = ap.parse_args()
    svg_p = Path(a.svg).resolve()
    brief = json.loads(Path(a.brief).read_text(encoding="utf-8")) if a.brief else None
    report = json.loads(Path(a.report).read_text(encoding="utf-8")) if a.report else None
    is_ext = a.external or (brief is None)
    rep = audit(svg_p, brief, report, external=is_ext)
    if a.data_dir and brief:
        dg = _audit_data_grounding(brief, Path(a.data_dir))
        rep["data_grounding"] = dg
        if dg.get("unmatched"):
            rep.setdefault("advisories", []).append(
                f"data_grounding: {len(dg['unmatched'])} value(s) not directly found in {a.data_dir}: "
                + ", ".join(f"{u['panel']}={u['value']}" for u in dg["unmatched"][:5]))
    try:
        (svg_p.parent / "_check_report.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(rep, ensure_ascii=False))
    if is_ext or a.allow_warnings:
        return 0 if rep["pass"] else 1
    return 0 if (rep["pass"] and len(rep["warnings"]) == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
