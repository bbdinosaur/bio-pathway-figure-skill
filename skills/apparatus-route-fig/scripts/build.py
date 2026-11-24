#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build.py — 组装 scene：标题/副标题/局部放大/图例/溯源页脚（双语自适应 + 零撞色分组）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene
import sir as sirmod


def group_color(name, gcolor_map=None):
    if gcolor_map and str(name) in gcolor_map:
        return gcolor_map[str(name)]
    return sirmod.PALETTE6[sum(ord(c) for c in str(name)) % len(sirmod.PALETTE6)]


def _legend_prims(sird, parts, used_nt, used_lk, W, y0, groups=None, lang="zh"):
    gcolor_map = parts.get("gcolor_map") or {
        g: sirmod.PALETTE6[i % len(sirmod.PALETTE6)] for i, g in enumerate(groups or [])
    }
    items = []
    seen_swatches = set()
    for t in used_nt:
        st = sirmod.NODE_STYLES.get(t, sirmod.NODE_STYLES["process"])
        sw_key = (st[0], st[1])
        if sw_key in seen_swatches:
            continue
        seen_swatches.add(sw_key)
        items.append({"kind": "node", "key": t, "label": sirmod.node_legend(t, lang),
                      "color": st[0], "stroke": st[1]})
    for k in used_lk:
        ls = sirmod.LINK_STYLES.get(k, sirmod.LINK_STYLES["material"])
        items.append({"kind": "link", "key": k, "label": sirmod.link_legend(k, lang),
                      "color": ls[0]})
    clustered = set(parts.get("clustered_groups") or [])
    for gname in groups or []:
        lbl = ("Group %s" % gname) if lang == "en" else ("分组 %s" % gname)
        items.append({"kind": "group_box" if gname in clustered else "node",
                      "key": "group:%s" % gname,
                      "label": lbl,
                      "color": "#F8FAFC" if gname in clustered else gcolor_map[gname],
                      "stroke": gcolor_map[gname]})
    prims = []
    x, y, rows = 32.0, y0, 1
    for it in items:
        iw = 34 + sirmod.est_w(it["label"], 12) + 22
        if x + iw > W - 32 and x > 33.0:
            x = 32.0
            y += 22
            rows += 1
        if it["kind"] == "group_box":
            prims.append(scene.R(x, y - 9, 18, 13, fill=it["color"],
                                 stroke=it.get("stroke", "#4A5568"),
                                 sw=1.3, rx=3, dash="4,2", layer="legend", tag="legend"))
        elif it["kind"] == "node":
            prims.append(scene.R(x, y - 9, 18, 13, fill=it["color"],
                                 stroke=it.get("stroke", "#4A5568"),
                                 sw=1.2, rx=3, layer="legend", tag="legend"))
        else:
            ls = sirmod.LINK_STYLES.get(it["key"], sirmod.LINK_STYLES["material"])
            mk_l = "tbar" if it["key"] == "inhibit" else "arrow"
            prims.append(scene.LN([(x, y - 2.5), (x + 24, y - 2.5)], stroke=ls[0],
                                  sw=2.0, dash=ls[1], marker=mk_l, layer="legend",
                                  tag="legend"))
        prims.append(scene.TX(x + 28, y + 1.5, it["label"], size=12, anchor="start",
                              fill="#2D3748", layer="legend", tag="legend"))
        x += iw
    h = rows * 22 + 12
    box_h = h + 6
    note = str(sird.get("legend_note") or "").strip()
    if note:
        for ln in sirmod.wrap_text(note, 11, W - 64)[:2]:
            prims.append(scene.TX(W - 32, y0 + h + 12, ln, size=11, anchor="end",
                                  fill="#718096", layer="legend", tag="legendnote"))
            h += 15
            box_h += 15
    if items:
        prims.insert(0, scene.R(20.0, y0 - 16.0, W - 40.0, box_h, fill="#F8FAFC",
                                stroke="#E2E8F0", sw=1.0, rx=8, layer="frame", tag="legend_box"))
    return prims, items, h


