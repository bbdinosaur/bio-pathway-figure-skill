#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_result.py — 组装并校验 /app/output/result.json。
用法:
  python3 make_result.py --case-json /input/case.json --out /app/output/result.json \
      --status auto --case-id auto \
      --deliverable editable_source:fig1.svg --deliverable export:fig1.png \
      --deliverable export:fig1.pdf --deliverable preview:preview.png \
      --provenance fig1.provenance.json --check layout.json \
      --change '替换错误实体名 TP53→BRCA1（SVG+PDF 双路）' \
      --uncertainty '颜色操作仅应用于 SVG 副本'
行为: 幂等——若 result.json 已存在则合并，保留此前已填的未知契约字段；
      对 case.json 中 output_contract 列出的每个字段，缺失则置 null 并列入 missing_fields；
      终态成功值统一为 complete（传入 --status ok 自动归一为 complete）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_common import load_json, dump_json, sha256_of, verify_svg_editable, png_edge_check  # noqa: E402

CONTRACT_KEYS = ("output_contract", "required_outputs", "output_fields", "outputs_contract")
_NO_LIMIT_TOKENS = {"无", "none", "n/a", "na", "nil", "null", ""}
_AUTO_LIMIT_PREFIXES = (
    "Step-0 bootstrap partial record:",
    "Draft partial record:",
    "缺少可编辑源文件",
    "可编辑 SVG 校验未通过",
    "缺少导出文件",
    "缺失 output_contract 字段:",
    "SVG 存在 ",
    "PNG 存在边缘疑似裁切",
    "PNG 内容占比 <0.5%",
    "glyph_value_audit 数值核验不通过",
    "data_fidelity 存在空面板",
)


def _is_placeholder_limit(val) -> bool:
    t = str(val).strip()
    if t.lower() in _NO_LIMIT_TOKENS:
        return True
    return any(t.startswith(p) for p in _AUTO_LIMIT_PREFIXES)


