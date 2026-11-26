#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sir.py — SIR（Structured Intermediate Representation，实体—连接—步骤—流向中间表示）
的样式常量、双语自适应（zh/en）、文本度量与结构校验。仅依赖 Python 标准库（可选 PIL 精确测量）。

SIR 顶层结构（详见 references/sir-spec.md）：
{
  "kind": "apparatus" | "flow" | "roadmap",
  "title": str, "subtitle": str?, "language": "zh" | "en"?,
  "nodes": [{id, label, type, attrs?, group?, icon?, layer?, zoom?, source:{quote, loc}?}, ...],
  "links": [{from, to, kind, label?, source?}, ...],
  "phases": [{id, name, duration?, goals?, methods?, milestones?, inputs?, outputs?, source?}, ...],
  "phase_links": [{from, to, kind: handoff|feedback, label?, source?}, ...],
  "legend_note": str?, "prov_footer": str?
}
"""
from __future__ import annotations
import unicodedata

# ---- 节点类型样式: type -> (fill, stroke, text_fill, shape, legend_zh, legend_en)
NODE_STYLES = {
    "apparatus": ("#EDF2F7", "#334E68", "#102A43", "rect", "装置/单元", "Apparatus / Unit"),
    "process":   ("#E8F1FB", "#2B6CB0", "#1A365D", "rect", "工艺步骤",  "Process Step"),
    "decision":  ("#FFF4E0", "#C05621", "#7B341E", "rect", "判定/分支", "Decision / Control"),
    "start":     ("#E6FFED", "#2F855A", "#22543D", "pill", "起点",      "Start"),
    "end":       ("#FED7D7", "#C53030", "#742A2A", "pill", "终点",      "End"),
    "input":     ("#F0FFF4", "#38A169", "#276749", "rect", "物料输入",  "Input / Sample"),
    "output":    ("#FAF5FF", "#6B46C1", "#44337A", "rect", "产物输出",  "Output / Product"),
    "waste":     ("#F7FAFC", "#718096", "#4A5568", "rect", "废料/排放", "Waste / Exhaust"),
    "storage":   ("#FEFCBF", "#B7791F", "#744210", "rect", "储存/缓冲", "Storage / Buffer"),
    "measure":   ("#EBFBFF", "#00838F", "#00363A", "rect", "检测/表征", "Measurement / Assay"),
    "phase":     ("#2B6CB0", "#1A365D", "#FFFFFF", "rect", "阶段",      "Phase"),
}

# ---- 连接类型样式: kind -> (color, dash, legend_zh, legend_en)
LINK_STYLES = {
    "material": ("#2B6CB0", None,  "物料流",      "Material / Flow"),
    "activate": ("#2F855A", None,  "激活/促进",   "Activation"),
    "inhibit":  ("#C53030", None,  "抑制/阻断",   "Inhibition / Block"),
    "energy":   ("#D69E2E", "8,3", "能量/光热流", "Energy / Optical"),
    "signal":   ("#805AD5", "6,4", "信号/控制",   "Signal / Control"),
    "data":     ("#2C7A7B", "2,4", "数据/信息流", "Data / Readout"),
    "loop":     ("#C05621", "7,4", "回流/循环",   "Recycle / Loop"),
    "handoff":  ("#2F855A", None,  "阶段交付",    "Phase Handoff"),
    "feedback": ("#C05621", "7,4", "反馈迭代",    "Feedback Loop"),
}

NODE_TYPE_SYNONYMS = {
    "sample": "input", "reagent": "input", "feed": "input", "source": "input", "stimulus": "input",
    "product": "output", "result": "output", "outcome": "output", "endpoint": "output",
    "assay": "measure", "sensor": "measure", "detector": "measure", "qc": "measure",
    "analysis": "measure", "characterization": "measure", "readout": "measure", "imaging": "measure",
    "equipment": "apparatus", "device": "apparatus", "instrument": "apparatus", "reactor": "apparatus", "unit": "apparatus",
    "pump": "apparatus", "valve": "apparatus", "mixer": "apparatus", "laser": "apparatus", "lamp": "apparatus",
    "heater": "apparatus", "furnace": "apparatus", "oven": "apparatus", "column": "apparatus", "filter": "apparatus",
    "separator": "apparatus", "centrifuge": "apparatus", "microscope": "apparatus", "spectrometer": "apparatus",
    "injector": "apparatus", "chamber": "apparatus", "chip": "apparatus", "module": "apparatus",
    "stage": "apparatus", "lens": "apparatus", "mirror": "apparatus", "beam_splitter": "apparatus",
    "controller": "decision", "gate": "decision", "branch": "decision", "checkpoint": "decision", "control": "decision",
    "buffer": "storage", "tank": "storage", "reservoir": "storage", "pool": "storage", "library": "storage",
    "exhaust": "waste", "effluent": "waste", "byproduct": "waste", "discard": "waste",
    "cell": "process", "tissue": "process", "treatment": "process", "step": "process", "intervention": "process",
    "receptor": "process", "protein": "process", "gene": "process", "pathway": "process", "cytokine": "process",
    "enzyme": "process", "ligand": "input", "drug": "input", "inhibitor": "input", "antibody": "input",
    "mice": "input", "mouse": "input", "patient": "input", "cohort": "input", "organoid": "input",
    "rna": "input", "dna": "input", "sirna": "input", "lnp": "input", "nanoparticle": "input",
    "elisa": "measure", "facs": "measure", "qpcr": "measure", "western": "measure", "ihc": "measure",
    "rna_seq": "measure", "scrna_seq": "measure", "flow_cytometry": "measure", "sequencing": "measure",
}

LINK_KIND_SYNONYMS = {
    "activation": "activate", "promote": "activate", "induce": "activate", "upregulate": "activate", "stimulate": "activate",
    "inhibition": "inhibit", "block": "inhibit", "suppress": "inhibit", "repression": "inhibit", "downregulate": "inhibit",
    "heat": "energy", "thermal": "energy", "optical": "energy", "laser": "energy", "light": "energy", "power": "energy", "electric": "energy",
    "info": "data", "information": "data", "readout": "data", "measurement": "data",
    "control": "signal", "regulation": "signal", "signaling": "signal",
    "recycle": "loop", "return": "loop", "iteration": "loop",
    "flow": "material", "reagent": "material", "sample": "material", "transfer": "material",
}


KIND_SYNONYMS = {
    "diagram": "flow", "schematic": "flow", "mechanism": "flow", "pathway": "flow",
    "workflow": "flow", "protocol": "flow", "pipeline": "flow", "process": "flow",
    "flowchart": "flow", "procedure": "flow",
    "setup": "apparatus", "equipment": "apparatus", "device": "apparatus",
    "system": "apparatus", "reactor": "apparatus", "instrument": "apparatus",
    "timeline": "roadmap", "milestones": "roadmap", "plan": "roadmap", "phases": "roadmap",
    "technical_route": "roadmap", "route": "roadmap",
}


def _norm_source(src):
    if isinstance(src, dict):
        return src
    if isinstance(src, str) and src.strip():
        return {"quote": src.strip(), "loc": ""}
    return {}


def _extract_prov(obj):
    """兼容 provenance / evidence / ref 作为 source 的别名。"""
    if isinstance(obj.get("source"), dict):
        return obj["source"]
    for alt in ("provenance", "evidence", "ref", "citation"):
        if obj.get(alt):
            return _norm_source(obj[alt])
    if isinstance(obj.get("source"), str) and obj["source"].strip():
        return _norm_source(obj["source"])
    return {}


def normalize_sir(sir):
    """原地规范化自然领域别名与常见图字段名，减少不必要 schema 报错重试。"""
    if not isinstance(sir, dict):
        return sir
    if not sir.get("kind") and isinstance(sir.get("type"), str):
        sir["kind"] = sir["type"]
    k0 = str(sir.get("kind") or "").strip().lower()
    if k0 in KIND_SYNONYMS:
        sir["kind"] = KIND_SYNONYMS[k0]
    if not sir.get("links") and isinstance(sir.get("edges"), list):
        sir["links"] = sir["edges"]
    if not sir.get("phases") and isinstance(sir.get("stages"), list):
        sir["phases"] = sir["stages"]
    if sir.get("kind") == "roadmap" and not sir.get("phase_links"):
        if isinstance(sir.get("stage_links"), list):
            sir["phase_links"] = sir["stage_links"]
        elif isinstance(sir.get("links"), list):
            sir["phase_links"] = sir["links"]
    node_ids = set()
    for n in sir.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if not n.get("label"):
            for alt in ("name", "title", "text"):
                if n.get(alt):
                    n["label"] = str(n[alt])
                    break
        if n.get("id"):
            node_ids.add(str(n["id"]))
        if "source" not in n or not isinstance(n.get("source"), dict):
            pv = _extract_prov(n)
            if pv:
                n["source"] = pv
        t = str(n.get("type") or "").strip().lower()
        if t in NODE_TYPE_SYNONYMS:
            n["type"] = NODE_TYPE_SYNONYMS[t]
        raw_a = n.get("attrs")
        if isinstance(raw_a, list):
            ad = {}
            for idx_a, av in enumerate(raw_a, 1):
                if isinstance(av, dict):
                    for ak, av2 in av.items():
                        ad[str(ak).strip()] = str(av2).strip()
                else:
                    s_av = str(av or "").strip()
                    if not s_av:
                        continue
                    if ":" in s_av:
                        ak, av2 = s_av.split(":", 1)
                    elif "：" in s_av:
                        ak, av2 = s_av.split("：", 1)
                    elif "=" in s_av:
                        ak, av2 = s_av.split("=", 1)
                    else:
                        ak, av2 = "Param %d" % idx_a, s_av
                    ak = ak.strip() or ("Param %d" % idx_a)
                    if ak in ad:
                        ak = "%s (%d)" % (ak, idx_a)
                    ad[ak] = av2.strip()
            n["attrs"] = ad
        elif isinstance(raw_a, str) and raw_a.strip():
            n["attrs"] = {"Note": raw_a.strip()}
    for e in sir.get("links") or []:
        if not isinstance(e, dict):
            continue
        if not e.get("from"):
            for alt in ("from_id", "src"):
                if e.get(alt):
                    e["from"] = str(e[alt])
                    break
            if not e.get("from") and isinstance(e.get("source"), str) and e["source"] in node_ids:
                e["from"] = e["source"]
                e.pop("source", None)
        if not e.get("to"):
            for alt in ("to_id", "dst", "target"):
                if e.get(alt):
                    e["to"] = str(e[alt])
                    break
        if "source" not in e or not isinstance(e.get("source"), dict):
            pv = _extract_prov(e)
            if pv:
                e["source"] = pv
        k = str(e.get("kind") or e.get("type") or "").strip().lower()
        if k in LINK_KIND_SYNONYMS:
            e["kind"] = LINK_KIND_SYNONYMS[k]
        elif k in LINK_STYLES and not e.get("kind"):
            e["kind"] = k
        if e.get("bidirectional") and not e.get("bidir"):
            e["bidir"] = True
    phase_ids = set()
    for p in sir.get("phases") or []:
        if not isinstance(p, dict):
            continue
        if not p.get("name"):
            for alt in ("label", "title"):
                if p.get(alt):
                    p["name"] = str(p[alt])
                    break
        if p.get("id"):
            phase_ids.add(str(p["id"]))
        if not p.get("methods"):
            for alt in ("steps", "items"):
                if isinstance(p.get(alt), list):
                    p["methods"] = p[alt]
                    break
        if not p.get("milestones") and p.get("milestone"):
            mv = p["milestone"]
            p["milestones"] = mv if isinstance(mv, list) else [str(mv)]
        if not p.get("goals") and p.get("goal"):
            gv = p["goal"]
            p["goals"] = gv if isinstance(gv, list) else [str(gv)]
        if "source" not in p or not isinstance(p.get("source"), dict):
            pv = _extract_prov(p)
            if pv:
                p["source"] = pv
    for e in sir.get("phase_links") or []:
        if not isinstance(e, dict):
            continue
        if not e.get("from"):
            for alt in ("from_id", "src"):
                if e.get(alt):
                    e["from"] = str(e[alt])
                    break
            if not e.get("from") and isinstance(e.get("source"), str) and e["source"] in phase_ids:
                e["from"] = e["source"]
                e.pop("source", None)
        if not e.get("to"):
            for alt in ("to_id", "dst", "target"):
                if e.get(alt):
                    e["to"] = str(e[alt])
                    break
        if "source" not in e or not isinstance(e.get("source"), dict):
            pv = _extract_prov(e)
            if pv:
                e["source"] = pv
    return sir

PALETTE6 = ["#2B6CB0", "#2C7A7B", "#6B46C1", "#C05621", "#2F855A", "#B83280"]


def detect_lang(sird):
    """返回 'en' 或 'zh'。优先显式 language 字段，否则按内容中 CJK 字符存在性自动推断。"""
    lang = str((sird or {}).get("language") or "").strip().lower()
    if lang.startswith("en"):
        return "en"
    if lang.startswith("zh") or lang.startswith("cn"):
        return "zh"
    buf = [str((sird or {}).get("title") or "")]
    for n in (sird or {}).get("nodes") or []:
        buf.append(str(n.get("label") or ""))
    for p in (sird or {}).get("phases") or []:
        buf.append(str(p.get("name") or ""))
    text = "".join(buf)
    cjk = sum(1 for ch in text if unicodedata.east_asian_width(ch) in ("W", "F"))
    return "zh" if cjk >= 2 else "en"


def node_legend(ntype, lang="zh"):
    st = NODE_STYLES.get(ntype, NODE_STYLES["process"])
    return st[5] if lang == "en" else st[4]


def link_legend(lkind, lang="zh"):
    ls = LINK_STYLES.get(lkind, LINK_STYLES["material"])
    return ls[3] if lang == "en" else ls[2]


# ---------------- 文本度量（优先 PIL 精确测量，字体路径与字号全局 dict 缓存） ----------------
_FONT_FILE_RESOLVED = False
_FONT_FILE_CACHE = None
_PIL_FONT_CACHE = {}


def _resolve_font_file():
    global _FONT_FILE_RESOLVED, _FONT_FILE_CACHE
    if not _FONT_FILE_RESOLVED:
        _FONT_FILE_RESOLVED = True
        try:
            import render as _r
            fam, ffile = _r.detect_cjk()
            _FONT_FILE_CACHE = ffile or (_r.font_file_for(fam) if fam else None)
        except Exception:
            _FONT_FILE_CACHE = None
    return _FONT_FILE_CACHE


def _pil_font(fs):
    """按字号缓存 PIL ImageFont，避免重复调用 fc-list。"""
    key = max(int(round(fs)), 8)
    if key in _PIL_FONT_CACHE:
        return _PIL_FONT_CACHE[key]
    try:
        from PIL import ImageFont
        f = _resolve_font_file()
        if not f:
            _PIL_FONT_CACHE[key] = None
            return None
        font = ImageFont.truetype(f, key)
        _PIL_FONT_CACHE[key] = font
        return font
    except Exception:
        _PIL_FONT_CACHE[key] = None
        return None


def _char_w(ch, fs):
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return fs * 1.02
    if ch in "iljItf.,:;'|!()[]- ":
        return fs * 0.34
    return fs * 0.56


def est_w(s, fs, bold=False):
    f = _pil_font(fs)
    if f is not None:
        try:
            w = f.getlength(s)
            return (w * 1.06) if bold else w
        except Exception:
            pass
    k = 1.06 if bold else 1.0
    return sum(_char_w(c, fs) for c in s) * k


def wrap_text(s, fs, maxw, bold=False):
    """贪婪换行。支持已有 \\n；CJK 逐字断行，拉丁按词，超长单词强拆。返回行列表。"""
    out = []
    for seg in str(s).split("\n"):
        if not seg:
            out.append("")
            continue
        cur, curw = "", 0.0
        tokens = _tokenize(seg)
        for tok in tokens:
            tw = est_w(tok, fs, bold)
            if curw + tw > maxw and cur:
                out.append(cur.rstrip())
                tok_s = tok.lstrip()
                if est_w(tok_s, fs, bold) > maxw:
                    # 超长无空格拉丁词/路径按字符硬断行防溢出
                    part = ""
                    for ch in tok_s:
                        if part and est_w(part + ch, fs, bold) > maxw:
                            out.append(part)
                            part = ch
                        else:
                            part += ch
                    cur, curw = part, est_w(part, fs, bold)
                else:
                    cur, curw = tok_s, est_w(tok_s, fs, bold)
            else:
                cur += tok
                curw += tw
        if cur or not out:
            out.append(cur.rstrip())
    return out


def _tokenize(seg):
    toks, buf = [], ""
    for ch in seg:
        is_cjk = unicodedata.east_asian_width(ch) in ("W", "F")
        if is_cjk:
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
        else:
            buf += ch
            if ch in (" ", "/", "-"):
                toks.append(buf)
                buf = ""
    if buf:
        toks.append(buf)
    return toks


# ---------------- SIR 校验 ----------------
def validate_sir(sir):
    """返回 (errors, warns, info)。errors 非空则不应继续布图。"""
    errs, warns, info = [], [], []
    if not isinstance(sir, dict):
        return ["SIR 根必须是 dict"], [], []
    normalize_sir(sir)
    kind = sir.get("kind")
    if kind not in ("apparatus", "flow", "roadmap"):
        errs.append("kind 必须是 apparatus/flow/roadmap，当前=%r" % (kind,))
    if not str(sir.get("title") or "").strip():
        warns.append("缺少 title，将使用空标题")
    if kind == "roadmap":
        phases = sir.get("phases") or []
        if len(phases) < 2:
            warns.append("roadmap 阶段数 <2，建议至少 2 个阶段")
        ids = [p.get("id") for p in phases]
        if any(not i for i in ids):
            errs.append("每个 phase 必须有 id")
        if len(ids) != len(set(ids)):
            errs.append("phase id 重复: %r" % ids)
        for i, p in enumerate(phases):
            if not str(p.get("name") or "").strip():
                errs.append("phases[%d] 缺少 name" % i)
            if not (p.get("source") or {}).get("quote"):
                warns.append("phases[%s] 缺少 source.quote（溯源不完整）" % p.get("id", i))
        plinks = sir.get("phase_links") or []
        idset = set(ids)
        for j, e in enumerate(plinks):
            if e.get("from") not in idset or e.get("to") not in idset:
                errs.append("phase_links[%d] 引用不存在的 phase id" % j)
    else:
        nodes = sir.get("nodes") or []
        if not nodes:
            errs.append("nodes 为空：至少需要 1 个节点")
        ids = [n.get("id") for n in nodes]
        if any(not i for i in ids):
            errs.append("每个 node 必须有 id")
        if len(ids) != len(set(ids)):
            errs.append("node id 重复: %r" % ids)
        idset = set(ids)
        for i, n in enumerate(nodes):
            if not str(n.get("label") or "").strip():
                errs.append("node[%s] 缺少 label" % n.get("id", i))
            t = n.get("type", "process")
            if t not in NODE_STYLES:
                warns.append("node[%s] type=%r 未知，按 process 处理" % (n.get("id", i), t))
            if not (n.get("source") or {}).get("quote"):
                warns.append("node[%s] 缺少 source.quote（溯源不完整）" % n.get("id", i))
        for j, e in enumerate(sir.get("links") or []):
            if e.get("from") not in idset:
                errs.append("links[%d].from=%r 不存在（断头连接）" % (j, e.get("from")))
            if e.get("to") not in idset:
                errs.append("links[%d].to=%r 不存在（断头连接）" % (j, e.get("to")))
            k = e.get("kind", "material")
            if k not in LINK_STYLES:
                warns.append("links[%d] kind=%r 未知，按 material 处理" % (j, k))
            if not (e.get("source") or {}).get("quote"):
                warns.append("links[%d] 缺少 source.quote（溯源不完整）" % j)
        conn = set()
        for e in sir.get("links") or []:
            conn.add(e.get("from"))
            conn.add(e.get("to"))
        for n in nodes:
            if n.get("id") not in conn and len(nodes) > 2:
                warns.append("node[%s] 无任何连接（悬空实体）" % n.get("id"))
    n_src = len(sir.get("nodes") or []) or len(sir.get("phases") or [])
    n_l = len(sir.get("links") or []) or len(sir.get("phase_links") or [])
    info.append("kind=%s lang=%s nodes/phases=%d links=%d" % (kind, detect_lang(sir), n_src, n_l))
    return errs, warns, info


def load(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        normalize_sir(data)
        for sub in data.get("figures") or []:
            if isinstance(sub, dict):
                normalize_sir(sub)
    return data
