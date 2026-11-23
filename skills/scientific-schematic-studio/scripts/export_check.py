#!/usr/bin/env python3
"""export_check.py — journal-export compliance checks for PNG/PDF/SVG.

Usage: python3 export_check.py --png f.png --pdf f.pdf --svg f.svg \
       --width-mm 180 --dpi 300 [--probe "TLR4,TNF"] [--out checks.json]
PNG: dpi metadata + pixel size vs physical mm. PDF: page size, embedded fonts,
text extraction (selectable text + probe words). SVG: valid header, <text>,
semantic layers. Exit 1 on errors.
"""
import argparse, json, re, subprocess, sys, os

MM = 25.4


def _import_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def _check_pdf_poppler(path, width_mm, probes):
    """Fallback PDF check using poppler-utils (pdfinfo + pdffonts + pdftotext)."""
    errs, info = [], {}
    w_mm = h_mm = None
    r_info = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=20)
    if r_info.returncode == 0:
        m = re.search(r"Page size:\s*([\d.]+)\s*x\s*([\d.]+)\s*pts", r_info.stdout)
        if m:
            w_mm = float(m.group(1)) / 72.0 * MM
            h_mm = float(m.group(2)) / 72.0 * MM
    embedded, notemb = [], []
    r_fnt = subprocess.run(["pdffonts", path], capture_output=True, text=True, timeout=20)
    if r_fnt.returncode == 0:
        for line in r_fnt.stdout.splitlines()[2:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            fname = parts[0]
            # pdffonts columns: name type encoding emb sub uni object ID
            emb_tok = None
            for tok in parts[1:]:
                if tok in ("yes", "no"):
                    emb_tok = tok
                    break
            if emb_tok == "yes":
                embedded.append(fname)
            elif emb_tok == "no":
                notemb.append(fname)
    r_txt = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=20)
    text = r_txt.stdout.strip() if r_txt.returncode == 0 else ""
    if w_mm is None and not text and r_info.returncode != 0:
        raise ImportError("neither pymupdf nor poppler pdfinfo/pdftotext available")
    missing = [p for p in probes if p and p not in text]
    info["pdf"] = {
        "path": path,
        "page_mm": [round(w_mm, 1), round(h_mm, 1)] if w_mm is not None else None,
        "fonts_embedded": embedded, "fonts_not_embedded": notemb,
        "text_chars": len(text), "probes_missing": missing,
        "checker": "poppler",
    }
    if notemb:
        errs.append("PDF has non-embedded fonts: %s" % ", ".join(notemb))
    if len(text) < 5:
        errs.append("PDF text layer nearly empty (text not selectable)")
    if width_mm and w_mm is not None and abs(w_mm - width_mm) / width_mm > 0.05:
        errs.append("PDF width %.1fmm != expected %.1fmm" % (w_mm, width_mm))
    if missing:
        errs.append("probe labels missing from PDF text: %s" % ", ".join(missing))
    return errs, info


def check_png(path, width_mm, want_dpi):
    from PIL import Image
    im = Image.open(path)
    dpi = im.info.get("dpi", (None, None))
    dpi_x = float(dpi[0]) if dpi and dpi[0] else None
    px_w, px_h = im.size
    errs, info = [], {}
    info["png"] = {"path": path, "pixel": [px_w, px_h], "dpi_x": dpi_x}
    if dpi_x is None:
        errs.append("PNG lacks dpi metadata")
    elif want_dpi and abs(dpi_x - want_dpi) / want_dpi > 0.05:
        errs.append("PNG dpi %.0f != requested %d" % (dpi_x, want_dpi))
    eff_mm = px_w / (dpi_x or want_dpi or 300.0) * MM
    if width_mm and abs(eff_mm - width_mm) / width_mm > 0.05:
        errs.append("PNG physical width %.1fmm != expected %.1fmm" % (eff_mm, width_mm))
    info["png"]["physical_mm"] = round(eff_mm, 1)
    return errs, info