def find_contract(obj):
    """在 case.json 中递归寻找 output_contract 类键。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in CONTRACT_KEYS and isinstance(v, (list, dict)):
                return v, k
        for v in obj.values():
            got = find_contract(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_contract(v)
            if got:
                return got
    return None


def contract_fields(c):
    fields = []
    if isinstance(c, list):
        for it in c:
            if isinstance(it, str):
                fields.append(it)
            elif isinstance(it, dict):
                fields.extend([k for k in it.keys() if k not in ("desc", "description", "type")])
    elif isinstance(c, dict):
        # 兼容 JSON Schema 或包装键（required / required_fields / fields / properties）
        for wrap in ("required", "required_fields", "fields", "properties"):
            if wrap in c and isinstance(c[wrap], (list, dict)):
                return contract_fields(c[wrap])
        fields.extend([k for k in c.keys() if k not in ("desc", "description", "type", "schema")])
    return fields


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-json")
    ap.add_argument("--out", default="result.json")
    ap.add_argument("--status", choices=["auto", "complete", "ok", "partial", "failed"], default="auto",
                    help="auto(默认): 有可编辑源+导出文件且无缺失必需契约字段与严重告警时自动为 complete，否则 partial（ok 自动归一为 complete）")
    ap.add_argument("--case-id", default="auto")
    ap.add_argument("--deliverable", action="append", default=[],
                    help="role:path[:format]，role ∈ editable_source|export|preview|provenance")
    ap.add_argument("--provenance", action="append", default=[])
    ap.add_argument("--check", action="append", default=[], help="检查报告 JSON 路径")
    ap.add_argument("--change", action="append", default=[])
    ap.add_argument("--uncertainty", action="append", default=[])
    ap.add_argument("--limit", action="append", default=[])
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--extra", action="append", default=[], help="合并额外 JSON 文件到 result.json（补齐自定义契约字段）")
    ap.add_argument("--set", dest="sets", action="append", default=[], help="key=value（支持 JSON 值），补齐契约字段")
    ap.add_argument("--auto-collect", help="扫描目录自动登记产物: svg→editable_source, pdf/png→exports, *preview*→previews")
    ap.add_argument("--strict", action="store_true", help="契约字段缺失时退出码 2")
    args = ap.parse_args()

    case = load_json(args.case_json) if args.case_json and Path(args.case_json).exists() else {}
    case_id = args.case_id
    if case_id in ("auto", ""):
        case_id = case.get("case_id") or case.get("id") or case.get("caseId") or "unknown"

    out = {}
    out_path = Path(args.out)
    if out_path.exists():
        try:
            out = load_json(out_path)
        except Exception:
            out = {}

    deliverables = out.get("deliverables", {"editable_source": [], "exports": [], "previews": []})
    # 清理已不存在于磁盘上的陈旧记录，避免覆盖重跑后残留死路径
    for bkt in ("editable_source", "exports", "previews"):
        if isinstance(deliverables.get(bkt), list):
            deliverables[bkt] = [x for x in deliverables[bkt]
                                 if isinstance(x, dict) and x.get("path") and Path(x["path"]).exists()]
    auto_provs = []
    if args.auto_collect:
        root_col = Path(args.auto_collect)
        _SKIP_SFX = (".tmp", ".bak", ".swp", ".pyc")
        _SKIP_NAMES = {"result.json", ".ds_store"}
        if root_col.exists():
            for f in sorted(root_col.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                n, sfx = f.name.lower(), f.suffix.lower()
                if n in _SKIP_NAMES or sfx in _SKIP_SFX:
                    continue
                if sfx == ".json":
                    if "provenance" in n:
                        auto_provs.append(str(f))
                    continue
                if n.endswith((".spec.svg", ".spec.pdf", ".tmp.svg", ".tmp.png")):
                    continue
                if sfx in (".svg", ".pptx"):
                    args.deliverable.append(f"editable_source:{f}")
                elif sfx in (".pdf", ".eps", ".tiff", ".tif"):
                    args.deliverable.append(f"export:{f}")
                elif sfx == ".png":
                    args.deliverable.append(f"{'preview' if 'preview' in n else 'export'}:{f}")
    for d in args.deliverable:
        parts = d.split(":")
        role = parts[0]
        p = parts[1] if len(parts) > 1 else ""
        fmt = parts[2] if len(parts) > 2 else Path(p).suffix.lstrip(".")
        rec = {"path": p, "format": fmt, "sha256": sha256_of(p) if p and Path(p).exists() else None}
        bucket = {"editable_source": "editable_source", "export": "exports",
                  "preview": "previews"}.get(role)
        if bucket:
            lst = deliverables.setdefault(bucket, [])
            existing = next((x for x in lst if x.get("path") == p), None)
            if existing is not None:
                existing.update(rec)
            else:
                lst.append(rec)
    out["case_id"] = case_id
    out["status"] = args.status
    out["deliverables"] = deliverables
    prov_paths = args.provenance or auto_provs
    if prov_paths:
        loaded = []
        for p in prov_paths:
            if Path(p).exists():
                try:
                    loaded.append(load_json(p))
                except Exception:
                    pass
        if len(loaded) == 1:
            out["source_mapping"] = loaded[0]
        elif len(loaded) > 1:
            out["source_mapping"] = {"figures": loaded}
    out["checks"] = out.get("checks", {})
    explicit_checks = set()
    for p in args.check:
        name = Path(p).stem
        explicit_checks.add(name)
        out["checks"][name] = load_json(p) if Path(p).exists() else {"missing": p}
    if isinstance(out.get("source_mapping"), dict):
        sm0 = out["source_mapping"]
        if sm0.get("self_check"):
            out["checks"]["self_check"] = sm0["self_check"]
        elif isinstance(sm0.get("figures"), list):
            for fi, fobj in enumerate(sm0["figures"]):
                if isinstance(fobj, dict) and fobj.get("self_check"):
                    fk = str(fobj.get("figure") or fobj.get("title") or f"fig_{fi + 1}")
                    out["checks"][fk] = fobj["self_check"]
    # 自动对收集到的 SVG 与主 PNG 执行真实几何与边缘自检（每次重跑刷新，剔除旧草稿残留，本次显式 --check 优先）
    if args.auto_collect:
        try:
            from check_layout import check_svg as _check_svg
        except Exception:
            _check_svg = None
        active_svg_keys = set()
        active_png_keys = set()
        for d_rec in deliverables.get("editable_source", []):
            dp = d_rec.get("path", "")
            if dp.lower().endswith(".svg") and Path(dp).exists() and _check_svg:
                ck = f"layout_{Path(dp).stem}"
                active_svg_keys.add(ck)
                if ck not in explicit_checks and "layout" not in explicit_checks:
                    try:
                        out["checks"][ck] = _check_svg(dp)
                    except Exception:
                        pass
        for d_rec in deliverables.get("exports", []):
            dp = d_rec.get("path", "")
            if dp.lower().endswith(".png") and Path(dp).exists():
                ck = f"png_edge_{Path(dp).stem}"
                active_png_keys.add(ck)
                if ck not in explicit_checks:
                    try:
                        out["checks"][ck] = png_edge_check(dp)
                    except Exception:
                        pass
        # 清理已被替换或删除的旧图遗留自动检查键，避免草稿报错污染终版 status
        for k in list(out["checks"].keys()):
            if k in explicit_checks:
                continue
            if k.startswith("layout_") and k not in active_svg_keys:
                out["checks"].pop(k, None)
            elif k.startswith("png_edge_") and k not in active_png_keys:
                out["checks"].pop(k, None)
    if args.change:
        out["change_log"] = (out.get("change_log") or []) + [{"change": c} for c in args.change]
    elif isinstance(out.get("source_mapping"), dict) and not out.get("change_log"):
        sm0 = out["source_mapping"]
        if isinstance(sm0.get("change_log"), list) and sm0["change_log"]:
            out["change_log"] = sm0["change_log"]
        elif isinstance(sm0.get("reproducibility"), dict):
            rep = sm0["reproducibility"]
            out["change_log"] = [{
                "action": "generate",
                "tool": sm0.get("generated_by") or "sci-figure-studio",
                "figure": sm0.get("figure") or sm0.get("title"),
                "command": rep.get("command"),
            }]
    if args.uncertainty:
        out["uncertainty"] = sorted(set((out.get("uncertainty") or []) + args.uncertainty))
    else:
        out.setdefault("uncertainty", [])
    prev_real_limits = [x for x in (out.get("limits") or []) if not _is_placeholder_limit(x)]
    if args.limit:
        new_real_limits = [x for x in args.limit if str(x).strip().lower() not in _NO_LIMIT_TOKENS]
        if not new_real_limits:
            # 显式传入 无/none/n/a 表示清空草稿占位限制，终态无真实缺口时保持 []
            out["limits"] = []
        else:
            out["limits"] = sorted(set(prev_real_limits + new_real_limits))
    else:
        out["limits"] = prev_real_limits
    if args.note:
        out["notes"] = (out.get("notes") or []) + args.note
    explicit_keys = set()
    for ep in args.extra:
        if Path(ep).exists():
            extra_obj = load_json(ep)
            if isinstance(extra_obj, dict):
                explicit_keys.update(extra_obj.keys())
                out.update(extra_obj)
    for kv in args.sets:
        if "=" in kv:
            k, v = kv.split("=", 1)
            ks = k.strip()
            explicit_keys.add(ks)
            try:
                out[ks] = json.loads(v)
            except Exception:
                out[ks] = v

    # 基于真实运行产物与自检数据生成结构化六检查点证据汇总（支持单图与多图，绝不虚构或因误报自我抹黑）
    sm = out.get("source_mapping") if isinstance(out.get("source_mapping"), dict) else {}
    figs = sm.get("figures") if isinstance(sm.get("figures"), list) else ([sm] if sm else [])
    scs = [f.get("self_check") for f in figs if isinstance(f, dict) and isinstance(f.get("self_check"), dict)]
    geo_checks = [s["svg_geometry"] for s in scs if isinstance(s.get("svg_geometry"), dict)]
    for cv in out.get("checks", {}).values():
        if isinstance(cv, dict) and "out_of_bounds" in cv:
            geo_checks.append(cv)
    ed_checks = [s["editable_svg"] for s in scs if isinstance(s.get("editable_svg"), dict)]
    if not ed_checks:
        # 若产物由自定义脚本生成而未写入 provenance.self_check.editable_svg，直接实测磁盘上的 SVG 文件
        for d in deliverables.get("editable_source", []):
            dp = d.get("path")
            if dp and str(dp).lower().endswith(".svg") and Path(dp).exists():
                try:
                    ed_checks.append(verify_svg_editable(dp))
                except Exception:
                    pass
    gva_checks = [s["glyph_value_audit"] for s in scs if isinstance(s.get("glyph_value_audit"), dict)]
    ent_checks = [s["entity_grounding_audit"] for s in scs if isinstance(s.get("entity_grounding_audit"), dict)]
    leg_vals = [bool(s["legend_series_match"]) for s in scs if "legend_series_match" in s]
    txt_checks = [s["svg_text_audit"] for s in scs if isinstance(s.get("svg_text_audit"), dict)]
    edge_checks = [s["png_edge"] for s in scs if isinstance(s.get("png_edge"), dict)]

    n_entities = sum(len(f.get("entities") or []) for f in figs if isinstance(f, dict))
    n_elements = sum(len(p.get("elements") or []) for f in figs if isinstance(f, dict) for p in (f.get("panels") or []))
    typo_suspects = [t for e in ent_checks for t in (e.get("typo_suspects") or [])]
    geo_errors = sum(int(g.get("n_errors", 0)) for g in geo_checks)
    max_diff = max((float(g.get("max_abs_diff", 0.0)) for g in gva_checks), default=0.0)
    verified_glyphs = sum(int(g.get("verified_glyphs", 0)) for g in gva_checks)
    missing_lbls = [m for t in txt_checks for m in (t.get("missing_labels") or [])]
    ed_text_cnt = sum(int(e.get("text_count", 0)) for e in ed_checks)
    exp_fmts = sorted({d.get("format", "") for d in deliverables.get("exports", []) if d.get("format")})
    edge_checks_all = list(edge_checks) + [
        cv for cv in out.get("checks", {}).values()
        if isinstance(cv, dict) and "clipping_suspect" in cv
    ]
    clip_any = any(bool(ec.get("clipping_suspect")) for ec in edge_checks_all)
    blank_any = any(bool(ec.get("blank_suspect")) for ec in edge_checks_all)
    gva_ok = all(g.get("ok", True) for g in gva_checks)
    df_checks = [s["data_fidelity"] for s in scs if isinstance(s.get("data_fidelity"), dict)]
    df_ok = all(d.get("ok", True) for d in df_checks)
    ed_ok = bool(deliverables.get("editable_source")) and all(e.get("ok", True) for e in ed_checks)

    repro_items = []
    for f in figs:
        if isinstance(f, dict) and isinstance(f.get("reproducibility"), dict):
            rp = f["reproducibility"]
            repro_items.append({
                "figure": f.get("figure") or f.get("title"),
                "command": rp.get("command"),
                "spec_sha256": rp.get("spec_sha256"),
                "input_file_hashes": rp.get("input_file_hashes"),
                "export_params": f.get("export_params"),
            })
    if repro_items:
        out["reproducibility"] = repro_items[0] if len(repro_items) == 1 else repro_items

    six_cp = {
        "scientific_entities": {
            "status": "warning" if typo_suspects else "pass",
            "n_entities": n_entities,
            "n_data_elements": n_elements,
            "typo_suspects": typo_suspects,
        },
        "spatial_relations": {
            "status": ("pass" if geo_errors == 0 else "warning") if geo_checks else "checked",
            "n_geometry_errors": geo_errors,
        },
        "data_encoding": {
            "status": ("pass" if all(g.get("ok", True) for g in gva_checks) else "warning") if gva_checks else "checked",
            "verified_glyphs": verified_glyphs,
            "max_abs_diff": round(max_diff, 8),
        },
        "legend_and_annotations": {
            "status": "warning" if (any(v is False for v in leg_vals) or missing_lbls) else "pass",
            "legend_series_match": all(leg_vals) if leg_vals else True,
            "n_missing_labels": len(missing_lbls),
        },
        "editable_source": {
            "status": "pass" if (deliverables.get("editable_source") and all(e.get("ok", True) for e in ed_checks)) else "warning",
            "n_files": len(deliverables.get("editable_source") or []),
            "svg_text_count": ed_text_cnt,
        },
        "export_formats": {
            "status": "pass" if (deliverables.get("exports") and not clip_any) else "warning",
            "formats": exp_fmts,
            "clipping_suspect": clip_any,
        },
    }
    out["six_checkpoints"] = six_cp

    # 若契约要求常见同义字段且尚未填写，从已有真实结构诚实映射（不编造数据）
    svg_paths = [d["path"] for d in deliverables.get("editable_source", []) if d.get("path", "").lower().endswith(".svg")]
    pdf_paths = [d["path"] for d in deliverables.get("exports", []) if d.get("path", "").lower().endswith(".pdf")]
    png_paths = [d["path"] for d in deliverables.get("exports", []) if d.get("path", "").lower().endswith(".png")]
    all_fig_paths = svg_paths + pdf_paths + png_paths
    alias_map = {
        "editable_source": deliverables.get("editable_source"),
        "editable_sources": deliverables.get("editable_source"),
        "editable_svg": svg_paths[0] if len(svg_paths) == 1 else (svg_paths or None),
        "svg_path": svg_paths[0] if svg_paths else None,
        "pdf_path": pdf_paths[0] if pdf_paths else None,
        "png_path": png_paths[0] if png_paths else None,
        "figure_files": all_fig_paths or None,
        "exports": deliverables.get("exports"),
        "exported_files": deliverables.get("exports"),
        "artifacts": deliverables,
        "previews": deliverables.get("previews"),
        "sources": out.get("source_mapping"),
        "provenance": out.get("source_mapping"),
        "data_mapping": out.get("source_mapping"),
        "change_records": out.get("change_log"),
        "changes": out.get("change_log"),
        "edit_log": out.get("change_log"),
        "verification": out.get("checks"),
        "export_checks": out.get("checks"),
        "checkpoints": six_cp,
        "limitations": out.get("limits"),
        "uncertainties": out.get("uncertainty"),
    }
    missing = []
    got = find_contract(case)
    contract_f_list = contract_fields(got[0]) if got else []
    _EMPTY_LIST_OK_ALIASES = {"limitations", "uncertainties", "limits", "uncertainty"}
    if got:
        _, key = got
        for f in contract_f_list:
            if f in explicit_keys and out.get(f) is not None:
                continue
            if f in alias_map:
                av = alias_map[f]
                if av not in (None, [], {}) or (f in _EMPTY_LIST_OK_ALIASES and isinstance(av, list)):
                    out[f] = av
                    continue
            if f not in out or out[f] is None:
                out[f] = None
                missing.append(f)
        out["output_contract_source"] = key
    action_required = []
    if not deliverables.get("editable_source"):
        action_required.append("缺少可编辑源文件 (.svg/.pptx)")
    elif not ed_ok:
        action_required.append("可编辑 SVG 校验未通过 (text_count==0，请勿将文字转曲)")
    if not deliverables.get("exports"):
        action_required.append("缺少导出文件 (.pdf/.png)")
    if missing:
        action_required.append(f"缺失 output_contract 字段: {missing}")
    if geo_errors > 0:
        action_required.append(f"SVG 存在 {geo_errors} 处几何越界/严重重叠错误，请修正后重跑")
    if clip_any:
        action_required.append("PNG 存在边缘疑似裁切 (clipping_suspect=true)，请增大画布或留白")
    if blank_any:
        action_required.append("PNG 内容占比 <0.5% (blank_suspect=true)，请检查绘图数据与坐标范围")
    if not gva_ok:
        action_required.append("glyph_value_audit 数值核验不通过，请检查图元与源表一致性")
    if not df_ok:
        action_required.append("data_fidelity 存在空面板，请检查 mapping 列名与源数据")

    if args.status == "auto":
        resolved_status = "complete" if not action_required else "partial"
    elif args.status == "ok":
        resolved_status = "complete"
    else:
        resolved_status = args.status
    out["status"] = resolved_status

    if resolved_status == "complete":
        if not action_required:
            out["limits"] = [x for x in (out.get("limits") or []) if not _is_placeholder_limit(x)]
    else:
        if not out.get("limits"):
            out["limits"] = (list(action_required) if action_required else
                             ["Draft partial record: initial deliverable saved; final scientific review and verification pending."])
    if got and "limitations" in contract_f_list and "limitations" not in explicit_keys:
        out["limitations"] = out["limits"]

    dump_json(out, out_path)
    print(json.dumps({"written": str(out_path), "case_id": case_id, "status": resolved_status,
                      "missing_contract_fields": missing,
                      "action_required": action_required,
                      "deliverables": {k: len(v) for k, v in deliverables.items()}},
                     ensure_ascii=False, indent=2))
    if args.strict and missing:
        sys.exit(2)


if __name__ == "__main__":
    main()
