#!/usr/bin/env python3
"""render_preview.py — rasterize any SVG to PNG for visual inspection.

Tries, in order: cairosvg, rsvg-convert, inkscape, ImageMagick convert, resvg.
Usage: python3 render_preview.py in.svg -o out.png [--width 2400]
Exit 0 + prints JSON {png, tool} on success; exit 1 with JSON {error} if none available.
"""
from __future__ import annotations
import sys, json, re, shutil, subprocess, argparse
from pathlib import Path

def _inline_css_for_mupdf(svg_text: str) -> str:
    """In-memory CSS class inliner so MuPDF/pymupdf renders Illustrator/BioRender <style> SVGs faithfully."""
    if "<style" not in svg_text:
        return svg_text
    styles = {}
    for sm in re.finditer(r"<style[^>]*>(.*?)</style>", svg_text, re.S | re.I):
        css = re.sub(r"/\*.*?\*/", "", sm.group(1), flags=re.S)
        for rule in re.finditer(r"([^{}]+)\{([^{}]+)\}", css):
            sels = [s.strip() for s in rule.group(1).split(",")]
            decls = rule.group(2).strip()
            for sel in sels:
                if sel.startswith(".") and " " not in sel and ":" not in sel:
                    cls = sel[1:]
                    styles[cls] = (styles.get(cls, "").rstrip(";") + ";" + decls).strip(";")
    if not styles:
        return svg_text
    def _apply_cls(m):
        tag = m.group(0)
        cm = re.search(r'\bclass=(["\'])([^"\']+)\1', tag)
        if not cm:
            return tag
        merged = []
        for c in cm.group(2).split():
            if c in styles:
                merged.append(styles[c])
        if not merged:
            return tag
        css_inline = ";".join(merged)
        st_m = re.search(r'\bstyle=(["\'])([^"\']*)\1', tag)
        if st_m:
            new_st = css_inline + ";" + st_m.group(2)
            return tag[:st_m.start(2)] + new_st + tag[st_m.end(2):]
        idx = tag.rfind("/>") if tag.rstrip().endswith("/>") else tag.rfind(">")
        return tag[:idx] + f' style="{css_inline}"' + tag[idx:]
    return re.sub(r'<(?:\w+:)?(?:rect|circle|ellipse|path|polygon|polyline|line|text|tspan|g)\b[^>]*\bclass=["\'][^"\']+["\'][^>]*/?>', _apply_cls, svg_text)

_SVG_UNIT_TO_PX = {
    "": 1.0,
    "px": 1.0,
    "in": 96.0,
    "cm": 96.0 / 2.54,
    "mm": 96.0 / 25.4,
    "pt": 96.0 / 72.0,
    "pc": 96.0 / 6.0,
    "q": 96.0 / 101.6,
}

_ROOT_SVG_RE = re.compile(r'<(?:\w+:)?svg\b((?:"[^"]*"|\'[^\']*\'|[^>\'"])*)>', re.S | re.I)
_SVG_LEN_RE = re.compile(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)$')

def _extract_root_svg_attrs(svg_txt: str) -> str:
    """Return attribute text of ONLY the root <svg ...> opening tag (ignoring comments & inner elements)."""
    cleaned = re.sub(r"<!--.*?-->", "", svg_txt or "", flags=re.S)
    m = _ROOT_SVG_RE.search(cleaned)
    return m.group(1) if m else ""

def _parse_svg_attr(tag_attrs: str, name: str):
    """Extract an attribute value (single or double quoted) from a single tag's attribute string."""
    if not tag_attrs:
        return None
    m = re.search(r'(?:^|[\s/])' + re.escape(name) + r'\s*=\s*(["\'])([^"\']*)\1', tag_attrs, re.I)
    return m.group(2) if m else None

def _parse_svg_length_px(val) -> float | None:
    """Convert an SVG absolute CSS length to CSS px (96 px/in). Returns None for '%' or relative/invalid values."""
    if val is None:
        return None
    m = _SVG_LEN_RE.match(str(val).strip())
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    if num <= 0.0:
        return None
    unit = m.group(2).lower()
    if unit == "%" or unit not in _SVG_UNIT_TO_PX:
        return None
    return num * _SVG_UNIT_TO_PX[unit]

def _parse_svg_viewbox(tag_attrs: str):
    """Parse root <svg> viewBox into (min_x, min_y, width, height) floats, or None."""
    vb = _parse_svg_attr(tag_attrs, "viewBox")
    if not vb:
        return None
    parts = [p for p in re.split(r"[\s,]+", vb.strip()) if p]
    if len(parts) < 4:
        return None
    try:
        x0, y0, vw, vh = (float(parts[i]) for i in range(4))
    except ValueError:
        return None
    if vw <= 0.0 or vh <= 0.0:
        return None
    return (x0, y0, vw, vh)

