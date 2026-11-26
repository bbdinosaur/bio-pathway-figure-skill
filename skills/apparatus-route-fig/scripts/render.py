#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py — SVG→PNG/PDF 渲染降级链 + 中文字体探测。
优先级：rsvg-convert > cairosvg > inkscape > pymupdf > soffice（完整 SVG 引擎优先）。
"""
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

PREF_FONTS = ["Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "Source Han Sans CN",
              "WenQuanYi Zen Hei", "WenQuanYi Micro Hei", "AR PL UMing CN", "Droid Sans Fallback"]

_CJK_CACHE = None


def _run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r
    except Exception:
        return False, None


def detect_cjk():
    global _CJK_CACHE
    if _CJK_CACHE is not None:
        return _CJK_CACHE
    fams = set()
    try:
        ok, r = _run(["fc-list", ":lang=zh", "family"], 20)
        if ok:
            for line in (r.stdout or "").splitlines():
                for f in line.split(","):
                    if f.strip():
                        fams.add(f.strip())
    except Exception:
        pass
    for p in PREF_FONTS:
        if p in fams:
            _CJK_CACHE = (p, font_file_for(p))
            return _CJK_CACHE
    if fams:
        f = sorted(fams)[0]
        _CJK_CACHE = (f, font_file_for(f))
        return _CJK_CACHE
    try:
        from matplotlib import font_manager
        for e in font_manager.fontManager.ttflist:
            if re.search(r"(CJK|Han|WenQuanYi|UMing|UKai|Hei)", e.name):
                _CJK_CACHE = (e.name, e.fname)
                return _CJK_CACHE
    except Exception:
        pass
    _CJK_CACHE = (None, None)
    return _CJK_CACHE


def font_file_for(family):
    if not family:
        return None
    try:
        ok, r = _run(["fc-list", family, "file"], 20)
        if ok and r.stdout:
            for line in r.stdout.splitlines():
                f = line.strip().rstrip(":")
                if f.endswith((".ttf", ".ttc", ".otf", ".otc")):
                    return f
    except Exception:
        pass
    return None


def _parse_len(val, unit):
    v = float(val)
    u = (unit or "").lower()
    if u == "mm":
        return v * 96.0 / 25.4
    if u == "cm":
        return v * 96.0 / 2.54
    if u == "in":
        return v * 96.0
    if u == "pt":
        return v * 96.0 / 72.0
    if u == "pc":
        return v * 16.0
    return v


def _parse_len_str(raw):
    """解析单个 CSS/SVG 长度值（px/pt/mm/cm/in/pc 或无单位）；百分比 '%' 或非法/非正值返回 None。"""
    if raw is None:
        return None
    m = re.match(r"^\s*\+?((?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-z%]*)\s*$", str(raw), re.I)
    if not m:
        return None
    unit = (m.group(2) or "").lower()
    if unit == "%" or (unit and unit not in ("px", "pt", "mm", "cm", "in", "pc")):
        return None
    v = _parse_len(m.group(1), unit)
    return v if v > 0 else None


def _parse_viewbox_str(raw):
    """解析空格或逗号分隔的 viewBox 四元组，返回 (vx, vy, vw, vh) 或 None。"""
    if not raw:
        return None
    parts = [p for p in re.split(r"[\s,]+", str(raw).strip()) if p]
    if len(parts) != 4:
        return None
    try:
        vx, vy, vw, vh = [float(p) for p in parts]
        if vw > 0 and vh > 0:
            return vx, vy, vw, vh
    except Exception:
        pass
    return None


def _extract_svg_root_tag(txt):
    """剥离前置 XML 注释后锁定根 <svg ...> 开标签，严禁在子元素 <rect> 等处误抓宽高。"""
    clean = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
    m = re.search(r"<svg\b[^>]*>", clean, re.I | re.S)
    return m.group(0) if m else ""


def _tag_attr(tag, name):
    """仅在开标签内解析单/双引号属性（要求属性名前为空白，杜绝误匹配 stroke-width/data-width）。"""
    m = re.search(r"""\s%s\s*=\s*(?:"([^"]*)"|'([^']*)')""" % re.escape(name), tag, re.I)
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def _svg_size_from_text(txt):
    tag = _extract_svg_root_tag(txt)
    if not tag:
        return 1600.0, 900.0
    w = _parse_len_str(_tag_attr(tag, "width"))
    h = _parse_len_str(_tag_attr(tag, "height"))
    if w is not None and h is not None:
        return w, h
    vb = _parse_viewbox_str(_tag_attr(tag, "viewBox"))
    if vb is not None:
        _, _, vw, vh = vb
        if w is not None:
            return w, w * vh / vw
        if h is not None:
            return h * vw / vh, h
        return vw, vh
    return (w or 1600.0), (h or 900.0)


