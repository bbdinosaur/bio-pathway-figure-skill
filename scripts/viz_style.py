"""Style/palette/naming constants for the bio-pathway diagram engine. UTF-8 only."""
from __future__ import annotations

FONT_STACK = ("Helvetica, Arial, 'DejaVu Sans', 'Noto Sans CJK SC', 'WenQuanYi Zen Hei', sans-serif")

def _hx(c):
    c = str(c).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))

def _mix(a, b, t):
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

def contrast_text(hex_col):
    """Return high-contrast ink (#ffffff or #0f172a) using WCAG relative luminance."""
    try:
        r, g, b = [v / 255.0 for v in _hx(hex_col)]
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#ffffff" if lum < 0.48 else "#0f172a"
    except Exception:
        return "#0f172a"

PALETTES = {
    "fold":     ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"],
    "blues":    ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5"],
    "viridis":  ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "reds":     ["#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#de2d26", "#a50f15"],
    # Colorblind-safe Nature / Okabe-Ito inspired qualitative palette
    "qual":     ["#2563eb", "#0d9488", "#d97706", "#7c3aed", "#dc2626", "#059669", "#db2777", "#475569"],
}

def ramp(name, t):
    """Map t in [0,1] to a palette color."""
    stops = PALETTES.get(name, PALETTES["blues"])
    t = min(1.0, max(0.0, float(t)))
    n = len(stops) - 1
    i = min(int(t * n), n - 1)
    return _mix(_hx(stops[i]), _hx(stops[i + 1]), t * n - i)

NODE_STYLES = {
    "protein":    {"fill": "#e3ecfb", "stroke": "#3b69b8", "shape": "rect"},
    "receptor":   {"fill": "#e2f4ea", "stroke": "#2f855a", "shape": "rect"},
    "gene":       {"fill": "#fef4e0", "stroke": "#c48422", "shape": "rect", "italic": True},
    "complex":    {"fill": "#f0e8fe", "stroke": "#7c3aed", "shape": "rect", "double": True},
    "metabolite": {"fill": "#e4f7ef", "stroke": "#1f8f63", "shape": "hex"},
    "dna":        {"fill": "#edf1f6", "stroke": "#64748b", "shape": "rect"},
    "cell":       {"fill": "#fdecec", "stroke": "#be5b5b", "shape": "ellipse"},
    "process":    {"fill": "#f0fdf4", "stroke": "#15803d", "shape": "pill"},
    "phenotype":  {"fill": "#f0fdf4", "stroke": "#15803d", "shape": "pill"},
    "drug":       {"fill": "#fff1f2", "stroke": "#be123c", "shape": "hex"},
    "other":      {"fill": "#f1f5f9", "stroke": "#64748b", "shape": "rect"},
}

# Every interaction type has a unique visual signature (color + endpoint + optional start glyph)
EDGE_STYLES = {
    "activation":      {"color": "#1d4ed8", "end": "arrow"},
    "recruitment":     {"color": "#0284c7", "end": "arrow",    "start_dot": True},
    "inhibition":      {"color": "#dc2626", "end": "bar"},
    "binding":         {"color": "#7c3aed", "end": "diamond",  "both": True},
    "phosphorylation": {"color": "#b45309", "end": "circle",   "tag": "P"},
    "ubiquitination":  {"color": "#92400e", "end": "circle",   "tag": "Ub"},
    "modification":    {"color": "#a21caf", "end": "circle",   "tag": "M"},
    "transport":       {"color": "#0f766e", "end": "open"},
    "translocation":   {"color": "#0d9488", "end": "open",     "start_dot": True},
    "expression":      {"color": "#475569", "end": "open"},
    "transcription":   {"color": "#4f46e5", "end": "open",     "start_bar": True},
    "degradation":     {"color": "#991b1b", "end": "cross",    "default_dashed": True},
    "undirected":      {"color": "#64748b", "end": "open_dot", "both": True, "default_dashed": True},
    "other":           {"color": "#334155", "end": "arrow"},
}
EDGE_ORDER = list(EDGE_STYLES.keys())

COMP_STYLES = {
    "exterior":  {"fill": "#f7fafd", "border": "#cbd5e1"},
    "membrane":  {"fill": "#e7eef5", "border": "#94a3b8"},
    "cytosol":   {"fill": "#fcfdff", "border": "#d6e0ec"},
    "nucleus":   {"fill": "#eaf1fc", "border": "#adc3e2"},
    "organelle": {"fill": "#f3f0fc", "border": "#b7aee0"},
    "custom":    {"fill": "#f8fafc", "border": "#cbd5e1"},
}

def text_w(s, size):
    """Estimate rendered text width in px (latin ~0.60em, CJK 1.0em). Multi-line aware."""
    lines = str(s).split("\n")
    best = 0.0
    for ln in lines:
        w = 0.0
        for ch in ln:
            w += size * (1.0 if ord(ch) > 0x2E80 else 0.60)
        if w > best:
            best = w
    return best

SCALES = {"compact": 60, "regular": 88, "roomy": 124}
