#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract.py — 工艺/装置文本 → SIR 草稿自动起草（启发式，产出必须人工/Agent 核对）。

用法: python3 extract.py --text methods.txt [--kind apparatus] [--out sir_draft.json]
识别（仅中文材料；英文材料请由 Agent 直接写 SIR）: ①器件实体（连接动词切分清洗 + 通名后缀）
②连接句式（A进入B / A后接B / A收集于B / A回流至B / A→B）。每条 node/link 带原句 quote 与行号 loc。
草稿仅是起点，引用关系必须核对。
"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import glyphs

DEV_SUF = r"(?:单元|器|瓶|泵|阀|塔|柱|罐|釜|槽|斗|机|仪|管|池|床)"
VERBS = ("泵入|输入|通入|送入|流入|进入|导出|后接|随后接入|再接|连接|连通|汇入|收集于|收集至|"
         "收集到|收集|回流至|回流到|回流|循环至|循环|排入|排至|排到|联动|回传|监测|称重|两台|一台|双台|经|由|"
         "从|以|用|将|把|先|随后|再|然后|两路|至|到|于")
VERB_RE = re.compile("(?:%s)" % VERBS)
UNIT_RE = re.compile(r"mL|min|℃|MPa|kPa|nm|°C|^[A-Za-z]{1,6}$")
DEV_SUF_NC_END = re.compile(r"(?:单元|器|瓶|泵|阀|塔|柱|罐|釜|槽|斗|机|仪|管|池|床)$")
TYPE_HINT = [("泵", "input"), ("瓶", "output"), ("检测|监测", "measure"), ("控制", "decision"),
             ("废", "waste"), ("收集", "output"), ("开始|起", "start"), ("结束|终点|成品", "end")]
CJK = r"\u4e00-\u9fff"
CONN = [
    (r"([%sA-Za-z0-9◆]{2,16}?)\s*(?:泵入|输入|通入|进入|送入|导入|流入)\s*([%sA-Za-z0-9◆]{2,14})" % (CJK, CJK), "material"),
    (r"([%sA-Za-z0-9]{2,14}?%s)\s*(?:后接|随后接入|再接|连接|连通|汇入)\s*([%sA-Za-z0-9]{2,14}?%s)" % (CJK, DEV_SUF, CJK, DEV_SUF), "material"),
    (r"([%sA-Za-z0-9◆]{2,16}?)\s*(?:收集于|收集至|收集到|汇入|排入|排至|排到)\s*([%sA-Za-z0-9◆]{2,14})" % (CJK, CJK), "material"),
    (r"([%sA-Za-z0-9]{2,14}?%s)\s*(?:回流|循环)\s*(?:至|到)\s*([%sA-Za-z0-9]{2,14}?%s)" % (CJK, DEV_SUF, CJK, DEV_SUF), "loop"),
]
ARROW = re.compile(r"([A-Za-z0-9%s]{1,12})\s*(?:→|->|—>)\s*([A-Za-z0-9%s]{1,12})" % (CJK, CJK))


def _type_of(name):
    for pat, t in TYPE_HINT:
        if re.search(pat, name):
            return t
    return "apparatus"


def _clean(seg):
    parts = [p.strip() for p in VERB_RE.split(seg) if p.strip()]
    name = parts[-1] if parts else seg.strip()
    name = name.strip("的，。、；()（） 　◆")
    if len(name) < 2 or UNIT_RE.search(name):
        return None
    return name


MASK_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mL/min|℃|MPa|kPa|nm|min|h|Hz|°C)")


