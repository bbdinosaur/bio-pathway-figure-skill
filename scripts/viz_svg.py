"""Layered SVG writer for primitive lists (pure stdlib, no dependencies).

Emits true named <g id="layer-..."> groups in clean painter's order, dominant-baseline
centering for exact SVG/PNG visual parity, multi-line <tspan> text, and semantic ids
(shape-*, label-*, edge-*, edgelabel-*) for direct editing in Inkscape/Illustrator/edit_svg.py.
"""
from __future__ import annotations
import re
from viz_style import FONT_STACK

LAYER_ORDER = [
    ("layer-backdrop",    "Backdrop"),
    ("layer-compartments","Compartments"),
    ("layer-groups",      "Groups"),
    ("layer-edges",       "Edges"),
    ("layer-nodes",       "Nodes"),
    ("layer-annotations", "Annotations"),
    ("layer-legend",      "Legend"),
    ("layer-chrome",      "Chrome"),
]

def _layer_for(p):
    if p.get("layer"):
        return p["layer"]
    role = p.get("role", "")
    if role == "bg":
        return "layer-compartments" if p.get("stroke") not in (None, "none") else "layer-backdrop"
    if role == "deco":
        return "layer-compartments"
    if role == "group":
        return "layer-groups"
    if role in ("edge", "error_bar", "bracket"):
        return "layer-edges"
    if role in ("node", "node_label", "mod", "data_point"):
        return "layer-nodes"
    if role in ("edge_label_bg", "edge_label", "annotation"):
        return "layer-annotations"
    if role.startswith("legend"):
        return "layer-legend"
    return "layer-chrome"

def _dash(p):
    if p.get("dotted"):
        return ' stroke-dasharray="2,4"'
    return ' stroke-dasharray="7,5"' if p.get("dashed") else ""

def _stroke(p):
    if p.get("stroke") in (None, "none"):
        return ""
    s = f' stroke="{p["stroke"]}" stroke-width="{p.get("stroke_w", 1)}"'
    s += ' stroke-linejoin="round" stroke-linecap="round"'
    return s + _dash(p)

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def prim_to_svg(p):
    op = p["op"]
    role = p.get("role", "")
    drole = f' data-role="{role}"' if role else ""
    eid = p.get("_id")
    if eid:
        drole += ' id="' + re.sub(r"[^A-Za-z0-9_.-]", "_", str(eid)) + '"'
    meta = p.get("_meta")
    if isinstance(meta, dict):
        for mk, mv in meta.items():
            if mv is not None and str(mv).strip() != "":
                drole += f' data-{re.sub(r"[^a-z0-9-]", "-", str(mk).lower())}="{esc(mv)}"'
    if op == "rect":
        rx = p.get("rx", 0)
        rx_attr = f' rx="{rx:.1f}" ry="{rx:.1f}"' if rx else ""
        op_attr = f' opacity="{p["opacity"]}"' if p.get("opacity", 1) != 1 else ""
        return (f'  <rect x="{p["x"]:.1f}" y="{p["y"]:.1f}" width="{p["w"]:.1f}" height="{p["h"]:.1f}"'
                f'{rx_attr} fill="{p["fill"]}"{_stroke(p)}{op_attr}{drole}/>')
    if op == "circle":
        op_attr = f' opacity="{p["opacity"]}"' if p.get("opacity", 1) != 1 else ""
        return (f'  <circle cx="{p["cx"]:.1f}" cy="{p["cy"]:.1f}" r="{p["r"]:.1f}"'
                f' fill="{p["fill"]}"{_stroke(p)}{op_attr}{drole}/>')
    if op == "ellipse":
        op_attr = f' opacity="{p["opacity"]}"' if p.get("opacity", 1) != 1 else ""
        return (f'  <ellipse cx="{p["cx"]:.1f}" cy="{p["cy"]:.1f}" rx="{p["rx"]:.1f}" ry="{p["ry"]:.1f}"'
                f' fill="{p["fill"]}"{_stroke(p)}{op_attr}{drole}/>')
    if op in ("polyline", "poly", "polygon"):
        tag = "polyline" if op == "polyline" else "polygon"
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in p["pts"])
        fill = p.get("fill", "none")
        op_attr = f' opacity="{p["opacity"]}"' if p.get("opacity", 1) != 1 else ""
        return f'  <{tag} points="{pts}" fill="{fill}"{_stroke(p)}{op_attr}{drole}/>'
    if op == "text":
        anchor = p.get("anchor", "middle")
        size = p.get("size", 15)
        weight = f' font-weight="{p.get("weight", "normal")}"'
        style = ' font-style="italic"' if p.get("italic") else ""
        rot = p.get("rotate")
        transform = f' transform="rotate({rot} {p["x"]:.1f} {p["y"]:.1f})"' if rot else ""
        halo = (' stroke="#ffffff" stroke-width="3" paint-order="stroke" stroke-linejoin="round"'
                if p.get("halo", True) else "")
        lines = str(p["s"]).split("\n")
        if len(lines) == 1:
            return (f'  <text x="{p["x"]:.1f}" y="{p["y"]:.1f}" font-size="{size}"'
                    f' text-anchor="{anchor}" dominant-baseline="central"{weight}{style}'
                    f' fill="{p.get("fill", "#1e293b")}"{transform}{halo}'
                    f' font-family="{esc(FONT_STACK)}"{drole}>{esc(lines[0])}</text>')
        line_h = size * 1.22
        y_start = p["y"] - line_h * (len(lines) - 1) / 2.0
        tspans = "".join(
            f'<tspan x="{p["x"]:.1f}" y="{y_start + i * line_h:.1f}">{esc(ln)}</tspan>'
            for i, ln in enumerate(lines)
        )
        return (f'  <text x="{p["x"]:.1f}" y="{p["y"]:.1f}" font-size="{size}"'
                f' text-anchor="{anchor}" dominant-baseline="central"{weight}{style}'
                f' fill="{p.get("fill", "#1e293b")}"{transform}{halo}'
                f' font-family="{esc(FONT_STACK)}"{drole}>{tspans}</text>')
    return ""