def _svg_size(svg):
    p = Path(svg)
    with p.open("r", encoding="utf-8", errors="ignore") as fp:
        head = fp.read(65536)
    if not _extract_svg_root_tag(head) and p.stat().st_size > 65536:
        head = p.read_text(encoding="utf-8", errors="ignore")
    return _svg_size_from_text(head)


def _fitz():
    try:
        import pymupdf
        return pymupdf
    except Exception:
        try:
            import fitz
            return fitz
        except Exception:
            return None


def _fitz_svg_bytes(svg_path):
    """仅当 SVG 含 <style>、行内 <tspan>、opacity/dasharray 或根尺寸缺失/百分比时，在内存中生成兼容 PyMuPDF 的标准 SVG 字节流（原文件不动）。"""
    raw = Path(svg_path).read_bytes()
    txt = raw.decode("utf-8", errors="ignore")
    root_tag = _extract_svg_root_tag(txt[:65536]) or _extract_svg_root_tag(txt)
    need_size_norm = bool(root_tag) and (
        _parse_len_str(_tag_attr(root_tag, "width")) is None
        or _parse_len_str(_tag_attr(root_tag, "height")) is None
        or "," in (_tag_attr(root_tag, "viewBox") or "")
    )
    if (not need_size_norm and "<style" not in txt and "<tspan" not in txt
            and "opacity" not in txt and "stroke-dasharray" not in txt):
        return raw
    try:
        import xml.etree.ElementTree as ET
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        root = ET.fromstring(raw)
        if need_size_norm:
            rw, rh = _svg_size_from_text(txt)
            if _parse_len_str(root.get("width")) is None:
                root.set("width", "%g" % rw)
            if _parse_len_str(root.get("height")) is None:
                root.set("height", "%g" % rh)
            vb_t = _parse_viewbox_str(root.get("viewBox"))
            if vb_t is not None:
                root.set("viewBox", "%g %g %g %g" % vb_t)
        root_ff = root.get("font-family")
        rules, id_rules = {}, {}
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.split("}")[-1] == "style" and el.text:
                for sel, body in re.findall(r"([^{]+)\{([^}]*)\}", el.text):
                    props = {}
                    for seg in body.split(";"):
                        if ":" in seg:
                            k, v = seg.split(":", 1)
                            props[k.strip()] = v.strip()
                    for part in sel.split(","):
                        part = part.strip()
                        if part.startswith("."):
                            rules.setdefault(part[1:], {}).update(props)
                        elif part.startswith("#"):
                            id_rules.setdefault(part[1:], {}).update(props)
        for el in root.iter():
            cls = (el.get("class") or "").split()
            eid = el.get("id") or ""
            st_raw = el.get("style") or ""
            if (rules or id_rules) and (cls or eid in id_rules):
                merged = {}
                for c in cls:
                    merged.update(rules.get(c, {}))
                if eid in id_rules:
                    merged.update(id_rules[eid])
                if st_raw:
                    for seg in st_raw.split(";"):
                        if ":" in seg:
                            k, v = seg.split(":", 1)
                            merged[k.strip()] = v.strip()
                for k, v in merged.items():
                    if k and not el.get(k):
                        el.set(k, v)
                    elif k and st_raw and k in st_raw:
                        el.set(k, v)
            # PyMuPDF 对 <use>/<path> 内联 style="fill-opacity/stroke-dasharray:..." 支持不完整，提升为显式 XML 属性
            if st_raw and ("opacity" in st_raw or "stroke-dasharray" in st_raw):
                st_map = {}
                for seg in st_raw.split(";"):
                    if ":" in seg:
                        k, v = seg.split(":", 1)
                        st_map[k.strip()] = v.strip()
                for ok in ("fill-opacity", "stroke-opacity", "opacity", "stroke-dasharray"):
                    if ok in st_map and not el.get(ok):
                        el.set(ok, st_map[ok])
                if isinstance(el.tag, str) and el.tag.split("}")[-1] == "use" and not el.get("opacity"):
                    fo = st_map.get("fill-opacity")
                    so = st_map.get("stroke-opacity")
                    if fo and (not so or so == fo):
                        el.set("opacity", fo)
        # 仅当 <tspan> 不含坐标属性（纯行内加粗/变色）时在临时渲染副本中展平，规避 PyMuPDF 行内 tspan 重叠缺陷；并补齐缺失的 font-family
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.split("}")[-1] == "text":
                if root_ff and not el.get("font-family") and "font-family" not in (el.get("style") or ""):
                    el.set("font-family", root_ff)
                ch = list(el)
                if ch and all(isinstance(c.tag, str) and c.tag.split("}")[-1] == "tspan"
                              and not any(c.get(a) for a in ("x", "y", "dx", "dy")) for c in ch):
                    full = "".join(el.itertext())
                    for c in ch:
                        el.remove(c)
                    el.text = full
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except Exception:
        return raw


