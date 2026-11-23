#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_probe.py — 科研论文 PDF 探针与按页提取工具（pymupdf → pdfplumber → pypdf → pdftotext 自动降级）。
用途：单次调用摸清 PDF 页数、章节标题、Figure/Table 图注所在页码，支持按关键词检索或按页输出原文，
以及将指定页渲染为 PNG 供视觉核查，避免 Agent 猜测原论文内容或遗漏关键页。

用法:
  python3 pdf_probe.py paper.pdf --summary
  python3 pdf_probe.py paper.pdf --search "Figure 3|Fig. 3|Method|Protocol"
  python3 pdf_probe.py paper.pdf --pages 3-5
  python3 pdf_probe.py paper.pdf --render-page 4 --out /app/work/p4.png --dpi 100
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _extract_pages(pdf_path, max_pages=None):
    """返回 (engine, [page1_text, page2_text, ...])，优先最快 C 后端（pymupdf → pdftotext → pypdf → pdfplumber 限时兜底）。"""
    import time
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError("PDF 不存在: %s" % p)
    # 1. PyMuPDF (fitz) — C 引擎，速度最快
    for modname in ("pymupdf", "fitz"):
        try:
            m = __import__(modname)
            doc = m.open(str(p))
            n = min(len(doc), max_pages) if max_pages else len(doc)
            pages = [doc[i].get_text("text") or "" for i in range(n)]
            doc.close()
            return "pymupdf", pages
        except Exception:
            pass
    # 2. pdftotext CLI (poppler C 引擎，几十页通常 <0.1s)
    if shutil.which("pdftotext"):
        try:
            cmd = ["pdftotext"]
            if max_pages:
                cmd += ["-f", "1", "-l", str(int(max_pages))]
            cmd += [str(p), "-"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                raw = r.stdout or ""
                pages = raw.split("\x0c")
                if pages and not pages[-1].strip():
                    pages = pages[:-1]
                return "pdftotext", pages
        except Exception:
            pass
    # 3. pypdf / PyPDF2 — 轻量纯 Python
    for modname in ("pypdf", "PyPDF2"):
        try:
            m = __import__(modname)
            rd = m.PdfReader(str(p))
            n = min(len(rd.pages), max_pages) if max_pages else len(rd.pages)
            pages = [(rd.pages[i].extract_text() or "") for i in range(n)]
            return modname, pages
        except Exception:
            pass
    # 4. pdfplumber — 末级兜底（限制最多 20 秒防复杂矢量 PDF 阻塞）
    try:
        import pdfplumber
        t0 = time.monotonic()
        pages = []
        with pdfplumber.open(str(p)) as pdf:
            n = min(len(pdf.pages), max_pages) if max_pages else len(pdf.pages)
            for i in range(n):
                if time.monotonic() - t0 > 20.0:
                    break
                pages.append(pdf.pages[i].extract_text() or "")
        return "pdfplumber", pages
    except Exception:
        pass
    raise RuntimeError("未找到可用的 PDF 文本提取后端（pymupdf/pdftotext/pypdf/pdfplumber）")


def _parse_page_spec(spec, total):
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo = max(1, int(a.strip()))
            hi = min(total, int(b.strip()))
            for i in range(lo, hi + 1):
                out.add(i)
        else:
            idx = int(part)
            if 1 <= idx <= total:
                out.add(idx)
    return sorted(out)


def _render_page(pdf_path, page_num, out_png, dpi=100):
    p, dst = Path(pdf_path), Path(out_png)
    dst.parent.mkdir(parents=True, exist_ok=True)
    for modname in ("pymupdf", "fitz"):
        try:
            m = __import__(modname)
            doc = m.open(str(p))
            if not (1 <= page_num <= len(doc)):
                doc.close()
                raise ValueError("页码越界: %d (总页数 %d)" % (page_num, len(doc)))
            sc = dpi / 72.0
            pm = doc[page_num - 1].get_pixmap(matrix=m.Matrix(sc, sc), alpha=False)
            pm.save(str(dst))
            doc.close()
            return "pymupdf"
        except ValueError:
            raise
        except Exception:
            pass
    if shutil.which("pdftoppm"):
        stem = dst.with_suffix("")
        r = subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page_num), "-l", str(page_num),
             "-singlefile", str(p), str(stem)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0 and dst.exists():
            return "pdftoppm"
    raise RuntimeError("无法渲染 PDF 页面（需 pymupdf 或 pdftoppm）")


