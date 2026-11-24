"""Node rendering: shapes, double borders, auto data-map color ramp, mod tags, multi-line labels."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import NODE_STYLES, ramp, contrast_text

MOD_COLORS = {"P": "#b45309", "Ub": "#92400e", "Ac": "#7c3aed", "GTP": "#0f766e",
              "Me": "#a21caf", "SUMO": "#0369a1"}

def hex_pts(cx, cy, w, h):
    s = min(w, h) * 0.30
    return [[cx - w / 2, cy], [cx - w / 2 + s * 0.7, cy - h / 2], [cx + w / 2 - s * 0.7, cy - h / 2],
            [cx + w / 2, cy], [cx + w / 2 - s * 0.7, cy + h / 2], [cx - w / 2 + s * 0.7, cy + h / 2]]

def _resolve_data_fill(n, spec, val_range):
    """Automatically map numeric node['value'] to palette color when data_map is active."""
    dm = spec.get("data_map") if spec else None
    if not dm or n.get("fill") or not isinstance(n.get("value"), (int, float)):
        return None
    vmin, vmax = val_range
    if vmin is None or vmax is None:
        return None
    t = (float(n["value"]) - vmin) / ((vmax - vmin) or 1.0)
    return ramp(dm.get("palette", "blues"), t)

def _numeric_range(placed, spec):
    dm = (spec or {}).get("data_map") or {}
    lo = dm.get("min_val")
    hi = dm.get("max_val")
    if lo is None:
        try:
            lo = float(dm.get("min"))
        except Exception:
            lo = None
    if hi is None:
        try:
            hi = float(dm.get("max"))
        except Exception:
            hi = None
    vals = [float(n["value"]) for n in placed if isinstance(n.get("value"), (int, float))]
    if vals:
        if lo is None:
            lo = min(vals)
        if hi is None:
            hi = max(vals)
    return lo, hi

def draw_nodes(placed, prims, spec=None):
    val_range = _numeric_range(placed, spec)
    for n in placed:
        kind = n.get("kind", "protein")
        st = NODE_STYLES.get(kind, NODE_STYLES["other"])
        auto_fill = _resolve_data_fill(n, spec, val_range)
        fill = n.get("fill") or auto_fill or st["fill"]
        stroke = n.get("stroke") or st["stroke"]
        x0, y0 = n["cx"] - n["w"] / 2.0, n["cy"] - n["h"] / 2.0
        shape = n.get("shape") or st.get("shape") or "rect"
        node_meta = {
            "kind": kind,
            "compartment": n.get("compartment"),
            "source": n.get("source"),
            "alias": n.get("alias"),
            "value": n.get("value"),
        }
        common = {"fill": fill, "stroke": stroke, "stroke_w": 1.8, "role": "node",
                  "layer": "layer-nodes", "_id": f"shape-{n['id']}", "_meta": node_meta}
        sh_common = {"fill": "#94a3b8", "stroke": "none", "stroke_w": 0, "opacity": 0.22,
                     "role": "deco", "layer": "layer-nodes"}
        if shape == "ellipse":
            prims.append({"op": "ellipse", "cx": n["cx"] + 2.0, "cy": n["cy"] + 2.5,
                          "rx": n["w"] / 2, "ry": n["h"] / 2, **sh_common})
            prims.append({"op": "ellipse", "cx": n["cx"], "cy": n["cy"], "rx": n["w"] / 2,
                          "ry": n["h"] / 2, **common})
        elif shape == "hex":
            prims.append({"op": "poly", "pts": hex_pts(n["cx"] + 2.0, n["cy"] + 2.5, n["w"], n["h"]), **sh_common})
            prims.append({"op": "poly", "pts": hex_pts(n["cx"], n["cy"], n["w"], n["h"]), **common})
        elif shape == "pill":
            rx_p = min(n["h"] / 2.0, 22.0)
            prims.append({"op": "rect", "x": x0 + 2.0, "y": y0 + 2.5, "w": n["w"], "h": n["h"],
                          "rx": rx_p, **sh_common})
            prims.append({"op": "rect", "x": x0, "y": y0, "w": n["w"], "h": n["h"],
                          "rx": rx_p, **common})
        else:
            rx_r = 8 if shape == "rect" else 0
            prims.append({"op": "rect", "x": x0 + 2.0, "y": y0 + 2.5, "w": n["w"], "h": n["h"],
                          "rx": rx_r, **sh_common})
            prims.append({"op": "rect", "x": x0, "y": y0, "w": n["w"], "h": n["h"],
                          "rx": rx_r, **common})
            if st.get("double") or n.get("double"):
                prims.append({"op": "rect", "x": x0 + 4, "y": y0 + 4, "w": n["w"] - 8,
                              "h": n["h"] - 8, "rx": 5, "fill": "none", "stroke": stroke,
                              "stroke_w": 1.0, "role": "node", "layer": "layer-nodes"})
            if kind == "receptor" and n["h"] >= 54:
                # Subtle transmembrane extracellular/intracellular domain-cap accents
                cap_w = max(18.0, n["w"] - 22.0)
                cx_l = n["cx"] - cap_w / 2.0
                prims.append({"op": "rect", "x": cx_l, "y": y0 + 3.5, "w": cap_w, "h": 4.0,
                              "rx": 2.0, "fill": stroke, "stroke": "none", "stroke_w": 0,
                              "opacity": 0.32, "role": "deco", "layer": "layer-nodes"})
                prims.append({"op": "rect", "x": cx_l, "y": y0 + n["h"] - 7.5, "w": cap_w, "h": 4.0,
                              "rx": 2.0, "fill": stroke, "stroke": "none", "stroke_w": 0,
                              "opacity": 0.32, "role": "deco", "layer": "layer-nodes"})
        label = str(n.get("label", n["id"]))
        sub = str(n.get("sublabel") or "")
        alias = str(n.get("alias") or "").strip()
        sub_eff = f"{sub} ({alias})" if (sub and alias) else (f"({alias})" if alias else sub)
        sub_italic = bool(alias and not sub)
        subunits = [str(u) for u in (n.get("subunits") or []) if str(u).strip()]
        italic = bool(st.get("italic")) or bool(n.get("italic"))
        size = float(n.get("label_size") or 14.5)
        maxw = n["w"] - 16
        longest = max((len(ln) for ln in label.split("\n")), default=1)
        while size > 10.5 and 0.62 * size * longest > maxw:
            size -= 0.5
        ink = n.get("label_fill") or (contrast_text(fill) if auto_fill else "#1e293b")
        use_halo = (ink == "#1e293b")
        n_lbl_lines = max(1, len(label.split("\n")))
        lbl_y = n["cy"] - (11.0 if subunits else 0.0)
        if sub_eff:
            lbl_shift = 7.5 + max(0, n_lbl_lines - 1) * (size * 0.52)
            sub_shift = 9.5 + max(0, n_lbl_lines - 1) * (size * 0.62)
            prims.append({"op": "text", "x": n["cx"], "y": lbl_y - lbl_shift + (3.0 if n_lbl_lines > 1 else 0.0),
                          "s": label, "size": size,
                          "anchor": "middle", "fill": ink, "weight": "bold", "italic": italic,
                          "halo": use_halo, "role": "node_label", "layer": "layer-nodes",
                          "_id": f"label-{n['id']}"})
            sub_ink = "#f1f5f9" if ink == "#ffffff" else ("#1e293b" if auto_fill else "#475569")
            prims.append({"op": "text", "x": n["cx"], "y": lbl_y + sub_shift, "s": sub_eff, "size": 10.0,
                          "anchor": "middle", "fill": sub_ink,
                          "italic": sub_italic, "halo": False, "role": "node_label",
                          "layer": "layer-nodes", "_id": f"alias-{n['id']}" if (alias and not sub) else f"sublabel-{n['id']}"})
        else:
            prims.append({"op": "text", "x": n["cx"], "y": lbl_y, "s": label, "size": size,
                          "anchor": "middle", "fill": ink, "weight": "bold", "italic": italic,
                          "halo": use_halo, "role": "node_label", "layer": "layer-nodes",
                          "_id": f"label-{n['id']}"})
        if subunits:
            pill_ws = [max(36.0, min(88.0, len(u) * 6.5 + 12.0)) for u in subunits]
            tot_pw = sum(pill_ws) + 6.0 * max(0, len(subunits) - 1)
            px_cur = n["cx"] - tot_pw / 2.0
            py_pill = y0 + n["h"] - 23.0
            for ui, (u, pw_u) in enumerate(zip(subunits, pill_ws)):
                prims.append({"op": "rect", "x": px_cur, "y": py_pill, "w": pw_u, "h": 16.0, "rx": 8.0,
                              "fill": "#ffffff", "stroke": stroke, "stroke_w": 0.9, "opacity": 0.92,
                              "role": "deco", "layer": "layer-nodes"})
                prims.append({"op": "text", "x": px_cur + pw_u / 2.0, "y": py_pill + 8.0, "s": u,
                              "size": 9.5, "anchor": "middle", "fill": "#334155", "weight": "bold",
                              "halo": False, "role": "node_label", "layer": "layer-nodes",
                              "_id": f"subunit-{n['id']}-{ui}"})
                px_cur += pw_u + 6.0
        cur_right = n["cx"] + n["w"] / 2.0 + 4.0
        my = n["cy"] - n["h"] / 2.0 + 2.0
        for m in (n.get("mods", []) or []):
            ms = str(m)
            col = MOD_COLORS.get(ms, "#b45309")
            if len(ms) >= 2:
                bw_m = max(24.0, len(ms) * 6.2 + 9.0)
                bh_m = 18.0
                mx = cur_right - bw_m / 2.0
                prims.append({"op": "rect", "x": cur_right - bw_m, "y": my - bh_m / 2.0,
                              "w": bw_m, "h": bh_m, "rx": bh_m / 2.0, "fill": "#ffffff",
                              "stroke": col, "stroke_w": 1.6, "role": "mod", "layer": "layer-nodes"})
                prims.append({"op": "text", "x": mx, "y": my, "s": ms, "size": 9.0,
                              "anchor": "middle", "fill": col, "weight": "bold", "halo": False,
                              "role": "mod", "layer": "layer-nodes"})
                cur_right -= (bw_m + 3.0)
            else:
                r = 9.5
                mx = cur_right - r
                prims.append({"op": "circle", "cx": mx, "cy": my, "r": r, "fill": "#ffffff",
                              "stroke": col, "stroke_w": 1.6, "role": "mod", "layer": "layer-nodes"})
                prims.append({"op": "text", "x": mx, "y": my, "s": ms, "size": 10.0,
                              "anchor": "middle", "fill": col, "weight": "bold", "halo": False,
                              "role": "mod", "layer": "layer-nodes"})
                cur_right -= (r * 2.0 + 3.0)
