# Specification Schema (`spec.json`)

`make_figure.py` and `run_case.py` consume one JSON spec supporting three modes: `"mechanism"`,
`"chart"`, and `"composite"`. Unknown keys are ignored; omitted fields use sensible defaults.

## 1. Mechanism Mode (`"mode": "mechanism"`)
```json
{
  "mode": "mechanism",
  "title": "Short declarative mechanism title",
  "caption": "Evidence & data encoding note (auto-wrapped).",
  "compartments": [
    {"id": "ext", "label": "Extracellular", "kind": "exterior"},
    {"id": "mb",  "label": "Plasma membrane", "kind": "membrane"},
    {"id": "cyt", "label": "Cytosol", "kind": "cytosol"},
    {"id": "nuc", "label": "Nucleus", "kind": "nucleus"}
  ],
  "groups": [
    {"id": "mapk", "label": "MAPK cascade", "members": ["RAF1", "MAP2K1", "MAPK1"],
     "style": "dashed", "source": "Materials §3.3"}
  ],
  "nodes": [
    {"id": "EGFR", "label": "EGFR", "kind": "receptor", "compartment": "mb",
     "mods": ["P"], "alias": "ERBB1", "sublabel": "RTK",
     "value": 8.4, "source": "Materials §3.1 p.4"}
  ],
  "edges": [
    {"from": "EGFR", "to": "GRB2", "type": "recruitment", "label": "pY1045",
     "evidence": "direct", "dashed": false, "route": "direct",
     "source": "Materials §3.2 Fig.2A"}
  ],
  "data_map": {"palette": "blues", "min": "0", "max": "10",
               "caption": "Node fill encodes log2 TPM (Table S2).",
               "source": "Table S2"},
  "width_map": {"min": 0.2, "max": 1.0, "caption": "Edge width encodes confidence.", "source": "Table S3"},
  "size_map": {"min": 0.0, "max": 1.0, "caption": "Node size encodes score."},
  "layout": {"auto_arc": true, "tighten_bands": true, "auto_tier": true,
             "evidence_auto_style": true},
  "legend": true
}
```

### Key options
- **Compartment kinds**: `exterior`, `membrane` (auto lipid bilayer interrupted by receptors; ≥2 membranes supported for cell-to-cell synapses),
  `cytosol`, `nucleus`, `organelle` (mitochondria/ER/Golgi/lysosome), `custom`.
- **Node kinds**: `receptor` (spans membrane band; intracellular/nuclear/cleaved receptors also valid in cytosol/nucleus), `protein`, `gene` (italicized), `complex`
  (double border), `metabolite` (hexagon), `drug` (rose hexagon), `process` / `phenotype`
  (rounded pill), `cell` (ellipse), `dna`, `other`.
- **Node fields**: `mods` (`["P","Ub","Ac","GTP","Me","SUMO"]`), `alias` (small italic inside node below primary label),
  `sublabel` (second line inside node), `subunits` (`["PIK3CA","PIK3R1"]` rendered as subunit pills inside complexes),
  `row` / `tier` (explicit integer sub-row inside a
  compartment; auto-tiered when wide), `value` (numeric value mapped automatically to `data_map`
  fill color with WCAG contrast text and/or `size_map` bi-dimensional node scaling), optional explicit `x`/`y`/`w`/`h`.
- **Edge fields**: `type` (see `arrow_semantics.md`), `label`, `evidence` (non-direct values such as `inferred`/`reported`/`putative` auto-dash and `weak` auto-dots when `evidence_auto_style` is enabled),
  `dashed` (indirect/reported), `dotted` (weak), `weight` / `confidence` (numeric value mapped
  to stroke width via `width_map` with automatic legend swatches), `route`: `"direct"` (default;
  auto obstacle-avoiding on same-row & cross-row), `"arc"` (staggered top rail), `"feedback"`
  (same-row top rail or obstacle-free outer right-margin rail for cross-compartment feedback).
