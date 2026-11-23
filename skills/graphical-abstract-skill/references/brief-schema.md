# Brief schema (`brief.json` — input to `ga_pipeline.py`)

`brief.json` is the ONLY creative artifact the agent authors in creation mode.
Everything downstream is deterministic: identical brief → byte-identical SVG.

## Top-level fields

| field | type | required | notes |
|---|---|---|---|
| `title` | string | yes | Study headline; auto-shrunk (28→18 px) with 2-line wrap fallback |
| `subtitle` | string | no | One-line context (e.g., system, model, study design, DOI) |
| `canvas` | `[W, H]` | no | Custom px dims (`600..4000 × 400..3000`); default `[1600, 900]` |
| `theme` | string | no | `"card"` (default soft-tinted Graphical Abstract cards) or `"journal"` (crisp white multi-panel Nature/Cell style for primary figures like Fig. 3) |
| `layout` | string | no | `"auto"` (default), `"hero-2x2"`, `"2x2"`, `"hero-1+2"`, `"grid"`, `"row"`. Auto picks `hero-2x2` for 4-panel studies with mechanism/chart/row and `grid` for 5–6 panels unless `panel_weights` is set |
| `row_weights` | `[r0, r1]` | no | Top/bottom row height ratio for `2x2`/`hero-2x2` (default `[0.48, 0.52]` for `hero-2x2`) |
| `top_weights` | `[w0, w1]` | no | Top row panel width ratio (default `[0.31, 0.69]` for `hero-2x2`) |
| `bottom_weights` | `[w2, w3]` | no | Bottom row panel width ratio (default `[0.64, 0.36]` for `hero-2x2`) |
| `panel_weights` | `number[]` | no | Relative widths for single-row layout (forces `"row"` when `layout="auto"`) |
| `panel_links` | `array` | no | `[{"from":"P1","to":"P2","label":"tests"}]` — supports horizontal & top→bottom links |
| `panels` | `array` | yes | 1–8 panels labeled A, B, C, … |
| `sources` | string | yes | Provenance line rendered in footer (paper/dataset/DOI) |
| `version` | string | no | Footer right tag, e.g. `"GA-Skill v12 · <case_id>"` |

## Panel fields

| field | type | notes |
|---|---|---|
| `id` | string | Unique id referenced by `panel_links` (e.g. `"P1"`) |
| `role` | string | `question` (blue) / `method` (green) / `mechanism` (teal) / `results` (orange) / `conclusion` (purple) / `neutral` (slate) |
| `title` | string | Concise panel header (auto-fit) |
| `icon` | string | Optional scientific header icon from `gaicons.py` (see icon list below) |
| `source` | string | Optional provenance citation (auto-populated into `result.json` `source_map`) |
| `blocks` | array | Vertically stacked content blocks |

## Block types

### 1. `text` — structured bullets
```json
{"type": "text", "heading": "Optional subheading", "items": ["Point 1", "Point 2"]}
```

### 2. `callout` — visual highlight card with icon
```json
{"type": "callout", "icon": "target", "title": "Core hypothesis",
 "body": "Isolated active sites steer intermediate geometry.", "color": "#0072B2"}
```

### 3. `kpi` — zero-truncation metric cards
```json
{"type": "kpi", "layout": "row", "items": [
  {"value": "-78%", "label": "tumor viability vs vehicle (n=6)"},
  {"value": "4.2", "label": "mean DAR across batches"}
]}
```
Omit `"layout": "row"` for vertical stack.

### 4. `flow` — numbered experimental workflow
```json
{"type": "flow", "numbered": true, "fill": false, "steps": [
  {"text": "Screen 42 candidates by SPR", "sub": "KD < 5 nM cutoff", "icon": "flask"},
  {"text": "Validate in organoids & xenografts", "icon": "organoid"}
]}
```
Plain strings are also accepted in `steps`. Use `"fill": true` ONLY when `flow` is the sole block in its panel.

