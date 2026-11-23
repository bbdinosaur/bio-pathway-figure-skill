"""Mechanism layout: compartments, multi-tier node placement, complex/module groups."""
from __future__ import annotations
import sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viz_style import NODE_STYLES, COMP_STYLES, text_w
from viz_geom import text_bbox, overlap

BAND_H = {"exterior": 96, "membrane": 72, "cytosol": 220, "nucleus": 200,
          "organelle": 160, "custom": 180}
TOP = 74
LEFT = 56
GAP = 14
ROW_GAP = 72  # vertical spacing between sub-rows (tiers) inside a compartment

def auto_compartment_bands(comps, top_y=TOP):
    bands, y = [], float(top_y)
    for c in comps:
        h = float(c.get("y1", 0) - c.get("y0", 0)) if c.get("y1") else BAND_H.get(c.get("kind", "custom"), 180)
        bands.append({"id": c["id"], "y0": y, "y1": y + h, "h": h})
        y += h + GAP
    return bands, y

def _auto_assign_rows(group, edges, gap, allow_auto_tier=True):
    """Return list of row indices (0, 1, ...) for nodes in one compartment."""
    if any(n.get("row") is not None or n.get("tier") is not None for n in group):
        return [int(n.get("row") if n.get("row") is not None else (n.get("tier") or 0)) for n in group]
    if not allow_auto_tier or len(group) < 5:
        return [0] * len(group)
    # Check if single row would be overly wide (>1350px) or has a clear intra-compartment DAG depth >= 2
    ids = {n["id"] for n in group}
    adj = {n["id"]: [] for n in group}
    indeg = {n["id"]: 0 for n in group}
    for e in edges or []:
        u, v = e.get("from"), e.get("to")
        if u in ids and v in ids and u != v and e.get("route") != "feedback":
            adj[u].append(v)
            indeg[v] += 1
    # Longest-path layering on DAG (break cycles via declaration order)
    pos = {n["id"]: i for i, n in enumerate(group)}
    depth = {n["id"]: 0 for n in group}
    for _ in range(len(group)):
        changed = False
        for n in group:
            u = n["id"]
            for v in adj[u]:
                if pos[u] < pos[v] and depth[v] < depth[u] + 1:
                    depth[v] = depth[u] + 1
                    changed = True
        if not changed:
            break
    max_d = max(depth.values()) if depth else 0
    total_w = sum(node_size(n)[0] for n in group) + gap * max(0, len(group) - 1)
    if max_d >= 1 and max_d <= 3 and (total_w > 1180 or (len(group) >= 6 and max_d >= 2)):
        # Collapse into 2-3 clean vertical signaling tiers
        rows = [min(depth[n["id"]], 2) for n in group]
        if len(set(rows)) >= 2:
            return rows
    if total_w > 1350 and len(group) >= 6:
        half = (len(group) + 1) // 2
        return [0 if i < half else 1 for i in range(len(group))]
    return [0] * len(group)

def _count_crossings(row_seq, edges):
    """Count inter-row edge crossings PLUS same-row non-adjacent edge skips."""
    pos = {}
    for r_idx, rnodes in enumerate(row_seq):
        n = max(1, len(rnodes))
        for i, nd in enumerate(rnodes):
            pos[nd["id"]] = (r_idx, (i + 0.5) / n, i)
    segs = []
    same_row_penalty = 0
    for e in edges or []:
        if e.get("route") == "feedback":
            continue
        a, b = pos.get(e.get("from")), pos.get(e.get("to"))
        if not a or not b:
            continue
        if a[0] == b[0]:
            # Penalize scrambling adjacent intra-row chains into jumping arcs
            skip = abs(a[2] - b[2]) - 1
            if skip > 0:
                same_row_penalty += 2 * skip
            continue
        if a[0] > b[0]:
            a, b = b, a
        segs.append((a[0], a[1], b[0], b[1]))
    cross = same_row_penalty
    for i in range(len(segs)):
        r1a, x1a, r1b, x1b = segs[i]
        for j in range(i + 1, len(segs)):
            r2a, x2a, r2b, x2b = segs[j]
            # Check crossing if vertical spans overlap
            if r1a == r2a and r1b == r2b:
                if (x1a - x2a) * (x1b - x2b) < -1e-9:
                    cross += 1
            elif max(r1a, r2a) < min(r1b, r2b):
                # Linear interpolation check at overlap midpoint
                rm = 0.5 * (max(r1a, r2a) + min(r1b, r2b))
                x1m = x1a + (x1b - x1a) * ((rm - r1a) / (r1b - r1a))
                x2m = x2a + (x2b - x2a) * ((rm - r2a) / (r2b - r2a))
                if (x1a - x2a) * (x1b - x2b) < -1e-9 and abs(x1m - x2m) < 0.35:
                    cross += 1
    return cross

