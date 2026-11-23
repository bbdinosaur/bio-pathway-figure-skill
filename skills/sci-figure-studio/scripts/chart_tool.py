#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chart_tool.py — 科研图表生成主入口。
用法: python3 chart_tool.py spec.json --outdir /app/output [--base figure1] [--png-dpi 300]
输出: {base}.svg(可编辑) {base}.pdf {base}.png {base}.provenance.json（可选 .pptx），并打印真实自检摘要。
spec 结构见 references/chart_recipes.md。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kit_common import (  # noqa: E402
    dump_json, setup_matplotlib, png_edge_check, verify_svg_editable, sha256_of,
)
from chart_spec import resolve_panel, resolve_style  # noqa: E402


def _norm_mathtext(s):
    """将常见 LaTeX/MathText 写法归一化为 SVG <text> 实际渲染文本，消除伪漏标误报。"""
    import re
    t = str(s)
    repl = [
        (r"\\mu\b", "μ"), (r"\\alpha\b", "α"), (r"\\beta\b", "β"), (r"\\gamma\b", "γ"),
        (r"\\delta\b", "δ"), (r"\\Delta\b", "Δ"), (r"\\sigma\b", "σ"), (r"\\kappa\b", "κ"),
        (r"\\pm\b", "±"), (r"\\times\b", "×"), (r"\\leq\b", "≤"), (r"\\geq\b", "≥"),
        (r"\\circ\b", "°"), (r"\\degree\b", "°"),
    ]
    for pat, sub in repl:
        t = re.sub(pat, sub, t)
    t = re.sub(r"[\$\{\}\^_\\]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _audit_svg_labels(svg_path, prov_panels, spec_panels):
    """反向校验：确认轴标签、图例系列名、分类分组名均真实存在于可编辑 SVG <text> 节点中。"""
    import re
    import unicodedata
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(svg_path)).getroot()
        svg_texts = ["".join(el.itertext()).strip()
                     for el in root.iter() if el.tag.split("}")[-1] == "text"]
        joined = "\n".join(svg_texts)
        joined_norm = re.sub(r"\s+", " ", joined)
        joined_compact = unicodedata.normalize("NFKC", re.sub(r"\s+", "", joined))
        # Matplotlib 对 MathText 按字体分组输出 <tspan>，字符顺序可能重排但同节点字符多重集一致
        node_sorted = {tuple(sorted(unicodedata.normalize("NFKC", re.sub(r"\s+", "", t))))
                       for t in svg_texts if t}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "missing_labels": []}

    missing = []
    for p, sp in zip(prov_panels, spec_panels):
        expected = []
        for key in ("xlabel", "ylabel", "ylabel2", "panel_title"):
            v = sp.get(key)
            if v:
                expected.append((key, str(v).strip()))
        for s in p.get("legend_entries", []):
            if s:
                expected.append(("legend", str(s).strip()))
        if not p.get("numeric_x") and p.get("kind") != "heatmap":
            for g in p.get("groups", []):
                if g:
                    expected.append(("group", str(g).strip()))
        for kind, lbl in expected:
            lbl_norm = re.sub(r"\s+", " ", lbl)
            lbl_math = _norm_mathtext(lbl)
            lbl_math_c = unicodedata.normalize("NFKC", re.sub(r"\s+", "", lbl_math))
            found = (
                (lbl in joined)
                or (lbl_norm in joined_norm)
                or (lbl_math and lbl_math in joined_norm)
                or (lbl_math_c and lbl_math_c in joined_compact)
                or ("$" in lbl and lbl_math_c and tuple(sorted(lbl_math_c)) in node_sorted)
            )
            if lbl and not found:
                missing.append({"panel": p["panel"], "kind": kind, "label": lbl})
    return {"ok": len(missing) == 0, "checked_texts": len(svg_texts), "missing_labels": missing}


