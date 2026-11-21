"""Chart mode: bars with error bars, significance stars, group legend, value labels."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import PALETTES, FONT_STACK
from viz_geom import text_bbox

def build_chart(spec, scale_name="regular"):
    ch = spec.get("chart", {})
    bars = ch.get("bars", [])
    W, H = ch.get("width", 1000), ch.get("height", 640)
    prims = [{"op": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": "#ffffff",
              "stroke": "none", "stroke_w": 0, "role": "bg"}]
    if spec.get("title"):
        prims.append({"op": "text", "x": W / 2, "y": 34, "s": spec["title"], "size": 20,
                      "anchor": "middle", "fill": "#0f172a", "weight": "bold", "role": "text"})
    m = {"l": 96, "r": 24, "t": 78, "b": 96}
    gw, gh = W - m["l"] - m["r"], H - m["t"] - m["b"]
    groups = []
    for b in bars:
        if b.get("group") and b["group"] not in groups:
            groups.append(b["group"])
    q = PALETTES["qual"]
    vals = [b.get("value", 0) for b in bars]
    errs = [b.get("err") or 0 for b in bars]
    vmin = min(0.0, min(vals) - 0.0)
    vmax = max(0.0, max(v + e for v, e in zip(vals, errs)))
    rng = (vmax - vmin) or 1.0
    top, bot = vmax * 1.18, vmin - rng * 0.12
    span = top - bot
    import math
    raw = span / 4.0
    k = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = 10 * k
    for mm in (1, 2, 2.5, 5, 10):
        if raw <= mm * k:
            step = mm * k
            break
    y0line = m["t"] + gh * (1 - (0 - bot) / span)  # zero baseline
    ticks = []
    tv = math.ceil(bot / step) * step
    while tv <= top + 1e-9:
        if tv >= bot - 1e-9:
            ticks.append(round(tv, 10))
        tv += step
    n = len(bars)
    bw = gw / max(n, 1) * 0.62
    for yv in ticks:
        gy = m["t"] + gh * (1 - (yv - bot) / span)
        prims.append({"op": "polyline", "pts": [[m["l"], gy], [m["l"] + gw, gy]],
                      "stroke": "#e5e7eb", "stroke_w": 1, "role": "deco"})
        lbl = f"{yv:.4g}".rstrip("0").rstrip(".") if isinstance(yv, float) else str(yv)
        prims.append({"op": "text", "x": m["l"] - 10, "y": gy, "s": lbl,
                      "size": 12, "anchor": "end", "fill": "#64748b", "role": "deco"})
    prims.append({"op": "polyline", "pts": [[m["l"], y0line], [m["l"] + gw, y0line]],
                  "stroke": "#9ca3af", "stroke_w": 1.4, "role": "deco"})
    for i, b in enumerate(bars):
        val, err = b.get("value", 0), b.get("err") or 0
        bx = m["l"] + gw * (i + 0.5) / n - bw / 2
        yval = m["t"] + gh * (1 - (val - bot) / span)
        by = min(yval, y0line)
        bh = abs(y0line - yval)
        col = b.get("fill") or (q[groups.index(b.get("group")) % len(q)] if b.get("group") in groups else q[0])
        prims.append({"op": "rect", "x": bx, "y": by, "w": bw, "h": bh, "rx": 2,
                      "fill": col, "stroke": "#ffffff", "stroke_w": 0.5, "role": "node"})
        if err:
            ex = bx + bw / 2
            eh = gh * (err / span)
            ey0, ey1 = yval - eh, yval + eh
            prims.append({"op": "polyline", "pts": [[ex, ey0], [ex, ey1]], "stroke": "#1f2937",
                          "stroke_w": 1.4, "role": "edge"})
            for yy in (ey0, ey1):
                prims.append({"op": "polyline", "pts": [[ex - 5, yy], [ex + 5, yy]],
                              "stroke": "#1f2937", "stroke_w": 1.4, "role": "edge"})
        vy = yval - gh * (err / span) - 12 if val >= 0 else yval + gh * (err / span) + 16
        prims.append({"op": "text", "x": bx + bw / 2, "y": vy,
                      "s": f"{val:.4g}".rstrip("0").rstrip("."), "size": 12.5, "anchor": "middle",
                      "fill": "#1e293b", "weight": "bold", "role": "text"})
        lbl = str(b.get("label", f"#{i+1}"))
        size = 12.5
        while size > 8.5 and 0.62 * size * len(lbl) > gw / n:
            size -= 0.5
        prims.append({"op": "text", "x": bx + bw / 2, "y": H - m["b"] + 18, "s": lbl, "size": size,
                      "anchor": "middle", "fill": "#1e293b", "role": "text"})
    for st in ch.get("stars", []):
        i, j = st.get("pair", [0, 1])
        if i < n and j < n:
            x0 = m["l"] + gw * (i + 0.5) / n
            x1 = m["l"] + gw * (j + 0.5) / n
            ybar = m["t"] + 16
            prims.append({"op": "polyline", "pts": [[x0, ybar], [x0, ybar + 8], [x1, ybar + 8],
                          [x1, ybar]], "stroke": "#334155", "stroke_w": 1.2, "role": "edge"})
            prims.append({"op": "text", "x": (x0 + x1) / 2, "y": ybar + 2, "s": str(st.get("text", "ns")),
                          "size": 14, "anchor": "middle", "fill": "#0f172a", "weight": "bold", "role": "text"})
    if ch.get("x_label"):
        prims.append({"op": "text", "x": m["l"] + gw / 2, "y": H - 30, "s": ch["x_label"], "size": 14,
                      "anchor": "middle", "fill": "#334155", "role": "text"})
    if ch.get("y_label"):
        prims.append({"op": "text", "x": 26, "y": m["t"] + gh / 2, "s": ch["y_label"], "size": 14,
                      "anchor": "middle", "fill": "#334155", "rotate": -90, "role": "text"})
    ly = m["t"] + 4
    for g in groups:
        prims.append({"op": "rect", "x": W - m["r"] - 190, "y": ly - 10, "w": 14, "h": 14, "rx": 2,
                      "fill": q[groups.index(g) % len(q)], "stroke": "none", "stroke_w": 0,
                      "role": "legend"})
        prims.append({"op": "text", "x": W - m["r"] - 170, "y": ly, "s": str(g), "size": 12.5,
                      "anchor": "start", "fill": "#334155", "role": "legend"})
        ly += 20
    if ch.get("y_note"):
        prims.append({"op": "text", "x": m["l"], "y": H - 12, "s": ch["y_note"], "size": 11.5,
                      "anchor": "start", "fill": "#64748b", "italic": True, "role": "text"})
    return prims, W, H, [], []
