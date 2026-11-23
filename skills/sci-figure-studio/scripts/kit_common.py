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

def read_table(path, return_meta=False):
    """读 CSV/TSV（支持 utf-8-sig/gb18030/latin-1 容错、跳过 # 注释行，保留真实 1-based 物理行号）。"""
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
    raw_lines = text.splitlines()
    first = next((ln for ln in raw_lines if ln.strip() and not ln.lstrip().startswith("#")), "")
    if not first:
        return ([], [], 1) if return_meta else ([], [])
    if "\t" in first and first.count("\t") >= first.count(","):
        delim = "\t"
    elif ";" in first and first.count(";") > first.count(","):
        delim = ";"
    else:
        delim = ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = None
    header_line = 1
    rows = []
    for line_no, vals in enumerate(reader, start=1):
        if not any(v.strip() for v in vals):
            continue
        if header is None and vals[0].lstrip().startswith("#"):
            continue
        if header is None:
            header = [c.strip() for c in vals]
            header_line = line_no
            continue
        if vals[0].lstrip().startswith("#"):
            continue
        rec = {header[j]: (vals[j].strip() if j < len(vals) else "") for j in range(len(header))}
        rec["__line__"] = line_no
        rows.append(rec)
    if return_meta:
        return header or [], rows, header_line
    return header or [], rows


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
    # SVG：优先 Chrome headless（渲染最正确），再试 PyMuPDF 与外部命令
    try:
        svg_text = src.read_text(encoding="utf-8", errors="ignore")[:4000]
        mvb = re.search(r'viewBox="\s*[-+\d.]+\s+[-+\d.]+\s+([\d.]+)\s+([\d.]+)\s*"', svg_text)
        mw = re.search(r'<svg[^>]*\swidth="([\d.]+)', svg_text)
        mh = re.search(r'<svg[^>]*\sheight="([\d.]+)', svg_text)
        vw = float(mvb.group(1)) if mvb else (float(mw.group(1)) if mw else 800.0)
        vh = float(mvb.group(2)) if mvb else (float(mh.group(1)) if mh else 600.0)
        scale = dpi / 96.0
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if chrome:
            win_w = max(120, int(math.ceil(vw)) + 16)
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
                        im.crop((0, 0, cw, ch)).save(out)
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
    """Chrome headless 将 SVG 打印为 PDF（无需 fitz，交付双格式）。"""
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        return {"ok": False, "error": "no chrome/chromium"}
    Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--no-pdf-header-footer", f"--print-to-pdf={Path(out_pdf).resolve()}",
                        Path(src_svg).resolve().as_uri()], capture_output=True, timeout=90)
    ok = r.returncode == 0 and Path(out_pdf).exists() and Path(out_pdf).stat().st_size > 500
    return {"ok": bool(ok), "tool": "chrome" if ok else None,
            "error": None if ok else "chrome print-to-pdf failed"}


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
    return {
        "ok": True,
        "size_px": [w, h],
        "mode": orig_mode,
        "dpi": [round(float(raw_dpi[0]), 2), round(float(raw_dpi[1]), 2)] if raw_dpi else None,
        "content_bbox_px": [x0, y0, x1, y1],
        "margins_pct": {"left": round(x0 / w, 4), "right": round((w - 1 - x1) / w, 4),
                        "top": round(y0 / h, 4), "bottom": round((h - 1 - y1) / h, 4)},
        "clipping_suspect": any(edges.values()),
        "edge_hits": edges,
    }


def merge_dicts(*ds):
    out = {}
    for d in ds:
        if d:
            out.update(d)
    return out
