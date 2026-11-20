"""SVG writer for primitive lists (pure stdlib, no dependencies)."""
from __future__ import annotations
from viz_style import FONT_STACK

def _dash(p):
    return ' stroke-dasharray="7,5"' if p.get("dashed") else ""

def _stroke(p):
    if p.get("stroke") in (None, "none"):
        return ""
    s = f' stroke="{p["stroke"]}" stroke-width="{p.get("stroke_w", 1)}"'
    s += ' stroke-linejoin="round" stroke-linecap="round"'
    return s + _dash(p)

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def prim_to_svg(p):
    op = p["op"]
    role = p.get("role", "")
    drole = f' data-role="{role}"' if role else ""
    eid = p.get("_id")
    if eid:
        import re as _re
        drole += ' id="' + _re.sub(r"[^A-Za-z0-9_.-]", "_", str(eid)) + '"'
    if op == "rect":
        return (f'<rect x="{p["x"]:.1f}" y="{p["y"]:.1f}" width="{p["w"]:.1f}" height="{p["h"]:.1f}"'
                f' rx="{p.get("rx", 0):.1f}" fill="{p["fill"]}"{_stroke(p)} opacity="{p.get("opacity", 1)}"{drole}/>')
    if op == "circle":
        return (f'<circle cx="{p["cx"]:.1f}" cy="{p["cy"]:.1f}" r="{p["r"]:.1f}" fill="{p["fill"]}"{drole}'
                f'{_stroke(p)}/>')
    if op == "ellipse":
        return (f'<ellipse cx="{p["cx"]:.1f}" cy="{p["cy"]:.1f}" rx="{p["rx"]:.1f}" ry="{p["ry"]:.1f}"{drole}'
                f' fill="{p["fill"]}"{_stroke(p)}/>')
    if op in ("polyline", "poly"):
        tag = "polyline" if op == "polyline" else "polygon"
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in p["pts"])
        fill = p.get("fill", "none")
        return f'<{tag} points="{pts}" fill="{fill}"{_stroke(p)}{drole}/>'
    if op == "text":
        anchor = p.get("anchor", "middle")
        weight = " font-weight=" + '"' + str(p.get("weight", "normal")) + '"'
        style = p.get("italic") and ' font-style="italic"' or ""
        rot = p.get("rotate")
        transform = f' transform="rotate({rot} {p["x"]:.1f} {p["y"]:.1f})"' if rot else ""
        halo = ' stroke="#ffffff" stroke-width="3" paint-order="stroke" stroke-linejoin="round"'
        return (f'<text x="{p["x"]:.1f}" y="{p["y"]:.1f}" font-size="{p.get("size", 15)}"'
                f' text-anchor="{anchor}"{weight}{style} fill="{p.get("fill", "#1e293b")}"'
                f'{transform}{halo} font-family="{esc(FONT_STACK)}"{drole}>{esc(p["s"])}</text>')
    return ""

def to_svg(prims, W, H, title="figure"):
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
            f' viewBox="0 0 {W} {H}" font-family="{esc(FONT_STACK)}">'
            f'<title>{esc(title)}</title>\n'
            f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>\n')
    body = "\n".join(prim_to_svg(p) for p in prims)
    return head + body + "\n</svg>\n"
