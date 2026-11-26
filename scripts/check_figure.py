#!/usr/bin/env python3
"""check_figure.py — independent SVG-level geometric & layer audit (bounds, overlap, legend, layers).

Usage: python3 check_figure.py figure.svg [--json out.json]
Re-parses the actual SVG bytes (including translate() panel transforms), auditing the delivered file.
"""
from __future__ import annotations
import sys, re, json, argparse
from pathlib import Path
from html import unescape

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from render_preview import parse_svg_dimensions

def _attr(tag, name):
    m = re.search(r'(?:^|\s)' + name + r'''=(["'])([^"']*)\1''', tag)
    return m.group(2) if m else None

def _num(val, default=0.0):
    if val is None:
        return float(default)
    m = re.search(r"-?\d+(?:\.\d+)?", str(val))
    return float(m.group(0)) if m else float(default)

def _text_width(s, size):
    best = 0.0
    for ln in s.split("\n"):
        w = sum(size * (1.0 if ord(ch) > 0x2E80 else 0.62) for ch in ln)
        if w > best:
            best = w
    return max(best, size * 0.6)

def _translate_of(attrs):
    tr = _attr(attrs, "transform") or ""
    m = re.search(r"translate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+))?\s*\)", tr)
    if not m:
        return 0.0, 0.0
    return float(m.group(1)), float(m.group(2) or 0.0)

def audit(svg_text):
    dims = parse_svg_dimensions(svg_text)
    vx0, vy0 = dims["user_x"], dims["user_y"]
    W, H = dims["user_w"], dims["user_h"]

    layers = []
    panel_groups = []
    v = []
    boxes = []
    legend_marks = 0
    g_stack = [(0.0, 0.0)]  # cumulative (dx, dy) from nested <g transform="translate(...)">

    tok_pat = re.compile(
        r'<(?:\w+:)?(g)\b([^>]*)>'
        r'|(</(?:\w+:)?g>)'
        r'|<(?:\w+:)?(rect|circle|ellipse|polyline|polygon)\b([^>]*)/?>'
        r'|<(?:\w+:)?(text)\b([^>]*)>(.*?)</(?:\w+:)?text>',
        re.S
    )
    for m in tok_pat.finditer(svg_text):
        if m.group(1):  # <g ...>
            attrs = m.group(2)
            gid = _attr(attrs, "id")
            if gid:
                layers.append(gid)
            if _attr(attrs, "data-panel"):
                panel_groups.append(_attr(attrs, "data-panel"))
            tdx, tdy = _translate_of(attrs)
            px, py = g_stack[-1]
            if not attrs.rstrip().endswith("/"):
                g_stack.append((px + tdx, py + tdy))
            continue
        if m.group(3):  # </g>
            if len(g_stack) > 1:
                g_stack.pop()
            continue

        dx, dy = g_stack[-1]
        if m.group(4):
            tag, attrs, content = m.group(4), m.group(5), ""
        else:
            tag, attrs, content = m.group(6), m.group(7), m.group(8)

        drole = _attr(attrs, "data-role") or ""
        if drole in ("bg", "deco", "group", ""):
            continue
        fill = _attr(attrs, "fill") or ""
        if tag == "rect" and fill == "#ffffff" and not _attr(attrs, "stroke"):
            continue

        x = _num(_attr(attrs, "x") or _attr(attrs, "cx"), 0) + dx
        y = _num(_attr(attrs, "y") or _attr(attrs, "cy"), 0) + dy
        if tag == "rect":
            w = _num(_attr(attrs, "width"), 0); h = _num(_attr(attrs, "height"), 0)
            bb = [x, y, x + w, y + h]
        elif tag == "circle":
            r = _num(_attr(attrs, "r"), 0)
            bb = [x - r, y - r, x + r, y + r]
        elif tag == "ellipse":
            rx = _num(_attr(attrs, "rx"), 0); ry = _num(_attr(attrs, "ry"), 0)
            bb = [x - rx, y - ry, x + rx, y + ry]
        elif tag in ("polyline", "polygon"):
            pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", attrs)
            xs = [float(a) + dx for a, _ in pts]; ys = [float(b) + dy for _, b in pts]
            if not xs:
                continue
            bb = [min(xs), min(ys), max(xs), max(ys)]
        else:  # text
            size = _num(_attr(attrs, "font-size"), 15)
            anchor = _attr(attrs, "text-anchor") or "middle"
            tspans = re.findall(r"<(?:\w+:)?tspan[^>]*>(.*?)</(?:\w+:)?tspan>", content, re.S)
            if tspans:
                s = "\n".join(unescape(re.sub(r"<[^>]+>", "", t).strip()) for t in tspans)
            else:
                s = unescape(re.sub(r"<[^>]+>", "", content).strip())
            w = _text_width(s, size)
            nlines = max(1, len(s.split("\n")))
            h = size * (1.24 if nlines == 1 else 1.25 * nlines)
            if "rotate" in attrs:
                bb = [x - h / 2.0, y - w / 2.0, x + h / 2.0, y + w / 2.0]
            else:
                x0 = x if anchor == "start" else x - w / 2.0 if anchor == "middle" else x - w
                bb = [x0, y - h / 2.0, x0 + w, y + h / 2.0]

        boxes.append((tag, bb, drole))
        if bb[0] < vx0 - 2 or bb[1] < vy0 - 2 or bb[2] > vx0 + W + 2 or bb[3] > vy0 + H + 2:
            v.append({"code": "out_of_canvas", "tag": tag, "role": drole,
                      "bbox": [round(q, 1) for q in bb]})
        if drole.startswith("legend"):
            legend_marks += 1

    texts = [bb for tag, bb, r in boxes if tag == "text" and r in ("text", "edge_label", "node_label", "legend")]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if not (a[2] <= b[0] + 0.5 or b[2] <= a[0] + 0.5 or a[3] <= b[1] + 0.5 or b[3] <= a[1] + 0.5):
                v.append({"code": "text_overlap", "a": [round(q, 1) for q in a], "b": [round(q, 1) for q in b]})

    out = {"canvas": [W, H], "elements": len(boxes), "layers_found": layers,
           "panel_groups": panel_groups, "layers_named": len(layers) >= 2,
           "legend_marks": legend_marks, "violations": v, "n_violations": len(v)}
    if dims["css_w"] > 0 and dims["css_h"] > 0:
        out["css_size"] = [round(dims["css_w"], 2), round(dims["css_h"], 2)]
    return out