def _audit_annotations(prov_panels, spec_panels, caption=""):
    """标注完整性自检：轴标签单位、误差线含义声明、缺失值汇总（提醒 Agent 在 P1 补全）。"""
    import re
    unit_pat = re.compile(r"(\([^)]+\)|\[[^\]]+\]|%|°|log|fold|ratio|index|score|count|pH|a\.u\.|ppm|mol|mg|μ|uM|nM|mM|kg|cm|mm|ms|min|hr|Hz|eV|Pa|K|℃|度|率|比|量|数)", re.I)
    err_pat = re.compile(r"(SD|SEM|CI|IQR|±|error|误差|标准差|标准误|置信)", re.I)
    warns = []
    cap_txt = str(caption or "")
    for p, sp in zip(prov_panels, spec_panels):
        kind = p.get("kind")
        pid = p.get("panel")
        if kind not in ("heatmap", "pie", "donut"):
            val_lbl = sp.get("xlabel") if kind == "barh" else sp.get("ylabel")
            axis_nm = "xlabel" if kind == "barh" else "ylabel"
            if not val_lbl:
                warns.append({"panel": pid, "issue": f"missing_{axis_nm}", "msg": f"缺少数值轴标签 {axis_nm}（请补充物理量与单位）"})
            elif not unit_pat.search(str(val_lbl)):
                warns.append({"panel": pid, "issue": "unit_unclear", "msg": f"{axis_nm}='{val_lbl}' 未见明显单位/量纲，请核对是否需补充单位"})
        has_err = any((el.get("error") is not None or el.get("error_low") is not None or el.get("error_high") is not None)
                      for el in p.get("elements", []))
        if has_err:
            combined = " ".join(str(x or "") for x in (sp.get("ylabel"), sp.get("panel_title"), sp.get("legend_title"), cap_txt))
            if not err_pat.search(combined):
                warns.append({"panel": pid, "issue": "error_def_missing", "msg": "含误差线但图注/标签未标明 SD/SEM/95%CI，建议在 caption 或轴标签注明"})
        if p.get("missing_cells"):
            warns.append({"panel": pid, "issue": "missing_values", "msg": f"存在 {len(p['missing_cells'])} 处源数据缺失（已诚实留空未补零）"})
    return {"ok": len(warns) == 0, "n_warnings": len(warns), "warnings": warns}


def _place_legend(ax, handles, pnl, font_pt):
    loc = pnl.get("legend_loc", "best")
    kw = dict(handles=handles, fontsize=font_pt * 0.88,
              title=pnl.get("legend_title"), title_fontsize=font_pt * 0.88)
    if loc == "outer_top":
        ncol = int(pnl.get("legend_ncol", min(len(handles), 4)))
        leg = ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.02),
                        ncol=max(1, ncol), **kw)
    elif loc == "outer_right":
        leg = ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), **kw)
    else:
        leg = ax.legend(loc=loc, **kw)
    if pnl.get("legend_title"):
        leg.get_title().set_fontsize(font_pt * 0.88)
    return leg