def _soffice_convert(svg, fmt, dst, timeout=60):
    """在独立临时目录与独立 UserInstallation 中调用 LibreOffice，避免覆盖同目录同名文件或锁冲突。"""
    if not shutil.which("soffice"):
        return False
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render_lo_") as td:
        td_p = Path(td)
        prof = (td_p / "profile").resolve()
        outd = td_p / "out"
        outd.mkdir(parents=True, exist_ok=True)
        cmd = [
            "soffice", "--headless", "--norestore", "--nolockcheck",
            "-env:UserInstallation=file://%s" % prof.as_posix(),
            "--convert-to", fmt, "--outdir", str(outd), str(svg),
        ]
        ok, _ = _run(cmd, timeout)
        cand = outd / (Path(svg).stem + "." + fmt)
        if ok and cand.exists() and cand.stat().st_size > 200:
            shutil.copy2(str(cand), str(dst_p))
            return True
    return False


def _soffice_svg_to_png(svg, png, dpi=300):
    """LibreOffice 兜底转 PNG：优先 SVG→PDF→pdftoppm/gs 以保持真实 DPI，再降级直接转 PNG。"""
    if not shutil.which("soffice"):
        return None
    png_p = Path(png)
    png_p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render_lopng_") as td:
        td_p = Path(td)
        tmp_pdf = td_p / "tmp.pdf"
        if _soffice_convert(svg, "pdf", tmp_pdf, timeout=60):
            if shutil.which("pdftoppm"):
                pref = td_p / "page"
                ok, _ = _run(["pdftoppm", "-png", "-r", str(int(dpi)), "-singlefile", str(tmp_pdf), str(pref)], 60)
                cand = td_p / "page.png"
                if ok and cand.exists() and cand.stat().st_size > 200:
                    shutil.copy2(str(cand), str(png_p))
                    return "soffice+pdftoppm"
            if shutil.which("gs"):
                cand = td_p / "gs.png"
                ok, _ = _run([
                    "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
                    "-sDEVICE=png16m", "-r%d" % int(dpi),
                    "-sOutputFile=%s" % str(cand), str(tmp_pdf),
                ], 60)
                if ok and cand.exists() and cand.stat().st_size > 200:
                    shutil.copy2(str(cand), str(png_p))
                    return "soffice+gs"
    if _soffice_convert(svg, "png", png_p, timeout=60):
        return "soffice"
    return None


def _stamp_png_dpi(png_path, dpi):
    """纯标准库写入/更新 PNG pHYs 块，确保所有渲染引擎导出的 PNG 均携带精确 DPI 元数据（300/96 等）。"""
    try:
        p = Path(png_path)
        data = p.read_bytes()
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
            return
        ppm = max(1, int(round(float(dpi) / 0.0254)))
        phys_body = struct.pack(">IIb", ppm, ppm, 1)
        phys_chunk = struct.pack(">I", len(phys_body)) + b"pHYs" + phys_body + struct.pack(">I", zlib.crc32(b"pHYs" + phys_body) & 0xFFFFFFFF)
        out = bytearray(data[:8])
        pos = 8
        inserted = False
        while pos + 12 <= len(data):
            clen = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            cend = pos + 12 + clen
            if cend > len(data):
                return
            if ctype == b"pHYs":
                if not inserted:
                    out.extend(phys_chunk)
                    inserted = True
            else:
                out.extend(data[pos:cend])
                if ctype == b"IHDR" and not inserted:
                    out.extend(phys_chunk)
                    inserted = True
            pos = cend
        if inserted:
            p.write_bytes(bytes(out))
    except Exception:
        pass


def svg_to_png(svg, png, dpi=300):
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    W, H = _svg_size(svg)
    px, py = max(round(W * dpi / 96.0), 100), max(round(H * dpi / 96.0), 100)
    if shutil.which("rsvg-convert"):
        ok, _ = _run(["rsvg-convert", "-w", str(px), "-h", str(py), "-o", str(png), str(svg)])
        if ok and Path(png).exists() and Path(png).stat().st_size > 200:
            _stamp_png_dpi(png, dpi)
            return "rsvg-convert"
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=px)
        if Path(png).exists() and Path(png).stat().st_size > 200:
            _stamp_png_dpi(png, dpi)
            return "cairosvg"
    except Exception:
        pass
    if shutil.which("inkscape"):
        ok, _ = _run(["inkscape", str(svg), "--export-type=png",
                      "--export-filename=%s" % png, "--export-width=%d" % px], 60)
        if ok and Path(png).exists() and Path(png).stat().st_size > 200:
            _stamp_png_dpi(png, dpi)
            return "inkscape"
    m = _fitz()
    if m is not None:
        try:
            doc = m.open(stream=_fitz_svg_bytes(svg), filetype="svg")
            scale = dpi / 96.0
            pm = doc[0].get_pixmap(matrix=m.Matrix(scale, scale), alpha=False)
            if hasattr(pm, "set_dpi"):
                pm.set_dpi(int(round(dpi)), int(round(dpi)))
            pm.save(str(png))
            doc.close()
            _stamp_png_dpi(png, dpi)
            return "pymupdf"
        except Exception:
            pass
    so_eng = _soffice_svg_to_png(svg, png, dpi)
    if so_eng:
        _stamp_png_dpi(png, dpi)
        return so_eng
    raise RuntimeError("所有 SVG→PNG 引擎均失败；请用 matplotlib 镜像渲染（scripts/mirror.py）")