def parse_svg_dimensions(svg_txt: str) -> dict:
    """Parse root <svg> CSS size (px at 96 dpi) and viewBox user-space coordinates.

    Strictly inspects ONLY the root <svg ...> opening tag so inner <rect>/<symbol>
    attributes never pollute canvas size or DPI calculations. Supports single/double
    quotes and CSS units (px, pt, pc, mm, cm, in, Q); '%' falls back to viewBox.
    """
    tag_attrs = _extract_root_svg_attrs(svg_txt)
    vb = _parse_svg_viewbox(tag_attrs)
    w_raw = _parse_svg_attr(tag_attrs, "width")
    h_raw = _parse_svg_attr(tag_attrs, "height")
    w_px = _parse_svg_length_px(w_raw)
    h_px = _parse_svg_length_px(h_raw)
    vb_w = vb[2] if vb else None
    vb_h = vb[3] if vb else None

    if w_px is not None and h_px is not None:
        css_w, css_h = w_px, h_px
    elif w_px is not None:
        css_w = w_px
        css_h = (w_px * vb_h / vb_w) if (vb_w and vb_h) else (vb_h or 0.0)
    elif h_px is not None:
        css_h = h_px
        css_w = (h_px * vb_w / vb_h) if (vb_w and vb_h) else (vb_w or 0.0)
    elif vb is not None:
        css_w, css_h = vb_w, vb_h
    else:
        css_w, css_h = 0.0, 0.0

    if vb is not None:
        user_x, user_y, user_w, user_h = vb
    else:
        user_x, user_y = 0.0, 0.0
        user_w = css_w if css_w > 0.0 else 1000.0
        user_h = css_h if css_h > 0.0 else 800.0

    return {
        "css_w": float(css_w),
        "css_h": float(css_h),
        "user_x": float(user_x),
        "user_y": float(user_y),
        "user_w": float(user_w),
        "user_h": float(user_h),
        "viewbox": vb,
        "width_raw": w_raw,
        "height_raw": h_raw,
    }

def _normalize_pct_for_mupdf(svg_txt: str) -> str:
    """In-memory only: replace root <svg> '%' width/height with resolved CSS px so MuPDF preserves aspect ratio."""
    dims = parse_svg_dimensions(svg_txt)
    if dims["css_w"] <= 0.0 or dims["css_h"] <= 0.0:
        return svg_txt
    w_pct = bool(dims["width_raw"] and "%" in str(dims["width_raw"]))
    h_pct = bool(dims["height_raw"] and "%" in str(dims["height_raw"]))
    if not (w_pct or h_pct):
        return svg_txt
    def _fix_root(m):
        attrs = m.group(1)
        if w_pct:
            attrs = re.sub(
                r'((?:^|[\s/])width\s*=\s*)(["\'])[^"\']*%\s*\2',
                lambda am: f'{am.group(1)}"{dims["css_w"]:.2f}"',
                attrs, count=1, flags=re.I,
            )
        if h_pct:
            attrs = re.sub(
                r'((?:^|[\s/])height\s*=\s*)(["\'])[^"\']*%\s*\2',
                lambda am: f'{am.group(1)}"{dims["css_h"]:.2f}"',
                attrs, count=1, flags=re.I,
            )
        return m.group(0)[:m.start(1) - m.start(0)] + attrs + m.group(0)[m.end(1) - m.start(0):]
    for m in re.finditer(r'<!--.*?-->|' + _ROOT_SVG_RE.pattern, svg_txt, re.S | re.I):
        if m.group(0).startswith("<!--"):
            continue
        return svg_txt[:m.start()] + _fix_root(m) + svg_txt[m.end():]
    return svg_txt

def _stamp_png_dpi(svg_txt: str, png_path: Path):
    """Set truthful physical pHYs DPI metadata on rasterized SVG PNGs (width_px / (svg_css_w / 96))."""
    try:
        from PIL import Image
        dims = parse_svg_dimensions(svg_txt)
        svg_w = dims["css_w"]
        if svg_w <= 10.0:
            return
        with Image.open(png_path) as im:
            im.load()
            pw = im.size[0]
            dpi_val = int(round(pw / (svg_w / 96.0)))
            if 72 <= dpi_val <= 1200:
                cur = im.info.get("dpi")
                if not cur or abs(float(cur[0]) - dpi_val) > 5:
                    im.save(png_path, dpi=(dpi_val, dpi_val))
    except Exception:
        pass