### 5. `mechanism` — compartment-aware scientific pathway/entity diagram
```json
{"type": "mechanism", "direction": "auto",
 "zones": [
   {"label": "Extracellular", "nodes": ["lig"], "color": "#E0F2FE", "stroke": "#38BDF8"},
   {"label": "Cytoplasm", "nodes": ["kin", "tf"], "color": "#ECFDF5", "stroke": "#34D399"}
 ],
 "nodes": [
   {"id": "lig", "label": "Ligand", "sub": "10 nM", "icon": "protein", "shape": "pill"},
   {"id": "kin", "label": "Kinase X", "icon": "receptor"},
   {"id": "tf",  "label": "TF-alpha", "icon": "nucleus"}
 ],
 "edges": [
   {"from": "lig", "to": "kin", "label": "binds", "kind": "activate"},
   {"from": "kin", "to": "tf",  "label": "blocks", "kind": "inhibit"}
 ],
 "legend": [{"kind": "activate", "label": "Activation"}, {"kind": "inhibit", "label": "Inhibition"}]}
```
- `direction`: `"auto"` (LR when wide, TB when narrow) | `"LR"` | `"TB"`.
- `kind`: `"activate"` (arrow) | `"inhibit"` (red T-bar) | `"bidirectional"` | `"dashed"`.
- Omit `nx`/`ny` for automatic collision-free layered layout (recommended); if all nodes specify `nx`/`ny` ∈ `[0, 1]`, collision protection automatically nudges any colliding pairs.
- Each panel also accepts optional `"badge"` (e.g. `"a"`, `"b"`, `"c"`, `"d"` or `"3a"`, overriding default `A–H`) and role aliases (`background`→`question`, `workflow`/`protocol`→`method`, `pathway`/`schematic`→`mechanism`, `data`/`findings`→`results`, `summary`/`impact`→`conclusion`).
- Zones in `mechanism` render a crisp top-edge header pill and auto-style borders: `membrane`/`bilayer`/`膜` → double-line phospholipid bilayer; `nucleus`/`核` → double-dashed nuclear envelope; `mitochondria`/`organelle`/`vesicle` → double-rim organelle (or explicit `style`).
- Skip-edges spanning >1 topological level, backward feedback loops, and mutual pairs render as curved quadratic Bezier arcs clearing intermediate nodes and zone headers; automatic 1-pass barycenter ordering minimizes edge crossings.
- Optional `"title"` header and `"stages": ["1. Step A", "2. Step B", ...]` top stage ribbon supported inside `mechanism` block.
- Omit `height` to auto-fill available panel height (or specify px when stacking with other blocks).

### 6. `chart` — publication-grade quantitative chart (values MUST come from material)
Supported `kind`: `"bar"`, `"hbar"` (supports negative values + zero baseline), `"stacked"`, `"line"` (supports `"band": true` shaded SD/SEM or `ci_lo`/`ci_hi` 95% CI band, `"step": true` KM survival curve), `"dot"`, `"box"` (biological box-and-whisker with quartiles & replicate dots from `points`), `"scatter"` (supports `"xlog": true` / `"ylog": true` + `"connect": true` for log-scale IC50/EC50 dose-response curves, `err`, `reflines`, `trend`, `xmin`/`xmax`/`ymin`/`ymax`, collision-free point `labels`), `"heatmap"` (auto RdBu diverging when `vmin < 0 < vmax`). `bar`/`line`/`dot`/`box` also support `"ylog": true` (log10 titers/CFU/fold-change). All 1D/2D charts support explicit `ymin`/`ymax` overrides and auto-cap percentage/survival axes cleanly at `100` (never emitting 120%/125% ticks). Common aliases (e.g., `grouped_bar`, `boxplot`, `survival`, `volcano`) are auto-normalized.
All chart kinds support an optional bold `"title"` (ideal inside side-by-side `row` blocks), `"value_suffix"` (e.g. `"%"`, `"x"`), and `"note"`.
- **Standard (`bar`/`hbar`/`stacked`/`line`/`dot`)**:
  ```json
  {"type": "chart", "kind": "bar", "title": "a. Viability across models", "ylabel": "Viability (%)", "xlabel": "Model",
   "xlabels": ["Organoid", "Xenograft"], "value_labels": true, "value_suffix": "%",
   "series": [
     {"name": "Vehicle", "values": [96, 92], "err": [3, 4], "points": [[93, 96, 99], [88, 92, 96]]},
     {"name": "Treatment", "values": [22, 18], "err": [4, 3], "points": [[18, 22, 26], [15, 18, 21]]}
   ],
   "sig": [{"x1": 0, "s1": 0, "x2": 0, "s2": 1, "label": "p < 0.001", "y": 106}],
   "refline": {"value": 50, "label": "IC50"},
   "note": "Mean ± SD with individual replicates, n = 3 per group (source_data.xlsx)"}
  ```
  - Optional `"points": [[...], ...]` overlays deterministic jittered biological replicate dots on `bar` / `hbar`.
  - Optional `"s1"` / `"s2"` in `sig` snaps bracket endpoints to exact grouped series bars (omit for group-center inter-group brackets).
  - Optional `"band": true` on `line` draws a translucent shaded error ribbon around `values ± err`; `"step": true` + optional `"censored": [idx, ...]` renders Kaplan-Meier step survival curves; `"sig_points": [{"x": i, "label": "***"}]` annotates point-wise significance.
  - Omit `"y"` in `"sig"` for automatic collision-free stacked bracket placement above bars, error bars, replicate dots, and value labels.
