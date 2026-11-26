#!/usr/bin/env python3
"""Source-preserving SVG editor + machine-readable edit record.

Ops (JSON list or single object):
  {"op":"replace_text","find":..,"replace":..,"all":false}
  {"op":"replace_label","find":..,"replace":..,"all":false}     # text-node-only replacement
  {"op":"set_text_by_id","id":..,"text":..}                     # preserves single <tspan> wrapper
  {"op":"set_attr_by_id","id":..,"attr":..,"value":..}
  {"op":"set_style_by_id","id":..,"prop":..,"value":..}         # updates CSS style or XML attr
  {"op":"translate_by_id","id":..,"dx":..,"dy":..}              # moves element/group cleanly
  {"op":"hide_by_id","id":..}                                   # sets visibility="hidden"
  {"op":"remove_by_id","id":..}                                 # removes self-closing/paired tag
  {"op":"add_text","x":..,"y":..,"text":..,"size":..,"fill":..,"id":..,"layer_id":..}
  {"op":"insert_in_layer","layer_id":..,"svg":..}

Only matched fragments are rewritten; all untouched regions remain byte-identical.
Emits before/after values and preservation ratio in .edit-record.json.
"""
from __future__ import annotations
import sys, json, re, math, argparse, difflib
from html import unescape as html_unescape
import xml.etree.ElementTree as ET
from pathlib import Path

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def _id_pat(eid: str) -> str:
    return r'''\bid=(?P<idq>["'])''' + re.escape(str(eid)) + r'''(?P=idq)'''

def _replace_attr_on_tag(tag: str, attr: str, val_esc: str):
    attr_pat = re.compile(r'''\b''' + re.escape(attr) + r'''=(["'])([^"']*)\1''')
    am = attr_pat.search(tag)
    before = am.group(2) if am else None
    if am:
        q = am.group(1)
        new_tag = attr_pat.sub(lambda _m: f"{attr}={q}{val_esc}{q}", tag, count=1)
    elif tag.rstrip().endswith("/>"):
        idx = tag.rfind("/>")
        new_tag = tag[:idx] + f' {attr}="{val_esc}"' + tag[idx:]
    else:
        idx = tag.rfind(">")
        new_tag = tag[:idx] + f' {attr}="{val_esc}"' + tag[idx:]
    return new_tag, before

def _append_into_layer(svg: str, lid: str, el: str):
    """Append element right before the matching </g> of <g id='lid'> so painter's order is preserved."""
    lpat = re.compile(r'<(?:\w+:)?g\b[^>]*?' + _id_pat(lid) + r'[^>]*?>')
    lm = lpat.search(svg)
    if not lm:
        return svg, False
    depth = 1
    pos = lm.end()
    g_tok = re.compile(r'<(?:\w+:)?g\b([^>]*)>|</(?:\w+:)?g>')
    for gm in g_tok.finditer(svg, pos):
        tok = gm.group(0)
        if tok.startswith("</"):
            depth -= 1
            if depth == 0:
                return svg[:gm.start()] + "\n" + el + "\n" + svg[gm.start():], True
        elif not (gm.group(1) or "").rstrip().endswith("/"):
            depth += 1
    return svg[:lm.end()] + "\n" + el + svg[lm.end():], True

