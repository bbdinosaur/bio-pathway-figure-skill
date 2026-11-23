# Color, legend & accessibility rules (`gaconfig.py` / `ga_check.py`)

## Role accents (panel identity)
| role | accent | tint fill | soft fill |
|---|---|---|---|
| `question` | `#0072B2` | `#F3F8FC` | `#DCECF8` |
| `method` | `#009E73` | `#F1FAF6` | `#D5F2E6` |
| `mechanism` | `#0E7490` | `#F0FAFC` | `#CFFAFE` |
| `results` | `#D55E00` | `#FDF6F0` | `#FCE4D0` |
| `conclusion` | `#8B5CF6` | `#F6F3FE` | `#E8DFFD` |
| `neutral` | `#475569` | `#F8FAFC` | `#E2E8F0` |

## Series palette (charts — Okabe-Ito derived, luminance-tuned)
`["#0072B2", "#D55E00", "#00BE8A", "#CC79A7", "#E69F00", "#56B4E9"]`
- Order encodes priority: series 1 = primary finding.
- Line & dot charts pair colors with distinct markers (`circle`, `square`, `triangle`, `diamond`) and line dashes (`solid`, `6 3`, `2 2`, `8 3 2 3`) for grayscale & CVD legibility.
- `ga_check.py` audits every multi-series chart pair for both raw luminance (`dL >= 0.05`) and Machado 2009 deuteranopia-simulated luminance (`dL' >= 0.04`).

## Sequential heatmap ramp (colorblind & grayscale safe)
`["#F0F4F8", "#BDD7E7", "#6BAED6", "#2171B5", "#08306B"]`
- Cell text automatically switches to `#FFFFFF` when background luminance `< 0.32` (dark blue), else `#111827`.

## Legend & encoding rules
1. Every color, marker, or arrow polarity (`activate` arrow vs `inhibit` red `#DC2626` T-bar) appears in its legend, and vice versa.
2. Units live on axis labels (`ylabel` / `xlabel` / colorbar `unit`), never only in prose.
3. Error bars always state sample size `n` and error type (SD / SEM / 95% CI) in `note` or subtitle; if missing in source, record in `result.json` `uncertainty`.
4. Never reuse one visual channel for two unrelated variables in the same panel.

## Contrast
- Body text `#111827` and secondary ink `#374151` on `#FFFFFF` / role tints exceed WCAG AA.
- Muted ink `#64748B` is reserved for auxiliary metadata (`>= 10–11 px`).