def extract(text, kind="apparatus"):
    nodes, links = {}, []
    for ln_no, raw in enumerate(text.splitlines(), 1):
        s = MASK_RE.sub("◆", raw.strip())
        if not s:
            continue
        occs = [(m.start(), m.end(), m.group(0))
                for m in re.finditer(r"([%sA-Za-z0-9◆]{2,16}?)%s" % (CJK, DEV_SUF), s)]
        merged = []
        for st, en, nm in occs:
            if merged and st == merged[-1][1]:
                merged[-1] = (merged[-1][0], en, merged[-1][2] + nm)
            else:
                merged.append((st, en, nm))
        for _st, _en, raw_name in merged:
            parts = [q.strip() for q in VERB_RE.split(raw_name) if q.strip()]
            cands = [q for q in parts if len(q) >= 2 and DEV_SUF_NC_END.search(q)]
            if not cands and len(raw_name) <= 8:
                cands = [raw_name]
            if not cands:
                tail = _clean(raw_name[-9:])
                if tail and len(tail) >= 3 and DEV_SUF_NC_END.search(tail):
                    cands = [tail]
            for name in cands:
                name = name.strip("的，。、；()（） 　◆")
                if not name or len(name) < 2 or UNIT_RE.search(name) or name in nodes:
                    continue
                nodes[name] = {"id": "n%d" % (len(nodes) + 1), "label": name,
                               "type": _type_of(name),
                               "source": {"quote": raw.strip()[:80], "loc": "L%d" % ln_no}}
    absorb = [n for n in nodes if any(n in other and n != other for other in nodes)]
    for n in absorb:
        host = min((o for o in nodes if n in o and n != o), key=len)
        nodes[host]["source"] = nodes[host]["source"] or nodes[n]["source"]
        del nodes[n]
    for v in nodes.values():
        m = glyphs.match(v)
        if m:
            v["icon"] = m[0]
    id_of = {name: v["id"] for name, v in nodes.items()}

    STREAM_RE = re.compile(r"(料液|溶液|混合液|母液|滤液|湿品|产物|物料|样品|粗品|馏分)")
    stream_ids = {}

    def _stream_node(word, role):
        key = word
        if key not in stream_ids:
            nid = "s%d" % (len(stream_ids) + 1)
            nodes[key] = {"id": nid, "label": word, "type": "input" if role == "src" else "output",
                          "source": {"quote": "(流片语自动补充节点)", "loc": "-"}}
            id_of[key] = nid
            stream_ids[key] = nid
        nodes[key]["type"] = "input" if role == "src" else nodes[key].get("type", "output")
        if role == "tgt" and nodes[key]["type"] == "input":
            nodes[key]["type"] = "output"
        return stream_ids[key]

    def resolve(seg, role="src"):
        seg = seg.strip()
        if seg in id_of:
            return id_of[seg]
        for name in sorted(id_of, key=len, reverse=True):
            if name in seg or seg in name:
                return id_of[name]
        m = STREAM_RE.search(seg)
        if m:
            return _stream_node(m.group(1), role)
        return None

    for ln_no, raw in enumerate(text.splitlines(), 1):
        s = MASK_RE.sub("◆", raw.strip())
        for pat, kind_l in CONN:
            for m in re.finditer(pat, s):
                a = resolve(_clean(m.group(1)) or m.group(1), "src")
                b = resolve(m.group(2), "tgt")
                if a and b and a != b:
                    links.append({"from": a, "to": b, "kind": kind_l,
                                  "source": {"quote": s[:80], "loc": "L%d" % ln_no}})
        for m in ARROW.finditer(s):
            a, b = resolve(m.group(1), "src"), resolve(m.group(2), "tgt")
            if a and b and a != b:
                links.append({"from": a, "to": b, "kind": "material",
                              "source": {"quote": s[:80], "loc": "L%d" % ln_no}})
    seen, dedup = set(), []
    for e in links:
        key = (e["from"], e["to"], e["kind"])
        if key not in seen:
            seen.add(key)
            dedup.append(e)
    return {"kind": kind, "title": "SIR 草稿（extract.py 自动起草，需人工核对）",
            "subtitle": "由启发式抽取生成；每条带原句与行号，务必逐条核对后使用",
            "nodes": list(nodes.values()), "links": dedup,
            "prov_footer": "extract.py 启发式草稿；引用关系未经全文核对"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--kind", default="apparatus")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    text = Path(a.text).read_text(encoding="utf-8")
    sir = extract(text, a.kind)
    out = json.dumps(sir, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
