#!/usr/bin/env python3
"""GA-Skill shared config: canvas, colorblind-safe palette, roles. Stdlib only."""
from __future__ import annotations

import re

W, H = 1600, 900
MARGIN = 22
GAP = 30
TITLE_H = 84
FOOTER_H = 38

FONT = ("DejaVu Sans, Arial, Helvetica, Noto Sans CJK SC, "
        "Noto Serif CJK SC, WenQuanYi Zen Hei, sans-serif")
INK = "#111827"
INK2 = "#374151"
MUT = "#64748B"
GRID = "#E5E9F0"
GRID_MINOR = "#F1F5F9"
EDGE = "#CBD5E1"
ARROW = "#64748B"

# Okabe-Ito derived, luminance-tuned series palette (colorblind & grayscale safe)
SERIES = ["#0072B2", "#D55E00", "#00BE8A", "#CC79A7", "#E69F00", "#56B4E9"]

# Sequential colorblind-safe ramp (low -> high, Cividis/Viridis-inspired)
HEAT_RAMP = ["#F0F4F8", "#BDD7E7", "#6BAED6", "#2171B5", "#08306B"]
# Diverging colorblind-safe RdBu ramp (negative -> zero -> positive)
DIV_RAMP = ["#2166AC", "#67A9CF", "#F7F7F7", "#EF8A62", "#B2182B"]

ROLE = {
    "question":   {"accent": "#0072B2", "fill": "#F3F8FC", "soft": "#DCECF8"},
    "method":     {"accent": "#009E73", "fill": "#F1FAF6", "soft": "#D5F2E6"},
    "results":    {"accent": "#D55E00", "fill": "#FDF6F0", "soft": "#FCE4D0"},
    "conclusion": {"accent": "#8B5CF6", "fill": "#F6F3FE", "soft": "#E8DFFD"},
    "mechanism":  {"accent": "#0E7490", "fill": "#F0FAFC", "soft": "#CFFAFE"},
    "neutral":    {"accent": "#475569", "fill": "#F8FAFC", "soft": "#E2E8F0"},
}

ROLE_ALIAS = {
    "background": "question", "problem": "question", "hypothesis": "question",
    "aim": "question", "motivation": "question", "context": "question",
    "approach": "method", "workflow": "method", "protocol": "method",
    "methods": "method", "design": "method", "pipeline": "method",
    "pathway": "mechanism", "signaling": "mechanism", "model": "mechanism",
    "schematic": "mechanism", "biology": "mechanism",
    "data": "results", "findings": "results", "validation": "results",
    "quantification": "results", "experiment": "results", "result": "results",
    "summary": "conclusion", "impact": "conclusion", "takeaway": "conclusion",
    "implications": "conclusion", "outlook": "conclusion", "significance": "conclusion",
}


def resolve_role(role: str | None) -> str:
    r = str(role or "neutral").strip().lower()
    if r in ROLE:
        return r
    return ROLE_ALIAS.get(r, "neutral")


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _hex_rgb(hexcolor: str):
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def interp_ramp(t: float, ramp=HEAT_RAMP) -> str:
    """Map t in [0, 1] to a hex color along sequential ramp."""
    t = max(0.0, min(1.0, float(t)))
    n = len(ramp) - 1
    pos = t * n
    i = min(int(pos), n - 1)
    f = pos - i
    c0, c1 = _hex_rgb(ramp[i]), _hex_rgb(ramp[i + 1])
    rgb = tuple(int(round(a + (b - a) * f)) for a, b in zip(c0, c1))
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def luminance(hexcolor: str) -> float:
    r, g, b = (c / 255.0 for c in _hex_rgb(hexcolor))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def lum_delta(a: str, b: str) -> float:
    return abs(luminance(a) - luminance(b))


def _unit_to_px(val: str) -> float | None:
    if not val:
        return None
    m = re.match(
        r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-z%]*)\s*$",
        str(val).lower(),
    )
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2)
    if num <= 0:
        return None
    scale = {"": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0, "in": 96.0,
             "cm": 96.0 / 2.54, "mm": 96.0 / 25.4}
    return num * scale[unit] if unit in scale else None


def _extract_root_svg_tag(svg_text: str) -> str:
    """Strictly extract the root <svg ...> opening tag (ignoring comments & child elements)."""
    if not svg_text:
        return ""
    head = re.sub(r"<!--.*?-->", "", svg_text[:32768], flags=re.S)
    m = re.search(r"<svg\b[^>]*>", head, re.I | re.S)
    if not m and len(svg_text) > 32768:
        m = re.search(r"<svg\b[^>]*>", re.sub(r"<!--.*?-->", "", svg_text, flags=re.S), re.I | re.S)
    return m.group(0) if m else ""


def _svg_attr(root_tag: str, name: str) -> str | None:
    """Extract a standalone attribute (single or double quoted) from the root <svg> tag."""
    if not root_tag:
        return None
    m = re.search(rf'(?<=\s){name}\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', root_tag, re.I)
    if not m:
        return None
    val = m.group(1) if m.group(1) is not None else m.group(2)
    return val.strip()


def _parse_viewbox_str(vb_str: str | None) -> tuple[float, float, float, float] | None:
    if not vb_str:
        return None
    try:
        parts = [float(x) for x in re.split(r"[\s,]+", vb_str.strip()) if x]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return (parts[0], parts[1], parts[2], parts[3])
    except Exception:
        pass
    return None


def parse_svg_dims(svg_text: str, default=(W, H)) -> tuple[int, int]:
    """Extract canvas pixel (w, h) strictly from root <svg> width/height or viewBox."""
    root_tag = _extract_root_svg_tag(svg_text)
    w = _unit_to_px(_svg_attr(root_tag, "width") or "")
    h = _unit_to_px(_svg_attr(root_tag, "height") or "")
    if not w or not h:
        vb = _parse_viewbox_str(_svg_attr(root_tag, "viewBox"))
        if vb:
            _, _, vbw, vbh = vb
            if not w and not h:
                w, h = vbw, vbh
            elif not w:
                w = h * (vbw / vbh)
            elif not h:
                h = w * (vbh / vbw)
    return int(round(w or default[0])), int(round(h or default[1]))


def parse_svg_viewbox(svg_text: str, default=(0.0, 0.0, float(W), float(H))) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, width, height) strictly from root <svg> viewBox or width/height."""
    root_tag = _extract_root_svg_tag(svg_text)
    vb = _parse_viewbox_str(_svg_attr(root_tag, "viewBox"))
    if vb:
        return vb
    w, h = parse_svg_dims(svg_text, default=(int(default[2]), int(default[3])))
    return (0.0, 0.0, float(w), float(h))


VERSION = "GA-Skill v19.1"
ROLE_ACCENTS = [ROLE[k]["accent"] for k in ("question", "method", "results", "conclusion")]
