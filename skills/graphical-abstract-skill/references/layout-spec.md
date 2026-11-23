# Layout & export specification (`ga_pipeline.py` / `galayout.py` / `gadoc.py`)

## Canvas & topologies
- Default canvas: **1600×900 px** viewBox (journal GA & 16:9 presentation standard); custom `canvas: [W, H]` supported (`600..4000 × 400..3000`).
- Margins `22 px`, panel gaps `30 px`, title zone `84 px`, footer band `38 px`.
- Supported panel topologies:
  - **`hero-2x2`** (auto-selected for 4 panels with mechanism/chart/row unless `panel_weights` is given): Top row `31% / 69%` (A Question + B Hero Mechanism/Method), Bottom row `64% / 36%` (C Hero Quantitative Results + D Conclusion/KPI); row height `48% / 52%`.
  - **`1+3`** (journal Figure 3 classic): Full-width top hero schematic/overview (`46%`) + 3 equal or custom-weighted (`bottom_weights`) bottom quantitative panels (`54%`).
  - **`2x2`**: Equal 2×2 quadrants (`50% / 50%`).
  - **`hero-1+2`** / **`hero-2+1`**: 3-panel asymmetric layouts (1 wide hero + 2 companion panels).
  - **`left-hero`**: Tall left hero panel (`44%`, customizable via `col_weights`) + 2–3 stacked right panels (`right_weights`).
  - **`stack`** / **`2x1`**: Full-width stacked rows (`row_weights`).
  - **`grid`** (auto-selected for 5–8 panels unless `panel_weights` is given): Balanced 2-row grid (`3+2`, `3+3`, `4+3`, `4+4`).
  - **`row`**: Single horizontal strip (1–8 panels, default equal or custom `panel_weights`).
- Themes:
  - **`card`** (default Graphical Abstract): rounded card `rx=11`, subtle role tint, `5.5 px` accent spine, colored letter chip `A–H`, 4-color header rule.
  - **`journal`** (Nature/Cell multi-panel figure): pure white background, clean hairline `rx=4` framing (`#E2E8F0`), bold dark panel letter (`a`/`b`/`c`/`d`), single crisp publication header rule (`#0F172A`).

## Typography & autofit
- Font stack: `DejaVu Sans, Arial, Helvetica, Noto Sans CJK SC, Noto Serif CJK SC, WenQuanYi Zen Hei, sans-serif`.
- CJK wrapping enforces basic kinsoku (no orphan closing punctuation at line start).

| element | size (px) | notes |
|---|---|---|
| Title | 28 → 18 min | Auto-shrink + 2-line wrap fallback |
| Subtitle | 13.5 | Auto-fit |
| Panel title | 15.0 | Auto-fit (bold width compensated) |
| Panel body | 14 → 13 → 12 → 11 | Autofit; sparse non-chart/non-mechanism panels upshift to 15 px |
| Chart ticks / labels | `max(10, fs-1)` / `max(10, fs-2)` | Rotated `ylabel` auto-fits to plot height |
| Footer | 11 | Provenance left, version right |

- Absolute font floor in generated SVGs: **10.0 px** (`ga_check.py` flags anything smaller).
- If content overflows even at 11 px → `overflow: true` (exit 1); shorten copy in `brief.json` rather than silently truncating.

## Exports (single SVG source of truth)
1. `<stem>.svg` — Master editable source, pure SVG 1.1 primitives, Inkscape-compatible named layers:
   `layer-background`, `layer-title`, `layer-panels` (`panel-P1`…), `layer-links`, `layer-footer`. All `<text>` elements remain editable (zero outline conversion).
2. `<stem>.png` — Canvas-exact 1:1 raster (`cw × ch`, strictly **96 DPI ≤ 108 DPI** preview), checked for non-blank variance.
3. `<stem>.pdf` — Single-page vector PDF matching native canvas dimensions (`1600×900 px = 1200×675 pt`), preserving real searchable text (`pdftotext` verifiable) and infinite print resolution.
4. Optional `<stem>_<DPI>dpi.png` — Print-resolution raster generated ONLY when `--hires-dpi <DPI>` (e.g., `300`) is explicitly requested by the workorder.

## Render engine fallback chain
`google-chrome` / `chromium` → `soffice --headless` + `pdftoppm` → ImageMagick `convert`.
If every renderer is unavailable, the master SVG is still written and `ga_result.py` honestly marks `status: "partial"` with missing exports listed in `limits`.

## Determinism
No timestamps, no RNG, stable iteration order → identical `brief.json` produces byte-identical SVG and structurally repeatable PNG/PDF across runs.
