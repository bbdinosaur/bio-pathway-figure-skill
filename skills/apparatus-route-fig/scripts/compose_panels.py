#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compose_panels.py — 顶刊级多面板学术复合图无损 SVG 合成器（纯标准库）：
将多个可编辑子图 SVG（如 run_all.py 机制/装置图 Panel A + chart_kit.py/matplotlib 数据图 Panel B/C）
合成为单张可编辑矢量 SVG（带加粗 A/B/C 面板标签、统一标题与溯源页脚），自动隔离各子图 XML ID/defs/clipPath
防止跨面板命名冲突，并复用 render.py 导出 300dpi PNG、矢量 PDF 与轻量 96dpi 预览图。

用法:
  python3 compose_panels.py --spec /app/work/compose.json --out /app/output --name figure03 --dpi 300
  或快捷命令行（等宽网格）:
  python3 compose_panels.py --panels A:panel_a.svg B:panel_b.svg --cols 2 --title "Figure 3" --out /app/output --name figure03
"""
import argparse
import copy
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render as rendermod
import sir as sirmod

SVGNS = "http://www.w3.org/2000/svg"
XLINKNS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVGNS)
ET.register_namespace("xlink", XLINKNS)

_UNIT_PX = {"": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0}


def _parse_len_px(val, fallback):
    if val is None:
        return float(fallback)
    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([a-z%]*)\s*$", str(val), re.I)
    if not m or m.group(2) == "%":
        return float(fallback)
    return float(m.group(1)) * _UNIT_PX.get(m.group(2).lower(), 1.0)


def _svg_viewbox(root):
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    if len(vb) == 4:
        try:
            vx, vy, vw, vh = [float(x) for x in vb]
            if vw > 1 and vh > 1:
                return vx, vy, vw, vh
        except Exception:
            pass
    w = _parse_len_px(root.get("width"), 800.0)
    h = _parse_len_px(root.get("height"), 600.0)
    return 0.0, 0.0, max(w, 10.0), max(h, 10.0)


def _rewrite_css_urls(txt, prefix, id_set):
    if not txt:
        return txt
    def _repl(m):
        ref = m.group(1).strip().strip("'\"")
        if ref in id_set:
            return "url(#%s%s)" % (prefix, ref)
        return m.group(0)
    return re.sub(r"url\(\s*#([^)\s]+)\s*\)", _repl, txt)


def _namespace_ids(elem, prefix):
    """隔离单个子 SVG 内全部 id 与引用（url(#id)、href="#id"、xlink:href="#id"、CSS <style>），杜绝 clipPath/defs 冲突。"""
    id_set = set()
    for e in elem.iter():
        eid = e.get("id")
        if eid:
            id_set.add(eid)
    if not id_set:
        return
    for e in elem.iter():
        eid = e.get("id")
        if eid in id_set:
            e.set("id", prefix + eid)
        for ak, av in list(e.attrib.items()):
            if not isinstance(av, str):
                continue
            if ak in ("href", "{%s}href" % XLINKNS) and av.startswith("#") and av[1:] in id_set:
                e.set(ak, "#" + prefix + av[1:])
            elif "url(#" in av:
                e.set(ak, _rewrite_css_urls(av, prefix, id_set))
        if isinstance(e.tag, str) and e.tag.split("}")[-1] == "style" and e.text:
            e.text = _rewrite_css_urls(e.text, prefix, id_set)
            # 同时给 class/id 选择器里的 #id 加前缀
            for old_id in id_set:
                e.text = re.sub(r"#%s\b" % re.escape(old_id), "#" + prefix + old_id, e.text)


def _inline_root_style_font(root, child_g):
    """把子 SVG 根节点的 font-family/style 继承到面板分组，避免拼接后丢失字体。"""
    ff = root.get("font-family")
    if ff:
        child_g.set("font-family", ff)
    st = root.get("style")
    if st:
        child_g.set("style", st)


def _strip_panel_chrome(root, vx, vy, vw, vh, strip_header=False, strip_footer=False):
    """剥离本 Skill 子 SVG 内部重复的标题栏/页脚与全画布白底矩形（防止平移裁剪后遮挡外层 A/B/C 徽标），并紧缩 viewBox 空白。"""
    pmap = {c: p for p in root.iter() for c in p}
    header_roles = {"title_bar", "title", "subtitle", "header_rule"}
    footer_roles = {"prov_footer"}
    cut_top = vy
    removed_footer = False
    # 剥离子 SVG 自身的全画布白底矩形（外层画布已有统一白底），彻底避免平移后白框上溢盖住面板标题
    for ch in list(root):
        if isinstance(ch.tag, str) and ch.tag.split("}")[-1] == "rect":
            cid = ch.get("id") or ""
            fill = (ch.get("fill") or "").strip().lower()
            if cid == "canvas_bg" or (fill in ("#ffffff", "#fff", "white") and (ch.get("stroke") or "none").lower() == "none"):
                try:
                    rw = _parse_len_px(ch.get("width"), 0)
                    rh = _parse_len_px(ch.get("height"), 0)
                    if cid == "canvas_bg" or (rw >= vw * 0.95 and rh >= vh * 0.95):
                        root.remove(ch)
                except Exception:
                    pass
    if not strip_header and not strip_footer:
        return vx, vy, vw, vh
    for e in list(root.iter()):
        role = e.get("data-role") or ""
        if strip_header and role in header_roles:
            if role == "header_rule":
                pts = (e.get("points") or "").split()
                for pt in pts:
                    if "," in pt:
                        try:
                            cut_top = max(cut_top, float(pt.split(",")[1]) + 4.0)
                        except Exception:
                            pass
            par = pmap.get(e)
            if par is not None:
                par.remove(e)
        elif strip_footer and role in footer_roles:
            removed_footer = True
            par = pmap.get(e)
            if par is not None:
                par.remove(e)
    new_vy = cut_top if cut_top > vy + 8.0 else vy
    new_vh = vh - (new_vy - vy) - (18.0 if removed_footer else 0.0)
    if new_vh < 60.0:
        return vx, vy, vw, vh
    return vx, new_vy, vw, new_vh


def _build_inline_sir(sir_obj, work_dir, idx, fam):
    import build as buildmod
    import checks as checksmod
    import svgfig as svgfigmod

    sird = copy.deepcopy(sir_obj)
    errs, warns, _info = sirmod.validate_sir(sird)
    if errs:
        raise ValueError("Panel %d SIR 校验失败: %s" % (idx, "; ".join(errs)))
    sc = buildmod.build_scene(sird, int(sird.get("maxcols") or 6))
    rep = checksmod.run(sc, sird)
    pdir = work_dir / ("p%d" % idx)
    pdir.mkdir(parents=True, exist_ok=True)
    svg_p = pdir / ("p%d.svg" % idx)
    svgfigmod.save(sc, svg_p, font_family=(fam or "sans-serif") + ", " + svgfigmod.DEFAULT_FONTS)
    prov = buildmod.provenance_table(sc)
    (pdir / "provenance.json").write_text(json.dumps({"table": prov}, ensure_ascii=False, indent=1), encoding="utf-8")
    return svg_p, {"mode": "sir", "ok": rep["ok"], "errors": rep["errors"], "warns": list(warns) + list(rep["warns"])}


def _build_inline_chart(chart_obj, base_dir, work_dir, idx, suppress_footer=False):
    import chart_kit as ckmod

    raw_ch = copy.deepcopy(chart_obj)
    if suppress_footer and raw_ch.get("prov_footer"):
        if not raw_ch.get("source"):
            raw_ch["source"] = {"quote": str(raw_ch["prov_footer"]), "loc": "panel.prov_footer"}
        raw_ch.pop("prov_footer", None)
    spec = ckmod.hydrate_spec(raw_ch, base_dir)
    errs = ckmod.validate(spec)
    if errs:
        raise ValueError("Panel %d chart 校验失败: %s" % (idx, "; ".join(errs)))
    pdir = work_dir / ("p%d" % idx)
    pdir.mkdir(parents=True, exist_ok=True)
    rep = ckmod.render(spec, pdir, "p%d" % idx, dpi=72)
    svg_p = pdir / ("p%d.svg" % idx)
    return svg_p, {"mode": "chart", "ok": rep["ok"], "errors": [], "warns": list(rep.get("warns") or [])}


def _load_panel(spec_item, base_dir, idx, has_outer_footer=False, work_dir=None, fam=None):
    panel_chk = None
    if spec_item.get("sir") or spec_item.get("sir_file"):
        sir_obj = spec_item.get("sir")
        if not sir_obj:
            sp = Path(spec_item["sir_file"])
            if not sp.is_absolute():
                sp = base_dir / sp
            sir_obj = json.loads(sp.read_text(encoding="utf-8"))
        svg_p, panel_chk = _build_inline_sir(sir_obj, work_dir, idx, fam)
    elif spec_item.get("chart") or spec_item.get("chart_file"):
        ch_obj = spec_item.get("chart")
        ch_base = base_dir
        if not ch_obj:
            cp = Path(spec_item["chart_file"])
            if not cp.is_absolute():
                cp = base_dir / cp
            ch_obj = json.loads(cp.read_text(encoding="utf-8"))
            ch_base = cp.parent
        svg_p, panel_chk = _build_inline_chart(ch_obj, ch_base, work_dir, idx, suppress_footer=bool(has_outer_footer))
    else:
        svg_p = Path(spec_item["svg"])
        if not svg_p.is_absolute():
            cand = base_dir / svg_p
            if cand.exists():
                svg_p = cand
        if not svg_p.exists():
            raise FileNotFoundError("面板 SVG 不存在: %s" % svg_p)
    root = ET.parse(str(svg_p)).getroot()
    vx, vy, vw, vh = _svg_viewbox(root)
    label = str(spec_item.get("label") or chr(ord("A") + idx)).strip()
    title = str(spec_item.get("title") or "").strip()
    strip_h = spec_item.get("strip_inner_header")
    if strip_h is None:
        strip_h = bool(title)
    strip_f = spec_item.get("strip_inner_footer")
    if strip_f is None:
        strip_f = bool(has_outer_footer)
    vx, vy, vw, vh = _strip_panel_chrome(root, vx, vy, vw, vh, strip_header=bool(strip_h), strip_footer=bool(strip_f))
    weight = float(spec_item.get("weight") or 0.0)
    return {
        "index": idx, "label": label, "title": title, "path": svg_p,
        "root": root, "vx": vx, "vy": vy, "vw": vw, "vh": vh,
        "weight": weight, "prefix": "p%d_" % idx, "check": panel_chk,
    }


def compose(spec, base_dir, out_dir, name, dpi=300, preview=None, preview_dpi=96):
    """按 rows（二维面板列表）或 panels+cols 网格无损合成多面板可编辑 SVG（支持 svg/inline sir/inline chart），并导出 PNG/PDF。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fam, _ffile = rendermod.detect_cjk()
    ff = ("%s, Arial, Helvetica, DejaVu Sans, sans-serif" % fam) if fam else "Arial, Helvetica, DejaVu Sans, sans-serif"

    # 解析行布局：支持 spec["rows"] = [[panelA, panelB], [panelC]] 或 spec["panels"] + spec["cols"]
    rows_raw = spec.get("rows")
    if isinstance(rows_raw, list) and rows_raw and isinstance(rows_raw[0], list):
        grid_spec = rows_raw
    else:
        plist = spec.get("panels") or []
        if not isinstance(plist, list) or not plist:
            raise ValueError("compose spec 缺少 panels 或 rows 列表")
        cols = max(1, int(spec.get("cols") or (2 if len(plist) > 1 else 1)))
        grid_spec = [plist[i:i + cols] for i in range(0, len(plist), cols)]

    footer = str(spec.get("footer") or spec.get("prov_footer") or "").strip()
    with tempfile.TemporaryDirectory(prefix="compose_panels_") as tmpd:
        work_dir = Path(tmpd)
        loaded_rows = []
        idx = 0
        for rlist in grid_spec:
            lrow = []
            for item in rlist:
                lrow.append(_load_panel(item, base_dir, idx, has_outer_footer=bool(footer), work_dir=work_dir, fam=fam))
                idx += 1
            if lrow:
                loaded_rows.append(lrow)

        return _assemble_and_export(spec, loaded_rows, out, name, ff, fam, footer, dpi, preview, preview_dpi)


def _assemble_and_export(spec, loaded_rows, out, name, ff, fam, footer, dpi, preview, preview_dpi):

    target_w = float(spec.get("width") or 1600.0)
    margin_x = float(spec.get("margin_x") or 28.0)
    gap_x = float(spec.get("gap_x") or 28.0)
    gap_y = float(spec.get("gap_y") or 30.0)
    inner_w = max(target_w - 2 * margin_x, 400.0)

    # 顶部总标题/副标题高度
    title = str(spec.get("title") or "").strip()
    subtitle = str(spec.get("subtitle") or "").strip()
    t_lines = sirmod.wrap_text(title, 20.0, inner_w - 20.0, bold=True)[:2] if title else []
    s_lines = sirmod.wrap_text(subtitle, 12.5, inner_w - 20.0)[:2] if subtitle else []
    y_cur = 24.0
    header_elems = []
    if t_lines:
        accent_h = len(t_lines) * 26.0 + (len(s_lines) * 18.0 + 4.0 if s_lines else 0.0)
        header_elems.append(("accent", margin_x, y_cur - 2.0, 5.0, accent_h))
        for li, ln in enumerate(t_lines):
            header_elems.append(("title", margin_x + 14.0, y_cur + 18.0 + li * 26.0, ln))
        y_cur += len(t_lines) * 26.0 + 4.0
        for si, ln in enumerate(s_lines):
            header_elems.append(("subtitle", margin_x + 14.0, y_cur + 13.0 + si * 18.0, ln))
        if s_lines:
            y_cur += len(s_lines) * 18.0 + 6.0
        header_elems.append(("rule", margin_x, y_cur + 2.0, target_w - margin_x, y_cur + 2.0))
        y_cur += 20.0

    # 逐行计算每块面板的缩放与落位：同行所有面板等高对齐，填满 inner_w
    placements = []
    for rrow in loaded_rows:
        n_c = len(rrow)
        avail_w = inner_w - gap_x * (n_c - 1)
        # 若某行显式给了 weight，按权重分配宽；否则按原始纵横比自然等高分配（保证文字比例最和谐）
        if any(p["weight"] > 0 for p in rrow):
            ws = [p["weight"] if p["weight"] > 0 else 1.0 for p in rrow]
            wsum = sum(ws)
            box_ws = [avail_w * (w / wsum) for w in ws]
            scales = [bw / p["vw"] for bw, p in zip(box_ws, rrow)]
            row_h = max(p["vh"] * sc for p, sc in zip(rrow, scales))
        else:
            # 理想等高 H_row 使 sum(H_row * (vw/vh)) == avail_w
            ar_sum = sum(p["vw"] / p["vh"] for p in rrow)
            row_h = avail_w / max(ar_sum, 0.2)
            # 防止单列极窄高图过高或极扁图失真
            row_h = max(240.0, min(row_h, 920.0))
            box_ws = [row_h * (p["vw"] / p["vh"]) for p in rrow]
            tot_bw = sum(box_ws)
            if tot_bw > avail_w:
                k = avail_w / tot_bw
                box_ws = [bw * k for bw in box_ws]
                row_h *= k
            scales = [bw / p["vw"] for bw, p in zip(box_ws, rrow)]

        # 面板顶栏高度（用于放 A/B/C 徽标与可选小标题）
        head_h = 26.0
        # 居中对齐整行
        row_total_w = sum(box_ws) + gap_x * (n_c - 1)
        x_cur = margin_x + max(0.0, (inner_w - row_total_w) / 2.0)
        for p, bw, sc in zip(rrow, box_ws, scales):
            ph = p["vh"] * sc
            py = y_cur + head_h + (row_h - ph) / 2.0
            placements.append({
                "panel": p, "x": x_cur, "y": py, "head_y": y_cur,
                "w": bw, "h": ph, "scale": sc,
            })
            x_cur += bw + gap_x
        y_cur += head_h + row_h + gap_y

    f_lines = sirmod.wrap_text(footer, 11.0, inner_w)[:2] if footer else []
    footer_y = y_cur - 6.0
    if f_lines:
        y_cur += len(f_lines) * 16.0 + 16.0
    else:
        y_cur = max(y_cur - 10.0, 200.0)
    total_h = round(y_cur, 1)

    # 组装顶层可编辑 SVG
    svg_root = ET.Element("{%s}svg" % SVGNS, {
        "width": "%g" % target_w, "height": "%g" % total_h,
        "viewBox": "0 0 %g %g" % (target_w, total_h),
        "font-family": ff,
    })
    ET.SubElement(svg_root, "{%s}rect" % SVGNS, {
        "id": "canvas_bg", "x": "0", "y": "0",
        "width": "%g" % target_w, "height": "%g" % total_h,
        "fill": "#FFFFFF", "stroke": "none",
    })

    # 顶层标题层
    if header_elems:
        g_hdr = ET.SubElement(svg_root, "{%s}g" % SVGNS, {"id": "layer_header"})
        for item in header_elems:
            if item[0] == "accent":
                _, x, y, w, h = item
                ET.SubElement(g_hdr, "{%s}rect" % SVGNS, {
                    "x": "%.1f" % x, "y": "%.1f" % y, "width": "%.1f" % w, "height": "%.1f" % h,
                    "rx": "2.5", "fill": "#2B6CB0",
                })
            elif item[0] == "title":
                _, x, y, ln = item
                te = ET.SubElement(g_hdr, "{%s}text" % SVGNS, {
                    "x": "%.1f" % x, "y": "%.1f" % y, "font-family": ff,
                    "font-size": "20", "font-weight": "bold", "fill": "#1A202C",
                })
                te.text = ln
            elif item[0] == "subtitle":
                _, x, y, ln = item
                te = ET.SubElement(g_hdr, "{%s}text" % SVGNS, {
                    "x": "%.1f" % x, "y": "%.1f" % y, "font-family": ff,
                    "font-size": "12.5", "fill": "#4A5568",
                })
                te.text = ln
            elif item[0] == "rule":
                _, x1, y1, x2, y2 = item
                ET.SubElement(g_hdr, "{%s}line" % SVGNS, {
                    "x1": "%.1f" % x1, "y1": "%.1f" % y1, "x2": "%.1f" % x2, "y2": "%.1f" % y2,
                    "stroke": "#CBD5E0", "stroke-width": "1.2",
                })

    # 逐面板注入（完整隔离 defs/id + 保留全部可编辑矢量与文本）
    panel_meta = []
    for pl in placements:
        p = pl["panel"]
        g_wrap = ET.SubElement(svg_root, "{%s}g" % SVGNS, {
            "id": "panel_%s" % re.sub(r"[^A-Za-z0-9_]", "_", p["label"]),
            "data-panel": p["label"], "data-source-svg": p["path"].name,
        })
        # 面板顶栏：Nature/Cell 规范粗体字母徽标 + 可选副标题
        if p["label"]:
            lbl_el = ET.SubElement(g_wrap, "{%s}text" % SVGNS, {
                "x": "%.1f" % (pl["x"] + 2.0), "y": "%.1f" % (pl["head_y"] + 19.0),
                "font-family": ff, "font-size": "18", "font-weight": "bold",
                "fill": "#1A202C", "data-role": "panel_label",
            })
            lbl_el.text = p["label"]
        if p["title"]:
            ttl_el = ET.SubElement(g_wrap, "{%s}text" % SVGNS, {
                "x": "%.1f" % (pl["x"] + 26.0), "y": "%.1f" % (pl["head_y"] + 18.0),
                "font-family": ff, "font-size": "13", "font-weight": "bold",
                "fill": "#2D3748", "data-role": "panel_title",
            })
            ttl_el.text = p["title"]

        # 轻微面板边界框（可选，默认浅灰极细边框强化分区，设 panel_border=false 可关）
        if spec.get("panel_border", False):
            ET.SubElement(g_wrap, "{%s}rect" % SVGNS, {
                "x": "%.1f" % pl["x"], "y": "%.1f" % pl["y"],
                "width": "%.1f" % pl["w"], "height": "%.1f" % pl["h"],
                "rx": "6", "fill": "none", "stroke": "#E2E8F0", "stroke-width": "1",
            })

        # 深拷贝并隔离命名空间
        cloned = copy.deepcopy(p["root"])
        _namespace_ids(cloned, p["prefix"])
        g_content = ET.SubElement(g_wrap, "{%s}g" % SVGNS, {
            "id": p["prefix"] + "content",
            "transform": "translate(%.2f,%.2f) scale(%.5f) translate(%.2f,%.2f)" % (
                pl["x"], pl["y"], pl["scale"], -p["vx"], -p["vy"]
            ),
        })
        _inline_root_style_font(cloned, g_content)
        for ch in list(cloned):
            g_content.append(ch)
        panel_meta.append({
            "label": p["label"], "title": p["title"], "source_svg": str(p["path"]),
            "orig_viewBox": [p["vx"], p["vy"], p["vw"], p["vh"]],
            "placed_box": [round(pl["x"], 1), round(pl["y"], 1), round(pl["w"], 1), round(pl["h"], 1)],
            "scale": round(pl["scale"], 4),
        })

    if f_lines:
        g_ft = ET.SubElement(svg_root, "{%s}g" % SVGNS, {"id": "layer_footer"})
        for fi, ln in enumerate(f_lines):
            fe = ET.SubElement(g_ft, "{%s}text" % SVGNS, {
                "x": "%.1f" % (target_w - margin_x), "y": "%.1f" % (footer_y + 12.0 + fi * 16.0),
                "font-family": ff, "font-size": "11", "fill": "#718096", "text-anchor": "end",
            })
            fe.text = ln

    svg_path = out / (name + ".svg")
    png_path = out / (name + ".png")
    pdf_path = out / (name + ".pdf")
    ET.ElementTree(svg_root).write(str(svg_path), encoding="utf-8", xml_declaration=True)

    rmeta = {"cjk_family": fam}
    render_warns = []
    try:
        rmeta["png"] = {"engine": rendermod.svg_to_png(svg_path, png_path, dpi)}
    except Exception as e:
        rmeta["png"] = {"error": str(e)}
        render_warns.append("PNG 导出降级失败: %s" % e)
    try:
        rmeta["pdf"] = {"engine": rendermod.svg_to_pdf(svg_path, pdf_path)}
    except Exception as e:
        rmeta["pdf"] = {"error": str(e)}
        render_warns.append("PDF 导出降级失败: %s" % e)
    if preview:
        pv_p = Path(preview)
        pv_p.parent.mkdir(parents=True, exist_ok=True)
        pv_dpi = min(int(preview_dpi or 96), 108)
        try:
            rmeta["preview"] = {"path": str(pv_p), "dpi": pv_dpi,
                                "engine": rendermod.svg_to_png(svg_path, pv_p, pv_dpi)}
        except Exception as e:
            rmeta["preview"] = {"error": str(e)}

    # 自动合并各面板同目录的 provenance.json，形成复合图统一溯源表
    merged_prov = []
    seen_prov_dirs = set()
    for pl in placements:
        p = pl["panel"]
        p_dir = p["path"].parent
        prov_f = p_dir / "provenance.json"
        if prov_f.exists() and (p["label"], str(prov_f)) not in seen_prov_dirs:
            seen_prov_dirs.add((p["label"], str(prov_f)))
            try:
                pj = json.loads(prov_f.read_text(encoding="utf-8"))
                for row in (pj.get("table") or []):
                    if isinstance(row, dict):
                        r2 = dict(row)
                        r2["panel"] = p["label"]
                        merged_prov.append(r2)
            except Exception:
                pass
    if merged_prov:
        (out / "provenance.json").write_text(json.dumps({
            "figure": name, "table": merged_prov,
            "note": "多面板学术复合图统一逐元素/逐系列溯源明细表（按面板 A/B/C 分组）",
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    # 统计可编辑文本数并汇总内联子面板自检结果
    n_text = sum(1 for e in svg_root.iter() if isinstance(e.tag, str) and e.tag.split("}")[-1] == "text")
    all_errs, all_warns, panel_checks = [], ([] if n_text > 0 else ["合成 SVG 未检测到 <text> 节点"]) + render_warns, []
    for pl in placements:
        p = pl["panel"]
        chk = p.get("check")
        if chk:
            panel_checks.append({"panel": p["label"], "mode": chk["mode"], "ok": chk["ok"],
                                 "errors": len(chk["errors"]), "warns": len(chk["warns"])})
            for e in chk["errors"]:
                all_errs.append("Panel %s: %s" % (p["label"], e))
            for w in chk["warns"]:
                all_warns.append("Panel %s: %s" % (p["label"], w))
    rep = {
        "ok": len(all_errs) == 0, "errors": all_errs, "warns": all_warns,
        "canvas": [target_w, total_h], "panels": panel_meta, "panel_checks": panel_checks,
        "text_nodes": n_text, "merged_provenance_rows": len(merged_prov),
        "svg": str(svg_path), "png": str(png_path),
        "pdf": str(pdf_path), "render": rmeta,
    }
    (out / (name + "_compose_meta.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "checks_report.json").write_text(json.dumps({
        "ok": rep["ok"], "errors": rep["errors"], "warns": rep["warns"],
        "summary": {"canvas": rep["canvas"], "panels": len(panel_meta), "text_nodes": n_text},
        "panel_checks": panel_checks,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "render_meta.json").write_text(json.dumps(rmeta, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep, merged_prov


def _write_result_skel(a, rep, merged_prov):
    dst_res = getattr(a, "result_skel", None)
    if not dst_res:
        return
    contract = {}
    if getattr(a, "contract", None) and Path(a.contract).exists():
        try:
            import audit_delivery as auditmod
            cj = json.loads(Path(a.contract).read_text(encoding="utf-8"))
            for k in auditmod._extract_contract_keys(cj):
                kl = k.strip().lower()
                if kl in ("editable_svg", "svg", "svg_file", "svg_path", "output_svg", "editable_source", "editable_source_path") or kl.endswith("_svg") or kl.endswith("_svg_path"):
                    contract[k] = a.name + ".svg"
                elif kl in ("png", "png_file", "png_path", "preview_png", "rendered_png", "output_png", "image_path") or kl.endswith("_png") or kl.endswith("_png_path"):
                    contract[k] = a.name + ".png"
                elif kl in ("pdf", "pdf_file", "pdf_path", "output_pdf", "vector_pdf") or kl.endswith("_pdf") or kl.endswith("_pdf_path"):
                    contract[k] = a.name + ".pdf"
                elif kl in ("status", "run_status"):
                    contract[k] = "ok"
                elif kl in ("case_id", "id"):
                    contract[k] = a.case_id or "CASE_ID"
                elif kl in ("provenance_file", "provenance_path", "provenance_json"):
                    contract[k] = "provenance.json"
                elif kl in ("checks_report", "check_report", "export_check", "export_checks"):
                    contract[k] = a.name + "_compose_meta.json"
                else:
                    contract[k] = "<待填：按 case.json 契约与多面板科学内容填写>"
        except Exception:
            pass
    src_locs = []
    for row in (merged_prov or []):
        loc = str(row.get("loc") or "").strip()
        if loc and loc not in src_locs:
            src_locs.append(loc)
    sk = {
        "case_id": a.case_id or "CASE_ID",
        "status": "ok" if rep.get("ok") else "partial",
        "deliverables": {
            "editable_source": {"path": a.name + ".svg", "format": "svg", "panels": [p["label"] for p in rep.get("panels") or []]},
            "exports": [{"path": a.name + ".png", "format": "png", "dpi": a.dpi},
                        {"path": a.name + ".pdf", "format": "pdf"}],
            "provenance": "多面板合并溯源见 provenance.json",
            "provenance_table": merged_prov or [],
        },
        "sources": src_locs or ["provenance.json"],
        "checks": {"ok": rep.get("ok", True), "errors": rep.get("errors", []), "warns": rep.get("warns", []),
                   "text_nodes": rep.get("text_nodes", 0), "panel_count": len(rep.get("panels") or [])},
        "render": rep.get("render", {}),
        "output_contract": contract,
        "output_contract_fields": list(contract.keys()),
        "uncertainty": list(rep.get("warns") or []),
        "change_records": [{"action": "compose_panels", "target": a.name + ".svg",
                            "detail": "Composed %d editable SVG panels into a unified vector figure" % len(rep.get("panels") or [])}],
    }
    for k, v in contract.items():
        if k not in sk:
            sk[k] = v
    p_out = Path(dst_res)
    p_out.parent.mkdir(parents=True, exist_ok=True)
    p_out.write_text(json.dumps(sk, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="多面板学术复合图无损 SVG 合成器")
    ap.add_argument("--spec", default=None, help="合成规格 JSON（含 rows 或 panels/cols/title/subtitle/footer）")
    ap.add_argument("--panels", nargs="*", help="快捷方式：LABEL:path.svg（如 A:mech.svg B:data.svg）")
    ap.add_argument("--cols", type=int, default=2)
    ap.add_argument("--width", type=float, default=1600.0)
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--footer", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="figure")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--preview", default=None)
    ap.add_argument("--preview-dpi", type=int, default=96)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--contract", default=None)
    ap.add_argument("--result-skel", default=None)
    a = ap.parse_args()

    if a.spec:
        sp = Path(a.spec)
        spec = json.loads(sp.read_text(encoding="utf-8"))
        base = sp.parent
    elif a.panels:
        plist = []
        for i, item in enumerate(a.panels):
            if ":" in item and not Path(item).exists():
                lbl, pth = item.split(":", 1)
            else:
                lbl, pth = chr(ord("A") + i), item
            plist.append({"label": lbl.strip(), "svg": pth.strip()})
        spec = {"panels": plist, "cols": a.cols, "width": a.width,
                "title": a.title, "subtitle": a.subtitle, "footer": a.footer}
        base = Path.cwd()
    else:
        print("必须提供 --spec 或 --panels", file=sys.stderr)
        return 2

    try:
        rep, merged_prov = compose(spec, base, a.out, a.name, dpi=a.dpi, preview=a.preview, preview_dpi=a.preview_dpi)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"ok": False, "stage": "compose_validate", "errors": [str(e)]}, ensure_ascii=False))
        return 2
    _write_result_skel(a, rep, merged_prov)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