def _untangle_rows(comp_order, comp_rows, edges):
    """Monotonic crossing-reducing barycenter sort (only accepts strict crossing reduction)."""
    row_keys = []
    row_seq = []
    for cid in comp_order:
        by_r = comp_rows.get(cid) or {}
        for r in sorted(by_r.keys()):
            row_keys.append((cid, r))
            row_seq.append(list(by_r[r]))
    if len(row_seq) < 2 or not edges:
        return
    base_c = _count_crossings(row_seq, edges)
    if base_c == 0:
        return
    nbrs = {}
    for e in edges:
        if e.get("route") == "feedback":
            continue
        u, v = e.get("from"), e.get("to")
        if u and v and u != v:
            nbrs.setdefault(u, []).append(v)
            nbrs.setdefault(v, []).append(u)
    for _sweep in range(2):
        for ri in list(range(len(row_seq))) + list(reversed(range(len(row_seq)))):
            rnodes = row_seq[ri]
            if len(rnodes) < 2 or any(nd.get("x") is not None for nd in rnodes):
                continue
            pos = {}
            for rj, rlist in enumerate(row_seq):
                if rj == ri:
                    continue
                n = max(1, len(rlist))
                for idx, nd in enumerate(rlist):
                    pos[nd["id"]] = (idx + 0.5) / n
            scored = []
            for idx, nd in enumerate(rnodes):
                xs = [pos[nb] for nb in nbrs.get(nd["id"], []) if nb in pos]
                bary = (sum(xs) / len(xs)) if xs else ((idx + 0.5) / len(rnodes))
                scored.append((bary, idx, nd))
            cand_row = [t[2] for t in sorted(scored, key=lambda t: (t[0], t[1]))]
            old_row = row_seq[ri]
            row_seq[ri] = cand_row
            new_c = _count_crossings(row_seq, edges)
            if new_c < base_c:
                base_c = new_c
            else:
                row_seq[ri] = old_row
            if base_c == 0:
                break
    for (cid, r), rnodes in zip(row_keys, row_seq):
        comp_rows[cid][r] = rnodes

def node_size(n, gap=86):
    lbl = str(n.get("label", n["id"]))
    sub = str(n.get("sublabel") or "")
    alias = str(n.get("alias") or "").strip()
    sub_eff = f"{sub} ({alias})" if (sub and alias) else (f"({alias})" if alias else sub)
    subunits = [str(u) for u in (n.get("subunits") or []) if str(u).strip()]
    lines = lbl.split("\n")
    w_main = text_w(lbl, 14.5)
    w_sub = text_w(sub_eff, 10.5) if sub_eff else 0.0
    w_units = (sum(max(38.0, text_w(u, 10.0) + 12.0) for u in subunits) + 6.0 * max(0, len(subunits) - 1) + 20.0) if subunits else 0.0
    w = n.get("w") or max(96, max(w_main, w_sub, w_units) + 30)
    nlines = len(lines) + (1 if sub_eff else 0)
    base_h = 46 if nlines <= 1 else (30 + nlines * 18)
    if subunits:
        base_h += 24
    h = n.get("h") or base_h
    return float(w), float(h)