- **Palettes**: `blues`, `fold`/`rdbu` (blue-white-red diverging with automatic `0` midpoint tick), `viridis`, `reds`, `greens`, `oranges`, `purples`, `ylorrd`, `plasma`, `qual` (colorblind-safe), plus `*_r` reverse variants.

## 2. Chart Mode (`"mode": "chart"`)
Supports **9 quantitative plot types** via `chart.kind` (auto-inferred from data keys) and direct
zero-transcription-error **`from_table`** binding (`{"file": "/input/data.csv|.tsv|.xlsx", "sheet"?: ..., "filter"?: {"col":..., "eq":...}, "label_col":..., "value_col"|"x_col"|"series_cols"|"value_cols":..., "sort_by"?:..., "top_n"?:...}`):
- **Vertical bar (`kind: "bar"`)**: `bars: [{label, value, err?, group?, points?: [r1,r2,...], italic?, source?}]`,
  `stars: [{pair: [i, j], text: "**"}]`, `x_label`, `y_label`, `y_note`.
- **Grouped multi-series bar (`kind: "grouped_bar"`)**: `categories: ["MYC", "CCND1", ...]`,
  `series: [{name, values: [...], errs?: [...], points?: [[...], ...], color?, source?}]`,
  `italic_x?: bool`, `x_label`, `y_label`, `y_note`.
- **Stacked / 100% composition bar (`kind: "stacked_bar"`)**: `categories: [...]`,
  `series: [{name, values: [...], color?, source?}]`, `normalize?: true` (100% proportions).
- **Horizontal / diverging bar (`kind: "hbar"` or `horizontal: true`)**: same `bars` schema (supports positive & diverging `+/-` NES/log2FC).
- **Line / time-course (`kind: "line"`)**: `series: [{name, x: [...], y: [...], err?: [...], dashed?: bool, source?}]`
  (numeric or categorical X; automatically draws translucent `±SD` confidence ribbons when `err` is provided),
  `hlines: [{y: 1.0, label?: "baseline"}]`, `x_label`, `y_label`, `y_note`.
- **Scatter / auto-volcano (`kind: "scatter"` or `"volcano"`)**: `points: [{x, y, group?: "Up"|"Down"|"NS", label?, size?, source?}]`,
  optional `x_thresh`/`y_thresh` (auto-classifies Up/Down/NS with legend counts and dashed threshold guides),
  `hlines`, `vlines`, `x_label`, `y_label`, `y_note`.
- **Heatmap (`kind: "heatmap"`)**: `rows: [...]`, `cols: [...]`, `values: [[...]]`, `palette: "fold"`,
  `cbar_label`, `italic_rows: true`, `annotate: true`, `y_note`.
- **Pathway enrichment bubble dotplot (`kind: "dotplot"`)**: `items: [{label, x, size, color, source?}]`,
  `x_label`, `color_label`, `size_label`, `palette: "reds"` (dual colorbar + gene-count size legend).
- **Box-and-whisker + replicate strip (`kind: "box"`)**: `groups: [{label, values: [...], color?, source?}]`,
  `sig_brackets: [{a: 0, b: 1, label: "***"}]`, `y_label`, `y_note`.

All chart numbers MUST be copied verbatim from source tables/data files and cited in `y_note`/`source`.

## 3. Composite Multi-Panel Mode (`"mode": "composite"`)
```json
{
  "mode": "composite",
  "title": "Overall multi-panel figure title",
  "caption": "(A) Mechanism summary. (B) Expression validation.",
  "layout": {"cols": 2, "panel_gap": 24},
  "panels": [
    {"id": "A", "spec": {"mode": "mechanism", "...": "..."}},
    {"id": "B", "spec": {"mode": "chart", "...": "..."}}
  ]
}
```
Each panel receives a bold `A`/`B`/`C` badge and its own `<g id="panel-A" transform="translate(...)">`
layer group in the editable SVG.
