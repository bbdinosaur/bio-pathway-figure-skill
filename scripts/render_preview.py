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

def _stamp_png_dpi(svg_txt: str, png_path: Path):
    """Set truthful physical pHYs DPI metadata on rasterized SVG PNGs (width_px / (svg_w / 96))."""
    try:
        from PIL import Image
        wm = re.search(r'\bwidth=["\']([0-9.]+)', svg_txt)
        vb = re.search(r'\bviewBox=["\']\s*[0-9.-]+[\s,]+[0-9.-]+[\s,]+([0-9.]+)', svg_txt)
        svg_w = float(wm.group(1)) if wm else (float(vb.group(1)) if vb else 0.0)
        if svg_w <= 10.0:
            return
        with Image.open(png_path) as im:
            pw = im.size[0]
            dpi_val = int(round(pw / (svg_w / 96.0)))
            if 72 <= dpi_val <= 600:
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
            if has_css:
                inlined = _inline_css_for_mupdf(svg_txt)
                doc = m.open(stream=inlined.encode("utf-8"), filetype="svg")
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
            if has_css:
                inlined = _inline_css_for_mupdf(svg_txt)
                doc = m.open(stream=inlined.encode("utf-8"), filetype="svg")
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
