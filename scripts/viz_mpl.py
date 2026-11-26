"""Matplotlib PNG/PDF renderer consuming the same primitives (true rounded rects + CJK font auto-resolve)."""
from __future__ import annotations

_CJK_FONT_CACHE = [False, None]  # [initialized, path_or_None]

def _find_cjk_font():
    """Find a real installed CJK font file (excluding LastResort) so Chinese labels never render as tofu."""
    if _CJK_FONT_CACHE[0]:
        return _CJK_FONT_CACHE[1]
    _CJK_FONT_CACHE[0] = True
    try:
        import matplotlib.font_manager as fm
        from matplotlib.ft2font import FT2Font
        prefs = ("wenquanyi zen hei", "wenquanyi micro hei", "noto sans cjk sc",
                 "source han sans", "microsoft yahei", "pingfang sc", "simhei",
                 "noto serif cjk sc", "droid sans fallback", "ar pl uming cn", "ipagothic")
        cands = []
        for f in fm.fontManager.ttflist:
            nl = f.name.lower()
            if "last resort" in nl or "lastresort" in f.fname.lower():
                continue
            rank = next((i for i, k in enumerate(prefs) if k in nl), None)
            if rank is not None:
                cands.append((rank, f.fname))
        cands.sort(key=lambda t: t[0])
        seen = set()
        for _, fn in cands:
            if fn in seen:
                continue
            seen.add(fn)
            try:
                ft = FT2Font(fn)
                if ft.get_char_index(ord("信")) != 0 and ft.get_char_index(ord("A")) != 0:
                    _CJK_FONT_CACHE[1] = fn
                    return fn
            except Exception:
                pass
    except Exception:
        pass
    return None

def to_mpl(prims, W, H, dpi, png=None, pdf=None, preview_png=None, preview_dpi=100):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Polygon, Rectangle, FancyBboxPatch, Circle, Ellipse
    cjk_font_path = _find_cjk_font() if any(
        p.get("op") == "text" and any(ord(c) > 0x2E80 for c in str(p.get("s", "")))
        for p in prims
    ) else None
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
            if lyr == "layer-groups":
                return 3.4
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
            txt_s = str(p["s"])
            fw = "bold" if p.get("weight") == "bold" else "normal"
            fst = "italic" if p.get("italic") else "normal"
            kw_font = {"fontsize": fs, "fontweight": fw, "fontstyle": fst}
            if cjk_font_path and any(ord(ch) > 0x2E80 for ch in txt_s):
                kw_font = {"fontproperties": FontProperties(fname=cjk_font_path, size=fs, weight=fw, style=fst)}
            ax.text(p["x"], p["y"], txt_s, ha=ha,
                    va="center", color=p.get("fill", "#1e293b"),
                    rotation=-p.get("rotate", 0), rotation_mode="anchor",
                    linespacing=1.22, path_effects=pe_arg, zorder=max(z, 9), **kw_font)
    eff_dpi = int(dpi)
    if png:
        eff_dpi = min(int(dpi), max(150, int(5200 * base_dpi / max(1.0, float(max(W, H))))))
        fig.savefig(png, dpi=eff_dpi, format="png", facecolor="white")
    if preview_png:
        fig.savefig(preview_png, dpi=preview_dpi, format="png", facecolor="white")
    if pdf:
        fig.savefig(pdf, format="pdf", facecolor="white")
    plt.close(fig)
    return eff_dpi
