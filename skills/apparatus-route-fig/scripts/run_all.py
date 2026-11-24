#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py — 一键管线：SIR JSON → 校验 → 布图 → 静态自检 → SVG/PNG/PDF + 报告。

用法: python3 run_all.py --sir sir.json --out /app/output [--name diagram]
      [--dpi 300] [--case-id CASE] [--maxcols 6] [--result-skel /app/output/result.json]
退出码: 0=全通过  2=SIR结构错误  3=静态检查有错误(仍会写出图件)
"""
import argparse
import json
import sys
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _multi(a, sirmod, buildmod, checks, svgfig, rendermod, figures, sird=None):
    """多图模式：顶层 figures=[子SIR,...] → 逐图生成 name_1..N + 汇总报告与溯源表。"""
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fam, ffile = rendermod.detect_cjk()
    all_ok, manifest, all_prov, all_warns = True, [], [], []
    for i, sub in enumerate(figures, 1):
        name = "%s_%d" % (a.name, i)
        try:
            errs, warns, info = sirmod.validate_sir(sub)
            if errs:
                manifest.append({"figure": name, "ok": False, "errors": errs})
                all_ok = False
                continue
            sc = buildmod.build_scene(sub, a.maxcols)
            rep = checks.run(sc, sub)
            svgfig.save(sc, out / (name + ".svg"), font_family=(fam or "sans-serif") + ", " + svgfig.DEFAULT_FONTS)
            png, pdf = out / (name + ".png"), out / (name + ".pdf")
            rmeta = {"cjk_family": fam}
            try:
                rmeta["png"] = {"engine": rendermod.svg_to_png(out / (name + ".svg"), png, a.dpi)}
                rmeta["pdf"] = {"engine": rendermod.svg_to_pdf(out / (name + ".svg"), pdf)}
                if a.preview:
                    pvd = Path(a.preview)
                    pv_dst = (pvd / (name + "_preview.png")) if pvd.suffix.lower() != ".png" else pvd.with_name(pvd.stem + "_%d.png" % i)
                    pv_dst.parent.mkdir(parents=True, exist_ok=True)
                    rmeta["preview"] = {"path": str(pv_dst), "dpi": min(int(a.preview_dpi or 96), 108),
                                        "engine": rendermod.svg_to_png(out / (name + ".svg"), pv_dst, min(int(a.preview_dpi or 96), 108))}
            except Exception:
                import mirror
                rmeta["mirror"] = mirror.render(sc, png, pdf, a.dpi, ffile, fam)
            (out / (name + "_checks.json")).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
            for row in buildmod.provenance_table(sc):
                row["figure"] = name
                all_prov.append(row)
            all_warns.extend(["%s: %s" % (name, w) for w in rep.get("warns", [])])
            if not rep["ok"]:
                all_ok = False
            manifest.append({"figure": name, "ok": rep["ok"], "errors": len(rep["errors"]),
                             "warns": len(rep["warns"]), "title": sub.get("title", ""), "render": rmeta})
        except Exception as e:
            manifest.append({"figure": name, "ok": False, "errors": [str(e)]})
            all_ok = False
    (out / "provenance.json").write_text(json.dumps({
        "case_id": a.case_id, "table": all_prov,
        "note": "多图模式逐元素溯源表；每个图面元素对应材料原文摘录与定位"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / (a.name + "_manifest.json")).write_text(json.dumps(
        {"case_id": a.case_id, "ok": all_ok, "figures": manifest,
         "files": sorted(p.name for p in out.iterdir())}, ensure_ascii=False, indent=1), encoding="utf-8")
    res_dst = a.result_out or a.result_skel
    unfilled = None
    if res_dst:
        agg_rep = {"ok": all_ok, "errors": [] if all_ok else ["部分子图检查未通过，见 manifest"],
                   "warns": all_warns, "figures": manifest}
        unfilled = _skel(a, agg_rep, {"mode": "multi", "cjk_family": fam}, Path(res_dst),
                         Path(a.contract) if a.contract else None, all_prov, sird=sird, multi_count=len(figures))
    out_msg = {"ok": all_ok, "mode": "multi", "figures": len(figures),
               "manifest": str(out / (a.name + "_manifest.json"))}
    if unfilled is not None:
        out_msg["unfilled_contract_fields"] = unfilled
    if a.result_out:
        import audit_delivery as auditmod
        out_msg["audit"] = auditmod.audit(Path(a.result_out).parent, a.contract)
    print(json.dumps(out_msg, ensure_ascii=False, indent=1))
    return 0 if all_ok else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="diagram")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--preview", default=None, help="轻量视觉自检预览 PNG 路径（<=108 DPI）")
    ap.add_argument("--preview-dpi", type=int, default=96)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--maxcols", type=int, default=6)
    ap.add_argument("--result-skel", default=None)
    ap.add_argument("--result-out", default=None, help="直接写入正式 result.json 并自动触发交付核验")
    ap.add_argument("--contract", default=None, help="case.json 路径：读取其中 output_contract 逐字段镜像到 result 骨架")
    ap.add_argument("--mirror-only", action="store_true", help="跳过SVG链，直接matplotlib镜像渲染")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import sir as sirmod
    import build as buildmod
    import checks
    import svgfig
    import render as rendermod
    sird = sirmod.load(a.sir)
    figures = sird.get("figures")
    if isinstance(figures, list) and figures:
        return _multi(a, sirmod, buildmod, checks, svgfig, rendermod, figures, sird)
    errs, warns, info = sirmod.validate_sir(sird)
    if errs:
        rep = {"ok": False, "stage": "sir_validate", "errors": errs, "warns": warns}
        (out / "checks_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 2
    fam, ffile = rendermod.detect_cjk()
    sc = buildmod.build_scene(sird, a.maxcols)
    rep = checks.run(sc, sird)
    rep["sir_warns"] = warns
    rep["info"] = (rep.get("info") or []) + info
    svg_path = out / (a.name + ".svg")
    svgfig.save(sc, svg_path, font_family=(fam or "sans-serif") + ", " + svgfig.DEFAULT_FONTS)
    png_path = out / (a.name + ".png")
    pdf_path = out / (a.name + ".pdf")
    rmeta = {"cjk_family": fam, "cjk_file": ffile}
    if a.mirror_only:
        import mirror
        rmeta["png"] = mirror.render(sc, png_path, pdf_path, a.dpi, ffile, fam)
    else:
        for label, fn, dst in (("png", rendermod.svg_to_png, png_path), ("pdf", rendermod.svg_to_pdf, pdf_path)):
            try:
                rmeta[label] = {"engine": fn(svg_path, dst, a.dpi) if label == "png" else fn(svg_path, dst)}
            except Exception as e:
                rmeta[label] = {"error": str(e)}
        if "error" in rmeta.get("png", {}) or "error" in rmeta.get("pdf", {}):
            try:
                import mirror
                rmeta["mirror"] = mirror.render(sc, png_path, pdf_path, a.dpi, ffile, fam)
            except Exception as e:
                rmeta["mirror"] = {"error": str(e)}
        if a.preview:
            pv_path = Path(a.preview)
            pv_path.parent.mkdir(parents=True, exist_ok=True)
            pv_dpi = min(int(a.preview_dpi or 96), 108)
            try:
                rmeta["preview"] = {"path": str(pv_path), "dpi": pv_dpi,
                                    "engine": rendermod.svg_to_png(svg_path, pv_path, pv_dpi)}
            except Exception as e:
                rmeta["preview"] = {"error": str(e)}
    (out / "render_meta.json").write_text(json.dumps(rmeta, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "checks_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    sc2 = {k: v for k, v in sc.items() if k != "prims"}
    sc2["prims"] = [{k: v for k, v in p.items() if not k.startswith("_")} for p in sc["prims"]]
    (out / "scene.json").write_text(json.dumps(sc2, ensure_ascii=False, indent=1), encoding="utf-8")
    import build as buildmod
    prov_rows = buildmod.provenance_table(sc)
    (out / "provenance.json").write_text(json.dumps({
        "case_id": a.case_id, "table": prov_rows,
        "note": "每个图面元素对应一条材料原文短摘录与定位；可直接人工比对核验"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    res_dst = a.result_out or a.result_skel
    unfilled = None
    if res_dst:
        unfilled = _skel(a, rep, rmeta, Path(res_dst), Path(a.contract) if a.contract else None, prov_rows, sird=sird)
    out_msg = {"ok": rep["ok"], "canvas": rep["summary"]["canvas"],
               "errors": len(rep["errors"]), "warns": len(rep["warns"]),
               "png": str(png_path), "svg": str(svg_path), "render": rmeta}
    if a.preview:
        out_msg["preview"] = str(a.preview)
    if unfilled is not None:
        out_msg["unfilled_contract_fields"] = unfilled
    if a.result_out:
        import audit_delivery as auditmod
        out_msg["audit"] = auditmod.audit(Path(a.result_out).parent, a.contract)
    print(json.dumps(out_msg, ensure_ascii=False, indent=1))
    return 0 if rep["ok"] else 3


def _smart_fill(key, a, stem=None):
    """仅对无歧义的文件路径/状态标识字段自动映射，绝不覆盖需科学判断的语义字段（如 source_evidence/figure_caption）。"""
    st = stem or a.name
    k = str(key).strip().lower()
    if k in ("case_id", "id"):
        return a.case_id or "CASE_ID"
    if k in ("status", "run_status"):
        return "ok"
    if k in ("editable_svg", "svg", "svg_file", "svg_path", "output_svg", "editable_source", "editable_source_path", "editable_source_file", "source_svg", "source_svg_path", "figure_svg", "figure_file"):
        return "%s.svg" % st
    if k in ("png", "png_file", "png_path", "preview_png", "rendered_png", "rendered_image", "output_png", "export_png", "figure_png", "image_path", "image_file"):
        return "%s.png" % st
    if k in ("pdf", "pdf_file", "pdf_path", "output_pdf", "rendered_pdf", "export_pdf", "figure_pdf", "vector_pdf"):
        return "%s.pdf" % st
    if k in ("provenance_file", "provenance_path", "provenance_json", "provenance_report"):
        return "provenance.json"
    if k in ("checks_report", "check_report", "checks_file", "export_check", "export_checks", "quality_check", "quality_report"):
        return "checks_report.json"
    if k in ("render_meta", "export_meta"):
        return "render_meta.json"
    if k.endswith("_svg") or k.endswith("_svg_path"):
        return "%s.svg" % st
    if k.endswith("_png") or k.endswith("_png_path"):
        return "%s.png" % st
    if k.endswith("_pdf") or k.endswith("_pdf_path"):
        return "%s.pdf" % st
    return None


def _skel(a, rep, rmeta, path, contract_path=None, prov_rows=None, sird=None, multi_count=0):
    sird = sird or {}
    stem = ("%s_1" % a.name) if multi_count else a.name
    contract = {}
    cid_eff = a.case_id
    if contract_path and contract_path.exists():
        try:
            import audit_delivery as auditmod
            cj = json.loads(contract_path.read_text(encoding="utf-8"))
            if not cid_eff and cj.get("case_id"):
                cid_eff = str(cj["case_id"])
            for ks in auditmod._extract_contract_keys(cj):
                fill = _smart_fill(ks, a, stem=stem)
                contract[ks] = fill if fill else "<待填：按 case.json 契约填写>"
        except Exception:
            contract = {}
    src_locs = []
    for row in (prov_rows or []):
        loc = str(row.get("loc") or "").strip()
        if loc and loc not in src_locs:
            src_locs.append(loc)
    unc = [w for w in rep.get("warns", [])][:10]
    for u in (sird.get("uncertainty") or []):
        if str(u) not in unc:
            unc.append(str(u))
    title_s = str(sird.get("title") or a.name).strip()[:80]
    if multi_count:
        detail_s = "Built multi-figure set '%s' (%d figures, %d grounded elements from %s) as layered SVG + %ddpi PNG/PDF." % (
            title_s, multi_count, len(prov_rows or []), ", ".join(src_locs[:4]) or "source SIR", a.dpi
        )
    else:
        summ = rep.get("summary") or {}
        detail_s = "Built %s '%s' (%d nodes/phases, %d links, %s provenance from %s) as layered SVG + %ddpi PNG/PDF." % (
            summ.get("kind") or sird.get("kind") or "diagram", title_s,
            int(summ.get("nodes") or 0), int(summ.get("links") or 0),
            summ.get("provenance") or "100%", ", ".join(src_locs[:4]) or "source SIR", a.dpi
        )
    sk = {
        "case_id": cid_eff or "CASE_ID",
        "status": "ok" if rep["ok"] else "partial",
        "deliverables": {
            "editable_source": {"path": stem + ".svg", "format": "svg", "layers": ["frame", "nodes", "links", "labels", "legend", "footer"]},
            "exports": [{"path": stem + ".png", "format": "png", "dpi": a.dpi},
                        {"path": stem + ".pdf", "format": "pdf"}],
            "provenance": "逐元素来源见 SVG data-prov/data-prov-loc 属性与 provenance.json",
            "provenance_table": prov_rows or [],
        },
        "sources": src_locs or ["provenance.json"],
        "checks": rep,
        "render": rmeta,
        "output_contract": contract,
        "output_contract_fields": list(contract.keys()),
        "uncertainty": unc,
        "change_records": [{"action": "generate", "target": stem + ".svg", "detail": detail_s}],
    }
    if multi_count:
        sk["deliverables"]["manifest"] = a.name + "_manifest.json"
    for k in list(contract.keys()):
        if "status" in str(k).lower():
            contract[k] = sk["status"]
        if k not in sk:
            sk[k] = contract[k]
    explicit_rf = sird.get("result_fields") if isinstance(sird.get("result_fields"), dict) else {}
    for k, v in explicit_rf.items():
        sk[k] = v
        if k in contract:
            contract[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if isinstance(existing, dict):
        old_oc = existing.get("output_contract") if isinstance(existing.get("output_contract"), dict) else {}
        for k, v in list(contract.items()):
            if k not in explicit_rf and isinstance(v, str) and "<待填" in v:
                prev = old_oc.get(k) if k in old_oc else existing.get(k)
                if prev not in (None, "") and not (isinstance(prev, str) and "<待填" in prev):
                    contract[k] = prev
                    sk[k] = prev
        if existing.get("output_contract_fields"):
            sk["output_contract_fields"] = existing["output_contract_fields"]
    unfilled = [k for k, v in contract.items() if isinstance(v, str) and "<待填" in v]
    path.write_text(json.dumps(sk, ensure_ascii=False, indent=1), encoding="utf-8")
    return unfilled


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print(json.dumps({"ok": False, "stage": "pipeline_crash"}), file=sys.stderr)
        sys.exit(4)
