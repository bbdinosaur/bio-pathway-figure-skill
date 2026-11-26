#!/usr/bin/env python3
"""Content block renderers: text / callout / kpi / flow / mechanism / row / scalebar."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from gaconfig import EDGE, INK, INK2, MUT, esc
from gaicons import render_icon
from gaprims import label_bg, line, quad_arrow, rrect, seg_arrow, text, text_fit
from textmetrics import text_width, wrap_text


def _text_block(b, x, y, w, fs, accent):
    out, cy = [], y
    if b.get("heading"):
        out.append(text_fit(x, cy + fs, str(b["heading"]), w, fs, accent, weight="bold"))
        cy += fs * 1.45
    cy += fs * 0.95
    for item in b.get("items", []):
        lines = wrap_text(str(item), fs, w - 18)
        # Clean vertically centered accent dot aligned to first line cap-height
        out.append(f'<circle cx="{x+6:.1f}" cy="{cy - fs*0.32:.1f}" r="3.2" fill="{accent}"/>')
        for ln in lines:
            out.append(text(x + 17, cy, ln, fs, INK))
            cy += fs * 1.38
        cy += fs * 0.25
    return "".join(out), max(cy - y - fs * 0.6, fs * 1.4)


def _callout_block(b, x, y, w, fs, accent):
    """Compact visual highlight card with optional scientific icon + title + body."""
    icon = b.get("icon", "")
    title = str(b.get("title", "")).strip()
    body = str(b.get("body", b.get("text", ""))).strip()
    ix = 38 if icon else 10
    tw = w - ix - 10
    t_lines = wrap_text(title, fs, tw) if title else []
    b_lines = wrap_text(body, max(10.0, fs - 0.8), tw) if body else []
    th = len(t_lines) * fs * 1.28
    bh = len(b_lines) * max(10.0, fs - 0.8) * 1.32
    pad = 9
    card_h = max(44.0 if icon else 28.0, pad * 2 + th + (4 if (th and bh) else 0) + bh)
    col = b.get("color") or accent
    out = [rrect(x, y, w, card_h, rx=8, fill=b.get("fill", "#FFFFFF"),
                 stroke=col, sw=1.2),
           rrect(x, y + 6, 4, card_h - 12, rx=2, fill=col)]
    if icon:
        out.append(render_icon(icon, x + 21, y + card_h / 2, r=12.5, color=col))
    cy = y + pad
    for ln in t_lines:
        out.append(text(x + ix, cy + fs * 0.92, ln, fs, INK, weight="bold"))
        cy += fs * 1.28
    if th and bh:
        cy += 3
    bfs = max(10.0, fs - 0.8)
    for ln in b_lines:
        out.append(text(x + ix, cy + bfs * 0.92, ln, bfs, INK2))
        cy += bfs * 1.32
    return "".join(out), card_h + 2


def _kpi_block(b, x, y, w, fs, accent):
    """Zero-truncation KPI metric cards (row or vertical stack)."""
    items = b.get("items", [])
    if not items:
        return "", 0.0
    if b.get("layout") == "row" and len(items) > 1:
        out = []
        n = len(items)
        gap = 10
        colw = (w - gap * (n - 1)) / n
        kfs = min(fs + 8, 25)
        lfs = max(10.0, fs - 1.2)
        wrapped = []
        box_h = 0.0
        for it in items:
            lab = str(it.get("label", ""))
            lns = wrap_text(lab, lfs, colw - 14)  # NEVER truncate!
            wrapped.append(lns)
            h_i = 10 + kfs + 7 + len(lns) * (lfs * 1.28) + 8
            box_h = max(box_h, h_i)
        for i, it in enumerate(items):
            cx = x + i * (colw + gap)
            v = str(it.get("value", ""))
            col = it.get("color") or accent
            out.append(rrect(cx, y, colw, box_h, rx=8, fill="#FFFFFF",
                             stroke=EDGE, sw=1.0))
            out.append(rrect(cx + 8, y + 1, colw - 16, 3.2, rx=1.6, fill=col))
            out.append(text_fit(cx + colw / 2, y + 10 + kfs * 0.92, v,
                                colw - 12, kfs, col, "middle", weight="bold"))
            cy2 = y + 10 + kfs + 7
            for ln in wrapped[i]:
                out.append(text(cx + colw / 2, cy2 + lfs * 0.88, ln, lfs, MUT, "middle"))
                cy2 += lfs * 1.28
        return "".join(out), box_h + 4
    out, cy = [], y
    kfs = min(fs + 9, 27)
    lfs = max(10.0, fs - 0.8)
    for it in items:
        v, lab = str(it.get("value", "")), str(it.get("label", ""))
        col = it.get("color") or accent
        lns = wrap_text(lab, lfs, w - 20)
        ch = 8 + kfs + 5 + len(lns) * (lfs * 1.28) + 8
        out.append(rrect(x, cy, w, ch, rx=8, fill="#FFFFFF", stroke=EDGE, sw=1.0))
        out.append(rrect(x, cy + 6, 4, ch - 12, rx=2, fill=col))
        out.append(text_fit(x + 12, cy + 8 + kfs * 0.9, v, w - 22, kfs, col, weight="bold"))
        cy2 = cy + 8 + kfs + 5
        for ln in lns:
            out.append(text(x + 12, cy2 + lfs * 0.88, ln, lfs, MUT))
            cy2 += lfs * 1.28
        cy += ch + 8
    return "".join(out), cy - y - 4


def _flow_block(b, x, y, w, avail_h, fs, accent):
    """Numbered workflow chain (supports plain strings or {text, icon, sub} dicts)."""
    raw_steps = b.get("steps", [])
    numbered = b.get("numbered", True)
    fill = b.get("fill", False)
    gap = max(12.0, fs * 0.95)
    out, cy = [], y
    n = max(len(raw_steps), 1)
    parsed = []
    for st in raw_steps:
        if isinstance(st, dict):
            parsed.append((str(st.get("text", st.get("label", ""))),
                           st.get("icon", ""), str(st.get("sub", "")).strip()))
        else:
            parsed.append((str(st), "", ""))
    # Compute intrinsic heights; smart fill caps dead space per step
    intr = []
    for txt, ico, sub in parsed:
        pad_l = (30 if numbered else 10) + (28 if ico else 0)
        lns = wrap_text(txt, fs, w - pad_l - 8)
        slns = wrap_text(sub, max(10.0, fs - 1.5), w - pad_l - 8) if sub else []
        h0 = max(36.0 if ico else 28.0,
                 len(lns) * fs * 1.32 + len(slns) * max(10.0, fs - 1.5) * 1.25 + 14)
        intr.append((lns, slns, ico, pad_l, h0))
    total_intr = sum(it[4] for it in intr) + gap * (n - 1)
    extra_per = 0.0
    if fill and avail_h > total_intr:
        # Cap stretch so steps look balanced, never giant hollow boxes
        extra_per = min(28.0, (avail_h - total_intr) / n)

    for i, (lns, slns, ico, pad_l, h0) in enumerate(intr):
        nh = h0 + extra_per
        bx = x + (16 if numbered else 0)
        bw = w - (16 if numbered else 0)
        out.append(rrect(bx, cy, bw, nh, rx=7, fill="#FFFFFF", stroke=accent, sw=1.2))
        if numbered:
            out.append(f'<circle cx="{x+16:.1f}" cy="{cy+nh/2:.1f}" r="{fs*0.72:.1f}" '
                       f'fill="{accent}"/>')
            out.append(text(x + 16, cy + nh / 2 + fs * 0.35, str(i + 1),
                            max(10.0, fs - 1), "#FFFFFF", "middle", weight="bold"))
        if ico:
            out.append(render_icon(ico, bx + 22, cy + nh / 2, r=11.0, color=accent))
        sfs = max(10.0, fs - 1.5)
        content_h = len(lns) * fs * 1.32 + len(slns) * sfs * 1.25
        ty0 = cy + (nh - content_h) / 2
        tx = x + pad_l
        for j, ln in enumerate(lns):
            out.append(text(tx, ty0 + fs * 0.96 + j * fs * 1.32, ln, fs, INK))
        for j, sln in enumerate(slns):
            out.append(text(tx, ty0 + len(lns) * fs * 1.32 + sfs * 0.95 + j * sfs * 1.25,
                            sln, sfs, MUT))
        if i < n - 1:
            ax = bx + bw / 2
            out.append(seg_arrow(ax, cy + nh + 1, ax, cy + nh + gap - 1,
                                 "#94A3B8", 1.6, 6.5))
        cy += nh + gap
    return "".join(out), cy - y - gap + 2


def _topo_levels(nodes, edges):
    """Kahn topological levels (stable order, handles cycles gracefully)."""
    ids = [n.get("id", f"n{i}") for i, n in enumerate(nodes)]
    adj = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for e in edges:
        a, bb = e.get("from"), e.get("to")
        if a in adj and bb in indeg and a != bb:
            adj[a].append(bb)
            indeg[bb] += 1
    level = {}
    frontier = [i for i in ids if indeg[i] == 0] or ([ids[0]] if ids else [])
    lv = 0
    visited = set()
    while frontier:
        nxt = []
        for n in frontier:
            if n in visited:
                continue
            visited.add(n)
            level[n] = lv
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] <= 0 and m not in visited:
                    nxt.append(m)
        frontier = nxt
        lv += 1
    for i in ids:
        level.setdefault(i, lv)
    return level


def _edge_t(dx, dy, hw, hh):
    tx = hw / abs(dx) if abs(dx) > 1e-9 else 1e9
    ty = hh / abs(dy) if abs(dy) > 1e-9 else 1e9
    return min(tx, ty)


def _mech_block(b, x, y, w, h, fs, accent, diag=None):
    """Compartment-aware, collision-free scientific mechanism engine.

    Features:
      - Auto orientation LR (wide) vs TB (tall/narrow) so text never splits mid-word
      - Compartments/zones (e.g., Extracellular / Membrane / Cytoplasm / Nucleus)
      - Scientific vector icons on nodes + pill/rect shapes + subtitle lines
      - Typed edges: activate / inhibit (T-bar) / bidirectional / dashed
      - Curved quadratic Bezier skip-edges that arc around intermediate nodes
      - Strict bounding-box clamping + node-node collision prevention
      - Collision-free edge labels (checked against all nodes & placed labels)
    """
    nodes = b.get("nodes", [])
    edges = b.get("edges", [])
    zones = b.get("zones", [])
    legend = b.get("legend", [])
    if not nodes:
        return "", 0.0

    title_svg = ""
    mech_title = str(b.get("title", "")).strip()
    th_off = 0.0
    if mech_title:
        tfs = max(11.0, fs)
        title_svg = text_fit(x + 2, y + tfs * 0.95, mech_title, w - 4, tfs, INK, weight="bold")
        th_off = tfs * 1.45
        y, h = y + th_off, max(80.0, h - th_off)

    # Reserve top strip for optional stage ribbon & bottom strip for legend
    stages = [str(st).strip() for st in (b.get("stages") or []) if str(st).strip()]
    stage_h = 26.0 if stages else 0.0
    leg_h = 24.0 if legend else 0.0
    zone_top_pad = (24.0 if zones else 4.0) + stage_h
    # Reserve vertical band for skip-edge / feedback / mutual-pair arcs
    level = _topo_levels(nodes, edges)
    edge_pairs = {(e.get("from"), e.get("to")) for e in edges}
    def _needs_curve(a_id, b_id):
        la, lb = level.get(a_id, 0), level.get(b_id, 0)
        return abs(lb - la) > 1 or lb < la or (b_id, a_id) in edge_pairs
    has_skip = any(_needs_curve(e.get("from"), e.get("to")) for e in edges)
    arc_pad = 36.0 if has_skip else 6.0

    # Decide orientation: LR vs TB
    n_lv = max(level.values(), default=0) + 1
    req_dir = str(b.get("direction", "auto")).upper()
    if req_dir in ("LR", "TB"):
        orient = req_dir
    else:
        # Use TB if panel is tall/narrow or too many levels to fit comfortably wide
        orient = "TB" if (w < h * 0.92 or (n_lv >= 4 and w < 560)) else "LR"

    # Build groups per level + 1-pass barycenter crossing reduction
    groups = {}
    for nd in nodes:
        nid = nd.get("id", "")
        groups.setdefault(level[nid], []).append(nd)
    lv_keys = sorted(groups.keys())
    if len(lv_keys) >= 2:
        order_idx = {}
        for pos_i, nd in enumerate(groups[lv_keys[0]]):
            order_idx[nd.get("id", "")] = float(pos_i)
        preds = {}
        for ed in edges:
            preds.setdefault(ed.get("to"), []).append(ed.get("from"))
        for k in lv_keys[1:]:
            gk = groups[k]
            if len(gk) > 1:
                def _bary(nd, orig_i):
                    nid = nd.get("id", "")
                    ps = [order_idx[p] for p in preds.get(nid, []) if p in order_idx]
                    return (sum(ps) / len(ps), orig_i) if ps else (float(orig_i), orig_i)
                groups[k] = [nd for _, nd in sorted(
                    ((_bary(nd, i), nd) for i, nd in enumerate(gk)), key=lambda t: t[0])]
            for pos_i, nd in enumerate(groups[k]):
                order_idx[nd.get("id", "")] = float(pos_i)
    max_per_lv = max((len(groups[k]) for k in lv_keys), default=1)

    # Effective drawable region inside (x, y, w, h)
    pad_x = 8.0
    pad_top = zone_top_pad + (arc_pad if orient == "LR" else 4.0)
    pad_bot = leg_h + 12.0 + (arc_pad if (orient == "LR" and has_skip) else 4.0)
    uw = max(80.0, w - 2 * pad_x - (arc_pad if (orient == "TB" and has_skip) else 0.0))
    uh = max(80.0, h - pad_top - pad_bot)

    # Pick optimal mechanism font size that avoids mid-word splits and fits tightly
    def _layout_try(mfs):
        sfs = max(10.0, mfs - 2.0)
        if orient == "LR":
            hgap = 26.0 if any(e.get("label") for e in edges) else 18.0
            vgap = 14.0
            # Max node width per column
            max_cw = max(72.0, (uw - hgap * max(n_lv - 1, 0)) / max(n_lv, 1))
            sizes = {}
            col_ws = {}
            single_row_tall = (uh > 165.0 and all(len(groups[k]) == 1 for k in lv_keys))
            spacious_hero = (uw > 650.0 and uh > 140.0 and max_per_lv <= 2)
            for k in lv_keys:
                cw = 0.0
                for nd in groups[k]:
                    nid = nd.get("id", "")
                    ico_w = 28.0 if (nd.get("icon") and spacious_hero) else (24.0 if nd.get("icon") else 0.0)
                    lbl = str(nd.get("label", nid))
                    sub = str(nd.get("sub", "")).strip()
                    req_w = float(nd.get("w", 0))
                    # Aim for natural width covering BOTH label and subtitle, capped by max_cw
                    sub_w = text_width(sub, sfs) if sub else 0.0
                    wide_bonus = 34.0 if (spacious_hero and n_lv <= 4) else (24.0 if (uw > 620.0 and n_lv <= 4) else 0.0)
                    nat_cap = 290.0 if spacious_hero else 255.0
                    nat_w = min(max_cw, max(req_w or 0, min(nat_cap, max(text_width(lbl, mfs), sub_w) + 34 + ico_w + wide_bonus)))
                    nw = max(92.0 if spacious_hero else 84.0, min(max_cw, nat_w))
                    lns = wrap_text(lbl, mfs, nw - 18 - ico_w)
                    slns = wrap_text(sub, sfs, nw - 18 - ico_w) if sub else []
                    min_nh = 62.0 if single_row_tall else (50.0 if spacious_hero else (36.0 if ico_w else 30.0))
                    nh = max(min_nh,
                             len(lns) * mfs * 1.26 + len(slns) * sfs * 1.2 + (22 if single_row_tall else (18 if spacious_hero else 14)))
                    sizes[nid] = (lns, slns, nw, nh)
                    cw = max(cw, nw)
                col_ws[k] = cw
            tot_w = sum(col_ws[k] for k in lv_keys) + hgap * max(n_lv - 1, 0)
            max_col_h = max(sum(sizes[nd["id"]][3] for nd in groups[k])
                            + vgap * max(len(groups[k]) - 1, 0) for k in lv_keys)
            fits = (tot_w <= uw + 1.0) and (max_col_h <= uh + 1.0)
            # Compute positions — align columns directly under stage ribbons when 1:1 matched!
            pos = {}
            col_xs = None
            if stages and len(stages) == n_lv and n_lv >= 2:
                sgap_st = 12.0
                sw_st = max(40.0, (w - 8 - sgap_st * (n_lv - 1)) / n_lv)
                cand_xs = []
                ok_st = True
                for si, k in enumerate(lv_keys):
                    st_cx = x + 4 + si * (sw_st + sgap_st) + sw_st / 2
                    cx_i = max(x + pad_x, min(x + pad_x + uw - col_ws[k], st_cx - col_ws[k] / 2))
                    if cand_xs and cx_i < cand_xs[-1] + col_ws[lv_keys[si - 1]] + hgap * 0.85:
                        ok_st = False
                        break
                    cand_xs.append(cx_i)
                if ok_st:
                    col_xs = cand_xs
            if col_xs is None:
                eff_hgap = hgap
                if n_lv > 1 and tot_w < uw:
                    gap_cap = 210.0 if uw > 620.0 else 130.0
                    eff_hgap = min(gap_cap, hgap + (uw - tot_w) / (n_lv - 1) * 0.82)
                tot_w2 = sum(col_ws[k] for k in lv_keys) + eff_hgap * max(n_lv - 1, 0)
                cx = x + pad_x + max(0.0, (uw - tot_w2) / 2)
                col_xs = []
                for k in lv_keys:
                    col_xs.append(cx)
                    cx += col_ws[k] + eff_hgap
            for k, cx in zip(lv_keys, col_xs):
                cw = col_ws[k]
                gk = groups[k]
                sum_nh = sum(sizes[nd["id"]][3] for nd in gk)
                eff_vgap = vgap
                if len(gk) > 1 and (sum_nh + vgap * (len(gk) - 1)) < uh:
                    eff_vgap = min(64.0, vgap + (uh - sum_nh - vgap * (len(gk) - 1)) / (len(gk) - 1) * 0.55)
                col_h = sum_nh + eff_vgap * max(len(gk) - 1, 0)
                cy = y + pad_top + max(0.0, (uh - col_h) / 2)
                for nd in gk:
                    nid = nd["id"]
                    _, _, nw, nh = sizes[nid]
                    pos[nid] = (cx + (cw - nw) / 2, cy, nw, nh)
                    cy += nh + eff_vgap
            return fits, sizes, pos
        else:  # TB orientation (levels top -> bottom)
            vgap = 26.0 if any(e.get("label") for e in edges) else 18.0
            hgap = 14.0
            sizes = {}
            row_hs = {}
            for k in lv_keys:
                m = len(groups[k])
                max_nw = max(84.0, (uw - hgap * max(m - 1, 0)) / max(m, 1))
                rh = 0.0
                for nd in groups[k]:
                    nid = nd.get("id", "")
                    ico_w = 24.0 if nd.get("icon") else 0.0
                    lbl = str(nd.get("label", nid))
                    sub = str(nd.get("sub", "")).strip()
                    sub_w = text_width(sub, sfs) if sub else 0.0
                    nat_w = min(max_nw, max(110.0, max(text_width(lbl, mfs), sub_w) + 26 + ico_w))
                    nw = max(84.0, min(max_nw, nat_w))
                    lns = wrap_text(lbl, mfs, nw - 16 - ico_w)
                    slns = wrap_text(sub, sfs, nw - 16 - ico_w) if sub else []
                    nh = max(34.0 if ico_w else 28.0,
                             len(lns) * mfs * 1.26 + len(slns) * sfs * 1.2 + 12)
                    sizes[nid] = (lns, slns, nw, nh)
                    rh = max(rh, nh)
                row_hs[k] = rh
            tot_h = sum(row_hs[k] for k in lv_keys) + vgap * max(n_lv - 1, 0)
            fits = tot_h <= uh + 1.0
            eff_vgap = vgap
            if n_lv > 1 and tot_h < uh:
                eff_vgap = min(46.0, vgap + (uh - tot_h) / (n_lv - 1))
            tot_h2 = sum(row_hs[k] for k in lv_keys) + eff_vgap * max(n_lv - 1, 0)
            pos = {}
            cy = y + pad_top + max(0.0, (uh - tot_h2) / 2)
            for k in lv_keys:
                rh = row_hs[k]
                row_w = (sum(sizes[nd["id"]][2] for nd in groups[k])
                         + hgap * max(len(groups[k]) - 1, 0))
                cx = x + pad_x + max(0.0, (uw - row_w) / 2)
                for nd in groups[k]:
                    nid = nd["id"]
                    _, _, nw, nh = sizes[nid]
                    pos[nid] = (cx, cy + (rh - nh) / 2, nw, nh)
                    cx += nw + hgap
                cy += rh + eff_vgap
            return fits, sizes, pos

    # Check if ALL nodes specify explicit nx, ny
    all_explicit = all("nx" in nd and "ny" in nd for nd in nodes)
    mfs = min(fs, 13.0)
    if all_explicit:
        sfs = max(10.0, mfs - 2.0)

        def _build_explicit(scale):
            sz, ps = {}, {}
            for nd in nodes:
                nid = nd["id"]
                ico_w = 24.0 if nd.get("icon") else 0.0
                nw = max(72.0, min(w * 0.42, float(nd.get("w", 130)) * scale))
                lns = wrap_text(str(nd.get("label", nid)), mfs, nw - 16 - ico_w)
                slns = wrap_text(str(nd.get("sub", "")).strip(), sfs, nw - 16 - ico_w) if nd.get("sub") else []
                nh = max(34.0 if ico_w else 28.0,
                         len(lns) * mfs * 1.26 + len(slns) * sfs * 1.2 + 12)
                sz[nid] = (lns, slns, nw, nh)
                px = x + pad_x + max(0.0, min(1.0, float(nd["nx"]))) * max(0.0, uw - nw)
                py = y + pad_top + max(0.0, min(1.0, float(nd["ny"]))) * max(0.0, uh - nh)
                ps[nid] = [px, py, nw, nh]
            return sz, ps

        def _has_overlap(ps, gap=8.0):
            keys = list(ps.keys())
            for ii in range(len(keys)):
                ax, ay, aw, ah = ps[keys[ii]]
                for jj in range(ii + 1, len(keys)):
                    bx, by, bw2, bh2 = ps[keys[jj]]
                    if ax < bx + bw2 + gap and ax + aw + gap > bx and ay < by + bh2 + gap and ay + ah + gap > by:
                        return True
            return False

        sizes, pos_mut = _build_explicit(1.0)
        for sc in (0.90, 0.82, 0.75):
            if not _has_overlap(pos_mut, 6.0):
                break
            sizes, pos_mut = _build_explicit(sc)
        # Deterministic pairwise separation if explicit coords still collide
        keys = list(pos_mut.keys())
        for _ in range(18):
            moved = False
            for ii in range(len(keys)):
                for jj in range(ii + 1, len(keys)):
                    a0, b0 = pos_mut[keys[ii]], pos_mut[keys[jj]]
                    ox = min(a0[0] + a0[2] + 8, b0[0] + b0[2] + 8) - max(a0[0], b0[0])
                    oy = min(a0[1] + a0[3] + 8, b0[1] + b0[3] + 8) - max(a0[1], b0[1])
                    if ox > 0 and oy > 0:
                        moved = True
                        if ox <= oy:
                            push = ox / 2.0 + 1.0
                            if a0[0] + a0[2] / 2 <= b0[0] + b0[2] / 2:
                                a0[0] -= push
                                b0[0] += push
                            else:
                                a0[0] += push
                                b0[0] -= push
                        else:
                            push = oy / 2.0 + 1.0
                            if a0[1] + a0[3] / 2 <= b0[1] + b0[3] / 2:
                                a0[1] -= push
                                b0[1] += push
                            else:
                                a0[1] += push
                                b0[1] -= push
                        for box0 in (a0, b0):
                            box0[0] = max(x + pad_x, min(x + w - pad_x - box0[2], box0[0]))
                            box0[1] = max(y + pad_top, min(y + h - leg_h - 6 - box0[3], box0[1]))
            if not moved:
                break
        pos = {k: tuple(v) for k, v in pos_mut.items()}
    else:
        sizes, pos = {}, {}
        for cand_fs in (min(fs, 14.0 if uh > 200 else 13.0), 13.0, 12.0, 11.0, 10.0):
            fits, sz, ps = _layout_try(cand_fs)
            mfs, sizes, pos = cand_fs, sz, ps
            if fits:
                break

    sfs = max(10.0, mfs - 2.0)
    node_label_map = {nd.get("id", ""): str(nd.get("label", nd.get("id", ""))) for nd in nodes}
    out = []
    # 0. Optional top stage ribbon (e.g. ["1. Perturbation", "2. Signaling", "3. Phenotype"])
    placed_labels = []  # [(rx0, ry0, rx1, ry1)] includes stage pills & zone headers
    if stages:
        ns = len(stages)
        sgap = 12.0
        sw_st = max(40.0, (w - 8 - sgap * (ns - 1)) / ns)
        sy_st = y + 2
        for si, st_txt in enumerate(stages):
            sx_st = x + 4 + si * (sw_st + sgap)
            out.append(rrect(sx_st, sy_st, sw_st, 20.0, rx=5,
                             fill="#F8FAFC", stroke=EDGE, sw=0.9))
            out.append(text_fit(sx_st + sw_st / 2, sy_st + 13.8, st_txt,
                                sw_st - 10, 10.5, INK2, "middle", weight="bold"))
            placed_labels.append((sx_st - 1, sy_st - 1, sx_st + sw_st + 1, sy_st + 21.0))
            if si < ns - 1:
                out.append(seg_arrow(sx_st + sw_st + 1.5, sy_st + 10.0,
                                     sx_st + sw_st + sgap - 1.5, sy_st + 10.0,
                                     "#94A3B8", 1.3, 4.8))

    # 1. Compute compartment zone boxes & separate adjacent non-nested overlaps cleanly
    zone_vborders = []  # [(bx, by0, by1)] vertical compartment walls to keep edge labels off
    tall_single = (orient == "LR" and uh > 165.0 and all(len(groups[k]) == 1 for k in lv_keys)) if not all_explicit else False
    zone_specs = []
    zone_min_y = y + (34.0 if stages else 10.0)
    for zn in zones:
        mids = [nid for nid in zn.get("nodes", []) if nid in pos]
        if not mids:
            continue
        zx0 = max(x + 2, min(pos[m][0] for m in mids) - 10)
        zy0 = max(zone_min_y, min(pos[m][1] for m in mids) - (28 if tall_single else 24))
        zx1 = min(x + w - 2, max(pos[m][0] + pos[m][2] for m in mids) + 10)
        zy1 = min(y + h - leg_h - 4, max(pos[m][1] + pos[m][3] for m in mids) + (16 if tall_single else 10))
        zone_specs.append([zn, set(mids), zx0, zy0, zx1, zy1])

    # Pairwise de-overlap for disjoint adjacent compartments (prevents border clash on tight columns)
    for zi in range(len(zone_specs)):
        for zj in range(zi + 1, len(zone_specs)):
            if zone_specs[zi][1] & zone_specs[zj][1]:
                continue  # intentionally nested/shared nodes
            ax0, ay0, ax1, ay1 = zone_specs[zi][2:]
            bx0, by0, bx1, by1 = zone_specs[zj][2:]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > -2.0 and oy > -2.0:
                if ox <= oy:
                    if (ax0 + ax1) <= (bx0 + bx1):
                        mid = (ax1 + bx0) / 2.0
                        zone_specs[zi][4] = min(ax1, mid - 2.0)
                        zone_specs[zj][2] = max(bx0, mid + 2.0)
                    else:
                        mid = (bx1 + ax0) / 2.0
                        zone_specs[zj][4] = min(bx1, mid - 2.0)
                        zone_specs[zi][2] = max(ax0, mid + 2.0)
                else:
                    if (ay0 + ay1) <= (by0 + by1):
                        mid = (ay1 + by0) / 2.0
                        zone_specs[zi][5] = min(ay1, mid - 2.0)
                        zone_specs[zj][3] = max(by0, mid + 2.0)
                    else:
                        mid = (by1 + ay0) / 2.0
                        zone_specs[zj][5] = min(by1, mid - 2.0)
                        zone_specs[zi][3] = max(ay0, mid + 2.0)

    # Pre-collect straight edge segments so zone label pills avoid sitting directly on arrows
    edge_segs = []
    for ed in edges:
        ea, eb = ed.get("from"), ed.get("to")
        if ea in pos and eb in pos and not _needs_curve(ea, eb):
            ax0, ay0, aw0, ah0 = pos[ea]
            bx0, by0, bw0, bh0 = pos[eb]
            edge_segs.append((ax0 + aw0 / 2.0, ay0 + ah0 / 2.0, bx0 + bw0 / 2.0, by0 + bh0 / 2.0))

    zone_pill_svgs = []
    for zn, _mset, zx0, zy0, zx1, zy1 in zone_specs:
        zone_vborders.append((zx0, zy0, zy1))
        zone_vborders.append((zx1, zy0, zy1))
        zcol = zn.get("color", "#E2E8F0")
        zstroke = zn.get("stroke", "#94A3B8")
        zlab_raw = str(zn.get("label", ""))
        zstyle = str(zn.get("style", "auto")).lower()
        if zstyle == "auto":
            zl = zlab_raw.lower()
            if any(kw in zl for kw in ("membrane", "bilayer", "plasma", "膜")):
                zstyle = "membrane"
            elif any(kw in zl for kw in ("nucleus", "nuclear", "核")):
                zstyle = "nucleus"
            elif any(kw in zl for kw in ("mitochond", "organelle", "vesicle", "线粒体")):
                zstyle = "organelle"
            else:
                zstyle = "dashed"
        zw_box, zh_box = zx1 - zx0, zy1 - zy0
        if zstyle == "membrane":
            # Biological double-line phospholipid bilayer compartment border
            out.append(rrect(zx0, zy0, zw_box, zh_box, rx=10,
                             fill=zcol, stroke=zstroke, sw=1.4,
                             extra='data-kind="mech-zone"'))
            if zw_box > 14 and zh_box > 14:
                out.append(rrect(zx0 + 3.5, zy0 + 3.5, zw_box - 7, zh_box - 7, rx=7.5,
                                 fill="none", stroke=zstroke, sw=0.95, dash="3 2",
                                 extra='data-kind="mech-zone"'))
        elif zstyle == "nucleus":
            # Biological double-dashed nuclear envelope
            out.append(rrect(zx0, zy0, zw_box, zh_box, rx=16,
                             fill=zcol, stroke=zstroke, sw=1.3, dash="7 3",
                             extra='data-kind="mech-zone"'))
            if zw_box > 14 and zh_box > 14:
                out.append(rrect(zx0 + 3.5, zy0 + 3.5, zw_box - 7, zh_box - 7, rx=13,
                                 fill="none", stroke=zstroke, sw=0.85, dash="7 3",
                                 extra='data-kind="mech-zone"'))
        elif zstyle == "organelle":
            # Rounded double-rim organelle/mitochondria compartment
            out.append(rrect(zx0, zy0, zw_box, zh_box, rx=14,
                             fill=zcol, stroke=zstroke, sw=1.35,
                             extra='data-kind="mech-zone"'))
            if zw_box > 14 and zh_box > 14:
                out.append(rrect(zx0 + 3.5, zy0 + 3.5, zw_box - 7, zh_box - 7, rx=11,
                                 fill="none", stroke=zstroke, sw=0.85, dash="5 2",
                                 extra='data-kind="mech-zone"'))
        else:
            out.append(rrect(zx0, zy0, zw_box, zh_box, rx=10,
                             fill=zcol, stroke=zstroke, sw=1.1, dash="5 3",
                             extra='data-kind="mech-zone"'))
        if zlab_raw:
            zmax = max(36.0, zw_box - 22)
            zw = min(zmax, text_width(zlab_raw, 10.5) * 1.07)
            pw_z, ph_z = zw + 11.0, 16.5
            # Collision-aware zone pill placement (strictly below stage ribbon & clear of all nodes/labels)
            pill_min_y = y + (25.0 if stages else 1.0)
            y_top_pill = max(pill_min_y, zy0 - 7.5)
            y_in_pill = max(pill_min_y, zy0 + 3.0)
            y_bot_pill = min(y + h - leg_h - ph_z - 2.0, zy1 - ph_z - 2.0)
            cand_p = [
                (zx0 + 10.0, y_top_pill),
                (max(zx0 + 6.0, zx1 - pw_z - 5.0), y_top_pill),
                (max(zx0 + 6.0, (zx0 + zx1 - pw_z) / 2.0), y_top_pill),
                (zx0 + 10.0, y_in_pill),
                (max(zx0 + 6.0, zx1 - pw_z - 5.0), y_in_pill),
                (zx0 + 10.0, y_bot_pill),
                (max(zx0 + 6.0, zx1 - pw_z - 5.0), y_bot_pill),
            ]
            best_p, best_pen = cand_p[0], 1e18
            for cx_p, cy_p in cand_p:
                rx0, ry0, rx1, ry1 = cx_p - 5.0, cy_p, cx_p - 5.0 + pw_z, cy_p + ph_z
                pen = 0.0
                for _nid, (nx0, ny0, nw0, nh0) in pos.items():
                    ovx = max(0.0, min(rx1 + 2.0, nx0 + nw0) - max(rx0 - 2.0, nx0))
                    ovy = max(0.0, min(ry1 + 2.0, ny0 + nh0) - max(ry0 - 2.0, ny0))
                    pen += ovx * ovy * 10.0
                for lx0, ly0, lx1, ly1 in placed_labels:
                    ovx = max(0.0, min(rx1 + 2.0, lx1) - max(rx0 - 2.0, lx0))
                    ovy = max(0.0, min(ry1 + 2.0, ly1) - max(ry0 - 2.0, ly0))
                    pen += ovx * ovy * 10.0
                for sx0, sy0, sx1, sy1 in edge_segs:
                    for ti in range(1, 10):
                        px_s = sx0 + (sx1 - sx0) * (ti / 10.0)
                        py_s = sy0 + (sy1 - sy0) * (ti / 10.0)
                        if rx0 - 2.0 <= px_s <= rx1 + 2.0 and ry0 - 2.0 <= py_s <= ry1 + 2.0:
                            pen += 80.0
                            break
                if pen < best_pen:
                    best_pen = pen
                    best_p = (cx_p, cy_p)
                    if pen == 0.0:
                        break
            px_b, py_b = best_p
            zone_pill_svgs.append(rrect(px_b - 5, py_b, pw_z, ph_z, rx=4,
                                        fill="#FFFFFF", stroke=zstroke, sw=0.85,
                                        extra='data-kind="label-bg"'))
            zone_pill_svgs.append(text_fit(px_b, py_b + 12.0, zlab_raw,
                                           zmax, 10.5, INK2, weight="bold"))
            placed_labels.append((px_b - 6, py_b - 1, px_b + zw + 7, py_b + 17.5))

    # 2. Render edges (straight or curved Bezier for skip-edges)
    missed = []
    skip_idx = 0
    edge_svgs = []
    label_svgs = []
    for ed in edges:
        a, bb = ed.get("from"), ed.get("to")
        if a not in pos or bb not in pos:
            continue
        ax, ay, aw, ah = pos[a]
        bx, by, bw2, bh2 = pos[bb]
        acx, acy = ax + aw / 2, ay + ah / 2
        bcx, bcy = bx + bw2 / 2, by + bh2 / 2
        ekind = str(ed.get("kind", "activate")).lower()
        ecol = ed.get("color") or ("#DC2626" if ekind == "inhibit" else "#64748B")
        dash = ed.get("dash") or ("5 3" if ekind == "dashed" else None)

        is_skip = _needs_curve(a, bb)
        if is_skip:
            sgn = -1 if skip_idx % 2 == 0 else 1
            skip_idx += 1
            if orient == "LR":
                # Arc above or below the intermediate row of nodes
                all_y0 = min(p[1] for p in pos.values())
                all_y1 = max(p[1] + p[3] for p in pos.values())
                sy1 = ay if sgn < 0 else ay + ah
                sy2 = by if sgn < 0 else by + bh2
                sx1, sx2 = acx, bcx
                cy_ctrl = (max(y + 6, all_y0 - 44) if sgn < 0
                           else min(y + h - leg_h - 6, all_y1 + 44))
                cx_ctrl = (sx1 + sx2) / 2
                edge_svgs.append(quad_arrow(sx1, sy1, cx_ctrl, cy_ctrl, sx2, sy2,
                                            ecol, 1.7, 7.5, dash=dash, kind=ekind))
                mid_pt = (0.25 * sx1 + 0.5 * cx_ctrl + 0.25 * sx2,
                          0.25 * sy1 + 0.5 * cy_ctrl + 0.25 * sy2)
            else:
                all_x1 = max(p[0] + p[2] for p in pos.values())
                sx1, sy1 = ax + aw, acy
                sx2, sy2 = bx + bw2, bcy
                cx_ctrl = min(x + w - 6, all_x1 + 36)
                cy_ctrl = (sy1 + sy2) / 2
                edge_svgs.append(quad_arrow(sx1, sy1, cx_ctrl, cy_ctrl, sx2, sy2,
                                            ecol, 1.7, 7.5, dash=dash, kind=ekind))
                mid_pt = (0.25 * sx1 + 0.5 * cx_ctrl + 0.25 * sx2,
                          0.25 * sy1 + 0.5 * cy_ctrl + 0.25 * sy2)
            cand_pts = [(mid_pt[0], mid_pt[1] + (sgn * 10 if orient == "LR" else 0)),
                        mid_pt,
                        (mid_pt[0], mid_pt[1] - 14),
                        (mid_pt[0], mid_pt[1] + 14)]
        else:
            dx, dy = bcx - acx, bcy - acy
            t1 = _edge_t(dx, dy, aw / 2, ah / 2)
            t2 = 1.0 - _edge_t(-dx, -dy, bw2 / 2, bh2 / 2)
            x1, y1 = acx + dx * t1, acy + dy * t1
            x2, y2 = acx + dx * t2, acy + dy * t2
            edge_svgs.append(seg_arrow(x1, y1, x2, y2, ecol, 1.7, 7.5,
                                       dash=dash, kind=ekind))
            cand_pts = []
            for t in (0.5, 0.58, 0.42, 0.68, 0.32):
                mx, my = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                for off in (0.0, -16.0, 16.0, -28.0, 28.0, -38.0, 38.0):
                    cand_pts.append((mx, my + off) if abs(dx) >= abs(dy) else (mx + off * 1.4, my))

        if ed.get("label"):
            lbl = str(ed["label"])
            lfs = max(10.0, mfs - 1.5)
            lw = text_width(lbl, lfs) + 10
            lh2 = lfs * 1.45 + 6
            # If horizontal edge gap is tight or crosses a compartment wall, prefer above/below arrow first
            if not is_skip and abs(dx) >= abs(dy):
                mx_mid, my_mid = (x1 + x2) / 2, (y1 + y2) / 2
                crosses_wall = any(
                    (mx_mid - lw / 2 - 2 <= bx <= mx_mid + lw / 2 + 2)
                    and (my_mid - lh2 / 2 <= by1 and my_mid + lh2 / 2 >= by0)
                    for bx, by0, by1 in zone_vborders
                )
                if abs(x2 - x1) < lw + 12 or crosses_wall:
                    cand_pts = []
                    for t in (0.5, 0.58, 0.42, 0.68, 0.32):
                        mx, my = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                        for off in (-22.0, 22.0, -34.0, 34.0, 0.0, -44.0, 44.0):
                            cand_pts.append((mx, my + off))
            chosen_pt = None
            for strict_wall in (True, False):
                for mx, my in cand_pts:
                    rx0, rx1 = mx - lw / 2, mx + lw / 2
                    ry0, ry1 = my - lh2 / 2, my + lh2 / 2
                    if rx0 < x + 1 or rx1 > x + w - 1 or ry0 < y + 1 or ry1 > y + h - leg_h - 1:
                        continue
                    hit = False
                    for px0, py0, nw0, nh0 in pos.values():
                        if rx0 < px0 + nw0 + 1 and rx1 > px0 - 1 and ry0 < py0 + nh0 + 1 and ry1 > py0 - 1:
                            hit = True
                            break
                    if not hit:
                        for lx0, ly0, lx1, ly1 in placed_labels:
                            if rx0 < lx1 + 2 and rx1 > lx0 - 2 and ry0 < ly1 + 2 and ry1 > ly0 - 2:
                                hit = True
                                break
                    if not hit and strict_wall:
                        for bx_w, by0_w, by1_w in zone_vborders:
                            if (rx0 - 2 <= bx_w <= rx1 + 2) and (ry0 <= by1_w and ry1 >= by0_w):
                                hit = True
                                break
                    if not hit:
                        chosen_pt = (mx, my)
                        placed_labels.append((rx0, ry0, rx1, ry1))
                        break
                if chosen_pt is not None:
                    break
            if chosen_pt is None:
                missed.append((node_label_map.get(a, a), node_label_map.get(bb, bb), lbl))
            else:
                label_svgs.append(label_bg(chosen_pt[0], chosen_pt[1], lbl, lfs,
                                           pad=3.5, bg="#FFFFFF", fg=INK2,
                                           stroke=EDGE))

    # 3. Render nodes ON TOP of edges, then labels ON TOP of nodes/edges
    out.extend(edge_svgs)
    for nd in nodes:
        nid = nd.get("id", "")
        px, py, nw, nh = pos[nid]
        col = nd.get("color") or accent
        fill = nd.get("fill", "#FFFFFF")
        shape = str(nd.get("shape", "rect")).lower()
        rx = nh / 2 if shape == "pill" else 8
        out.append(rrect(px + 1.5, py + 2.2, nw, nh, rx=rx, fill="#0F172A",
                         extra='fill-opacity="0.06"'))
        out.append(rrect(px, py, nw, nh, rx=rx, fill=fill, stroke=col, sw=1.6,
                         extra=f'data-kind="mech-node" data-node-id="{esc(nid)}"'))
        if shape != "pill" and nh >= 44.0 and nw >= 110.0:
            out.append(rrect(px + 1.2, py + 5.0, 3.6, nh - 10.0, rx=1.8, fill=col))
        ico = nd.get("icon", "")
        ico_r = 12.0 if nh >= 48.0 else 10.5
        ico_cx = px + (22.0 if nh >= 48.0 else 16.0)
        if ico:
            out.append(render_icon(ico, ico_cx, py + nh / 2, r=ico_r, color=col, bg=fill))
        lns, slns, _, _ = sizes[nid]
        tx = px + (nw + (30.0 if nh >= 48.0 else 22.0)) / 2 if ico else px + nw / 2
        tot_th = len(lns) * mfs * 1.26 + len(slns) * sfs * 1.2
        ty0 = py + (nh - tot_th) / 2
        for j, ln in enumerate(lns):
            out.append(text(tx, ty0 + mfs * 0.92 + j * mfs * 1.26, ln,
                            mfs, INK, "middle", weight="bold" if slns else "normal"))
        for j, sln in enumerate(slns):
            out.append(text(tx, ty0 + len(lns) * mfs * 1.26 + sfs * 0.9 + j * sfs * 1.2,
                            sln, sfs, MUT, "middle"))
    out.extend(zone_pill_svgs)
    out.extend(label_svgs)

    # 4. Human-readable wrapped footnote if any edge label couldn't avoid collisions
    if missed:
        fn = "; ".join(f"{c} ({a} -> {d})" for a, d, c in missed)
        flines = wrap_text("Pathways: " + fn, 10.0, w - 8)[:2]
        fy0 = y + h - leg_h - 3 - (len(flines) - 1) * 12.5
        for fi, fln in enumerate(flines):
            out.append(text(x + 2, fy0 + fi * 12.5, fln, 10.0, MUT))
        if diag is not None:
            diag["warnings"].append(
                f"{len(missed)} edge label(s) placed in footnote")

    # 5. Optional mechanism legend bar at bottom (auto-fits width to prevent panel overflow)
    if legend:
        ly = y + h - 8
        lx = x + 4
        max_x = x + w - 4
        lfs_leg = 10.5
        est_w = sum(34 + text_width(str(it.get("label", it.get("kind", ""))), lfs_leg) for it in legend)
        if est_w > (w - 8):
            lfs_leg = 10.0
        for item in legend:
            ek = str(item.get("kind", "activate")).lower()
            lb = str(item.get("label", ek))
            lc = item.get("color") or ("#DC2626" if ek == "inhibit" else "#64748B")
            rem = max_x - (lx + 26)
            if rem < 28:
                break
            out.append(seg_arrow(lx, ly - 3, lx + 20, ly - 3, lc, 1.7, 5.8, kind=ek))
            out.append(text_fit(lx + 24, ly, lb, rem, lfs_leg, MUT))
            lx += 30 + min(rem, text_width(lb, lfs_leg))

    return title_svg + "".join(out), h + th_off


def _table_block(b, x, y, w, fs, accent):
    """Compact auto-wrapped scientific summary table."""
    headers = [str(h) for h in b.get("headers", [])]
    rows = b.get("rows", [])
    nc = max(len(headers), max((len(r) for r in rows), default=0))
    if nc == 0:
        return "", 0.0
    out = []
    cy = y
    if b.get("title"):
        tfs = max(11.0, fs)
        out.append(text_fit(x + 2, cy + tfs * 0.95, str(b["title"]), w - 4, tfs, INK, weight="bold"))
        cy += tfs * 1.4
    weights = b.get("col_weights") or [1.0 / nc] * nc
    sw = sum(weights[:nc]) or 1.0
    cws = [w * (wt / sw) for wt in weights[:nc]]
    cfs = max(10.0, fs - 1.5)
    lh = cfs * 1.25
    pad_x, pad_y = 6.0, 5.0
    hl_row = b.get("highlight_row")

    def _draw_row(cells, ry, is_hdr=False, r_idx=-1):
        wrapped = [wrap_text(str(cells[i]) if i < len(cells) else "", cfs, max(24.0, cws[i] - 2 * pad_x))
                   for i in range(nc)]
        max_ln = max((len(lns) for lns in wrapped), default=1)
        rh = max(22.0, max_ln * lh + 2 * pad_y)
        if is_hdr:
            fill = accent
            fg = "#FFFFFF"
        elif hl_row is not None and r_idx == int(hl_row):
            fill = "#FEF3C7"
            fg = INK
        else:
            fill = "#FFFFFF" if r_idx % 2 == 0 else "#F8FAFC"
            fg = INK
        out.append(rrect(x, ry, w, rh, rx=4 if is_hdr else 0, fill=fill, stroke=EDGE, sw=0.7))
        cx = x
        for i in range(nc):
            if i > 0:
                out.append(line(cx, ry, cx, ry + rh, "#FFFFFF" if is_hdr else EDGE, 0.7))
            lns = wrapped[i]
            ty0 = ry + (rh - len(lns) * lh) / 2
            for li, ln in enumerate(lns):
                out.append(text(cx + pad_x, ty0 + cfs * 0.88 + li * lh, ln, cfs, fg,
                                weight="bold" if (is_hdr or i == 0) else "normal"))
            cx += cws[i]
        return rh

    if headers:
        cy += _draw_row(headers, cy, is_hdr=True)
    for ri, r in enumerate(rows):
        cy += _draw_row(r, cy, is_hdr=False, r_idx=ri)
    if b.get("note"):
        out.append(text_fit(x + 2, cy + cfs * 1.15, str(b["note"]), w - 4,
                            max(10.0, cfs - 0.5), MUT))
        cy += cfs * 1.4
    return "".join(out), cy - y + 2


def _scalebar_block(b, x, y, w, fs, accent):
    """Microscopy/imaging scale bar."""
    px = min(float(b.get("px", 100)), w - 60)
    lab = str(b.get("length", "20 um"))
    align = b.get("align", "left")
    sx = (x + w - px - text_width(lab, fs) - 14) if align == "right" else x + 4
    ty = y + fs * 1.0
    out = [line(sx, ty, sx + px, ty, INK, 2.4),
           line(sx, ty - 4, sx, ty + 4, INK, 2.0),
           line(sx + px, ty - 4, sx + px, ty + 4, INK, 2.0),
           text(sx + px + 8, ty + fs * 0.34, lab, max(10.0, fs - 1), INK, weight="bold")]
    return "".join(out), fs * 1.9


def _row_block(b, x, y, w, avail_h, fs, accent, diag=None):
    """Side-by-side horizontal split of sub-blocks inside a wide panel."""
    items = b.get("blocks", [])
    if not items:
        return "", 0.0
    n = len(items)
    weights = b.get("weights") or [1.0 / n] * n
    s = sum(weights) or 1.0
    weights = [v / s for v in weights]
    gap = 16.0
    bh = min(float(b.get("height", avail_h)), avail_h)
    out, cx, max_used = [], x, 0.0
    for sub, wt in zip(items, weights):
        sw = (w - gap * (n - 1)) * wt
        svg_s, used = render_block(dict(sub), cx, y, sw, bh, fs, accent, diag=diag)
        out.append(svg_s)
        max_used = max(max_used, used)
        cx += sw + gap
    return "".join(out), max_used


def _custom_svg_block(b, x, y, w, avail_h, fs, accent):
    """Auto-scaled inline custom SVG vector visual block for bespoke domain diagrams."""
    raw = str(b.get("svg") or b.get("xml") or b.get("content") or "").strip()
    if not raw:
        return "", 0.0
    out, cy = [], y
    if b.get("title"):
        tfs = max(11.0, fs)
        out.append(text_fit(x + 2, cy + tfs * 0.95, str(b["title"]), w - 4, tfs, INK, weight="bold"))
        cy += tfs * 1.45
    note = str(b.get("note", "")).strip()
    note_h = (max(10.0, fs - 1.5) * 1.4) if note else 0.0
    bh = min(float(b.get("height", avail_h - (cy - y))), max(60.0, avail_h - (cy - y)))
    vh_box = max(40.0, bh - note_h)
    vb_s = str(b.get("viewBox") or b.get("viewbox") or "0 0 400 220")
    nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", vb_s)]
    vx0, vy0, vw, vh = (nums[0], nums[1], nums[2], nums[3]) if len(nums) >= 4 and nums[2] > 0 and nums[3] > 0 else (0.0, 0.0, 400.0, 220.0)
    try:
        ET.fromstring(f'<g xmlns="http://www.w3.org/2000/svg">{raw}</g>')
    except ET.ParseError:
        out.append(text_fit(x + 4, cy + fs, "Custom SVG snippet parse error", w - 8, fs, MUT))
        return "".join(out), (cy - y) + fs * 1.6
    sc = min((w - 8.0) / vw, (vh_box - 4.0) / vh)
    tx = x + (w - vw * sc) / 2.0 - vx0 * sc
    ty = cy + (vh_box - vh * sc) / 2.0 - vy0 * sc
    out.append(f'<g data-kind="custom-svg" transform="translate({tx:.2f},{ty:.2f}) scale({sc:.4f})">{raw}</g>')
    used_y = cy + vh_box
    if note:
        out.append(text_fit(x + w / 2, used_y + max(10.0, fs - 1.5), note, w - 8,
                            max(10.0, fs - 1.5), MUT, "middle"))
        used_y += note_h
    return "".join(out), used_y - y


_BLOCK_ALIASES = {
    "text": "text", "bullets": "text", "list": "text", "points": "text",
    "summary": "text", "paragraph": "text", "notes": "text",
    "callout": "callout", "highlight": "callout", "box": "callout",
    "card": "callout", "banner": "callout", "takeaway": "callout", "finding": "callout",
    "kpi": "kpi", "metrics": "kpi", "metric": "kpi", "stats": "kpi", "stat": "kpi", "cards": "kpi",
    "flow": "flow", "workflow": "flow", "steps": "flow", "pipeline": "flow",
    "protocol": "flow", "timeline": "flow", "process": "flow",
    "scalebar": "scalebar", "scale_bar": "scalebar", "scale": "scalebar",
    "table": "table", "grid_table": "table", "params": "table",
    "row": "row", "columns": "row", "split": "row", "hstack": "row", "side_by_side": "row",
    "mechanism": "mechanism", "pathway": "mechanism", "diagram": "mechanism",
    "schematic": "mechanism", "network": "mechanism", "model": "mechanism",
    "svg": "svg", "custom_svg": "svg", "vector": "svg", "graphic": "svg",
    "chart": "chart", "plot": "chart", "graph": "chart", "figure": "chart", "data": "chart",
}
_DIRECT_CHART_TYPES = {
    "bar", "grouped_bar", "bar_chart", "hbar", "horizontal_bar", "stacked",
    "line", "line_chart", "dot", "dotplot", "strip", "stripplot", "beeswarm", "dot_mean", "swarm",
    "boxplot", "box_plot", "violin",
    "scatter", "volcano", "paired", "slope", "before_after", "heatmap",
    "survival", "kaplan_meier", "km", "forest", "forest_plot",
}


def render_block(b, x, y, w, avail_h, fs, accent, diag=None):
    raw_t = str(b.get("type", "text")).strip().lower().replace("-", "_").replace(" ", "_")
    if raw_t in _DIRECT_CHART_TYPES:
        b = {**b, "type": "chart", "kind": b.get("kind", raw_t)}
        t = "chart"
    elif raw_t == "box" and (b.get("series") or b.get("xlabels")):
        b = {**b, "type": "chart", "kind": "box"}
        t = "chart"
    else:
        t = _BLOCK_ALIASES.get(raw_t, raw_t)
    if t == "text":
        if "items" not in b and (b.get("text") or b.get("body")):
            val = b.get("text") or b.get("body")
            b = {**b, "items": val if isinstance(val, list) else [str(val)]}
        return _text_block(b, x, y, w, fs, accent)
    if t == "callout":
        return _callout_block(b, x, y, w, fs, accent)
    if t == "kpi":
        if "items" not in b and any(k in b for k in ("value", "metric", "number", "stat")):
            b = {**b, "items": [{
                "value": b.get("value", b.get("metric", b.get("number", b.get("stat", "")))),
                "label": b.get("label", b.get("text", b.get("sub", ""))),
                "color": b.get("color"),
            }]}
        return _kpi_block(b, x, y, w, fs, accent)
    if t == "flow":
        if "steps" not in b and b.get("items"):
            b = {**b, "steps": b["items"]}
        return _flow_block(b, x, y, w, avail_h, fs, accent)
    if t == "scalebar":
        return _scalebar_block(b, x, y, w, fs, accent)
    if t == "table":
        return _table_block(b, x, y, w, fs, accent)
    if t == "row":
        if "blocks" not in b:
            for k_alt in ("items", "children", "columns"):
                if b.get(k_alt):
                    b = {**b, "blocks": b[k_alt]}
                    break
        return _row_block(b, x, y, w, avail_h, fs, accent, diag=diag)
    if t == "mechanism":
        mh = min(float(b.get("height", avail_h)), avail_h)
        return _mech_block(b, x, y, w, mh, fs, accent, diag=diag)
    if t == "svg":
        return _custom_svg_block(b, x, y, w, avail_h, fs, accent)
    if t == "chart":
        from gachart import render_chart
        ch = min(float(b.get("height", avail_h)), avail_h)
        return render_chart(b, x, y, w, ch, fs)
    # Last-resort graceful degradation if block carries readable text/items
    if b.get("items") or b.get("text") or b.get("body"):
        val = b.get("items") or b.get("text") or b.get("body")
        return _text_block({"heading": b.get("heading") or b.get("title", ""),
                            "items": val if isinstance(val, list) else [str(val)]},
                           x, y, w, fs, accent)
    return text(x, y + fs, "?unknown block", fs, MUT), fs * 1.4
