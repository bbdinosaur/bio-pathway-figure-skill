#!/usr/bin/env python3
"""Re-render any SVG (preserving native viewBox/dims) to PNG + @2x PNG + PDF.

Used by source-preserving edit mode: edit the SVG directly, then run
  python3 ga_render.py --svg edited.svg [--outdir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gaconfig import parse_svg_dims  # noqa: E402
from ga_pipeline import render, render_hi_res, verify_exports  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--hires-dpi", type=int, default=0)
    a = ap.parse_args()
    svg = Path(a.svg).resolve()
    outdir = Path(a.outdir).resolve() if a.outdir else svg.parent
    outdir.mkdir(parents=True, exist_ok=True)
    cw, ch = parse_svg_dims(svg.read_text(encoding="utf-8", errors="ignore"))
    log = []
    png = outdir / (svg.stem + ".png")
    pdf = outdir / (svg.stem + ".pdf")
    eng = render(svg, png, pdf, log)
    if a.hires_dpi > 0:
        render_hi_res(pdf, outdir / f"{svg.stem}_{a.hires_dpi}dpi.png", dpi=a.hires_dpi)
    rep = {"svg": str(svg), "canvas": [cw, ch], "render_engine": eng, "render_log": log}
    ec = verify_exports(png, pdf, rep, hires_dpi=a.hires_dpi) if png.exists() else {}
    (outdir / "_build_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"engine": eng, "canvas": [cw, ch], "png": str(png),
                      "pdf": str(pdf), "export_check": ec, "log": log},
                     ensure_ascii=False))
    ok = png.exists() and pdf.exists() and ec.get("pdf", {}).get("ok")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