def summarize(pdf_path, engine, pages):
    fig_pat = re.compile(r"^\s*((?:Figure|Fig\.?|Supplementary\s+Fig\.?|图)\s*[S]?\d+[A-Za-z]?[\.:：]?\s*.{0,140})", re.I)
    tbl_pat = re.compile(r"^\s*((?:Table|Supplementary\s+Table|表)\s*[S]?\d+[\.:：]?\s*.{0,120})", re.I)
    sec_pat = re.compile(
        r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(Abstract|Introduction|Materials?\s+and\s+Methods?|Methods?|"
        r"Experimental(?:\s+Setup|\s+Section|\s+Procedures?)?|Results?|Discussion|Conclusion|"
        r"Protocol|Workflow|Technical\s+Route|实验装置|实验方法|实验步骤|材料与方法|技术路线|结果与讨论)\b.{0,60}$",
        re.I,
    )
    figures, tables, sections, empty_pages = [], [], [], []
    for idx, txt in enumerate(pages, 1):
        if len(txt.strip()) < 30:
            empty_pages.append(idx)
        for line in txt.splitlines():
            s = line.strip()
            if not s:
                continue
            m = fig_pat.match(s)
            if m and len(figures) < 40:
                figures.append({"page": idx, "caption": re.sub(r"\s+", " ", m.group(1))[:160]})
                continue
            m = tbl_pat.match(s)
            if m and len(tables) < 30:
                tables.append({"page": idx, "caption": re.sub(r"\s+", " ", m.group(1))[:160]})
                continue
            if len(s) <= 80 and sec_pat.match(s) and len(sections) < 30:
                sections.append({"page": idx, "heading": s})
    first_lines = [ln.strip() for ln in (pages[0] if pages else "").splitlines() if ln.strip()][:5]
    out = {
        "pdf": str(pdf_path),
        "engine": engine,
        "page_count": len(pages),
        "total_chars": sum(len(t) for t in pages),
        "first_page_head": first_lines,
        "sections": sections,
        "figures": figures,
        "tables": tables,
        "empty_or_scanned_pages": empty_pages,
    }
    if len(empty_pages) == len(pages) and len(pages) > 0:
        out["warning"] = "全文档未检测到可提取文本，可能是扫描件 PDF；请使用 --render-page 渲染页面或调用 OCR 工具"
    return out


def search_pages(pages, pattern, context=2, max_hits=30):
    rx = re.compile(pattern, re.I)
    hits = []
    for idx, txt in enumerate(pages, 1):
        lines = txt.splitlines()
        for li, ln in enumerate(lines):
            if rx.search(ln):
                lo = max(0, li - context)
                hi = min(len(lines), li + context + 1)
                snippet = "\n".join(x.strip() for x in lines[lo:hi] if x.strip())
                hits.append({"page": idx, "line": li + 1, "snippet": snippet[:420]})
                if len(hits) >= max_hits:
                    return hits
    return hits


def main():
    ap = argparse.ArgumentParser(description="科研论文 PDF 探针与按页提取")
    ap.add_argument("pdf", help="PDF 文件路径")
    ap.add_argument("--summary", action="store_true", help="输出结构摘要（页数/章节/Figure与Table图注页码）")
    ap.add_argument("--pages", default=None, help="按页输出原文，如 1-3,7")
    ap.add_argument("--search", default=None, help="正则关键词检索（不区分大小写）并返回页码与上下文")
    ap.add_argument("--max-chars", type=int, default=16000, help="--pages 输出字符上限")
    ap.add_argument("--render-page", type=int, default=None, help="将指定页码（1-indexed）渲染为 PNG")
    ap.add_argument("--out", default=None, help="--render-page 输出 PNG 路径")
    ap.add_argument("--dpi", type=int, default=100, help="渲染 DPI（预览建议 <=108，默认 100）")
    a = ap.parse_args()

    if a.render_page is not None:
        if not a.out:
            print(json.dumps({"ok": False, "error": "--render-page 需要同时指定 --out"}, ensure_ascii=False))
            return 2
        eng = _render_page(a.pdf, a.render_page, a.out, a.dpi)
        print(json.dumps({"ok": True, "pdf": str(a.pdf), "page": a.render_page,
                          "png": str(a.out), "dpi": a.dpi, "engine": eng}, ensure_ascii=False, indent=1))
        return 0

    eng, pages = _extract_pages(a.pdf)
    if a.search:
        hits = search_pages(pages, a.search)
        print(json.dumps({"pdf": str(a.pdf), "engine": eng, "page_count": len(pages),
                          "pattern": a.search, "hit_count": len(hits), "hits": hits},
                         ensure_ascii=False, indent=1))
        return 0

    if a.pages:
        sel = _parse_page_spec(a.pages, len(pages))
        buf, used = [], 0
        for pno in sel:
            chunk = "=== [Page %d / %d] ===\n%s\n" % (pno, len(pages), pages[pno - 1].strip())
            if used + len(chunk) > a.max_chars:
                rem = max(0, a.max_chars - used)
                if rem > 60:
                    buf.append(chunk[:rem] + "\n...[truncated]...")
                break
            buf.append(chunk)
            used += len(chunk)
        print("\n".join(buf))
        return 0

    # 默认执行 summary
    print(json.dumps(summarize(a.pdf, eng, pages), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