def inset_panels(sird, parts, lang="zh"):
    """局部放大：node.zoom=[细目行] → 底部绘制放大面板 + 引线（多放大面板宽画布自动并排），返回额外图元。"""
    W = parts["W"]
    y_row = max(parts["bottom"], max(parts.get("bus_ys") or [0]) + 16.0) + 16.0
    prims, new_bottom = [], y_row
    z_nodes = [n for n in (sird.get("nodes") or [])
               if isinstance(n.get("zoom"), list) and n.get("zoom") and (parts.get("geom") or {}).get(n["id"])]
    if not z_nodes:
        return prims
    can_side = len(z_nodes) >= 2 and (W - 64.0) >= 560.0
    pw = min(330.0, max(240.0, (W - 68.0) / 2.0)) if can_side else min(330.0, max(240.0, W - 120.0))
    if can_side:
        y_row += 18.0
    row_max_h = 0.0
    for zi, n in enumerate(z_nodes):
        items = n.get("zoom")
        g = (parts.get("geom") or {}).get(n["id"])
        lines = []
        for it in items:
            lines += sirmod.wrap_text("• " + str(it), 11, pw - 26)
        ph = 30 + len(lines) * 15 + 10
        if can_side:
            col_i = zi % 2
            if col_i == 0 and zi > 0:
                y_row += row_max_h + 24.0
                row_max_h = 0.0
            x0 = (W - 2 * pw - 20.0 - 24.0) + col_i * (pw + 20.0)
            x0 = max(24.0, x0)
            y0 = y_row
            row_max_h = max(row_max_h, ph)
        else:
            x0 = W - pw - 24.0
            y0 = y_row
            y_row += ph + 14.0
        src = n.get("source") or {}
        prefix = "Zoom-in: " if lang == "en" else "局部放大："
        meta = {"tag": "node", "id": n["id"] + "_inset"}
        if src.get("quote"):
            meta["prov"] = prefix + src["quote"]
        if src.get("loc"):
            meta["prov_loc"] = src["loc"]
        prims.append(scene.R(x0, y0, pw, ph, fill="#F7FAFC", stroke="#2B6CB0", sw=1.2,
                             rx=8, dash="4,3", layer="nodes", **meta))
        prims.append(scene.TX(x0 + 12, y0 + 20, prefix + str(n.get("label", "")), size=12,
                              weight="bold", anchor="start", fill="#1A365D", layer="labels",
                              node=n["id"], boxw=pw - 56))
        yy = y0 + 38
        for ln in lines:
            prims.append(scene.TX(x0 + 12, yy, ln, size=11, anchor="start", fill="#2D3748",
                                  layer="labels", node=n["id"], boxw=pw - 26))
            yy += 15
        import glyphs as _gl
        gi = _gl.draw(n, x0 + pw - 42, y0 + 6, 30, 22)
        if gi:
            prims += gi[1]
        # 引线若同列下方有节点则从右侧外廊绕下；并排多放大面板统一从面板顶边汇入，绝不横穿相邻放大框
        geom = parts.get("geom") or {}
        blocked_below = any(
            oid != n["id"] and og["col"] == g["col"] and og["band"] == g["band"] and og["y"] >= g["y"] + g["h"] - 2
            for oid, og in geom.items()
        )
        ax_ = g["cx"]
        if can_side:
            turn_y = y0 - 10.0 - 6.0 * (zi % 2)
            tx_top = x0 + pw * (0.35 if (zi % 2 == 0) else 0.50)
            if blocked_below:
                sx = min(W - 18.0, g["x"] + g["w"] + 18.0)
                prims.append(scene.LN([(g["x"] + g["w"], g["cy"]), (sx, g["cy"]),
                                       (sx, turn_y), (tx_top, turn_y), (tx_top, y0)],
                                      stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                      layer="links", tag="leader"))
            else:
                prims.append(scene.LN([(ax_, g["y"] + g["h"]), (ax_, turn_y),
                                       (tx_top, turn_y), (tx_top, y0)],
                                      stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                      layer="links", tag="leader"))
        elif blocked_below:
            sx = min(W - 18.0, g["x"] + g["w"] + 18.0)
            if sx < x0 - 8:
                prims.append(scene.LN([(g["x"] + g["w"], g["cy"]), (sx, g["cy"]),
                                       (sx, y0 + ph / 2.0), (x0, y0 + ph / 2.0)],
                                      stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                      layer="links", tag="leader"))
            else:
                prims.append(scene.LN([(g["x"] + g["w"], g["cy"]), (sx, g["cy"]),
                                       (sx, y0 - 10.0), (x0 + pw / 2.0, y0 - 10.0), (x0 + pw / 2.0, y0)],
                                      stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                      layer="links", tag="leader"))
        elif ax_ < x0 - 16:
            prims.append(scene.LN([(ax_, g["y"] + g["h"]), (ax_, y0 + ph / 2.0), (x0, y0 + ph / 2.0)],
                                  stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                  layer="links", tag="leader"))
        else:
            prims.append(scene.LN([(ax_, g["y"] + g["h"]), (ax_, y0)],
                                  stroke="#718096", sw=1.2, dash="3,3", marker="arrow",
                                  layer="links", tag="leader"))
        new_bottom = max(new_bottom, y0 + ph + 14.0)
    parts["bottom"] = max(parts["bottom"], new_bottom)
    return prims


