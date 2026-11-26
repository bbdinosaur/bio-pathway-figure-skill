#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sci-figure-studio 共享工具库：字体、JSON IO、栅格化、PNG 边缘检查。
仅依赖标准库 + matplotlib + Pillow，PyMuPDF/rsvg 等按可用性自动降级。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _import_fitz():
    try:
        import pymupdf as fitz
        return fitz
    except ImportError:
        import fitz
        return fitz

# ---------------- JSON / IO ----------------

def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def dump_json(obj, p):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2,
                   default=lambda o: o.item() if hasattr(o, "item") else str(o)),
        encoding="utf-8",
    )
    return str(p)


def sha256_of(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------- 字体 ----------------

CJK_PREFERRED = (
    "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK TC", "Noto Sans CJK HK",
    "Source Han Sans SC", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "Microsoft YaHei", "SimHei", "PingFang SC", "Droid Sans Fallback", "AR PL UMing CN",
)


def detect_cjk_font():
    """返回第一个可用的中文字体族名（找不到返回 None）。"""
    try:
        import matplotlib.font_manager as fm
        names = {f.name for f in fm.fontManager.ttflist}
    except Exception:
        return None
    for pref in CJK_PREFERRED:
        if pref in names:
            return pref
    for n in sorted(names):
        if any(k in n for k in ("CJK", "WenQuanYi", "Source Han", "YaHei", "SimHei")):
            return n
    return None


def setup_matplotlib(font_pt=None):
    """统一 rcParams：SVG 保留真实 <text>（可编辑），PDF 嵌入 TrueType，中文字体回退链。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cjk = detect_cjk_font()
    chain = ([cjk] if cjk else []) + ["DejaVu Sans", "Arial", "Helvetica", "Liberation Sans"]
    plt.rcParams.update({
        "svg.fonttype": "none",          # 关键：SVG 内文字保持 <text>，可在 Inkscape/Illustrator 编辑
        "pdf.fonttype": 42,              # TrueType 嵌入，不转曲
        "ps.fonttype": 42,
        "font.family": "sans-serif",
        "font.sans-serif": chain,
        "axes.unicode_minus": False,
        "font.size": float(font_pt) if font_pt else 8.0,
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "legend.frameon": False,
        "figure.dpi": 100,
    })
    return {"cjk_font": cjk, "font_chain": chain}


# ---------------- 读取表格（无 pandas 依赖） ----------------

def read_table(path, return_meta=False, header_row=None):
    """读 CSV/TSV（支持 utf-8-sig/gb18030/latin-1 容错、跳过 # 注释行与首行单列标题横幅，保留真实 1-based 物理行号）。"""
    p = Path(path)
    text = None
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            text = p.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return ([], [], 1) if return_meta else ([], [])
    raw_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not raw_lines:
        return ([], [], 1) if return_meta else ([], [])
    sample = raw_lines[:10]
    scores = {d: sum(ln.count(d) for ln in sample) for d in ("\t", ",", ";")}
    if scores["\t"] > 0 and scores["\t"] >= scores[","]:
        delim = "\t"
    elif scores[";"] > scores[","] and scores[";"] >= len(sample):
        delim = ";"
    else:
        delim = ","
    parsed = []
    for line_no, vals in enumerate(csv.reader(io.StringIO(text), delimiter=delim), start=1):
        if not any(v.strip() for v in vals):
            continue
        if vals[0].lstrip().startswith("#"):
            continue
        parsed.append((line_no, vals))
    if not parsed:
        return ([], [], 1) if return_meta else ([], [])
    hdr_idx = 0
    if header_row is not None and int(header_row) >= 1:
        target_ln = int(header_row)
        for i, (ln, _) in enumerate(parsed):
            if ln >= target_ln:
                hdr_idx = i
                break
    else:
        # 自动跳过 Nature/Cell Source Data 常见的单列标题横幅行（仅当后续存在 ≥2 列数据表头时）
        col_counts = [sum(1 for x in vals if x.strip()) for _, vals in parsed[:8]]
        max_cc = max(col_counts) if col_counts else 1
        if max_cc >= 2 and col_counts[0] == 1:
            for i, cc in enumerate(col_counts):
                if cc >= 2:
                    hdr_idx = i
                    break
    header_line, hvals = parsed[hdr_idx]
    header = [c.strip() for c in hvals]
    rows = []
    for line_no, vals in parsed[hdr_idx + 1:]:
        rec = {header[j]: (vals[j].strip() if j < len(vals) else "") for j in range(len(header))}
        rec["__line__"] = line_no
        rows.append(rec)
    if return_meta:
        return header or [], rows, header_line
    return header or [], rows


_VAL_ERR_PAT = re.compile(
    r"^\s*([-+\u2212\u2013]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(?:±|\+/-|\+-)\s*(\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*%?\s*$"
)


def parse_val_err(v):
    """解析 '12.4 ± 1.2' 或 '12.4 +/- 1.2' 单元格为 (val, err)，否则返回 (None, None)。"""
    if v is None or isinstance(v, (int, float)):
        return None, None
    m = _VAL_ERR_PAT.match(str(v).strip())
    if not m:
        return None, None
    return to_num(m.group(1)), to_num(m.group(2))


def to_num(v):
    """宽松数值解析：支持 1,234 / 5% / Unicode 负号(−/–) / 空串或 Inf→None。不编造缺失值。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        fv = float(v)
        return None if (math.isnan(fv) or math.isinf(fv)) else fv
    s = str(v).strip().replace("\u2212", "-").replace("\u2013", "-").replace(",", "").rstrip("%")
    if s in ("", "-", "NA", "N/A", "na", "nan", "NaN", "null", "None", "inf", "-inf", "+inf", "Inf", "-Inf"):
        return None
    try:
        fv = float(s)
        return None if (math.isnan(fv) or math.isinf(fv)) else fv
    except ValueError:
        return None


def _parse_svg_len_px(val_str):
    """将 SVG 长度属性（含 pt/mm/cm/in/px 单位）精确换算为 CSS px（96 DPI 基准）。"""
    if not val_str or "%" in val_str:
        return None
    m = re.match(r"^\s*([\d.]+)\s*(px|pt|mm|cm|in|pc)?\s*$", str(val_str), re.I)
    if not m:
        return None
    v = float(m.group(1))
    unit = (m.group(2) or "px").lower()
    mul = {"px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0}
    return v * mul.get(unit, 1.0)


def _svg_css_size(src):
    """解析 SVG 在浏览器/PDF 中的真实 CSS 渲染宽高 (vw_px, vh_px)，彻底修复 pt/mm/in 单位裁切。"""
    svg_text = Path(src).read_text(encoding="utf-8", errors="ignore")[:8000]
    m_tag = re.search(r"<svg\b[^>]*>", svg_text, re.S)
    hdr = m_tag.group(0) if m_tag else svg_text[:2000]
    mw = re.search(r'\bwidth="([^"]+)"', hdr)
    mh = re.search(r'\bheight="([^"]+)"', hdr)
    mvb = re.search(r'\bviewBox="\s*[-+\d.]+\s+[-+\d.]+\s+([\d.]+)\s+([\d.]+)\s*"', hdr)
    w_px = _parse_svg_len_px(mw.group(1)) if mw else None
    h_px = _parse_svg_len_px(mh.group(1)) if mh else None
    vb_w = float(mvb.group(1)) if mvb else None
    vb_h = float(mvb.group(2)) if mvb else None
    vw = w_px if (w_px and w_px > 1) else (vb_w if (vb_w and vb_w > 1) else 800.0)
    vh = h_px if (h_px and h_px > 1) else (vb_h if (vb_h and vb_h > 1) else 600.0)
    return vw, vh


# ---------------- 栅格化（多级回退） ----------------

def rasterize_any(src, out_png, dpi=150):
    """SVG/PDF → PNG。按可用工具逐级回退，返回 {ok, tool|error}。"""
    src, out = Path(src), Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    low = str(src).lower()
    if low.endswith(".pdf"):
        try:
            fitz = _import_fitz()
            d = fitz.open(str(src))
            pix = d[0].get_pixmap(dpi=dpi)
            pix.save(str(out))
            d.close()
            return {"ok": True, "tool": "pymupdf"}
        except Exception:
            pass
        if shutil.which("pdftoppm"):
            r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile",
                                str(src), str(out.with_suffix(""))], capture_output=True)
            if r.returncode == 0 and out.exists():
                return {"ok": True, "tool": "pdftoppm"}
        return {"ok": False, "error": "no pdf rasterizer (pymupdf/pdftoppm 均不可用)"}
    # SVG：优先 Chrome headless（按真实 CSS 物理尺寸渲染，彻底避免 pt/mm/in 裁切）
    try:
        vw, vh = _svg_css_size(src)
        scale = dpi / 96.0
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if chrome:
            win_w = max(120, int(math.ceil(vw)) + 24)
            win_h = max(120, int(math.ceil(vh)) + 140)  # 预留 Chrome headless=new UI 栏高度，避免底部裁切
            r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                                "--hide-scrollbars", "--default-background-color=FFFFFFFF",
                                "--force-device-scale-factor=" + f"{scale:.3f}",
                                f"--window-size={win_w},{win_h}",
                                "--screenshot=" + str(out), src.resolve().as_uri()],
                               capture_output=True, timeout=60)
            if r.returncode == 0 and out.exists() and out.stat().st_size > 500:
                try:
                    from PIL import Image
                    im = Image.open(out)
                    cw = min(im.width, max(1, int(round(vw * scale))))
                    ch = min(im.height, max(1, int(round(vh * scale))))
                    if cw < im.width or ch < im.height:
                        im = im.crop((0, 0, cw, ch))
                    im.save(out, dpi=(dpi, dpi))
                except Exception:
                    pass
                return {"ok": True, "tool": "chrome-headless"}
    except Exception:
        pass
    try:
        fitz = _import_fitz()
        d = fitz.open(str(src))
        pix = d[0].get_pixmap(dpi=dpi)
        pix.save(str(out))
        d.close()
        return {"ok": True, "tool": "pymupdf-svg"}
    except Exception:
        pass
    candidates = [
        ("rsvg-convert", ["rsvg-convert", "-d", str(dpi), "-p", str(dpi), "-o", str(out), str(src)]),
        ("inkscape", ["inkscape", str(src), "--export-type=png",
                      "--export-filename=" + str(out), "--export-dpi=" + str(dpi)]),
        ("cairosvg", ["cairosvg", str(src), "-o", str(out), "--dpi", str(dpi)]),
    ]
    for name, argv in candidates:
        if shutil.which(name):
            r = subprocess.run(argv, capture_output=True)
            if r.returncode == 0 and out.exists():
                return {"ok": True, "tool": name}
    return {"ok": False, "error": "no svg rasterizer (tried chrome/pymupdf/rsvg-convert/inkscape/cairosvg)"}


def svg_to_pdf_chrome(src_svg, out_pdf):
    """Chrome headless 将 SVG 按精确画布尺寸打印为单页紧贴矢量 PDF（无 US Letter 留白/分页）。"""
    import tempfile
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        return {"ok": False, "error": "no chrome/chromium"}
    Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
    tmp_html = None
    try:
        vw, vh = _svg_css_size(src_svg)
        w_in = max(1.0, (vw + 1.0) / 96.0)
        h_in = max(1.0, (vh + 1.0) / 96.0)
        svg_body = Path(src_svg).read_text(encoding="utf-8", errors="ignore")
        # 去掉 XML 声明，直接内联至精确 @page 尺寸的 HTML 中保持 100% 矢量与可编辑文字
        svg_body = re.sub(r"<\?xml[^>]*\?>", "", svg_body, count=1).strip()
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'><style>"
            f"@page {{ size: {w_in:.4f}in {h_in:.4f}in; margin: 0; }}"
            f"html, body {{ margin: 0; padding: 0; width: {vw:.2f}px; height: {vh:.2f}px; overflow: hidden; background: #fff; }}"
            f"svg {{ display: block; }}"
            f"</style></head><body>{svg_body}</body></html>"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
            tf.write(html)
            tmp_html = Path(tf.name)
        r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--no-pdf-header-footer", f"--print-to-pdf={Path(out_pdf).resolve()}",
                            tmp_html.resolve().as_uri()], capture_output=True, timeout=90)
        ok = r.returncode == 0 and Path(out_pdf).exists() and Path(out_pdf).stat().st_size > 500
        return {"ok": bool(ok), "tool": "chrome-exact" if ok else None,
                "error": None if ok else "chrome print-to-pdf failed"}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    finally:
        if tmp_html and tmp_html.exists():
            try:
                tmp_html.unlink()
            except Exception:
                pass


def svg_to_pdf_any(src_svg, out_pdf):
    """SVG → PDF 多级回退：rsvg-convert / inkscape / cairosvg / chrome / pymupdf。"""
    src, out = Path(src_svg), Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmds = [
        ("rsvg-convert", ["rsvg-convert", "-f", "pdf", "-o", str(out), str(src)]),
        ("inkscape", ["inkscape", str(src), "--export-type=pdf", "--export-filename=" + str(out)]),
        ("cairosvg", ["cairosvg", str(src), "-o", str(out)]),
    ]
    for name, argv in cmds:
        if shutil.which(name):
            r = subprocess.run(argv, capture_output=True, timeout=90)
            if r.returncode == 0 and out.exists() and out.stat().st_size > 300:
                return {"ok": True, "tool": name}
    res = svg_to_pdf_chrome(src, out)
    if res.get("ok"):
        return res
    try:
        fitz = _import_fitz()
        d = fitz.open(str(src))
        pdf_bytes = d.convert_to_pdf()
        d.close()
        out.write_bytes(pdf_bytes)
        if out.stat().st_size > 300:
            return {"ok": True, "tool": "pymupdf"}
    except Exception as e:
        return {"ok": False, "error": f"all svg->pdf backends failed (last: {type(e).__name__}: {e})"}
    return {"ok": False, "error": "svg->pdf produced empty file"}


def verify_svg_editable(svg_path):
    """核验 SVG 是否包含可编辑 <text> 节点与 <metadata> 溯源节点。"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(svg_path)).getroot()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "text_count": 0}
    texts, has_meta = [], False
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "text":
            t = "".join(el.itertext()).strip()
            if t:
                texts.append(t)
        elif tag == "metadata":
            has_meta = True
    return {"ok": len(texts) > 0, "text_count": len(texts),
            "has_metadata": has_meta, "sample_texts": texts[:8]}


def pdf_to_png(src_pdf, out_png, dpi=150, page=0):
    try:
        fitz = _import_fitz()
        d = fitz.open(str(src_pdf))
        pix = d[page].get_pixmap(dpi=dpi)
        pix.save(str(out_png))
        d.close()
        return {"ok": True, "tool": "pymupdf"}
    except Exception as e:
        if shutil.which("pdftoppm"):
            r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page + 1),
                                "-l", str(page + 1), "-singlefile", str(src_pdf),
                                str(Path(out_png).with_suffix(""))], capture_output=True)
            if r.returncode == 0 and Path(out_png).exists():
                return {"ok": True, "tool": "pdftoppm"}
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------- PNG 边缘/留白检查 ----------------

