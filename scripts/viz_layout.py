"""Mechanism layout: compartments, nodes -> primitives (part 1)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import NODE_STYLES, COMP_STYLES, FONT_STACK, text_w
from viz_geom import bbox_of

BAND_H = {"exterior": 92, "membrane": 66, "cytosol": 250, "nucleus": 250,
          "organelle": 160, "custom": 190}
TOP = 74
LEFT = 56
GAP = 12

def auto_compartment_bands(comps):
    bands, y = [], TOP
    for c in comps:
        h = float(c.get("y1", 0) - c.get("y0", 0)) if c.get("y1") else BAND_H.get(c.get("kind", "custom"), 190)
        bands.append({"id": c["id"], "y0": y, "y1": y + h, "h": h})
        y += h + GAP
    return bands, y

def draw_compartments(comps, bands, plot_w, prims):
    x0, x1 = LEFT - 24, LEFT + plot_w + 24
    for c, b in zip(comps, bands):
        st = COMP_STYLES.get(c.get("kind", "custom"), COMP_STYLES["custom"])
        prims.append({"op": "rect", "x": x0, "y": b["y0"], "w": x1 - x0, "h": b["h"],
                      "rx": 10, "fill": st["fill"], "stroke": st["border"],
                      "stroke_w": 1.2, "role": "bg"})
        lbl = c.get("label", c["id"])
        lx = x0 + 12
        ly = b["y1"] - 12
        prims.append({"op": "text", "x": lx, "y": ly, "s": lbl, "size": 13,
                      "anchor": "start", "fill": "#64748b", "weight": "bold",
                      "role": "deco"})
        if c.get("kind") == "membrane":
            n = int((x1 - x0) // 26)
            for i in range(1, n):
                tx = x0 + i * 26
                prims.append({"op": "polyline", "pts": [[tx, b["y0"]], [tx, b["y0"] + 5]],
                              "stroke": "#94a3b8", "stroke_w": 1.2, "role": "deco"})
                prims.append({"op": "polyline", "pts": [[tx, b["y1"]], [tx, b["y1"] - 5]],
                              "stroke": "#94a3b8", "stroke_w": 1.2, "role": "deco"})

def tighten_bands(comps, bands, placed):
    """Shrink each band to its node extent (+padding); membrane keeps a minimum height.
    Keeps declared heights when the spec pinned y0/y1 explicitly."""
    from copy import deepcopy
    out = deepcopy(bands)
    if not out:
        return out
    pinned = {c["id"] for c in comps if c.get("y1")}
    byid = {b["id"]: b for b in out}
    for c, b in zip(comps, bands):
        nid = c["id"]
        ns = [n for n in placed if n.get("compartment") == nid]
        if not ns or nid in pinned:
            continue
        top = min(n["cy"] - n["h"] / 2 for n in ns)
        bot = max(n["cy"] + n["h"] / 2 for n in ns)
        kind = c.get("kind", "custom")
        hmin = 66 if kind == "membrane" else 110
        need = (bot - b["y0"]) + 26
        h = max(hmin, need)
        byid[nid]["y1"] = b["y0"] + h
        byid[nid]["h"] = h
    # re-stack following bands to remove gaps
    y = out[0]["y0"]
    for b in out:
        b["y0"] = y
        b["y1"] = y + b["h"]
        y = b["y1"] + GAP
    return out

def node_size(n, gap):
    lbl = str(n.get("label", n["id"]))
    w = n.get("w") or max(92, text_w(lbl, 15) + 30)
    h = n.get("h") or 46
    return w, h

def place_nodes(spec, bands, comp_kind, gap, plot_w=0):
    """Assign cx, cy, w, h to each node. Returns placed list."""
    bmap = {b["id"]: b for b in bands}
    placed = []
    max_total = 0
    bycomp = {}
    for n in spec.get("nodes", []):
        bycomp.setdefault(n.get("compartment") or "_", []).append(n)
    totals = {}
    for cid, group in bycomp.items():
        t = sum(node_size(n, gap)[0] for n in group) + gap * max(0, len(group) - 1)
        totals[cid] = t
        max_total = max(max_total, t)
    plot_w = max(plot_w, max_total, 520)
    for cid, group in bycomp.items():
        b = bmap.get(cid)
        sizes = [node_size(n, gap) for n in group]
        sm = spec.get("size_map") or {}
        have_scale = sm.get("min") is not None and sm.get("max") is not None
        total = sum(s[0] for s in sizes) + gap * max(0, len(sizes) - 1)
        row_w = max(total, 520)
        x = LEFT + max(0.0, (plot_w - total) / 2.0)
        # serpentine 2-row fallback for very wide cascades
        rows = 2 if total > 1700 and len(group) >= 6 else 1
        half = (len(group) + 1) // 2
        for idx, (n, (w, h)) in enumerate(zip(group, sizes)):
            if have_scale and isinstance(n.get("value"), (int, float)):
                tv = (n["value"] - sm["min"]) / ((sm["max"] - sm["min"]) or 1)
                tv = min(1.0, max(0.0, tv))
                h = h * (0.72 + 0.56 * tv)
            kind = n.get("kind", "protein")
            if b and (comp_kind.get(cid) == "membrane" or n.get("span_band")):
                h = max(h, b["y1"] - b["y0"] - 4)
                cy = (b["y0"] + b["y1"]) / 2.0
            else:
                if b:
                    if rows == 1:
                        cy = (b["y0"] + b["y1"]) / 2.0
                    else:
                        cy = (b["y0"] + b["y1"]) / 2.0 + (-b["h"] * 0.24 if idx < half else b["h"] * 0.24)
                else:
                    cy = TOP + 140
            cx = n.get("x") if n.get("x") else x + w / 2.0
            cy = n.get("y") if n.get("y") else cy
            placed.append({**n, "cx": cx, "cy": cy, "w": w, "h": h,
                           "shape": NODE_STYLES.get(kind, {}).get("shape", "rect")})
            x += w + gap
        max_total = max(max_total, total)
    return placed, max(max_total, 520)
