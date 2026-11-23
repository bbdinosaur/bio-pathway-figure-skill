#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""layout_edges.py — flow 边布线：笔直邻列 / 避障同列 / 右出带间折返 / 避障底总线回流 / 顶通道跨列。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene
import sir as sirmod


def _has_node_between_y(geom, col, y1, y2, exclude_ids):
    lo, hi = min(y1, y2), max(y1, y2)
    for nid, gg in geom.items():
        if nid in exclude_ids or gg["col"] != col:
            continue
        if gg["y"] + gg["h"] > lo + 2 and gg["y"] < hi - 2:
            return True
    return False


def _has_node_below(geom, node_id):
    g = geom[node_id]
    for nid, gg in geom.items():
        if nid != node_id and gg["col"] == g["col"] and gg["band"] == g["band"] and gg["y"] >= g["y"] + g["h"] - 2:
            return True
    return False


def _has_node_above(geom, node_id):
    g = geom[node_id]
    for nid, gg in geom.items():
        if nid != node_id and gg["col"] == g["col"] and gg["band"] == g["band"] and gg["y"] + gg["h"] <= g["y"] + 2:
            return True
    return False


def route_edges(sird, g):
    edges, labels = [], []
    bus_ys = []
    geom, col_x, bands, W = g["geom"], g["col_x"], g["bands"], g["W"]
    links = sird.get("links", [])
    per_gap, per_bus, per_wrap, per_top, per_lbl, per_same = {}, {}, {}, {}, {}, {}

    # 统计每个节点的扇入/扇出与左进/右出端口排序，避免多条箭头/T-bar 叠压在同一端点
    out_deg, in_deg = {}, {}
    left_in_map, right_out_map = {}, {}
    col_has_drop = set()
    for idx_e, e in enumerate(links):
        a0, b0 = geom[e["from"]], geom[e["to"]]
        k0 = e.get("kind", "material")
        if k0 != "loop":
            out_deg[e["from"]] = out_deg.get(e["from"], 0) + 1
            in_deg[e["to"]] = in_deg.get(e["to"], 0) + 1
        ba0, bb0 = a0["band"], b0["band"]
        ca0, cb0 = a0["col"], b0["col"]
        is_wf = bb0 > ba0
        is_wb = bb0 < ba0
        is_sb = (ba0 == bb0) and ((cb0 < ca0) or (k0 == "loop" and cb0 <= ca0))
        is_sc = (ca0 == cb0) and (ba0 == bb0) and (k0 != "loop")
        is_adj = (cb0 == ca0 + 1) and (ba0 == bb0) and not is_sb
        is_top_skip = not is_wf and not is_wb and not is_sb and not is_sc and not is_adj
        # 哪些边会进入 b0 的左侧边
        enters_left = (
            is_wf
            or is_adj
            or (is_wb and (b0["bcol"] == 0 or _has_node_below(geom, e["to"])))
            or (is_sb and _has_node_below(geom, e["to"]))
            or (is_top_skip and _has_node_above(geom, e["to"]))
        )
        if (is_top_skip and _has_node_above(geom, e["to"])) or (is_sb and _has_node_below(geom, e["to"])) or (is_wb and _has_node_below(geom, e["to"])):
            col_has_drop.add((bb0, cb0))
        if enters_left:
            # 回流/反馈边放最下方，顶跨列放最上方，其余按源节点 y 排序，尽量减少交叉
            if is_wb or is_sb or k0 == "loop":
                sort_y = 1e6 + a0["cy"]
            elif is_top_skip:
                sort_y = -1e6 + a0["cy"]
            else:
                sort_y = a0["cy"]
            left_in_map.setdefault(e["to"], []).append((sort_y, idx_e))
        exits_right = (
            is_adj
            or is_wf
            or (is_wb and _has_node_below(geom, e["from"]))
            or (is_sb and _has_node_below(geom, e["from"]))
            or (is_top_skip and _has_node_above(geom, e["from"]))
        )
        if exits_right:
            right_out_map.setdefault(e["from"], []).append((b0["cy"], idx_e))

    in_port_y, out_port_y = {}, {}
    def _is_straight_adj(idx_e):
        e0 = links[idx_e]
        a0, b0 = geom[e0["from"]], geom[e0["to"]]
        return (a0["band"] == b0["band"] and b0["col"] == a0["col"] + 1
                and e0.get("kind", "material") != "loop" and abs(a0["cy"] - b0["cy"]) <= 1.5)

    for nid, items in left_in_map.items():
        if len(items) <= 1:
            continue
        items.sort()
        gg = geom[nid]
        step = min(16.0, max(10.0, (gg["h"] - 26.0) / float(len(items))))
        y_lo, y_hi = gg["y"] + 10.0, gg["y"] + gg["h"] - 10.0
        straight = [it for it in items if _is_straight_adj(it[1])]
        if len(straight) == 1:
            st_idx = straight[0][1]
            in_port_y[st_idx] = gg["cy"]
            above = [it for it in items if it[1] != st_idx and it[0] < gg["cy"]]
            below = [it for it in items if it[1] != st_idx and it[0] >= gg["cy"]]
            for r, (_, idx_e) in enumerate(reversed(above)):
                in_port_y[idx_e] = max(y_lo, gg["cy"] - (r + 1) * step)
            for r, (_, idx_e) in enumerate(below):
                in_port_y[idx_e] = min(y_hi, gg["cy"] + (r + 1) * step)
        else:
            mid = (len(items) - 1) / 2.0
            for rank, (_, idx_e) in enumerate(items):
                in_port_y[idx_e] = gg["cy"] + (rank - mid) * step
    for nid, items in right_out_map.items():
        if len(items) <= 1:
            continue
        items.sort()
        gg = geom[nid]
        step = min(14.0, max(8.0, (gg["h"] - 30.0) / float(len(items))))
        y_lo, y_hi = gg["y"] + 10.0, gg["y"] + gg["h"] - 10.0
        straight = [it for it in items if _is_straight_adj(it[1])]
        if len(straight) == 1:
            st_idx = straight[0][1]
            out_port_y[st_idx] = gg["cy"]
            above = [it for it in items if it[1] != st_idx and it[0] < gg["cy"]]
            below = [it for it in items if it[1] != st_idx and it[0] >= gg["cy"]]
            for r, (_, idx_e) in enumerate(reversed(above)):
                out_port_y[idx_e] = max(y_lo, gg["cy"] - (r + 1) * step)
            for r, (_, idx_e) in enumerate(below):
                out_port_y[idx_e] = min(y_hi, gg["cy"] + (r + 1) * step)
        else:
            mid = (len(items) - 1) / 2.0
            for rank, (_, idx_e) in enumerate(items):
                out_port_y[idx_e] = gg["cy"] + (rank - mid) * step

    for i, e in enumerate(links):
        a, b = geom[e["from"]], geom[e["to"]]
        kind = e.get("kind", "material")
        ls = sirmod.LINK_STYLES.get(kind, sirmod.LINK_STYLES["material"])
        color, dash = ls[0], ls[1]
        uyc = out_port_y.get(i, a["cy"])
        vyc = in_port_y.get(i, b["cy"])
        ca, cb = a["col"], b["col"]
        ba, bb = a["band"], b["band"]

        meta = {"tag": "edge", "id": "e%d" % i, "from": e["from"], "to": e["to"], "kind": kind}
        src = e.get("source") or {}
        if src.get("quote"):
            meta["prov"] = src["quote"]
        if src.get("loc"):
            meta["prov_loc"] = src["loc"]

        wrap_fwd = bb > ba
        wrap_back = bb < ba
        same_band_back = (ba == bb) and ((cb < ca) or (kind == "loop" and cb <= ca))
        same_col = (ca == cb) and (ba == bb) and (kind != "loop")
        pts, lxy = None, None
        lbl_anchor = "middle"

        if wrap_fwd:
            k = per_wrap.get(ba, 0)
            per_wrap[ba] = k + 1
            band_bot = bands[ba]["y_base"] + bands[ba]["h"] + bands[ba].get("group_bot_pad", 0.0)
            next_top = bands[bb]["y_base"] - bands[bb].get("group_top_pad", 0.0)
            wy = min(band_bot + 28.0 + (k % 4) * 18.0, next_top - 18.0)
            gxa = min(W - 18.0, a["x"] + a["w"] + 22.0 + 10.0 * (k % 3))
            gxb = max(18.0, b["x"] - 24.0 - 10.0 * (k % 3))
            pts = [(a["x"] + a["w"], uyc), (gxa, uyc), (gxa, wy),
                   (gxb, wy), (gxb, vyc), (b["x"], vyc)]
            frac = (0.50, 0.32, 0.68)[k % 3]
            lxy = (gxb + (gxa - gxb) * frac, wy - 7.0)

        elif wrap_back:
            k = per_bus.get(("wb", ba), 0)
            per_bus[("wb", ba)] = k + 1
            bus_y = bands[ba]["y_base"] + bands[ba]["h"] + bands[ba].get("group_bot_pad", 0.0) + 24.0 + (k % 4) * 18.0
            bus_ys.append(bus_y)
            gx_left = max(16.0, min(b["x"] - 24.0, 40.0 - 8.0 * (k % 3)))
            # 若源节点同列下方还有节点，从源右侧外绕下到 bus_y，避免穿框
            if _has_node_below(geom, e["from"]):
                sx = a["x"] + a["w"] + 16.0 + 8.0 * (k % 2)
                start_pts = [(a["x"] + a["w"], uyc), (sx, uyc), (sx, bus_y)]
                lx_mid = (sx + gx_left) / 2.0
            else:
                start_pts = [(a["cx"], a["y"] + a["h"]), (a["cx"], bus_y)]
                lx_mid = (a["cx"] + gx_left) / 2.0
            if b["bcol"] == 0:
                end_pts = [(gx_left, bus_y), (gx_left, vyc), (b["x"], vyc)]
            else:
                mid_y = bands[bb]["y_base"] + bands[bb]["h"] + bands[bb].get("group_bot_pad", 0.0) + 18.0 + (k % 3) * 16.0
                if _has_node_below(geom, e["to"]):
                    tx = b["x"] - 16.0
                    end_pts = [(gx_left, bus_y), (gx_left, mid_y), (tx, mid_y), (tx, vyc), (b["x"], vyc)]
                else:
                    end_pts = [(gx_left, bus_y), (gx_left, mid_y), (b["cx"], mid_y), (b["cx"], b["y"] + b["h"])]
            pts = start_pts + end_pts
            lxy = (lx_mid, bus_y - 7.0)

        elif same_band_back:
            k = per_bus.get(("sb", ba), 0)
            per_bus[("sb", ba)] = k + 1
            bus_y = bands[ba]["y_base"] + bands[ba]["h"] + bands[ba].get("group_bot_pad", 0.0) + 22.0 + (k % 5) * 18.0
            bus_ys.append(bus_y)
            if _has_node_below(geom, e["from"]):
                sx = a["x"] + a["w"] + 16.0
                p_start = [(a["x"] + a["w"], uyc), (sx, uyc), (sx, bus_y)]
                x_s = sx
            else:
                p_start = [(a["cx"], a["y"] + a["h"]), (a["cx"], bus_y)]
                x_s = a["cx"]
            if _has_node_below(geom, e["to"]):
                pad_g = 22.0 if b.get("in_group_box") else 16.0
                tx = b["x"] - pad_g - 8.0 * (k % 2)
                p_end = [(tx, bus_y), (tx, vyc), (b["x"], vyc)]
                x_t = tx
            else:
                p_end = [(b["cx"], bus_y), (b["cx"], b["y"] + b["h"])]
                x_t = b["cx"]
            pts = p_start + p_end
            lxy = ((x_s + x_t) / 2.0, bus_y - 7.0)

        elif same_col:
            k = per_same.get(ca, 0)
            per_same[ca] = k + 1
            blocked = _has_node_between_y(geom, ca, uyc, vyc, {e["from"], e["to"]})
            if blocked:
                # 中间夹着同列节点时，走左侧外廊绕行，零穿框
                gx = max(16.0, a["x"] - 22.0 - 10.0 * (k % 3))
                pts = [(a["x"], uyc), (gx, uyc), (gx, vyc), (b["x"], vyc)]
                lxy = (gx - 4.0 if gx > 60 else gx + 6.0, (uyc + vyc) / 2.0)
                lbl_anchor = "end" if gx > 60 else "start"
            else:
                dx = (k // 2) * 14.0 * (1 if k % 2 == 0 else -1)
                if b["y"] >= a["y"]:
                    pts = [(a["cx"] + dx, a["y"] + a["h"]), (b["cx"] + dx, b["y"])]
                    lxy = (a["cx"] + dx + 8.0, (a["y"] + a["h"] + b["y"]) / 2.0 + 4.0)
                else:
                    pts = [(a["cx"] + dx, a["y"]), (b["cx"] + dx, b["y"] + b["h"])]
                    lxy = (a["cx"] + dx + 8.0, (a["y"] + b["y"] + b["h"]) / 2.0 + 4.0)
                lbl_anchor = "start"

        elif cb == ca + 1 and ba == bb:
            pair_key = (e["from"], e["to"])
            pk = per_lbl.get(("pair", pair_key), 0)
            per_lbl[("pair", pair_key)] = pk + 1
            if abs(uyc - vyc) <= 1.5:
                pts = [(a["x"] + a["w"], uyc), (b["x"], vyc)]
                key = (cb, round(uyc / 10.0))
                j = per_lbl.get(key, 0)
                per_lbl[key] = j + 1
                # 平行双边上下错开标签（第 1 条在上方，第 2 条在下方），杜绝标签重叠
                if pk == 1:
                    lxy = ((a["x"] + a["w"] + b["x"]) / 2.0, uyc + 14.0)
                else:
                    lxy = ((a["x"] + a["w"] + b["x"]) / 2.0, uyc - 9.0 - 14.0 * j)
            else:
                k = per_gap.get(cb, 0)
                per_gap[cb] = k + 1
                gap_w = b["x"] - (a["x"] + a["w"])
                chx = a["x"] + a["w"] + max(24.0, gap_w * (0.56 + 0.10 * ((k % 3) - 1)))
                pts = [(a["x"] + a["w"], uyc), (chx, uyc), (chx, vyc), (b["x"], vyc)]
                # 多输入汇入同一目标 → 标签放源出线段；单源分叉多目标 → 标签贴目标进线段右对齐（若有垂直跨列通道则自动左退避让）
                dy_lbl = 14.0 if (pk % 2 == 1 or (uyc > vyc and in_deg.get(e["to"], 0) > 1)) else -8.0
                if in_deg.get(e["to"], 0) > 1 and out_deg.get(e["from"], 0) == 1:
                    lxy = (a["x"] + a["w"] + 6.0, uyc + dy_lbl)
                    lbl_anchor = "start"
                else:
                    rx_pad = 28.0 if (bb, cb) in col_has_drop else 6.0
                    lxy = (b["x"] - rx_pad, vyc + dy_lbl)
                    lbl_anchor = "end"

        else:
            k = per_top.get(ba, 0)
            per_top[ba] = k + 1
            ty = bands[ba]["y_base"] - bands[ba].get("group_top_pad", 0.0) - 18.0 - (k % 3) * 14.0
            if _has_node_above(geom, e["from"]):
                pad_s = 22.0 if a.get("in_group_box") else 16.0
                sx = a["x"] + a["w"] + pad_s + 8.0 * (k % 2)
                p_start = [(a["x"] + a["w"], uyc), (sx, uyc), (sx, ty)]
                x_s = sx
            else:
                p_start = [(a["cx"], a["y"]), (a["cx"], ty)]
                x_s = a["cx"]
            if _has_node_above(geom, e["to"]):
                pad_t = 22.0 if b.get("in_group_box") else 16.0
                tx = b["x"] - pad_t - 8.0 * (k % 2)
                p_end = [(tx, ty), (tx, vyc), (b["x"], vyc)]
                x_t = tx
            else:
                p_end = [(b["cx"], ty), (b["cx"], b["y"])]
                x_t = b["cx"]
            pts = p_start + p_end
            lxy = ((x_s + x_t) / 2.0, ty - 7.0)

        mk = str(e.get("marker") or "").strip()
        if not mk:
            if kind == "inhibit":
                mk = "tbar"
            elif e.get("bidirectional") or str(e.get("dir") or "").lower() in ("both", "bi", "bidirectional"):
                mk = "arrowboth"
            else:
                mk = "arrow"
        edges.append(scene.LN(pts, stroke=color, sw=2.0 if not dash else 1.85,
                              dash=dash, marker=mk, layer="links", **meta))
        lab = str(e.get("label") or "").strip()
        if lab and lxy:
            for ln in sirmod.wrap_text(lab, 11.2, 148)[:3]:
                labels.append(scene.TX(lxy[0], lxy[1], ln, size=11.2, fill="#2D3748",
                                       anchor=lbl_anchor, layer="labels", halo=True, edge="e%d" % i))
                lxy = (lxy[0], lxy[1] + 13.5)

    return {"edge_prims": edges, "labels": labels, "bus_ys": bus_ys}
