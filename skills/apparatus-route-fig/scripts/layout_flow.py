#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_flow.py — apparatus/flow SIR → 节点分层分列布点（主干优先拓扑 + 紧凑换行分带 + 垂直居中）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene
import sir as sirmod
import glyphs

MAXCOLS = 5
NODE_W = 212.0
COLGAP = 104.0
ROWGAP = 42.0
T_TOP = 108.0
L_M = 74.0
R_M = 74.0
BANDGAP = 112.0
FS_LABEL = 13.5
FS_ATTR = 11.2


def _has_icon(n):
    st = sirmod.NODE_STYLES.get(n.get("type", "process"), sirmod.NODE_STYLES["process"])
    if st[3] == "pill":
        return False
    return glyphs.match(n) is not None


def _text_w(n, nw=NODE_W):
    return nw - (58.0 if _has_icon(n) else 26.0)


def _node_h(n, nw=NODE_W):
    tw = _text_w(n, nw)
    nl = len(sirmod.wrap_text(n.get("label", ""), FS_LABEL, tw, bold=True))
    al = 0
    for k, v in (n.get("attrs") or {}).items():
        al += len(sirmod.wrap_text("%s: %s" % (k, v), FS_ATTR, tw))
    return max(58.0, 14.0 + nl * 17.5 + (al * 15.0 + 4.0 if al else 0.0) + 10.0)


def _assign_layers(nodes, all_links):
    """主物料/工艺前向边优先分层，避免控制/监测反馈把 start/input 挤到中间。"""
    ids = [n["id"] for n in nodes]
    nmap = {n["id"]: n for n in nodes}
    explicit = {n["id"]: int(n["layer"]) for n in nodes if isinstance(n.get("layer"), int)}

    # 跨平行臂的抑制/串扰边（两端属不同非空 group，且目标已有同组或无组前向入边）：不强行把目标列右推，避免平行臂留空洞
    in_same_fwd = set()
    for e in all_links:
        if e.get("kind", "material") in ("material", "activate"):
            ga = str((nmap.get(e["from"]) or {}).get("group") or "").strip()
            gb = str((nmap.get(e["to"]) or {}).get("group") or "").strip()
            if not ga or not gb or ga == gb:
                in_same_fwd.add(e["to"])
    mat_links = []
    for e in all_links:
        k_e = e.get("kind", "material")
        if k_e in ("loop", "signal", "data"):
            continue
        if k_e == "inhibit":
            ga = str((nmap.get(e["from"]) or {}).get("group") or "").strip()
            gb = str((nmap.get(e["to"]) or {}).get("group") or "").strip()
            if ga and gb and ga != gb and e["to"] in in_same_fwd:
                continue
        mat_links.append(e)
    aux_links = [e for e in all_links if e.get("kind", "material") in ("signal", "data")]
    use_links = mat_links if mat_links else [e for e in all_links if e.get("kind") != "loop"]

    touched = set()
    for e in use_links:
        touched.add(e["from"])
        touched.add(e["to"])

    # DFS 破环：自动识别生物负反馈等有向环的回边（如 JAK2→STAT3→SOCS3-|JAK2），避免环上节点被推到最末列
    adj_use = {i: [] for i in ids}
    in_use = {i: 0 for i in ids}
    for e in use_links:
        if e["from"] in adj_use and e["to"] in in_use and e["from"] != e["to"]:
            adj_use[e["from"]].append(e["to"])
            in_use[e["to"]] += 1
    roots = sorted(
        ids,
        key=lambda nid: (
            0 if nmap[nid].get("type") == "start" else (1 if nmap[nid].get("type") == "input" else 2),
            0 if in_use.get(nid, 0) == 0 else 1,
            ids.index(nid),
        ),
    )
    visited, on_stack, back_pairs = set(), set(), set()

    def _dfs_cycle(u):
        visited.add(u)
        on_stack.add(u)
        for v in adj_use.get(u, []):
            if v in on_stack:
                back_pairs.add((u, v))
            elif v not in visited:
                _dfs_cycle(v)
        on_stack.remove(u)

    for r in roots:
        if r not in visited:
            _dfs_cycle(r)
    dag_links = [e for e in use_links if e["from"] != e["to"] and (e["from"], e["to"]) not in back_pairs]

    layer = {i: explicit.get(i, 0) for i in ids}
    cap = max(len(ids), 1)
    for _ in range(len(ids) + 1):
        changed = False
        for e in dag_links:
            a, b = e["from"], e["to"]
            if b in explicit:
                continue
            if layer.get(b, 0) < layer.get(a, 0) + 1 <= cap:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break

    # 将仅由 signal/data 连接的辅助节点分类放置：
    # - 若存在指向主干节点的 signal 控制边（如控制器→泵），对齐目标所在列；
    # - 否则若由上游指向（如下游 QC/分析/结果输出），自然推进到 max(ins)+1，避免倒流。
    if mat_links:
        max_main = max((layer[i] for i in touched), default=0)
        unplaced = [i for i in ids if i not in touched and i not in explicit]
        for _ in range(len(unplaced) + 2):
            changed = False
            for u in list(unplaced):
                outs_to_main = [layer[e["to"]] for e in aux_links
                                if e["from"] == u and e["to"] in touched]
                ins = [layer[e["from"]] for e in aux_links
                       if e["to"] == u and e["from"] not in unplaced]
                outs_placed = [layer[e["to"]] for e in aux_links
                               if e["from"] == u and e["to"] not in unplaced]
                if outs_to_main:
                    layer[u] = min(max(min(outs_to_main), 0), max_main)
                    unplaced.remove(u)
                    changed = True
                elif ins:
                    layer[u] = max(ins) + 1
                    unplaced.remove(u)
                    changed = True
                elif outs_placed:
                    layer[u] = max(0, min(outs_placed) - 1)
                    unplaced.remove(u)
                    changed = True
            if not changed:
                break

    # 旁路加料/辅料源节点（无入边、非起点、且所有下游都在 layer>=2）：右移贴近首个消费步骤，避免长跨距穿图
    fwd_all = [e for e in all_links if e.get("kind") != "loop"]
    in_cnt = {i: 0 for i in ids}
    out_tgts = {i: [] for i in ids}
    for e in fwd_all:
        if e["to"] in in_cnt:
            in_cnt[e["to"]] += 1
        if e["from"] in out_tgts:
            out_tgts[e["from"]].append(e["to"])
    for n in nodes:
        nid = n["id"]
        if nid in explicit or n.get("type") == "start":
            continue
        if in_cnt.get(nid, 0) == 0 and out_tgts.get(nid):
            min_tgt = min(layer.get(t, 0) for t in out_tgts[nid])
            if min_tgt >= 2 and layer.get(nid, 0) < min_tgt - 1:
                layer[nid] = min_tgt - 1

    # 压缩空列并归一化最小层为 0，杜绝显式 layer 跳号产生空白列
    if layer:
        uniq_l = sorted(set(layer.values()))
        lmap = {lv: idx_l for idx_l, lv in enumerate(uniq_l)}
        layer = {k: lmap[v] for k, v in layer.items()}
    return layer