def png_edge_check(png, bg_thresh=245, border_px=2):
    """检查内容是否触及画布边缘（疑似裁切）与四边留白比例。"""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "Pillow/numpy 不可用"}
    raw_im = Image.open(png)
    orig_mode = raw_im.mode
    raw_dpi = raw_im.info.get("dpi")
    if orig_mode in ("RGBA", "LA"):
        bg = Image.new("RGB", raw_im.size, (255, 255, 255))
        bg.paste(raw_im, mask=raw_im.split()[-1])
        im = bg
    else:
        im = raw_im.convert("RGB")
    a = np.asarray(im).astype(int)
    h, w, _ = a.shape
    nonbg = a.min(axis=2) < bg_thresh
    edges = {
        "top": bool(nonbg[:border_px, :].any()), "bottom": bool(nonbg[-border_px:, :].any()),
        "left": bool(nonbg[:, :border_px].any()), "right": bool(nonbg[:, -border_px:].any()),
    }
    cols = nonbg.any(axis=0)
    rows = nonbg.any(axis=1)
    x0 = int(cols.argmax()) if cols.any() else 0
    x1 = int(w - 1 - cols[::-1].argmax()) if cols.any() else w - 1
    y0 = int(rows.argmax()) if rows.any() else 0
    y1 = int(h - 1 - rows[::-1].argmax()) if rows.any() else h - 1
    cov_pct = round(100.0 * float(nonbg.mean()), 3) if (w * h) else 0.0
    return {
        "ok": True,
        "size_px": [w, h],
        "mode": orig_mode,
        "dpi": [round(float(raw_dpi[0]), 2), round(float(raw_dpi[1]), 2)] if raw_dpi else None,
        "content_bbox_px": [x0, y0, x1, y1],
        "content_coverage_pct": cov_pct,
        "blank_suspect": cov_pct < 0.5,
        "margins_pct": {"left": round(x0 / w, 4), "right": round((w - 1 - x1) / w, 4),
                        "top": round(y0 / h, 4), "bottom": round((h - 1 - y1) / h, 4)},
        "clipping_suspect": any(edges.values()),
        "edge_hits": edges,
    }


