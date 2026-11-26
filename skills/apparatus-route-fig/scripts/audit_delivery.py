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
_TBD_PAT = re.compile(r"(?:\bTBD\b|待定)", re.I)
_AUTO_CR_PREFIXES = ("Built ", "Plotted ", "Composed ", "Generated ")


def _extract_tbd_items(obj, out_list, seen, limit=12):
    """从 SIR/chart spec 中提取真实待定参数（TBD/待定），绝不混入内部几何排版告警。"""
    if not isinstance(obj, dict) or len(out_list) >= limit:
        return

    def _add(msg):
        m = str(msg or "").strip()
        if m and m not in seen and len(out_list) < limit:
            seen.add(m)
            out_list.append(m)

    for key in ("subtitle", "note"):
        val = obj.get(key)
        if isinstance(val, str) and _TBD_PAT.search(val):
            _add("参数待定(TBD): %s=%s" % (key, val.strip()[:80]))

    for coll_k in ("nodes", "phases"):
        for item in (obj.get(coll_k) or []):
            if not isinstance(item, dict) or len(out_list) >= limit:
                continue
            iid = str(item.get("id") or item.get("label") or item.get("title") or coll_k)
            for fk in ("label", "title", "time", "deliverable", "note"):
                v = item.get(fk)
                if isinstance(v, str) and _TBD_PAT.search(v):
                    _add("参数待定(TBD): %s.%s (%s)" % (iid, fk, v.strip()[:60]))
            attrs = item.get("attrs")
            if isinstance(attrs, list):
                for av in attrs:
                    s = str(av or "").strip()
                    if _TBD_PAT.search(s):
                        _add("参数待定(TBD): %s (%s)" % (iid, s[:60]))
            elif isinstance(attrs, dict):
                for ak, av in attrs.items():
                    s = "%s=%s" % (ak, av)
                    if _TBD_PAT.search(s):
                        _add("参数待定(TBD): %s (%s)" % (iid, s[:60]))
            for tv in (item.get("tasks") or []):
                s = str(tv or "").strip()
                if _TBD_PAT.search(s):
                    _add("参数待定(TBD): %s (%s)" % (iid, s[:60]))

    for lk in (obj.get("links") or []):
        if not isinstance(lk, dict) or len(out_list) >= limit:
            continue
        for fk in ("label", "note"):
            v = lk.get(fk)
            if isinstance(v, str) and _TBD_PAT.search(v):
                _add("参数待定(TBD): %s->%s (%s)" % (lk.get("from", "?"), lk.get("to", "?"), v.strip()[:60]))


def collect_scientific_uncertainty(spec=None, data_mapping=None):
    """仅收集真实科学材料层面的不确定项（显式 uncertainty/conflicts、源表缺失/NA 剔除、TBD 待定参数），
    严禁将内部版式/几何检查 warns 写入 result.json.uncertainty。"""
    unc, seen = [], set()

    def _add(item):
        s = str(item or "").strip()
        if s and s not in seen:
            seen.add(s)
            unc.append(s)

    def _scan_spec(d):
        if not isinstance(d, dict):
            return
        for fk in ("uncertainty", "conflicts"):
            val = d.get(fk)
            if isinstance(val, list):
                for u in val:
                    _add(u)
            elif isinstance(val, str) and val.strip():
                _add(val)
        _extract_tbd_items(d, unc, seen)
        for sub_k in ("figures", "panels"):
            if isinstance(d.get(sub_k), list):
                for sub in d[sub_k]:
                    if isinstance(sub, dict):
                        _scan_spec(sub)
        if isinstance(d.get("rows"), list):
            for row in d["rows"]:
                if isinstance(row, list):
                    for sub in row:
                        if isinstance(sub, dict):
                            _scan_spec(sub)

    _scan_spec(spec)

    for m in (data_mapping or []):
        if not isinstance(m, dict):
            continue
        dm = int(m.get("dropped_missing") or 0)
        if dm > 0:
            plbl = str(m.get("panel") or "").strip()
            ptag = ("Panel %s " % plbl) if (plbl and plbl.lower() != "main") else ""
            sname = str(m.get("series") or "series")
            _add("%s%s: 源表剔除 %d 行缺失/NA 数值" % (ptag, sname, dm))
    return unc


def _cr_key(rec):
    if not isinstance(rec, dict):
        return None
    act = str(rec.get("action") or "").strip().lower()
    tgt = str(rec.get("target") or rec.get("target_id") or rec.get("id") or "").strip()
    return (act, tgt)


def _is_auto_change_record(rec):
    if not isinstance(rec, dict):
        return False
    if rec.get("auto") is True:
        return True
    act = str(rec.get("action") or "").strip().lower()
    if act not in ("generate", "generate_chart", "compose_panels"):
        return False
    extra = set(rec.keys()) - {"action", "target", "detail", "auto"}
    if extra:
        return False
    det = str(rec.get("detail") or "").strip()
    return any(det.startswith(p) for p in _AUTO_CR_PREFIXES)


