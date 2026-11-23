"""Style tokens + text measurement helpers (matplotlib, mm-space)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.text import Text

MM_PER_INCH = 25.4
PT_TO_MM = 25.4 / 72.0

_CJK_FULL_FONTS = (
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK SC",
    "Noto Sans CJK HK", "Noto Sans CJK JP", "Source Han Sans SC",
    "SimHei", "Microsoft YaHei", "PingFang SC", "AR PL UMing CN",
)


def has_cjk(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text))


def contrast_text_color(bg_hex, dark="#10243B", light="#FFFFFF"):
    """Pick high-contrast foreground (dark or light) from hex background color."""
    if not isinstance(bg_hex, str):
        return dark
    s = bg_hex.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return dark
    try:
        r, g, b = int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0
    except ValueError:
        return dark
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return light if lum < 0.45 else dark


def wrap_label(text, max_chars=24):
    """Auto-wrap long single-line labels into 2-3 balanced, orphan-free lines without losing words."""
    s = str(text or "")
    if "\n" in s or not s.strip():
        return s
    eff_max = int(max_chars * 0.65) if has_cjk(s) else max_chars
    if len(s) <= eff_max:
        return s
    words = s.split()
    if len(words) >= 2:
        # Try 2 lines first if balanced length fits within slight slack, else up to 3 balanced lines
        def _split_k(ws, k):
            total = sum(len(w) for w in ws) + len(ws) - 1
            target = total / float(k)
            lines, cur = [], ""
            for wi, w in enumerate(ws):
                rem_lines = k - len(lines) - 1
                rem_words = len(ws) - wi - 1
                cand = (cur + " " + w).strip() if cur else w
                if cur and rem_lines > 0 and rem_words >= rem_lines - 1:
                    if len(cand) > eff_max or (len(cur) >= target * 0.82 and abs(len(cand) - target) > abs(len(cur) - target)):
                        lines.append(cur)
                        cur = w
                        continue
                cur = cand
            if cur:
                lines.append(cur)
            return lines

        k_need = 2 if len(s) <= eff_max * 2 + 2 else 3
        lines = _split_k(words, k_need)
        # Prevent ugly 1-3 char orphan last line (e.g. Roman numeral "I" / "II" / "A")
        if len(lines) >= 2 and len(lines[-1]) <= 3 and len(lines[-2].split()) >= 2:
            prev_ws = lines[-2].split()
            if len(lines[-2]) + 1 + len(lines[-1]) <= eff_max + 4:
                lines[-2] = lines[-2] + " " + lines[-1]
                lines.pop()
            else:
                moved = prev_ws.pop()
                lines[-2] = " ".join(prev_ws)
                lines[-1] = moved + " " + lines[-1]
        return "\n".join(lines[:3])
    # Single long token (e.g., CJK or slash/hyphen-joined): split cleanly near midpoint
    mid = len(s) // 2
    for sep in ("/", "-", "_", "·", "、", "，"):
        idx = s.find(sep, max(3, mid - 5), min(len(s) - 2, mid + 6))
        if idx != -1:
            return s[:idx + 1] + "\n" + s[idx + 1:]
    if has_cjk(s):
        return s[:mid] + "\n" + s[mid:]
    return s


def configure_fonts(base_family="sans-serif", prefer_cjk=False):
    """Use DejaVu Sans for Latin; when prefer_cjk=True put a full bilingual CJK+Latin font first."""
    try:
        all_names = {f.name for f in fm.fontManager.ttflist}
        cjk = [c for c in _CJK_FULL_FONTS if c in all_names]
        if prefer_cjk and cjk:
            chain = cjk + ["DejaVu Sans", "Arial", "Helvetica"]
        else:
            chain = ["DejaVu Sans", "Arial", "Helvetica"] + cjk
        plt.rcParams["font.family"] = base_family
        plt.rcParams["font.sans-serif"] = chain
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        plt.rc("font", family=base_family)

STYLE = {
    "font_family": "sans-serif",
    "node_fill": "#EAF2FB", "node_stroke": "#2E5E8C", "node_text": "#10243B",
    "sublabel_text": "#4A5B6D", "group_fill": "#F5F7FA", "group_stroke": "#8A99A8",
    "group_text": "#2D3B48", "edge_color": "#2C3A47", "edge_label_bg": "#FFFFFF",
    "panel_label": "#000000", "title_color": "#10243B",
    "legend_bg": "#FFFFFF", "legend_stroke": "#C8D0D8",
    # colorblind-safe categorical palette (Okabe-Ito subset)
    "palette": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#8C8C8C"],
    "line_w": 1.4, "edge_w": 1.5, "node_lw": 1.3, "group_lw": 1.0,
    "arrow_len": 2.8, "arrow_w": 1.7, "tbar_len": 2.6,
    "fontsize": 9.0, "min_scale": 0.78, "margin_mm": 6.5, "panel_gap_mm": 6.0,
    "node_gap_x": 14.0, "node_gap_y": 9.0,
    "pad_x": 3.2, "pad_y": 2.2,
}

EDGE_KINDS = {
    "activates":       {"ls": "-",           "head": "arrow",      "color": "#1E3A5F"},
    "catalyzes":       {"ls": "-",           "head": "arrow",      "color": "#1E3A5F"},
    "inhibits":        {"ls": "-",           "head": "tbar",       "color": "#C0392B"},
    "inhibits_dashed": {"ls": (0, (4, 2)),   "head": "tbar",       "color": "#C0392B"},
    "translocates":    {"ls": (0, (4, 2)),   "head": "arrow_open", "color": "#0072B2"},
    "binds":           {"ls": "-",           "head": "arrow_both", "color": "#5B4B8A"},
    "flows":           {"ls": "-",           "head": "arrow",      "color": "#1E3A5F"},
    "assoc":           {"ls": "-",           "head": "none",       "color": "#5D6D7E"},
    "compare":         {"ls": (0, (2, 2)),   "head": "none",       "color": "#5D6D7E"},
}


def canonical_edge_kind(raw_kind):
    """Normalize biological edge-kind synonyms so inhibition/translocation never silently fall back to activates."""
    k = str(raw_kind or "activates").strip().lower().replace("-", "_").replace(" ", "_")
    if k in EDGE_KINDS:
        return k
    if any(w in k for w in ("inhibit", "repress", "block", "suppress", "antagon", "downreg", "attenuat", "degrad", "cleav", "prevent")):
        if any(w in k for w in ("dash", "indirect", "putative", "weak")):
            return "inhibits_dashed"
        return "inhibits"
    if any(w in k for w in ("transloc", "transport", "shuttle", "traffick", "import", "export", "migrat", "secret", "nuclear")):
        return "translocates"
    if any(w in k for w in ("bind", "interact", "complex", "dimer", "recruit", "dock", "heterodimer")):
        return "binds"
    if any(w in k for w in ("catalyz", "enzym", "convert", "synthes")):
        return "catalyzes"
    if any(w in k for w in ("flow", "step", "next", "stage", "pipeline", "process")):
        return "flows"
    if any(w in k for w in ("compar", "contrast", "versus")):
        return "compare"
    if any(w in k for w in ("assoc", "correl", "link")):
        return "assoc"
    return "activates"


def canonical_shape(raw_shape):
    """Normalize common node shape synonyms cleanly."""
    s = str(raw_shape or "round").strip().lower().replace("-", "_").replace(" ", "_")
    if s in SHAPES:
        return s
    aliases = {
        "circle": "ellipse", "oval": "ellipse", "ligand": "ellipse",
        "box": "rect", "rectangle": "rect", "square": "rect",
        "rounded": "round", "rounded_rect": "round", "roundrect": "round",
        "pill": "stadium", "capsule": "stadium", "effector": "stadium",
        "decision": "diamond", "rhombus": "diamond",
        "hex": "hexagon", "drug": "hexagon", "small_molecule": "hexagon", "inhibitor": "hexagon",
        "receptor": "complex", "dimer": "complex", "heterodimer": "complex",
        "promoter": "gene", "dna": "gene", "locus": "gene", "mrna": "gene",
    }
    return aliases.get(s, "round")


def edge_color(edge_or_kind):
    """Resolve edge color: explicit item color wins, else semantic default for kind."""
    if isinstance(edge_or_kind, dict):
        if edge_or_kind.get("color"):
            return edge_or_kind["color"]
        k = canonical_edge_kind(edge_or_kind.get("kind", "activates"))
    else:
        k = canonical_edge_kind(edge_or_kind)
    return EDGE_KINDS.get(k, EDGE_KINDS["activates"]).get("color", STYLE["edge_color"])


SHAPES = {"rect", "round", "ellipse", "stadium", "diamond", "hexagon", "complex", "gene"}
UNIT_HINTS = {"%", "fold", "ratio", "pH", "°C", "x", "U", "AU", "log2", "score", "n"}


class Measurer:
    """Measure rendered text sizes in mm using a hidden figure (with cache)."""

    def __init__(self, fontsize=9.0, prefer_cjk=None):
        if prefer_cjk is not None:
            configure_fonts(STYLE["font_family"], prefer_cjk=prefer_cjk)
        elif "DejaVu Sans" not in plt.rcParams.get("font.sans-serif", []):
            configure_fonts(STYLE["font_family"], prefer_cjk=False)
        self.fig = plt.figure(figsize=(4, 4), dpi=100)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(0, 100)
        self.mm_per_unit = (4 * MM_PER_INCH) / 100.0
        self.fontsize = fontsize
        self.fig.canvas.draw()
        self.renderer = self.fig.canvas.get_renderer()
        self._cache = {}

    def text_mm(self, s, fontsize=None, weight="normal"):
        """Return (width_mm, height_mm, n_lines) of string s (may contain \\n)."""
        if s is None or s == "":
            return 0.0, 0.0, 0
        fs = float(fontsize) if fontsize else float(self.fontsize)
        key = (str(s), round(fs, 2), weight)
        if key in self._cache:
            return self._cache[key]
        t = Text(0, 50, str(s), fontsize=fs, fontweight=weight)
        self.ax.add_artist(t)
        try:
            bb = t.get_window_extent(renderer=self.renderer)
            inv = self.ax.transData.inverted()
            (x0, y0), (x1, y1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
            res = (abs(x1 - x0) * self.mm_per_unit,
                   abs(y1 - y0) * self.mm_per_unit,
                   len(str(s).split("\n")))
            self._cache[key] = res
            return res
        finally:
            t.remove()

    def close(self):
        plt.close(self.fig)


def line_height_mm(fontsize):
    return fontsize * PT_TO_MM * 1.32


def legend_dims(panel, measurer, avail_w, fs=7.2):
    """Shared legend layout math (used by height budgeting and drawing)."""
    leg = panel.get("legend")
    if not leg:
        return None
    items = leg.get("items", [])
    if not items:
        return None
    lh = line_height_mm(fs)
    glyph_w = 13.5  # 11mm glyph + 2.5mm gap
    item_gap = 6.0
    widths = [glyph_w + measurer.text_mm(it.get("label", ""), fontsize=fs)[0] + item_gap
              for it in items]
    title_w = measurer.text_mm(leg.get("title", "Legend"), fontsize=fs, weight="bold")[0] + 6.0
    box_max_w = max(avail_w - 2.0, 48.0)
    inner_max_w = max(box_max_w - 4.0, 40.0)
    rows, xi, max_row_w = 1, 0.0, 0.0
    for wd in widths:
        if xi > 0 and xi + wd - item_gap > inner_max_w:
            max_row_w = max(max_row_w, xi - item_gap)
            rows += 1
            xi = 0.0
        xi += wd
    max_row_w = max(max_row_w, xi - item_gap)
    w = min(box_max_w, max(title_w, max_row_w + 5.0, 32.0))
    h = lh * (rows + 1) + 4.8
    return {"w": w, "h": h, "lh": lh, "rows": rows, "fs": fs,
            "n_items": len(items), "glyph_w": glyph_w, "item_gap": item_gap}