- **Scatter (`kind: "scatter"`)**: `series: [{"name": "...", "x": [...], "y": [...], "labels": [...]}]`; supports `"xlog"`/`"ylog"`, `"connect": true` (dose-response curves), `"err"`, `"refline"` / `"reflines"` (horizontal `y` and/or vertical `x`), `"trend": true` (OLS linear fit + `R²`), and automatic 4-quadrant collision-free point labels.
- **Volcano (`kind: "volcano"`)**: accepts either pre-split `series` or flat `"x"` / `"y"` / `"labels"` (or `"points": [{"x": 2.4, "y": 4.2, "label": "GENE1"}]`) + optional `"fc_thresh"` (default `1.0`) and `"p_thresh"` (default `1.301` for `p = 0.05`); automatically partitions Up (`#D55E00`), Down (`#0072B2`), and NS (`#94A3B8`) with counts in legend and dashed cutoff lines.
- **Paired / Slope (`kind: "paired"` or `"slope"`)**: accepts `"pairs": [[pre, post], ...]` with `"xlabels": ["Pre", "Post"]`, or 2+ `"series": [{"name": "Ctrl", "values": [...]}, {"name": "Treated", "values": [...]}]`; connects matched donors/samples with translucent trajectories + bold group mean bars + optional `"sig"` brackets.
- **Heatmap (`kind: "heatmap"`)**: `rows`/`ylabels`, `cols`/`xlabels`, `values`: 2D matrix (`null` rendered as `—`), optional `vmin`/`vmax`/`unit`, and `"ramp": "auto"|"sequential"|"diverging"` (automatically switches to colorblind-safe RdBu diverging ramp when `vmin < 0 < vmax`).

### 7. `svg` — auto-scaled custom inline vector block
For bespoke domain schematics (anatomical cross-sections, microfluidic chips, protein domain maps, gels/blots) inside any multi-panel layout:
```json
{"type": "svg", "title": "Domain architecture", "viewBox": "0 0 360 120",
 "svg": "<rect x='10' y='40' width='120' height='36' rx='6' fill='#0072B2'/><text x='70' y='63' font-size='13' fill='#FFFFFF' text-anchor='middle'>Kinase</text>",
 "note": "Schematic adapted from Fig. 3a"}
```

### 8. `table` — compact auto-wrapped summary table
```json
{"type": "table", "title": "Cohort parameters", "headers": ["Arm", "Dose", "n", "Response"],
 "rows": [["Vehicle", "0", "6", "4%"], ["Combo", "10 mg/kg", "6", "82%"]],
 "col_weights": [0.28, 0.28, 0.14, 0.30], "highlight_row": 1}
```

### 8. `row` — horizontal multi-block split inside a wide panel
```json
{"type": "row", "weights": [0.58, 0.42], "blocks": [
  {"type": "chart", ...},
  {"type": "chart", ...}
]}
```

### 9. `scalebar` — imaging / microscopy scale bar
```json
{"type": "scalebar", "px": 90, "length": "20 μm", "align": "left"}
```

## Available scientific icons (`gaicons.py`)
`cell`, `nucleus`, `membrane`, `receptor`, `antibody`, `nanobody`, `drug` (capsule/inhibitor),
`dna`, `rna`, `protein`, `nanoparticle`, `vesicle`, `microbe`, `tumor`, `organoid`,
`mitochondria`, `molecule`, `catalyst`, `electrode`, `device`, `flask`,
`microscope`, `target`, `shield`, `tcell`, `mouse`, `patient`, `virus`,
`crispr`, `neuron`, `check`, `warning`.