def merge_change_records(old_records, new_records):
    """按 (action, target) 智能合并 change_records：保留非同目标前序记录及人工撰写的详细科学说明。"""
    old_list = old_records if isinstance(old_records, list) else []
    new_list = new_records if isinstance(new_records, list) else []
    new_keys = {_cr_key(r) for r in new_list if _cr_key(r) is not None}
    merged = []
    human_keys = set()

    for rec in old_list:
        k = _cr_key(rec)
        if k is None:
            if rec not in merged:
                merged.append(rec)
            continue
        if k not in new_keys:
            if rec not in merged:
                merged.append(rec)
        elif not _is_auto_change_record(rec):
            human_keys.add(k)
            if rec not in merged:
                merged.append(rec)

    for rec in new_list:
        k = _cr_key(rec)
        if k is not None and k in human_keys and _is_auto_change_record(rec):
            continue
        if rec not in merged:
            merged.append(rec)
    return merged


def merge_existing_result(sk, contract, explicit_rf, existing):
    """非覆盖合并已有 result.json：保留已填 output_contract、自定义顶层键、sources、uncertainty 与 change_records。"""
    if not isinstance(existing, dict):
        return sk
    explicit_rf = explicit_rf if isinstance(explicit_rf, dict) else {}
    old_oc = existing.get("output_contract") if isinstance(existing.get("output_contract"), dict) else {}

    if sk.get("case_id") in (None, "", "CASE_ID") and existing.get("case_id") not in (None, "", "CASE_ID"):
        sk["case_id"] = existing["case_id"]
        if "case_id" in contract and contract["case_id"] in (None, "", "CASE_ID"):
            contract["case_id"] = existing["case_id"]

    for k, v in list(contract.items()):
        if k not in explicit_rf and isinstance(v, str) and "<待填" in v:
            prev = old_oc.get(k) if k in old_oc else existing.get(k)
            if prev not in (None, "") and not (isinstance(prev, str) and "<待填" in prev):
                contract[k] = prev
                sk[k] = prev

    for ok_k, ok_v in old_oc.items():
        if ok_k not in contract and ok_v not in (None, "") and not (isinstance(ok_v, str) and "<待填" in ok_v):
            contract[ok_k] = ok_v
            if ok_k not in sk:
                sk[ok_k] = ok_v

    for k, v in existing.items():
        if k not in sk and k not in ("output_contract", "output_contract_fields"):
            sk[k] = v

    if isinstance(existing.get("sources"), list):
        for s_item in existing["sources"]:
            if s_item not in sk["sources"]:
                sk["sources"].append(s_item)

    if isinstance(existing.get("uncertainty"), list):
        for u_item in existing["uncertainty"]:
            if u_item not in sk["uncertainty"]:
                sk["uncertainty"].append(u_item)

    if isinstance(existing.get("change_records"), list):
        sk["change_records"] = merge_change_records(existing["change_records"], sk.get("change_records"))
        if "change_records" in contract:
            contract["change_records"] = sk["change_records"]

    if existing.get("output_contract_fields"):
        merged_ocf = list(existing["output_contract_fields"])
        for f in contract.keys():
            if f not in merged_ocf:
                merged_ocf.append(f)
        sk["output_contract_fields"] = merged_ocf
    return sk


def _png_info(path):
    """纯标准库读取 PNG 宽高与 pHYs DPI 元数据，返回 (w, h, dpi_x) 或 None。"""
    try:
        data = Path(path).read_bytes()
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            return None
        w, h = struct.unpack(">II", data[16:24])
        dpi_x = None
        pos = 8
        while pos + 12 <= len(data):
            clen = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            cend = pos + 12 + clen
            if cend > len(data):
                break
            if ctype == b"pHYs" and clen == 9:
                ppu_x, _ppu_y, unit = struct.unpack(">IIb", data[pos + 8:pos + 17])
                if unit == 1 and ppu_x > 0:
                    dpi_x = round(ppu_x * 0.0254, 1)
                break
            if ctype == b"IDAT":
                break
            pos = cend
        return int(w), int(h), dpi_x
    except Exception:
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
        info = _png_info(f)
        if not info:
            errs.append("PNG 文件头无效或损坏: %s" % rel)
            continue
        pw, ph, pdpi = info
        if pw < 120 or ph < 80:
            warns.append("PNG 像素尺寸过小: %s (%dx%d)" % (rel, pw, ph))
        if pdpi is not None and pdpi < 150 and "preview" not in rel.lower():
            warns.append("正式 PNG 分辨率偏低: %s (%.1f DPI < 150)" % (rel, pdpi))
        rec_p = {"file": rel, "width": pw, "height": ph, "bytes": f.stat().st_size}
        if pdpi is not None:
            rec_p["dpi"] = pdpi
        pngs.append(rec_p)
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
