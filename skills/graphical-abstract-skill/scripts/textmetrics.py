#!/usr/bin/env python3
"""Text width estimation + greedy wrapping for DejaVu Sans / Arial-like fonts.

Stdlib only. Used by ga_pipeline.py (autofit) and ga_check.py (overflow audit).
Estimation uses per-character em-width classes calibrated for DejaVu Sans;
a 6% safety margin is applied by callers via SAFETY.
"""
from __future__ import annotations

SAFETY = 1.06  # inflate estimated widths by 6% before comparing to boxes

# em-fraction width classes (DejaVu Sans approximate advance widths)
_NARROW = set("iljtIf1.,:;'`!|()[]{}-")
_WIDE = set("mwMW@%&")
_CAPS = set("ABCDEFGHJKLNOPQRSTUVXYZ0123456789")
_LOWER = set("abcdeghknopqsuvxyz")
_LOWER_N = set("frt")
_CJK_MIN, _CJK_MAX = 0x2E80, 0x9FFF


def char_em(ch: str) -> float:
    o = ord(ch)
    if (_CJK_MIN <= o <= _CJK_MAX) or (0xFF00 <= o <= 0xFF60):
        return 1.0
    if ch == " ":
        return 0.32
    if ch in _NARROW:
        return 0.32
    if ch in _WIDE:
        return 0.92
    if ch in _CAPS:
        return 0.68
    if ch in _LOWER:
        return 0.58
    if ch in _LOWER_N:
        return 0.40
    return 0.60


_NO_LINE_START = set("，。！？；：、）》」】〕〉”’.,!?;:)]}%‰")


def text_width(text: str, fontsize: float) -> float:
    """Estimated rendered width in px (font-size in px)."""
    if not text:
        return 0.0
    em = sum(char_em(c) for c in text)
    return em * fontsize * SAFETY


def wrap_text(text: str, fontsize: float, max_width: float) -> list[str]:
    """Greedy word wrap with CJK kinsoku (no orphan line-start punctuation)."""
    if max_width <= 0 or not text:
        return [text] if text else []
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = w if not cur else cur + " " + w
            if text_width(trial, fontsize) <= max_width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            # token alone too wide -> char split with kinsoku check
            while text_width(w, fontsize) > max_width and len(w) > 1:
                k = max(1, int(len(w) * max_width / max(text_width(w, fontsize), 1e-6)))
                while k > 1 and text_width(w[:k], fontsize) > max_width:
                    k -= 1
                while k + 1 < len(w) and text_width(w[:k + 1], fontsize) <= max_width:
                    k += 1
                # Avoid leaving closing punctuation at the start of the next line
                if k < len(w) and w[k] in _NO_LINE_START:
                    if text_width(w[:k + 1], fontsize) <= max_width * 1.06:
                        k += 1
                    elif k > 1:
                        k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
        if cur:
            # Avoid orphan single punctuation line when wrapping CJK/mixed text
            if (len(cur) <= 2 and all(c in _NO_LINE_START for c in cur)
                    and lines and text_width(lines[-1] + cur, fontsize) <= max_width * 1.08):
                lines[-1] = lines[-1] + cur
            elif len(cur) == 1 and cur in _NO_LINE_START and lines and len(lines[-1]) > 2:
                lines.append(lines[-1][-1] + cur)
                lines[-2] = lines[-2][:-1]
            else:
                lines.append(cur)
        elif not lines:
            lines.append("")
    return lines


def fit_font(text: str, max_width: float, start: float, floor: float, step: float = 1.0) -> float:
    """Largest font size in [floor, start] whose single-line width fits."""
    fs = start
    while fs - step >= floor and text_width(text, fs) > max_width:
        fs -= step
    return max(floor, fs)


if __name__ == "__main__":  # tiny self-test
    assert wrap_text("the quick brown fox jumps", 14, 120)[0].count(" ") >= 1
    assert text_width("MM", 20) > text_width("il", 20)
    print("textmetrics OK")