def to_svg(prims, W, H, title="figure", panel_groups=None):
    """Write layered SVG. If panel_groups is given (list of (panel_id, dx, dy, sub_prims)),
    each panel is wrapped in its own <g id="panel-<id>" transform="translate(dx,dy)">."""
    head = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg"'
            f' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
            f' width="{W}" height="{H}"'
            f' viewBox="0 0 {W} {H}" font-family="{esc(FONT_STACK)}">\n'
            f'<title>{esc(title)}</title>\n'
            f'<g id="layer-canvas" data-layer="Canvas" inkscape:groupmode="layer" inkscape:label="Canvas">\n'
            f'  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff" data-role="bg"/>\n'
            f'</g>\n')
    parts = [head]
    if panel_groups:
        for pid, dx, dy, sub_prims in panel_groups:
            parts.append(f'<g id="panel-{esc(pid)}" data-panel="{esc(pid)}" transform="translate({dx:.1f},{dy:.1f})">\n')
            parts.append(_render_layered(sub_prims, prefix=f"panel-{pid}-"))
            parts.append("</g>\n")
        if prims:
            parts.append(_render_layered(prims))
    else:
        parts.append(_render_layered(prims))
    parts.append("</svg>\n")
    return "".join(parts)

def _render_layered(prims, prefix=""):
    buckets = {lid: [] for lid, _ in LAYER_ORDER}
    for p in prims:
        lid = _layer_for(p)
        if lid not in buckets:
            buckets[lid] = []
        s = prim_to_svg(p)
        if s:
            buckets[lid].append(s)
    out = []
    for lid, label in LAYER_ORDER:
        items = buckets.get(lid)
        if items:
            gid = f"{prefix}{lid}"
            out.append(f'<g id="{esc(gid)}" data-layer="{esc(label)}" inkscape:groupmode="layer" inkscape:label="{esc(label)}">\n')
            out.append("\n".join(items) + "\n")
            out.append("</g>\n")
    return "".join(out)
