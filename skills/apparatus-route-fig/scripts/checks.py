#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checks.py — 场景静态自检：越界 / 节点重叠 / 文本溢出 / 悬空端点 / 图例覆盖 / 溯源覆盖率。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sir as sirmod

MARGIN = 6.0


def run(sc, sird):
    errs, warns, info = [], [], []
    W, H = sc["w"], sc["h"]
    prims = sc["prims"]
    for p in prims:
        p["_est_w"] = sirmod.est_w
    for p in prims:
        x0, y0, x1, y1 = _bbox(p)
        if x0 < MARGIN - 0.5 or y0 < MARGIN - 0.5 or x1 > W - MARGIN + 0.5 or y1 > H - MARGIN + 0.5:
            tag = (p.get("meta") or {}).get("tag") or p["op"]
            ident = (p.get("meta") or {}).get("id") or (p.get("meta") or {}).get("node") or ""
            msg = "越界: %s[%s] bbox=(%.0f,%.0f,%.0f,%.0f) 画布=(%g,%g)" % (p["op"], ident, x0, y0, x1, y1, W, H)
            if tag in ("legend", "prov_footer", "legendnote"):
                warns.append(msg)
            else:
                errs.append(msg)
    nodes = [p for p in prims if p["op"] == "rect" and (p.get("meta") or {}).get("tag") == "node"]
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = _bbox(nodes[i]), _bbox(nodes[j])
            if a[0] + 2 < b[2] and b[0] + 2 < a[2] and a[1] + 2 < b[3] and b[1] + 2 < a[3]:
                errs.append("节点重叠: %s 与 %s" % (nodes[i]["meta"]["id"], nodes[j]["meta"]["id"]))
    nrects = [(p, _bbox(p)) for p in nodes]
    texts = [p for p in prims if p["op"] == "text" and (p.get("meta") or {}).get("tag") != "legend"]
    tbs = [(p, _bbox(p)) for p in texts]
    for i in range(len(tbs)):
        for j in range(i + 1, len(tbs)):
            a, b = tbs[i][1], tbs[j][1]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > 4 and oy > 4:
                ar = (a[2] - a[0]) * (a[3] - a[1]) or 1
                if ox * oy > 0.3 * ar:
                    warns.append("文本重叠: %r 与 %r" % (tbs[i][0]["s"][:14], tbs[j][0]["s"][:14]))
    # 检测边标签是否仍被其他边的垂直线段穿过
    vsegs = []
    for ep in prims:
        if ep["op"] == "line" and (ep.get("meta") or {}).get("tag") == "edge":
            eid = (ep.get("meta") or {}).get("id")
            pts = ep.get("pts") or []
            for si in range(len(pts) - 1):
                x1, y1 = pts[si]
                x2, y2 = pts[si + 1]
                if abs(x1 - x2) < 1.0 and abs(y2 - y1) > 12.0:
                    vsegs.append((eid, x1, min(y1, y2), max(y1, y2)))
    for p in prims:
        if p["op"] == "text" and (p.get("meta") or {}).get("halo"):
            tb = _bbox(p)
            for q, qb in nrects:
                if tb[0] < qb[2] and qb[0] < tb[2] and tb[1] < qb[3] and qb[1] < tb[3]:
                    warns.append("边标签压到节点 %s: %r" % (q["meta"]["id"], p["s"][:18]))
                    break
            own = (p.get("meta") or {}).get("edge")
            for eid, vx, vy0, vy1 in vsegs:
                pad_x = 5.0 if eid == own else 2.0
                if tb[0] + pad_x < vx < tb[2] - pad_x and tb[1] < vy1 - 2 and vy0 + 2 < tb[3]:
                    warns.append("边标签被连线 %s 穿过: %r" % (eid, p["s"][:18]))
                    break
    for p in prims:
        if p["op"] == "text" and (p.get("meta") or {}).get("boxw"):
            bw = p["meta"]["boxw"]
            for ln in str(p["s"]).split("\n"):
                if sirmod.est_w(ln, p["size"], p["weight"] == "bold") > bw + 4:
                    warns.append("文本超宽: %r (est>%.0f)" % (ln[:20], bw))
    for p in prims:
        if p["op"] == "line" and (p.get("meta") or {}).get("tag") == "edge":
            g = sc.get("geom") or {}
            fr, to = (p["meta"]).get("from"), (p["meta"]).get("to")
            for end, key in ((p["pts"][0], fr), (p["pts"][-1], to)):
                gg = g.get(key)
                if not gg:
                    continue
                bx0, by0, bx1, by1 = gg["x"], gg["y"], gg["x"] + gg["w"], gg["y"] + gg["h"]
                near = min(abs(end[0] - bx0), abs(end[0] - bx1)) <= 8 if bx0 - 8 <= end[0] <= bx1 + 8 else False
                near = near or (min(abs(end[1] - by0), abs(end[1] - by1)) <= 8 if by0 - 8 <= end[1] <= by1 + 8 else False)
                if not near:
                    warns.append("边 %s 端点未贴合节点 %s 边界 (%.0f,%.0f)" % (p["meta"]["id"], key, end[0], end[1]))
            # 检测中间线段是否穿透非端点节点框
            pts = p["pts"]
            for si in range(len(pts) - 1):
                x1, y1 = pts[si]
                x2, y2 = pts[si + 1]
                sx0, sx1 = min(x1, x2), max(x1, x2)
                sy0, sy1 = min(y1, y2), max(y1, y2)
                for q, qb in nrects:
                    qid = (q.get("meta") or {}).get("id")
                    if qid in (fr, to) or str(qid).endswith("_inset"):
                        continue
                    # 水平或垂直段严格进入节点内部（内缩 3px 容差）
                    if abs(y1 - y2) < 1e-2 and qb[1] + 3 < y1 < qb[3] - 3 and sx0 < qb[2] - 3 and sx1 > qb[0] + 3:
                        warns.append("边 %s 横穿节点 %s" % (p["meta"]["id"], qid))
                        break
                    if abs(x1 - x2) < 1e-2 and qb[0] + 3 < x1 < qb[2] - 3 and sy0 < qb[3] - 3 and sy1 > qb[1] + 3:
                        warns.append("边 %s 纵穿节点 %s" % (p["meta"]["id"], qid))
                        break
    used_nt = sc["meta"]["used_node_types"]
    used_lk = sc["meta"]["used_link_kinds"]
    leg_n = {i["key"] for i in sc["legend"] if i["kind"] == "node"}
    leg_l = {i["key"] for i in sc["legend"] if i["kind"] == "link"}
    for t in used_nt:
        if t not in leg_n:
            errs.append("图例缺少节点类型: %s" % t)
    for k in used_lk:
        if k not in leg_l:
            errs.append("图例缺少连接类型: %s" % k)
    n_el = sum(1 for p in prims if (p.get("meta") or {}).get("tag") in ("node", "edge"))
    n_pv = sum(1 for p in prims if (p.get("meta") or {}).get("prov"))
    cov = (n_pv / n_el) if n_el else 1.0
    info.append("溯源覆盖率: %d/%d = %.0f%%" % (n_pv, n_el, cov * 100))
    if cov < 1.0:
        warns.append("存在无溯源引用的实体/连接（%.0f%%），请回材料补 quote/loc" % (cov * 100))
    if W > 4200:
        warns.append("画布过宽 (%gpx)，建议减少节点数或分带" % W)
    six = {
        "科学实体": bool(sc["meta"]["n_nodes"]),
        "空间关系": bool(sc["meta"]["n_links"]) or sc["meta"]["kind"] == "roadmap",
        "数据编码": bool(sird.get("nodes") and any(n.get("attrs") for n in sird.get("nodes") or [])) or bool(sird.get("phases")),
        "图例标注": bool(sc["legend"]),
        "可编辑源文件": True,
        "导出格式": True,
    }
    return {"ok": not errs, "errors": errs, "warns": warns, "info": info,
            "six_elements": six,
            "summary": {"canvas": [W, H], "elements": n_el, "provenance": "%.0f%%" % (cov * 100),
                        "kind": sc["meta"]["kind"], "nodes": sc["meta"]["n_nodes"],
                        "links": sc["meta"]["n_links"]}}


def _bbox(p):
    import scene as _scene
    return _scene.bbox(p)


if __name__ == "__main__":
    import json
    sc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sird = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else {}
    print(json.dumps(run(sc, sird), ensure_ascii=False, indent=1))
