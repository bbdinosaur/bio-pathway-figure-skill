"""Auto legend panel, title, caption, data-encoding scale."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import EDGE_STYLES, NODE_STYLES, ramp, FONT_STACK
from viz_geom import norm, arrow_poly, diamond_poly

NODE_LEGEND = [("receptor", "Receptor / TM"), ("protein", "Protein"), ("gene", "Gene (italic)"),
               ("complex", "Complex"), ("metabolite", "Metabolite"), ("cell", "Cell type"), ("dna", "DNA")]

def legend_edge_sample(prims, x, y, et, dashed=False):
    st = EDGE_STYLES[et]
    col = st["color"]
    a, b = [x, y], [x + 64, y]
    dirv = norm(1, 0)
    prims.append({"op": "polyline", "pts": [a, [b[0] - 8, b[1]]], "stroke": col, "stroke_w": 2.4,
                  "dashed": dashed, "role": "legend_edge"})
    end = st["end"]
    from viz_edges import _draw_marker
    _draw_marker(prims, st, b, dirv, col, et, {})
    if st.get("both"):
        _draw_marker(prims, st, a, dirv, col, et, {}, start=True)

def build_legend(prims, used_edges, placed, spec, lx, top, opts=None):
    opts = opts or {}
    y = top
    title = spec.get("legend_title", "LEGEND")
    prims.append({"op": "text", "x": lx, "y": y, "s": title, "size": 15, "anchor": "start",
                  "fill": "#0f172a", "weight": "bold", "role": "legend"})
    y += 26
    if used_edges:
        prims.append({"op": "text", "x": lx, "y": y, "s": "Interactions", "size": 12.5,
                      "anchor": "start", "fill": "#475569", "weight": "bold", "role": "legend"})
        y += 20
        for et in used_edges:
            st = EDGE_STYLES[et]
            legend_edge_sample(prims, lx + 6, y - 4, et)
            prims.append({"op": "text", "x": lx + 84, "y": y, "s": et.capitalize(), "size": 13,
                          "anchor": "start", "fill": "#1e293b", "role": "legend"})
            y += 22
    auto = bool(opts.get("evidence_auto_style"))
    if any(e.get("dashed") or (auto and str(e.get("evidence") or "").lower() in
           ("reported", "inferred", "indirect", "putative"))
           for e in spec.get("edges", [])):
        legend_edge_sample(prims, lx + 6, y - 4, "activation", dashed=True)
        prims.append({"op": "text", "x": lx + 84, "y": y, "s": "Indirect / reported", "size": 13,
                      "anchor": "start", "fill": "#1e293b", "role": "legend"})
        y += 22
    if any(e.get("dotted") or (auto and str(e.get("evidence") or "").lower() == "weak")
           for e in spec.get("edges", [])):
        prims.append({"op": "polyline", "pts": [[lx + 6, y - 4], [lx + 62, y - 4]],
                      "stroke": EDGE_STYLES["activation"]["color"], "stroke_w": 2.4,
                      "dotted": True, "role": "legend_edge"})
        prims.append({"op": "text", "x": lx + 84, "y": y, "s": "Weak evidence", "size": 13,
                      "anchor": "start", "fill": "#1e293b", "role": "legend"})
        y += 22
    kinds = []
    for n in placed:
        if n.get("kind") not in kinds:
            kinds.append(n.get("kind"))
    show_shapes = [k for k in NODE_LEGEND if k[0] in kinds]
    if len(show_shapes) >= 2:
        prims.append({"op": "text", "x": lx, "y": y, "s": "Node types", "size": 12.5,
                      "anchor": "start", "fill": "#475569", "weight": "bold", "role": "legend"})
        y += 20
        for k, lbl in show_shapes:
            st = NODE_STYLES[k]
            prims.append({"op": "rect", "x": lx + 6, "y": y - 11, "w": 46, "h": 22, "rx": 5,
                          "fill": st["fill"], "stroke": st["stroke"], "stroke_w": 1.6, "role": "legend"})
            prims.append({"op": "text", "x": lx + 62, "y": y + 4, "s": lbl, "size": 13,
                          "anchor": "start", "fill": "#1e293b", "role": "legend"})
            y += 28
    dm = spec.get("data_map")
    if dm:
        prims.append({"op": "text", "x": lx, "y": y, "s": "Data encoding", "size": 12.5,
                      "anchor": "start", "fill": "#475569", "weight": "bold", "role": "legend"})
        y += 20
        name = dm.get("palette", "blues")
        for i in range(12):
            prims.append({"op": "rect", "x": lx + 6 + i * 20, "y": y - 10, "w": 20, "h": 13,
                          "fill": ramp(name, i / 11.0), "stroke": "#e2e8f0", "stroke_w": 0.5,
                          "role": "legend"})
        lo, hi = dm.get("min", "low"), dm.get("max", "high")
        prims.append({"op": "text", "x": lx + 6, "y": y + 16, "s": str(lo), "size": 11.5,
                      "anchor": "start", "fill": "#475569", "role": "legend"})
        prims.append({"op": "text", "x": lx + 246, "y": y + 16, "s": str(hi), "size": 11.5,
                      "anchor": "end", "fill": "#475569", "role": "legend"})
        y_extra = 16
        if dm.get("size_caption"):
            y_extra += 15
            prims.append({"op": "text", "x": lx + 6, "y": y + 31, "s": str(dm["size_caption"]),
                          "size": 11.5, "anchor": "start", "fill": "#475569", "role": "legend"})
        from viz_style import text_w
        ccap = str(dm.get("caption", ""))
        cy2 = y + 33 + (15 if dm.get("size_caption") else 0)
        cur = ""
        for word in ccap.split(" "):
            t = (cur + " " + word).strip()
            if text_w(t, 11.5) <= 320 or not cur:
                cur = t
            else:
                prims.append({"op": "text", "x": lx + 6, "y": cy2, "s": cur, "size": 11.5,
                              "anchor": "start", "fill": "#475569", "role": "legend"})
                cy2 += 15
                cur = word
        if cur:
            prims.append({"op": "text", "x": lx + 6, "y": cy2, "s": cur, "size": 11.5,
                          "anchor": "start", "fill": "#475569", "role": "legend"})
        y = max(cy2 + 14, y + 46)
    return y + 8
