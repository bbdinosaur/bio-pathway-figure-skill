#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mirror.py — scene → matplotlib 镜像渲染 PNG/PDF（SVG 渲染链全部失败时的兜底）。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def render(scene, png=None, pdf=None, dpi=300, fontfile=None, family=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, rcParams
    from matplotlib.patches import FancyBboxPatch, Rectangle, Ellipse
    W, H = scene["w"], scene["h"]
    if not family and fontfile:
        try:
            from matplotlib import font_manager
            font_manager.fontManager.addfont(fontfile)
            family = font_manager.FontProperties(fname=fontfile).get_name()
        except Exception:
            pass
    if not family or not fontfile:
        try:
            import render as _r
            family2, fontfile2 = _r.detect_cjk()
            family = family or family2
            fontfile = fontfile or fontfile2
        except Exception:
            pass
    if fontfile and family is None:
        try:
            font_manager.fontManager.addfont(fontfile)
            family = font_manager.FontProperties(fname=fontfile).get_name()
        except Exception:
            pass
    if family:
        rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
    rcParams["axes.unicode_minus"] = False
    fig = plt.figure(figsize=(W / 100.0, H / 100.0), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    for p in scene["prims"]:
        m = p.get("meta") or {}
        if p["op"] == "rect":
            if m.get("tag") == "patch":
                continue
            common = dict(facecolor=p["fill"] if p["fill"] != "none" else "none",
                          edgecolor=p["stroke"], linewidth=max(p["sw"], 0.1), zorder=2,
                          linestyle=(0, tuple(int(x) for x in p["dash"].split(","))) if p["dash"] else "solid")
            if p["rx"] > 2 and m.get("tag") != "glyph":
                ax.add_patch(FancyBboxPatch((p["x"], p["y"]), p["w"], p["h"],
                            boxstyle="round,pad=0,rounding_size=%g" % min(p["rx"], p["h"] / 2),
                            mutation_aspect=1, **common))
            else:
                ax.add_patch(Rectangle((p["x"], p["y"]), p["w"], p["h"], **common))
        elif p["op"] == "ellipse":
            ax.add_patch(Ellipse((p["cx"], p["cy"]), 2 * p["rx"], 2 * p["ry"],
                        facecolor=p["fill"], edgecolor=p["stroke"],
                        linewidth=max(p["sw"], 0.1), zorder=2))
        elif p["op"] == "line":
            xs = [q[0] for q in p["pts"]]
            ys = [q[1] for q in p["pts"]]
            ls = (0, tuple(int(x) for x in p["dash"].split(","))) if p["dash"] else "solid"
            ax.plot(xs, ys, color=p["stroke"], lw=p["sw"], linestyle=ls,
                    solid_joinstyle="round", zorder=3)
            mk = p.get("marker", "none")
            if mk in ("arrow", "arrowboth") and len(p["pts"]) >= 2:
                (x1, y1), (x2, y2) = p["pts"][-2], p["pts"][-1]
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1), zorder=3,
                            arrowprops=dict(arrowstyle="-|>", color=p["stroke"],
                                            lw=0, mutation_scale=13, shrinkA=0, shrinkB=0))
            if mk == "arrowboth" and len(p["pts"]) >= 2:
                (x1, y1), (x2, y2) = p["pts"][1], p["pts"][0]
                ax.annotate("", xy=(x2, y2), xytext=(x1, y1), zorder=3,
                            arrowprops=dict(arrowstyle="-|>", color=p["stroke"],
                                            lw=0, mutation_scale=13, shrinkA=0, shrinkB=0))
            if mk == "tbar" and len(p["pts"]) >= 2:
                import math as _m
                (x1, y1), (x2, y2) = p["pts"][-2], p["pts"][-1]
                d = _m.hypot(x2 - x1, y2 - y1)
                if d > 1e-3:
                    px, py = -(y2 - y1) / d * 5.5, (x2 - x1) / d * 5.5
                    ax.plot([x2 + px, x2 - px], [y2 + py, y2 - py], color=p["stroke"], lw=max(p["sw"] + 0.4, 2.2), zorder=3)
        elif p["op"] == "text":
            lines = str(p["s"]).split("\n")
            ha = {"start": "left", "middle": "center", "end": "right"}[p["anchor"]]
            bbox = dict(boxstyle="square,pad=0.18", fc="white", ec="none", alpha=0.88) \
                if m.get("halo") else None
            for k, ln in enumerate(lines):
                ax.text(p["x"], p["y"] + k * p["size"] * 1.3, ln, ha=ha, va="baseline",
                        fontsize=p["size"], fontweight=p["weight"], color=p["fill"],
                        bbox=bbox, zorder=4.5,
                        family=rcParams["font.sans-serif"][0] if family else None)
    if png:
        fig.savefig(str(png), dpi=dpi, facecolor="white")
    if pdf:
        fig.savefig(str(pdf), facecolor="white")
    plt.close(fig)
    return {"engine": "matplotlib-mirror", "dpi": dpi}


if __name__ == "__main__":
    sc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    print(json.dumps(render(sc, out / "mirror.png", out / "mirror.pdf", dpi=200)))
