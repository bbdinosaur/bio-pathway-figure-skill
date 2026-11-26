"""Auto legend card: interactions (distinct glyphs), node shapes, mods, groups, data ramp."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import EDGE_STYLES, NODE_STYLES, ramp, text_w, wrap_text, is_diverging
from viz_geom import norm
from viz_nodes import MOD_COLORS, hex_pts

NODE_LEGEND = [
    ("receptor",   "Receptor / TM"),
    ("protein",    "Protein"),
    ("gene",       "Gene (italic)"),
    ("complex",    "Complex"),
    ("metabolite", "Metabolite"),
    ("process",    "Process / Outcome"),
    ("phenotype",  "Phenotype"),
    ("drug",       "Drug / Inhibitor"),
    ("cell",       "Cell type"),
    ("dna",        "DNA"),
]

def legend_edge_sample(prims, x, y, et, dashed=False, dotted=False):
    st = EDGE_STYLES[et]
    col = st["color"]
    a, b = [x, y], [x + 58, y]
    dirv = norm(1, 0)
    x0 = x + (8 if st.get("both") else 0)
    x1 = b[0] - (14 if st["end"] == "circle" and st.get("tag") else (8 if st["end"] in ("arrow", "open", "diamond", "open_dot") else 2))
    prims.append({"op": "polyline", "pts": [[x0, y], [x1, y]], "stroke": col, "stroke_w": 2.2,
                  "dashed": dashed or bool(st.get("default_dashed")), "dotted": dotted,
                  "role": "legend_edge", "layer": "layer-legend"})
    from viz_edges import _draw_marker
    _draw_marker(prims, st, b, dirv, col, role="legend_edge", layer="layer-legend")
    if st.get("both"):
        _draw_marker(prims, st, a, (-1.0, 0.0), col, role="legend_edge", layer="layer-legend")
    elif st.get("start_dot"):
        prims.append({"op": "circle", "cx": x + 4.5, "cy": y, "r": 3.5, "fill": "#ffffff",
                      "stroke": col, "stroke_w": 1.6, "role": "legend_edge", "layer": "layer-legend"})
    elif st.get("start_bar"):
        prims.append({"op": "polyline", "pts": [[x + 4.5, y - 5.0], [x + 4.5, y + 5.0]],
                      "stroke": col, "stroke_w": 2.2, "role": "legend_edge", "layer": "layer-legend"})

def build_legend(prims, used_edges, placed, spec, lx, top, opts=None):
    opts = opts or {}
    # Subtle drop shadow behind legend card (height synced with card at end)
    sh_idx = len(prims)
    prims.append({"op": "rect", "x": lx - 12, "y": top - 17, "w": 324, "h": 100, "rx": 10,
                  "fill": "#94a3b8", "stroke": "none", "stroke_w": 0, "opacity": 0.16,
                  "role": "deco", "layer": "layer-legend"})
    card_idx = len(prims)
    # Placeholder card rect updated with final height at end
    prims.append({"op": "rect", "x": lx - 14, "y": top - 20, "w": 324, "h": 100, "rx": 10,
                  "fill": "#f8fafc", "stroke": "#e2e8f0", "stroke_w": 1.2,
                  "role": "legend_bg", "layer": "layer-legend"})
    y = top
    title = spec.get("legend_title", "LEGEND")
    prims.append({"op": "text", "x": lx, "y": y, "s": title, "size": 14.5, "anchor": "start",
                  "fill": "#0f172a", "weight": "bold", "role": "legend", "layer": "layer-legend"})
    y += 26
    if used_edges:
        prims.append({"op": "text", "x": lx, "y": y, "s": "Interactions", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 22
        for et in used_edges:
            legend_edge_sample(prims, lx + 4, y, et)
            elbl = "Undirected / assoc." if et == "undirected" else et.capitalize()
            prims.append({"op": "text", "x": lx + 74, "y": y, "s": elbl, "size": 12.5,
                          "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
            y += 22
    auto = bool(opts.get("evidence_auto_style", True))
    if any(e.get("dashed") or (auto and str(e.get("evidence") or "").lower() in
           ("reported", "inferred", "indirect", "putative", "predicted", "uncertain"))
           for e in spec.get("edges", [])):
        legend_edge_sample(prims, lx + 4, y, "activation", dashed=True)
        prims.append({"op": "text", "x": lx + 74, "y": y, "s": "Indirect / reported", "size": 12.5,
                      "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
        y += 22
    if any(e.get("dotted") or (auto and str(e.get("evidence") or "").lower() == "weak")
           for e in spec.get("edges", [])):
        legend_edge_sample(prims, lx + 4, y, "activation", dotted=True)
        prims.append({"op": "text", "x": lx + 74, "y": y, "s": "Weak evidence", "size": 12.5,
                      "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
        y += 22

    kinds = []
    for n in placed:
        if n.get("kind") not in kinds:
            kinds.append(n.get("kind"))
    show_shapes = [k for k in NODE_LEGEND if k[0] in kinds]
    if len(show_shapes) >= 2:
        y += 6
        prims.append({"op": "text", "x": lx, "y": y, "s": "Node types", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 26  # clean gap so swatch top never collides with 'Node types' header!
        for k, lbl in show_shapes:
            st = NODE_STYLES[k]
            sx, sy, sw, sh = lx + 4, y - 10, 44, 20
            shp = st.get("shape", "rect")
            if shp == "ellipse":
                prims.append({"op": "ellipse", "cx": sx + sw / 2, "cy": y, "rx": sw / 2, "ry": sh / 2,
                              "fill": st["fill"], "stroke": st["stroke"], "stroke_w": 1.5,
                              "role": "legend", "layer": "layer-legend"})
            elif shp == "hex":
                prims.append({"op": "poly", "pts": hex_pts(sx + sw / 2, y, sw, sh),
                              "fill": st["fill"], "stroke": st["stroke"], "stroke_w": 1.5,
                              "role": "legend", "layer": "layer-legend"})
            elif shp == "pill":
                prims.append({"op": "rect", "x": sx, "y": sy, "w": sw, "h": sh, "rx": sh / 2,
                              "fill": st["fill"], "stroke": st["stroke"], "stroke_w": 1.5,
                              "role": "legend", "layer": "layer-legend"})
            else:
                prims.append({"op": "rect", "x": sx, "y": sy, "w": sw, "h": sh, "rx": 5,
                              "fill": st["fill"], "stroke": st["stroke"], "stroke_w": 1.5,
                              "role": "legend", "layer": "layer-legend"})
                if st.get("double"):
                    prims.append({"op": "rect", "x": sx + 3, "y": sy + 3, "w": sw - 6, "h": sh - 6, "rx": 3,
                                  "fill": "none", "stroke": st["stroke"], "stroke_w": 0.9,
                                  "role": "legend", "layer": "layer-legend"})
            if st.get("italic"):
                prims.append({"op": "text", "x": sx + sw / 2, "y": y, "s": "Gene", "size": 9.5,
                              "anchor": "middle", "fill": "#475569", "italic": True, "halo": False,
                              "role": "legend", "layer": "layer-legend"})
            prims.append({"op": "text", "x": lx + 60, "y": y, "s": lbl, "size": 12.5,
                          "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
            y += 28

    # Modifications used
    mods_used = []
    for n in placed:
        for m in (n.get("mods") or []):
            if str(m) not in mods_used:
                mods_used.append(str(m))
    if mods_used:
        y += 4
        prims.append({"op": "text", "x": lx, "y": y, "s": "Modifications", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 22
        mod_names = {"P": "Phosphorylation", "Ub": "Ubiquitination", "Ac": "Acetylation",
                     "GTP": "GTP-bound", "Me": "Methylation", "SUMO": "SUMOylation"}
        for m in mods_used:
            col = MOD_COLORS.get(m, "#b45309")
            if len(m) >= 2:
                bw_m = max(24.0, len(m) * 6.2 + 9.0)
                bh_m = 18.0
                prims.append({"op": "rect", "x": lx + 20 - bw_m / 2.0, "y": y - bh_m / 2.0,
                              "w": bw_m, "h": bh_m, "rx": bh_m / 2.0, "fill": "#ffffff",
                              "stroke": col, "stroke_w": 1.5, "role": "legend", "layer": "layer-legend"})
                prims.append({"op": "text", "x": lx + 20, "y": y, "s": m, "size": 9.0, "anchor": "middle",
                              "fill": col, "weight": "bold", "halo": False,
                              "role": "legend", "layer": "layer-legend"})
                tx_m = max(lx + 42, lx + 20 + bw_m / 2.0 + 10)
            else:
                prims.append({"op": "circle", "cx": lx + 20, "cy": y, "r": 9.0, "fill": "#ffffff",
                              "stroke": col, "stroke_w": 1.5, "role": "legend", "layer": "layer-legend"})
                prims.append({"op": "text", "x": lx + 20, "y": y, "s": m, "size": 9.5, "anchor": "middle",
                              "fill": col, "weight": "bold", "halo": False,
                              "role": "legend", "layer": "layer-legend"})
                tx_m = lx + 42
            prims.append({"op": "text", "x": tx_m, "y": y, "s": mod_names.get(m, m), "size": 12.0,
                          "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
            y += 23

    # Complex / module group swatch
    if spec.get("groups"):
        y += 4
        prims.append({"op": "rect", "x": lx + 4, "y": y - 9, "w": 44, "h": 18, "rx": 5,
                      "fill": "#f8fafc", "stroke": "#94a3b8", "stroke_w": 1.3, "dashed": True,
                      "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "text", "x": lx + 60, "y": y, "s": "Complex / module", "size": 12.0,
                      "anchor": "start", "fill": "#1e293b", "role": "legend", "layer": "layer-legend"})
        y += 24

    dm = spec.get("data_map")
    if dm:
        y += 6
        prims.append({"op": "text", "x": lx, "y": y, "s": "Data encoding", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 20
        name = dm.get("palette", "blues")
        for i in range(12):
            prims.append({"op": "rect", "x": lx + 4 + i * 22, "y": y - 7, "w": 22, "h": 13,
                          "fill": ramp(name, i / 11.0), "stroke": "#e2e8f0", "stroke_w": 0.4,
                          "role": "legend", "layer": "layer-legend"})
        lo, hi = dm.get("min", "low"), dm.get("max", "high")
        prims.append({"op": "text", "x": lx + 4, "y": y + 17, "s": str(lo), "size": 11.0,
                      "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        if is_diverging(name) and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            mid_v = 0 if (float(lo) < 0 < float(hi) and abs(float(lo) + float(hi)) <= 0.15 * (float(hi) - float(lo))) else round(0.5 * (float(lo) + float(hi)), 2)
            mid_s = "0" if mid_v == 0 else f"{mid_v:g}"
            prims.append({"op": "text", "x": lx + 136, "y": y + 17, "s": mid_s, "size": 11.0,
                          "anchor": "middle", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "text", "x": lx + 268, "y": y + 17, "s": str(hi), "size": 11.0,
                      "anchor": "end", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        cy2 = y + 34
        if dm.get("size_caption"):
            for ln in wrap_text(str(dm["size_caption"]), 290, 11.0):
                prims.append({"op": "text", "x": lx + 4, "y": cy2, "s": ln,
                              "size": 11.0, "anchor": "start", "fill": "#475569",
                              "role": "legend", "layer": "layer-legend"})
                cy2 += 16
        for ln in wrap_text(str(dm.get("caption", "")), 290, 11.0):
            prims.append({"op": "text", "x": lx + 4, "y": cy2, "s": ln, "size": 11.0,
                          "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
            cy2 += 15
        y = max(cy2, y + 42)

    wm = spec.get("width_map")
    wvals = [e.get("weight") if e.get("weight") is not None else e.get("confidence")
             for e in spec.get("edges", [])
             if isinstance(e.get("weight") if e.get("weight") is not None else e.get("confidence"), (int, float))]
    if wm or wvals:
        wm = wm or {}
        wlo = wm.get("min", min(wvals) if wvals else "low")
        whi = wm.get("max", max(wvals) if wvals else "high")
        wmid = (f"{round(0.5 * (float(wlo) + float(whi)), 2):g}"
                if isinstance(wlo, (int, float)) and isinstance(whi, (int, float)) else "mid")
        y += 6
        prims.append({"op": "text", "x": lx, "y": y, "s": "Edge width", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 20
        for sw_px, lbl_w, ox in ((1.5, str(wlo), 4), (3.0, wmid, 100), (4.6, str(whi), 196)):
            prims.append({"op": "polyline", "pts": [[lx + ox, y], [lx + ox + 34, y]],
                          "stroke": "#334155", "stroke_w": sw_px,
                          "role": "legend_edge", "layer": "layer-legend"})
            prims.append({"op": "text", "x": lx + ox + 40, "y": y, "s": lbl_w, "size": 10.5,
                          "anchor": "start", "fill": "#475569",
                          "role": "legend", "layer": "layer-legend"})
        y += 18
        if wm.get("caption"):
            for ln in wrap_text(str(wm["caption"]), 290, 11.0):
                prims.append({"op": "text", "x": lx + 4, "y": y, "s": ln, "size": 11.0,
                              "anchor": "start", "fill": "#475569",
                              "role": "legend", "layer": "layer-legend"})
                y += 15
            y += 1

    sm = spec.get("size_map")
    if sm and not (dm and dm.get("size_caption")):
        y += 6
        prims.append({"op": "text", "x": lx, "y": y, "s": "Node size", "size": 12.0,
                      "anchor": "start", "fill": "#475569", "weight": "bold",
                      "role": "legend", "layer": "layer-legend"})
        y += 22
        prims.append({"op": "rect", "x": lx + 4, "y": y - 7, "w": 28, "h": 14, "rx": 4,
                      "fill": "#e3ecfb", "stroke": "#3b69b8", "stroke_w": 1.3,
                      "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "text", "x": lx + 38, "y": y, "s": str(sm.get("min", "low")), "size": 10.5,
                      "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "rect", "x": lx + 116, "y": y - 11, "w": 36, "h": 22, "rx": 5,
                      "fill": "#e3ecfb", "stroke": "#3b69b8", "stroke_w": 1.3,
                      "role": "legend", "layer": "layer-legend"})
        prims.append({"op": "text", "x": lx + 158, "y": y, "s": str(sm.get("max", "high")), "size": 10.5,
                      "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
        y += 20
        if sm.get("caption"):
            for ln in wrap_text(str(sm["caption"]), 290, 11.0):
                prims.append({"op": "text", "x": lx + 4, "y": y, "s": ln, "size": 11.0,
                              "anchor": "start", "fill": "#475569", "role": "legend", "layer": "layer-legend"})
                y += 15
            y += 1

    card_h = max(60, (y + 10) - (top - 20))
    prims[sh_idx]["h"] = card_h
    prims[card_idx]["h"] = card_h
    return top - 20 + card_h + 6
