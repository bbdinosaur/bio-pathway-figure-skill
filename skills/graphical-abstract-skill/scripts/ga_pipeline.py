#!/usr/bin/env python3
"""GA-Skill pipeline CLI: brief.json -> layered SVG + PNG + PDF.

Usage: python3 ga_pipeline.py --brief brief.json [--outdir DIR] [--stem NAME] [--check-only]
Deterministic: same brief -> byte-identical SVG. Stdlib only for build;
render chain: chrome -> soffice+pdftoppm -> imagemagick.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gaconfig import H, W, parse_svg_dims  # noqa: E402
from gadoc import document  # noqa: E402
from galayout import build_svg  # noqa: E402


def _chrome(html: Path, png: Path, pdf: Path, log: list, cw: int, ch: int) -> bool:
    exe = None
    for c in ("google-chrome", "chromium", "chromium-browser"):
        try:
            subprocess.run([c, "--version"], capture_output=True, timeout=15)
            exe = c
            break
        except Exception:
            continue
    if not exe:
        return False
    prof = Path(f"/tmp/ga_chrome_{os.getpid()}")
    base = [exe, "--headless", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars", "--default-background-color=FFFFFFFF",
            f"--user-data-dir={prof}",
            "--force-device-scale-factor=1"]
    ok = True
    try:
        try:
            subprocess.run(base + [f"--window-size={cw},{ch + 150}",
                                   f"--screenshot={png}", str(html)],
                           capture_output=True, timeout=90, check=True)
            try:
                from PIL import Image
                im = Image.open(png)
                if im.size != (cw, ch):
                    im.crop((0, 0, min(cw, im.size[0]), min(ch, im.size[1]))).save(png)
            except Exception:
                pass
        except Exception as e:
            log.append(f"chrome png failed: {e}")
            ok = False
        try:
            subprocess.run(base + ["--no-pdf-header-footer",
                                   f"--print-to-pdf={pdf}", str(html)],
                           capture_output=True, timeout=90, check=True)
        except Exception as e:
            log.append(f"chrome pdf failed: {e}")
            ok = False
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return ok


def _rsvg(svg: Path, png: Path, pdf: Path, log: list, cw: int, ch: int) -> bool:
    try:
        subprocess.run(["rsvg-convert", "-w", str(cw), "-h", str(ch),
                        "-f", "png", "-o", str(png), str(svg)],
                       capture_output=True, timeout=60, check=True)
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg)],
                       capture_output=True, timeout=60, check=True)
        return png.exists() and pdf.exists()
    except Exception as e:
        log.append(f"rsvg-convert failed: {e}")
        return False


def _soffice(svg: Path, png: Path, pdf: Path, log: list, cw: int, ch: int) -> bool:
    ok = False
    try:
        with tempfile.TemporaryDirectory(prefix="ga_lo_") as td:
            lo_prof = Path(td) / "lo_profile"
            lo_env = dict(os.environ)
            lo_env["HOME"] = td
            lo_env["XDG_CONFIG_HOME"] = str(lo_prof)
            lo_env["XDG_CACHE_HOME"] = str(Path(td) / "cache")
            subprocess.run(
                ["soffice", "--headless",
                 f"-env:UserInstallation={lo_prof.resolve().as_uri()}",
                 "--convert-to", "pdf",
                 "--outdir", td, str(svg)],
                capture_output=True, timeout=120, check=True, env=lo_env,
            )
            got = Path(td) / f"{svg.stem}.pdf"
            if not got.exists():
                pdfs = sorted(Path(td).glob("*.pdf"))
                got = pdfs[0] if pdfs else got
            if got.exists():
                pdf.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(got), str(pdf))
        ok = pdf.exists()
    except Exception as e:
        log.append(f"soffice pdf failed: {e}")
    if ok:
        try:
            subprocess.run(["pdftoppm", "-png", "-r", "96", "-singlefile",
                            str(pdf), str(png.with_suffix(""))],
                           capture_output=True, timeout=60, check=True)
            try:
                from PIL import Image
                im = Image.open(png)
                if im.size != (cw, ch) and im.size[0] >= cw and im.size[1] >= ch:
                    im.crop((0, 0, cw, ch)).save(png)
            except Exception:
                pass
        except Exception as e:
            log.append(f"pdftoppm failed: {e}")
            ok = ok and png.exists()
    return ok


def _stamp_png_dpi(png: Path, dpi: int = 96) -> bool:
    """Stamp exact PNG pHYs chunk (pure stdlib) so preview PNG reports strict 96 DPI (<=108)."""
    try:
        data = png.read_bytes()
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        ppm = int(round(dpi / 0.0254))
        phys_data = struct.pack(">IIB", ppm, ppm, 1)
        phys_chunk = struct.pack(">I", 9) + b"pHYs" + phys_data + struct.pack(">I", zlib.crc32(b"pHYs" + phys_data) & 0xFFFFFFFF)
        out = bytearray(data[:8])
        pos = 8
        inserted = False
        while pos + 8 <= len(data):
            clen = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            end = pos + 12 + clen
            if end > len(data):
                return False
            if ctype == b"pHYs":
                if not inserted:
                    out.extend(phys_chunk)
                    inserted = True
            else:
                out.extend(data[pos:end])
                if ctype == b"IHDR" and not inserted:
                    out.extend(phys_chunk)
                    inserted = True
            pos = end
        png.write_bytes(bytes(out))
        return True
    except Exception:
        return False


def _read_png_dpi(png: Path) -> float | None:
    """Read PNG physical DPI from pHYs chunk (pure stdlib)."""
    try:
        data = png.read_bytes()
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos = 8
        while pos + 8 <= len(data):
            clen = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            if ctype == b"pHYs" and clen == 9:
                xppm, _yppm, unit = struct.unpack(">IIB", data[pos + 8:pos + 17])
                if unit == 1 and xppm > 0:
                    return round(xppm * 0.0254, 1)
            pos += 12 + clen
    except Exception:
        pass
    return None


def render(svg: Path, png: Path, pdf: Path, log: list) -> str:
    """Render any SVG at its native canvas dimensions to 1:1 96-DPI PNG + vector PDF."""
    svg_text = svg.read_text(encoding="utf-8")
    cw, ch = parse_svg_dims(svg_text, default=(W, H))
    html = svg.with_name("_ga_wrap.html")
    html.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>@page{{size:{cw}px {ch}px;margin:0}}html,body{{margin:0;padding:0;"
        f"width:{cw}px;height:{ch}px;overflow:hidden;background:#fff}}"
        f"body>svg{{display:block;width:{cw}px;height:{ch}px}}</style></head>"
        "<body>" + svg_text + "</body></html>",
        encoding="utf-8")
    eng = "failed"
    try:
        if _chrome(html, png, pdf, log, cw, ch) and png.exists() and pdf.exists():
            eng = "chrome"
        elif _soffice(svg, png, pdf, log, cw, ch) and png.exists() and pdf.exists():
            eng = "soffice"
        elif _rsvg(svg, png, pdf, log, cw, ch):
            eng = "rsvg-convert"
        else:
            try:
                subprocess.run(["convert", "-density", "96", str(svg), str(png)],
                               capture_output=True, timeout=90, check=True)
                eng = "imagemagick-png-only"
            except Exception as e:
                log.append(f"convert failed: {e}")
        if png.exists():
            _stamp_png_dpi(png, 96)
        return eng
    finally:
        try:
            html.unlink(missing_ok=True)
        except Exception:
            pass


def render_hi_res(pdf: Path, png_hi: Path, dpi: int = 300):
    """Optional print-resolution PNG from vector PDF (only when --hires-dpi is explicitly requested)."""
    if not pdf.exists() or dpi <= 0:
        return False
    try:
        subprocess.run(["pdftoppm", "-png", "-r", str(int(dpi)), "-singlefile",
                        str(pdf), str(png_hi.with_suffix(""))],
                       capture_output=True, timeout=60, check=True)
        return png_hi.exists()
    except Exception:
        return False


def _png_dims_stdlib(p: Path):
    try:
        hdr = p.read_bytes()[:24]
        if hdr[:8] == b"\x89PNG\r\n\x1a\n" and len(hdr) >= 24:
            import struct
            return list(struct.unpack(">II", hdr[16:24]))
    except Exception:
        pass
    return None


def verify_exports(png: Path, pdf: Path, report: dict, hires_dpi: int = 0):
    """Post-render integrity audit: PNG non-blank + dims + exact pHYs DPI (<=108); PDF pages + searchable text."""
    ec = {}
    if png.exists():
        real_dpi = _read_png_dpi(png) or 96.0
        try:
            from PIL import Image
            import statistics
            im = Image.open(png).convert("L")
            iw, ih = im.size
            raw_px = (list(im.get_flattened_data()) if hasattr(im, "get_flattened_data")
                      else list(im.getdata()))
            px = raw_px[:: max(1, len(raw_px) // 20000)]
            ink_ratio = round(sum(1 for v in px if v < 245) / max(len(px), 1), 4)
            # Outer 1px border ink check catches clipped text/shapes even on complex external SVGs
            edge_clip = 0
            if iw >= 4 and ih >= 4 and len(raw_px) == iw * ih:
                top_b = raw_px[:iw]
                bot_b = raw_px[(ih - 1) * iw:]
                lft_b = raw_px[::iw]
                rgt_b = raw_px[iw - 1::iw]
                edge_clip = sum(1 for v in top_b if v < 180) + sum(1 for v in bot_b if v < 180) \
                    + sum(1 for v in lft_b if v < 180) + sum(1 for v in rgt_b if v < 180)
            ec["png"] = {
                "dims": [iw, ih], "dpi": real_dpi, "dpi_ok": real_dpi <= 108.0,
                "non_blank": statistics.pstdev(px) > 4.0,
                "ink_ratio": ink_ratio, "edge_clip_px": edge_clip,
            }
            if hires_dpi > 0:
                p2 = png.with_name(f"{png.stem}_{hires_dpi}dpi.png")
                if p2.exists():
                    ec["png_hires"] = {"dims": list(Image.open(p2).size), "dpi": int(hires_dpi)}
        except Exception:
            dims = _png_dims_stdlib(png)
            ec["png"] = {"dims": dims, "dpi": real_dpi, "dpi_ok": real_dpi <= 108.0,
                         "non_blank": png.stat().st_size > 2048}
            if hires_dpi > 0:
                p2 = png.with_name(f"{png.stem}_{hires_dpi}dpi.png")
                if p2.exists():
                    ec["png_hires"] = {"dims": _png_dims_stdlib(p2), "dpi": int(hires_dpi)}
    else:
        ec["png"] = {"error": "png missing"}
    try:
        raw = pdf.read_bytes()
        boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                           raw)
        pages = len(re.findall(rb"/Type\s*/Page[^s]", raw)) or 1
        w_pt, h_pt = ((float(boxes[0][2]), float(boxes[0][3]))
                      if boxes else (None, None))
        pdf_info = {"bytes": len(raw), "pages": pages,
                    "page_pt": [w_pt, h_pt],
                    "ok": raw[:5] == b"%PDF-" and pages >= 1 and len(raw) > 2048}
        try:
            r = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                txt_len = len(r.stdout.strip())
                pdf_info["searchable_text"] = txt_len > 0
                pdf_info["extracted_chars"] = txt_len
        except Exception:
            pass
        ec["pdf"] = pdf_info
    except Exception as e:
        ec["pdf"] = {"error": str(e)[:120]}
    report["export_check"] = ec
    return ec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--stem", default=None, help="output filename stem (default: brief stem)")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--hires-dpi", type=int, default=0,
                    help="optional print PNG DPI (e.g. 300); preview PNG stays 96 DPI")
    ap.add_argument("--audit", action="store_true",
                    help="run ga_check audit in-process and emit _check_report.json")
    ap.add_argument("--data-dir", default=None,
                    help="input dir for source data grounding cross-verification")
    ap.add_argument("--deliver", default=None,
                    help="target delivery dir (e.g. /app/output); copies SVG/PNG/PDF and writes result.json if --case set")
    ap.add_argument("--case", default=None, help="/input/case.json path for writing result.json")
    ap.add_argument("--report", default=None, help="optional report.json path for provenance/notes")
    a = ap.parse_args()
    bpath = Path(a.brief).resolve()
    outdir = Path(a.outdir).resolve() if a.outdir else bpath.parent
    outdir.mkdir(parents=True, exist_ok=True)
    brief = json.loads(bpath.read_text(encoding="utf-8"))
    body, links, boxes, diag = build_svg(brief)
    svg_text = document(brief, body, links)
    stem = a.stem or str(brief.get("stem") or "").strip()
    if not stem:
        raw_st = bpath.stem.replace(".brief", "") or "ga"
        if raw_st in ("brief", "ga") and a.case and Path(a.case).exists():
            try:
                c_obj = json.loads(Path(a.case).read_text(encoding="utf-8", errors="ignore"))
                # Only scan output/workorder fields (NEVER input materials/attachments!)
                out_blob = json.dumps(
                    {k: c_obj[k] for k in ("output_contract", "required_outputs", "deliverables",
                                           "expected_outputs", "workorder", "target_output", "task")
                     if k in c_obj},
                    ensure_ascii=False,
                )
                bad_stems = {"editable", "source", "input", "original", "template", "reference", "draft", "example"}
                found_st = False
                for m_svg in re.finditer(r"\b([A-Za-z][A-Za-z0-9_-]{2,40})\.svg\b", out_blob):
                    cand_st = m_svg.group(1)
                    if not any(bw in cand_st.lower() for bw in bad_stems):
                        raw_st = cand_st
                        found_st = True
                        break
                if not found_st:
                    m_fig = re.search(r"\b(figure[_-]?\d+[a-z]?|fig[_-]?\d+[a-z]?|graphical[_-]abstract)\b",
                                      out_blob, re.IGNORECASE)
                    if m_fig:
                        raw_st = m_fig.group(1).lower()
            except Exception:
                pass
        stem = raw_st
    svg = outdir / f"{stem}.svg"
    svg.write_text(svg_text, encoding="utf-8")
    cw, ch = diag.get("canvas", [W, H])
    report = {"svg": str(svg), "canvas": [cw, ch], "layout": diag.get("layout"),
              "diag": diag, "panels": len(boxes),
              "render_engine": None, "render_log": []}
    png = outdir / f"{stem}.png"
    pdf = outdir / f"{stem}.pdf"
    if not a.check_only:
        eng = render(svg, png, pdf, report["render_log"])
        report["render_engine"] = eng
        if a.hires_dpi > 0:
            render_hi_res(pdf, outdir / f"{stem}_{a.hires_dpi}dpi.png", dpi=a.hires_dpi)
        report["export_check"] = verify_exports(png, pdf, report, hires_dpi=a.hires_dpi)
    overflow = [k for k, v in diag["panels"].items() if v.get("overflow")]
    report["overflow_panels"] = overflow
    br_path = outdir / "_build_report.json"
    br_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {
        "svg": str(svg), "layout": diag.get("layout"),
        "theme": diag.get("theme"),
        "engine": report["render_engine"], "overflow": overflow,
        "panel_fs": {k: v["fs"] for k, v in diag["panels"].items()},
        "panel_fill": {k: v.get("fill_ratio") for k, v in diag["panels"].items()},
    }
    if report.get("export_check"):
        ec = report["export_check"]
        p_ec = ec.get("png") or {}
        f_ec = ec.get("pdf") or {}
        summary["export_check"] = {
            "dpi": p_ec.get("dpi"),
            "dpi_ok": p_ec.get("dpi_ok"),
            "ink_ratio": p_ec.get("ink_ratio"),
            "edge_clip_px": p_ec.get("edge_clip_px"),
            "non_blank": p_ec.get("non_blank"),
            "searchable_text": f_ec.get("searchable_text"),
        }
    if overflow:
        summary["overflow_hints"] = [
            f"{k} overflows by {round(diag['panels'][k]['content_h'] - diag['panels'][k]['avail_h'], 1)}px "
            f"(content_h={diag['panels'][k]['content_h']} > avail_h={diag['panels'][k]['avail_h']}): "
            "shorten copy, trim chart height, or increase row_weights/top_weights/bottom_weights"
            for k in overflow
        ]

    # Optional in-process audit + data grounding (automatically enabled when --data-dir or --deliver is set)
    if a.audit or a.data_dir or a.deliver:
        from ga_check import _audit_data_grounding, audit as run_audit
        rep_obj = None
        if a.report and Path(a.report).exists():
            try:
                loaded_rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
                if isinstance(loaded_rep, dict):
                    rep_obj = loaded_rep
            except Exception:
                rep_obj = None
        ck = run_audit(svg, brief=brief, report=rep_obj, external=False)
        if a.data_dir:
            dg = _audit_data_grounding(brief, Path(a.data_dir))
            ck["data_grounding"] = dg
            if dg.get("unmatched"):
                ck.setdefault("advisories", []).append(
                    f"data_grounding: {len(dg['unmatched'])} unmatched value(s): "
                    + ", ".join(f"{u['panel']}={u['value']}" for u in dg["unmatched"][:5]))
        (outdir / "_check_report.json").write_text(
            json.dumps(ck, ensure_ascii=False, indent=1), encoding="utf-8")
        summary["audit_pass"] = ck["pass"] and len(ck["warnings"]) == 0
        summary["errors"] = ck["errors"]
        summary["warnings"] = ck["warnings"]
        summary["advisories"] = ck.get("advisories", [])
        if ck.get("data_grounding"):
            summary["data_grounding"] = ck["data_grounding"]

    # Optional one-shot delivery to /app/output + result.json generation
    if a.deliver or (a.case and Path(a.case).exists() and outdir.name == "output"):
        deliv = Path(a.deliver).resolve() if a.deliver else outdir
        deliv.mkdir(parents=True, exist_ok=True)
        copied = []
        cand_files = [svg, png, pdf]
        if a.hires_dpi > 0:
            cand_files.append(outdir / f"{stem}_{a.hires_dpi}dpi.png")
        for fsrc in cand_files:
            if fsrc.exists():
                dst = deliv / fsrc.name
                if fsrc.resolve() != dst.resolve():
                    shutil.copy2(fsrc, dst)
                copied.append(fsrc.name)
        summary["delivered"] = copied
        if a.case and Path(a.case).exists():
            from ga_result import build_result
            res_sum = build_result(
                case_path=Path(a.case),
                out_path=deliv / "result.json",
                outdir=deliv,
                work=outdir,
                report_path=Path(a.report) if a.report else None,
                build_report_path=br_path,
                main_svg=svg.name,
                brief_path=bpath,
            )
            summary["result"] = res_sum

    print(json.dumps(summary, ensure_ascii=False))
    if overflow:
        print("CHECK FAIL: panel content overflows:", overflow, file=sys.stderr)
        return 1
    if report["render_engine"] == "failed" and not a.check_only:
        print("RENDER FAILED; SVG written; see _build_report.json", file=sys.stderr)
        return 3
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