def apply_edits(svg, edits):
    record = []
    if isinstance(edits, dict):
        edits = [edits]
    for e in edits:
        op = e.get("op")
        if op == "replace_text":
            find, rep = str(e["find"]), esc(e["replace"])
            n = svg.count(find)
            if n == 0:
                record.append({"op": op, "find": e["find"], "status": "not_found"})
                continue
            if e.get("all"):
                svg = svg.replace(find, rep)
                record.append({"op": op, "before": e["find"], "after": e["replace"],
                               "status": "ok", "count": n})
            else:
                svg = svg.replace(find, rep, 1)
                record.append({"op": op, "before": e["find"], "after": e["replace"],
                               "status": "ok", "count": 1})
        elif op == "replace_label":
            find, rep = str(e["find"]), esc(e["replace"])
            find_esc = esc(find)
            hit = [0]
            limit = 0 if e.get("all") else 1
            def _sub_node(m):
                if limit and hit[0] >= limit:
                    return m.group(0)
                inner = m.group(2)
                target = find if (find in inner) else (find_esc if (find_esc != find and find_esc in inner) else None)
                if target is not None:
                    hit[0] += 1
                    new_inner = inner.replace(target, rep) if e.get("all") else inner.replace(target, rep, 1)
                    return m.group(1) + new_inner + m.group(3)
                return m.group(0)
            # Pass 1: target actual <text>/<tspan> leaf nodes first so <style>/<metadata> are never touched
            txt_leaf_pat = re.compile(r'(<(?:\w+:)?(?:text|tspan)\b[^>]*>)([^<]+)(</(?:\w+:)?(?:text|tspan)>)')
            svg = txt_leaf_pat.sub(_sub_node, svg)
            if hit[0] == 0:
                pat = re.compile(r'(>)([^<]+)(<)')
                svg = pat.sub(_sub_node, svg)
            if hit[0] == 0:
                # Fallback: text split across nested <tspan> elements (multi-line OR kerning-split)
                tpat = re.compile(r'(<(?:\w+:)?text\b[^>]*>)(.*?)(</(?:\w+:)?text>)', re.S)
                raw_rep = str(e["replace"])
                find_norm = " ".join(find.split())
                find_tight = "".join(find.split())
                def _sub_tspan_text(tm):
                    if limit and hit[0] >= limit:
                        return tm.group(0)
                    inner = tm.group(2)
                    plain_sp = " ".join(html_unescape(re.sub(r"<[^>]+>", " ", inner)).split())
                    plain_tg = " ".join(html_unescape(re.sub(r"<[^>]+>", "", inner)).split())
                    matched_mode = None
                    if find_norm in plain_sp:
                        matched_mode = "sp"
                    elif find_norm in plain_tg:
                        matched_mode = "tg"
                    elif find_tight and find_tight in "".join(plain_tg.split()):
                        matched_mode = "tight"
                    if matched_mode:
                        hit[0] += 1
                        base_plain = plain_sp if matched_mode == "sp" else plain_tg
                        if matched_mode == "tight":
                            new_plain = raw_rep
                        else:
                            new_plain = base_plain.replace(find_norm, raw_rep) if e.get("all") else base_plain.replace(find_norm, raw_rep, 1)
                        ts_all = list(re.finditer(r'(<(?:\w+:)?tspan\b[^>]*>)(.*?)(</(?:\w+:)?tspan>)', inner, re.S))
                        if ts_all:
                            lines = new_plain.split("\n")
                            if len(lines) == 1:
                                return tm.group(1) + ts_all[0].group(1) + esc(new_plain) + ts_all[0].group(3) + tm.group(3)
                            return tm.group(1) + "".join(
                                ts_all[min(i, len(ts_all) - 1)].group(1) + esc(ln) + ts_all[min(i, len(ts_all) - 1)].group(3)
                                for i, ln in enumerate(lines)
                            ) + tm.group(3)
                        return tm.group(1) + esc(new_plain) + tm.group(3)
                    return tm.group(0)
                svg = tpat.sub(_sub_tspan_text, svg)
            if hit[0] == 0:
                record.append({"op": op, "find": e["find"], "status": "not_found"})
            else:
                record.append({"op": op, "before": e["find"], "after": e["replace"],
                               "status": "ok", "count": hit[0]})
        elif op == "set_text_by_id":
            pat = re.compile(
                r'(?P<open><(?:\w+:)?(?P<tag>text|tspan)\b[^>]*' + _id_pat(e["id"]) + r'[^>]*>)'
                r'(?P<inner>.*?)'
                r'(?P<close></(?:\w+:)?(?P=tag)>)',
                re.S
            )
            m = pat.search(svg)
            if not m:
                # Fallback: id placed on parent <g id="..."> directly wrapping a <text> (never cross </g>!)
                gpat = re.compile(
                    r'(<(?:\w+:)?g\b[^>]*' + _id_pat(e["id"]) + r'[^>]*>(?:(?!</(?:\w+:)?g>).)*?'
                    r'(?P<open><(?:\w+:)?text\b[^>]*>)(?P<inner>.*?)(?P<close></(?:\w+:)?text>))',
                    re.S
                )
                gm = gpat.search(svg)
                if not gm:
                    record.append({"op": op, "id": e["id"], "status": "not_found"})
                    continue
                inner = gm.group("inner")
                old = re.sub(r"<[^>]+>", "", inner)
                new_esc = esc(e["text"])
                ts_all = list(re.finditer(r'(<(?:\w+:)?tspan\b[^>]*>)(.*?)(</(?:\w+:)?tspan>)', inner, re.S))
                if ts_all:
                    lines = str(e["text"]).split("\n")
                    if len(lines) == 1:
                        replacement_inner = ts_all[0].group(1) + new_esc + ts_all[0].group(3)
                    else:
                        replacement_inner = "".join(
                            ts_all[min(i, len(ts_all) - 1)].group(1) + esc(ln) + ts_all[min(i, len(ts_all) - 1)].group(3)
                            for i, ln in enumerate(lines)
                        )
                else:
                    replacement_inner = new_esc
                svg = svg[:gm.start("inner")] + replacement_inner + svg[gm.end("inner"):]
                record.append({"op": op, "id": e["id"], "before": old, "after": str(e["text"]), "status": "ok"})
                continue
            inner = m.group("inner")
            old = re.sub(r"<[^>]+>", "", inner)
            new_esc = esc(e["text"])
            # Preserve single or multi <tspan ...> wrapper(s) if present (Inkscape/Illustrator/matplotlib SVGs)
            ts_all = list(re.finditer(r'(<(?:\w+:)?tspan\b[^>]*>)(.*?)(</(?:\w+:)?tspan>)', inner, re.S))
            if ts_all:
                lines = str(e["text"]).split("\n")
                if len(lines) == 1:
                    replacement_inner = ts_all[0].group(1) + new_esc + ts_all[0].group(3)
                else:
                    replacement_inner = "".join(
                        ts_all[min(i, len(ts_all) - 1)].group(1) + esc(ln) + ts_all[min(i, len(ts_all) - 1)].group(3)
                        for i, ln in enumerate(lines)
                    )
            else:
                replacement_inner = new_esc
            svg = svg[:m.start()] + m.group("open") + replacement_inner + m.group("close") + svg[m.end():]
            record.append({"op": op, "id": e["id"], "before": old, "after": str(e["text"]), "status": "ok"})
        elif op == "set_attr_by_id":
            tag_pat = re.compile(r'<(?:\w+:)?\w+\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?/?>')
            m = tag_pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "attr": e["attr"], "status": "not_found"})
                continue
            new_tag, before = _replace_attr_on_tag(m.group(0), str(e["attr"]), esc(e["value"]))
            svg = svg[:m.start()] + new_tag + svg[m.end():]
            record.append({"op": op, "id": e["id"], "attr": e["attr"],
                           "before": before, "after": str(e["value"]), "status": "ok"})
        elif op == "set_style_by_id":
            tag_pat = re.compile(r'<(?:\w+:)?\w+\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?/?>')
            m = tag_pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "prop": e["prop"], "status": "not_found"})
                continue
            tag = m.group(0)
            prop, val = str(e["prop"]), esc(e["value"])
            sm = re.search(r'''\bstyle=(["'])([^"']*)\1''', tag)
            if sm and re.search(r'(?:^|;\s*)' + re.escape(prop) + r'\s*:', sm.group(2)):
                style_str = sm.group(2)
                pm = re.search(r'((?:^|;\s*)' + re.escape(prop) + r'\s*:\s*)([^;"]*)', style_str)
                before = pm.group(2).strip() if pm else None
                new_style = re.sub(
                    r'((?:^|;\s*)' + re.escape(prop) + r'\s*:\s*)([^;"]*)',
                    lambda mm: mm.group(1) + val,
                    style_str, count=1
                )
                new_tag = tag[:sm.start(2)] + new_style + tag[sm.end(2):]
            else:
                new_tag, before = _replace_attr_on_tag(tag, prop, val)
            svg = svg[:m.start()] + new_tag + svg[m.end():]
            record.append({"op": op, "id": e["id"], "prop": prop,
                           "before": before, "after": str(e["value"]), "status": "ok"})
        elif op == "set_css_class_style":
            cls = str(e.get("class") or e.get("selector") or "").lstrip(".")
            prop, val = str(e["prop"]), esc(e["value"])
            cpat = re.compile(r'(\.' + re.escape(cls) + r'\b[^{]*\{)([^}]*)(\})', re.S)
            cm = cpat.search(svg)
            if not cm:
                record.append({"op": op, "class": cls, "prop": prop, "status": "not_found"})
                continue
            body = cm.group(2)
            ppat = re.compile(r'((?:^|;)\s*' + re.escape(prop) + r'\s*:\s*)([^;}]*)')
            pm = ppat.search(body)
            if pm:
                before = pm.group(2).strip()
                new_body = ppat.sub(lambda mm: mm.group(1) + val, body, count=1)
            else:
                before = None
                sep = "" if (not body.strip() or body.rstrip().endswith(";")) else ";"
                new_body = body + f"{sep}{prop}:{val};"
            svg = svg[:cm.start(2)] + new_body + svg[cm.end(2):]
            record.append({"op": op, "class": cls, "prop": prop, "before": before, "after": str(e["value"]), "status": "ok"})
        elif op == "translate_by_id":
            tag_pat = re.compile(r'<(?:\w+:)?\w+\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?/?>')
            m = tag_pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "status": "not_found"})
                continue
            dx, dy = float(e.get("dx", 0)), float(e.get("dy", 0))
            tag = m.group(0)
            tm = re.search(r'''\btransform=(["'])([^"']*)\1''', tag)
            tr_add = f"translate({dx:g},{dy:g})"
            if tm:
                before = tm.group(2)
                new_tr = (before + " " + tr_add).strip()
                new_tag = tag[:tm.start(2)] + new_tr + tag[tm.end(2):]
            else:
                before = None
                new_tag, _ = _replace_attr_on_tag(tag, "transform", tr_add)
                new_tr = tr_add
            svg = svg[:m.start()] + new_tag + svg[m.end():]
            record.append({"op": op, "id": e["id"], "before": before, "after": new_tr, "status": "ok"})
        elif op == "hide_by_id":
            tag_pat = re.compile(r'<(?:\w+:)?\w+\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?/?>')
            m = tag_pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "status": "not_found"})
                continue
            new_tag, before = _replace_attr_on_tag(m.group(0), "visibility", "hidden")
            svg = svg[:m.start()] + new_tag + svg[m.end():]
            record.append({"op": op, "id": e["id"], "before": before, "after": "hidden", "status": "ok"})
        elif op == "remove_by_id":
            sc_pat = re.compile(r'<(?:\w+:)?(\w+)\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?/>')
            m = sc_pat.search(svg)
            if m:
                svg = svg[:m.start()] + svg[m.end():]
                record.append({"op": op, "id": e["id"], "status": "ok"})
                continue
            open_pat = re.compile(r'<(?:\w+:)?(\w+)\b[^>]*?' + _id_pat(e["id"]) + r'[^>]*?>')
            m2 = open_pat.search(svg)
            if not m2:
                record.append({"op": op, "id": e["id"], "status": "not_found"})
                continue
            # Depth-counted matching close tag so nested <g>...</g> never corrupts XML!
            tname = m2.group(1)
            tok_p = re.compile(r'<(?:\w+:)?' + re.escape(tname) + r'\b([^>]*)>|</(?:\w+:)?' + re.escape(tname) + r'>')
            depth = 1
            end_pos = None
            for tm in tok_p.finditer(svg, m2.end()):
                tok = tm.group(0)
                if tok.startswith("</"):
                    depth -= 1
                    if depth == 0:
                        end_pos = tm.end()
                        break
                elif not (tm.group(1) or "").rstrip().endswith("/"):
                    depth += 1
            if end_pos is not None:
                svg = svg[:m2.start()] + svg[end_pos:]
                record.append({"op": op, "id": e["id"], "status": "ok"})
            else:
                record.append({"op": op, "id": e["id"], "status": "not_found"})
        elif op == "add_text":
            anc = esc(e.get("anchor", "middle"))
            wt = f' font-weight="{esc(e["weight"])}"' if e.get("weight") else ""
            it = ' font-style="italic"' if e.get("italic") else ""
            ff = esc(e.get("font_family", "Helvetica, Arial, 'DejaVu Sans', 'Noto Sans CJK SC', sans-serif"))
            el = (f'<text x="{e.get("x", 40)}" y="{e.get("y", 20)}" font-size="{e.get("size", 12)}"'
                  f' text-anchor="{anc}" dominant-baseline="central"{wt}{it}'
                  f' fill="{e.get("fill", "#334155")}" font-family="{ff}"'
                  f' id="{esc(e.get("id", "added_text"))}"'
                  f' data-role="annotation">{esc(e["text"])}</text>')
            lid = e.get("layer_id")
            inserted = False
            if lid:
                svg, inserted = _append_into_layer(svg, str(lid), el)
            if not inserted:
                svg = svg.replace("</svg>", el + "\n</svg>", 1)
            record.append({"op": op, "text": str(e["text"]), "layer_id": lid if inserted else None, "status": "ok"})
        elif op == "add_shape":
            sk = str(e.get("shape", "rect")).lower()
            sid = esc(e.get("id", "added_shape"))
            fill = esc(e.get("fill", "none"))
            stroke = esc(e.get("stroke", "#334155"))
            sw = e.get("stroke_w", 1.8 if sk in ("arrow", "tbar") else 1.5)
            dash = ' stroke-dasharray="6,4"' if e.get("dashed") else ""
            if sk == "circle":
                el = (f'<circle cx="{e.get("cx", 50)}" cy="{e.get("cy", 50)}" r="{e.get("r", 8)}"'
                      f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash} id="{sid}" data-role="annotation"/>')
            elif sk == "ellipse":
                el = (f'<ellipse cx="{e.get("cx", 50)}" cy="{e.get("cy", 50)}" rx="{e.get("rx", 30)}" ry="{e.get("ry", 18)}"'
                      f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash} id="{sid}" data-role="annotation"/>')
            elif sk == "polyline":
                pts = " ".join(f"{float(p[0]):.1f},{float(p[1]):.1f}" for p in (e.get("pts") or []))
                el = (f'<polyline points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'
                      f' stroke-linecap="round" stroke-linejoin="round"{dash} id="{sid}" data-role="annotation"/>')
            elif sk in ("arrow", "tbar"):
                x1, y1 = float(e.get("x1", 0)), float(e.get("y1", 0))
                x2, y2 = float(e.get("x2", 60)), float(e.get("y2", 0))
                dx, dy = x2 - x1, y2 - y1
                dist = math.hypot(dx, dy) or 1.0
                ux, uy = dx / dist, dy / dist
                nx, ny = -uy, ux
                if sk == "arrow":
                    hlen, hhalf = float(e.get("head_len", 10)), float(e.get("head_half", 4.5))
                    sx2, sy2 = x2 - ux * hlen, y2 - uy * hlen
                    p_str = f"{x2:.1f},{y2:.1f} {sx2 + nx*hhalf:.1f},{sy2 + ny*hhalf:.1f} {sx2 - nx*hhalf:.1f},{sy2 - ny*hhalf:.1f}"
                    el = (f'<g id="{sid}" data-role="edge">\n'
                          f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{sx2:.1f}" y2="{sy2:.1f}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round"{dash}/>\n'
                          f'  <polygon points="{p_str}" fill="{stroke}" stroke="{stroke}" stroke-width="0.6"/>\n'
                          f'</g>')
                else:
                    bh = float(e.get("bar_half", 6.5))
                    el = (f'<g id="{sid}" data-role="edge">\n'
                          f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round"{dash}/>\n'
                          f'  <line x1="{x2 - nx*bh:.1f}" y1="{y2 - ny*bh:.1f}" x2="{x2 + nx*bh:.1f}" y2="{y2 + ny*bh:.1f}" stroke="{stroke}" stroke-width="{float(sw) + 0.6}" stroke-linecap="round"/>\n'
                          f'</g>')
            elif sk == "line":
                el = (f'<line x1="{e.get("x1", 0)}" y1="{e.get("y1", 0)}" x2="{e.get("x2", 40)}" y2="{e.get("y2", 0)}"'
                      f' stroke="{stroke}" stroke-width="{sw}"{dash} id="{sid}" data-role="annotation"/>')
            else:
                rx = e.get("rx", 4)
                el = (f'<rect x="{e.get("x", 40)}" y="{e.get("y", 20)}" width="{e.get("w", 80)}" height="{e.get("h", 30)}"'
                      f' rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash} id="{sid}" data-role="annotation"/>')
            lid = e.get("layer_id")
            inserted = False
            if lid:
                svg, inserted = _append_into_layer(svg, str(lid), el)
            if not inserted:
                svg = svg.replace("</svg>", el + "\n</svg>", 1)
            record.append({"op": op, "shape": sk, "id": sid, "layer_id": lid if inserted else None, "status": "ok"})
        elif op == "insert_in_layer":
            lid = str(e.get("layer_id", ""))
            frag = str(e.get("svg", ""))
            svg, inserted = _append_into_layer(svg, lid, frag)
            if not inserted:
                record.append({"op": op, "layer_id": lid, "status": "not_found"})
            else:
                record.append({"op": op, "layer_id": lid, "status": "ok"})
        else:
            record.append({"op": str(op), "status": "unknown_op"})
    # Enrich any not_found record with closest SVG IDs / labels / CSS classes for instant 1-shot recovery
    if any(r.get("status") == "not_found" for r in record):
        all_ids = sorted(set(re.findall(r'\bid=["\']([^"\']+)["\']', svg)))
        all_texts = sorted(set(
            " ".join(html_unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split())
            for m in re.finditer(r'<(?:\w+:)?text\b[^>]*>(.*?)</(?:\w+:)?text>', svg, re.S)
            if m.group(1).strip()
        ))
        all_cls = sorted(set(re.findall(r'\.([A-Za-z_][\w-]*)', "\n".join(re.findall(r'<style[^>]*>(.*?)</style>', svg, re.S | re.I)))))
        for r in record:
            if r.get("status") != "not_found":
                continue
            if r.get("find"):
                sug = difflib.get_close_matches(str(r["find"]), all_texts, n=3, cutoff=0.4)
                if not sug:
                    q_lo = str(r["find"]).lower()
                    sug = [t for t in all_texts if q_lo in t.lower()][:3]
                if sug:
                    r["suggestions"] = sug
            elif r.get("id") or r.get("layer_id"):
                q = str(r.get("id") or r.get("layer_id"))
                sug = difflib.get_close_matches(q, all_ids, n=4, cutoff=0.4)
                if sug:
                    r["suggestions"] = sug
            elif r.get("class"):
                sug = difflib.get_close_matches(str(r["class"]).lstrip("."), all_cls, n=3, cutoff=0.4)
                if sug:
                    r["suggestions"] = sug
    return svg, record

