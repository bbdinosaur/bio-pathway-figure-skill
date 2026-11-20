"""Style/palette/naming constants for the bio-pathway diagram engine. UTF-8 only."""
from __future__ import annotations

FONT_STACK = ("Helvetica, Arial, 'DejaVu Sans', 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', sans-serif")

def _hx(c):
    return tuple(int(c[i:i+2], 16) for i in (1, 3, 5))

def _mix(a, b, t):
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

PALETTES = {
    "fold":  ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"],
    "blues": ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5"],
    "qual":  ["#4a72b8", "#3a8f5f", "#c98a2d", "#8b5cf6", "#d65f5f", "#0f766e"],
}

def ramp(name, t):
    """Map t in [0,1] to a palette color."""
    stops = PALETTES.get(name, PALETTES["blues"])
    t = min(1.0, max(0.0, float(t)))
    n = len(stops) - 1
    i = min(int(t * n), n - 1)
    return _mix(_hx(stops[i]), _hx(stops[i + 1]), t * n - i)

NODE_STYLES = {
    "protein":    {"fill": "#e3ecfb", "stroke": "#4a72b8"},
    "receptor":   {"fill": "#e5f3ea", "stroke": "#3a8f5f"},
    "gene":       {"fill": "#fdf3e0", "stroke": "#c98a2d", "italic": True},
    "complex":    {"fill": "#f1e9fd", "stroke": "#8b5cf6", "double": True},
    "metabolite": {"fill": "#e7f6ef", "stroke": "#2f9e6e", "shape": "hex"},
    "dna":        {"fill": "#eef1f5", "stroke": "#64748b"},
    "cell":       {"fill": "#fdeeee", "stroke": "#c26b6b", "shape": "ellipse"},
    "other":      {"fill": "#f1f5f9", "stroke": "#64748b"},
}

EDGE_STYLES = {
    "activation":      {"color": "#1d4ed8", "end": "arrow"},
    "recruitment":     {"color": "#1d4ed8", "end": "arrow"},
    "inhibition":      {"color": "#dc2626", "end": "bar"},
    "binding":         {"color": "#7c3aed", "end": "diamond", "both": True},
    "phosphorylation": {"color": "#b45309", "end": "circle", "tag": "P"},
    "ubiquitination":  {"color": "#92400e", "end": "circle", "tag": "Ub"},
    "transport":       {"color": "#0f766e", "end": "open"},
    "translocation":   {"color": "#0f766e", "end": "open"},
    "expression":      {"color": "#475569", "end": "open"},
    "other":           {"color": "#334155", "end": "arrow"},
}
EDGE_ORDER = list(EDGE_STYLES.keys())

COMP_STYLES = {
    "exterior":  {"fill": "#f7fafc", "border": "#cbd5e1"},
    "membrane":  {"fill": "#e8eef4", "border": "#94a3b8"},
    "cytosol":   {"fill": "#fdfeff", "border": "#dbe4ee"},
    "nucleus":   {"fill": "#eaf1fb", "border": "#b6c8e3"},
    "organelle": {"fill": "#f2f0fb", "border": "#b7aee0"},
    "custom":    {"fill": "#f8fafc", "border": "#cbd5e1"},
}

def text_w(s, size):
    """Estimate rendered text width in px (latin ~0.60em, CJK 1.0em)."""
    w = 0.0
    for ch in str(s):
        w += size * (1.0 if ord(ch) > 0x2E80 else 0.60)
    return w

SCALES = {"compact": 56, "regular": 86, "roomy": 122}