def check_pdf(path, width_mm, probes):
    try:
        pymupdf = _import_pymupdf()
    except ImportError:
        return _check_pdf_poppler(path, width_mm, probes)
    errs, info = [], {}
    doc = pymupdf.open(path)
    page = doc[0]
    w_pt, h_pt = page.rect.width, page.rect.height
    w_mm, h_mm = w_pt / 72.0 * MM, h_pt / 72.0 * MM
    fonts = page.get_fonts(full=True)
    embedded, notemb = [], []
    for f in fonts:
        ext, basefont = f[1], f[3]
        if ext and ext != "n/a":
            embedded.append(basefont)
        else:
            notemb.append(basefont)
    text = page.get_text().strip()
    missing = [p for p in probes if p and p not in text]
    info["pdf"] = {
        "path": path, "page_mm": [round(w_mm, 1), round(h_mm, 1)],
        "fonts_embedded": embedded, "fonts_not_embedded": notemb,
        "text_chars": len(text), "probes_missing": missing
    }
    if notemb:
        errs.append("PDF has non-embedded fonts: %s" % ", ".join(notemb))
    if len(text) < 5:
        errs.append("PDF text layer nearly empty (text not selectable)")
    if width_mm and abs(w_mm - width_mm) / width_mm > 0.05:
        errs.append("PDF width %.1fmm != expected %.1fmm" % (w_mm, width_mm))
    if missing:
        errs.append("probe labels missing from PDF text: %s" % ", ".join(missing))
    doc.close()
    return errs, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--svg", default=None)
    ap.add_argument("--width-mm", type=float, default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--probe", default="")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    probes = [p.strip() for p in a.probe.split(",") if p.strip()]
    errs, info, unavail = [], {}, []
    if a.png:
        try:
            e, i = check_png(a.png, a.width_mm, a.dpi)
            errs += e
            info.update(i)
        except ImportError as ex:
            unavail.append("png check skipped (missing lib: %s)" % ex)
        except Exception as ex:
            errs.append("png check failed: %s" % ex)
    if a.pdf:
        try:
            e, i = check_pdf(a.pdf, a.width_mm, probes)
            errs += e
            info.update(i)
        except ImportError as ex:
            unavail.append("pdf check skipped (missing lib: %s)" % ex)
        except Exception as ex:
            errs.append("pdf check failed: %s" % ex)
    if a.svg:
        body = open(a.svg, "rb").read().decode("utf-8", "ignore")
        ok = "<svg" in body[:600]
        n_text = body.count("<text")
        sem_ids = re.findall(r'\bid="(?:panel|node|edge|elabel|group|legend|series|text)-[^"]+"', body)
        all_ids = re.findall(r'\bid="([^"]+)"', body)
        dup_ids = len(all_ids) - len(set(all_ids))
        comp_layers = len(re.findall(r'data-layer="(?:node|edge|compartment|legend)"', body))
        info["svg"] = {
            "path": a.svg, "is_svg": ok, "text_elements": n_text,
            "editable_text": n_text > 0, "semantic_layers": len(sem_ids),
            "composite_layers": comp_layers, "duplicate_ids": dup_ids,
        }
        if not ok:
            errs.append("SVG invalid header")
        if n_text == 0:
            errs.append("SVG has no <text> elements (text was rasterized?)")
        if dup_ids > 0:
            info.setdefault("svg_warnings", []).append("%d duplicate SVG id(s)" % dup_ids)
        mv = re.search(r'viewBox="([\d.\-\s]+)"', body)
        if mv:
            vb = [float(x) for x in mv.group(1).split()]
            oob = 0
            for mm in re.finditer(
                    r'<(rect|ellipse|text)[^>]*?\b(?:x|cx)="(-?[\d.]+)"[^>]*?'
                    r'\b(?:y|cy)="(-?[\d.]+)"', body):
                x, y = float(mm.group(2)), float(mm.group(3))
                pad = (vb[2] - vb[0]) * 0.05
                if (x < vb[0] - pad or x > vb[0] + vb[2] + pad or
                        y < vb[1] - pad or y > vb[1] + vb[3] + pad):
                    oob += 1
            info["svg"]["elements_outside_viewbox_est"] = oob
            if oob:
                info.setdefault("svg_warnings", []).append(
                    "%d element(s) outside viewBox (+5%% pad)" % oob)
    if unavail:
        info["unavailable_checks"] = unavail
    rep = {"errors": errs, "n_errors": len(errs),
           "status": "pass" if not errs else "fail", **info}
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