def assemble(sird, parts):
    lang = sirmod.detect_lang(sird)
    extra = []
    if sird.get("kind") != "roadmap":
        try:
            extra = inset_panels(sird, parts, lang)
        except Exception:
            extra = []
    title = str(sird.get("title") or "").strip()
    W = max(float(parts["W"]), min(sirmod.est_w(title, 19.5, True) + 48.0, 1600.0))
    bus_bottom = max(parts.get("bus_ys") or [0]) + 18.0
    bottom = max(parts["bottom"], bus_bottom)
    used_nt, used_lk = parts.get("used_node_types", []), parts.get("used_link_kinds", [])
    groups = sorted({str(n.get("group")) for n in (sird.get("nodes") or []) if n.get("group")})
    lg_prims, lg_items, lg_h = _legend_prims(sird, parts, used_nt, used_lk, W, bottom + 28, groups, lang)
    H = bottom + 28 + lg_h + 30
    prims = []
    sub = str(sird.get("subtitle") or "").strip()
    if title or sub:
        t_lines = sirmod.wrap_text(title, 19.5, W - 56, bold=True)[:2] if title else []
        sub_lines = sirmod.wrap_text(sub, 12.2, W - 56)[:2] if sub else []
        bar_top = 18.0
        t_bot = (38.0 + (len(t_lines) - 1) * 23.0) if t_lines else 22.0
        sub_y0 = (t_bot + 20.0) if t_lines else 34.0
        bar_bot = (sub_y0 + (len(sub_lines) - 1) * 17.0 + 4.0) if sub_lines else (t_bot + 6.0)
        if title:
            prims.append(scene.R(20.0, bar_top, 4.5, max(24.0, bar_bot - bar_top), fill="#2B6CB0",
                                 stroke="none", sw=0, rx=2.2, layer="frame", tag="title_bar"))
        for ti, tln in enumerate(t_lines):
            prims.append(scene.TX(32.0, 38.0 + ti * 23.0, tln, size=19.5, weight="bold", anchor="start",
                                  fill="#1A202C", layer="frame", tag="title"))
        for i, ln in enumerate(sub_lines):
            prims.append(scene.TX(32.0, sub_y0 + i * 17.0, ln, size=12.2, anchor="start",
                                  fill="#4A5568", layer="frame", tag="subtitle"))
        div_y = bar_bot + 9.0
        prims.append(scene.LN([(20.0, div_y), (W - 20.0, div_y)], stroke="#E2E8F0", sw=1.2,
                              marker="none", layer="frame", tag="header_rule"))
    prims += parts["node_prims"]
    prims += parts["edge_prims"]
    prims += _nudge_labels(parts["labels"], parts["node_prims"], W, H, parts["edge_prims"])
    prims += extra
    prims += lg_prims
    default_prov = (
        "Generated by apparatus-route-fig Skill; element provenance in SVG data-prov & provenance.json"
        if lang == "en"
        else "由 apparatus-route-fig Skill 生成；逐元素溯源见 SVG data-prov 属性与 provenance.json"
    )
    if "prov_footer" in sird and sird.get("prov_footer") == "":
        prov = ""
    else:
        prov = str(sird.get("prov_footer") or default_prov).strip()
    if prov:
        prims.append(scene.TX(W - 20, H - 10, prov, size=10.5, anchor="end", fill="#718096",
                              layer="footer", tag="prov_footer"))
    used = {"kind": sird.get("kind"), "lang": lang, "title": title,
            "used_node_types": used_nt, "used_link_kinds": used_lk,
            "groups": groups,
            "n_nodes": len(sird.get("nodes") or sird.get("phases") or []),
            "n_links": len(sird.get("links") or sird.get("phase_links") or [])}
    return {"w": W, "h": H, "prims": prims, "legend": lg_items, "meta": used}


