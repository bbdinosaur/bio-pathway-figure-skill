"""Deterministic schematic layout: layer ranking, ordering, mm coordinates."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fig_style as S


def build_graph(nodes, edges):
    ids = [n["id"] for n in nodes]
    id_set = set(ids)
    fwd = {i: [] for i in ids}
    for e in edges:
        u, v = e.get("from"), e.get("to")
        if u in id_set and v in id_set and u != v:
            fwd[u].append(v)

    # cycle breaking: DFS back-edge detection
    back = set()
    color = {i: 0 for i in ids}

    def dfs(u):
        color[u] = 1
        for v in fwd[u]:
            if color[v] == 1:
                back.add((u, v))
            elif color[v] == 0:
                dfs(v)
        color[u] = 2

    for i in ids:
        if color[i] == 0:
            dfs(i)

    # longest-path layering on DAG (skip back edges and self loops)
    rank = {i: 0 for i in ids}
    fixed = {}
    for n in nodes:
        if "rank" in n and n["rank"] is not None:
            fixed[n["id"]] = int(n["rank"])
            rank[n["id"]] = int(n["rank"])
    for _ in range(len(ids) + 1):
        changed = False
        for e in edges:
            u, v = e.get("from"), e.get("to")
            if u in rank and v in rank and (u, v) not in back and u != v:
                if v not in fixed and rank[v] < rank[u] + 1:
                    rank[v] = rank[u] + 1
                    changed = True
        if not changed:
            break
    # Also mark any edge going backwards or same-rank relative to explicit ranks
    for e in edges:
        u, v = e.get("from"), e.get("to")
        if u in rank and v in rank and rank[v] < rank[u]:
            back.add((u, v))
    return rank, back


def order_layers(nodes, edges, rank, groups=None):
    layers = {}
    for n in nodes:
        layers.setdefault(rank[n["id"]], []).append(n["id"])
    pos_in_layer = {}
    for r in sorted(layers):
        for k, nid in enumerate(layers[r]):
            pos_in_layer[nid] = k
    # Map each node to its innermost (smallest) group so siblings in the same compartment stay contiguous
    node_grp = {}
    if groups:
        for gi, g in enumerate(sorted(groups, key=lambda x: -len(x.get("members", [])))):
            for m in g.get("members", []):
                node_grp[m] = g.get("id", str(gi))
    # barycenter sweeps to reduce crossings
    preds, succs = {}, {}
    for e in edges:
        u, v = e.get("from"), e.get("to")
        succs.setdefault(u, []).append(v)
        preds.setdefault(v, []).append(u)
    for sweep in range(4):
        keys = sorted(layers) if sweep % 2 == 0 else sorted(layers, reverse=True)
        for r in keys:
            for k, nid in enumerate(layers[r]):
                nb = [m for m in (preds.get(nid, []) + succs.get(nid, []))
                      if m in pos_in_layer and rank.get(m) != r]
                if nb:
                    pos_in_layer[nid] = sum(pos_in_layer[m] for m in nb) / len(nb)
            if node_grp:
                # Compute average barycenter per group in this rank so group blocks stay contiguous
                grp_pos = {}
                for nid in layers[r]:
                    gk = node_grp.get(nid)
                    if gk is not None:
                        grp_pos.setdefault(gk, []).append(pos_in_layer[nid])
                grp_avg = {gk: sum(vs) / len(vs) for gk, vs in grp_pos.items()}
                layers[r] = sorted(
                    layers[r],
                    key=lambda x: (grp_avg[node_grp[x]] if x in node_grp else pos_in_layer[x],
                                   node_grp.get(x, ""), pos_in_layer[x]),
                )
            else:
                layers[r] = sorted(layers[r], key=lambda x: pos_in_layer[x])
            for k, nid in enumerate(layers[r]):
                pos_in_layer[nid] = k
    return layers


def size_nodes(nodes, meas, style, fs_sub=None):
    """Auto-size node boxes from measured text (mm)."""
    fs_base = style.get("fontsize", 9.0)
    lh = S.line_height_mm(fs_base)
    out = {}
    for n in nodes:
        fs = float(n.get("fontsize", fs_base))
        fs_s = float(fs_sub) if fs_sub is not None else fs * 0.8
        lh_n = S.line_height_mm(fs)
        lh_sub = S.line_height_mm(fs_s)
        w_l, h_l, n_l = meas.text_mm(S.wrap_label(n.get("label", n["id"])), fontsize=fs, weight="bold")
        w_s, h_s, n_s = (meas.text_mm(S.wrap_label(n["sublabel"], max_chars=28), fontsize=fs_s)
                         if n.get("sublabel") else (0.0, 0.0, 0))
        sub_gap = 0.9 if n_s > 0 else 0.0
        w = max(w_l, w_s) + 2.0 * style["pad_x"]
        h = max(h_l, n_l * lh_n) + (max(h_s, n_s * lh_sub) if n_s else 0.0) + sub_gap + 2.0 * style["pad_y"]
        shape = n.get("shape", "round")
        if shape == "diamond":
            w *= 1.48
            h *= 1.55
        elif shape == "ellipse":
            w *= 1.24
            h *= 1.28
        elif shape == "stadium":
            w += 3.0
        elif shape == "hexagon":
            w += 4.6
            h += 0.8
        elif shape == "complex":
            w += 2.0
            h += 1.6
        elif shape == "gene":
            h += 1.6
        out[n["id"]] = {
            "w": max(w, fs * 1.8),
            "h": max(h, fs * 1.25),
            "h_l": max(h_l, n_l * lh_n),
            "h_s": max(h_s, n_s * lh_sub) if n_s else 0.0,
        }
    return out


def _stack_gap(a, b, gap_y, node_group):
    if node_group and node_group.get(a) != node_group.get(b):
        return gap_y + 7.2
    return gap_y


def _col_height(members, sizes, gap_y, node_group=None):
    if not members:
        return 0.0
    hsum = sum(sizes[n]["h"] for n in members)
    gsum = sum(_stack_gap(members[i], members[i + 1], gap_y, node_group)
               for i in range(len(members) - 1))
    return hsum + gsum


def _stack_members(members, sizes, gap_y, y_center, node_group=None):
    total_h = _col_height(members, sizes, gap_y, node_group)
    cur = y_center + total_h / 2.0
    out = {}
    for i, n in enumerate(members):
        out[n] = cur - sizes[n]["h"] / 2.0
        if i + 1 < len(members):
            cur -= sizes[n]["h"] + _stack_gap(n, members[i + 1], gap_y, node_group)
    return out


def _separate_non_members_from_groups(pos, sizes, layers, groups, direction, min_gap=7.5):
    """Push non-member nodes outside any compartment bounding box they accidentally fall inside."""
    if not groups or not pos:
        return pos, 0.0, 0.0
    g_sets = {g.get("id", str(i)): set(g.get("members", [])) for i, g in enumerate(groups)}
    node_rank = {nid: r for r, ns in layers.items() for nid in ns}
    for _ in range(3):
        moved_any = False
        for gi, g in enumerate(groups):
            gid = g.get("id", str(gi))
            mems = [m for m in g.get("members", []) if m in pos]
            if not mems:
                continue
            ms = g_sets[gid]
            nd = sum(1 for ogid, oms in g_sets.items() if ogid != gid and oms and oms < ms)
            pad = 2.6 + nd * 2.5
            hdr = 3.8 + nd * 3.8 + (1.4 if g.get("membrane") else 0.0)
            gx0 = min(pos[m][0] - sizes[m]["w"] / 2.0 for m in mems) - pad
            gx1 = max(pos[m][0] + sizes[m]["w"] / 2.0 for m in mems) + pad
            gy0 = min(pos[m][1] - sizes[m]["h"] / 2.0 for m in mems) - pad
            gy1 = max(pos[m][1] + sizes[m]["h"] / 2.0 for m in mems) + pad + hdr
            g_cx = (gx0 + gx1) / 2.0
            g_cy = (gy0 + gy1) / 2.0
            for nid in list(pos.keys()):
                if nid in ms:
                    continue
                cx, cy = pos[nid]
                hw, hh = sizes[nid]["w"] / 2.0, sizes[nid]["h"] / 2.0
                if (cx + hw > gx0 - 1.2 and cx - hw < gx1 + 1.2 and
                        cy + hh > gy0 - 1.2 and cy - hh < gy1 + 1.2):
                    rk = node_rank.get(nid)
                    if direction == "TB":
                        go_left = cx <= g_cx
                        new_cx = (gx0 - 5.2 - hw) if go_left else (gx1 + 5.2 + hw)
                        pos[nid] = (new_cx, cy)
                        if rk is not None:
                            sibs = [n for n in layers[rk] if n not in ms]
                            sibs.sort(key=lambda n: pos[n][0])
                            if go_left:
                                for si in range(len(sibs) - 2, -1, -1):
                                    a, b = sibs[si], sibs[si + 1]
                                    max_ax = pos[b][0] - sizes[b]["w"] / 2.0 - min_gap - sizes[a]["w"] / 2.0
                                    if pos[a][0] > max_ax:
                                        pos[a] = (max_ax, pos[a][1])
                            else:
                                for si in range(1, len(sibs)):
                                    a, b = sibs[si - 1], sibs[si]
                                    min_bx = pos[a][0] + sizes[a]["w"] / 2.0 + min_gap + sizes[b]["w"] / 2.0
                                    if pos[b][0] < min_bx:
                                        pos[b] = (min_bx, pos[b][1])
                    else:
                        go_up = cy >= g_cy
                        new_cy = (gy1 + 4.8 + hh) if go_up else (gy0 - 4.8 - hh)
                        pos[nid] = (cx, new_cy)
                        if rk is not None:
                            sibs = [n for n in layers[rk] if n not in ms]
                            sibs.sort(key=lambda n: pos[n][1])
                            if go_up:
                                for si in range(1, len(sibs)):
                                    a, b = sibs[si - 1], sibs[si]
                                    min_by = pos[a][1] + sizes[a]["h"] / 2.0 + min_gap + sizes[b]["h"] / 2.0
                                    if pos[b][1] < min_by:
                                        pos[b] = (pos[b][0], min_by)
                            else:
                                for si in range(len(sibs) - 2, -1, -1):
                                    a, b = sibs[si], sibs[si + 1]
                                    max_ay = pos[b][1] - sizes[b]["h"] / 2.0 - min_gap - sizes[a]["h"] / 2.0
                                    if pos[a][1] > max_ay:
                                        pos[a] = (pos[a][0], max_ay)
                    moved_any = True
        if not moved_any:
            break
    min_x = min(pos[n][0] - sizes[n]["w"] / 2.0 for n in pos)
    min_y = min(pos[n][1] - sizes[n]["h"] / 2.0 for n in pos)
    if abs(min_x) > 1e-6 or abs(min_y) > 1e-6:
        pos = {n: (xy[0] - min_x, xy[1] - min_y) for n, xy in pos.items()}
    total_w = max(pos[n][0] + sizes[n]["w"] / 2.0 for n in pos)
    total_h = max(pos[n][1] + sizes[n]["h"] / 2.0 for n in pos)
    return pos, total_w, total_h


def assign_xy(nodes, edges, layers, sizes, direction, gap_x, gap_y, wrap_w=None,
              groups=None, meas=None):
    """Layered layout in mm; tight row heights (no vertical bloat) and direct TB."""
    order = sorted(layers)
    if not order:
        return {}, 10.0, 10.0

    node_rank = {nid: r for r in order for nid in layers[r]}
    node_group = {}
    # Sort outermost-first (-len(members)) so nested inner compartments (e.g. Nucleus inside Cytoplasm) win
    extra_col_w = {}
    if groups:
        for g in sorted(groups, key=lambda x: -len(x.get("members", []))):
            gid = g.get("id", "")
            mem = [m for m in g.get("members", []) if m in node_rank]
            for m in mem:
                node_group[m] = gid
            if not mem:
                continue
            ranks_in_g = {node_rank[m] for m in mem}
            if len(ranks_in_g) == 1:
                r0 = next(iter(ranks_in_g))
                lbl = str(g.get("label", g.get("id", "")))
                if meas is not None:
                    lw = meas.text_mm(lbl, fontsize=7.2, weight="bold")[0]
                else:
                    lw = len(lbl) * 1.6
                need_w = lw + 5.2
                extra_col_w[r0] = max(extra_col_w.get(r0, 0.0), need_w)

    if direction == "TB":
        # Vertical rank axis uses node HEIGHT; horizontal sibling axis uses node WIDTH.
        rank_gap = max(gap_y, 11.0)
        sib_gap = max(gap_x * 0.85, 9.0)
        rank_h = {r: max(sizes[n]["h"] for n in layers[r]) for r in order}
        # Reserve extra vertical clearance between ranks belonging to different compartments
        inter_gaps = []
        for idx in range(len(order) - 1):
            ga = {node_group.get(n) for n in layers[order[idx]]}
            gb = {node_group.get(n) for n in layers[order[idx + 1]]}
            inter_gaps.append(rank_gap + (7.5 if (node_group and ga != gb) else 0.0))
        total_h = sum(rank_h[r] for r in order) + sum(inter_gaps)

        def _row_sib_gap(a, b):
            if node_group and node_group.get(a) != node_group.get(b):
                return sib_gap + 7.0
            return sib_gap

        row_widths = {}
        for r in order:
            ms = layers[r]
            row_widths[r] = (sum(sizes[n]["w"] for n in ms) +
                             sum(_row_sib_gap(ms[i], ms[i + 1]) for i in range(len(ms) - 1)))
        total_w = max(row_widths.values()) if row_widths else 10.0
        pos = {}
        top = total_h
        for ri, r in enumerate(order):
            y_center = top - rank_h[r] / 2.0
            members = layers[r]
            wsum = row_widths[r]
            cur = (total_w - wsum) / 2.0
            for mi, n in enumerate(members):
                pos[n] = (cur + sizes[n]["w"] / 2.0, y_center)
                if mi + 1 < len(members):
                    cur += sizes[n]["w"] + _row_sib_gap(n, members[mi + 1])
            top -= rank_h[r] + (inter_gaps[ri] if ri < len(inter_gaps) else 0.0)
        if groups:
            pos, total_w, total_h = _separate_non_members_from_groups(
                pos, sizes, layers, groups, "TB", min_gap=sib_gap)
        return pos, total_w, total_h

    # LR layout (with optional row wrap when width exceeds wrap_w)
    col_w = {r: max(max(sizes[n]["w"] for n in layers[r]), extra_col_w.get(r, 0.0)) for r in order}
    col_h = {
        r: _col_height(layers[r], sizes, gap_y, node_group)
        for r in order
    }
    rank_grps = {r: {node_group.get(n) for n in layers[r]} for r in order}

    def _lr_col_gap(ra, rb):
        if node_group and rank_grps[ra] != rank_grps[rb]:
            return gap_x + 6.8
        return gap_x

    # Group-atomic LR row wrapping: never split a compartment across two wrapped rows
    rows, cur, cur_w = [], [], 0.0
    for r in order:
        w = col_w[r] + (_lr_col_gap(cur[-1], r) if cur else 0.0)
        if cur and wrap_w and cur_w + w > wrap_w:
            # If r shares a compartment with cur[-1], pull that whole compartment to the new row
            shared = {g for g in (rank_grps[r] & rank_grps[cur[-1]]) if g is not None}
            pull = []
            if shared:
                k = len(cur) - 1
                while k > 0 and (rank_grps[cur[k]] & shared):
                    k -= 1
                if not (rank_grps[cur[k]] & shared):
                    pull = cur[k + 1:]
                    cur = cur[:k + 1]
            rows.append(cur)
            cur = pull + [r]
            cur_w = sum(col_w[x] for x in cur) + sum(_lr_col_gap(cur[i], cur[i + 1]) for i in range(len(cur) - 1))
        else:
            cur.append(r)
            cur_w += w
    if cur:
        rows.append(cur)

    row_gap = max(gap_y * 1.4, 12.0)
    row_hs, row_ws = [], []
    for row in rows:
        gsum = sum(_lr_col_gap(row[i], row[i + 1]) for i in range(len(row) - 1))
        row_ws.append(sum(col_w[r] for r in row) + gsum)
        # Row height = MAX column height across columns placed side-by-side in the row
        row_hs.append(max(col_h[r] for r in row))
    total_h = sum(row_hs) + row_gap * max(len(rows) - 1, 0)
    total_w = max(row_ws) if row_ws else 10.0

    pos = {}
    top = total_h
    for ri, row in enumerate(rows):
        row_w = row_ws[ri]
        y_center = top - row_hs[ri] / 2.0
        xcur = (total_w - row_w) / 2.0
        for ci, r in enumerate(row):
            cx = xcur + col_w[r] / 2.0
            ys = _stack_members(layers[r], sizes, gap_y, y_center, node_group)
            for n, cy in ys.items():
                pos[n] = (cx, cy)
            xcur += col_w[r] + (_lr_col_gap(r, row[ci + 1]) if ci + 1 < len(row) else 0.0)
        top -= row_hs[ri] + row_gap
    if groups:
        pos, total_w, total_h = _separate_non_members_from_groups(
            pos, sizes, layers, groups, "LR", min_gap=gap_y)
    return pos, total_w, total_h
