#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_delivery.py — 交付前一键核验（纯标准库）：检查 result.json 契约完整性、
无未填占位符、引用文件落盘非空、SVG 合法 XML 与可编辑 <text> 计数。

用法: python3 audit_delivery.py --out /app/output [--contract /input/case.json]
退出码: 0=全通过  1=存在必须修复的错误
"""
import argparse
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PLACEHOLDER_PAT = re.compile(r"(<待填|TODO_FILL|PLACEHOLDER|REPLACE_ME)", re.I)


def _png_size(path):
    try:
        hdr = Path(path).read_bytes()[:24]
        if len(hdr) == 24 and hdr[:8] == b"\x89PNG\r\n\x1a\n" and hdr[12:16] == b"IHDR":
            w, h = struct.unpack(">II", hdr[16:24])
            return int(w), int(h)
    except Exception:
        pass
    return None


def _iter_strings(obj, prefix=""):
    if isinstance(obj, str):
        yield prefix, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, "%s.%s" % (prefix, k) if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, "%s[%d]" % (prefix, i))


_META_KEYS = frozenset((
    "required_fields", "fields", "required", "properties", "type", "description",
    "title", "$schema", "schema", "schema_version", "version", "format", "notes",
    "rules", "additionalProperties", "required_files", "files", "artifacts",
    "result_file", "output_file", "output_dir", "deliverables_spec",
))


def _extract_contract_keys_typed(cj):
    """区分显式 schema 必填键（strict）与松散描述字典键（soft），避免把说明性元字段误判为阻塞错误。"""
    c = cj.get("output_contract")
    if isinstance(c, dict) and isinstance(c.get("schema"), dict):
        c = c["schema"]
    strict, soft = [], []

    def _add(target, k):
        if isinstance(k, dict):
            k = k.get("name") or k.get("key") or k.get("field") or k.get("id")
        if not isinstance(k, str):
            return
        ks = k.strip()
        if ks and ks not in strict and ks not in soft:
            target.append(ks)

    if isinstance(c, dict):
        has_schema = False
        for list_k in ("required_fields", "fields", "required"):
            if isinstance(c.get(list_k), list):
                has_schema = True
                for item in c[list_k]:
                    _add(strict, item)
        if isinstance(c.get("properties"), dict):
            has_schema = True
            for k in c["properties"].keys():
                _add(strict, k)
        if not has_schema:
            for k in c.keys():
                if str(k) not in _META_KEYS:
                    _add(soft, k)
    elif isinstance(c, list):
        for item in c:
            _add(strict, item)
    return strict, soft


def _extract_contract_keys(cj):
    strict, soft = _extract_contract_keys_typed(cj)
    return strict + soft


def audit(out_dir, contract_path=None):
    out = Path(out_dir)
    errs, warns = [], []
    if not out.exists():
        return {"ok": False, "errors": ["输出目录不存在: %s" % out], "warns": [], "svgs": []}

    rj = out / "result.json"
    res = None
    if not rj.exists():
        errs.append("缺少 /app/output/result.json")
    else:
        try:
            res = json.loads(rj.read_text(encoding="utf-8"))
            if not isinstance(res, dict):
                errs.append("result.json 顶层必须是 JSON 对象")
                res = None
        except Exception as e:
            errs.append("result.json JSON 解析失败: %s" % e)

    if res is not None:
        for req in ("case_id", "status", "sources", "uncertainty", "change_records"):
            if req not in res:
                warns.append("result.json 缺少建议顶层字段: %s" % req)
        all_names = {f.name for f in out.rglob("*") if f.is_file()}
        for path_k, val in _iter_strings(res):
            if PLACEHOLDER_PAT.search(val):
                errs.append("result.json 含未替换占位符 %s = %r" % (path_k, val[:60]))
            if val.strip().startswith("Generated editable layered SVG") and path_k.startswith("change_records"):
                warns.append("result.json 的 %s 仍为默认脚本模板句，建议补充真实科学内容与修订依据" % path_k)
            # 检查相对/绝对交付件路径是否真实落盘
            if re.search(r"\.(svg|png|pdf|json)$", val.strip(), re.I) and " " not in val.strip() and not val.startswith("http"):
                if any(tok in path_k for tok in ("source_svg", "sources[", "diff.orig")):
                    continue
                p = Path(val.strip())
                cand = p if p.is_absolute() else (out / p)
                if not cand.exists() and p.exists():
                    cand = p
                if not cand.exists() and (out / p.name).exists():
                    cand = out / p.name
                if not cand.exists() and p.name not in all_names and not str(val).startswith("/input"):
                    warns.append("result.json 引用文件未在输出目录找到: %s (%s)" % (val, path_k))

        if contract_path and Path(contract_path).exists():
            try:
                cj = json.loads(Path(contract_path).read_text(encoding="utf-8"))
                cid = cj.get("case_id")
                if cid and str(res.get("case_id") or "") != str(cid):
                    errs.append("case_id 不一致: result=%r vs case.json=%r" % (res.get("case_id"), cid))
                strict_keys, soft_keys = _extract_contract_keys_typed(cj)
                oc_sub = res.get("output_contract") if isinstance(res.get("output_contract"), dict) else {}
                for k in strict_keys:
                    if k not in res and k not in oc_sub:
                        errs.append("result.json 缺少 output_contract 必填字段: %s" % k)
                for k in soft_keys:
                    if k not in res and k not in oc_sub:
                        warns.append("result.json 未包含 output_contract 参考字段: %s" % k)
            except Exception as e:
                warns.append("读取 contract 文件失败: %s" % e)

    svgs = []
    for f in sorted(out.rglob("*.svg")):
        rel = str(f.relative_to(out))
        sz = f.stat().st_size
        rec = {"file": rel, "bytes": sz}
        if sz < 200:
            errs.append("SVG 文件过小或为空: %s (%d B)" % (rel, sz))
        else:
            try:
                root = ET.parse(str(f)).getroot()
                n_txt = sum(1 for e in root.iter() if isinstance(e.tag, str) and e.tag.split("}")[-1] == "text")
                n_g = sum(1 for e in root.iter() if isinstance(e.tag, str) and e.tag.split("}")[-1] == "g")
                rec.update({"valid_xml": True, "viewBox": root.get("viewBox"), "text_nodes": n_txt, "groups": n_g})
                if n_txt == 0:
                    warns.append("SVG 未包含可编辑 <text> 节点: %s" % rel)
            except Exception as e:
                rec["valid_xml"] = False
                errs.append("SVG XML 解析失败 %s: %s" % (rel, e))
        svgs.append(rec)

    pngs = []
    for f in sorted(out.rglob("*.png")):
        rel = str(f.relative_to(out))
        if f.stat().st_size <= 200:
            errs.append("PNG 文件过小或为空: %s" % rel)
            continue
        wh = _png_size(f)
        if not wh:
            errs.append("PNG 文件头无效或损坏: %s" % rel)
            continue
        if wh[0] < 120 or wh[1] < 80:
            warns.append("PNG 像素尺寸过小: %s (%dx%d)" % (rel, wh[0], wh[1]))
        pngs.append({"file": rel, "width": wh[0], "height": wh[1], "bytes": f.stat().st_size})
    pdfs = [str(f.relative_to(out)) for f in sorted(out.rglob("*.pdf")) if f.stat().st_size > 200]
    if not svgs:
        errs.append("输出目录未找到可编辑 .svg 源文件")
    if not pngs:
        errs.append("输出目录未找到渲染预览 .png 文件")
    if not pdfs:
        warns.append("输出目录未找到矢量导出 .pdf 文件")

    # 检查输出目录内既有 checks 报告是否仍含未解决 error（仅告警，不因旧残余文件阻塞交付）
    for cf in sorted(out.rglob("*checks*.json")):
        try:
            cr = json.loads(cf.read_text(encoding="utf-8"))
            if isinstance(cr, dict) and isinstance(cr.get("errors"), list) and cr["errors"]:
                warns.append("%s 含 %d 项检查错误: %s" % (cf.name, len(cr["errors"]), str(cr["errors"][0])[:80]))
        except Exception:
            pass

    return {"ok": not errs, "errors": errs, "warns": warns,
            "svgs": svgs, "pngs": pngs, "pdfs": pdfs}


def main():
    ap = argparse.ArgumentParser(description="交付前核验 result.json 与图件完整性")
    ap.add_argument("--out", required=True, help="输出目录（如 /app/output）")
    ap.add_argument("--contract", default=None, help="case.json 路径")
    a = ap.parse_args()
    rep = audit(a.out, a.contract)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
