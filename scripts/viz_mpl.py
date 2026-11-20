"""Matplotlib PNG/PDF renderer consuming the same primitives (guaranteed raster export)."""
from __future__ import annotations

def to_mpl(prims, W, H, dpi, png=None, pdf=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.patches import Polygon, Rectangle, Circle, Ellipse
    k = 72.0 / dpi  # px -> points
    import matplotlib as _mpl
    _mpl.rcParams["font.family"] = "sans-serif"
    _mpl.rcParams["font.sans-serif"] = ["DejaVu Sans", "Noto Sans CJK SC",
                                         "WenQuanYi Zen Hei", "Arial", "Helvetica"]
    fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.set_facecolor("white")
    halo = [pe.withStroke(linewidth=2.6 / k * k, foreground="white")]
    for p in prims:
        op = p["op"]; role = p.get("role", "")
        ec = p.get("stroke", "none")
        lw = max((p.get("stroke_w", 1) or 0) * k, 0.1)
        ls = (0, (7 * k, 5 * k)) if p.get("dashed") else "-"
        if op == "rect":
            ax.add_patch(Rectangle((p["x"], p["y"]), p["w"], p["h"],
                         facecolor=p["fill"], edgecolor=ec, linewidth=lw if ec != "none" else 0,
                         linestyle=ls, zorder=2 if role == "bg" else 5,
                         alpha=p.get("opacity", 1)))
        elif op == "circle":
            ax.add_patch(Circle((p["cx"], p["cy"]), p["r"], facecolor=p["fill"],
                         edgecolor=ec, linewidth=lw if ec != "none" else 0, zorder=6))
        elif op == "ellipse":
            ax.add_patch(Ellipse((p["cx"], p["cy"]), p["rx"] * 2, p["ry"] * 2,
                         facecolor=p["fill"], edgecolor=ec,
                         linewidth=lw if ec != "none" else 0, zorder=5))
        elif op in ("polyline", "poly", "polygon"):
            pts = p["pts"]
            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
            if op == "polyline":
                ax.plot(xs, ys, color=p.get("stroke", "#333"), linewidth=max(lw, 0.4),
                        linestyle=ls, solid_capstyle="round", zorder=4,
                        alpha=p.get("opacity", 1))
            else:
                ax.add_patch(Polygon(pts, closed=True, facecolor=p.get("fill", "none"),
                             edgecolor=ec if ec != "none" else "none", linewidth=lw,
                             zorder=6))
        elif op == "text":
            fs = p.get("size", 15) * k
            ha = {"middle": "center", "start": "left", "end": "right"}.get(
                p.get("anchor", "middle"), "center")
            ax.text(p["x"], p["y"], str(p["s"]), fontsize=fs, ha=ha,
                    va="center", color=p.get("fill", "#1e293b"),
                    fontweight=("bold" if p.get("weight") == "bold" else "normal"),
                    fontstyle=("italic" if p.get("italic") else "normal"),
                    rotation=p.get("rotate", 0), rotation_mode="anchor",
                    path_effects=halo, zorder=9)
    for ext, path in (("png", png), ("pdf", pdf)):
        if path:
            fig.savefig(path, dpi=dpi, format=ext, facecolor="white")
    plt.close(fig)
