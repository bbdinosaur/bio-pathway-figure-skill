#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svg_edit.py — 图稿 source-preserving 编辑与机制图/流程图构建主入口。
模式 1 (编辑既有 PDF/SVG): --input fig.pdf --ops ops.json --out-svg out.svg --out-pdf out.pdf --preview out.png
模式 2 (改前只读侦查):     --inspect --input fig.pdf [--page 0] [--find-text "Figure 3"]
模式 3 (空白画布 ops):     --blank 900x540 --ops ops.json --out-svg mech.svg [--out-pdf mech.pdf] --preview mech.png
模式 4 (机制图自动排版):   --diagram mech.json --out-svg mech.svg [--out-pdf mech.pdf] --preview mech.png
语法见 references/chart_recipes.md。"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kit_common import (  # noqa: E402
    dump_json, rasterize_any, pdf_to_png, svg_to_pdf_any,
    verify_svg_editable, sha256_of, _import_fitz,
)
from svg_ops import apply_ops, _est_text_w, _wrap_text, DEFAULT_FONT  # noqa: E402


ROLE_PALETTE = {
    "ligand": ("#E6F4F1", "#1B7F79"),
    "signal": ("#E6F4F1", "#1B7F79"),
    "receptor": ("#FFF3E0", "#C66900"),
    "kinase": ("#EBF3FA", "#2B5B84"),
    "enzyme": ("#EBF3FA", "#2B5B84"),
    "protein": ("#EEF3FA", "#33506B"),
    "tf": ("#F3ECFA", "#6B3FA0"),
    "transcription": ("#F3ECFA", "#6B3FA0"),
    "gene": ("#FCEEF2", "#B53864"),
    "dna": ("#FCEEF2", "#B53864"),
    "mrna": ("#FCEEF2", "#B53864"),
    "drug": ("#FDECEC", "#B83227"),
    "inhibitor": ("#FDECEC", "#B83227"),
    "process": ("#EDF5E8", "#3A7D44"),
    "phenotype": ("#EDF5E8", "#3A7D44"),
    "outcome": ("#EDF5E8", "#3A7D44"),
}


def _node_colors(nd):
    role = str(nd.get("role") or "").strip().lower()
    df, ds = ROLE_PALETTE.get(role, ("#EEF3FA", "#33506B"))
    return nd.get("fill") or df, nd.get("stroke") or ds


def _complex_ops(spec, pos, font_fam):
    """根据 complexes:[{id,label,members:[id1,id2]}] 绘制多蛋白复合物虚线包络框。"""
    out = []
    for ci, cx in enumerate(spec.get("complexes") or []):
        mems = [pos[mid] for mid in (cx.get("members") or []) if mid in pos]
        if not mems:
            continue
        x0 = min(b[0] for b in mems) - 12.0
        y0 = min(b[1] for b in mems) - 24.0
        x1 = max(b[0] + b[2] for b in mems) + 12.0
        y1 = max(b[1] + b[3] for b in mems) + 10.0
        out.append({
            "op": "add_compartment",
            "id": cx.get("id", f"complex-{ci}"),
            "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
            "title": cx.get("label") or cx.get("title") or "",
            "title_pos": cx.get("title_pos", "top_right"),
            "fill": cx.get("fill", "#FAFBFD"),
            "stroke": cx.get("stroke", "#6A7E96"),
            "dashed": cx.get("dashed", True),
            "font_family": font_fam,
        })
    return out


