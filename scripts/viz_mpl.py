"""Matplotlib PNG/PDF renderer consuming the same primitives (true rounded rects + preview DPI)."""
from __future__ import annotations

def to_mpl(prims, W, H, dpi, png=None, pdf=None, preview_png=None, preview_dpi=100):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.patches import Polygon, Rectangle, FancyBboxPatch, Circle, Ellipse
    # Use a fixed logical-px -> points scale (72/96 = 0.75 pt/px) so font & stroke sizes
    # stay IDENTICAL regardless of output DPI (100 vs 300 DPI)!
    base_dpi = 96.0
    k = 72.0 / base_dpi
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans", "Noto Sans CJK SC",
                                               "WenQuanYi Zen Hei", "Arial", "Helvetica"]
    matplotlib.rcParams["pdf.fonttype"] = 42  # embed editable TrueType fonts in PDF
    matplotlib.rcParams["ps.fonttype"] = 42
    fig = plt.figure(figsize=(W / base_dpi, H / base_dpi), dpi=base_dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    ax.set_facecolor("white")
    halo = [pe.withStroke(linewidth=2.6 * k, foreground="white")]

    def _zorder(p):
        role = p.get("role", "")
        if role == "bg":
            return 1 if p.get("stroke") in (None, "none") else 2
        if role == "deco":
            lyr = p.get("layer", "")
            if lyr == "layer-nodes":
                return 4.6 if p.get("fill") == "#94a3b8" else 5.2
            if lyr == "layer-legend":
                return 7.8
            return 2.5
        if role == "group":
            return 3
        if role == "edge":
            return 4
        if role == "node":
            return 5
        if role in ("error_bar", "bracket", "data_point", "edge_marker"):
            return 6
        if role == "mod":
            return 7
        if role == "edge_label_bg":
            return 7.6
        if role in ("edge_label", "annotation"):
            return 8
        if role == "legend_bg":
            return 8.0
        if role.startswith("legend"):
            return 8.6 if p["op"] != "text" else 9.0
        return 9

    for p in prims:
        op = p["op"]
        ec = p.get("stroke", "none")
        lw = max((p.get("stroke_w", 1) or 0) * k, 0.1) if ec not in (None, "none") else 0.0
        ls = (0, (2 * k, 4 * k)) if p.get("dotted") else ((0, (7 * k, 5 * k)) if p.get("dashed") else "-")
        z = _zorder(p)
        alpha = p.get("opacity", 1.0)
        if op == "rect":
            rx = float(p.get("rx", 0) or 0)
            if rx > 0.5 and p["w"] > 1.0 and p["h"] > 1.0:
                rx_eff = min(rx, p["w"] * 0.49, p["h"] * 0.49)
                patch = FancyBboxPatch(
                    (p["x"], p["y"]), p["w"], p["h"],
                    boxstyle=f"round,pad=0,rounding_size={rx_eff}",
                    facecolor=p["fill"], edgecolor=(ec if ec != "none" else "none"),
                    linewidth=lw, linestyle=ls, zorder=z, alpha=alpha
                )
            else:
                patch = Rectangle(
                    (p["x"], p["y"]), p["w"], p["h"],
                    facecolor=p["fill"], edgecolor=(ec if ec != "none" else "none"),
                    linewidth=lw, linestyle=ls, zorder=z, alpha=alpha
                )
            ax.add_patch(patch)
        elif op == "circle":
            ax.add_patch(Circle((p["cx"], p["cy"]), p["r"], facecolor=p["fill"],
                         edgecolor=(ec if ec != "none" else "none"), linewidth=lw,
                         linestyle=ls, zorder=z, alpha=alpha))
        elif op == "ellipse":
            ax.add_patch(Ellipse((p["cx"], p["cy"]), p["rx"] * 2, p["ry"] * 2,
                         facecolor=p["fill"], edgecolor=(ec if ec != "none" else "none"),
                         linewidth=lw, linestyle=ls, zorder=z, alpha=alpha))
        elif op in ("polyline", "poly", "polygon"):
            pts = p["pts"]
            if not pts:
                continue
            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
            if op == "polyline":
                ax.plot(xs, ys, color=p.get("stroke", "#333"), linewidth=max(lw, 0.4),
                        linestyle=ls, solid_capstyle="round", solid_joinstyle="round",
                        zorder=z, alpha=alpha)
            else:
                ax.add_patch(Polygon(pts, closed=True, facecolor=p.get("fill", "none"),
                             edgecolor=(ec if ec != "none" else "none"), linewidth=lw,
                             linestyle=ls, zorder=z, alpha=alpha))
        elif op == "text":
            fs = p.get("size", 15) * k
            ha = {"middle": "center", "start": "left", "end": "right"}.get(
                p.get("anchor", "middle"), "center")
            pe_arg = halo if p.get("halo", True) else None
            ax.text(p["x"], p["y"], str(p["s"]), fontsize=fs, ha=ha,
                    va="center", color=p.get("fill", "#1e293b"),
                    fontweight=("bold" if p.get("weight") == "bold" else "normal"),
                    fontstyle=("italic" if p.get("italic") else "normal"),
                    rotation=-p.get("rotate", 0), rotation_mode="anchor",
                    linespacing=1.22, path_effects=pe_arg, zorder=max(z, 9))
    eff_dpi = int(dpi)
    if png:
        eff_dpi = min(int(dpi), max(150, int(9600 * base_dpi / max(1.0, float(max(W, H))))))
        fig.savefig(png, dpi=eff_dpi, format="png", facecolor="white")
    if preview_png:
        fig.savefig(preview_png, dpi=preview_dpi, format="png", facecolor="white")
    if pdf:
        fig.savefig(pdf, format="pdf", facecolor="white")
    plt.close(fig)
    return eff_dpi
