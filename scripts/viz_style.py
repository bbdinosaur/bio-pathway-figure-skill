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
    """Return high-contrast ink (#ffffff or #0f172a) using true WCAG 2.1 sRGB luminance."""
    try:
        def _lin(u):
            return (u / 12.92) if u <= 0.04045 else (((u + 0.055) / 1.055) ** 2.4)
        r, g, b = [_lin(v / 255.0) for v in _hx(hex_col)]
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        # Compare WCAG contrast ratio vs white (L=1) and dark slate (L≈0.008)
        cr_white = 1.05 / (lum + 0.05)
        cr_dark = (lum + 0.05) / 0.058
        return "#ffffff" if cr_white >= cr_dark else "#0f172a"
    except Exception:
        return "#0f172a"

PALETTES = {
    "fold":     ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"],
    "blues":    ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5"],
    "viridis":  ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "reds":     ["#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#de2d26", "#a50f15"],
    "greens":   ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#31a354", "#006d2c"],
    "oranges":  ["#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b", "#fd8d3c", "#e6550d", "#a63603"],
    "purples":  ["#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#756bb1", "#54278f"],
    "ylorrd":   ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"],
    "plasma":   ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"],
    # Colorblind-safe Nature / Okabe-Ito inspired qualitative palette
    "qual":     ["#2563eb", "#0d9488", "#d97706", "#7c3aed", "#dc2626", "#059669", "#db2777", "#475569"],
}
PALETTE_ALIASES = {
    "rdbu": "fold", "rd_bu": "fold", "redblue": "fold", "red_blue": "fold",
    "coolwarm": "fold", "bwr": "fold", "diverging": "fold", "seismic": "fold",
    "rdylbu": "fold", "bluered": "fold", "blue_red": "fold", "log2fc": "fold",
    "zscore": "fold", "z_score": "fold", "heat": "ylorrd", "hot": "ylorrd",
    "blue": "blues", "red": "reds", "green": "greens", "orange": "oranges", "purple": "purples",
}

def ramp(name, t):
    """Map t in [0,1] to a palette color with case-insensitive & *_r reverse support."""
    key = str(name or "blues").strip().lower()
    rev = False
    if key.endswith("_r") and len(key) > 2:
        rev = True
        key = key[:-2]
    key = PALETTE_ALIASES.get(key, key)
    stops = PALETTES.get(key, PALETTES["blues"])
    if rev:
        stops = list(reversed(stops))
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

def is_diverging(name) -> bool:
    key = str(name or "blues").strip().lower()
    if key.endswith("_r") and len(key) > 2:
        key = key[:-2]
    return PALETTE_ALIASES.get(key, key) == "fold"

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

def wrap_text(s, maxpx, size):
    """CJK-aware word wrapper that preserves explicit newlines and breaks wide unspaced CJK runs cleanly."""
    out = []
    for para in str(s or "").split("\n"):
        if not para:
            continue
        words = para.split(" ")
        cur = ""
        for w in words:
            t = (cur + " " + w).strip() if cur else w
            if text_w(t, size) <= maxpx:
                cur = t
            elif not cur or text_w(w, size) > maxpx:
                if cur:
                    out.append(cur)
                    cur = ""
                # Break overly long token (e.g. unspaced Chinese sentence or long ID) char-by-char
                buf = ""
                for ch in w:
                    if buf and text_w(buf + ch, size) > maxpx and ch not in "）)】》。.,，；;:：":
                        out.append(buf)
                        buf = ch
                    else:
                        buf += ch
                cur = buf
            else:
                out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out

SCALES = {"compact": 60, "regular": 88, "roomy": 124}
