#!/usr/bin/env python3
"""Source-preserving SVG text edits + machine-readable edit record.

Ops (JSON list): {"op":"replace_text","find":..,"replace":..,"all":false}
              |  {"op":"set_text_by_id","id":..,"text":..}
              |  {"op":"set_attr_by_id","id":..,"attr":..,"value":..}
              |  {"op":"add_text","x":..,"y":..,"text":..,"size":..}
Only matched fragments are rewritten; all other bytes stay identical.
"""
from __future__ import annotations
import sys, json, re, argparse
from pathlib import Path

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

def apply_edits(svg, edits):
    record = []
    for e in edits:
        op = e.get("op")
        if op == "replace_text":
            find, rep = str(e["find"]), esc(e["replace"])
            n = svg.count("" + find + "")
            if n == 0:
                record.append({"op": op, "find": e["find"], "status": "not_found"})
                continue
            if e.get("all"):
                svg = svg.replace("" + find + "", "" + rep + "")
                record.append({"op": op, "find": e["find"], "replace": e["replace"],
                               "status": "ok", "count": n})
            else:
                svg = svg.replace("" + find + "", "" + rep + "", 1)
                record.append({"op": op, "find": e["find"], "replace": e["replace"], "status": "ok"})
        elif op == "set_text_by_id":
            pat = re.compile(r'(<text[^>]*id="' + re.escape(e["id"]) + r'"[^>]*>)(.*?)(</text>)', re.S)
            m = pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "status": "not_found"})
                continue
            old = re.sub(r"<[^>]+>", "", m.group(2))
            svg = pat.sub(lambda mm: mm.group(1) + esc(e["text"]) + mm.group(3), svg, count=1)
            record.append({"op": op, "id": e["id"], "before": old, "after": str(e["text"]), "status": "ok"})
        elif op == "set_attr_by_id":
            tag_pat = re.compile(r'<\w+\b[^>]*?id="' + re.escape(e["id"]) + r'"[^>]*?/?>')
            m = tag_pat.search(svg)
            if not m:
                record.append({"op": op, "id": e["id"], "attr": e["attr"], "status": "not_found"})
                continue
            tag = m.group(0)
            attr_pat = re.compile(r'\b' + re.escape(e["attr"]) + r'="[^"]*"')
            new_tag, n_sub = attr_pat.subn(f'{e["attr"]}="{esc(e["value"])}"', tag, count=1)
            if n_sub == 0:
                new_tag = tag.replace("/>", f' {e["attr"]}="{esc(e["value"])}"/>', 1) \
                    if tag.rstrip().endswith("/>") else tag
            svg = svg[:m.start()] + new_tag + svg[m.end():]
            record.append({"op": op, "id": e["id"], "attr": e["attr"], "after": str(e["value"]), "status": "ok"})
        elif op == "add_text":
            svg = svg.replace("</svg>",
                f'<text x="{e.get("x", 40)}" y="{e.get("y", 20)}" font-size="{e.get("size", 12)}"'
                f' fill="{e.get("fill", "#334155")}" id="{esc(e.get("id", "added_text"))}"'
                f'>{esc(e["text"])}</text>\n</svg>')
            record.append({"op": op, "text": str(e["text"]), "status": "ok"})
        else:
            record.append({"op": str(op), "status": "unknown_op"})
    return svg, record

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svg", required=True)
    ap.add_argument("--edits", required=True, help="JSON file or inline JSON")
    ap.add_argument("--out", required=True)
    ap.add_argument("--record", default=None)
    a = ap.parse_args()
    src = Path(a.svg).read_text(encoding="utf-8")
    raw = Path(a.edits).read_text(encoding="utf-8") if Path(a.edits).exists() else a.edits
    edits = json.loads(raw)
    out, record = apply_edits(src, edits)
    Path(a.out).write_text(out, encoding="utf-8")
    rec = {"source": str(a.svg), "output": str(a.out), "n_edits": len(edits),
           "source_preserved": True, "edits": record}
    rp = Path(a.record or (a.out + ".edit-record.json"))
    rp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