def _nudge_labels(labels, node_prims, W=2000.0, H=1200.0, edge_prims=None):
    """边标签与节点盒/垂直连线/其他边标签碰撞时自动避让，并限制在画布安全边距内。"""
    import scene as _sc
    rects = [(_sc.bbox(p)) for p in node_prims
             if p["op"] == "rect" and (p.get("meta") or {}).get("tag") == "node"]
    # 提取垂直/水平边线段，用于避免其他边的线段从边标签文字中间穿过或被白底晕遮挡
    vsegs, hsegs = [], []
    for ep in (edge_prims or []):
        if ep.get("op") != "line":
            continue
        eid = (ep.get("meta") or {}).get("id")
        pts = ep.get("pts") or []
        for k in range(len(pts) - 1):
            x1, y1 = pts[k]
            x2, y2 = pts[k + 1]
            if abs(x1 - x2) < 1.0 and abs(y2 - y1) > 12.0:
                vsegs.append((eid, x1, min(y1, y2), max(y1, y2)))
            elif abs(y1 - y2) < 1.0 and abs(x2 - x1) > 14.0:
                hsegs.append((eid, y1, min(x1, x2), max(x1, x2)))
    halos = [t for t in labels if (t.get("meta") or {}).get("halo")]
    for _ in range(5):
        moved = False
        for t in halos:
            t["_est_w"] = sirmod.est_w
            tb = _sc.bbox(t)
            for rb in rects:
                if tb[0] < rb[2] and rb[0] < tb[2] and tb[1] < rb[3] and rb[1] < tb[3]:
                    dy = -16 if (tb[1] - rb[1]) < (rb[3] - tb[3]) else 16
                    t["y"] += dy
                    moved = True
                    break
        for t in halos:
            t["_est_w"] = sirmod.est_w
            tb = _sc.bbox(t)
            own = (t.get("meta") or {}).get("edge")
            for eid, vx, vy0, vy1 in vsegs:
                # 同时避免跨过其他边以及自身垂直折线段中心，杜绝文字压在红/蓝竖线上
                pad_x = 3.0 if eid == own else -2.0
                if tb[0] + pad_x < vx < tb[2] - pad_x and tb[1] < vy1 - 2 and vy0 + 2 < tb[3]:
                    # 优先水平避让；若窄缝内水平移不动则垂直翻到连线另一侧避开垂线端点
                    shift_l = (vx - 6.0) - tb[2]
                    shift_r = (vx + 6.0) - tb[0]
                    placed = False
                    for dx in sorted((shift_l, shift_r), key=abs):
                        if abs(dx) <= 95.0:
                            nb = (tb[0] + dx, tb[1], tb[2] + dx, tb[3])
                            hit_node = any(nb[0] < rb[2] and rb[0] < nb[2] and nb[1] < rb[3] and rb[1] < nb[3] for rb in rects)
                            if not hit_node and nb[0] >= 10.0 and nb[2] <= W - 10.0:
                                t["x"] += dx
                                placed = True
                                moved = True
                                break
                    if not placed:
                        for dy in (22.0, -22.0, 26.0, -26.0):
                            nb = (tb[0], tb[1] + dy, tb[2], tb[3] + dy)
                            hit_node = any(nb[0] < rb[2] and rb[0] < nb[2] and nb[1] < rb[3] and rb[1] < nb[3] for rb in rects)
                            hit_v = any(nb[0] + (3.0 if e2 == own else -2.0) < vx2 < nb[2] - (3.0 if e2 == own else -2.0) and nb[1] < vy1_2 - 2 and vy0_2 + 2 < nb[3]
                                        for e2, vx2, vy0_2, vy1_2 in vsegs)
                            if not hit_node and not hit_v and nb[1] >= 22.0 and nb[3] <= H - 10.0:
                                t["y"] += dy
                                moved = True
                                break
                    if moved:
                        break
        for t in halos:
            t["_est_w"] = sirmod.est_w
            tb = _sc.bbox(t)
            own = (t.get("meta") or {}).get("edge")
            for eid, hy, hx0, hx1 in hsegs:
                if eid == own:
                    continue
                if tb[1] - 1.5 < hy < tb[3] + 1.5 and tb[0] < hx1 - 2 and hx0 + 2 < tb[2]:
                    for dy in (16.0, -16.0):
                        nb = (tb[0], tb[1] + dy, tb[2], tb[3] + dy)
                        hit_node = any(nb[0] < rb[2] and rb[0] < nb[2] and nb[1] < rb[3] and rb[1] < nb[3] for rb in rects)
                        hit_h = any(e2 != own and nb[1] - 1.5 < hy2 < nb[3] + 1.5 and nb[0] < hx1_2 - 2 and hx0_2 + 2 < nb[2]
                                    for e2, hy2, hx0_2, hx1_2 in hsegs)
                        if not hit_node and not hit_h and nb[1] >= 22.0 and nb[3] <= H - 10.0:
                            t["y"] += dy
                            moved = True
                            break
                    if moved:
                        break
        for i in range(len(halos)):
            halos[i]["_est_w"] = sirmod.est_w
            a = _sc.bbox(halos[i])
            ei = (halos[i].get("meta") or {}).get("edge")
            for j in range(i + 1, len(halos)):
                ej = (halos[j].get("meta") or {}).get("edge")
                if ei and ei == ej:
                    continue
                halos[j]["_est_w"] = sirmod.est_w
                b = _sc.bbox(halos[j])
                if a[0] < b[2] - 2 and b[0] < a[2] - 2 and a[1] < b[3] - 2 and b[1] < a[3] - 2:
                    halos[j]["y"] += 15.0
                    moved = True
        for t in halos:
            t["_est_w"] = sirmod.est_w
            tb = _sc.bbox(t)
            if tb[0] < 10.0:
                t["x"] += (10.0 - tb[0])
            elif tb[2] > W - 10.0:
                t["x"] -= (tb[2] - (W - 10.0))
            if tb[1] < 22.0:
                t["y"] += (22.0 - tb[1])
            elif tb[3] > H - 10.0:
                t["y"] -= (tb[3] - (H - 10.0))
        if not moved:
            break
    return labels