def render(svg, png, width):
    svg_p = Path(svg)
    if not svg_p.exists():
        return None
    svg_txt = svg_p.read_text(encoding="utf-8", errors="replace")
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=str(svg_p), write_to=str(png), output_width=width)
        _stamp_png_dpi(svg_txt, Path(png))
        return "cairosvg"
    except Exception:
        pass
    has_css = "<style" in svg_txt
    if has_css:
        for tool, args in (
            ("rsvg-convert", ["rsvg-convert", "-w", str(width), "-o", str(png), str(svg_p)]),
            ("resvg", ["resvg", "-w", str(width), str(svg_p), str(png)]),
        ):
            if shutil.which(tool):
                try:
                    subprocess.run(args, check=True, capture_output=True, timeout=30)
                    if Path(png).exists() and Path(png).stat().st_size > 1000:
                        _stamp_png_dpi(svg_txt, Path(png))
                        return tool
                except Exception:
                    continue
    for mod in ("pymupdf", "fitz"):
        try:
            m = __import__(mod)
            prep = _normalize_pct_for_mupdf(svg_txt)
            if has_css:
                prep = _inline_css_for_mupdf(prep)
            if prep != svg_txt:
                doc = m.open(stream=prep.encode("utf-8"), filetype="svg")
            else:
                doc = m.open(str(svg_p))
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            pdf = m.open("pdf", pdf_bytes)
            pg = pdf[0]
            scale = max(1.0, float(width) / max(1.0, pg.rect.width))
            pix = pg.get_pixmap(matrix=m.Matrix(scale, scale), alpha=False)
            pix.save(str(png))
            pdf.close()
            if Path(png).exists() and Path(png).stat().st_size > 1000:
                _stamp_png_dpi(svg_txt, Path(png))
                return mod
        except Exception:
            continue
    for tool, args in (
        ("rsvg-convert", ["rsvg-convert", "-w", str(width), "-o", str(png), str(svg_p)]),
        ("resvg", ["resvg", "-w", str(width), str(svg_p), str(png)]),
        ("inkscape", ["inkscape", str(svg_p), "--export-type=png",
                      f"--export-filename={png}", f"--export-width={width}"]),
        ("convert", ["convert", "-limit", "memory", "512MiB", "-limit", "time", "25",
                     "-density", "192", str(svg_p), str(png)]),
    ):
        if shutil.which(tool):
            try:
                subprocess.run(args, check=True, capture_output=True, timeout=30)
                if Path(png).exists() and Path(png).stat().st_size > 1000:
                    _stamp_png_dpi(svg_txt, Path(png))
                    return tool + (" (low fidelity: prefer cairosvg/rsvg-convert)"
                                   if tool == "convert" else "")
            except Exception:
                continue
    return None

def render_pdf(svg, pdf):
    svg_p = Path(svg)
    if not svg_p.exists():
        return None
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2pdf(url=str(svg_p), write_to=str(pdf))
        return "cairosvg"
    except Exception:
        pass
    svg_txt = svg_p.read_text(encoding="utf-8", errors="replace")
    has_css = "<style" in svg_txt
    if has_css and shutil.which("rsvg-convert"):
        try:
            subprocess.run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg_p)],
                           check=True, capture_output=True, timeout=30)
            if Path(pdf).exists() and Path(pdf).stat().st_size > 200:
                return "rsvg-convert"
        except Exception:
            pass
    for mod in ("pymupdf", "fitz"):
        try:
            m = __import__(mod)
            prep = _normalize_pct_for_mupdf(svg_txt)
            if has_css:
                prep = _inline_css_for_mupdf(prep)
            if prep != svg_txt:
                doc = m.open(stream=prep.encode("utf-8"), filetype="svg")
            else:
                doc = m.open(str(svg_p))
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            Path(pdf).write_bytes(pdf_bytes)
            if Path(pdf).exists() and Path(pdf).stat().st_size > 200:
                return mod
        except Exception:
            continue
    for tool, args in (
        ("rsvg-convert", ["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg_p)]),
        ("inkscape", ["inkscape", str(svg_p), "--export-type=pdf", f"--export-filename={pdf}"]),
        ("convert", ["convert", "-limit", "memory", "512MiB", "-limit", "time", "25", str(svg_p), str(pdf)]),
    ):
        if shutil.which(tool):
            try:
                subprocess.run(args, check=True, capture_output=True, timeout=30)
                if Path(pdf).exists() and Path(pdf).stat().st_size > 200:
                    return tool
            except Exception:
                continue
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--pdf", dest="pdf", default=None)
    a = ap.parse_args()
    tool = render(a.svg, a.out, a.width)
    pdf_tool = render_pdf(a.svg, a.pdf) if a.pdf else None
    if tool:
        print(json.dumps({"png": str(a.out), "tool": tool,
                          "pdf": str(a.pdf) if pdf_tool else None,
                          "pdf_tool": pdf_tool}))
    else:
        print(json.dumps({"error": "no svg rasterizer available",
                          "hint": "install cairosvg or rsvg-convert, or open SVG in browser and print to PDF"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
