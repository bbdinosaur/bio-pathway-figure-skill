#!/usr/bin/env python3
"""check_figure.py — independent SVG-level geometric audit (bounds, overlap, legend).

Usage: python3 check_figure.py figure.svg [--json out.json]
Re-parses the actual SVG bytes (no build-time state), so it audits the delivered file.
"""
from __future__ import annotations
import sys, re, json, argparse
from pathlib import Path
from html import unescape

NUM = r"(-?[\d.]+)"

def _attr(tag, name):
    m = re.search(r'(?:^|\s)' + name + r'="([^"]*)"', tag)
    return m.group(1) if m else None

def audit(svg_text):
    vb = _attr(svg_text, "viewBox")
    if vb:
        W = float(vb.split()[2]); H = float(vb.split()[3])
    else:
        W = float(_attr(svg_text, "width") or 1000)
        H = float(_attr(svg_text, "height") or 800)
    v = []
    boxes = []
    legend_edges = 0
    for m in re.finditer(r"<(rect|circle|ellipse|text|polyline|polygon)\b([^>]*)>([^<]*)", svg_text):
        tag, attrs, content = m.group(1), m.group(2), m.group(3)
        x = float(_attr(attrs, "x") or _attr(attrs, "cx") or 0)
        y = float(_attr(attrs, "y") or _attr(attrs, "cy") or 0)
        if tag == "rect":
            w = float(_attr(attrs, "width") or 0); h = float(_attr(attrs, "height") or 0)
            bb = [x, y, x + w, y + h]
        elif tag == "circle":
            r = float(_attr(attrs, "r") or 0)
            bb = [x - r, y - r, x + r, y + r]
        elif tag == "ellipse":
            rx = float(_attr(attrs, "rx") or 0); ry = float(_attr(attrs, "ry") or 0)
            bb = [x - rx, y - ry, x + rx, y + ry]
        elif tag in ("polyline", "polygon"):
            pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", attrs)
            xs = [float(a) for a, b in pts]; ys = [float(b) for a, b in pts]
            if not xs:
                continue
            bb = [min(xs), min(ys), max(xs), max(ys)]
        else:  # text
            size = float(_attr(attrs, "font-size") or 15)
            anchor = _attr(attrs, "text-anchor") or "middle"
            s = unescape(content.strip())
            w = 0.62 * size * max(1, len(s))
            if "rotate" in attrs:
                bb = [x - size, y - w / 2, x + size, y + w / 2]
                boxes.append((tag, bb, drole))
                if bb[0] < -2 or bb[1] < -2 or bb[2] > W + 2 or bb[3] > H + 2:
                    v.append({"code": "out_of_canvas", "tag": tag, "bbox": [round(q, 1) for q in bb]})
                continue
            x0 = x if anchor == "start" else x - w / 2 if anchor == "middle" else x - w
            bb = [x0, y - size * 0.62, x0 + w, y + size * 0.62]
            if 'paint-order="stroke"' not in attrs:
                continue
        style = _attr(attrs, "style") or ""
        drole = _attr(attrs, "data-role") or ""
        if drole in ("bg", "deco", ""):
            continue
        fill = _attr(attrs, "fill") or ""
        if tag == "rect" and fill == "#ffffff":
            continue  # canvas backdrop
        boxes.append((tag, bb, drole))
        if bb[0] < -2 or bb[1] < -2 or bb[2] > W + 2 or bb[3] > H + 2:
            v.append({"code": "out_of_canvas", "tag": tag, "bbox": [round(q, 1) for q in bb]})
        if drole.startswith("legend"):
            legend_edges += 1
    texts = [(bb) for tag, bb, r in boxes if tag == "text" and r in ("text", "edge_label", "node_label")]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if not (a[2] <= b[0] + 0.5 or b[2] <= a[0] + 0.5 or a[3] <= b[1] + 0.5 or b[3] <= a[1] + 0.5):
                v.append({"code": "text_overlap", "a": [round(q, 1) for q in a], "b": [round(q, 1) for q in b]})
    return {"canvas": [W, H], "elements": len(boxes), "legend_marks": legend_edges,
            "violations": v, "n_violations": len(v)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--json", dest="jout")
    a = ap.parse_args()
    r = audit(Path(a.svg).read_text(encoding="utf-8"))
    if a.jout:
        Path(a.jout).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["n_violations"] == 0 else 2)

if __name__ == "__main__":
    main()