def preservation_stats(src, out):
    src_lines = src.splitlines()
    out_lines = out.splitlines()
    sm = difflib.SequenceMatcher(None, src_lines, out_lines, autojunk=False)
    unchanged = sum(b.size for b in sm.get_matching_blocks())
    total = max(1, max(len(src_lines), len(out_lines)))
    gpat = re.compile(r'<(?:\w+:)?g\b[^>]*?\bid=["\']([^"\']+)["\']')
    l_src = sorted(set(gpat.findall(src)))
    l_out = sorted(set(gpat.findall(out)))
    return {
        "unchanged_lines": unchanged,
        "total_lines": total,
        "unchanged_line_ratio": round(unchanged / total, 4),
        "byte_delta": len(out.encode("utf-8")) - len(src.encode("utf-8")),
        "layers_before": len(l_src),
        "layers_after": len(l_out),
        "layers_preserved": all(lid in l_out for lid in l_src),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--edits", required=True, help="JSON file or inline JSON")
    ap.add_argument("--out", required=True)
    ap.add_argument("--record", default=None)
    a = ap.parse_args()
    src = Path(a.svg).read_text(encoding="utf-8")
    p = Path(a.edits)
    edits = json.loads(p.read_text(encoding="utf-8")) if p.exists() else json.loads(a.edits)
    out_svg, rec = apply_edits(src, edits)
    Path(a.out).write_text(out_svg, encoding="utf-8")
    rec_path = Path(a.record) if a.record else Path(a.out).with_suffix(".edit-record.json")
    xml_ok = True
    try:
        ET.fromstring(out_svg)
    except Exception:
        xml_ok = False
    payload = {
        "source": a.svg, "output": a.out, "edits": rec, "source_preserved": True,
        "xml_valid": xml_ok,
        "preservation": preservation_stats(src, out_svg),
    }
    rec_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": a.out, "record": str(rec_path),
                      "ok": sum(1 for r in rec if r["status"] == "ok"),
                      "not_found": sum(1 for r in rec if r["status"] == "not_found"),
                      "total": len(rec),
                      "unchanged_line_ratio": payload["preservation"]["unchanged_line_ratio"]}))

if __name__ == "__main__":
    main()