def provenance_table(sc):
    """从 scene 提取逐元素溯源表（节点/连接），供 result.json 与人工核验。"""
    rows = []
    for p in sc["prims"]:
        m = p.get("meta") or {}
        if m.get("prov") and m.get("tag") in ("node", "edge"):
            rows.append({"id": m.get("id") or m.get("node"), "element": m.get("tag"),
                         "kind": m.get("kind", ""), "quote": m.get("prov"),
                         "loc": m.get("prov_loc", "")})
    return rows


def build_scene(sird, maxcols=None):
    kind = sird.get("kind", "flow")
    if kind == "roadmap":
        import layout_roadmap, roadmap_edges
        rg = layout_roadmap.build_roadmap(sird)
        parts = {**roadmap_edges.build_links(rg, sird), **{k: rg[k] for k in
                 ("node_prims", "geom", "W", "bottom")}}
        parts["used_node_types"] = ["phase"]
        parts["used_link_kinds"] = sorted(set(e.get("kind", "handoff") for e in sird.get("phase_links") or [])) or ["handoff"]
        sc = assemble(sird, parts)
        sc["geom"] = rg["geom"]
        return sc
    import layout_flow, layout_edges
    g = layout_flow.place_nodes(sird, maxcols)
    r = layout_edges.route_edges(sird, g)
    parts = {"W": g["W"], "bottom": g["bottom"], "node_prims": g["node_prims"],
             "edge_prims": r["edge_prims"], "labels": r["labels"], "bus_ys": r["bus_ys"],
             "geom": g["geom"], "gcolor_map": g.get("gcolor_map"),
             "clustered_groups": g.get("clustered_groups")}
    seen = []
    for n in sird.get("nodes") or []:
        t = n.get("type", "process")
        t = t if t in sirmod.NODE_STYLES else "process"
        if t not in seen:
            seen.append(t)
    parts["used_node_types"] = seen
    seenl = []
    for e in sird.get("links") or []:
        k = e.get("kind", "material")
        k = k if k in sirmod.LINK_STYLES else "material"
        if k not in seenl:
            seenl.append(k)
    parts["used_link_kinds"] = seenl
    sc = assemble(sird, parts)
    sc["geom"] = g["geom"]
    return sc