def verify_entities_against_pdf(entities, pdf_path):
    """对照原论文 PDF 全文智能分层核验机制图实体名（精确/大小写无关/希腊字母/核心词 + 疑似基因拼写错误拦截）。"""
    import difflib
    import re
    if not pdf_path or not Path(pdf_path).exists():
        return {"ok": None, "note": "未提供原论文 PDF，跳过实体接地核验"}
    pages = []
    try:
        fitz = _import_fitz()
        doc = fitz.open(str(pdf_path))
        pages = [re.sub(r"-\s*\n\s*", "", doc[i].get_text("text") or "") for i in range(doc.page_count)]
        doc.close()
    except Exception as ex:
        return {"ok": None, "error": f"{type(ex).__name__}: {ex}"}

    def _greek_norm(s):
        return (s.replace("α", "a").replace("β", "b").replace("γ", "g")
                 .replace("κ", "k").replace("δ", "d").replace("μ", "u"))

    pages_lo = [p.lower() for p in pages]
    pages_gn = [_greek_norm(p).lower() for p in pages]
    full_txt = "\n".join(pages)
    vocab = sorted(set(re.findall(r"[A-Za-z0-9α-ωΑ-Ω][A-Za-z0-9α-ωΑ-Ω\-_/]{1,28}", full_txt)))
    stop_toks = {"the", "and", "for", "with", "from", "cell", "cells", "pathway", "signal",
                 "signaling", "complex", "protein", "gene", "receptor", "kinase", "factor",
                 "activation", "inhibition", "arrest", "death", "growth", "response", "cycle"}
    details = []
    n_grounded = 0
    typo_suspects = []
    unverified_desc = []
    for ent in entities:
        lbl = str(ent.get("label") or "").strip()
        if not lbl:
            continue
        lbl_lo = lbl.lower()
        parts = [p.strip() for p in re.split(r"[\s/,()+]+", lbl) if len(p.strip()) >= 2]
        hit_page = None
        match_kind = "exact"
        for pi, ptxt in enumerate(pages):
            if lbl in ptxt:
                hit_page = pi
                break
        if hit_page is None:
            for pi, ptxt in enumerate(pages_lo):
                if lbl_lo in ptxt:
                    hit_page = pi
                    match_kind = "case_insensitive"
                    break
        if hit_page is None:
            gn_lbl = _greek_norm(lbl).lower()
            greek_pat = re.sub(r"[αβγδκμΑΒΓΔΚΜ]", r".?", re.escape(lbl))
            greek_re = re.compile(greek_pat, re.I) if greek_pat != re.escape(lbl) else None
            for pi, ptxt in enumerate(pages_gn):
                if (gn_lbl != lbl_lo and gn_lbl in ptxt) or (greek_re and greek_re.search(pages[pi])):
                    hit_page = pi
                    match_kind = "greek_normalized"
                    break
        if hit_page is None and len(parts) >= 2:
            # 复合名称（如 "p53 (TP53)" 或 "PI3K/AKT signaling"）：核心实体 token 命中即可接地
            sci_parts = [tk for tk in parts if tk.lower() not in stop_toks]
            hits = [(tk, next((pi for pi, ptxt in enumerate(pages_lo) if tk.lower() in ptxt), None))
                    for tk in (sci_parts or parts)]
            found_hits = [(tk, fp) for tk, fp in hits if fp is not None]
            if found_hits and len(found_hits) >= max(1, (len(hits) + 1) // 2):
                hit_page = min(fp for _, fp in found_hits)
                match_kind = "token_grounded"
        if hit_page is not None:
            n_grounded += 1
            details.append({"id": ent.get("id"), "label": lbl, "found_exact": (match_kind == "exact"),
                            "grounded": True, "match_kind": match_kind, "first_page": hit_page})
        else:
            sugg = []
            for tk in (parts or [lbl]):
                if tk.lower() not in stop_toks:
                    sugg.extend(difflib.get_close_matches(tk, vocab, n=2, cutoff=0.75))
            sugg = sorted(set(sugg))[:4]
            looks_like_symbol = bool(re.match(r"^[A-Za-z0-9α-ωΑ-Ω\-_/]{2,14}$", lbl) and any(c.isupper() or c.isdigit() for c in lbl))
            rec = {"id": ent.get("id"), "label": lbl, "found_exact": False, "grounded": False,
                   "suggestions": sugg}
            details.append(rec)
            if looks_like_symbol and sugg:
                typo_suspects.append(rec)
            else:
                unverified_desc.append(rec)
    total = len(details)
    return {
        "ok": (len(typo_suspects) == 0),
        "source_pdf": str(pdf_path),
        "grounded_exact": n_grounded,
        "total_entities": total,
        "grounded_ratio": round(n_grounded / max(1, total), 4),
        "typo_suspects": typo_suspects,
        "unverified_descriptive": unverified_desc,
        "unmatched": typo_suspects,
        "details": details,
    }


def _svg_text_snapshot(svg_path):
    """提取 SVG 中所有 <text> 文本列表，用于计算 source-preserving 编辑差分。"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(svg_path)).getroot()
        return ["".join(el.itertext()).strip()
                for el in root.iter() if el.tag.split("}")[-1] == "text" and "".join(el.itertext()).strip()]
    except Exception:
        return []


def _compute_edit_diff(before_texts, after_texts):
    from collections import Counter
    cb, ca = Counter(before_texts), Counter(after_texts)
    unchanged = sum((cb & ca).values())
    removed = list((cb - ca).elements())
    added = list((ca - cb).elements())
    ratio = round(unchanged / max(1, len(before_texts)), 4)
    return {
        "before_count": len(before_texts),
        "after_count": len(after_texts),
        "unchanged_count": unchanged,
        "removed_or_replaced": removed[:30],
        "added_or_new": added[:30],
        "source_preserved_ratio": ratio,
    }


def _has_cjk(s):
    return any(0x2E80 <= ord(ch) <= 0x9FFF for ch in str(s))


def _hex_to_rgb01(h, default=(0.2, 0.31, 0.42)):
    try:
        s = str(h).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return default


def _sample_bg_rgb01(pg, rect):
    """采样 PDF 页面上 rect 外缘 2px 处背景色（0..1 RGB），使彩色盒内文字替换无白块。"""
    try:
        clip = type(rect)(max(0, rect.x0 - 3), max(0, rect.y0 - 3),
                          min(pg.rect.width, rect.x1 + 3), min(pg.rect.height, rect.y1 + 3))
        pix = pg.get_pixmap(clip=clip, dpi=72)
        if pix.width >= 2 and pix.height >= 2:
            # 取左上角外缘像素
            p = pix.pixel(0, 0)
            return (p[0] / 255.0, p[1] / 255.0, p[2] / 255.0)
    except Exception:
        pass
    return (1.0, 1.0, 1.0)


def edit_pdf_ops(pdf_path, ops, page=0):
    """把可映射到 PDF 的操作并行应用：replace_text(逐处红改+自动背景采样)、add_text/box/arrow；move/delete/recolor→svg_only。"""
    fitz = _import_fitz()
    doc = fitz.open(str(pdf_path))
    pg = doc[page]
    log = []
    for op in ops:
        k = op.get("op")
        e = {"op": k, "status": "svg_only", "detail": ""}
        try:
            if k == "replace_text":
                import re as _re
                find = op["find"]
                match_mode = op.get("match", "contains")
                max_hits = int(op.get("max_hits", 20))

                def _span_match(txt):
                    if match_mode == "exact":
                        return txt.strip() == find.strip()
                    if match_mode == "regex":
                        return bool(_re.search(find, txt))
                    return find in txt

                def _span_replace(txt):
                    if match_mode == "exact":
                        return op["replace"]
                    if match_mode == "regex":
                        return _re.sub(find, op["replace"], txt)
                    return txt.replace(find, op["replace"])

                spans = []
                for b in pg.get_text("dict")["blocks"]:
                    for ln in b.get("lines", []):
                        for sp in ln.get("spans", []):
                            if _span_match(sp.get("text", "")):
                                spans.append(sp)
                spans = spans[:max_hits]
                if spans:
                    # 整 span 红改后按原 origin/size/color 回写，避免局部红改误伤邻近字符，也支持变长替换
                    targets = []
                    for sp in spans:
                        sr = fitz.Rect(sp["bbox"])
                        bg_col = (_hex_to_rgb01(op["bg_fill"], (1, 1, 1)) if op.get("bg_fill")
                                  else _sample_bg_rgb01(pg, sr))
                        redact_r = (fitz.Rect(sr.x0, sr.y0 + 0.3, sr.x1, sr.y1 - 0.3)
                                    if sr.height > 2.5 else sr)
                        pg.add_redact_annot(redact_r, fill=bg_col)
                        orig = sp.get("origin") or (sr.x0, sr.y1 - 2.0)
                        if op.get("fill"):
                            col = _hex_to_rgb01(op["fill"], (0, 0, 0))
                        else:
                            cint = int(sp.get("color", 0) or 0)
                            col = (((cint >> 16) & 255) / 255.0,
                                   ((cint >> 8) & 255) / 255.0,
                                   (cint & 255) / 255.0)
                        new_txt = _span_replace(sp["text"])
                        targets.append((orig, float(sp["size"]), col, new_txt))
                    pg.apply_redactions()
                    for orig, sz, col, new_txt in targets:
                        fn = "china-s" if _has_cjk(new_txt) else "helv"
                        pg.insert_text((orig[0], orig[1]), new_txt,
                                       fontname=fn, fontsize=sz, color=col)
                    e.update(status="applied", after=op["replace"], n=len(targets))
                elif match_mode == "contains":
                    # 跨 span 命中兜底（仅 contains 模式）：search_for 并右缘微收紧防误伤后续词
                    rects = pg.search_for(find)[:max_hits]
                    if not rects:
                        e["status"] = "not_found_in_pdf"
                    else:
                        targets = []
                        for r in rects:
                            bg_col = (_hex_to_rgb01(op["bg_fill"], (1, 1, 1)) if op.get("bg_fill")
                                      else _sample_bg_rgb01(pg, r))
                            rr = fitz.Rect(r.x0, r.y0 + 0.3, max(r.x0 + 1, r.x1 - 0.6), r.y1 - 0.3)
                            pg.add_redact_annot(rr, fill=bg_col)
                            targets.append((r, 11.0, r.y1 - 2.0))
                        pg.apply_redactions()
                        fn = "china-s" if _has_cjk(op["replace"]) else "helv"
                        col = _hex_to_rgb01(op.get("fill", "#000000"), (0, 0, 0))
                        for r, sz, base_y in targets:
                            pg.insert_text((r.x0, base_y), op["replace"],
                                           fontname=fn, fontsize=sz, color=col)
                        e.update(status="applied", after=op["replace"], n=len(targets))
                else:
                    e["status"] = "not_found_in_pdf"
            elif k == "set_text":
                e["status"] = "svg_only"
                e["detail"] = "set_text 需 id，PDF 路径仅支持文本查找"
            elif k == "add_text":
                fn = "china-s" if _has_cjk(op.get("text", "")) else "helv"
                col = _hex_to_rgb01(op.get("fill", "#000000"), (0, 0, 0))
                pg.insert_text((op["x"], op["y"]), op.get("text", ""), fontname=fn,
                               fontsize=float(op.get("font_pt", 12)), color=col)
                e["status"] = "applied"
            elif k == "add_box":
                col = _hex_to_rgb01(op.get("stroke", "#33506B"))
                fill = _hex_to_rgb01(op.get("fill", "#EEF3FA"), (0.93, 0.95, 0.98))
                pg.draw_rect(fitz.Rect(op["x"], op["y"], op["x"] + op["w"], op["y"] + op["h"]),
                             color=col, fill=fill, width=op.get("stroke_w", 1.2),
                             radius=min(0.5, op.get("rx", 4) / max(1e-6, min(op["w"], op["h"]))))
                if op.get("label"):
                    fn = "china-s" if _has_cjk(op["label"]) else "helv"
                    pg.insert_text((op["x"] + 6, op["y"] + op["h"] / 2.0 + op.get("font_pt", 11) * 0.35),
                                   op["label"], fontname=fn, fontsize=float(op.get("font_pt", 11)))
                e["status"] = "applied"
            elif k in ("add_arrow", "add_line") and "x1" in op and "x2" in op:
                style = op.get("style") or ("line" if k == "add_line" else "activate")
                default_hex = "#C0392B" if style in ("inhibit", "tbar") else "#33506B"
                col = _hex_to_rgb01(op.get("stroke", default_hex))
                p1 = fitz.Point(op["x1"], op["y1"])
                p2 = fitz.Point(op["x2"], op["y2"])
                dashes = "[5 3] 0" if op.get("dashed") else None
                pg.draw_line(p1, p2, color=col, width=op.get("width", 1.4), dashes=dashes)
                ang = math.atan2(p2.y - p1.y, p2.x - p1.x)
                if style in ("inhibit", "tbar"):
                    L = 5.5
                    px, py = -math.sin(ang) * L, math.cos(ang) * L
                    pg.draw_line(fitz.Point(p2.x - px, p2.y - py),
                                 fitz.Point(p2.x + px, p2.y + py), color=col, width=2.0)
                elif style in ("activate", "both", "arrow"):
                    L = 7.0
                    a = fitz.Point(p2.x - L * math.cos(ang - 0.42), p2.y - L * math.sin(ang - 0.42))
                    b = fitz.Point(p2.x - L * math.cos(ang + 0.42), p2.y - L * math.sin(ang + 0.42))
                    pg.draw_polyline([a, p2, b], color=col, width=op.get("width", 1.4))
                if op.get("label"):
                    fn = "china-s" if _has_cjk(op["label"]) else "helv"
                    fpt_l = float(op.get("font_pt", 10))
                    tw_l = _est_text_w(op["label"], fpt_l)
                    pg.insert_text(((op["x1"] + op["x2"]) / 2 - tw_l / 2, (op["y1"] + op["y2"]) / 2 - 5),
                                   op["label"], fontname=fn, fontsize=fpt_l)
                e["status"] = "applied"
        except Exception as ex:
            e["status"] = "failed"
            e["detail"] = f"{type(ex).__name__}: {ex}"
        log.append({"applied_to": "pdf", **e})
    tmp = str(pdf_path) + ".tmp"
    doc.save(tmp)
    doc.close()
    os.replace(tmp, str(pdf_path))
    return log


def inspect_pdf(pdf_path, page=0, find_text=None):
    """列出页面尺寸、全部文字 span（文本/坐标/字号/字体）与矢量图形颜色，供精准构造 ops。"""
    fitz = _import_fitz()
    doc = fitz.open(str(pdf_path))
    if find_text:
        n_pages = doc.page_count
        hits = [i for i in range(n_pages) if doc[i].search_for(find_text)]
        doc.close()
        return {"find_text": find_text, "n_pages": n_pages, "pages_with_text": hits,
                "hint": "用 --page <命中页号> 再 inspect 该页详情，或直接作为编辑输入页"}
    page_obj = doc[page]
    texts = []
    for b in page_obj.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip():
                    r = sp["bbox"]
                    texts.append({"text": sp["text"], "bbox": [round(v, 1) for v in r],
                                  "x0": round(r[0], 1), "y0": round(r[1], 1),
                                  "baseline_y": round(r[3] - 2, 1), "size": round(sp["size"], 1),
                                  "font": sp["font"]})
    fills, strokes = set(), set()
    for d in page_obj.get_drawings():
        for key, sink in (("fill", fills), ("color", strokes)):
            c = d.get(key)
            if c:
                sink.add("#" + "".join(f"{int(round(v * 255)):02X}" for v in c[:3]))
    info = {"page": page, "n_pages": doc.page_count,
            "rect": [round(v, 1) for v in page_obj.rect],
            "note": "坐标系为顶部原点(y向下)，add_text/add_box 直接用此坐标",
            "texts": texts, "fill_colors": sorted(fills), "stroke_colors": sorted(strokes)}
    doc.close()
    return info


def extract_pdf_text(pdf_path, query=None, out_txt=None, render_hits=None):
    """提取原论文 PDF 逐页文本、Figure 图注、查询命中段落，以及命中页的空间矢量文字标签清单（含 x,y 坐标与可选页图渲染）。"""
    import re
    pages = []
    tool = None
    fitz_mod = None
    try:
        fitz_mod = _import_fitz()
        doc = fitz_mod.open(str(pdf_path))
        for i in range(doc.page_count):
            pages.append(doc[i].get_text("text") or "")
        doc.close()
        tool = "pymupdf"
    except Exception:
        try:
            import pdfplumber
            with pdfplumber.open(str(pdf_path)) as pdf:
                for p in pdf.pages:
                    pages.append(p.extract_text() or "")
            tool = "pdfplumber"
        except Exception as e:
            return {"ok": False, "error": f"PDF 文本提取依赖不可用: {type(e).__name__}: {e}"}

    if out_txt:
        Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
        joined = "\n\n".join(f"===== PAGE {i} =====\n{t}" for i, t in enumerate(pages))
        Path(out_txt).write_text(joined, encoding="utf-8")

    fig_pat = re.compile(
        r"(?:^|\n)\s*(?:Extended\s+Data\s+|Supplementary\s+)?(?:Fig(?:ure)?\.?\s*\d+[A-Za-z]?|图\s*\d+)\b",
        re.I,
    )
    q_pat = re.compile(query, re.I) if query else None
    mech_verb_pat = re.compile(
        r"\b(?:activat\w*|inhibit\w*|phosphorylat\w*|ubiquitinat\w*|acetylat\w*|methylat\w*|"
        r"suppress\w*|induc\w*|promot\w*|translocat\w*|bind\w*|cleav\w*|block\w*|recruit\w*|"
        r"mediat\w*|upregulat\w*|downregulat\w*|repress\w*|stimulat\w*|driv\w*|antagoniz\w*|degrad\w*)\b",
        re.I,
    )
    captions, matches, mech_sents = [], [], []
    hit_pages = []
    for pi, txt in enumerate(pages):
        clean_pg = re.sub(r"-\s*\n\s*", "", txt)
        paras = [p.strip() for p in re.split(r"\n\s*\n", clean_pg) if p.strip()]
        for p in paras:
            one = re.sub(r"\s+", " ", p)
            if fig_pat.search(p[:180]):
                captions.append({"page": pi, "text": one[:2500]})
            if q_pat and q_pat.search(one):
                matches.append({"page": pi, "text": one[:2500]})
                if pi not in hit_pages:
                    hit_pages.append(pi)
    if not hit_pages and captions:
        hit_pages = sorted({c["page"] for c in captions})[:3]
    for pi in (hit_pages or list(range(min(len(pages), 4)))):
        clean_pg = re.sub(r"-\s*\n\s*", "", pages[pi])
        for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", clean_pg)):
            if 25 <= len(sent) <= 360 and mech_verb_pat.search(sent):
                mech_sents.append({"page": pi, "sentence": sent.strip()})
                if len(mech_sents) >= 25:
                    break
        if len(mech_sents) >= 25:
            break

    # 对命中页提取空间坐标标签（帮助准确还原原图 Figure 中的基因/蛋白/区室名及上下游位置）
    spatial_pages = []
    rendered_pages = []
    if fitz_mod and hit_pages:
        try:
            doc = fitz_mod.open(str(pdf_path))
            for pi in hit_pages[:4]:
                pg = doc[pi]
                short_labels = []
                for b in pg.get_text("dict").get("blocks", []):
                    for ln in b.get("lines", []):
                        line_txt = "".join(sp.get("text", "") for sp in ln.get("spans", [])).strip()
                        if not line_txt or len(line_txt) > 65:
                            continue
                        bb = ln.get("bbox", [0, 0, 0, 0])
                        sz = round(float(ln["spans"][0].get("size", 0)), 1) if ln.get("spans") else 0.0
                        short_labels.append({"text": line_txt, "x": round(bb[0], 1),
                                             "y": round(bb[1], 1), "size": sz})
                short_labels.sort(key=lambda r: (round(r["y"] / 18.0), r["x"]))
                n_imgs = len(pg.get_images(full=False))
                spatial_pages.append({
                    "page": pi, "rect": [round(pg.rect.width, 1), round(pg.rect.height, 1)],
                    "n_images": n_imgs,
                    "figure_is_raster_hint": bool(n_imgs > 0 and len(short_labels) < 8),
                    "spatial_labels": short_labels[:120],
                })
                if render_hits:
                    Path(render_hits).mkdir(parents=True, exist_ok=True)
                    png_out = Path(render_hits) / f"page_{pi}.png"
                    pix = pg.get_pixmap(dpi=100)
                    pix.save(str(png_out))
                    rendered_pages.append({"page": pi, "png": str(png_out)})
            doc.close()
        except Exception:
            pass

    import collections as _coll
    _ent_re = re.compile(
        r"\b(?:[A-Z][A-Z0-9]{1,8}(?:[-/][A-Za-z0-9α-ωΑ-Ω]{1,6})?|"
        r"p[0-9]{2,3}|mTORC[12]|NF-[κk]B|TGF-[βb][0-9]?|IL-[0-9]{1,2}|TNF-[αa]|IFN-[γg])\b"
    )
    _stop = {"THE", "AND", "FOR", "WITH", "FROM", "FIG", "FIGURE", "TABLE", "PDF", "SVG", "PNG", "DPI", "DOI", "USA"}
    clean_joined = re.sub(r"-\s*\n\s*", "", "\n".join(pages))
    ent_cnt = _coll.Counter(
        t for t in _ent_re.findall(clean_joined) if t.upper() not in _stop and not t.isdigit()
    )

    return {
        "ok": True, "tool": tool, "input": str(pdf_path),
        "n_pages": len(pages), "total_chars": sum(len(t) for t in pages),
        "out_txt": str(out_txt) if out_txt else None,
        "figure_captions": captions[:20],
        "query": query, "query_matches": matches[:25],
        "hit_pages": hit_pages,
        "mechanism_sentences": mech_sents[:25],
        "candidate_entities": [k for k, _ in ent_cnt.most_common(35)],
        "spatial_pages": spatial_pages,
        "rendered_pages": rendered_pages,
    }


def inspect_svg(svg_path):
    import re
    import xml.etree.ElementTree as ET
    root = ET.parse(str(svg_path)).getroot()
    texts, fills, strokes = [], set(), set()
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if el.get("fill") and el.get("fill") != "none":
            fills.add(el.get("fill"))
        if el.get("stroke") and el.get("stroke") != "none":
            strokes.add(el.get("stroke"))
        if tag == "text":
            txt = "".join(el.itertext()).strip()
            if txt:
                fs = el.get("font-size")
                if fs is None and el.get("style"):
                    mfs = re.search(r"font-size:\s*([\d.]+)", el.get("style", ""))
                    fs = mfs.group(1) if mfs else None
                texts.append({"text": txt[:80], "id": el.get("id"),
                              "x": (el.get("x") or "").split()[0:1],
                              "y": (el.get("y") or "").split()[0:1], "font_size": fs})
    return {"viewBox": root.get("viewBox", ""), "texts": texts,
            "fill_colors": sorted(fills), "stroke_colors": sorted(strokes)}


def _antiparallel_coords(b1, b2, offset=10.0):
    """对同层或直连双向边 (u->v 与 v->u) 自动分离为 ±offset 平行双线与外侧无冲突标签位。"""
    c1x, c1y = b1[0] + b1[2] / 2.0, b1[1] + b1[3] / 2.0
    c2x, c2y = b2[0] + b2[2] / 2.0, b2[1] + b2[3] / 2.0
    dx, dy = c2x - c1x, c2y - c1y
    if abs(dx) >= abs(dy):
        off = min(offset, b1[3] * 0.24, b2[3] * 0.24)
        if dx >= 0:
            x1, y1 = b1[0] + b1[2], c1y - off
            x2, y2 = b2[0], c2y - off
            lpos, lanch = [(x1 + x2) / 2.0, (y1 + y2) / 2.0 - 6.0], "middle"
        else:
            x1, y1 = b1[0], c1y + off
            x2, y2 = b2[0] + b2[2], c2y + off
            lpos, lanch = [(x1 + x2) / 2.0, (y1 + y2) / 2.0 + 13.0], "middle"
    else:
        off = min(offset, b1[2] * 0.22, b2[2] * 0.22)
        if dy >= 0:
            x1, y1 = c1x - off, b1[1] + b1[3]
            x2, y2 = c2x - off, b2[1]
            lpos, lanch = [(x1 + x2) / 2.0 - 8.0, (y1 + y2) / 2.0 + 3.0], "end"
        else:
            x1, y1 = c1x + off, b1[1]
            x2, y2 = c2x + off, b2[1] + b2[3]
            lpos, lanch = [(x1 + x2) / 2.0 + 8.0, (y1 + y2) / 2.0 + 3.0], "start"
    return x1, y1, x2, y2, lpos, lanch


def _build_diagram_lr(spec, nodes, edges, compartments, lanes, node_dims, font_fam, fpt):
    """横向（左->右）机制图/流程图自动排版：lane 为列，order 为列内行，反馈/跨列边走顶部/底部圆角走廊。"""
    node_lane = {nd["id"]: int(nd.get("lane", 0)) for nd in nodes}
    has_detour = any(
        (e.get("route") in ("curve", "detour"))
        or (node_lane.get(e["from"], 0) > node_lane.get(e["to"], 0))
        or (abs(node_lane.get(e["to"], 0) - node_lane.get(e["from"], 0)) >= 2 and not e.get("route"))
        for e in edges
    )
    gap_x = float(spec.get("gap_x", 84))
    gap_y = float(spec.get("gap_y", 52))
    margin_x = 56.0
    title_h = 52.0 if spec.get("title") else 22.0
    corridor_top = 48.0 if has_detour else 10.0
    corridor_bot = 48.0 if has_detour else 10.0
    comp_pad_top = 30.0 if compartments else 0.0

    col_w = {ln: max(node_dims[m["id"]][0] for m in ms) for ln, ms in lanes.items()}
    col_h = {ln: sum(node_dims[m["id"]][1] for m in ms) + max(0, len(ms) - 1) * gap_y
             for ln, ms in lanes.items()}
    max_col_h = max(col_h.values(), default=180.0)
    total_cols_w = sum(col_w[ln] for ln in sorted(lanes.keys())) + max(0, len(lanes) - 1) * gap_x
    canvas_w = float(spec.get("width") or max(780.0, total_cols_w + 2 * margin_x + 40.0))

    used_styles = []
    for e in edges:
        st = e.get("style") or e.get("type") or "activate"
        key = (st, bool(e.get("dashed")))
        if key not in used_styles:
            used_styles.append(key)
    want_legend = spec.get("legend", True) and bool(used_styles)
    caption_txt = spec.get("caption") or (f"Source: {spec['source']}" if spec.get("source") else "")
    legend_h = 42.0 if want_legend else 10.0
    caption_h = 22.0 if caption_txt else 0.0

    body_y0 = title_h + corridor_top + comp_pad_top + 12.0
    canvas_h = float(spec.get("height") or (body_y0 + max_col_h + 26.0 + corridor_bot + legend_h + caption_h))

    pos = {}
    lane_x_bounds = {}
    cur_x = (canvas_w - total_cols_w) / 2.0
    for ln in sorted(lanes.keys()):
        ms = lanes[ln]
        cw = col_w[ln]
        ch = col_h[ln]
        cur_y = body_y0 + (max_col_h - ch) / 2.0
        for m in ms:
            w, h = node_dims[m["id"]]
            mx = float(m["x"]) if "x" in m else cur_x + (cw - w) / 2.0
            my = float(m["y"]) if "y" in m else cur_y
            pos[m["id"]] = (mx, my, w, h)
            cur_y += h + gap_y
        lane_x_bounds[ln] = (cur_x, cur_x + cw)
        cur_x += cw + gap_x

    ops = []
    if spec.get("title"):
        ops.append({"op": "add_text", "id": "diagram-title", "x": canvas_w / 2.0, "y": 32,
                    "text": spec["title"], "font_pt": 15, "bold": True,
                    "fill": "#1A2B3C", "anchor": "middle", "font_family": font_fam})

    # 垂直列区室框（等高对齐）
    comp_boxes = []
    for ci, c in enumerate(compartments):
        c_nodes = ([pos[nid] for nid in c["node_ids"] if nid in pos] if c.get("node_ids")
                   else [pos[m["id"]] for ln in (c.get("lanes") or []) for m in lanes.get(ln, []) if m["id"] in pos])
        if not c_nodes:
            continue
        x0 = min(b[0] for b in c_nodes) - 20.0
        x1 = max(b[0] + b[2] for b in c_nodes) + 20.0
        comp_boxes.append((ci, c, x0, x1))
    gy0 = body_y0 - 28.0
    gy1 = body_y0 + max_col_h + 18.0
    for ci, c, x0, x1 in comp_boxes:
        ctitle = c.get("title") or c.get("label") or c.get("name") or ""
        ops.append({
            "op": "add_compartment", "id": c.get("id", f"comp-{ci}"),
            "x": max(20.0, x0), "y": gy0, "w": min(canvas_w - 20.0, x1) - max(20.0, x0), "h": gy1 - gy0,
            "title": ctitle, "fill": c.get("fill", "#F5F8FC"),
            "stroke": c.get("stroke", "#8FA6C0"), "dashed": c.get("dashed", True),
            "style": c.get("style", ""), "font_family": font_fam,
        })

    ops.extend(_complex_ops(spec, pos, font_fam))

    for nd in nodes:
        x, y, w, h = pos[nd["id"]]
        nfill, nstroke = _node_colors(nd)
        op_b = {
            "op": "add_box", "id": nd["id"], "x": x, "y": y, "w": w, "h": h,
            "shape": nd.get("shape", "rounded"), "fill": nfill,
            "stroke": nstroke,
            "label": nd.get("label") or nd.get("name") or nd["id"],
            "sublabel": nd.get("sublabel") or nd.get("subtitle") or "", "font_pt": fpt, "font_family": font_fam,
        }
        if nd.get("badge"):
            op_b["badge"] = nd["badge"]
            for bk in ("badge_fill", "badge_stroke", "badge_text_fill"):
                if nd.get(bk):
                    op_b[bk] = nd[bk]
        ops.append(op_b)

    def _tb_clear(nid, side):
        if nid not in pos:
            return True
        _, by, _, bh = pos[nid]
        ln = node_lane.get(nid, 0)
        for m in lanes.get(ln, []):
            if m["id"] == nid or m["id"] not in pos:
                continue
            _, oy, _, oh = pos[m["id"]]
            if side == "top" and oy + oh <= by + 1:
                return False
            if side == "bottom" and oy >= by + bh - 1:
                return False
        return True

    side_load = {"top": 0, "bottom": 0}
    edge_routes = {}
    detours = []
    for ei, e in enumerate(edges):
        fl, tl = node_lane.get(e["from"], 0), node_lane.get(e["to"], 0)
        explicit = e.get("route")
        is_det = (explicit in ("curve", "detour")) or (not explicit and (fl > tl or abs(tl - fl) >= 2))
        if not is_det:
            edge_routes[ei] = (explicit or "straight", None)
        else:
            detours.append(ei)

    for ei in detours:
        e = edges[ei]
        pref = e.get("curve_side")
        if pref in ("top", "bottom"):
            chosen = pref
        else:
            bt = (0 if _tb_clear(e["from"], "top") else 1) + (0 if _tb_clear(e["to"], "top") else 2)
            bb = (0 if _tb_clear(e["from"], "bottom") else 1) + (0 if _tb_clear(e["to"], "bottom") else 2)
            chosen = "top" if (bt, side_load["top"]) <= (bb, side_load["bottom"]) else "bottom"
        side_load[chosen] += 1
        edge_routes[ei] = ("detour", chosen)

    # 常规边多入边按源框 y 顺序错开目标框左侧接入点
    incoming_lr = {}
    for ei, e in enumerate(edges):
        if edge_routes[ei][0] != "detour":
            incoming_lr.setdefault(e["to"], []).append(ei)
    lr_y_bias = {}
    for tid, eidxs in incoming_lr.items():
        if len(eidxs) > 1 and tid in pos:
            ordered = sorted(eidxs, key=lambda idx: (pos[edges[idx]["from"]][1] + pos[edges[idx]["from"]][3] / 2.0)
                             if edges[idx]["from"] in pos else 0.0)
            m = len(ordered)
            for k, idx in enumerate(ordered):
                lr_y_bias[idx] = -0.26 + (0.52 * k / max(1, m - 1))

    # 统计每个节点在 top/bottom 侧上的 detour 端点，避免同侧一进一出重叠竖线
    node_tb_ports = {}
    for ei in detours:
        e = edges[ei]
        side = edge_routes[ei][1] or "top"
        node_tb_ports.setdefault((e["from"], side), []).append((ei, "out", pos[e["to"]][0] if e["to"] in pos else 0.0))
        node_tb_ports.setdefault((e["to"], side), []).append((ei, "in", pos[e["from"]][0] if e["from"] in pos else 0.0))
    tb_x_shift = {}
    for (nid, side), plist in node_tb_ports.items():
        if len(plist) > 1:
            # 按另一端 x 坐标从左到右排，使走左边的端口偏左、走右边的端口偏右，避免交叉
            plist_s = sorted(plist, key=lambda t: t[2])
            m = len(plist_s)
            for k, (ei, role, _) in enumerate(plist_s):
                tb_x_shift[(ei, role)] = -18.0 + (36.0 * k / max(1, m - 1))

    non_detour_pairs_lr = {(edges[i]["from"], edges[i]["to"]) for i in range(len(edges))
                           if edge_routes[i][0] != "detour"}
    det_cnt = {"top": 0, "bottom": 0}
    for ei, e in enumerate(edges):
        st = e.get("style") or e.get("type") or "activate"
        route, side = edge_routes[ei]
        op_e = {
            "op": "add_arrow" if st != "line" else "add_line",
            "id": e.get("id", f"edge-{ei}"),
            "style": st, "dashed": bool(e.get("dashed", False)),
            "route": route, "label": e.get("label", ""),
            "font_pt": max(9.5, fpt - 1.5), "font_family": font_fam,
        }
        if route == "detour" and e["from"] in pos and e["to"] in pos:
            side = side or "top"
            k_slot = det_cnt[side]
            det_cnt[side] += 1
            b1, b2 = pos[e["from"]], pos[e["to"]]
            cx1 = b1[0] + b1[2] / 2.0 + tb_x_shift.get((ei, "out"), 0.0)
            cy1 = b1[1] + b1[3] / 2.0
            cx2 = b2[0] + b2[2] / 2.0 + tb_x_shift.get((ei, "in"), 0.0)
            cy2 = b2[1] + b2[3] / 2.0
            corridor_y = (max(title_h + 12.0, gy0 - 20.0 - 20.0 * k_slot) if side == "top"
                          else min(canvas_h - legend_h - caption_h - 14.0, gy1 + 22.0 + 20.0 * k_slot))
            going_left = cx2 < cx1
            if _tb_clear(e["from"], side):
                sy = b1[1] if side == "top" else (b1[1] + b1[3])
                wpts = [(cx1, sy), (cx1, corridor_y)]
            else:
                sx = b1[0] if going_left else (b1[0] + b1[2])
                fln = node_lane.get(e["from"], 0)
                gap_x_mid = (lane_x_bounds[fln][0] - gap_x * 0.42) if going_left else (lane_x_bounds[fln][1] + gap_x * 0.42)
                wpts = [(sx, cy1), (gap_x_mid, cy1), (gap_x_mid, corridor_y)]
            if _tb_clear(e["to"], side):
                ey = b2[1] if side == "top" else (b2[1] + b2[3])
                wpts.extend([(cx2, corridor_y), (cx2, ey)])
            else:
                ex = (b2[0] + b2[2]) if going_left else b2[0]
                tln = node_lane.get(e["to"], 0)
                gap_x_mid2 = (lane_x_bounds[tln][1] + gap_x * 0.42) if going_left else (lane_x_bounds[tln][0] - gap_x * 0.42)
                wpts.extend([(gap_x_mid2, corridor_y), (gap_x_mid2, cy2), (ex, cy2)])
            op_e["waypoints"] = wpts
            op_e["label_pos"] = [(wpts[1][0] + wpts[-2][0]) / 2.0, corridor_y + (-6.0 if side == "top" else 13.0)]
            op_e["label_anchor"] = "middle"
        elif e["from"] in pos and e["to"] in pos:
            b1, b2 = pos[e["from"]], pos[e["to"]]
            fl, tl = node_lane.get(e["from"], 0), node_lane.get(e["to"], 0)
            if (e["to"], e["from"]) in non_detour_pairs_lr:
                x1, y1, x2, y2, lpos, lanch = _antiparallel_coords(b1, b2)
                op_e["x1"], op_e["y1"], op_e["x2"], op_e["y2"] = x1, y1, x2, y2
                op_e["label_pos"], op_e["label_anchor"] = lpos, lanch
            elif fl == tl:
                # 同列上下对接
                op_e["from_id"], op_e["to_id"] = e["from"], e["to"]
            else:
                # 跨列：从源框右侧中点出发，精准接入目标框左侧（按 y 顺序错开）；斜向时自动采用垂直入框平滑 S 曲线防斜 T-bar
                x1, y1 = b1[0] + b1[2], b1[1] + b1[3] / 2.0
                x2, y2 = b2[0], b2[1] + b2[3] * (0.5 + lr_y_bias.get(ei, 0.0))
                op_e["x1"], op_e["y1"], op_e["x2"], op_e["y2"] = x1, y1, x2, y2
                if route == "straight" and abs(y2 - y1) > 16.0 and abs(x2 - x1) > 16.0:
                    op_e["route"] = "smooth"
                    op_e["smooth_axis"] = "horizontal"
        else:
            op_e["from_id"], op_e["to_id"] = e["from"], e["to"]
        if e.get("stroke"):
            op_e["stroke"] = e["stroke"]
        ops.append(op_e)

    if want_legend:
        ly = canvas_h - (40.0 if caption_txt else 22.0)
        label_map = {
            ("activate", False): "Activation / Direct", ("activate", True): "Indirect / Transport",
            ("inhibit", False): "Inhibition (T-bar)", ("tbar", False): "Inhibition (T-bar)",
            ("inhibit", True): "Indirect Inhibition", ("both", False): "Bidirectional",
            ("line", False): "Association",
        }
        items = [(st, dsh, label_map.get((st, dsh), f"{st}" + (" (dashed)" if dsh else "")))
                 for st, dsh in used_styles[:4]]
        total_lw = sum(44 + _est_text_w(txt, 10) + 24 for _, _, txt in items) - 24
        lx = max(32.0, (canvas_w - total_lw) / 2.0)
        for st, dsh, txt in items:
            ops.append({"op": "add_arrow" if st != "line" else "add_line",
                        "x1": lx, "y1": ly, "x2": lx + 34, "y2": ly,
                        "style": st, "dashed": dsh, "width": 1.6})
            ops.append({"op": "add_text", "x": lx + 42, "y": ly + 4, "text": txt,
                        "font_pt": 10, "fill": "#334455", "font_family": font_fam})
            lx += 44 + _est_text_w(txt, 10) + 24
    if caption_txt:
        ops.append({"op": "add_text", "id": "diagram-caption", "x": canvas_w / 2.0, "y": canvas_h - 12.0,
                    "text": str(caption_txt), "font_pt": 9.2, "fill": "#5A6B7C",
                    "anchor": "middle", "font_family": font_fam})

    provenance = {
        "generated_by": "sci-figure-studio svg_edit --diagram v3 (LR)",
        "case_id": spec.get("case_id"), "title": spec.get("title"),
        "direction": "LR", "source": spec.get("source"),
        "entities": [{"id": n["id"], "label": n.get("label") or n.get("name"),
                      "sublabel": n.get("sublabel"), "lane": n.get("lane", 0),
                      "source_ref": n.get("source_ref")} for n in nodes],
        "relations": [{"from": e["from"], "to": e["to"],
                       "type": e.get("style") or e.get("type") or "activate",
                       "dashed": bool(e.get("dashed", False)),
                       "label": e.get("label", ""), "source_ref": e.get("source_ref")}
                      for e in edges],
        "compartments": [c.get("title") or c.get("label") or c.get("name") for c in compartments],
    }
    return ops, int(round(canvas_w)), int(round(canvas_h)), provenance


def _build_diagram_ops(spec):
    """将紧凑的生物学机制图/流程图 JSON 自动排版为无重叠的 svg_ops 列表 + 画布尺寸 + 溯源对象。"""
    nodes = spec.get("nodes") or spec.get("modules") or []
    edges = spec.get("edges") or []
    compartments = spec.get("compartments") or []
    font_fam = spec.get("font_family", DEFAULT_FONT)
    fpt = float(spec.get("font_pt", 11.5))

    # 1. 按 lane 分组并计算每个节点所需宽高
    lanes = {}
    for idx, nd in enumerate(nodes):
        ln = int(nd.get("lane", 0))
        lanes.setdefault(ln, []).append(nd)
    for ln in lanes:
        lanes[ln].sort(key=lambda m: float(m.get("order", 0)))

    node_dims = {}
    for nd in nodes:
        lbl = str(nd.get("label") or nd.get("name") or nd["id"])
        sub = str(nd.get("sublabel") or nd.get("subtitle") or "")
        shape = nd.get("shape", "rounded")
        max_line_w = max([_est_text_w(x, fpt * 1.07) for x in lbl.split("\n")] +
                         ([_est_text_w(x, fpt * 0.82) for x in sub.split("\n")] if sub else [0]))
        w = float(nd.get("w") or min(228, max(124, max_line_w + 32)))
        pad_x = 14.0 if shape in ("pill", "ellipse") else 12.0
        max_tw = max(48.0, w - 2 * pad_x)
        n_main = len(_wrap_text(lbl, max_tw, fpt * (1.07 if sub else 1.0))) if lbl else 0
        n_sub = len(_wrap_text(sub, max_tw, max(8.5, fpt * 0.82))) if sub else 0
        h_base = 24.0 + n_main * (fpt * 1.32) + n_sub * (max(8.5, fpt * 0.82) * 1.32) + (6.0 if (n_main and n_sub) else 0.0)
        h = float(nd.get("h") or max(54.0, math.ceil(h_base)))
        node_dims[nd["id"]] = (w, h)

    raw_dir = str(spec.get("direction") or spec.get("layout") or spec.get("orientation") or "TB").strip().upper()
    if raw_dir in ("LR", "HORIZONTAL", "LEFT_TO_RIGHT", "LEFT-TO-RIGHT"):
        return _build_diagram_lr(spec, nodes, edges, compartments, lanes, node_dims, font_fam, fpt)

    node_lane_pre = {nd["id"]: int(nd.get("lane", 0)) for nd in nodes}
    has_detour_edges = any(
        (e.get("route") in ("curve", "detour"))
        or (node_lane_pre.get(e["from"], 0) > node_lane_pre.get(e["to"], 0))
        or (abs(node_lane_pre.get(e["to"], 0) - node_lane_pre.get(e["from"], 0)) >= 2 and not e.get("route"))
        for e in edges
    )
    gap_x = float(spec.get("gap_x", 76))
    gap_y = float(spec.get("gap_y", 74))
    margin_x = 128.0 if has_detour_edges else 58.0
    title_h = 54.0 if spec.get("title") else 24.0

    # 检查是否有区室需要额外顶部标题留白
    comp_lane_first = {}
    for c in compartments:
        c_lanes = c.get("lanes") or []
        if c_lanes:
            comp_lane_first[min(c_lanes)] = c

    # 先算总宽（含外侧反馈走廊留白）
    row_widths = {}
    for ln, ms in lanes.items():
        rw = sum(node_dims[m["id"]][0] for m in ms) + max(0, len(ms) - 1) * gap_x
        row_widths[ln] = rw
    canvas_w = float(spec.get("width") or max(760, max(row_widths.values(), default=640) + 2 * margin_x + 40))

    # 逐泳道分配坐标
    pos = {}
    lane_y_bounds = {}
    cur_y = title_h + 18.0
    for ln in sorted(lanes.keys()):
        if ln in comp_lane_first:
            cur_y += 28.0  # 给区室标题留足空间
        ms = lanes[ln]
        row_h = max(node_dims[m["id"]][1] for m in ms)
        rw = row_widths[ln]
        cur_x = (canvas_w - rw) / 2.0
        for m in ms:
            w, h = node_dims[m["id"]]
            mx = float(m["x"]) if "x" in m else cur_x
            my = float(m["y"]) if "y" in m else cur_y + (row_h - h) / 2.0
            pos[m["id"]] = (mx, my, w, h)
            cur_x += w + gap_x
        lane_y_bounds[ln] = (cur_y, cur_y + row_h)
        cur_y += row_h + gap_y

    # 底部图例区 + 可选图注/来源行
    used_styles = []
    for e in edges:
        st = e.get("style") or e.get("type") or "activate"
        key = (st, bool(e.get("dashed")))
        if key not in used_styles:
            used_styles.append(key)
    want_legend = spec.get("legend", True) and bool(used_styles)
    caption_txt = spec.get("caption") or (f"Source: {spec['source']}" if spec.get("source") else "")
    legend_h = 42.0 if want_legend else 10.0
    caption_h = 22.0 if caption_txt else 0.0
    canvas_h = float(spec.get("height") or (cur_y - gap_y + 34.0 + legend_h + caption_h))

    ops = []
    # 标题
    if spec.get("title"):
        ops.append({"op": "add_text", "id": "diagram-title", "x": canvas_w / 2.0, "y": 34,
                    "text": spec["title"], "font_pt": 15, "bold": True,
                    "fill": "#1A2B3C", "anchor": "middle", "font_family": font_fam})

    # 区室框（自动统一所有区室左右宽度，形成整齐分层膜结构）
    comp_boxes = []
    for ci, c in enumerate(compartments):
        c_nodes = []
        if c.get("node_ids"):
            c_nodes = [pos[nid] for nid in c["node_ids"] if nid in pos]
        elif c.get("lanes"):
            for ln in c["lanes"]:
                for m in lanes.get(ln, []):
                    c_nodes.append(pos[m["id"]])
        if not c_nodes:
            continue
        x0 = min(b[0] for b in c_nodes) - 26
        y0 = min(b[1] for b in c_nodes) - 28
        x1 = max(b[0] + b[2] for b in c_nodes) + 26
        y1 = max(b[1] + b[3] for b in c_nodes) + 18
        comp_boxes.append((ci, c, x0, y0, x1, y1))
    if comp_boxes:
        gx0 = max(24.0, min(b[2] for b in comp_boxes))
        gx1 = min(canvas_w - 24.0, max(b[4] for b in comp_boxes))
        for ci, c, _, y0, _, y1 in comp_boxes:
            ctitle = c.get("title") or c.get("label") or c.get("name") or ""
            ops.append({
                "op": "add_compartment",
                "id": c.get("id", f"comp-{ci}"),
                "x": gx0, "y": max(title_h, y0),
                "w": gx1 - gx0, "h": y1 - max(title_h, y0),
                "title": ctitle,
                "fill": c.get("fill", "#F5F8FC"),
                "stroke": c.get("stroke", "#8FA6C0"),
                "dashed": c.get("dashed", True),
                "style": c.get("style", ""),
                "font_family": font_fam,
            })

    ops.extend(_complex_ops(spec, pos, font_fam))

    # 节点框
    for nd in nodes:
        x, y, w, h = pos[nd["id"]]
        nfill, nstroke = _node_colors(nd)
        op_b = {
            "op": "add_box", "id": nd["id"], "x": x, "y": y, "w": w, "h": h,
            "shape": nd.get("shape", "rounded"),
            "fill": nfill,
            "stroke": nstroke,
            "label": nd.get("label") or nd.get("name") or nd["id"],
            "sublabel": nd.get("sublabel") or nd.get("subtitle") or "",
            "font_pt": fpt, "font_family": font_fam,
        }
        if nd.get("badge"):
            op_b["badge"] = nd["badge"]
            for bk in ("badge_fill", "badge_stroke", "badge_text_fill"):
                if nd.get(bk):
                    op_b[bk] = nd[bk]
        ops.append(op_b)

    # 连线（1) 常规边按目标框入边方向 top/bottom/left/right 分组错开，同泳道水平边不被顶部入边带歪；
    #      2) 反馈回路或跨>=2泳道的长边自动走外侧圆角走廊 detour，中间列节点先经行间空隙出廊，绝不穿框）
    node_lane = {nd["id"]: int(nd.get("lane", 0)) for nd in nodes}
    all_x0 = min((b[0] for b in pos.values()), default=margin_x)
    all_x1 = max((b[0] + b[2] for b in pos.values()), default=canvas_w - margin_x)
    comp_x0 = max(24.0, all_x0 - 26.0) if comp_boxes else all_x0
    comp_x1 = min(canvas_w - 24.0, all_x1 + 26.0) if comp_boxes else all_x1

    def _side_clear(nid, side):
        """检查节点 nid 同泳道内 side('left'/'right') 外侧是否无兄弟节点遮挡。"""
        if nid not in pos:
            return True
        bx, _, bw, _ = pos[nid]
        ln = node_lane.get(nid, 0)
        for m in lanes.get(ln, []):
            if m["id"] == nid or m["id"] not in pos:
                continue
            ox, _, ow, _ = pos[m["id"]]
            if side == "left" and ox + ow <= bx + 1:
                return False
            if side == "right" and ox >= bx + bw - 1:
                return False
        return True

    def _entry_side(fid, tid):
        if fid not in pos or tid not in pos:
            return "top"
        x1, y1, w1, h1 = pos[fid]
        x2, y2, w2, h2 = pos[tid]
        cx1, cy1 = x1 + w1 / 2.0, y1 + h1 / 2.0
        cx2, cy2 = x2 + w2 / 2.0, y2 + h2 / 2.0
        if abs(cy2 - cy1) < min(h1, h2) * 0.5:
            return "left" if cx2 > cx1 else "right"
        return "top" if cy2 >= cy1 else "bottom"

    # 为每个 detour 边平衡分配左右外侧走廊（先分配单侧受限边，再将对称/中间列边均衡分摊到负载更轻的一侧）
    side_load = {"left": 0, "right": 0}
    edge_routes = {}
    detour_indices = []
    for ei, e in enumerate(edges):
        fl, tl = node_lane.get(e["from"], 0), node_lane.get(e["to"], 0)
        explicit = e.get("route")
        is_detour = (explicit in ("curve", "detour")) or (not explicit and (fl > tl or abs(tl - fl) >= 2))
        if not is_detour:
            edge_routes[ei] = (explicit or "straight", None)
        else:
            detour_indices.append(ei)

    def _blocked_pair(e):
        bl = (0 if _side_clear(e["from"], "left") else 1) + (0 if _side_clear(e["to"], "left") else 2)
        br = (0 if _side_clear(e["from"], "right") else 1) + (0 if _side_clear(e["to"], "right") else 2)
        return bl, br

    # 优先处理有明确偏好的边（|bl-br| 更大或显式指定 curve_side）
    detour_indices.sort(
        key=lambda idx: (0 if edges[idx].get("curve_side") in ("left", "right") else 1,
                         -abs(_blocked_pair(edges[idx])[0] - _blocked_pair(edges[idx])[1]))
    )
    for ei in detour_indices:
        e = edges[ei]
        pref = e.get("curve_side")
        if pref in ("left", "right"):
            chosen = pref
        else:
            bl, br = _blocked_pair(e)
            chosen = "left" if (bl, side_load["left"]) <= (br, side_load["right"]) else "right"
        side_load[chosen] += 1
        edge_routes[ei] = ("detour", chosen)

    # 常规边按 (tid, entry_side) 分组错开接入点
    incoming = {}
    for ei, e in enumerate(edges):
        if edge_routes[ei][0] != "detour":
            eside = _entry_side(e["from"], e["to"])
            incoming.setdefault((e["to"], eside), []).append(ei)
    edge_bias = {}
    for (tid, eside), eidxs in incoming.items():
        if len(eidxs) > 1 and tid in pos:
            tx, ty, tw, th = pos[tid]
            tcx, tcy = tx + tw / 2.0, ty + th / 2.0
            horiz = eside in ("left", "right")
            ordered = sorted(
                eidxs,
                key=lambda idx: ((pos[edges[idx]["from"]][1] + pos[edges[idx]["from"]][3] / 2.0 - tcy)
                                 if horiz else (pos[edges[idx]["from"]][0] + pos[edges[idx]["from"]][2] / 2.0 - tcx))
                if edges[idx]["from"] in pos else 0.0,
            )
            m = len(ordered)
            if m == 2 and not horiz:
                d0 = (pos[edges[ordered[0]]["from"]][0] + pos[edges[ordered[0]]["from"]][2] / 2.0 - tcx) if edges[ordered[0]]["from"] in pos else -1.0
                d1 = (pos[edges[ordered[1]]["from"]][0] + pos[edges[ordered[1]]["from"]][2] / 2.0 - tcx) if edges[ordered[1]]["from"] in pos else 1.0
                if abs(d0) < tw * 0.2 and abs(d1) >= tw * 0.2:
                    edge_bias[ordered[0]] = 0.0
                    edge_bias[ordered[1]] = 0.26 if d1 > 0 else -0.26
                elif abs(d1) < tw * 0.2 and abs(d0) >= tw * 0.2:
                    edge_bias[ordered[1]] = 0.0
                    edge_bias[ordered[0]] = 0.26 if d0 > 0 else -0.26
                else:
                    edge_bias[ordered[0]], edge_bias[ordered[1]] = -0.24, 0.24
            else:
                for k, idx in enumerate(ordered):
                    edge_bias[idx] = -0.24 + (0.48 * k / max(1, m - 1))

    non_detour_pairs_tb = {(edges[i]["from"], edges[i]["to"]) for i in range(len(edges))
                           if edge_routes[i][0] != "detour"}
    detour_count = {"left": 0, "right": 0}
    for ei, e in enumerate(edges):
        st = e.get("style") or e.get("type") or "activate"
        route, side = edge_routes[ei]
        op_e = {
            "op": "add_arrow" if st != "line" else "add_line",
            "id": e.get("id", f"edge-{ei}"),
            "from_id": e["from"], "to_id": e["to"],
            "dst_bias": edge_bias.get(ei, 0.0),
            "style": st, "dashed": bool(e.get("dashed", False)),
            "route": route,
            "label": e.get("label", ""),
            "font_pt": max(9.5, fpt - 1.5), "font_family": font_fam,
        }
        if route != "detour" and (e["to"], e["from"]) in non_detour_pairs_tb and e["from"] in pos and e["to"] in pos:
            x1, y1, x2, y2, lpos, lanch = _antiparallel_coords(pos[e["from"]], pos[e["to"]])
            op_e.pop("from_id", None)
            op_e.pop("to_id", None)
            op_e["x1"], op_e["y1"], op_e["x2"], op_e["y2"] = x1, y1, x2, y2
            op_e["label_pos"], op_e["label_anchor"] = lpos, lanch
        elif route == "straight" and e["from"] in pos and e["to"] in pos:
            fl, tl = node_lane.get(e["from"], 0), node_lane.get(e["to"], 0)
            if fl != tl:
                b1, b2 = pos[e["from"]], pos[e["to"]]
                cx1, cx2 = b1[0] + b1[2] / 2.0, b2[0] + b2[2] / 2.0
                if abs(cx2 - cx1) > 18.0:
                    op_e["route"] = "smooth"
                    op_e["smooth_axis"] = "vertical"
        if route == "detour" and e["from"] in pos and e["to"] in pos:
            side = side or "left"
            k_slot = detour_count[side]
            detour_count[side] += 1
            b1, b2 = pos[e["from"]], pos[e["to"]]
            cx1, cy1 = b1[0] + b1[2] / 2.0, b1[1] + b1[3] / 2.0
            cx2, cy2 = b2[0] + b2[2] / 2.0, b2[1] + b2[3] / 2.0
            corridor_x = (max(26.0, comp_x0 - 30.0 - 22.0 * k_slot) if side == "left"
                          else min(canvas_w - 26.0, comp_x1 + 30.0 + 22.0 * k_slot))
            going_up = cy2 < cy1
            # 起点：外侧无兄弟时水平直出，有兄弟时从顶/底退入行间空隙再横移至外侧走廊
            if _side_clear(e["from"], side):
                sx = b1[0] if side == "left" else (b1[0] + b1[2])
                sy = cy1
                wpts = [(sx, sy), (corridor_x, sy)]
            else:
                sy = b1[1] if going_up else (b1[1] + b1[3])
                gy = (b1[1] - 18.0 - 8.0 * k_slot) if going_up else (b1[1] + b1[3] + 18.0 + 8.0 * k_slot)
                wpts = [(cx1, sy), (cx1, gy), (corridor_x, gy)]
            # 终点：外侧无兄弟时水平直入，有兄弟时经行间空隙折入顶/底
            if _side_clear(e["to"], side):
                tx = b2[0] if side == "left" else (b2[0] + b2[2])
                ty = cy2 + (10.0 * k_slot if going_up else -10.0 * k_slot)
                wpts += [(corridor_x, ty), (tx, ty)]
            else:
                ty = (b2[1] + b2[3]) if going_up else b2[1]
                gy2 = (b2[1] + b2[3] + 18.0 + 8.0 * k_slot) if going_up else (b2[1] - 18.0 - 8.0 * k_slot)
                wpts += [(corridor_x, gy2), (cx2, gy2), (cx2, ty)]
            op_e["waypoints"] = wpts
            # 标签放在外侧走廊垂直段中点，并钳制水平位置防越界
            vy_mid = (wpts[1][1] + wpts[-2][1]) / 2.0 + (k_slot * 26.0 - 10.0)
            lbl_fpt = max(9.5, fpt - 1.5)
            half_lw = (_est_text_w(e.get("label", ""), lbl_fpt) + 8.0) / 2.0
            lx_clamped = min(canvas_w - 14.0 - half_lw, max(14.0 + half_lw, corridor_x))
            op_e["label_pos"] = [lx_clamped, vy_mid]
            op_e["label_anchor"] = "middle"
        if e.get("stroke"):
            op_e["stroke"] = e["stroke"]
        ops.append(op_e)

    # 底部语义图例（居中排布）与来源/图注行
    if want_legend:
        ly = canvas_h - (40.0 if caption_txt else 22.0)
        label_map = {
            ("activate", False): "Activation / Direct",
            ("activate", True): "Indirect / Transport",
            ("inhibit", False): "Inhibition (T-bar)",
            ("tbar", False): "Inhibition (T-bar)",
            ("inhibit", True): "Indirect Inhibition",
            ("both", False): "Bidirectional",
            ("line", False): "Association",
        }
        items = [(st, dsh, label_map.get((st, dsh), f"{st}" + (" (dashed)" if dsh else "")))
                 for st, dsh in used_styles[:4]]
        total_lw = sum(44 + _est_text_w(txt, 10) + 24 for _, _, txt in items) - 24
        lx = max(32.0, (canvas_w - total_lw) / 2.0)
        for st, dsh, txt in items:
            ops.append({"op": "add_arrow" if st != "line" else "add_line",
                        "x1": lx, "y1": ly, "x2": lx + 34, "y2": ly,
                        "style": st, "dashed": dsh, "width": 1.6})
            ops.append({"op": "add_text", "x": lx + 42, "y": ly + 4, "text": txt,
                        "font_pt": 10, "fill": "#334455", "font_family": font_fam})
            lx += 44 + _est_text_w(txt, 10) + 24
    if caption_txt:
        ops.append({"op": "add_text", "id": "diagram-caption", "x": canvas_w / 2.0, "y": canvas_h - 12.0,
                    "text": str(caption_txt), "font_pt": 9.2, "fill": "#5A6B7C",
                    "anchor": "middle", "font_family": font_fam})

    provenance = {
        "generated_by": "sci-figure-studio svg_edit --diagram v2",
        "case_id": spec.get("case_id"),
        "title": spec.get("title"),
        "source": spec.get("source"),
        "entities": [{"id": n["id"], "label": n.get("label") or n.get("name"),
                      "sublabel": n.get("sublabel"), "lane": n.get("lane", 0),
                      "source_ref": n.get("source_ref")} for n in nodes],
        "relations": [{"from": e["from"], "to": e["to"],
                       "type": e.get("style") or e.get("type") or "activate",
                       "dashed": bool(e.get("dashed", False)),
                       "label": e.get("label", ""), "source_ref": e.get("source_ref")}
                      for e in edges],
        "compartments": [c.get("title") or c.get("label") or c.get("name") for c in compartments],
    }
    return ops, int(round(canvas_w)), int(round(canvas_h)), provenance


def _write_blank_svg(out_svg, w, h, meta_str=None):
    Path(out_svg).parent.mkdir(parents=True, exist_ok=True)
    meta = f'<metadata id="sci-provenance">{meta_str}</metadata>' if meta_str else ""
    Path(out_svg).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<rect id="canvas-bg" x="0" y="0" width="{w}" height="{h}" fill="#FFFFFF" stroke="none"/>'
        f'<rect id="canvas-border" x="1" y="1" width="{w - 2}" height="{h - 2}" fill="none" '
        f'stroke="#E0E6ED" stroke-width="1"/>{meta}</svg>',
        encoding="utf-8",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--ops")
    ap.add_argument("--diagram", help="机制图/流程图紧凑 JSON 自动排版模式（自动生成区室/节点/T-bar/图例/溯源）")
    ap.add_argument("--out-svg")
    ap.add_argument("--out-pdf")
    ap.add_argument("--preview")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--report")
    ap.add_argument("--inspect", action="store_true",
                    help="只读检查：列出文字清单(坐标/字号)、颜色清单、页数，不修改任何文件")
    ap.add_argument("--extract-pdf", help="提取原论文 PDF 逐页文本、Figure 图注与匹配段落（用于机制图溯源）")
    ap.add_argument("--query", help="配合 --extract-pdf 搜索关键词正则（如 'Figure 3|Fig\\. 3'）")
    ap.add_argument("--out-txt", help="配合 --extract-pdf 将全文导出到文本文件")
    ap.add_argument("--render-hits", help="配合 --extract-pdf 将查询命中页渲染为 150 DPI PNG 存入该目录")
    ap.add_argument("--verify-pdf", help="配合 --diagram 对照原论文 PDF 逐字核验实体名拼写（实体接地审计）")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--find-text", help="inspect 时逐页搜索该字符串，返回命中页号（定位论文中目标图）")
    ap.add_argument("--blank", help="从空白画布搭建机制图/流程图，如 --blank 800x500（忽略 --input）")
    args = ap.parse_args()

    # 模式 5: 原论文 PDF 文本与图注提取（含命中页空间矢量标签与可选页图渲染）
    if args.extract_pdf:
        res = extract_pdf_text(args.extract_pdf, query=args.query,
                               out_txt=args.out_txt, render_hits=args.render_hits)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if args.report:
            dump_json(res, args.report)
        return

    # 模式 4: 机制图自动排版
    if args.diagram:
        if not args.out_svg:
            ap.error("--diagram 需配合 --out-svg")
        spec = json.loads(Path(args.diagram).read_text(encoding="utf-8"))
        ops, w, h, prov = _build_diagram_ops(spec)
        out_svg = Path(args.out_svg)
        prov_path = out_svg.with_suffix(".provenance.json")
        _write_blank_svg(out_svg, w, h,
                         meta_str=f"case_id={spec.get('case_id')}; spec={Path(args.diagram).name}; provenance={prov_path.name}")
        _, log_svg = apply_ops(str(out_svg), ops)
        log_all = [{"applied_to": "svg", **e} for e in log_svg]
        pdf_res = None
        if args.out_pdf:
            pdf_res = svg_to_pdf_any(out_svg, args.out_pdf)
            log_all.append({"applied_to": "pdf", "op": "svg_to_pdf",
                            "status": "applied" if pdf_res.get("ok") else "failed",
                            "detail": pdf_res.get("tool") or pdf_res.get("error")})
        geo = {}
        try:
            from check_layout import check_svg
            geo = check_svg(str(out_svg))
        except Exception as e:
            geo = {"ok": None, "error": f"{type(e).__name__}: {e}"}
        editable = verify_svg_editable(out_svg)
        preview = rasterize_any(out_svg, args.preview, dpi=args.dpi) if args.preview else None
        verify_pdf = args.verify_pdf or spec.get("source_pdf")
        entity_audit = verify_entities_against_pdf(prov.get("entities", []), verify_pdf) if verify_pdf else None
        prov["canvas"] = {"w": w, "h": h}
        prov["self_check"] = {"editable_svg": editable, "svg_geometry": geo, "pdf": pdf_res}
        if entity_audit is not None:
            prov["self_check"]["entity_grounding_audit"] = entity_audit
        dump_json(prov, prov_path)
        rep = {"mode": "diagram", "out_svg": str(out_svg), "out_pdf": args.out_pdf,
               "provenance": str(prov_path), "canvas": [w, h], "n_ops": len(ops),
               "editable_svg": editable, "svg_geometry": geo, "preview": preview,
               "entity_grounding_audit": entity_audit,
               "change_log": log_all,
               "ok": bool(geo.get("ok")) and bool(editable.get("ok"))
               and all(e.get("status") != "failed" for e in log_all)}
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        if args.report:
            dump_json(rep, args.report)
        return

    # 模式 3: 空白画布 + ops
    if args.blank:
        if not args.out_svg:
            ap.error("--blank 需配合 --out-svg")
        w, h = [int(v) for v in args.blank.lower().split("x")]
        out_svg = Path(args.out_svg)
        _write_blank_svg(out_svg, w, h)
        ops = json.loads(Path(args.ops).read_text(encoding="utf-8")) if args.ops else []
        if isinstance(ops, dict):
            ops = ops.get("ops", [])
        _, log_svg = apply_ops(str(out_svg), ops)
        log_all = [{"applied_to": "svg", **e} for e in log_svg]
        if args.out_pdf:
            pdf_res = svg_to_pdf_any(out_svg, args.out_pdf)
            log_all.append({"applied_to": "pdf", "op": "svg_to_pdf",
                            "status": "applied" if pdf_res.get("ok") else "failed",
                            "detail": pdf_res.get("tool") or pdf_res.get("error")})
        geo = {}
        try:
            from check_layout import check_svg
            geo = check_svg(str(out_svg))
        except Exception as e:
            geo = {"ok": None, "error": f"{type(e).__name__}: {e}"}
        editable = verify_svg_editable(out_svg)
        preview = rasterize_any(out_svg, args.preview, dpi=args.dpi) if args.preview else None
        rep = {"input": "blank", "out_svg": str(out_svg), "out_pdf": args.out_pdf,
               "n_ops": len(ops), "change_log": log_all, "editable_svg": editable,
               "svg_geometry": geo, "preview": preview,
               "ok": bool(geo.get("ok")) and all(e.get("status") != "failed" for e in log_all)}
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        if args.report:
            dump_json(rep, args.report)
        return

    if not args.input and not args.inspect:
        ap.error("--input（或 --diagram / --blank / --inspect）必需")

    # 模式 2: 只读侦查
    if args.inspect:
        src = Path(args.input)
        info = inspect_pdf(src, args.page, find_text=args.find_text) if src.suffix.lower() == ".pdf" else inspect_svg(src)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if args.report:
            dump_json(info, args.report)
        return

    # 模式 1: source-preserving 编辑既有 PDF/SVG
    if not args.ops or not args.out_svg:
        ap.error("--ops 与 --out-svg 为编辑模式必需（inspect 模式可省）")
    ops = json.loads(Path(args.ops).read_text(encoding="utf-8"))
    if isinstance(ops, dict):
        ops = ops.get("ops", [])
    src = Path(args.input)
    out_svg = Path(args.out_svg)
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    log_all, preview_src = [], None
    if src.suffix.lower() == ".pdf":
        fitz = _import_fitz()
        doc = fitz.open(str(src))
        n_pages = doc.page_count
        if args.page >= n_pages:
            print(json.dumps({"error": f"page {args.page} 超出总页数 {n_pages}",
                              "n_pages": n_pages, "ok": False}, ensure_ascii=False))
            doc.close()
            return
        svg_str = doc[args.page].get_svg_image(text_as_path=False)
        out_svg.write_text(svg_str, encoding="utf-8")
        doc.close()
        before_texts = _svg_text_snapshot(out_svg)
        _, log_svg = apply_ops(str(out_svg), ops)
        log_all += [{"applied_to": "svg", **e} for e in log_svg]
        has_svg_only = False
        if args.out_pdf:
            Path(args.out_pdf).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(src), args.out_pdf)
            log_pdf = edit_pdf_ops(args.out_pdf, ops, page=args.page)
            has_svg_only = any(e.get("status") == "svg_only" for e in log_pdf)
            if has_svg_only:
                # 含 recolor/move/delete 等 svg_only 操作时，从已编辑 SVG 重导单页 PDF 并同步（支持单页与多页 PDF）
                if n_pages == 1:
                    pdf_res = svg_to_pdf_any(out_svg, args.out_pdf)
                    if pdf_res.get("ok"):
                        log_all.append({"applied_to": "pdf", "op": "svg_to_pdf_sync",
                                        "status": "applied", "detail": pdf_res.get("tool")})
                    else:
                        log_all += log_pdf
                else:
                    tmp_pg_pdf = str(args.out_pdf) + ".page_sync.pdf"
                    pdf_res = svg_to_pdf_any(out_svg, tmp_pg_pdf)
                    if pdf_res.get("ok") and Path(tmp_pg_pdf).exists():
                        try:
                            d_main = fitz.open(str(args.out_pdf))
                            d_one = fitz.open(tmp_pg_pdf)
                            d_main.delete_page(args.page)
                            d_main.insert_pdf(d_one, from_page=0, to_page=0, start_at=args.page)
                            d_one.close()
                            tmp_merged = str(args.out_pdf) + ".merged.pdf"
                            d_main.save(tmp_merged)
                            d_main.close()
                            os.replace(tmp_merged, str(args.out_pdf))
                            log_all.append({"applied_to": "pdf", "op": "svg_to_pdf_page_sync",
                                            "status": "applied", "detail": f"{pdf_res.get('tool')}@page{args.page}"})
                        except Exception as ex:
                            log_all += log_pdf
                            log_all.append({"applied_to": "pdf", "op": "svg_to_pdf_page_sync",
                                            "status": "failed", "detail": f"{type(ex).__name__}: {ex}"})
                        finally:
                            if Path(tmp_pg_pdf).exists():
                                Path(tmp_pg_pdf).unlink()
                    else:
                        log_all += log_pdf
            else:
                log_all += log_pdf
            preview_src = None if has_svg_only else args.out_pdf
    else:
        shutil.copy(str(src), out_svg)
        before_texts = _svg_text_snapshot(out_svg)
        _, log_svg = apply_ops(str(out_svg), ops)
        log_all += [{"applied_to": "svg", **e} for e in log_svg]
        if args.out_pdf:
            pdf_res = svg_to_pdf_any(out_svg, args.out_pdf)
            log_all.append({"applied_to": "pdf", "op": "svg_to_pdf",
                            "status": "applied" if pdf_res.get("ok") else "failed",
                            "detail": pdf_res.get("tool") or pdf_res.get("error")})
    # 自动注入可核验 provenance 元数据并写出同名前缀 .provenance.json
    prov_path = out_svg.with_suffix(".provenance.json")
    try:
        svg_txt = out_svg.read_text(encoding="utf-8")
        if 'id="sci-provenance"' not in svg_txt and "</svg>" in svg_txt:
            meta = f'<metadata id="sci-provenance">source={src.name}; page={args.page}; provenance={prov_path.name}</metadata>'
            out_svg.write_text(svg_txt.replace("</svg>", meta + "</svg>", 1), encoding="utf-8")
    except Exception:
        pass
    preview = None
    if args.preview:
        if preview_src and Path(preview_src).exists():
            preview = pdf_to_png(preview_src, args.preview, dpi=args.dpi, page=args.page)
        else:
            preview = rasterize_any(out_svg, args.preview, dpi=args.dpi)
    geo = {}
    try:
        from check_layout import check_svg
        geo = check_svg(str(out_svg))
    except Exception as e:
        geo = {"ok": None, "error": f"{type(e).__name__}: {e}"}
    editable = verify_svg_editable(out_svg)
    edit_diff = _compute_edit_diff(before_texts, _svg_text_snapshot(out_svg))
    prov_obj = {
        "generated_by": "sci-figure-studio svg_edit (source-preserving)",
        "source_file": str(src),
        "source_sha256": sha256_of(src) if src.exists() else None,
        "page": args.page,
        "ops_file": str(args.ops),
        "out_svg": str(out_svg),
        "out_pdf": args.out_pdf,
        "change_log": log_all,
        "edit_diff_audit": edit_diff,
        "self_check": {"editable_svg": editable, "svg_geometry": geo, "preview": preview, "edit_diff_audit": edit_diff},
    }
    dump_json(prov_obj, prov_path)
    report = {"input": str(src), "out_svg": str(out_svg),
              "out_pdf": args.out_pdf, "provenance": str(prov_path),
              "n_ops": len(ops), "page": args.page,
              "editable_svg": editable, "edit_diff_audit": edit_diff,
              "change_log": log_all,
              "preview": preview, "svg_geometry": geo,
              "ok": bool(geo.get("ok")) and all(e.get("status") != "failed" for e in log_all)}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.report:
        dump_json(report, args.report)


if __name__ == "__main__":
    main()
