#!/usr/bin/env python3
"""build_pptx.py — package a figure into an editable slide deck (答辩/汇报交付).

Usage: python3 build_pptx.py --png figure1.png --title "..." [--case-id ID]
       [--subtitle "..."] [--footer "..."] [--out-dir DIR] [--stem figure1]
Produces <stem>.pptx (16:9, full-bleed figure + editable title/footer text boxes).
Rendered preview check: convert with soffice -> pdf -> png (see SKILL.md S5).
"""
import argparse, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", required=True)
    ap.add_argument("--title", default="Figure")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--footer", default="")
    ap.add_argument("--case-id", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stem", default="figure_slides")
    a = ap.parse_args()
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from PIL import Image
        import io
    except Exception as e:
        print(json.dumps({"error": "python-pptx/Pillow unavailable: %s" % e,
                          "fallback": "deliver PNG/PDF directly"}))
        sys.exit(1)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    # title (editable text box)
    tb = slide.shapes.add_textbox(Inches(0.45), Inches(0.22), Inches(12.4), Inches(0.7))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run(); r.text = a.title
    r.font.size = Pt(28); r.font.bold = True
    # subtitle line
    if a.subtitle:
        tb2 = slide.shapes.add_textbox(Inches(0.47), Inches(0.86), Inches(12.4), Inches(0.4))
        p2 = tb2.text_frame.paragraphs[0]
        r2 = p2.add_run(); r2.text = a.subtitle
        r2.font.size = Pt(13)
    # figure centered in remaining area, preserving aspect
    im = Image.open(a.png)
    iw, ih = im.size
    area_w, area_h = 12.6, 5.6  # inches available
    scale = min(area_w / iw, area_h / ih)
    w_in, h_in = iw * scale, ih * scale
    x0 = (13.333 - w_in) / 2
    y0 = 1.35 + (area_h - h_in) / 2
    with open(a.png, "rb") as f:
        slide.shapes.add_picture(io.BytesIO(f.read()), Inches(x0), Inches(y0),
                                 Inches(w_in), Inches(h_in))
    # footer (editable; carries provenance/audit note)
    tb3 = slide.shapes.add_textbox(Inches(0.45), Inches(7.02), Inches(12.4), Inches(0.38))
    p3 = tb3.text_frame.paragraphs[0]
    r3 = p3.add_run()
    r3.text = (a.footer or ("case_id: %s | editable source + audit trail in result.json"
                            % a.case_id)).strip()
    r3.font.size = Pt(10)
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, a.stem + ".pptx")
    prs.save(out)
    # real rendered preview (office -> pdf -> png) for inspection compliance
    preview = None
    try:
        import subprocess, tempfile, shutil
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "lo_profile")
            subprocess.run(["soffice", "-env:UserInstallation=file://%s" % prof,
                            "--headless", "--convert-to", "pdf",
                            "--outdir", td, out], check=True, capture_output=True,
                           timeout=180)
            pdfs = [f for f in os.listdir(td) if f.endswith(".pdf")]
            if pdfs:
                pdf_path = os.path.join(a.out_dir, a.stem + "_deck.pdf")
                shutil.move(os.path.join(td, pdfs[0]), pdf_path)
                preview = os.path.join(a.out_dir, a.stem + "_deck_preview.png")
                subprocess.run(["pdftoppm", "-png", "-r", "100", "-singlefile",
                                pdf_path, preview[:-4]], check=True,
                               capture_output=True, timeout=120)
    except Exception as e:
        preview = None
        note = str(e)
    print(json.dumps({"pptx": out, "slides_pdf": os.path.join(
        a.out_dir, a.stem + "_deck.pdf") if os.path.exists(
        os.path.join(a.out_dir, a.stem + "_deck.pdf")) else None,
        "preview": preview}, indent=1))


if __name__ == "__main__":
    main()