def build_figure(spec):
    import matplotlib.pyplot as plt
    from chart_render import draw_panel

    st = resolve_style(spec.get("style", {}))
    font_pt = float(st["font_pt"])
    finfo = setup_matplotlib(font_pt)
    panels = spec.get("panels", [])
    ncol = int(spec.get("ncols", max(1, min(len(panels), 2))))
    nrow = max(1, (len(panels) + ncol - 1) // ncol)
    w_in = st["width_mm"] / 25.4
    has_cap = bool(spec.get("caption"))
    h_in = st["panel_h_mm"] * nrow / 25.4 + (0.28 * nrow) + (0.28 if has_cap else 0.0)
    fig, axes = plt.subplots(nrow, ncol, figsize=(w_in, h_in), squeeze=False,
                             layout="constrained")
    prov_panels = []
    legend_checks = []
    labels = "abcdefghijklmnop"

    for i, pnl in enumerate(panels):
        ax = axes[i // ncol][i % ncol]
        resolved = resolve_panel(pnl)
        for k, v in pnl.items():
            if k not in ("data", "mapping", "kind") and k not in resolved:
                resolved[k] = v
        handles, info = draw_panel(ax, fig, resolved, st)
        tag = pnl.get("id") or labels[i]
        if len(panels) > 1 and not pnl.get("no_panel_label"):
            tag_y = 1.14 if pnl.get("legend_loc") == "outer_top" else 1.04
            ax.text(-0.14, tag_y, f"({tag})", transform=ax.transAxes,
                    fontsize=font_pt + 1, fontweight="bold", va="bottom")

        is_pie = resolved["kind"] in ("pie", "donut")
        sec_set = set(str(n) for n in (pnl.get("secondary_series") or []))
        if is_pie:
            expected_series = [str(g) for g in resolved.get("groups", [])]
        elif sec_set and resolved["kind"] in ("bar", "grouped_bar"):
            prim_names = [s["name"] for s in resolved.get("series", []) if s["name"] != "__all__" and s["name"] not in sec_set]
            sec_names = [s["name"] for s in resolved.get("series", []) if s["name"] != "__all__" and s["name"] in sec_set]
            expected_series = prim_names + sec_names
        else:
            expected_series = [s["name"] for s in resolved.get("series", []) if s["name"] != "__all__"]
        rendered_legend = []
        want_leg = pnl.get("legend", False if is_pie else True)
        if want_leg and handles and resolved["kind"] != "heatmap":
            leg = _place_legend(ax, handles, pnl, font_pt)
            rendered_legend = [t.get_text() for t in leg.get_texts()]
            legend_checks.append({
                "panel": tag,
                "expected": expected_series,
                "rendered": rendered_legend,
                "match": rendered_legend == expected_series,
            })

        prov_panels.append({
            "panel": tag,
            "kind": resolved["kind"],
            "numeric_x": bool(resolved.get("numeric_x")),
            "aggregated": bool(resolved.get("aggregated")),
            "aggregation_mode": resolved.get("aggregation_mode"),
            "mapping": pnl.get("mapping"),
            "xlabel": pnl.get("xlabel"),
            "ylabel": pnl.get("ylabel"),
            "groups": resolved.get("groups", []),
            "series_names": expected_series,
            "legend_entries": rendered_legend,
            "elements": resolved["elements"],
            "missing_cells": resolved["missing"],
            "warnings": resolved.get("warnings", []),
            "glyph_audit": info.get("glyph_audit"),
            "fit_stats": info.get("fit_stats"),
            "data_source": resolved["source"],
        })

    # 隐藏未使用的多余空子图
    for j in range(len(panels), nrow * ncol):
        axes[j // ncol][j % ncol].set_visible(False)

    if spec.get("suptitle"):
        fig.suptitle(spec["suptitle"], fontsize=font_pt + 1)
    if spec.get("caption"):
        fig.supxlabel(str(spec["caption"]), fontsize=max(6.0, font_pt * 0.82), color="#444444")
    return fig, axes, st, finfo, prov_panels, legend_checks


def _export_pptx(spec, png_path, prov_path):
    """汇报用 PPTX：可编辑标题/图注文本框 + 嵌入高清图 + 溯源页。需 python-pptx（可选依赖）。"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    base = Path(png_path).with_suffix("")
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title = spec.get("suptitle") or "Figure"
    tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.25), Inches(12.3), Inches(0.8))
    p = tb.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(24)
    p.font.bold = True
    slide.shapes.add_picture(str(png_path), Inches(1.2), Inches(1.15), height=Inches(5.0))
    cap = slide.shapes.add_textbox(Inches(0.5), Inches(6.35), Inches(12.3), Inches(1.0))
    cap.text_frame.text = spec.get("caption") or "图注（可编辑）：单位、误差线含义（SD/SEM/95%CI）、显著性标记、样本量 n"
    cap.text_frame.paragraphs[0].font.size = Pt(12)
    if prov_path and Path(prov_path).exists():
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        tb2 = s2.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(6.8))
        tf = tb2.text_frame
        prov = json.loads(Path(prov_path).read_text(encoding="utf-8"))
        lines = ["溯源与自检（图表→源数据，可核验）：",
                 f"数据源: {', '.join(prov.get('data_sources', []))[:600]}",
                 f"字体: {json.dumps(prov.get('fonts', {}), ensure_ascii=False)}"]
        for pan in prov.get("panels", [])[:6]:
            lines.append(
                f"面板{pan.get('panel')}: 类型={pan.get('kind')}, 系列={pan.get('series_names')}, "
                f"分组={pan.get('groups')}, 缺失={len(pan.get('missing_cells', []))}"
            )
        chk = prov.get("self_check", {})
        lines.append(
            f"自检: editable_text={chk.get('editable_svg', {}).get('text_count')}, "
            f"svg_geometry.ok={chk.get('svg_geometry', {}).get('ok')}, "
            f"裁切={chk.get('png_edge', {}).get('clipping_suspect')}"
        )
        for i, ln in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = ln
            para.font.size = Pt(12)
    out = Path(str(base) + ".pptx")
    prs.save(str(out))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--base", default="figure")
    ap.add_argument("--png-dpi", type=int, default=300)
    ap.add_argument("--preview-dpi", type=int, default=100)
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base = args.base
    exp_cfg = spec.get("export") or {}
    png_dpi = int(exp_cfg.get("png_dpi", args.png_dpi))
    preview_dpi = min(108, max(72, int(exp_cfg.get("preview_dpi", args.preview_dpi))))
    transparent = bool(exp_cfg.get("transparent", False))
    want_pptx = bool(exp_cfg.get("pptx"))
    fig_spec = spec
    if want_pptx and (spec.get("suptitle") or spec.get("caption")):
        fig_spec = dict(spec)
        fig_spec["suptitle"] = ""  # 标题改放 PPTX 可编辑文本框，避免重复
        fig_spec["caption"] = ""   # 图注改放 PPTX 可编辑文本框

    fig, axes, st, finfo, prov, legend_checks = build_figure(fig_spec)
    w_in, h_in = fig.get_size_inches()
    paths = {}
    svg_path = outdir / f"{base}.svg"
    pdf_path = outdir / f"{base}.pdf"
    png_path = outdir / f"{base}.png"
    fig.savefig(svg_path, bbox_inches=None, transparent=transparent)
    paths["svg"] = str(svg_path)
    fig.savefig(pdf_path, transparent=transparent)
    paths["pdf"] = str(pdf_path)
    fig.savefig(png_path, dpi=png_dpi, transparent=transparent)
    paths["png"] = str(png_path)
    if exp_cfg.get("preview_png"):
        prev_path = outdir / f"{base}_preview.png"
        fig.savefig(prev_path, dpi=preview_dpi, transparent=transparent)
        paths["preview"] = str(prev_path)
    import matplotlib.pyplot as plt
    plt.close(fig)

    # 先嵌入元数据到 SVG 再做真实校验
    prov_file = outdir / f"{base}.provenance.json"
    svg_text = svg_path.read_text(encoding="utf-8")
    meta = (f'<metadata id="sci-provenance">case_id={spec.get("case_id")}; '
            f'spec={Path(args.spec).name}; provenance={prov_file.name}</metadata>')
    svg_text = svg_text.replace("</svg>", meta + "</svg>", 1)
    svg_path.write_text(svg_text, encoding="utf-8")

    # 真实多维度自检
    svg_text_audit = _audit_svg_labels(svg_path, prov, spec.get("panels", []))
    ann_audit = _audit_annotations(prov, spec.get("panels", []), caption=spec.get("caption", ""))
    ga_list = [{"panel": p["panel"], **(p.get("glyph_audit") or {})} for p in prov]
    glyph_value_audit = {
        "ok": all(g.get("ok", True) for g in ga_list),
        "verified_glyphs": sum(int(g.get("verified_glyphs", g.get("total_points", 0))) for g in ga_list),
        "max_abs_diff": max((float(g.get("max_abs_diff", 0.0)) for g in ga_list), default=0.0),
        "panels": ga_list,
    }
    checks = {
        "legend_series_match": all(c["match"] for c in legend_checks) if legend_checks else True,
        "legend_details": legend_checks,
        "editable_svg": verify_svg_editable(svg_path),
        "svg_text_audit": svg_text_audit,
        "glyph_value_audit": glyph_value_audit,
        "annotation_audit": ann_audit,
        "data_fidelity": {
            "n_panels": len(prov),
            "n_elements": sum(len(p["elements"]) for p in prov),
            "n_missing": sum(len(p["missing_cells"]) for p in prov),
            "warnings": [w for p in prov for w in p.get("warnings", [])],
        },
    }
    ec = png_edge_check(paths["png"])
    checks["png_edge"] = ec
    export_audit = {
        "width_mm": round(float(w_in) * 25.4, 2),
        "height_mm": round(float(h_in) * 25.4, 2),
        "png_dpi": png_dpi,
        "preview_dpi": preview_dpi if "preview" in paths else None,
        "png_size_px": ec.get("size_px"),
        "colorspace": ec.get("mode") or ("RGBA" if transparent else "RGB"),
        "transparent": transparent,
        "svg_fonttype": "none",
        "pdf_fonttype": 42,
        "svg_bytes": svg_path.stat().st_size,
        "pdf_bytes": pdf_path.stat().st_size,
        "png_bytes": png_path.stat().st_size,
    }
    checks["export_audit"] = export_audit
    try:
        from check_layout import check_svg
        checks["svg_geometry"] = check_svg(paths["svg"])
    except Exception as e:
        checks["svg_geometry"] = {"ok": None, "error": f"{type(e).__name__}: {e}"}

    note_scale = []
    for p in prov:
        vals = [el["value"] for el in p["elements"] if el.get("value") is not None]
        if vals:
            mx = max(map(abs, vals))
            nz = [abs(v) for v in vals if v != 0]
            mn = min(nz) if nz else 0
            if mn and mx / mn > 1e4:
                note_scale.append({"panel": p["panel"],
                                   "note": "数值跨>4个量级，建议 log_y 或 SI 词头并核对单位"})

    provenance = {
        "generated_by": "sci-figure-studio chart_tool v3",
        "case_id": spec.get("case_id"), "figure": base,
        "reproducibility": {
            "spec_file": str(Path(args.spec).name),
            "spec_sha256": sha256_of(args.spec),
            "command": f"python3 chart_tool.py {Path(args.spec).name} --outdir {outdir} --base {base} --png-dpi {png_dpi}",
        },
        "style": st, "fonts": finfo,
        "export_params": export_audit,
        "title": spec.get("suptitle"),
        "data_sources": sorted({json.dumps(p["data_source"], ensure_ascii=False, sort_keys=True)
                                for p in prov}),
        "panels": prov, "self_check": checks, "scale_notes": note_scale,
    }
    prov_path = dump_json(provenance, prov_file)

    if want_pptx:
        try:
            ppt = _export_pptx(spec, png_path, prov_path)
            paths["pptx"] = str(ppt)
        except Exception as e:
            paths["pptx_error"] = f"{type(e).__name__}: {e}"

    ok = (
        bool(checks.get("svg_geometry", {}).get("ok"))
        and bool(checks.get("editable_svg", {}).get("ok"))
        and bool(checks.get("legend_series_match"))
        and bool(checks.get("glyph_value_audit", {}).get("ok", True))
        and not ec.get("clipping_suspect")
    )
    summary = {
        "ok": ok,
        "outputs": paths,
        "provenance": prov_path,
        "fonts": finfo,
        "checks": {
            "editable_svg": checks["editable_svg"],
            "legend_series_match": checks["legend_series_match"],
            "svg_text_audit": checks["svg_text_audit"],
            "glyph_value_audit": checks["glyph_value_audit"],
            "annotation_audit": checks["annotation_audit"],
            "data_fidelity": checks["data_fidelity"],
            "png_edge": ec,
            "svg_geometry": checks["svg_geometry"],
            "scale_notes": note_scale,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