def place_nodes(spec, bands, comp_kind, gap, plot_w=0, extra_top_pad=None, top_y=TOP):
    """Assign cx, cy, w, h to each node with multi-tier row support. Returns (placed, plot_w)."""
    bmap = {b["id"]: b for b in bands}
    extra_top_pad = extra_top_pad or {}
    edges = spec.get("edges", [])
    lopts = spec.get("layout") or {}
    allow_tier = lopts.get("auto_tier", True)
    if lopts.get("wide_canvas"):
        gap = gap * 1.45
    bycomp = {}
    for n in spec.get("nodes", []):
        bycomp.setdefault(n.get("compartment") or "_", []).append(n)
    # Pre-compute row assignments & widest row across all compartments
    comp_rows = {}
    max_row_w = 520.0
    for cid, group in bycomp.items():
        is_mem = comp_kind.get(cid) == "membrane"
        rlist = [0] * len(group) if is_mem else _auto_assign_rows(group, edges, gap, allow_tier)
        by_r = {}
        for n, r in zip(group, rlist):
            by_r.setdefault(r, []).append(n)
        comp_rows[cid] = by_r
        for r, rnodes in by_r.items():
            rw = sum(node_size(n, gap)[0] for n in rnodes) + gap * max(0, len(rnodes) - 1)
            max_row_w = max(max_row_w, rw)
    # Monotonic barycenter crossing reduction across compartment rows
    if not lopts.get("preserve_order"):
        comp_order = [b["id"] for b in bands] if bands else list(comp_rows.keys())
        for cid in comp_rows:
            if cid not in comp_order:
                comp_order.append(cid)
        _untangle_rows(comp_order, comp_rows, edges)
    # Ensure membrane bands leave horizontal clearance for their compartment label on the left
    comp_lbl = {c["id"]: c.get("label", c["id"]) for c in spec.get("compartments", [])}
    for cid, by_r in comp_rows.items():
        if comp_kind.get(cid) == "membrane":
            lbl_w = text_w(comp_lbl.get(cid, cid), 12.5)
            for rnodes in by_r.values():
                rw = sum(node_size(n, gap)[0] for n in rnodes) + gap * max(0, len(rnodes) - 1)
                max_row_w = max(max_row_w, rw + min(360.0, 2.0 * (lbl_w + 14.0)))
    plot_w = max(float(plot_w), max_row_w, 560.0)

    sm = spec.get("size_map") or {}
    have_scale = sm.get("min") is not None and sm.get("max") is not None
    placed = []
    for cid, by_r in comp_rows.items():
        b = bmap.get(cid)
        sorted_rs = sorted(by_r.keys())
        n_rows = len(sorted_rs)
        top_pad = extra_top_pad.get(cid, 0.0)
        for ri, r in enumerate(sorted_rs):
            rnodes = by_r[r]
            sizes = []
            for n in rnodes:
                w, h = node_size(n, gap)
                sv_raw = n.get("size_value") if n.get("size_value") is not None else n.get("value")
                if have_scale and isinstance(sv_raw, (int, float)):
                    tv = (sv_raw - sm["min"]) / ((sm["max"] - sm["min"]) or 1.0)
                    tv = min(1.0, max(0.0, tv))
                    h = h * (0.80 + 0.42 * tv)
                sizes.append((w, h))
            row_max_h = max((s[1] for s in sizes), default=46.0)
            rw = sum(s[0] for s in sizes) + gap * max(0, len(rnodes) - 1)
            x = LEFT + max(0.0, (plot_w - rw) / 2.0)
            for n, (w, h) in zip(rnodes, sizes):
                kind = n.get("kind", "protein")
                if b and (comp_kind.get(cid) == "membrane" or n.get("span_band")):
                    h = max(h, b["y1"] - b["y0"] - 4)
                    cy = (b["y0"] + b["y1"]) / 2.0
                elif b:
                    if n_rows == 1:
                        cy = (b["y0"] + top_pad + b["y1"]) / 2.0
                    else:
                        usable_top = b["y0"] + max(34.0, row_max_h / 2.0 + 16.0) + top_pad
                        usable_bot = b["y1"] - max(36.0, row_max_h / 2.0 + 20.0)
                        span = max(ROW_GAP * (n_rows - 1), usable_bot - usable_top)
                        cy = usable_top + span * (ri / max(1, n_rows - 1))
                else:
                    cy = float(top_y) + 140 + ri * ROW_GAP
                cx = float(n["x"]) if n.get("x") is not None else (x + w / 2.0)
                cy = float(n["y"]) if n.get("y") is not None else cy
                st = NODE_STYLES.get(kind, NODE_STYLES["other"])
                placed.append({**n, "cx": cx, "cy": cy, "w": w, "h": h,
                               "_tier": r, "shape": n.get("shape") or st.get("shape", "rect")})
                x += w + gap
    return placed, plot_w

