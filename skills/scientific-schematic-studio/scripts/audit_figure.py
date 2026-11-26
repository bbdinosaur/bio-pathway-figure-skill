#!/usr/bin/env python3
"""audit_figure.py — deterministic geometry & consistency audit.

Usage: python3 audit_figure.py geometry.json [--spec spec.json] [--out audit.json]
Checks: out-of-bounds, node overlap, label-vs-node & label-vs-label overlap,
group/node-vs-legend overlap, legend==data mapping, units on numeric labels,
panel labels. Exit 1 on errors (warnings never block).
"""
import argparse, json, math, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


NUM_RE = re.compile(r"(?<![A-Za-z0-9_/'′\-])\d+(?:\.\d+)?(?![A-Za-z0-9_/'′\-])")
DIMLESS = {"%", "fold", "ratio", "pH", "AU", "U", "score", "log2", "-log10", "n", "x"}


def label_needs_unit(text):
    t = (text or "").strip()
    m = NUM_RE.findall(t)
    if not m:
        return False
    for d in DIMLESS:
        if t.endswith(d):
            return False
    if re.search(r"\d\s*(?:[A-Za-zµμ°%]+)[\s)]*$", t):
        return False
    return True


def _overlap_area(a, b):
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy


def _shift_box(b, ox, oy):
    return (b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy)


def _seg_hits_box(p0, p1, box, shrink=0.8):
    """Exact Liang-Barsky segment vs shrunk AABB check to detect edges slicing unrelated nodes."""
    x0, y0, x1, y1 = box[0] + shrink, box[1] + shrink, box[2] - shrink, box[3] - shrink
    if x1 <= x0 or y1 <= y0:
        return False
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, p0[0] - x0), (dx, x1 - p0[0]), (-dy, p0[1] - y0), (dy, y1 - p0[1])):
        if abs(pp) < 1e-9:
            if qq < 0:
                return False
        else:
            r = qq / pp
            if pp < 0:
                if r > t1:
                    return False
                t0 = max(t0, r)
            else:
                if r < t0:
                    return False
                t1 = min(t1, r)
    return t0 <= t1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geometry")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--margin", type=float, default=1.5)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    G = json.load(open(a.geometry, encoding="utf-8"))
    spec = json.load(open(a.spec, encoding="utf-8")) if a.spec else None
    W, H = G["canvas_mm"]
    errs, warns = [], []
    x0m, y0m, x1m, y1m = a.margin, a.margin, W - a.margin, H - a.margin

    spec_panels = {}
    spec_dir = os.path.dirname(os.path.abspath(a.spec)) if a.spec else None
    if spec:
        for pi, pp in enumerate(spec.get("panels", [])):
            spec_panels[pp.get("id", str(pi))] = pp

    data_verif = {}
    for pid, p in G.get("panels", {}).items():
        if p.get("type") == "chart":
            if p.get("legend_entries") and p["legend_entries"] != p["n_series"]:
                errs.append("panel %s: legend entries (%d) != series count (%d)"
                            % (pid, p["legend_entries"], p["n_series"]))
            slens = p.get("series_lengths") or []
            ncat = p.get("n_categories", 0)
            is_hue_scatter = (p.get("kind") == "scatter" and len(slens) >= 2 and sum(slens) == ncat)
            if slens and ncat and not is_hue_scatter and any(L != ncat for L in slens):
                errs.append("panel %s: plotted series lengths %s != categories (%d)"
                            % (pid, slens, ncat))
            if p.get("n_series", 0) == 0:
                errs.append("panel %s: chart has 0 plotted data series" % pid)
            s_cols = [sd.get("color") for sd in (p.get("series_data") or []) if sd.get("color")]
            if len(s_cols) >= 2 and len(set(c.lower() for c in s_cols)) < len(s_cols):
                warns.append("panel %s: multi-series chart has duplicate series colors %s" % (pid, s_cols))
            if p.get("unit") is not None and p.get("unit") == "":
                unit_cfg = (spec or {}).get("units_ok", [])
                if pid not in unit_cfg:
                    warns.append("panel %s: chart has values but empty unit" % pid)
            # Independent source-data fidelity cross-check for data_file-bound charts
            sp_panel = spec_panels.get(pid) or {}
            sp_ch = dict(sp_panel.get("chart") or {})
            if sp_ch and not sp_ch.get("kind"):
                pt_l = str(sp_panel.get("type", "")).strip().lower()
                if pt_l in ("bar", "barh", "stacked_bar", "line", "scatter", "box", "heatmap"):
                    sp_ch["kind"] = pt_l
            if sp_ch.get("data_file") and p.get("series_data"):
                try:
                    import fig_chart as FC
                    reloaded = FC.load_chart_table(sp_ch, spec_dir=spec_dir)
                    plotted_s = p.get("series_data") or []
                    src_s = reloaded.get("series") or []
                    checked, mismatches, err_checked, err_mismatches = 0, 0, 0, 0
                    for ps, ss in zip(plotted_s, src_s):
                        for pv, sv in zip(ps.get("values", []), ss.get("values", [])):
                            fv = FC._parse_float(sv)
                            if pv is None and math.isnan(fv):
                                checked += 1
                                continue
                            checked += 1
                            if pv is None or math.isnan(fv) or abs(float(pv) - fv) > 1e-3:
                                mismatches += 1
                        p_errs = ps.get("errors") or []
                        s_errs = ss.get("errors") or []
                        if p_errs and s_errs:
                            for pe, se in zip(p_errs, s_errs):
                                fe = FC._parse_float(se)
                                if (pe is None or (isinstance(pe, float) and math.isnan(pe))) and math.isnan(fe):
                                    err_checked += 1
                                    continue
                                err_checked += 1
                                if pe is None or math.isnan(fe) or abs(float(pe) - fe) > 1e-3:
                                    err_mismatches += 1
                    cat_ok = (not p.get("categories") or
                              [str(c) for c in p["categories"]] == [str(c) for c in reloaded.get("categories", [])])
                    ok_v = (mismatches == 0 and err_mismatches == 0 and cat_ok
                            and len(plotted_s) == len(src_s) and checked > 0)
                    data_verif[pid] = {
                        "data_file": os.path.basename(str(sp_ch["data_file"])),
                        "sheet_name": sp_ch.get("sheet_name"),
                        "source_sha256": p.get("source_sha256") or reloaded.get("_source_sha256"),
                        "n_values_checked": checked,
                        "n_errors_checked": err_checked,
                        "mismatches": mismatches + err_mismatches,
                        "categories_match": cat_ok,
                        "verified": ok_v,
                    }
                    if not ok_v:
                        errs.append("panel %s: plotted chart values/errors diverged from source data (%d mismatch(es))"
                                    % (pid, mismatches + err_mismatches))
                except Exception as ex:
                    data_verif[pid] = {"verified": False, "error": str(ex)[:120]}
                    warns.append("panel %s: source data re-verification skipped (%s)" % (pid, str(ex)[:80]))
            continue

        ox, oy = p.get("origin", [0.0, 0.0])
        nodes = p.get("nodes", {})
        boxes = {
            k: (v["x"] - v["w"] / 2.0 + ox, v["y"] - v["h"] / 2.0 + oy,
                v["x"] + v["w"] / 2.0 + ox, v["y"] + v["h"] / 2.0 + oy)
            for k, v in nodes.items()
        }
        # 1) Canvas bounds for nodes
        for k, b in boxes.items():
            if b[0] < x0m or b[1] < y0m or b[2] > x1m or b[3] > y1m:
                errs.append("panel %s: node %s out of canvas bounds %s (canvas %.1fx%.1f)"
                            % (pid, k, [round(v, 1) for v in b], W, H))
        # 2) Node-node overlap
        ks = list(boxes)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                if _overlap_area(boxes[ks[i]], boxes[ks[j]]) > 0.05:
                    errs.append("panel %s: nodes %s and %s overlap" % (pid, ks[i], ks[j]))

        # 2b) Disjoint group compartment box overlap check
        gboxes = {gid: _shift_box(gb, ox, oy) for gid, gb in (p.get("groups") or {}).items()}
        sp_cur = spec_panels.get(pid) or {}
        g_mems = {g.get("id"): set(g.get("members", [])) for g in sp_cur.get("groups", [])}
        gids = list(gboxes)
        for i in range(len(gids)):
            for j in range(i + 1, len(gids)):
                ga, gb = gids[i], gids[j]
                ma, mb = g_mems.get(ga, set()), g_mems.get(gb, set())
                if ma and mb and (ma <= mb or mb <= ma):
                    continue  # intentional nested sub-compartment
                if _overlap_area(gboxes[ga], gboxes[gb]) > 0.5:
                    warns.append("panel %s: group boxes %s and %s overlap" % (pid, ga, gb))
        # 2c) Check that no group compartment box accidentally encloses a non-member node
        for gid, gb in gboxes.items():
            mems = g_mems.get(gid, set())
            if not mems:
                continue
            for nk, nb in boxes.items():
                if nk in mems:
                    continue
                n_area = max((nb[2] - nb[0]) * (nb[3] - nb[1]), 0.1)
                if _overlap_area(gb, nb) / n_area > 0.35:
                    warns.append("panel %s: group %s visually encloses non-member node %s"
                                 % (pid, gid, nk))

        # 2d) Check for dangling group members referencing non-existent node IDs
        for g in sp_cur.get("groups", []):
            bad_m = [str(m) for m in g.get("members", []) if str(m) not in boxes]
            if bad_m:
                warns.append("panel %s: group %s references unknown node(s) %s"
                             % (pid, g.get("id", "?"), bad_m[:6]))
        # 2e) Check for contradictory opposing edges on identical (u, v) without distinguishing labels
        pair_kinds = {}
        for e in p.get("edges", []):
            pk = (e.get("subject"), e.get("object"))
            pair_kinds.setdefault(pk, []).append((e.get("kind", "activates"), bool(e.get("label"))))
        for (eu, ev), klist in pair_kinds.items():
            if len(klist) >= 2:
                ks_only = {k for k, _ in klist}
                has_pos = bool(ks_only & {"activates", "catalyzes"})
                has_neg = bool(ks_only & {"inhibits", "inhibits_dashed"})
                if has_pos and has_neg and not all(hl for _, hl in klist):
                    warns.append("panel %s: opposing edges on %s->%s (%s) without distinguishing labels"
                                 % (pid, eu, ev, sorted(ks_only)))

        # 3) Legend overlap with nodes or groups
        leg_b = p.get("legend_bbox")
        if leg_b:
            lbox = _shift_box(leg_b, ox, oy)
            for k, b in boxes.items():
                if _overlap_area(lbox, b) > 0.2:
                    errs.append("panel %s: node %s overlaps legend box" % (pid, k))
            for gid, gb in (p.get("groups") or {}).items():
                if _overlap_area(lbox, _shift_box(gb, ox, oy)) > 0.2:
                    warns.append("panel %s: group %s touches legend box" % (pid, gid))

        # 4) Edge labels vs nodes, edge polylines vs unrelated nodes, and edge labels vs edge labels
        label_boxes = []
        used_kinds = set()
        for e in p.get("edges", []):
            used_kinds.add(e.get("kind", "activates"))
            ends = {e.get("subject"), e.get("object")}
            pts_e = [(pt[0] + ox, pt[1] + oy) for pt in (e.get("points") or [])]
            if len(pts_e) >= 2:
                for k, box in boxes.items():
                    if k in ends:
                        continue
                    if any(_seg_hits_box(pts_e[si], pts_e[si + 1], box, shrink=0.8)
                           for si in range(len(pts_e) - 1)):
                        warns.append("panel %s: edge %s->%s crosses unrelated node %s"
                                     % (pid, e.get("subject"), e.get("object"), k))
                        break
            lb_raw = e.get("label_bbox")
            if lb_raw and e.get("label"):
                lb = _shift_box(lb_raw, ox, oy)
                lab_area = max((lb[2] - lb[0]) * (lb[3] - lb[1]), 0.1)
                if lb[0] < 0.2 or lb[1] < 0.2 or lb[2] > W - 0.2 or lb[3] > H - 0.2:
                    warns.append("panel %s: edge label '%s' near/outside canvas edge"
                                 % (pid, e["label"]))
                for k, box in boxes.items():
                    oa = _overlap_area(lb, box)
                    if oa > 0.1:
                        frac = oa / lab_area
                        if k in ends:
                            if frac > 0.35:
                                warns.append("panel %s: label '%s' overlaps endpoint node %s (%.0f%%)"
                                             % (pid, e["label"], k, frac * 100))
                        elif frac > 0.20:
                            errs.append("panel %s: label '%s' overlaps unrelated node %s"
                                        % (pid, e["label"], k))
                for prev_lab, prev_b in label_boxes:
                    if _overlap_area(lb, prev_b) / lab_area > 0.25:
                        warns.append("panel %s: edge labels '%s' and '%s' overlap"
                                     % (pid, prev_lab, e["label"]))
                label_boxes.append((e["label"], lb))

            if label_needs_unit(e.get("label", "")):
                warns.append("panel %s: edge label '%s' has number without unit"
                             % (pid, e["label"]))

        # 5) Legend kind consistency with edges (canonicalized against biological synonyms)
        sp = spec_panels.get(pid)
        if sp and sp.get("legend"):
            try:
                import fig_style as _FS
                _ck = _FS.canonical_edge_kind
            except Exception:
                _ck = lambda x: x
            leg_kinds = {_ck(it.get("kind")) for it in sp["legend"].get("items", []) if it.get("kind")}
            if leg_kinds:
                missing_k = sorted(k for k in {_ck(u) for u in used_kinds} if k not in leg_kinds)
                if missing_k:
                    warns.append("panel %s: edge kind(s) %s not listed in panel legend"
                                 % (pid, missing_k))

        p["_nn"] = sum(1 for v in nodes.values() if not v.get("source"))
        p["_en"] = sum(1 for e in p.get("edges", []) if not e.get("source"))
        p["_nt"] = len(nodes)
        p["_et"] = len(p.get("edges", []))
        # 6) Check for unintentionally disconnected/orphan nodes in multi-node schematics
        if len(nodes) >= 3 and p.get("edges"):
            deg = {k: 0 for k in nodes}
            for e in p.get("edges", []):
                if e.get("subject") in deg:
                    deg[e["subject"]] += 1
                if e.get("object") in deg:
                    deg[e["object"]] += 1
            sp_nodes = {str(n.get("id")): n for n in (sp_cur.get("nodes") or [])}
            orphans = [k for k, d in deg.items()
                       if d == 0 and not (sp_nodes.get(k) or {}).get("standalone")]
            if orphans:
                warns.append("panel %s: disconnected node(s) %s (connect with edge or mark standalone:true)"
                             % (pid, orphans[:6]))

    if spec:
        n_panels = len(spec.get("panels", []))
        if n_panels > 1:
            have = [pp.get("panel_label", True) for pp in spec["panels"]]
            if not all(have):
                errs.append("multi-panel figure missing panel labels (A/B/C)")
        for pi, pp in enumerate(spec.get("panels", [])):
            pid = pp.get("id", str(pi))
            if pp.get("type") == "chart":
                ch = pp.get("chart", {})
                if ch.get("data_file"):
                    continue  # hydrated from file at build time
                cats = ch.get("categories", [])
                sers = ch.get("series", [])
                if cats and sers:
                    nvals = {len(s.get("values", [])) for s in sers}
                    if nvals != {len(cats)}:
                        errs.append("panel %s: series value counts %s != categories (%d)"
                                    % (pid, nvals, len(cats)))

    for pid, p in G.get("panels", {}).items():
        sc = p.get("scale", 1.0)
        if sc < 0.55:
            warns.append("panel %s: scale %.2f -> fonts below ~5pt, split panel or shorten labels"
                         % (pid, sc))

    tot_nt = sum(int(p.get("_nt", 0)) for p in G.get("panels", {}).values() if isinstance(p, dict))
    tot_et = sum(int(p.get("_et", 0)) for p in G.get("panels", {}).values() if isinstance(p, dict))
    tot_nn = sum(int(p.get("_nn", 0)) for p in G.get("panels", {}).values() if isinstance(p, dict))
    tot_en = sum(int(p.get("_en", 0)) for p in G.get("panels", {}).values() if isinstance(p, dict))
    tot_nosrc = tot_nn + tot_en
    if tot_nosrc:
        warns.append("provenance: %d/%d element(s) lack source locators "
                     "(add source:{file,locator} to spec nodes/edges)" % (tot_nosrc, tot_nt + tot_et))

    rep = {
        "errors": errs, "warnings": warns,
        "canvas_mm": [round(W, 1), round(H, 1)],
        "provenance": {
            "nodes_sourced": tot_nt - tot_nn, "nodes_total": tot_nt,
            "edges_sourced": tot_et - tot_en, "edges_total": tot_et,
        },
        "data_verification": data_verif,
        "n_errors": len(errs), "n_warnings": len(warns),
        "status": "pass" if not errs else "fail"
    }
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