def svg_to_pdf(svg, pdf):
    Path(pdf).parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsvg-convert"):
        ok, _ = _run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg)])
        if ok and Path(pdf).exists() and Path(pdf).stat().st_size > 200:
            return "rsvg-convert"
    try:
        import cairosvg
        cairosvg.svg2pdf(url=str(svg), write_to=str(pdf))
        if Path(pdf).exists() and Path(pdf).stat().st_size > 200:
            return "cairosvg"
    except Exception:
        pass
    if shutil.which("inkscape"):
        ok, _ = _run(["inkscape", str(svg), "--export-type=pdf",
                      "--export-filename=%s" % pdf], 60)
        if ok and Path(pdf).exists() and Path(pdf).stat().st_size > 200:
            return "inkscape"
    m = _fitz()
    if m is not None:
        try:
            doc = m.open(stream=_fitz_svg_bytes(svg), filetype="svg")
            p2 = m.open("pdf", doc.convert_to_pdf())
            p2.save(str(pdf))
            p2.close()
            doc.close()
            return "pymupdf"
        except Exception:
            pass
    if _soffice_convert(svg, "pdf", pdf, timeout=60):
        return "soffice"
    raise RuntimeError("所有 SVG→PDF 引擎均失败；请用 matplotlib 镜像渲染（scripts/mirror.py）")


def make_preview_png(src_png, dst_preview, src_dpi=300, dst_dpi=96, fallback_svg=None):
    """零重复渲染生成轻量预览 PNG（<=108 DPI）：优先直接用 Pillow 对已渲染 300 DPI PNG 做 LANCZOS 降采样（~20ms），缺 Pillow 再回退 svg_to_png。"""
    pv_dpi = min(max(int(dst_dpi or 96), 48), 108)
    dst = Path(dst_preview)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sp = Path(src_png) if src_png else None
    if sp and sp.exists() and sp.stat().st_size > 200:
        try:
            from PIL import Image
            with Image.open(str(sp)) as im:
                scale = float(pv_dpi) / float(max(int(src_dpi or 300), pv_dpi))
                if scale < 0.99:
                    nw = max(120, int(round(im.width * scale)))
                    nh = max(80, int(round(im.height * scale)))
                    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
                    im = im.resize((nw, nh), resample)
                im.save(str(dst), format="PNG", dpi=(pv_dpi, pv_dpi))
            _stamp_png_dpi(dst, pv_dpi)
            return "pillow-downsample"
        except Exception:
            pass
    if fallback_svg and Path(fallback_svg).exists():
        return svg_to_png(fallback_svg, dst, pv_dpi)
    raise RuntimeError("预览图生成失败：缺少源 PNG 与回退 SVG")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="SVG→PNG/PDF 渲染工具 / CJK 字体探测")
    ap.add_argument("--svg", help="待渲染 SVG 文件路径")
    ap.add_argument("--png", help="输出 PNG 路径")
    ap.add_argument("--pdf", help="输出 PDF 路径")
    ap.add_argument("--preview", help="可选轻量预览 PNG 路径（<=108 DPI）")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--preview-dpi", type=int, default=96)
    a = ap.parse_args()
    fam, ffile = detect_cjk()
    res = {"cjk_family": fam, "cjk_file": ffile}
    if a.svg:
        if a.png:
            res["png"] = {"engine": svg_to_png(a.svg, a.png, a.dpi), "path": a.png, "dpi": a.dpi}
        if a.pdf:
            res["pdf"] = {"engine": svg_to_pdf(a.svg, a.pdf), "path": a.pdf}
        if a.preview:
            pv_dpi = min(int(a.preview_dpi or 96), 108)
            res["preview"] = {"engine": make_preview_png(a.png, a.preview, a.dpi, pv_dpi, fallback_svg=a.svg),
                              "path": a.preview, "dpi": pv_dpi}
    print(json.dumps(res, ensure_ascii=False))