def tighten_bands(comps, bands, placed, extra_top_pad=None, group_pad_comps=None):
    """Adjust each compartment band height tightly around its nodes + arc/group padding."""
    out = deepcopy(bands)
    if not out:
        return out
    extra_top_pad = extra_top_pad or {}
    group_pad_comps = group_pad_comps or set()
    pinned = {c["id"] for c in comps if c.get("y1")}
    byid = {b["id"]: b for b in out}
    for c, b in zip(comps, bands):
        nid = c["id"]
        ns = [n for n in placed if n.get("compartment") == nid]
        if not ns or nid in pinned:
            continue
        kind = c.get("kind", "custom")
        if kind == "membrane":
            byid[nid]["h"] = max(70.0, max(n["h"] for n in ns) + 6.0)
            continue
        tiers = sorted({n.get("_tier", 0) for n in ns})
        max_h = max(n["h"] for n in ns)
        has_alias = any(n.get("alias") for n in ns)
        has_mod = any(n.get("mods") for n in ns)
        tpad = 26.0 + (16.0 if has_alias else 0.0) + (8.0 if has_mod else 0.0) + extra_top_pad.get(nid, 0.0)
        if nid in group_pad_comps:
            tpad += 26.0 if has_mod else 18.0
        bpad = 30.0 + (22.0 if nid in group_pad_comps else 0.0)
        if len(tiers) <= 1:
            h = max(106.0, max_h + tpad + bpad)
        else:
            h = max(106.0, tpad + bpad + len(tiers) * max_h + (len(tiers) - 1) * (ROW_GAP - 16))
        byid[nid]["h"] = h
    y = out[0]["y0"]
    for b in out:
        b["y0"] = y
        b["y1"] = y + b["h"]
        y = b["y1"] + GAP
    return out