def apply_journal_style(preset="nature_double", font_pt=None):
    """自定义 Matplotlib 脚本 1 行接入出版级样式预设与可编辑 SVG/PDF 字体设置。"""
    pfile = Path(__file__).resolve().parent.parent / "assets" / "journal_presets.json"
    st = {"width_mm": 180, "panel_h_mm": 68, "font_pt": 8.0, "dpi": 300}
    if pfile.exists():
        try:
            presets = json.loads(pfile.read_text(encoding="utf-8"))
            if preset in presets:
                st.update(presets[preset])
        except Exception:
            pass
    if font_pt is not None:
        st["font_pt"] = float(font_pt)
    finfo = setup_matplotlib(st["font_pt"])
    st["fonts"] = finfo
    return st


def export_and_audit_figure(fig, outdir, base="figure", provenance=None,
                            png_dpi=300, preview_dpi=100, transparent=False):
    """自定义 Matplotlib 脚本 1 行导出 SVG(<text>可编辑)+PDF+300 DPI PNG+100 DPI 预览+自检+溯源 JSON。"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    svg_path = outdir / f"{base}.svg"
    pdf_path = outdir / f"{base}.pdf"
    png_path = outdir / f"{base}.png"
    prev_path = outdir / f"{base}_preview.png"
    prov_path = outdir / f"{base}.provenance.json"
    fig.savefig(svg_path, bbox_inches=None, transparent=transparent)
    fig.savefig(pdf_path, transparent=transparent)
    fig.savefig(png_path, dpi=png_dpi, transparent=transparent)
    fig.savefig(prev_path, dpi=min(108, max(72, int(preview_dpi))), transparent=transparent)
    svg_txt = svg_path.read_text(encoding="utf-8")
    if "<metadata" not in svg_txt:
        meta = f'<metadata id="sci-provenance">figure={base}; provenance={prov_path.name}</metadata>'
        svg_path.write_text(svg_txt.replace("</svg>", meta + "</svg>", 1), encoding="utf-8")
    ed = verify_svg_editable(svg_path)
    ec = png_edge_check(png_path)
    try:
        from check_layout import check_svg
        geo = check_svg(str(svg_path))
    except Exception as e:
        geo = {"ok": None, "error": f"{type(e).__name__}: {e}"}
    prov = dict(provenance or {})
    prov.setdefault("generated_by", "sci-figure-studio custom matplotlib + kit_common")
    prov.setdefault("figure", base)
    prov["export_params"] = {
        "png_dpi": png_dpi, "preview_dpi": min(108, max(72, int(preview_dpi))),
        "colorspace": ec.get("mode") or ("RGBA" if transparent else "RGB"),
        "transparent": transparent, "svg_fonttype": "none", "pdf_fonttype": 42,
    }
    prov["self_check"] = {"editable_svg": ed, "svg_geometry": geo, "png_edge": ec}
    dump_json(prov, prov_path)
    return {
        "ok": bool(ed.get("ok")) and bool(geo.get("ok")) and not ec.get("clipping_suspect") and not ec.get("blank_suspect"),
        "outputs": {"svg": str(svg_path), "pdf": str(pdf_path), "png": str(png_path), "preview": str(prev_path)},
        "provenance": str(prov_path),
        "checks": prov["self_check"],
    }


def merge_dicts(*ds):
    out = {}
    for d in ds:
        if d:
            out.update(d)
    return out
