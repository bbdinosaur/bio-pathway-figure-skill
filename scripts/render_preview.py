#!/usr/bin/env python3
"""render_preview.py — rasterize any SVG to PNG for visual inspection.

Tries, in order: cairosvg, rsvg-convert, inkscape, ImageMagick convert, resvg.
Usage: python3 render_preview.py in.svg -o out.png [--width 2400]
Exit 0 + prints JSON {png, tool} on success; exit 1 with JSON {error} if none available.
"""
from __future__ import annotations
import sys, json, shutil, subprocess, argparse
from pathlib import Path

def render(svg, png, width):
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=width)
        return "cairosvg"
    except Exception:
        pass
    for tool, args in (
        ("rsvg-convert", ["rsvg-convert", "-w", str(width), "-o", str(png), str(svg)]),
        ("resvg", ["resvg", "-w", str(width), str(svg), str(png)]),
        ("inkscape", ["inkscape", str(svg), "--export-type=png",
                      f"--export-filename={png}", f"--export-width={width}"]),
        ("convert", ["convert", "-density", "192", str(svg), str(png)]),
    ):
        if shutil.which(tool):
            try:
                subprocess.run(args, check=True, capture_output=True)
                if Path(png).exists() and Path(png).stat().st_size > 0:
                    return tool
            except Exception:
                continue
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--width", type=int, default=2400)
    a = ap.parse_args()
    tool = render(a.svg, a.out, a.width)
    if tool:
        print(json.dumps({"png": str(a.out), "tool": tool}))
    else:
        print(json.dumps({"error": "no svg rasterizer available",
                          "hint": "install cairosvg or rsvg-convert, or open SVG in browser and print to PDF"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