def draw_compartments(comps, bands, plot_w, prims, placed=None):
    x0, x1 = LEFT - 24, LEFT + plot_w + 24
    placed = placed or []
    for c, b in zip(comps, bands):
        kind = c.get("kind", "custom")
        st = dict(COMP_STYLES.get(kind, COMP_STYLES["custom"]))
        lbl_low = str(c.get("label", c["id"])).lower()
        if kind == "organelle":
            if any(k in lbl_low for k in ("mito", "mitochondri")):
                st = {"fill": "#fef6ec", "border": "#d9a066"}
            elif any(k in lbl_low for k in ("lyso", "endosom", "phagosom", "vesicl")):
                st = {"fill": "#edf9f7", "border": "#7ac2b8"}
            elif any(k in lbl_low for k in ("endoplasmic", "reticulum", "er ", " er", "golgi")):
                st = {"fill": "#f4f2fc", "border": "#a78bfa"}
            elif any(k in lbl_low for k in ("chloroplast", "plastid")):
                st = {"fill": "#eef9f0", "border": "#68b684"}
        elif kind == "custom":
            if any(k in lbl_low for k in ("t cell", "t-cell", "immune", "lymphocyte", "macrophage", "nk cell")):
                st = {"fill": "#f0f7ff", "border": "#93c5fd"}
            elif any(k in lbl_low for k in ("tumor", "cancer", "target cell", "apc", "donor", "stroma")):
                st = {"fill": "#fff5f5", "border": "#fca5a5"}
        prims.append({"op": "rect", "x": x0, "y": b["y0"], "w": x1 - x0, "h": b["h"],
                      "rx": 10, "fill": st["fill"], "stroke": st["border"],
                      "stroke_w": 1.2, "role": "bg", "layer": "layer-compartments",
                      "_id": f"comp-{c['id']}"})
        # Subtle Nature-style left accent bar for non-membrane compartments
        if kind != "membrane":
            prims.append({"op": "rect", "x": x0 + 1.5, "y": b["y0"] + 6, "w": 3.5,
                          "h": max(10.0, b["h"] - 12), "rx": 1.8, "fill": st["border"],
                          "stroke": "none", "stroke_w": 0, "opacity": 0.55,
                          "role": "deco", "layer": "layer-compartments"})
        # Subtle double-envelope accents for nuclear envelope and double-membrane organelles
        if kind == "nucleus":
            prims.append({"op": "rect", "x": x0 + 4, "y": b["y0"] + 4, "w": x1 - x0 - 8,
                          "h": b["h"] - 8, "rx": 8, "fill": "none", "stroke": st["border"],
                          "stroke_w": 1.0, "dashed": True, "role": "deco", "layer": "layer-compartments"})
        elif kind == "organelle":
            prims.append({"op": "rect", "x": x0 + 4, "y": b["y0"] + 4, "w": x1 - x0 - 8,
                          "h": b["h"] - 8, "rx": 8, "fill": "none", "stroke": st["border"],
                          "stroke_w": 0.9, "opacity": 0.75, "role": "deco", "layer": "layer-compartments"})
        lbl = c.get("label", c["id"])
        ly = b["y1"] - 13
        c_nodes = [n for n in placed if n.get("compartment") == c["id"]]
        nboxes = [[n["cx"] - n["w"] / 2, n["cy"] - n["h"] / 2,
                   n["cx"] + n["w"] / 2, n["cy"] + n["h"] / 2] for n in c_nodes]
        # Try bottom-left, bottom-right, top-left, top-right with generous clearance from nodes
        candidates = [
            (x0 + 12, ly, "start"),
            (x1 - 12, ly, "end"),
            (x0 + 12, b["y0"] + 14, "start"),
            (x1 - 12, b["y0"] + 14, "end"),
        ]
        chosen = candidates[0]
        for lx, cy_c, anc in candidates:
            lb = text_bbox(lx, cy_c, lbl, 12.5, anc)
            if not any(overlap(lb, nb, tol=8) for nb in nboxes):
                chosen = (lx, cy_c, anc)
                break
        lbl_bb = text_bbox(chosen[0], chosen[1], lbl, 12.5, chosen[2])
        # Clean lipid bilayer graphic on membrane band, interrupted by receptors and label
        if kind == "membrane":
            receptors = [(n["cx"] - n["w"] / 2.0 - 4, n["cx"] + n["w"] / 2.0 + 4)
                         for n in placed if n.get("compartment") == c["id"]]
            step = 18
            lbl_on_bot = chosen[1] > (b["y0"] + b["y1"]) / 2.0
            for xi in range(int(x0 + 12), int(x1 - 10), step):
                if any(rx0 <= xi <= rx1 for rx0, rx1 in receptors):
                    continue
                in_lbl = (lbl_bb[0] - 6 <= xi <= lbl_bb[2] + 6)
                if not (in_lbl and not lbl_on_bot):
                    prims.append({"op": "circle", "cx": xi, "cy": b["y0"] + 6, "r": 3.0,
                                  "fill": "#cbd5e1", "stroke": "#94a3b8", "stroke_w": 0.8,
                                  "role": "deco", "layer": "layer-compartments"})
                    prims.append({"op": "polyline", "pts": [[xi - 1.2, b["y0"] + 9.5], [xi - 1.2, b["y0"] + 16]],
                                  "stroke": "#94a3b8", "stroke_w": 0.8, "role": "deco", "layer": "layer-compartments"})
                if not (in_lbl and lbl_on_bot):
                    prims.append({"op": "circle", "cx": xi, "cy": b["y1"] - 6, "r": 3.0,
                                  "fill": "#cbd5e1", "stroke": "#94a3b8", "stroke_w": 0.8,
                                  "role": "deco", "layer": "layer-compartments"})
                    prims.append({"op": "polyline", "pts": [[xi + 1.2, b["y1"] - 9.5], [xi + 1.2, b["y1"] - 16]],
                                  "stroke": "#94a3b8", "stroke_w": 0.8, "role": "deco", "layer": "layer-compartments"})
        if kind == "membrane":
            # Soft crisp pill badge behind bold membrane label so it never fights the lipid bilayer
            pill_w = (lbl_bb[2] - lbl_bb[0]) * 1.14 + 14.0
            pill_x = (lbl_bb[0] - 6.0) if chosen[2] == "start" else (lbl_bb[2] + 6.0 - pill_w)
            prims.append({"op": "rect", "x": pill_x, "y": lbl_bb[1] - 2.5,
                          "w": pill_w, "h": (lbl_bb[3] - lbl_bb[1]) + 5.0,
                          "rx": 5, "fill": "#ffffff", "stroke": st["border"],
                          "stroke_w": 0.7, "opacity": 0.90,
                          "role": "deco", "layer": "layer-compartments"})
        prims.append({"op": "text", "x": chosen[0], "y": chosen[1], "s": lbl, "size": 12.5,
                      "anchor": chosen[2], "fill": "#475569" if kind == "membrane" else "#64748b",
                      "weight": "bold", "role": "deco", "layer": "layer-compartments",
                      "_id": f"complabel-{c['id']}"})