def place_nodes(sird, maxcols=None):
    maxcols = maxcols or MAXCOLS
    nodes = sird.get("nodes", [])
    all_links = sird.get("links", [])
    fwd_links = [e for e in all_links if e.get("kind") != "loop"]

    layer = _assign_layers(nodes, all_links)
    cols = {}
    for n in nodes:
        cols.setdefault(layer[n["id"]], []).append(n)
    ncols = (max(cols) if cols else 0) + 1
    for c in range(ncols):
        cols.setdefault(c, [])

    # 去除空列，避免出现空白槽
    non_empty = [c for c in range(ncols) if cols[c]]
    remap = {old: idx for idx, old in enumerate(non_empty)}
    cols = {remap[c]: cols[c] for c in non_empty}
    layer = {nid: remap[c] for nid, c in layer.items()}
    ncols = len(non_empty)

    def idx_map():
        m = {}
        for c in range(ncols):
            for i, n in enumerate(cols[c]):
                m[n["id"]] = i
        return m

    # 按节点首次出现顺序记录分组泳道顺序，保证平行实验臂（如 Control vs Treatment）跨列对齐不交叉
    group_order = {}
    for n in nodes:
        g_s = str(n.get("group") or "").strip()
        if g_s and g_s not in group_order:
            group_order[g_s] = len(group_order)

    for _sweep in range(2):
        m = idx_map()
        for c in range(ncols):
            col_groups = {str(n.get("group") or "").strip() for n in cols[c] if str(n.get("group") or "").strip()}
            use_g_lane = len(col_groups) >= 2
            def score_in(n, c=c, m=m, use_g_lane=use_g_lane):
                ps = [m[e["from"]] for e in fwd_links if e["to"] == n["id"] and layer.get(e["from"]) == c - 1]
                aux_bias = 0.4 if n.get("type") in ("measure", "decision") and not ps else 0.0
                base = (sum(ps) / len(ps) if ps else m[n["id"]]) + aux_bias
                g_s = str(n.get("group") or "").strip()
                return (group_order[g_s] if (use_g_lane and g_s in group_order) else 999, base)
            cols[c].sort(key=score_in)
        m = idx_map()
        for c in range(ncols - 1, -1, -1):
            col_groups = {str(n.get("group") or "").strip() for n in cols[c] if str(n.get("group") or "").strip()}
            use_g_lane = len(col_groups) >= 2
            def score_out(n, c=c, m=m, use_g_lane=use_g_lane):
                ss = [m[e["to"]] for e in fwd_links if e["from"] == n["id"] and layer.get(e["to"]) == c + 1]
                base = sum(ss) / len(ss) if ss else m[n["id"]]
                g_s = str(n.get("group") or "").strip()
                return (group_order[g_s] if (use_g_lane and g_s in group_order) else 999, base)
            cols[c].sort(key=score_out)

    # 反孤儿换行：若仅超出 1 列且末列仅有 <=2 个终端节点，适度收紧列间距保单带横向贯通，避免 1800px 折返长线
    colgap = COLGAP
    if ncols == maxcols + 1 and maxcols <= 6 and len(cols.get(ncols - 1, [])) <= 2:
        maxcols = ncols
        if ncols >= 7:
            colgap = 88.0

    # 真正按带内列号 c % maxcols 计算 X 坐标，杜绝对角线漂移与超宽死白；<=4 列且文本较密时自适应拓宽节点卡片
    eff_cols = min(ncols, maxcols) if ncols else 1
    nw = NODE_W
    if eff_cols <= 4 and nodes:
        max_need = 0.0
        for n in nodes:
            pad_ic = 58.0 if _has_icon(n) else 26.0
            lw = sirmod.est_w(str(n.get("label") or ""), FS_LABEL, True) + pad_ic
            aw = max((sirmod.est_w("%s: %s" % (k, v), FS_ATTR) + pad_ic
                      for k, v in (n.get("attrs") or {}).items()), default=0.0)
            max_need = max(max_need, min(lw, 238.0), min(aw, 238.0))
        if max_need > NODE_W + 4.0:
            nw = min(238.0, max(NODE_W, round(max_need, 1)))
    col_x = {c: L_M + (c % maxcols) * (nw + colgap) for c in range(ncols)}
    W = max(720.0, L_M + eff_cols * (nw + colgap) - colgap + R_M)

    # 动态计算标题/副标题高度与 Band 0 跨列顶通道留白，无标题子面板自动紧缩顶部留白
    title_s = str(sird.get("title") or "").strip()
    sub_s = str(sird.get("subtitle") or "").strip()
    if title_s or sub_s:
        t_lines = sirmod.wrap_text(title_s, 19.5, W - 56, bold=True)[:2] if title_s else []
        sub_lines = sirmod.wrap_text(sub_s, 12.2, W - 56)[:2] if sub_s else []
        t_bot = (38.0 + (len(t_lines) - 1) * 23.0) if t_lines else 22.0
        header_bot = t_bot + (16.0 + len(sub_lines) * 17.0 if sub_lines else 14.0) + 12.0
    else:
        header_bot = 8.0
    top_row_ids = {cols[c][0]["id"] for c in range(min(ncols, maxcols)) if cols.get(c)}
    has_lower_row = any(len(cols.get(c, [])) >= 2 for c in range(min(ncols, maxcols)))
    n_skip_b0 = sum(1 for e in fwd_links
                    if layer.get(e["from"], 0) // maxcols == 0
                    and layer.get(e["to"], 0) // maxcols == 0
                    and layer.get(e["to"], 0) > layer.get(e["from"], 0) + 1)
    if has_lower_row:
        n_skip_b0 += sum(1 for e in all_links
                         if (e.get("kind") == "loop" or layer.get(e["to"], 0) < layer.get(e["from"], 0))
                         and layer.get(e["from"], 0) // maxcols == 0
                         and layer.get(e["to"], 0) // maxcols == 0
                         and e["from"] in top_row_ids and e["to"] in top_row_ids)
    skip_pad_b0 = (26.0 + 14.0 * min(n_skip_b0, 3)) if n_skip_b0 else 0.0

    groups = sorted({str(n.get("group")) for n in nodes if n.get("group")})
    has_steps = any(str(n.get("step") or "").strip() for n in nodes)
    gcolor_map = {gname: sirmod.PALETTE6[i % len(sirmod.PALETTE6)] for i, gname in enumerate(groups)}
    pad_top = 34.0 if (groups and has_steps) else (26.0 if groups else 0.0)
    pad_bot = 12.0 if groups else 0.0
    # 若同列存在多个不同 group（如平行实验臂 Control vs Treatment），自动加大行距确保上下虚线泳道框不碰撞
    has_stacked_groups = any(
        len({str(n.get("group") or "").strip() for n in cols[c] if str(n.get("group") or "").strip()}) >= 2
        for c in range(ncols)
    )
    rowgap = ROWGAP + (6.0 if has_steps else 0.0)
    if has_stacked_groups:
        rowgap = max(rowgap, pad_top + pad_bot + 16.0)
    base_top = max(T_TOP, header_bot + 16.0) if (title_s or sub_s) else 20.0
    t_top = base_top + (pad_top if groups else (12.0 if has_steps else 0.0)) + skip_pad_b0
    bandgap = BANDGAP + (32.0 if groups else 0.0)

    geom, bands_meta = {}, {}
    yb = t_top
    for b in sorted(set(c // maxcols for c in range(ncols))):
        bcols = [c for c in range(ncols) if c // maxcols == b]
        # 检测本带是否存在同列堆叠的多分组（平行实验臂泳道）
        band_groups = []
        for g_s in sorted(group_order.keys(), key=lambda x: group_order[x]):
            if any(str(n.get("group") or "").strip() == g_s for c in bcols for n in cols[c]):
                band_groups.append(g_s)
        band_stacked = len(band_groups) >= 2 and any(
            len({str(n.get("group") or "").strip() for n in cols[c] if str(n.get("group") or "").strip()}) >= 2
            for c in bcols
        )
        if band_stacked:
            lane_keys = list(band_groups)
            has_mixed_ungrouped = any(
                any(str(n.get("group") or "").strip() for n in cols[c])
                and any(not str(n.get("group") or "").strip() for n in cols[c])
                for c in bcols
            )
            if has_mixed_ungrouped:
                lane_keys.append("__ungrouped__")
            base_rg = ROWGAP + (6.0 if has_steps else 0.0)
            lane_gap = max(base_rg, pad_top + pad_bot + 16.0)
            lane_h = {}
            for lk in lane_keys:
                mh = 0.0
                for c in bcols:
                    if not any(str(n.get("group") or "").strip() for n in cols[c]):
                        continue
                    lnodes = [n for n in cols[c]
                              if (str(n.get("group") or "").strip() or "__ungrouped__") == lk]
                    if lnodes:
                        hs = [_node_h(n, nw) for n in lnodes]
                        mh = max(mh, sum(hs) + max(len(hs) - 1, 0) * base_rg)
                lane_h[lk] = max(mh, 60.0)
            lane_y = {}
            yl = yb
            for lk in lane_keys:
                lane_y[lk] = yl
                yl += lane_h[lk] + lane_gap
            band_h = max(yl - lane_gap - yb, 60.0)
            # 先按泳道对齐放置含分组列的节点，再将纯未分组连接列垂直居中（贴合泳道中轴）
            grp_top = lane_y[band_groups[0]]
            grp_bot = lane_y[band_groups[-1]] + lane_h[band_groups[-1]]
            for c in bcols:
                has_g = any(str(n.get("group") or "").strip() for n in cols[c])
                if has_g:
                    for lk in lane_keys:
                        lnodes = [n for n in cols[c]
                                  if (str(n.get("group") or "").strip() or "__ungrouped__") == lk]
                        if not lnodes:
                            continue
                        hs = [_node_h(n, nw) for n in lnodes]
                        ch = sum(hs) + max(len(hs) - 1, 0) * base_rg
                        y = lane_y[lk] + (lane_h[lk] - ch) / 2.0
                        for n, hn in zip(lnodes, hs):
                            geom[n["id"]] = {"x": col_x[c], "y": y, "w": nw, "h": hn,
                                             "cx": col_x[c] + nw / 2.0, "cy": y + hn / 2.0,
                                             "col": c, "bcol": c % maxcols, "band": b,
                                             "type": n.get("type", "process")}
                            y += hn + base_rg
                else:
                    hs = [_node_h(n, nw) for n in cols[c]]
                    ch = sum(hs) + max(len(hs) - 1, 0) * base_rg
                    center_span_y = grp_top if (grp_bot - grp_top) >= ch else yb
                    center_span_h = (grp_bot - grp_top) if (grp_bot - grp_top) >= ch else band_h
                    y = center_span_y + (center_span_h - ch) / 2.0
                    for n, hn in zip(cols[c], hs):
                        geom[n["id"]] = {"x": col_x[c], "y": y, "w": nw, "h": hn,
                                         "cx": col_x[c] + nw / 2.0, "cy": y + hn / 2.0,
                                         "col": c, "bcol": c % maxcols, "band": b,
                                         "type": n.get("type", "process")}
                        y += hn + base_rg
        else:
            col_hs = {}
            for c in bcols:
                hs = [_node_h(n, nw) for n in cols[c]]
                col_hs[c] = sum(hs) + max(len(hs) - 1, 0) * rowgap
            band_h = max(col_hs.values(), default=60.0)
            for c in bcols:
                # 每一列在带内垂直居中，消除相邻不同高度节点间的小锯齿折角
                y = yb + (band_h - col_hs[c]) / 2.0
                for n in cols[c]:
                    hn = _node_h(n, nw)
                    geom[n["id"]] = {"x": col_x[c], "y": y, "w": nw, "h": hn,
                                     "cx": col_x[c] + nw / 2.0, "cy": y + hn / 2.0,
                                     "col": c, "bcol": c % maxcols, "band": b,
                                     "type": n.get("type", "process")}
                    y += hn + rowgap
        bands_meta[b] = {"y_base": yb, "h": band_h, "cols": bcols,
                         "group_top_pad": 0.0, "group_bot_pad": 0.0}
        yb = yb + band_h + bandgap

    bottom = max((gg["y"] + gg["h"] for gg in geom.values()), default=t_top)

    # 若同一 group 节点位于同一带且外接框不侵入其他节点/其他分组框，则自动绘制子系统/阶段虚线背景容器
    group_prims = []
    drawn_group_boxes = []
    clustered_groups = set()
    for gname in groups:
        gnodes = [n for n in nodes if str(n.get("group") or "") == gname]
        if not gnodes:
            continue
        gbands = {geom[n["id"]]["band"] for n in gnodes}
        if len(gbands) != 1:
            continue
        gb = next(iter(gbands))
        gids = {n["id"] for n in gnodes}
        x0 = min(geom[n["id"]]["x"] for n in gnodes) - 12.0
        y0 = min(geom[n["id"]]["y"] for n in gnodes) - pad_top
        x1 = max(geom[n["id"]]["x"] + geom[n["id"]]["w"] for n in gnodes) + 12.0
        y1 = max(geom[n["id"]]["y"] + geom[n["id"]]["h"] for n in gnodes) + pad_bot
        if x0 < 10.0 or x1 > W - 10.0 or y0 < header_bot + 6.0:
            continue
        clash = False
        for oid, og in geom.items():
            if oid in gids:
                continue
            if x0 < og["x"] + og["w"] + 4 and og["x"] - 4 < x1 and y0 < og["y"] + og["h"] + 4 and og["y"] - 4 < y1:
                clash = True
                break
        if not clash:
            for bx0, by0, bx1, by1 in drawn_group_boxes:
                if x0 < bx1 + 4 and bx0 < x1 + 4 and y0 < by1 + 4 and by0 < y1 + 4:
                    clash = True
                    break
        if not clash:
            gc = gcolor_map[gname]
            drawn_group_boxes.append((x0, y0, x1, y1))
            clustered_groups.add(gname)
            bands_meta[gb]["group_top_pad"] = max(bands_meta[gb]["group_top_pad"], pad_top)
            bands_meta[gb]["group_bot_pad"] = max(bands_meta[gb]["group_bot_pad"], pad_bot)
            bottom = max(bottom, y1)
            group_prims.append(scene.R(x0, y0, x1 - x0, y1 - y0, fill="#F8FAFC", stroke=gc,
                                       sw=1.2, rx=10, dash="6,4", layer="frame",
                                       tag="group_box", id="grp_" + gname))
            glbl = sirmod.wrap_text(gname, 11.0, max((x1 - x0) - 20.0, 80.0), bold=True)[0]
            group_prims.append(scene.TX(x0 + 10.0, y0 + 15.0, glbl, size=11.0, weight="bold",
                                        anchor="start", fill=gc, layer="frame",
                                        tag="group_label", boxw=max((x1 - x0) - 20.0, 80.0)))

    node_prims = list(group_prims)
    for n in nodes:
        gg = geom[n["id"]]
        st = sirmod.NODE_STYLES.get(n.get("type", "process"), sirmod.NODE_STYLES["process"])
        pill = st[3] == "pill"
        meta = {"tag": "node", "id": n["id"]}
        src = n.get("source") or {}
        if src.get("quote"):
            meta["prov"] = src["quote"]
        if src.get("loc"):
            meta["prov_loc"] = src["loc"]
        rx_v = gg["h"] / 2.0 if pill else 9
        node_prims.append(scene.R(gg["x"] + 2.0, gg["y"] + 2.5, gg["w"], gg["h"], fill="#E2E8F0",
                                  stroke="none", sw=0, rx=rx_v, layer="frame", tag="shadow"))
        node_prims.append(scene.R(gg["x"], gg["y"], gg["w"], gg["h"], fill=st[0], stroke=st[1],
                                  sw=1.6, rx=rx_v, layer="nodes", **meta))
        icon = glyphs.draw(n, gg["x"] + 9, gg["cy"] - 13) if not pill else None
        tw = _text_w(n, nw)
        if icon:
            node_prims += icon[1]
            tx_x = gg["x"] + 48.0
            anchor = "start"
        else:
            tx_x = gg["cx"]
            anchor = "middle"
        lines = sirmod.wrap_text(n.get("label", ""), FS_LABEL, tw, bold=True)
        attrs = n.get("attrs") or {}
        attr_lines = []
        for k, v in attrs.items():
            attr_lines += sirmod.wrap_text("%s: %s" % (k, v), FS_ATTR, tw)
        total_th = len(lines) * 17.5 + (len(attr_lines) * 15.0 + 4.0 if attr_lines else 0.0)
        ty = gg["cy"] - total_th / 2.0 + FS_LABEL * 0.92
        node_prims.append(scene.TX(tx_x, ty, "\n".join(lines),
                                   size=FS_LABEL, weight="bold", fill=st[2], layer="labels",
                                   node=n["id"], anchor=anchor, boxw=tw))
        if n.get("group") and str(n.get("group")) not in clustered_groups:
            gc = gcolor_map[str(n["group"])]
            node_prims.append(scene.R(gg["x"] + 0.8, gg["y"] + 3, 4.5, gg["h"] - 6, fill=gc,
                                      stroke="none", sw=0, rx=2, layer="nodes",
                                      tag="groupbar", id=n["id"]))
        step_s = str(n.get("step") or "").strip()
        if step_s:
            bw = max(20.0, sirmod.est_w(step_s, 10.0, True) + 10.0)
            bx = gg["x"] + 7.0
            by = gg["y"] - 9.0
            node_prims.append(scene.R(bx, by, bw, 17.0, fill=st[1], stroke="#FFFFFF",
                                      sw=1.2, rx=8.5, layer="nodes",
                                      tag="step_badge", id=n["id"] + "_step"))
            node_prims.append(scene.TX(bx + bw / 2.0, by + 12.2, step_s, size=10.0, weight="bold",
                                       fill="#FFFFFF", anchor="middle", layer="labels",
                                       tag="step_badge_text", node=n["id"]))
        yy = ty + (len(lines) - 1) * 17.5 + 16.5
        for ln in attr_lines:
            node_prims.append(scene.TX(tx_x, yy, ln, size=FS_ATTR, fill="#4A5568",
                                       layer="labels", node=n["id"], anchor=anchor, boxw=tw))
            yy += 15.0

    for n in nodes:
        if n.get("group") and str(n.get("group")) in clustered_groups:
            geom[n["id"]]["in_group_box"] = True

    return {"geom": geom, "node_prims": node_prims, "col_x": col_x, "W": W,
            "bands": bands_meta, "bottom": bottom, "ncols": ncols,
            "cols": cols, "layer": layer, "maxcols": maxcols,
            "gcolor_map": gcolor_map, "clustered_groups": clustered_groups}
