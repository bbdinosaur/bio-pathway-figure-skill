"""Node rendering: shapes, double borders, mod tags (P/Ub), labels."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import NODE_STYLES, FONT_STACK

MOD_COLORS = {"P": "#b45309", "Ub": "#92400e", "Ac": "#7c3aed", "GTP": "#0f766e"}

def hex_pts(cx, cy, w, h):
    s = min(w, h) * 0.30
    return [[cx - w / 2, cy], [cx - w / 2 + s * 0.7, cy - h / 2], [cx + w / 2 - s * 0.7, cy - h / 2],
            [cx + w / 2, cy], [cx + w / 2 - s * 0.7, cy + h / 2], [cx - w / 2 + s * 0.7, cy + h / 2]]

def draw_nodes(placed, prims):
    for n in placed:
        kind = n.get("kind", "protein")
        st = NODE_STYLES.get(kind, NODE_STYLES["other"])
        fill = n.get("fill") or st["fill"]
        stroke = n.get("stroke") or st["stroke"]
        x0, y0 = n["cx"] - n["w"] / 2.0, n["cy"] - n["h"] / 2.0
        shape = n.get("shape") or st.get("shape") or "rect"
        common = {"fill": fill, "stroke": stroke, "stroke_w": 1.8, "role": "node",
                  "_id": f"shape-{n['id']}"}
        if shape == "ellipse":
            prims.append({"op": "ellipse", "cx": n["cx"], "cy": n["cy"], "rx": n["w"] / 2,
                          "ry": n["h"] / 2, **common})
        elif shape == "hex":
            prims.append({"op": "poly", "pts": hex_pts(n["cx"], n["cy"], n["w"], n["h"]), **common})
        else:
            prims.append({"op": "rect", "x": x0, "y": y0, "w": n["w"], "h": n["h"],
                          "rx": 8 if shape == "rect" else 0, **common})
            if st.get("double") or n.get("double"):
                prims.append({"op": "rect", "x": x0 + 4, "y": y0 + 4, "w": n["w"] - 8,
                              "h": n["h"] - 8, "rx": 5, "fill": "none", "stroke": stroke,
                              "stroke_w": 1.0, "role": "node"})
        label = str(n.get("label", n["id"]))
        italic = bool(st.get("italic")) or bool(n.get("italic"))
        size = n.get("label_size") or 15.0
        maxw = n["w"] - 16
        while size > 10.5 and 0.62 * size * len(label) > maxw:
            size -= 0.5
        prims.append({"op": "text", "x": n["cx"], "y": n["cy"], "s": label, "size": size,
                      "anchor": "middle", "fill": n.get("label_fill", "#1e293b"),
                      "weight": "bold", "italic": italic, "role": "node_label",
                      "_id": f"label-{n['id']}"})
        alias = n.get("alias")
        if alias:
            prims.append({"op": "text", "x": n["cx"], "y": y0 - 7, "s": str(alias), "size": 11,
                          "anchor": "middle", "fill": "#64748b", "italic": True, "role": "text"})
        for i, m in enumerate(n.get("mods", []) or []):
            col = MOD_COLORS.get(str(m), "#b45309")
            mx = n["cx"] + n["w"] / 2.0 - 2 + i * 15
            my = n["cy"] - n["h"] / 2.0 + 2
            prims.append({"op": "circle", "cx": mx, "cy": my, "r": 9.5, "fill": "#ffffff",
                          "stroke": col, "stroke_w": 1.6, "role": "mod"})
            prims.append({"op": "text", "x": mx, "y": my, "s": str(m), "size": 10,
                          "anchor": "middle", "fill": col, "weight": "bold", "role": "mod"})