def draw_groups(groups, placed, prims):
    """Draw dashed/tinted complex or functional-module boxes enclosing member nodes."""
    if not groups:
        return
    nmap = {n["id"]: n for n in placed}
    for g in groups:
        members = [nmap[mid] for mid in (g.get("members") or []) if mid in nmap]
        if not members:
            continue
        has_mod = any(n.get("mods") for n in members)
        pad_x = float(g.get("pad_x", 13))
        pad_top = float(g.get("pad_top", 32 if has_mod else 24))
        pad_bot = float(g.get("pad_bot", 12))
        x0 = min(n["cx"] - n["w"] / 2.0 for n in members) - pad_x
        x1 = max(n["cx"] + n["w"] / 2.0 for n in members) + pad_x
        if g.get("label"):
            x1 = max(x1, x0 + text_w(str(g["label"]), 11.5) + 22.0)
        y0 = min(n["cy"] - n["h"] / 2.0 for n in members) - pad_top
        y1 = max(n["cy"] + n["h"] / 2.0 for n in members) + pad_bot
        dashed = g.get("style", "dashed") != "solid"
        prims.append({
            "op": "rect", "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "rx": 10,
            "fill": g.get("fill", "#f8fafc"), "stroke": g.get("stroke", "#94a3b8"),
            "stroke_w": 1.4, "dashed": dashed, "opacity": 0.72,
            "role": "group", "layer": "layer-groups", "_id": f"group-{g.get('id', 'box')}",
            "_meta": {"kind": "group", "source": g.get("source")},
        })
        if g.get("label"):
            glbl = str(g["label"])
            gw_pill = text_w(glbl, 11.5) * 1.10 + 14.0
            prims.append({
                "op": "rect", "x": x0 + 6, "y": y0 + 2, "w": gw_pill, "h": 17.5, "rx": 4.5,
                "fill": "#ffffff", "stroke": "none", "stroke_w": 0, "opacity": 0.88,
                "role": "deco", "layer": "layer-groups",
            })
            prims.append({
                "op": "text", "x": x0 + 11, "y": y0 + 11, "s": glbl,
                "size": 11.5, "anchor": "start", "fill": g.get("label_fill", "#475569"),
                "weight": "bold", "italic": True, "halo": False, "role": "deco", "layer": "layer-groups",
                "_id": f"grouplabel-{g.get('id', 'box')}"
            })
