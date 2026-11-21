"""Build mechanism figure primitives from spec (orchestrator)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import SCALES
from viz_layout import auto_compartment_bands, draw_compartments, place_nodes, tighten_bands
from viz_nodes import draw_nodes
from viz_edges import draw_edges
from viz_legend import build_legend

def build_mechanism(spec, scale_name="regular"):
    gap = SCALES.get(scale_name, 86)
    from viz_style import text_w
    lgap = 0
    for e in spec.get("edges", []):
        t = str(e.get("label") or "")
        if e.get("evidence"):
            t += f" [{e['evidence']}]"
        if t and e.get("route", "direct") == "direct":
            lgap = max(lgap, text_w(t, 12.5) + 14)
    gap = max(gap, lgap)
    prims = []
    comps = spec.get("compartments", [])
    comp_kind = {c["id"]: c.get("kind", "custom") for c in comps}
    # pass 1: measure needed band heights from node extents (opt-in)
    lopts = spec.get("layout") or {}
    bands0, _ = auto_compartment_bands(comps)
    placed0, row_w = place_nodes(spec, bands0, comp_kind, gap, 0)
    bands = tighten_bands(comps, bands0, placed0) if lopts.get("tighten_bands", True) else bands0
    placed, row_w = place_nodes(spec, bands, comp_kind, gap, 0)
    plot_w = max(row_w, 520)
    if comps:
        draw_compartments(comps, bands, plot_w, prims, placed=placed)
    from viz_geom import bbox_of
    node_boxes = []
    for n in placed:
        nb = {"op": "rect", "role": "node", "x": n["cx"] - n["w"] / 2,
              "y": n["cy"] - n["h"] / 2, "w": n["w"], "h": n["h"]}
        if n.get("shape") == "ellipse":
            nb = {"op": "ellipse", "role": "node", "cx": n["cx"], "cy": n["cy"],
                  "rx": n["w"] / 2, "ry": n["h"] / 2}
        node_boxes.append((n["id"], bbox_of(nb)))
    used = draw_edges(spec.get("edges", []), placed, gap, prims,
                      node_boxes=node_boxes, opts=lopts)
    draw_nodes(placed, prims)
    legend_w = 0
    legend_bottom = 0
    if used or spec.get("data_map") or spec.get("legend") is not False:
        lx = 56 + plot_w + 40
        legend_bottom = build_legend(prims, used, placed, spec, lx, 80, opts=lopts)
        legend_w = 330
    W = int(max(56 + plot_w + (40 + legend_w if legend_w else 0) + 30, 760))
    title = spec.get("title", "")
    tlines = _wrap(title, W - 112, 21) if title else []
    for i, ln in enumerate(tlines[:2]):
        prims.append({"op": "text", "x": 56, "y": 26 + i * 26, "s": ln, "size": 21,
                      "anchor": "start", "fill": "#0f172a", "weight": "bold", "role": "text"})
    caption = spec.get("caption", "")
    bands_bottom = (bands[-1]["y1"] + 12) if bands else 0
    cap_y = int(max(bands_bottom if comps else placed and max(n["cy"] + n["h"] / 2 for n in placed) or 400,
                    legend_bottom) + (24 if caption else 28))
    clines = _wrap(caption, W - 112, 12.5) if caption else []
    for i, ln in enumerate(clines):
        prims.append({"op": "text", "x": 56, "y": cap_y + i * 17, "s": ln, "size": 12.5,
                      "anchor": "start", "fill": "#64748b", "italic": True, "role": "text"})
    H = int(cap_y + 17 * len(clines) + 16)
    return prims, W, H, placed, used

def _wrap(s, maxpx, size):
    from viz_style import text_w
    words, lines, cur = str(s).split(" "), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(t, size) <= maxpx or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines
