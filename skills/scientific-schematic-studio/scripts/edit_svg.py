#!/usr/bin/env python3
"""edit_svg.py — source-preserving edits on an existing SVG, then render PNG/PDF.

Usage:
  python3 edit_svg.py input.svg --inspect
  python3 edit_svg.py input.svg ops.json --out-dir DIR [--stem name_edited] [--dpi 300]
Ops (ops.json = {"ops": [...]}):
  {"op":"retext","gid":"node-A","text":"New label"}
  {"op":"replace_text","find":"Old text","replace":"New text"}
  {"op":"set_attr","gid":"node-A","attr":"fill","value":"#D55E00"}
  {"op":"move","gid":"node-A","dx":10,"dy":-5}
  {"op":"swap_edge","gid":"edge-X-Y"}        reverse line/path + flip marker or split -head
  {"op":"set_marker","gid":"edge-X-Y","marker":"arrow|tbar|open|none"}
  {"op":"delete","gid":"edge-X-Y"}           remove group/element by id
  {"op":"add_node","id":"node-Z","label":"Z","x":100,"y":60,"w":80,"h":32}
  {"op":"add_note","text":"...","x":10,"y":10,"fs":7}
Original file is copied unmodified next to the edited one (source preservation).
"""
import argparse, json, sys, os, shutil, math, re
import xml.etree.ElementTree as ET

NS = "http://www.w3.org/2000/svg"


def q(tag):
    return "{%s}%s" % (NS, tag)


def load(path):
    ET.register_namespace("", NS)
    return ET.parse(path)


def find_by_id(root, gid):
    if root.get("id") == gid:
        return root
    for el in root.iter():
        if el.get("id") == gid:
            return el
    # Fallback: match data-id or inkscape:label on external Inkscape/Illustrator SVGs
    for el in root.iter():
        if el.get("data-id") == gid:
            return el
        for k, v in el.attrib.items():
            if k.endswith("}label") and v == gid:
                return el
    return None


def build_parent_map(root):
    return {c: p for p in root.iter() for c in p}


def first_shape(g):
    # Prefer semantic primary shape/line subgroup inside composite node/edge layers (skip shadow/label/badge)
    for ch in list(g):
        cid = ch.get("id") or ""
        if cid.endswith("-shape") or cid.endswith("-line") or cid.endswith("-box"):
            sub = first_shape(ch)
            if sub is not None:
                return sub
    skip_set = set()
    for ch in list(g):
        cid = ch.get("id") or ""
        if cid.endswith("-shadow") or cid.startswith("elabel-") or cid.startswith("badge-") or cid.endswith("-head") or cid.endswith("-head2"):
            for desc in ch.iter():
                skip_set.add(desc)
    for tag in ("path", "line", "rect", "ellipse", "circle", "polygon", "polyline"):
        for el in g.findall(".//%s" % q(tag)):
            if el not in skip_set:
                return el
    return None


def _element_endpoints(el):
    """Return [(x0,y0), ..., (x1,y1)] for a line/polyline/open path connector, else None."""
    tag = el.tag.split("}")[-1]
    if tag == "line":
        try:
            return [(float(el.get("x1", 0)), float(el.get("y1", 0))),
                    (float(el.get("x2", 0)), float(el.get("y2", 0)))]
        except Exception:
            return None
    if tag == "polyline":
        nums = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', el.get("points", ""))
        if len(nums) >= 4:
            return [(float(nums[i]), float(nums[i + 1])) for i in range(0, len(nums) - 1, 2)]
        return None
    if tag == "path":
        dd = el.get("d", "")
        if not dd or re.search(r"[Zz]\s*$", dd):
            return None
        pts = _parse_path_coords(dd)
        if pts and len(pts) >= 2:
            return pts
    return None


def _accum_affine(el, pmap):
    """Compose ancestor translate/scale/matrix transforms into (a, b, c, d, e, f)."""
    chain = []
    cur = el
    while cur is not None:
        tf = cur.get("transform")
        if tf:
            chain.append(tf)
        cur = pmap.get(cur)
    # Apply outermost -> innermost: M = M_outer * M_inner
    a, b, c, d, e, f = 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

    def _mul(m1, m2):
        a1, b1, c1, d1, e1, f1 = m1
        a2, b2, c2, d2, e2, f2 = m2
        return (
            a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1,
        )

    for tf in reversed(chain):
        for m in re.finditer(r"(translate|scale|matrix)\s*\(([^)]+)\)", tf):
            fn = m.group(1)
            nums = [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', m.group(2))]
            if fn == "translate" and len(nums) >= 1:
                tx = nums[0]
                ty = nums[1] if len(nums) >= 2 else 0.0
                a, b, c, d, e, f = _mul((a, b, c, d, e, f), (1.0, 0.0, 0.0, 1.0, tx, ty))
            elif fn == "scale" and len(nums) >= 1:
                sx = nums[0]
                sy = nums[1] if len(nums) >= 2 else sx
                a, b, c, d, e, f = _mul((a, b, c, d, e, f), (sx, 0.0, 0.0, sy, 0.0, 0.0))
            elif fn == "matrix" and len(nums) == 6:
                a, b, c, d, e, f = _mul((a, b, c, d, e, f), tuple(nums))
    return (a, b, c, d, e, f)


def _apply_affine(x, y, mat):
    a, b, c, d, e, f = mat
    return (a * x + c * y + e, b * x + d * y + f)


def _world_delta_to_local(dx, dy, mat):
    """Convert a world-space displacement (dx, dy) into local coordinates via linear inverse."""
    a, b, c, d = mat[0], mat[1], mat[2], mat[3]
    det = a * d - b * c
    if abs(det) < 1e-9:
        return dx, dy
    return ((d * dx - c * dy) / det, (-b * dx + a * dy) / det)


def _shift_connector_endpoint(el, which, ldx, ldy):
    """Shift start (which=0) or end (which=1) endpoint of <line>/<polyline>/<path> by local (ldx, ldy)."""
    if el.tag == q("line"):
        kx, ky = ("x1", "y1") if which == 0 else ("x2", "y2")
        try:
            el.set(kx, "%.3f" % (float(el.get(kx, "0")) + ldx))
            el.set(ky, "%.3f" % (float(el.get(ky, "0")) + ldy))
            return True
        except Exception:
            return False
    if el.tag == q("polyline"):
        pts_raw = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', el.get("points", ""))
        if len(pts_raw) >= 4:
            pts = [[float(pts_raw[i]), float(pts_raw[i + 1])] for i in range(0, len(pts_raw) - 1, 2)]
            idx = 0 if which == 0 else (len(pts) - 1)
            pts[idx][0] += ldx
            pts[idx][1] += ldy
            el.set("points", " ".join("%.3f,%.3f" % (p[0], p[1]) for p in pts))
            return True
        return False
    if el.tag == q("path") and el.get("d"):
        segs = _parse_path_segments(el.get("d"))
        if not segs:
            return False
        new_segs = []
        for si, (kind, p0, ctrls, p1) in enumerate(segs):
            np0, nctrls, np1 = p0, list(ctrls), p1
            if which == 0 and si == 0:
                np0 = (p0[0] + ldx, p0[1] + ldy)
                if kind in ("C", "Q") and nctrls:
                    nctrls[0] = (nctrls[0][0] + ldx, nctrls[0][1] + ldy)
            if which == 1 and si == len(segs) - 1:
                np1 = (p1[0] + ldx, p1[1] + ldy)
                if kind == "C" and len(nctrls) >= 2:
                    nctrls[1] = (nctrls[1][0] + ldx, nctrls[1][1] + ldy)
                elif kind == "Q" and nctrls:
                    nctrls[0] = (nctrls[0][0] + ldx, nctrls[0][1] + ldy)
            new_segs.append((kind, np0, nctrls, np1))
        out = ["M %.3f %.3f" % new_segs[0][1]]
        for kind, _, nctrls, np1 in new_segs:
            if kind == "L":
                out.append("L %.3f %.3f" % np1)
            elif kind == "C":
                out.append("C %.3f %.3f %.3f %.3f %.3f %.3f" % (
                    nctrls[0][0], nctrls[0][1], nctrls[1][0], nctrls[1][1], np1[0], np1[1]))
            elif kind == "Q":
                out.append("Q %.3f %.3f %.3f %.3f" % (nctrls[0][0], nctrls[0][1], np1[0], np1[1]))
        el.set("d", " ".join(out))
        return True
    return False


def _accum_translate(el, pmap):
    """Return effective world translation offset (e, f) for el under ancestor transforms."""
    mat = _accum_affine(el, pmap)
    return mat[4], mat[5]


def _list_svg_edges(root):
    """Inventory all connector-like line/polyline/open-path elements (named or unnamed)."""
    pmap = build_parent_map(root)
    skip_set = set()
    for el in root.iter():
        if el.tag == q("defs") or el.get("data-layer") in ("compartment", "legend") or (el.get("id") or "").startswith("legend-"):
            for ch in el.iter():
                skip_set.add(ch)
    out = []
    for el in root.iter():
        if el in skip_set or "-membrane" in (el.get("id") or ""):
            continue
        pts = _element_endpoints(el)
        if not pts:
            continue
        mat = _accum_affine(el, pmap)
        p0 = _apply_affine(pts[0][0], pts[0][1], mat)
        p1 = _apply_affine(pts[-1][0], pts[-1][1], mat)
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 4.0 and len(pts) == 2:
            continue
        pgid = el.get("id")
        cur = pmap.get(el)
        while not pgid and cur is not None:
            if cur.get("id"):
                pgid = cur.get("id")
            cur = pmap.get(cur)
        st = el.get("style", "")
        mk_end = el.get("marker-end") or (re.search(r"marker-end\s*:\s*([^;]+)", st).group(1).strip()
                                          if re.search(r"marker-end\s*:\s*([^;]+)", st) else None)
        dash = el.get("stroke-dasharray") or (re.search(r"stroke-dasharray\s*:\s*([^;]+)", st).group(1).strip()
                                              if re.search(r"stroke-dasharray\s*:\s*([^;]+)", st) else None)
        out.append({
            "edge_idx": len(out),
            "el": el,
            "id": el.get("id"),
            "group_id": pgid,
            "p0": [round(p0[0], 1), round(p0[1], 1)],
            "p1": [round(p1[0], 1), round(p1[1], 1)],
            "mid": ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0),
            "marker_end": mk_end,
            "dash": dash,
        })
    return out


def _shape_bbox(el, pmap=None):
    """Return world (x0, y0, x1, y1) for rect/ellipse/circle elements (incl. ancestor affine transforms)."""
    tag = el.tag.split("}")[-1]
    mat = _accum_affine(el, pmap) if pmap is not None else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    try:
        if tag == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width", 0)), float(el.get("height", 0))
            if w > 0 and h > 0:
                p0 = _apply_affine(x, y, mat)
                p1 = _apply_affine(x + w, y + h, mat)
                return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
        elif tag == "ellipse":
            cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
            rx, ry = float(el.get("rx", 0)), float(el.get("ry", 0))
            if rx > 0 and ry > 0:
                p0 = _apply_affine(cx - rx, cy - ry, mat)
                p1 = _apply_affine(cx + rx, cy + ry, mat)
                return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
        elif tag == "circle":
            cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
            r = float(el.get("r", 0))
            if r > 0:
                p0 = _apply_affine(cx - r, cy - r, mat)
                p1 = _apply_affine(cx + r, cy + r, mat)
                return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
        elif tag == "polygon":
            nums = [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', el.get("points", ""))]
            if len(nums) >= 6:
                wpts = [_apply_affine(nums[i], nums[i + 1], mat) for i in range(0, len(nums) - 1, 2)]
                xs = [p[0] for p in wpts]; ys = [p[1] for p in wpts]
                if max(xs) - min(xs) > 1.0 and max(ys) - min(ys) > 1.0:
                    return (min(xs), min(ys), max(xs), max(ys))
        elif tag == "path":
            dd = (el.get("d") or "").strip()
            if dd and re.search(r"[Zz]\s*$", dd):
                segs = _parse_path_segments(dd)
                if segs:
                    pts = [segs[0][1]]
                    for _, _, ctrls, p_end in segs:
                        pts.extend(ctrls)
                        pts.append(p_end)
                    wpts = [_apply_affine(x, y, mat) for x, y in pts]
                    xs = [p[0] for p in wpts]; ys = [p[1] for p in wpts]
                    if max(xs) - min(xs) > 2.0 and max(ys) - min(ys) > 2.0:
                        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        pass
    return None


def _text_world_xy(t_el, pmap):
    mat = _accum_affine(t_el, pmap)
    ts0 = t_el.find("./%s" % q("tspan"))
    raw_x = t_el.get("x") if t_el.get("x") is not None else (ts0.get("x") if ts0 is not None else None)
    raw_y = t_el.get("y") if t_el.get("y") is not None else (ts0.get("y") if ts0 is not None else None)
    try:
        lx = float(raw_x.split()[0]) if raw_x is not None else 0.0
        ly = float(raw_y.split()[0]) if raw_y is not None else 0.0
        if raw_x is not None or raw_y is not None or mat[4] or mat[5]:
            return _apply_affine(lx, ly, mat)
    except Exception:
        pass
    return None


def _is_single_node_group(g_el, pmap):
    """True only if <g> represents a single node (not a multi-node Illustrator/BioRender layer <g>)."""
    if g_el is None or g_el.tag != q("g"):
        return False
    eid = g_el.get("id") or ""
    if g_el.get("data-layer") == "node" or eid.startswith("node-"):
        return True
    # Count direct/nested box-sized shapes (>18px) and distinct texts
    big_shapes = 0
    for ch in g_el.iter():
        if ch is g_el:
            continue
        if ch.tag in (q("rect"), q("ellipse"), q("circle"), q("polygon"), q("path")):
            bb = _shape_bbox(ch, pmap=pmap)
            if bb is not None and (bb[2] - bb[0]) >= 18.0 and (bb[3] - bb[1]) >= 14.0:
                big_shapes += 1
                if big_shapes > 2:
                    return False
    t_els = [t for t in g_el.findall(".//%s" % q("text")) if "".join(t.itertext()).strip()]
    if len(t_els) > 2:
        return False
    if len(t_els) == 2:
        p0 = _text_world_xy(t_els[0], pmap)
        p1 = _text_world_xy(t_els[1], pmap)
        if p0 and p1 and math.hypot(p0[0] - p1[0], p0[1] - p1[1]) > 50.0:
            return False
    return big_shapes <= 2 and len(t_els) >= 1


def _collect_node_anchors(root, pmap):
    """Collect world-space (label, bbox, center) anchors for non-legend/non-compartment nodes."""
    skip_set = set()
    for el in root.iter():
        dl = el.get("data-layer") or ""
        eid = el.get("id") or ""
        if el.tag == q("defs") or dl in ("legend", "compartment", "edge") or eid.startswith("legend-") or eid.startswith("group-") or eid.startswith("elabel-") or eid.startswith("edge-"):
            for ch in el.iter():
                skip_set.add(ch)
    anchors = []
    seen_groups = set()
    # 1) Single-node groups first (e.g. node-PI3K, or a <g> wrapping 1 node shape + its text)
    for el in root.iter(q("g")):
        if el in skip_set:
            continue
        eid = el.get("id") or ""
        if eid.startswith("edge-") or eid.startswith("panel-"):
            continue
        if not _is_single_node_group(el, pmap):
            continue
        t_els = [t for t in el.findall("./%s" % q("text")) if t not in skip_set]
        if not t_els and (el.get("data-layer") == "node" or eid.startswith("node-")):
            t_els = [t for t in el.findall(".//%s" % q("text")) if t not in skip_set]
        if not t_els:
            continue
        lbl = " ".join("".join(t.itertext()).strip() for t in t_els[:1]).strip()
        if not lbl:
            continue
        sh = first_shape(el)
        bb = _shape_bbox(sh, pmap=pmap) if sh is not None else None
        if bb is None:
            for ch in el.iter():
                if ch is not el and ch.tag in (q("rect"), q("ellipse"), q("circle"), q("polygon"), q("path")):
                    bb = _shape_bbox(ch, pmap=pmap)
                    if bb is not None:
                        break
        if bb is not None:
            cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
            anchors.append({"label": lbl[:60], "bbox": bb, "center": (cx, cy), "gid": eid or None})
            seen_groups.add(el)
    # 2) Ungrouped texts (fall back to sibling shape bbox or synthetic text box)
    for t in root.iter(q("text")):
        if t in skip_set:
            continue
        par = pmap.get(t)
        if par in seen_groups:
            continue
        lbl = "".join(t.itertext()).strip()
        if not lbl or len(lbl) > 64:
            continue
        # Skip if already inside a seen composite node
        cur = par
        inside_seen = False
        while cur is not None:
            if cur in seen_groups:
                inside_seen = True
                break
            cur = pmap.get(cur)
        if inside_seen:
            continue
        xy = _text_world_xy(t, pmap)
        if xy is None:
            continue
        bb = None
        if par is not None:
            best_d = 90.0
            for ch in list(par):
                if ch.tag in (q("rect"), q("ellipse"), q("circle"), q("polygon"), q("path")):
                    cb = _shape_bbox(ch, pmap=pmap)
                    if cb is not None and (cb[2] - cb[0]) < 450 and (cb[3] - cb[1]) < 260:
                        if cb[0] - 8 <= xy[0] <= cb[2] + 8 and cb[1] - 8 <= xy[1] <= cb[3] + 8:
                            bb = cb
                            break
                        d = math.hypot((cb[0] + cb[2]) / 2.0 - xy[0], (cb[1] + cb[3]) / 2.0 - xy[1])
                        if d < best_d:
                            best_d, bb = d, cb
        if bb is None:
            hw = max(len(lbl) * 3.2, 16.0)
            bb = (xy[0] - hw, xy[1] - 10.0, xy[0] + hw, xy[1] + 6.0)
        cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
        anchors.append({"label": lbl[:60], "bbox": bb, "center": (cx, cy), "gid": t.get("id")})
    return anchors


def _point_to_box_dist(pt, bb):
    dx = max(bb[0] - pt[0], 0.0, pt[0] - bb[2])
    dy = max(bb[1] - pt[1], 0.0, pt[1] - bb[3])
    return math.hypot(dx, dy)


def _infer_edge_kind(el, mk_end, dash):
    mk = (mk_end or "").lower()
    st = (el.get("style") or "").lower()
    mk_start = (el.get("marker-start") or "")
    if not mk_start:
        ms = re.search(r"marker-start\s*:\s*([^;]+)", st)
        mk_start = ms.group(1).strip() if ms else ""
    stroke = (el.get("stroke") or "").lower()
    if not stroke:
        ms = re.search(r"stroke\s*:\s*([^;]+)", st)
        stroke = ms.group(1).strip() if ms else ""
    if "tbar" in mk or "blunt" in mk or "inhibit" in mk:
        return "inhibits_dashed" if dash else "inhibits"
    if "open" in mk:
        return "translocates"
    if mk_start and mk_end:
        return "binds"
    if stroke in ("#b91c1c", "#c0392b", "#d55e00", "#dc2626", "red"):
        return "inhibits_dashed" if dash else "inhibits"
    if stroke in ("#7c3aed", "#6a1b9a", "purple"):
        return "binds"
    if dash:
        return "translocates"
    return "activates"


def _annotate_edges_with_labels(root, raw_edges, pmap):
    anchors = _collect_node_anchors(root, pmap)
    for ed in raw_edges:
        p0, p1 = tuple(ed["p0"]), tuple(ed["p1"])
        from_lbl, to_lbl = None, None
        if anchors:
            b0 = min(anchors, key=lambda a: (_point_to_box_dist(p0, a["bbox"]), math.hypot(p0[0] - a["center"][0], p0[1] - a["center"][1])))
            b1 = min(anchors, key=lambda a: (_point_to_box_dist(p1, a["bbox"]), math.hypot(p1[0] - a["center"][0], p1[1] - a["center"][1])))
            if _point_to_box_dist(p0, b0["bbox"]) <= 45.0:
                from_lbl = b0["label"]
            if _point_to_box_dist(p1, b1["bbox"]) <= 45.0:
                to_lbl = b1["label"]
        ed["from_label"] = from_lbl
        ed["to_label"] = to_lbl
        ed["inferred_kind"] = _infer_edge_kind(ed["el"], ed.get("marker_end"), ed.get("dash"))
    return raw_edges


def inspect_svg(path):
    tree = load(path)
    root = tree.getroot()
    pmap = build_parent_map(root)
    groups = []
    named_shapes = []
    texts = []
    markers = []
    shape_tags = {q(t) for t in ("path", "line", "polyline", "rect", "ellipse", "circle", "polygon")}
    for el in root.iter():
        eid = el.get("id")
        ilabel = next((v for k, v in el.attrib.items() if k.endswith("}label")), None)
        if el.tag == q("g") and (eid or ilabel):
            groups.append(eid or ilabel)
        elif el.tag in shape_tags and eid:
            named_shapes.append("%s:%s" % (el.tag.split("}")[-1], eid))
        elif el.tag == q("marker") and eid:
            markers.append(eid)
        elif el.tag == q("text"):
            full = "".join(el.itertext()).strip()
            if full:
                pgid = eid
                cur = pmap.get(el)
                while not pgid and cur is not None:
                    if cur.get("id"):
                        pgid = cur.get("id")
                    cur = pmap.get(cur)
                mat = _accum_affine(el, pmap)
                ts0 = el.find("./%s" % q("tspan"))
                raw_x = el.get("x") if el.get("x") is not None else (ts0.get("x") if ts0 is not None else None)
                raw_y = el.get("y") if el.get("y") is not None else (ts0.get("y") if ts0 is not None else None)
                try:
                    lx = float(raw_x.split()[0]) if raw_x is not None else 0.0
                    ly = float(raw_y.split()[0]) if raw_y is not None else 0.0
                    if raw_x is not None or raw_y is not None or mat[4] or mat[5]:
                        px, py = _apply_affine(lx, ly, mat)
                        wx, wy = round(px, 1), round(py, 1)
                    else:
                        wx, wy = None, None
                except Exception:
                    wx, wy = raw_x, raw_y
                texts.append({
                    "id": eid, "group_id": pgid, "text": full[:120],
                    "x": wx, "y": wy
                })
    # Inventory connector edges (including unnamed <path>/<line>/<polyline>) + semantic endpoints
    raw_edges = _annotate_edges_with_labels(root, _list_svg_edges(root), pmap)
    edges_out = []
    for ed in raw_edges[:50]:
        edges_out.append({
            "edge_idx": ed["edge_idx"],
            "id": ed["id"],
            "group_id": ed["group_id"],
            "from_label": ed.get("from_label"),
            "to_label": ed.get("to_label"),
            "inferred_kind": ed.get("inferred_kind"),
            "p0": ed["p0"],
            "p1": ed["p1"],
            "marker_end": ed["marker_end"],
            "dash": ed["dash"],
        })
    # Collect compact node bounding boxes (for spatial awareness in prepare)
    anchors = _collect_node_anchors(root, pmap)
    node_boxes = []
    for anc in anchors[:40]:
        lbl, bb = anc.get("label"), anc.get("bbox")
        if lbl and bb:
            node_boxes.append({
                "label": lbl[:60],
                "bbox": [round(bb[0], 1), round(bb[1], 1), round(bb[2], 1), round(bb[3], 1)],
            })
    return {
        "path": path,
        "width": root.get("width"), "height": root.get("height"),
        "viewBox": root.get("viewBox"),
        "n_groups_with_id": len(groups), "groups": groups[:80],
        "named_shapes": named_shapes[:60],
        "node_boxes": node_boxes,
        "edges": edges_out,
        "markers": markers, "n_texts": len(texts), "texts": texts[:80],
    }


def _set_text_preserve_tspan(t_el, new_text):
    tspans = t_el.findall("./%s" % q("tspan"))
    lines = new_text.split("\n")
    if tspans:
        for i, ts in enumerate(tspans):
            ts.text = lines[i] if i < len(lines) else ""
        if len(lines) > len(tspans):
            tspans[-1].text = (tspans[-1].text + " " + " ".join(lines[len(tspans):])).strip()
    else:
        t_el.text = new_text


def _find_by_text(root, query, want_shape=False):
    """Locate an element (or its enclosing <g> / nearest sibling shape) by text content."""
    qstr = str(query or "").strip()
    if not qstr:
        return None
    pmap = build_parent_map(root)
    hit_t = None
    for t in root.iter(q("text")):
        full = "".join(t.itertext()).strip()
        if full == qstr or qstr in full:
            hit_t = t
            if full == qstr:
                break
    if hit_t is None:
        return None
    parent = pmap.get(hit_t)
    if parent is not None and parent is not root and _is_single_node_group(parent, pmap):
        if want_shape:
            sh = first_shape(parent)
            if sh is not None:
                return sh
        return parent
    if want_shape and parent is not None:
        # Look for an adjacent sibling shape (rect/ellipse/circle/polygon/closed-path) containing or nearest to text world (x,y)
        wxy = _text_world_xy(hit_t, pmap)
        best, best_d = None, float("inf")
        for ch in list(parent):
            if ch.tag in (q("rect"), q("ellipse"), q("circle"), q("polygon"), q("path")):
                cb = _shape_bbox(ch, pmap=pmap)
                if cb is None:
                    continue
                if wxy is not None:
                    cx, cy = (cb[0] + cb[2]) / 2.0, (cb[1] + cb[3]) / 2.0
                    d = _point_to_box_dist(wxy, cb) * 2.0 + math.hypot(cx - wxy[0], cy - wxy[1]) * 0.25
                    if d < best_d:
                        best_d, best = d, ch
        if best is not None and best_d < 120.0:
            return best
    return hit_t


def _resolve_el(root, o, want_shape=False):
    if o.get("gid"):
        el = find_by_id(root, o["gid"])
        if el is not None:
            return el
    if o.get("by_text"):
        return _find_by_text(root, o["by_text"], want_shape=want_shape)
    return None


def _parse_viewbox(root):
    vb = root.get("viewBox")
    if vb:
        parts = [float(x) for x in re.split(r"[\s,]+", vb.strip()) if x]
        if len(parts) == 4:
            return parts
    try:
        w = float(re.match(r"[\d.]+", str(root.get("width", "400"))).group(0))
        h = float(re.match(r"[\d.]+", str(root.get("height", "300"))).group(0))
        return [0.0, 0.0, w, h]
    except Exception:
        return None


def _expand_viewbox_if_needed(root, x0, y0, x1, y1, pad=10.0):
    vb = _parse_viewbox(root)
    if not vb:
        return
    vx, vy, vw, vh = vb
    nx0 = min(vx, x0 - pad)
    ny0 = min(vy, y0 - pad)
    nx1 = max(vx + vw, x1 + pad)
    ny1 = max(vy + vh, y1 + pad)
    nw, nh = nx1 - nx0, ny1 - ny0
    if abs(nx0 - vx) < 0.1 and abs(ny0 - vy) < 0.1 and abs(nw - vw) < 0.1 and abs(nh - vh) < 0.1:
        return
    root.set("viewBox", "%.2f %.2f %.2f %.2f" % (nx0, ny0, nw, nh))
    # Scale physical width/height proportionally if present with unit
    for attr, old_v, new_v in (("width", vw, nw), ("height", vh, nh)):
        cur = root.get(attr)
        if cur and old_v > 0:
            m = re.match(r"^\s*([\d.]+)\s*([a-zA-Z%]*)\s*$", cur)
            if m:
                val = float(m.group(1)) * (new_v / old_v)
                root.set(attr, "%.2f%s" % (val, m.group(2)))


def op_retext(root, o, log, errs):
    el = _resolve_el(root, o)
    ref = o.get("gid") or o.get("by_text")
    if el is None:
        errs.append("retext: target %s not found" % ref)
        return
    if el.tag == q("text"):
        texts = [el]
    else:
        # Exclude badge-* text when retexting a composite node so quantitative callouts survive
        pmap = build_parent_map(root)
        gid_s = str(o.get("gid") or "")
        texts = []
        for t in el.findall(".//%s" % q("text")):
            if not gid_s.startswith("badge-"):
                cur, is_badge = t, False
                while cur is not None and cur is not el:
                    if (cur.get("id") or "").startswith("badge-"):
                        is_badge = True
                        break
                    cur = pmap.get(cur)
                if is_badge:
                    continue
            texts.append(t)
    if not texts:
        errs.append("retext: no <text> under %s" % ref)
        return
    lines = str(o["text"]).split("\n")
    if len(texts) == 1:
        _set_text_preserve_tspan(texts[0], str(o["text"]))
    else:
        for i, t in enumerate(texts):
            _set_text_preserve_tspan(t, lines[i] if i < len(lines) else "")
    log.append("retext %s -> %r" % (ref, str(o["text"])[:40]))


def op_replace_text(root, o, log, errs):
    find_s = str(o.get("find", ""))
    rep_s = str(o.get("replace", ""))
    if not find_s:
        errs.append("replace_text: empty 'find'")
        return
    scope = root
    if o.get("gid"):
        scope = find_by_id(root, o["gid"])
        if scope is None:
            errs.append("replace_text: gid %s not found" % o["gid"])
            return
    hits = 0
    for t in scope.iter(q("text")):
        tspans = t.findall(".//%s" % q("tspan"))
        matched = False
        for ts in tspans:
            if ts.text and find_s in ts.text:
                ts.text = ts.text.replace(find_s, rep_s)
                hits += 1
                matched = True
        if not matched:
            if t.text and find_s in t.text:
                t.text = t.text.replace(find_s, rep_s)
                hits += 1
            elif tspans:
                joined = "".join(t.itertext())
                if find_s in joined:
                    _set_text_preserve_tspan(t, joined.replace(find_s, rep_s))
                    hits += 1
    if hits == 0:
        errs.append("replace_text: %r not found in SVG text" % find_s)
    else:
        log.append("replace_text %r -> %r (%d hit(s))" % (find_s[:30], rep_s[:30], hits))


def op_set_attr(root, o, log, errs):
    attr, val = o["attr"], str(o["value"])
    text_attr = attr.lower() in ("font-size", "font-weight", "font-family", "text-anchor")
    if o.get("edge_idx") is not None or (o.get("from_text") and o.get("to_text")):
        el, ref = _resolve_edge(root, o)
    else:
        el = _resolve_el(root, o, want_shape=not text_attr)
        ref = o.get("gid") or o.get("by_text")
    if el is None:
        errs.append("set_attr: target %s not found" % ref)
        return
    # Apply typography attrs or text-only group attrs directly to child <text>/<tspan>
    sh = first_shape(el) if el.tag == q("g") else None
    if text_attr or el.tag == q("text") or (el.tag == q("g") and sh is None and el.findall(".//%s" % q("text"))):
        t_els = [el] if el.tag == q("text") else el.findall(".//%s" % q("text"))
        for te in t_els:
            _set_style_prop(te, attr, val)
            for ts in te.findall(".//%s" % q("tspan")):
                if ts.get(attr) or attr in (ts.get("style") or ""):
                    _set_style_prop(ts, attr, val)
        log.append("set_attr %s @%s=%s (text)" % (ref, attr, val))
        return
    target = sh if (el.tag == q("g") and sh is not None) else el
    _set_style_prop(target, attr, val)
    # When recoloring an edge stroke, keep its arrowhead/marker color in sync (both mh-* and external <marker> defs)!
    if attr.lower() == "stroke":
        import copy as _copy
        st_cur = target.get("style", "")
        for mk_prop in ("marker-end", "marker-start"):
            raw_mk = (target.get(mk_prop) or "") + " " + (
                re.search(r"%s\s*:\s*([^;]+)" % mk_prop, st_cur).group(1)
                if re.search(r"%s\s*:\s*([^;]+)" % mk_prop, st_cur) else ""
            )
            mk_m = re.search(r"url\(#(mh-(arrow|tbar|open)(?:-[A-Za-z0-9]+)?)\)", raw_mk)
            if mk_m:
                mids = _ensure_marker_defs(root, color=val)
                _set_style_prop(target, mk_prop, "url(#%s)" % mids[mk_m.group(2)])
            else:
                ext_m = re.search(r"url\(#([^)\s]+)\)", raw_mk)
                if ext_m:
                    orig_mid = ext_m.group(1)
                    orig_mel = find_by_id(root, orig_mid)
                    if orig_mel is not None and orig_mel.tag == q("marker"):
                        suf = re.sub(r"[^A-Za-z0-9]", "", val)[:8] or "col"
                        new_mid = "%s-%s" % (re.sub(r"-[0-9A-Fa-f]{6}$", "", orig_mid), suf)
                        if find_by_id(root, new_mid) is None:
                            cloned = _copy.deepcopy(orig_mel)
                            cloned.set("id", new_mid)
                            for mch in cloned.iter():
                                if mch.tag in (q("path"), q("polygon"), q("line"), q("polyline"), q("circle"), q("rect")):
                                    mst = mch.get("style", "")
                                    hf = (mch.get("fill") not in (None, "", "none")) or bool(re.search(r"(?:^|;)\s*fill\s*:\s*(?!none\b)", mst, re.I))
                                    hs = (mch.get("stroke") not in (None, "", "none")) or bool(re.search(r"(?:^|;)\s*stroke\s*:\s*(?!none\b)", mst, re.I))
                                    if hf or (not hf and not hs and mch.tag in (q("path"), q("polygon"))):
                                        _set_style_prop(mch, "fill", val)
                                    if hs:
                                        _set_style_prop(mch, "stroke", val)
                            defs = root.find(q("defs"))
                            if defs is None:
                                defs = ET.SubElement(root, q("defs"))
                            defs.append(cloned)
                        _set_style_prop(target, mk_prop, "url(#%s)" % new_mid)
        gid_s = str(o.get("gid") or ref or "")
        base = gid_s[:-5] if gid_s.endswith("-line") else gid_s
        if base:
            for suf in ("-head", "-head-b", "-head2", "-head2-b"):
                hel = find_by_id(root, base + suf)
                if hel is not None:
                    for hsh in hel.iter():
                        if hsh.tag in (q("polygon"), q("path"), q("line")):
                            hst = hsh.get("style", "")
                            has_fill = ((hsh.get("fill") not in (None, "", "none")) or
                                        bool(re.search(r"(?:^|;)\s*fill\s*:\s*(?!none\b)", hst, re.I)))
                            has_stroke = ((hsh.get("stroke") not in (None, "", "none")) or
                                          bool(re.search(r"(?:^|;)\s*stroke\s*:\s*(?!none\b)", hst, re.I)))
                            if has_fill:
                                _set_style_prop(hsh, "fill", val)
                            if has_stroke:
                                _set_style_prop(hsh, "stroke", val)
    # Auto-contrast node text when changing node box fill to dark/light color (unless auto_contrast=False)
    if attr.lower() == "fill" and o.get("auto_contrast", True) and val.startswith("#"):
        want_tc = _svg_contrast_color(val)
        pmap_c = build_parent_map(root)
        txt_cands = []
        if el.tag == q("g"):
            for te in el.findall(".//%s" % q("text")):
                txt_cands.append(te)
        elif o.get("by_text"):
            t_hit = _find_by_text(root, o["by_text"], want_shape=False)
            if t_hit is not None and t_hit.tag == q("text"):
                txt_cands.append(t_hit)
        for te in txt_cands:
            cur_f = (te.get("fill") or "").strip()
            if not cur_f:
                m_cf = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", te.get("style", ""), re.I)
                cur_f = m_cf.group(1).strip() if m_cf else "#000000"
            if want_tc == "#FFFFFF" and _svg_contrast_color(cur_f) == "#FFFFFF":
                _set_style_prop(te, "fill", "#FFFFFF")
                for ts in te.findall(".//%s" % q("tspan")):
                    if ts.get("fill") or "fill" in (ts.get("style") or ""):
                        _set_style_prop(ts, "fill", "#FFFFFF")
            elif want_tc == "#10243B" and cur_f.lower() in ("#fff", "#ffffff", "white"):
                _set_style_prop(te, "fill", "#10243B")
                for ts in te.findall(".//%s" % q("tspan")):
                    if ts.get("fill") or "fill" in (ts.get("style") or ""):
                        _set_style_prop(ts, "fill", "#10243B")
    log.append("set_attr %s @%s=%s" % (ref, attr, val))


def op_move(root, o, log, errs):
    el = _resolve_el(root, o)
    ref = o.get("gid") or o.get("by_text")
    if el is None:
        errs.append("move: target %s not found" % ref)
        return
    dx, dy = float(o.get("dx", 0)), float(o.get("dy", 0))
    targets = [el]
    pmap = build_parent_map(root)
    # If moving an ungrouped <text> inside a multi-node layer <g>, move its tightly enclosing sibling shape together!
    if el.tag == q("text") and o.get("by_text"):
        sh_sib = _find_by_text(root, o["by_text"], want_shape=True)
        if sh_sib is not None and sh_sib is not el and pmap.get(sh_sib) is pmap.get(el):
            wxy = _text_world_xy(el, pmap)
            sb = _shape_bbox(sh_sib, pmap=pmap)
            if wxy and sb and _point_to_box_dist(wxy, sb) <= 12.0 and (sb[2] - sb[0]) < 260 and (sb[3] - sb[1]) < 140:
                targets.append(sh_sib)
    # Capture pre-move world bbox + moved element set so connected edges can stay elastically anchored
    old_boxes = []
    moved_set = set()
    for t_el in targets:
        for d_el in t_el.iter():
            moved_set.add(d_el)
        b0 = _shape_bbox(t_el, pmap=pmap)
        if b0:
            old_boxes.append(b0)
    old_bb = (
        min(b[0] for b in old_boxes), min(b[1] for b in old_boxes),
        max(b[2] for b in old_boxes), max(b[3] for b in old_boxes),
    ) if old_boxes else None

    tr = "translate(%.3f,%.3f)" % (dx, dy)
    for t_el in targets:
        prev = t_el.get("transform", "").strip()
        t_el.set("transform", (tr + " " + prev).strip() if prev else tr)
        bb = _shape_bbox(t_el, pmap=pmap)
        if bb:
            _expand_viewbox_if_needed(root, bb[0], bb[1], bb[2], bb[3], pad=8.0)

    # Elastic re-anchoring of external incident edges touching old_bb (opt-out via detach_edges=True)
    reanchored = 0
    if old_bb and not o.get("detach_edges"):
        for ed in _list_svg_edges(root):
            e_el = ed["el"]
            if e_el in moved_set:
                continue
            p0, p1 = ed["p0"], ed["p1"]
            d0 = _point_to_box_dist(p0, old_bb)
            d1 = _point_to_box_dist(p1, old_bb)
            if d0 <= 14.0 and d1 > 14.0:
                mat = _accum_affine(e_el, pmap)
                ldx, ldy = _world_delta_to_local(dx, dy, mat)
                if _shift_connector_endpoint(e_el, 0, ldx, ldy):
                    reanchored += 1
            elif d1 <= 14.0 and d0 > 14.0:
                mat = _accum_affine(e_el, pmap)
                ldx, ldy = _world_delta_to_local(dx, dy, mat)
                if _shift_connector_endpoint(e_el, 1, ldx, ldy):
                    reanchored += 1
                    # Also shift any detached polygon arrowhead sitting at old tip p1
                    for cand_h in root.iter():
                        if cand_h in moved_set or cand_h is e_el:
                            continue
                        if cand_h.tag not in (q("polygon"), q("path")):
                            continue
                        hb = _shape_bbox(cand_h, pmap=pmap)
                        if hb and (hb[2] - hb[0]) <= 18.0 and (hb[3] - hb[1]) <= 18.0:
                            hcx, hcy = (hb[0] + hb[2]) / 2.0, (hb[1] + hb[3]) / 2.0
                            if math.hypot(hcx - p1[0], hcy - p1[1]) <= 12.0:
                                hprev = cand_h.get("transform", "").strip()
                                cand_h.set("transform", (tr + " " + hprev).strip() if hprev else tr)
    suf = (" (reanchored %d edge(s))" % reanchored) if reanchored else ""
    log.append("move %s by (%.1f, %.1f)%s" % (ref, dx, dy, suf))


_CSS_PROPS = frozenset({
    "fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray",
    "stroke-opacity", "opacity", "marker-end", "marker-start", "font-size",
    "font-family", "font-weight", "visibility", "display",
})


def _set_style_prop(el, prop, val):
    """Update or remove a CSS property in inline style='...' (overrides <style> classes) AND XML attr."""
    style = el.get("style", "")
    need_style = bool(style) or bool(el.get("class")) or (prop.lower() in _CSS_PROPS)
    if need_style:
        parts = [p.strip() for p in style.split(";") if p.strip()]
        kept = [p for p in parts if not p.split(":", 1)[0].strip().lower() == prop.lower()]
        if val:
            kept.append("%s:%s" % (prop, val))
        if kept:
            el.set("style", ";".join(kept))
        elif "style" in el.attrib:
            del el.attrib["style"]
    if val:
        el.set(prop, val)
    elif prop in el.attrib:
        del el.attrib[prop]


def _parse_path_segments(dd):
    """Parse M/L/H/V/C/Q (abs & rel) SVG paths into [(kind, p_start, ctrl_pts, p_end), ...]."""
    toks = re.findall(r'[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', dd)
    segs = []
    i, cmd = 0, None
    cx, cy = 0.0, 0.0
    while i < len(toks):
        tk = toks[i]
        if len(tk) == 1 and tk.isalpha():
            cmd = tk
            i += 1
            if cmd in ("Z", "z"):
                break
            continue
        if cmd == "M":
            cx, cy = float(toks[i]), float(toks[i + 1]); i += 2; cmd = "L"
        elif cmd == "m":
            cx += float(toks[i]); cy += float(toks[i + 1]); i += 2; cmd = "l"
        elif cmd == "L":
            nx, ny = float(toks[i]), float(toks[i + 1]); i += 2
            segs.append(("L", (cx, cy), [], (nx, ny))); cx, cy = nx, ny
        elif cmd == "l":
            nx, ny = cx + float(toks[i]), cy + float(toks[i + 1]); i += 2
            segs.append(("L", (cx, cy), [], (nx, ny))); cx, cy = nx, ny
        elif cmd == "H":
            nx = float(toks[i]); i += 1
            segs.append(("L", (cx, cy), [], (nx, cy))); cx = nx
        elif cmd == "h":
            nx = cx + float(toks[i]); i += 1
            segs.append(("L", (cx, cy), [], (nx, cy))); cx = nx
        elif cmd == "V":
            ny = float(toks[i]); i += 1
            segs.append(("L", (cx, cy), [], (cx, ny))); cy = ny
        elif cmd == "v":
            ny = cy + float(toks[i]); i += 1
            segs.append(("L", (cx, cy), [], (cx, ny))); cy = ny
        elif cmd == "C":
            c1 = (float(toks[i]), float(toks[i + 1]))
            c2 = (float(toks[i + 2]), float(toks[i + 3]))
            p2 = (float(toks[i + 4]), float(toks[i + 5])); i += 6
            segs.append(("C", (cx, cy), [c1, c2], p2)); cx, cy = p2
        elif cmd == "c":
            c1 = (cx + float(toks[i]), cy + float(toks[i + 1]))
            c2 = (cx + float(toks[i + 2]), cy + float(toks[i + 3]))
            p2 = (cx + float(toks[i + 4]), cy + float(toks[i + 5])); i += 6
            segs.append(("C", (cx, cy), [c1, c2], p2)); cx, cy = p2
        elif cmd == "Q":
            c1 = (float(toks[i]), float(toks[i + 1]))
            p2 = (float(toks[i + 2]), float(toks[i + 3])); i += 4
            segs.append(("Q", (cx, cy), [c1], p2)); cx, cy = p2
        elif cmd == "q":
            c1 = (cx + float(toks[i]), cy + float(toks[i + 1]))
            p2 = (cx + float(toks[i + 2]), cy + float(toks[i + 3])); i += 4
            segs.append(("Q", (cx, cy), [c1], p2)); cx, cy = p2
        else:
            return None  # unsupported arc/smooth command — do not corrupt
    return segs if segs else None


def _parse_path_coords(dd):
    """Return anchor points of M/L/H/V/C/Q path (first & last are exact endpoints)."""
    segs = _parse_path_segments(dd)
    if not segs:
        return None
    pts = [segs[0][1]]
    for _, _, _, p_end in segs:
        pts.append(p_end)
    return pts if len(pts) >= 2 else None


def reverse_path_d(dd):
    """Reverse polyline AND cubic/quadratic Bezier paths accurately."""
    try:
        segs = _parse_path_segments(dd)
        if segs:
            rev = list(reversed(segs))
            out = ["M %.3f %.3f" % rev[0][3]]
            for kind, p0, ctrls, p1 in rev:
                if kind == "L":
                    out.append("L %.3f %.3f" % p0)
                elif kind == "C":
                    out.append("C %.3f %.3f %.3f %.3f %.3f %.3f" % (
                        ctrls[1][0], ctrls[1][1], ctrls[0][0], ctrls[0][1], p0[0], p0[1]))
                elif kind == "Q":
                    out.append("Q %.3f %.3f %.3f %.3f" % (ctrls[0][0], ctrls[0][1], p0[0], p0[1]))
            return " ".join(out)
    except Exception:
        pass
    return dd


def _ensure_marker_defs(root, color="#2C3A47"):
    defs = root.find(q("defs"))
    if defs is None:
        defs = ET.SubElement(root, q("defs"))
    have = {d.get("id") for d in defs.findall(q("marker"))}
    col = str(color or "#2C3A47").strip()
    suf = "" if col.upper() == "#2C3A47" else ("-" + re.sub(r"[^A-Za-z0-9]", "", col)[:8])
    ids = {"arrow": "mh-arrow" + suf, "open": "mh-open" + suf, "tbar": "mh-tbar" + suf}
    if ids["arrow"] not in have:
        m = ET.SubElement(defs, q("marker"))
        m.set("id", ids["arrow"]); m.set("markerWidth", "8"); m.set("markerHeight", "6")
        m.set("refX", "7"); m.set("refY", "3"); m.set("orient", "auto")
        pth = ET.SubElement(m, q("path")); pth.set("d", "M0,0 L8,3 L0,6 z")
        pth.set("fill", col)
    if ids["open"] not in have:
        m = ET.SubElement(defs, q("marker"))
        m.set("id", ids["open"]); m.set("markerWidth", "8"); m.set("markerHeight", "6")
        m.set("refX", "7"); m.set("refY", "3"); m.set("orient", "auto")
        pth = ET.SubElement(m, q("path")); pth.set("d", "M1,1 L7,3 L1,5")
        pth.set("fill", "none"); pth.set("stroke", col); pth.set("stroke-width", "1.4")
    if ids["tbar"] not in have:
        m = ET.SubElement(defs, q("marker"))
        m.set("id", ids["tbar"]); m.set("markerWidth", "4"); m.set("markerHeight", "10")
        m.set("refX", "2"); m.set("refY", "5"); m.set("orient", "auto")
        ln = ET.SubElement(m, q("line"))
        ln.set("x1", "2"); ln.set("y1", "0.5"); ln.set("x2", "2"); ln.set("y2", "9.5")
        ln.set("stroke", col); ln.set("stroke-width", "2.2")
    return ids


def _remove_id(root, gid):
    pmap = build_parent_map(root)
    el = find_by_id(root, gid)
    if el is not None and el in pmap:
        pmap[el].remove(el)
        return True
    return False


def _resolve_edge(root, o):
    """Resolve an edge element by gid, edge_idx, from_text+to_text, or by_text (works on unnamed SVGs)."""
    gid = o.get("gid")
    if gid:
        el = find_by_id(root, gid)
        if el is None:
            el = find_by_id(root, gid + "-line")
        if el is not None:
            return el, gid
    if o.get("edge_idx") is not None:
        edges = _list_svg_edges(root)
        idx = int(o["edge_idx"])
        if 0 <= idx < len(edges):
            return edges[idx]["el"], (edges[idx]["id"] or ("edge_idx=%d" % idx))
    if o.get("from_text") and o.get("to_text"):
        fq = str(o["from_text"]).strip().lower()
        tq = str(o["to_text"]).strip().lower()
        pmap = build_parent_map(root)
        edges = _annotate_edges_with_labels(root, _list_svg_edges(root), pmap)
        # 1) Exact or substring semantic match on inferred (from_label, to_label)
        for exact in (True, False):
            for ed in edges:
                fl = (ed.get("from_label") or "").strip().lower()
                tl = (ed.get("to_label") or "").strip().lower()
                if not fl or not tl:
                    continue
                ok = (fl == fq and tl == tq) if exact else ((fq in fl or fl in fq) and (tq in tl or tl in tq))
                if ok:
                    return ed["el"], (ed["id"] or ed["group_id"] or ("%s->%s" % (o["from_text"], o["to_text"])))
        # 2) Fallback: geometric distance to world boxes of from_text and to_text
        b1, b2 = _box_for_text(root, o["from_text"]), _box_for_text(root, o["to_text"])
        if b1 and b2 and edges:
            best = min(edges, key=lambda e: _point_to_box_dist(e["p0"], b1) + _point_to_box_dist(e["p1"], b2))
            if _point_to_box_dist(best["p0"], b1) + _point_to_box_dist(best["p1"], b2) <= 95.0:
                return best["el"], (best["id"] or best["group_id"] or ("%s->%s" % (o["from_text"], o["to_text"])))
    if o.get("by_text"):
        qstr = str(o["by_text"]).strip()
        hit_t = None
        for t in root.iter(q("text")):
            full = "".join(t.itertext()).strip()
            if full == qstr or qstr in full:
                hit_t = t
                if full == qstr:
                    break
        if hit_t is not None:
            pmap = build_parent_map(root)
            par = pmap.get(hit_t)
            if par is not None and par is not root and par.tag == q("g"):
                sh = first_shape(par)
                if sh is not None and sh.tag in (q("path"), q("line"), q("polyline")):
                    return par, (par.get("id") or ("by_text:%s" % qstr))
            try:
                tx = float(hit_t.get("x", "0").split()[0])
                ty = float(hit_t.get("y", "0").split()[0])
                edges = _list_svg_edges(root)
                if edges:
                    best = min(edges, key=lambda e: math.hypot(e["mid"][0] - tx, e["mid"][1] - ty))
                    return best["el"], (best["id"] or ("edge_idx=%d" % best["edge_idx"]))
            except Exception:
                pass
    return None, (gid or o.get("edge_idx") or o.get("by_text"))


def _remove_tip_arrowheads(root, target_el, tip_xy):
    """Remove orphaned unnamed small triangle/polygon arrowheads sitting at an edge tip (draw.io/BioRender/PPTX SVGs)."""
    if tip_xy is None:
        return 0
    pmap = build_parent_map(root)
    defs_set = set()
    for d in root.iter(q("defs")):
        for ch in d.iter():
            defs_set.add(ch)
    to_remove = []
    for el in root.iter():
        if el is target_el or el in defs_set:
            continue
        tag = el.tag.split("}")[-1]
        pts = None
        if tag == "polygon":
            nums = [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', el.get("points", ""))]
            if len(nums) >= 6:
                pts = list(zip(nums[0::2], nums[1::2]))
        elif tag == "path":
            dd = (el.get("d") or "").strip()
            if dd and dd[-1] in ("Z", "z"):
                nums = [float(x) for x in re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', dd)]
                if 6 <= len(nums) <= 16:
                    pts = list(zip(nums[0::2], nums[1::2]))
        if not pts:
            continue
        mat = _accum_affine(el, pmap)
        wpts = [_apply_affine(x, y, mat) for x, y in pts]
        xs = [p[0] for p in wpts]; ys = [p[1] for p in wpts]
        bw, bh = max(xs) - min(xs), max(ys) - min(ys)
        if bw <= 18.0 and bh <= 18.0 and max(bw, bh) >= 2.0:
            cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
            if math.hypot(cx - tip_xy[0], cy - tip_xy[1]) <= 12.0:
                to_remove.append(el)
    removed = 0
    for el in to_remove:
        par = pmap.get(el)
        if par is not None:
            try:
                par.remove(el)
                removed += 1
            except ValueError:
                pass
    return removed


def op_swap_edge(root, o, log, errs):
    el, ref = _resolve_edge(root, o)
    if el is None:
        errs.append("swap_edge: target %s not found" % ref)
        return
    gid = str(o.get("gid") or ref)
    base = gid[:-5] if gid.endswith("-line") else gid
    # Scope reversal to the -line subgroup when operating on a composite edge-<id> group
    line_scope = find_by_id(el, base + "-line") if el.tag == q("g") else None
    rev_target = line_scope if line_scope is not None else el
    target_pre = first_shape(rev_target) if rev_target.tag == q("g") else rev_target
    old_tip = None
    if target_pre is not None:
        pmap_pre = build_parent_map(root)
        ep_pre = _element_endpoints(target_pre)
        if ep_pre:
            old_tip = _apply_affine(ep_pre[-1][0], ep_pre[-1][1], _accum_affine(target_pre, pmap_pre))
    for ln in rev_target.iter(q("line")):
        x1, y1, x2, y2 = ln.get("x1"), ln.get("y1"), ln.get("x2"), ln.get("y2")
        ln.set("x1", x2); ln.set("y1", y2); ln.set("x2", x1); ln.set("y2", y1)
    for pl in rev_target.iter(q("polyline")):
        pts_raw = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', pl.get("points", ""))
        if len(pts_raw) >= 4:
            pairs = list(zip(pts_raw[0::2], pts_raw[1::2]))
            pairs.reverse()
            pl.set("points", " ".join("%s,%s" % p for p in pairs))
    for p in rev_target.iter(q("path")):
        dd = p.get("d")
        if dd:
            p.set("d", reverse_path_d(dd))
    # If split -head exists (matplotlib SVG) or unnamed polygon arrowhead sat at old_tip, clean up & attach marker-end
    head_el = find_by_id(root, base + "-head")
    removed_poly = _remove_tip_arrowheads(root, target_pre, old_tip) if head_el is None else 0
    if head_el is not None or removed_poly > 0:
        is_tbar = (head_el is not None and head_el.find(".//%s" % q("polygon")) is None and
                   len(head_el.findall(".//%s" % q("path"))) == 1)
        if head_el is not None:
            _remove_id(root, base + "-head")
            _remove_id(root, base + "-head-b")
        target = first_shape(rev_target) if rev_target.tag == q("g") else rev_target
        st_tmp = target.get("style", "") if target is not None else ""
        m_sc = re.search(r"stroke\s*:\s*([^;]+)", st_tmp)
        mcol = (target.get("stroke") if target is not None else None) or (m_sc.group(1).strip() if m_sc else "#2C3A47")
        mids = _ensure_marker_defs(root, color=mcol)
        if target is not None:
            _set_style_prop(target, "marker-end",
                            "url(#%s)" % (mids["tbar"] if is_tbar else mids["arrow"]))
    log.append("swap_edge %s (endpoints reversed, arrowhead follows reversed path)" % ref)


def op_set_marker(root, o, log, errs):
    el, ref = _resolve_edge(root, o)
    if el is None:
        errs.append("set_marker: target %s not found" % ref)
        return
    gid = str(o.get("gid") or ref)
    mk = o.get("marker", "none")
    mapping = {"arrow": "url(#mh-arrow)", "tbar": "url(#mh-tbar)",
               "open": "url(#mh-open)", "none": ""}
    if mk not in mapping:
        errs.append("set_marker: unknown marker %r" % mk)
        return
    # Remove any split matplotlib -head group or unnamed tip polygon arrowhead so old head does not remain
    base = gid[:-5] if gid.endswith("-line") else gid
    _remove_id(root, base + "-head")
    _remove_id(root, base + "-head-b")
    target_pre = first_shape(el) if el.tag == q("g") else el
    if target_pre is not None:
        pmap_pre = build_parent_map(root)
        ep_pre = _element_endpoints(target_pre)
        if ep_pre:
            tip_pre = _apply_affine(ep_pre[-1][0], ep_pre[-1][1], _accum_affine(target_pre, pmap_pre))
            _remove_tip_arrowheads(root, target_pre, tip_pre)
    if mk != "none":
        target_tmp = first_shape(el) if el.tag == q("g") else el
        st_tmp = (target_tmp.get("style", "") if target_tmp is not None else "")
        m_sc = re.search(r"stroke\s*:\s*([^;]+)", st_tmp)
        mcol = o.get("color") or (target_tmp.get("stroke") if target_tmp is not None else None) or (
            m_sc.group(1).strip() if m_sc else "#2C3A47")
        mids = _ensure_marker_defs(root, color=mcol)
        mapping = {"arrow": "url(#%s)" % mids["arrow"], "tbar": "url(#%s)" % mids["tbar"],
                   "open": "url(#%s)" % mids["open"], "none": ""}
    target = first_shape(el) if el.tag == q("g") else el
    if target is None:
        target = el
    if o.get("color"):
        _set_style_prop(target, "stroke", str(o["color"]))
    if mapping[mk]:
        _set_style_prop(target, "marker-end", mapping[mk])
        if el.tag == q("g"):
            _set_style_prop(el, "marker-end", "")
    else:
        for obj in (el, target):
            _set_style_prop(obj, "marker-end", "")
    log.append("set_marker %s -> %s" % (ref, mk))


def op_set_dash(root, o, log, errs):
    el, ref = _resolve_edge(root, o)
    if el is None:
        errs.append("set_dash: target %s not found" % ref)
        return
    preset = {"solid": "", "none": "", "dashed": "5,3", "dotted": "2,2"}
    raw = str(o.get("dash", "dashed"))
    val = preset.get(raw.lower(), raw)
    target = first_shape(el) if el.tag == q("g") else el
    if target is None:
        target = el
    _set_style_prop(target, "stroke-dasharray", val)
    log.append("set_dash %s -> %s" % (ref, raw))


def op_delete(root, o, log, errs):
    if o.get("gid"):
        if _remove_id(root, o["gid"]):
            base = str(o["gid"])[:-5] if str(o["gid"]).endswith("-line") else str(o["gid"])
            _remove_id(root, base + "-head")
            _remove_id(root, base + "-head-b")
            log.append("delete %s" % o["gid"])
            return
    if o.get("edge_idx") is not None or (o.get("from_text") and o.get("to_text")):
        el, ref = _resolve_edge(root, o)
        if el is not None:
            pmap = build_parent_map(root)
            target_pre = first_shape(el) if el.tag == q("g") else el
            if target_pre is not None:
                ep_pre = _element_endpoints(target_pre)
                if ep_pre:
                    tip_pre = _apply_affine(ep_pre[-1][0], ep_pre[-1][1], _accum_affine(target_pre, pmap))
                    _remove_tip_arrowheads(root, target_pre, tip_pre)
            base = str(ref)[:-5] if str(ref).endswith("-line") else str(ref)
            _remove_id(root, base + "-head")
            _remove_id(root, base + "-head-b")
            par = pmap.get(el)
            if par is not None:
                par.remove(el)
                log.append("delete edge %s" % ref)
                return
    if o.get("by_text"):
        el = _find_by_text(root, o["by_text"])
        if el is not None:
            pmap = build_parent_map(root)
            par = pmap.get(el)
            if par is not None:
                # If deleting an ungrouped <text> inside a layer <g>, also remove its tightly enclosing sibling node shape!
                if el.tag == q("text"):
                    sh_sib = _find_by_text(root, o["by_text"], want_shape=True)
                    if sh_sib is not None and sh_sib is not el and pmap.get(sh_sib) is par:
                        wxy = _text_world_xy(el, pmap)
                        sb = _shape_bbox(sh_sib, pmap=pmap)
                        if wxy and sb and _point_to_box_dist(wxy, sb) <= 12.0 and (sb[2] - sb[0]) < 260 and (sb[3] - sb[1]) < 140:
                            try:
                                par.remove(sh_sib)
                            except ValueError:
                                pass
                par.remove(el)
                log.append("delete by_text=%r" % o["by_text"])
                return
    errs.append("delete: target %s not found" % (o.get("gid") or o.get("by_text") or o.get("edge_idx") or o.get("from_text")))


def _svg_contrast_color(bg_hex):
    s = str(bg_hex or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return "#10243B"
    try:
        r, g, b = int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0
        return "#FFFFFF" if (0.2126 * r + 0.7152 * g + 0.0722 * b) < 0.45 else "#10243B"
    except ValueError:
        return "#10243B"


def _resolve_box_ref(root, ref_s):
    if not ref_s:
        return None
    el = find_by_id(root, str(ref_s))
    if el is not None:
        pmap = build_parent_map(root)
        bb = _shape_bbox(el, pmap=pmap)
        if bb:
            return bb
    return _box_for_text(root, str(ref_s))


def op_add_node(root, o, log, errs):
    w = float(o.get("w", 96))
    h = float(o.get("h", 40 if o.get("sublabel") else 34))
    gap = float(o.get("gap", 46.0))
    # Smart relative placement (right_of / left_of / below / above) removes coordinate guesswork!
    x, y = None, None
    for rel_k in ("right_of", "left_of", "below", "above"):
        if o.get(rel_k):
            rb = _resolve_box_ref(root, o[rel_k])
            if rb:
                rcx, rcy = (rb[0] + rb[2]) / 2.0, (rb[1] + rb[3]) / 2.0
                if rel_k == "right_of":
                    x, y = rb[2] + gap, rcy - h / 2.0
                elif rel_k == "left_of":
                    x, y = rb[0] - gap - w, rcy - h / 2.0
                elif rel_k == "below":
                    x, y = rcx - w / 2.0, rb[3] + gap
                elif rel_k == "above":
                    x, y = rcx - w / 2.0, rb[1] - gap - h
                break
    if x is None:
        x, y = float(o.get("x", 40)), float(o.get("y", 40))
    _expand_viewbox_if_needed(root, x, y, x + w, y + h, pad=8.0)
    fill = o.get("fill", "#EAF2FB")
    stroke = o.get("stroke", "#2E5E8C")
    shape = str(o.get("shape", "round")).lower()
    g = ET.SubElement(root, q("g"))
    g.set("id", o.get("id", "node-new"))
    if shape == "ellipse":
        el = ET.SubElement(g, q("ellipse"))
        el.set("cx", "%.2f" % (x + w / 2.0)); el.set("cy", "%.2f" % (y + h / 2.0))
        el.set("rx", "%.2f" % (w / 2.0)); el.set("ry", "%.2f" % (h / 2.0))
    elif shape == "hexagon":
        dx_h = min(w * 0.16, h * 0.45)
        pts_h = [(x + dx_h, y), (x + w - dx_h, y), (x + w, y + h / 2.0),
                 (x + w - dx_h, y + h), (x + dx_h, y + h), (x, y + h / 2.0)]
        el = ET.SubElement(g, q("polygon"))
        el.set("points", " ".join("%.2f,%.2f" % p for p in pts_h))
    elif shape == "diamond":
        pts_d = [(x + w / 2.0, y), (x + w, y + h / 2.0), (x + w / 2.0, y + h), (x, y + h / 2.0)]
        el = ET.SubElement(g, q("polygon"))
        el.set("points", " ".join("%.2f,%.2f" % p for p in pts_d))
    else:
        el = ET.SubElement(g, q("rect"))
        el.set("x", "%.2f" % x); el.set("y", "%.2f" % y)
        el.set("width", "%.2f" % w); el.set("height", "%.2f" % h)
        el.set("rx", "%.2f" % (h / 2.0 if shape == "stadium" else (0.0 if shape == "rect" else float(o.get("rx", 6)))))
    el.set("fill", fill); el.set("stroke", stroke); el.set("stroke-width", "1.3")
    if shape == "complex":
        el2 = ET.SubElement(g, q("rect"))
        el2.set("x", "%.2f" % (x + 2.5)); el2.set("y", "%.2f" % (y + 2.5))
        el2.set("width", "%.2f" % max(w - 5.0, 2.0)); el2.set("height", "%.2f" % max(h - 5.0, 2.0))
        el2.set("rx", "4"); el2.set("fill", "none"); el2.set("stroke", stroke); el2.set("stroke-width", "0.9")
    tcol = o.get("text_color") or _svg_contrast_color(fill)
    fs = float(o.get("fs", 12))
    sub = o.get("sublabel")
    t = ET.SubElement(g, q("text"))
    t.set("x", "%.2f" % (x + w / 2.0))
    t.set("y", "%.2f" % (y + h * (0.42 if sub else 0.50) + fs * 0.34))
    t.set("text-anchor", "middle"); t.set("font-family", "sans-serif")
    t.set("font-size", str(fs)); t.set("font-weight", "bold")
    t.set("fill", tcol)
    t.text = str(o.get("label", "new"))
    if sub:
        ts = ET.SubElement(g, q("text"))
        ts.set("x", "%.2f" % (x + w / 2.0))
        ts.set("y", "%.2f" % (y + h * 0.76 + fs * 0.22))
        ts.set("text-anchor", "middle"); ts.set("font-family", "sans-serif")
        ts.set("font-size", "%.1f" % (fs * 0.78))
        ts.set("fill", "#E6EEF8" if tcol == "#FFFFFF" else "#4A5B6D")
        ts.text = str(sub)
    log.append("add_node %s at (%.1f,%.1f)" % (g.get("id"), x, y))


def _box_for_text(root, query):
    """Locate world bounding box of the node shape corresponding to text label `query`."""
    pmap = build_parent_map(root)
    sh = _find_by_text(root, query, want_shape=True)
    if sh is None:
        return None
    bb = _shape_bbox(sh, pmap=pmap)
    if bb:
        return bb
    if sh.tag == q("g"):
        s2 = first_shape(sh)
        if s2 is not None:
            bb = _shape_bbox(s2, pmap=pmap)
            if bb:
                return bb
    return None


def _connect_boxes(b1, b2):
    """Compute clean border-to-border anchor points between two SVG bounding boxes."""
    c1 = ((b1[0] + b1[2]) / 2.0, (b1[1] + b1[3]) / 2.0)
    c2 = ((b2[0] + b2[2]) / 2.0, (b2[1] + b2[3]) / 2.0)
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    if abs(dx) >= abs(dy):
        if dx >= 0:
            return (b1[2], c1[1]), (b2[0], c2[1])
        return (b1[0], c1[1]), (b2[2], c2[1])
    if dy >= 0:
        return (c1[0], b1[3]), (c2[0], b2[1])
    return (c1[0], b1[1]), (c2[0], b2[3])


def op_add_edge(root, o, log, errs):
    raw_pts = o.get("points")
    if raw_pts and len(raw_pts) >= 2:
        pts = [(float(p[0]), float(p[1])) for p in raw_pts]
    elif (o.get("from_text") or o.get("from_gid")) and (o.get("to_text") or o.get("to_gid")):
        b1 = _resolve_box_ref(root, o.get("from_gid") or o.get("from_text"))
        b2 = _resolve_box_ref(root, o.get("to_gid") or o.get("to_text"))
        if not b1 or not b2:
            errs.append("add_edge: could not resolve from=%r / to=%r" % (
                o.get("from_gid") or o.get("from_text"), o.get("to_gid") or o.get("to_text")))
            return
        p1, p2 = _connect_boxes(b1, b2)
        if o.get("elbow"):
            mx = (p1[0] + p2[0]) / 2.0
            pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
        else:
            # Obstacle-aware detour if direct line slices through an intermediate node box!
            pmap_o = build_parent_map(root)
            blockers = []
            for anc_o in _collect_node_anchors(root, pmap_o):
                ob = anc_o.get("bbox")
                if not ob:
                    continue
                if (abs(ob[0] - b1[0]) < 2 and abs(ob[1] - b1[1]) < 2) or (abs(ob[0] - b2[0]) < 2 and abs(ob[1] - b2[1]) < 2):
                    continue
                # Liang-Barsky segment vs shrunk box
                x0b, y0b, x1b, y1b = ob[0] + 2.0, ob[1] + 2.0, ob[2] - 2.0, ob[3] - 2.0
                if x1b <= x0b or y1b <= y0b:
                    continue
                ddx, ddy = p2[0] - p1[0], p2[1] - p1[1]
                t0, t1, hit = 0.0, 1.0, True
                for pp, qq in ((-ddx, p1[0] - x0b), (ddx, x1b - p1[0]), (-ddy, p1[1] - y0b), (ddy, y1b - p1[1])):
                    if abs(pp) < 1e-9:
                        if qq < 0:
                            hit = False; break
                    else:
                        rr = qq / pp
                        if pp < 0:
                            if rr > t1: hit = False; break
                            t0 = max(t0, rr)
                        else:
                            if rr < t0: hit = False; break
                            t1 = min(t1, rr)
                if hit and t0 <= t1:
                    blockers.append(ob)
            if blockers:
                c1x, c1y = (b1[0] + b1[2]) / 2.0, (b1[1] + b1[3]) / 2.0
                c2x, c2y = (b2[0] + b2[2]) / 2.0, (b2[1] + b2[3]) / 2.0
                if abs(c2x - c1x) >= abs(c2y - c1y):
                    top_y = min(min(b[1] for b in blockers), b1[1], b2[1]) - 18.0
                    bot_y = max(max(b[3] for b in blockers), b1[3], b2[3]) + 18.0
                    if abs(top_y - (c1y + c2y) / 2.0) <= abs(bot_y - (c1y + c2y) / 2.0):
                        pts = [(c1x, b1[1]), (c1x, top_y), (c2x, top_y), (c2x, b2[1])]
                    else:
                        pts = [(c1x, b1[3]), (c1x, bot_y), (c2x, bot_y), (c2x, b2[3])]
                else:
                    r_x = max(max(b[2] for b in blockers), b1[2], b2[2]) + 18.0
                    pts = [(b1[2], c1y), (r_x, c1y), (r_x, c2y), (b2[2], c2y)]
            else:
                pts = [p1, p2]
    else:
        x1, y1 = float(o.get("x1", 40)), float(o.get("y1", 40))
        x2, y2 = float(o.get("x2", 140)), float(o.get("y2", 40))
        if o.get("elbow"):
            mx = (x1 + x2) / 2.0
            pts = [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
        else:
            pts = [(x1, y1), (x2, y2)]
    xs_p = [p[0] for p in pts]
    ys_p = [p[1] for p in pts]
    _expand_viewbox_if_needed(root, min(xs_p), min(ys_p), max(xs_p), max(ys_p), pad=10.0)
    mk = str(o.get("marker", "arrow"))
    def_col = "#C0392B" if mk == "tbar" else ("#0072B2" if mk == "open" else "#1E3A5F")
    col = str(o.get("color", def_col))
    if mk != "none":
        mids = _ensure_marker_defs(root, color=col)
        mapping = {"arrow": "url(#%s)" % mids["arrow"], "tbar": "url(#%s)" % mids["tbar"],
                   "open": "url(#%s)" % mids["open"], "none": ""}
    else:
        mapping = {"none": ""}
    g = ET.SubElement(root, q("g"))
    g.set("id", o.get("id", "edge-new"))
    pth = ET.SubElement(g, q("path"))
    d_cmd = "M %.2f %.2f " % pts[0] + " ".join("L %.2f %.2f" % p for p in pts[1:])
    pth.set("d", d_cmd)
    pth.set("fill", "none")
    pth.set("stroke", col)
    pth.set("stroke-width", str(o.get("lw", 1.8)))
    dash = str(o.get("dash", "solid")).lower()
    if dash == "dashed":
        pth.set("stroke-dasharray", "5,3")
    elif dash == "dotted":
        pth.set("stroke-dasharray", "2,2")
    elif dash not in ("solid", "none", ""):
        pth.set("stroke-dasharray", dash)
    if mapping.get(mk):
        pth.set("marker-end", mapping[mk])
    if o.get("label"):
        # Place label on longest segment
        best_i = max(range(len(pts) - 1),
                     key=lambda i: math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
        pa, pb = pts[best_i], pts[best_i + 1]
        is_vert = abs(pb[1] - pa[1]) > abs(pb[0] - pa[0])
        fs_l = float(o.get("fs", 10))
        lab_s = str(o["label"])
        est_w = len(lab_s) * fs_l * 0.62
        if is_vert:
            lx_t = (pa[0] + pb[0]) / 2.0 + 7.0
            ly_t = (pa[1] + pb[1]) / 2.0 + 3.5
            bx0, by0, bw, bh = lx_t - 2.0, ly_t - fs_l * 0.92, est_w + 4.0, fs_l * 1.25
            _expand_viewbox_if_needed(root, bx0, by0, bx0 + bw, by0 + bh, pad=8.0)
        else:
            lx_t = (pa[0] + pb[0]) / 2.0
            span_h = abs(pb[0] - pa[0])
            # Lift label cleanly above tight horizontal spans so it never clips node boxes
            ly_t = (pa[1] + pb[1]) / 2.0 - (24.0 if est_w > span_h * 0.85 else 7.0)
            bx0, by0, bw, bh = lx_t - est_w / 2.0 - 2.5, ly_t - fs_l * 0.92, est_w + 5.0, fs_l * 1.25
            _expand_viewbox_if_needed(root, bx0, by0, bx0 + bw, by0 + bh, pad=8.0)
        # SVG 1.1-safe opaque white pill behind edge label (works in rsvg/cairo/Inkscape/Illustrator)
        pill = ET.SubElement(g, q("rect"))
        pill.set("x", "%.2f" % bx0)
        pill.set("y", "%.2f" % by0)
        pill.set("width", "%.2f" % bw)
        pill.set("height", "%.2f" % bh)
        pill.set("rx", "2.5")
        pill.set("fill", "#FFFFFF")
        pill.set("fill-opacity", "0.92")
        t = ET.SubElement(g, q("text"))
        t.set("x", "%.2f" % lx_t)
        t.set("y", "%.2f" % ly_t)
        t.set("text-anchor", "start" if is_vert else "middle")
        t.set("font-family", "sans-serif")
        t.set("font-size", str(o.get("fs", 10))); t.set("fill", col)
        t.text = lab_s
    log.append("add_edge %s (%s,%s)->(%s,%s) [%s]" % (g.get("id"), pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], mk))


def op_add_legend(root, o, log, errs):
    """Append a clean auto-wrapping vector legend box below current viewBox without disturbing art."""
    items = o.get("items") or []
    if not items:
        errs.append("add_legend: empty items")
        return
    vb = _parse_viewbox(root) or [0.0, 0.0, 420.0, 220.0]
    vx, vy, vw, vh = vb
    fs = float(o.get("fs", 10.0))
    lx = vx + 10.0
    lw_box = max(vw - 20.0, 180.0)
    row_h = fs * 1.65
    # Pre-plan multi-row item layout so legend never overflows horizontally
    rows_plan, cur_row, cur_x = [], [], 0.0
    inner_w = lw_box - 20.0
    for it in items:
        lab = str(it.get("label", it.get("kind", "item")))
        need = 30.0 + max(len(lab) * fs * 0.58, 36.0) + 12.0
        if cur_row and cur_x + need > inner_w:
            rows_plan.append(cur_row)
            cur_row, cur_x = [], 0.0
        cur_row.append((it, need))
        cur_x += need
    if cur_row:
        rows_plan.append(cur_row)
    box_h = max(float(o.get("h", 0.0)), 18.0 + len(rows_plan) * row_h + 6.0)
    ly = vy + vh + 6.0
    _expand_viewbox_if_needed(root, lx, ly, lx + lw_box, ly + box_h, pad=8.0)
    g = ET.SubElement(root, q("g"))
    g.set("id", o.get("id", "legend-added"))
    bg = ET.SubElement(g, q("rect"))
    bg.set("x", "%.2f" % lx); bg.set("y", "%.2f" % ly)
    bg.set("width", "%.2f" % lw_box); bg.set("height", "%.2f" % box_h)
    bg.set("rx", "4"); bg.set("fill", "#FFFFFF"); bg.set("stroke", "#C8D0D8")
    bg.set("stroke-width", "1.0")
    title = str(o.get("title", "Legend"))
    tt = ET.SubElement(g, q("text"))
    tt.set("x", "%.2f" % (lx + 8.0)); tt.set("y", "%.2f" % (ly + 12.0))
    tt.set("font-family", "sans-serif"); tt.set("font-size", "%.1f" % fs)
    tt.set("font-weight", "bold"); tt.set("fill", "#10243B")
    tt.text = title
    sem_col = {"activates": "#1E3A5F", "catalyzes": "#1E3A5F", "flows": "#1E3A5F",
               "inhibits": "#C0392B", "inhibits_dashed": "#C0392B",
               "translocates": "#0072B2", "binds": "#5B4B8A"}
    mk_kind_map = {"activates": "arrow", "catalyzes": "arrow", "flows": "arrow",
                   "inhibits": "tbar", "inhibits_dashed": "tbar", "translocates": "open"}
    for ri, row_items in enumerate(rows_plan):
        xi = lx + 10.0
        yi = ly + 25.0 + ri * row_h
        for it, need in row_items:
            kind = str(it.get("kind", "activates"))
            col = str(it.get("color", sem_col.get(kind, "#2C3A47")))
            lab = str(it.get("label", kind))
            if kind == "swatch":
                sw = ET.SubElement(g, q("rect"))
                sw.set("x", "%.2f" % xi); sw.set("y", "%.2f" % (yi - 6.0))
                sw.set("width", "16"); sw.set("height", "10"); sw.set("rx", "2")
                sw.set("fill", it.get("fill", col)); sw.set("stroke", it.get("stroke", "#2E5E8C"))
                sw.set("stroke-width", "1.0")
            else:
                mk_k = mk_kind_map.get(kind)
                mids = _ensure_marker_defs(root, color=col) if mk_k else {}
                pth = ET.SubElement(g, q("path"))
                pth.set("d", "M %.2f %.2f L %.2f %.2f" % (xi, yi - 1.0, xi + 22.0, yi - 1.0))
                pth.set("fill", "none"); pth.set("stroke", col); pth.set("stroke-width", "1.6")
                if "dashed" in kind or kind == "translocates":
                    pth.set("stroke-dasharray", "4,2")
                if mk_k and mids.get(mk_k):
                    pth.set("marker-end", "url(#%s)" % mids[mk_k])
            lt = ET.SubElement(g, q("text"))
            lt.set("x", "%.2f" % (xi + 28.0)); lt.set("y", "%.2f" % (yi + 2.5))
            lt.set("font-family", "sans-serif"); lt.set("font-size", "%.1f" % fs)
            lt.set("fill", "#10243B")
            lt.text = lab
            xi += need
    log.append("add_legend (%d items)" % len(items))


def op_add_group(root, o, log, errs):
    """Add a rounded dashed compartment box behind existing nodes (supports members_text / members_gid)."""
    pmap = build_parent_map(root)
    bbs = []
    for txt in (o.get("members_text") or []):
        bb = _box_for_text(root, txt)
        if bb:
            bbs.append(bb)
    for mg in (o.get("members_gid") or []):
        el_m = find_by_id(root, mg)
        if el_m is not None:
            sh_m = first_shape(el_m) if el_m.tag == q("g") else el_m
            if sh_m is not None:
                bb = _shape_bbox(sh_m, pmap=pmap)
                if bb:
                    bbs.append(bb)
    if not bbs and all(k in o for k in ("x", "y", "w", "h")):
        x, y, w, h = float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])
        bbs.append((x, y, x + w, y + h))
    if not bbs:
        errs.append("add_group: no member bounding boxes found for %r" % (o.get("label") or o.get("id")))
        return
    pad = float(o.get("pad", 12.0))
    hdr = float(o.get("header_h", 20.0 if o.get("membrane") else 16.0))
    x0 = min(b[0] for b in bbs) - pad
    y0 = min(b[1] for b in bbs) - pad - hdr
    x1 = max(b[2] for b in bbs) + pad
    y1 = max(b[3] for b in bbs) + pad
    _expand_viewbox_if_needed(root, x0, y0, x1, y1, pad=8.0)
    g = ET.Element(q("g"))
    gid = o.get("id", "group-added")
    g.set("id", gid)
    g.set("data-layer", "compartment")
    rect = ET.SubElement(g, q("rect"))
    rect.set("x", "%.2f" % x0); rect.set("y", "%.2f" % y0)
    rect.set("width", "%.2f" % (x1 - x0)); rect.set("height", "%.2f" % (y1 - y0))
    rect.set("rx", "6"); rect.set("ry", "6")
    rect.set("fill", o.get("fill", "#F4F7FA"))
    rect.set("stroke", o.get("stroke", "#7B8D9E"))
    rect.set("stroke-width", "1.2")
    if o.get("dash", True):
        rect.set("stroke-dasharray", "6,3")
    if o.get("membrane"):
        mcol = o.get("membrane_color", "#B9770E")
        for mi, dy_m in enumerate((0.0, 3.0), 1):
            ml = ET.SubElement(g, q("line"))
            ml.set("id", "%s-membrane-%d" % (gid, mi))
            ml.set("x1", "%.2f" % (x0 + 2.0)); ml.set("y1", "%.2f" % (y0 + dy_m))
            ml.set("x2", "%.2f" % (x1 - 2.0)); ml.set("y2", "%.2f" % (y0 + dy_m))
            ml.set("stroke", mcol); ml.set("stroke-width", "1.4")
    lbl = str(o.get("label", ""))
    if lbl:
        lt = ET.SubElement(g, q("text"))
        lt.set("id", "grouplabel-%s" % gid)
        lt.set("x", "%.2f" % (x0 + 8.0))
        lt.set("y", "%.2f" % (y0 + (15.0 if o.get("membrane") else 13.0)))
        lt.set("font-family", "sans-serif"); lt.set("font-size", str(o.get("fs", 10)))
        lt.set("font-weight", "bold"); lt.set("fill", o.get("text_color", "#2C3E50"))
        lt.text = lbl
    # Insert behind existing nodes (right after <defs>/<style>/<metadata> and optional canvas bg rect)
    ins_idx = 0
    for idx_c, ch in enumerate(list(root)):
        tag = ch.tag.split("}")[-1]
        if tag in ("defs", "style", "metadata", "title", "desc"):
            ins_idx = idx_c + 1
        elif tag == "rect" and idx_c <= ins_idx:
            # Skip full-canvas white background rect if present
            if (ch.get("fill") or "").lower() in ("#fff", "#ffffff", "white"):
                ins_idx = idx_c + 1
        else:
            break
    root.insert(ins_idx, g)
    log.append("add_group %s (%r, %d members)" % (gid, lbl, len(bbs)))


def op_add_note(root, o, log, errs):
    x, y, fs = float(o.get("x", 10)), float(o.get("y", 10)), float(o.get("fs", 7))
    txt = str(o.get("text", ""))
    _expand_viewbox_if_needed(root, x, y - fs, x + len(txt) * fs * 0.6, y + 4.0, pad=6.0)
    t = ET.SubElement(root, q("text"))
    t.set("x", str(x)); t.set("y", str(y)); t.set("id", "note-%d" % int(y * 1000))
    t.set("font-family", "sans-serif"); t.set("font-size", str(fs))
    t.set("fill", "#33404F")
    t.text = txt
    log.append("add_note at (%s,%s)" % (x, y))


def _ensure_png_dpi_and_preview(png_path, preview_path, dpi):
    try:
        from PIL import Image
        im = Image.open(png_path)
        cur_dpi = im.info.get("dpi")
        if not cur_dpi or not cur_dpi[0]:
            im.save(png_path, dpi=(dpi, dpi))
        # Generate lightweight ~100 DPI preview (<=108 DPI, max width 1200px)
        pw, ph = im.size
        scale = min(100.0 / max(dpi, 100), 1200.0 / max(pw, 1), 1.0)
        if scale < 0.99:
            im_p = im.resize((max(1, int(pw * scale)), max(1, int(ph * scale))),
                             Image.LANCZOS)
            im_p.save(preview_path, dpi=(100, 100))
        else:
            im.save(preview_path, dpi=(100, 100))
        return preview_path
    except Exception:
        return None


def render(svg_path, out_dir, stem, dpi=300):
    """Fallback render chain; returns dict with produced files + renderer used."""
    res = {"png": None, "pdf": None, "preview": None, "renderer": None, "errors": []}
    png = os.path.join(out_dir, stem + ".png")
    pdf = os.path.join(out_dir, stem + ".pdf")
    preview = os.path.join(out_dir, stem + "_preview.png")
    scale = max(dpi / 96.0, 2.0)

    # 1) cairosvg
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png, scale=scale)
        cairosvg.svg2pdf(url=svg_path, write_to=pdf)
        res.update(png=png, pdf=pdf, renderer="cairosvg")
        res["preview"] = _ensure_png_dpi_and_preview(png, preview, dpi)
        return res
    except Exception as e:
        res["errors"].append("cairosvg: %s" % e)
    # 2) rsvg-convert
    try:
        import subprocess
        subprocess.run(["rsvg-convert", "-z", "%.2f" % scale, "-o", png, svg_path],
                       check=True, capture_output=True, timeout=60)
        subprocess.run(["rsvg-convert", "-f", "pdf", "-o", pdf, svg_path],
                       check=True, capture_output=True, timeout=60)
        res.update(png=png, pdf=pdf, renderer="rsvg-convert")
        res["preview"] = _ensure_png_dpi_and_preview(png, preview, dpi)
        return res
    except Exception as e:
        res["errors"].append("rsvg-convert: %s" % e)
    # 3) inkscape
    try:
        import subprocess
        subprocess.run(["inkscape", svg_path, "--export-type=png",
                        "--export-filename=%s" % png, "--export-dpi=%d" % dpi],
                       check=True, capture_output=True, timeout=120)
        subprocess.run(["inkscape", svg_path, "--export-type=pdf",
                        "--export-filename=%s" % pdf],
                       check=True, capture_output=True, timeout=120)
        res.update(png=png, pdf=pdf, renderer="inkscape")
        res["preview"] = _ensure_png_dpi_and_preview(png, preview, dpi)
        return res
    except Exception as e:
        res["errors"].append("inkscape: %s" % e)
    # 4) LibreOffice -> pdf, pdftoppm -> png (isolated user profile for container safety)
    try:
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(td, "lo_profile")
            subprocess.run(
                ["soffice", "-env:UserInstallation=file://%s" % prof,
                 "--headless", "--convert-to", "pdf", "--outdir", td, svg_path],
                check=True, capture_output=True, timeout=180)
            pdfs = [f for f in os.listdir(td) if f.endswith(".pdf")]
            if pdfs:
                shutil.move(os.path.join(td, pdfs[0]), pdf)
                subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile",
                                pdf, png[:-4]], check=True, capture_output=True, timeout=120)
                res.update(png=png, pdf=pdf, renderer="libreoffice+pdftoppm")
                res["preview"] = _ensure_png_dpi_and_preview(png, preview, dpi)
                return res
    except Exception as e:
        res["errors"].append("libreoffice: %s" % e)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("ops", nargs="?", default=None)
    ap.add_argument("--inspect", action="store_true",
                    help="print SVG viewBox, group ids, markers, and text inventory")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--stem", default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    if a.inspect:
        print(json.dumps(inspect_svg(a.svg), indent=1, ensure_ascii=False))
        sys.exit(0)
    if not a.ops or not a.out_dir:
        raise SystemExit("usage: edit_svg.py input.svg ops.json --out-dir DIR  (or --inspect)")
    os.makedirs(a.out_dir, exist_ok=True)
    stem = a.stem or (os.path.splitext(os.path.basename(a.svg))[0] + "_edited")
    orig_copy = os.path.join(a.out_dir, "original_" + os.path.basename(a.svg))
    if os.path.abspath(orig_copy) != os.path.abspath(a.svg):
        shutil.copy2(a.svg, orig_copy)
    tree = load(a.svg)
    root = tree.getroot()
    groups_before = sum(1 for el in root.iter(q("g")) if el.get("id"))
    texts_before = ["".join(t.itertext()).strip() for t in root.iter(q("text")) if "".join(t.itertext()).strip()]
    vb_before = root.get("viewBox")
    ops = json.load(open(a.ops, encoding="utf-8")).get("ops", [])
    log, errs = [], []
    dispatch = {
        "retext": op_retext, "replace_text": op_replace_text,
        "set_attr": op_set_attr, "move": op_move,
        "swap_edge": op_swap_edge, "set_marker": op_set_marker,
        "set_dash": op_set_dash,
        "delete": op_delete, "add_note": op_add_note,
        "add_node": op_add_node, "add_edge": op_add_edge,
        "add_legend": op_add_legend, "add_group": op_add_group,
    }
    for o in ops:
        fn = dispatch.get(o.get("op"))
        if fn is None:
            errs.append("unknown op %r" % o.get("op"))
        else:
            try:
                fn(root, o, log, errs)
            except Exception as ex:
                errs.append("op %s failed: %s" % (o.get("op"), ex))
    groups_after = sum(1 for el in root.iter(q("g")) if el.get("id"))
    texts_after = ["".join(t.itertext()).strip() for t in root.iter(q("text")) if "".join(t.itertext()).strip()]
    # Post-edit lightweight geometric sanity check (viewBox clipping & severe node-box overlap)
    edit_audit_warns = []
    vb_cur = _parse_viewbox(root)
    pmap_fin = build_parent_map(root)
    anchors_fin = _collect_node_anchors(root, pmap_fin)
    if vb_cur:
        vx0, vy0, vw0, vh0 = vb_cur
        vx1, vy1 = vx0 + vw0, vy0 + vh0
        for anc_a in anchors_fin:
            lbl_a, bb_a = anc_a.get("label", ""), anc_a.get("bbox")
            if bb_a and (bb_a[0] < vx0 - 4 or bb_a[1] < vy0 - 4 or bb_a[2] > vx1 + 4 or bb_a[3] > vy1 + 4):
                edit_audit_warns.append("node %r extends outside viewBox" % lbl_a[:30])
    for i_a in range(len(anchors_fin)):
        la, ba = anchors_fin[i_a].get("label", ""), anchors_fin[i_a].get("bbox")
        if not ba:
            continue
        for j_a in range(i_a + 1, len(anchors_fin)):
            lb, bb = anchors_fin[j_a].get("label", ""), anchors_fin[j_a].get("bbox")
            if not bb:
                continue
            ix = min(ba[2], bb[2]) - max(ba[0], bb[0])
            iy = min(ba[3], bb[3]) - max(ba[1], bb[1])
            if ix > 6.0 and iy > 6.0:
                area_a = max((ba[2] - ba[0]) * (ba[3] - ba[1]), 1.0)
                area_b = max((bb[2] - bb[0]) * (bb[3] - bb[1]), 1.0)
                if (ix * iy) / min(area_a, area_b) > 0.25:
                    edit_audit_warns.append("overlapping edited nodes: %r vs %r" % (la[:24], lb[:24]))
    out_svg = os.path.join(a.out_dir, stem + ".svg")
    tree.write(out_svg, xml_declaration=True, encoding="utf-8")
    res = {"edited_svg": out_svg, "original_copy": orig_copy,
           "source_preserved": os.path.exists(orig_copy),
           "groups_before": groups_before, "groups_after": groups_after,
           "viewBox_before": vb_before, "viewBox_after": root.get("viewBox"),
           "texts_added": [t for t in texts_after if t not in texts_before][:20],
           "texts_removed": [t for t in texts_before if t not in texts_after][:20],
           "applied_ops": log, "errors": errs, "audit_warnings": edit_audit_warns[:12], "n_ops": len(ops)}
    if not a.no_render:
        res["render"] = render(out_svg, a.out_dir, stem, dpi=a.dpi)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