def pixel_audit(png_path):
    """Real pixel-level verification of a rendered PNG (dimensions, ink coverage, border clipping)."""
    p = Path(png_path)
    if not p.exists():
        return {"ok": False, "error": f"PNG not found: {p}"}
    raw = p.read_bytes()
    if not raw.startswith(b"\x89PNG"):
        return {"ok": False, "error": "invalid PNG magic signature"}
    w_hdr = int.from_bytes(raw[16:20], "big") if len(raw) >= 24 else 0
    h_hdr = int.from_bytes(raw[20:24], "big") if len(raw) >= 24 else 0
    arr = None
    backend = "header_only"
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(p).convert("RGB")
        arr = np.asarray(im)
        backend = "PIL+numpy"
    except Exception:
        try:
            import matplotlib.image as mpimg
            import numpy as np
            raw_im = mpimg.imread(str(p))
            if raw_im.ndim == 3:
                arr = (raw_im[:, :, :3] * 255).astype("uint8") if raw_im.dtype.kind == "f" else raw_im[:, :, :3]
                backend = "matplotlib+numpy"
        except Exception:
            arr = None
    if arr is None:
        return {"ok": (w_hdr > 200 and h_hdr > 100), "backend": backend,
                "size_px": [w_hdr, h_hdr], "bytes": len(raw)}
    h_px, w_px = int(arr.shape[0]), int(arr.shape[1])
    # Non-white ink mask (any RGB channel < 248)
    ink = (arr < 248).any(axis=2)
    ink_ratio = float(ink.mean())
    top_clip = int(ink[0:2, :].sum())
    bot_clip = int(ink[-2:, :].sum())
    left_clip = int(ink[:, 0:2].sum())
    right_clip = int(ink[:, -2:].sum())
    border_clipped = (top_clip + bot_clip + left_clip + right_clip) > 0
    # Quantized color diversity (4-bit per channel)
    q = (arr[::max(1, h_px // 250), ::max(1, w_px // 250)] >> 4)
    uniq_colors = int(len({(int(r), int(g), int(b)) for r, g, b in q.reshape(-1, 3)}))
    issues = []
    if ink_ratio < 0.005:
        issues.append("blank_or_nearly_empty_image")
    if border_clipped:
        issues.append(f"border_ink_clipped(t={top_clip},b={bot_clip},l={left_clip},r={right_clip})")
    if uniq_colors < 3:
        issues.append("low_color_diversity")
    return {
        "ok": (not issues),
        "backend": backend,
        "size_px": [w_px, h_px],
        "bytes": len(raw),
        "ink_ratio": round(ink_ratio, 4),
        "border_clipped": border_clipped,
        "quantized_colors": uniq_colors,
        "issues": issues,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--png", dest="png", default=None)
    ap.add_argument("--json", dest="jout")
    a = ap.parse_args()
    r = audit(Path(a.svg).read_text(encoding="utf-8"))
    if a.png:
        r["pixel_audit"] = pixel_audit(a.png)
    if a.jout:
        Path(a.jout).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["n_violations"] == 0 else 2)

if __name__ == "__main__":
    main()
