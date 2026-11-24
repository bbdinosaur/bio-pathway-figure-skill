# Bio-Pathway Figure Skill (`bio-pathway-figure`)

A deterministic, source-bound scientific diagram and quantitative figure Skill for biological mechanism and pathway illustration. Compiles a traceable JSON specification into layered editable SVG (Inkscape/Illustrator-ready `<g id="layer-...">` groups and semantic element IDs) alongside synchronized 300 DPI PNG, TrueType-embedded PDF, and lightweight 100 DPI inspection previews.

## Capabilities
- **Biological Mechanism Diagrams (`mode: "mechanism"`)**: Physiological compartment bands (`exterior` → `membrane` with lipid bilayer & crisp label pill → `cytosol` → `organelle` with mitochondria/lysosome/ER accents → `nucleus` with dashed nuclear envelope) plus dynamic 2-line title safe zones, transmembrane receptor domain-cap accents, complex `subunits` pills, subtle node & legend shadows, smooth rounded orthogonal connectors, obstacle-aware side/top autophosphorylation self-loops (`from == to`), monotonic barycenter crossing-minimizing layout, 11 distinct node kinds, 6 PTM corner badges (`P`, `Ub`, `Ac`, `GTP`, `Me`, `SUMO`) with exact multi-char pill avoidance, dashed complex/module enclosures (`groups`) with auto-fit labels and SVG provenance, obstacle-free outer-rail cross-compartment feedback routing, symmetric border-anchored bidirectional/parallel edges, and continuous `data_map` / `width_map` / `size_map` encodings with auto-wrapped legend captions and WCAG contrast text.
- **14 Visually Distinct Interaction Types**: Unique color + endpoint glyph (+ optional start glyph) for `activation`, `recruitment`, `inhibition` (T-bar), `binding` (double diamond), `phosphorylation` (`P` badge circle), `ubiquitination` (`Ub` badge circle), `modification` (`M` badge circle), `transport`, `translocation`, `expression`, `transcription` (promoter bar + open arrow), `degradation` (dashed cross), `undirected` (dashed hollow circles for missing-direction associations), and `other`, plus dashed/dotted uncertainty encoding.
- **Inkscape-Native Layered Editable SVG (`viz_svg.py`)**: Emits `inkscape:groupmode="layer"` / `inkscape:label` groups (`layer-backdrop`, `layer-compartments`, `layer-groups`, `layer-edges`, `layer-nodes`, `layer-annotations`, `layer-legend`, `layer-chrome`) and embeds `data-source`, `data-kind`, `data-compartment`, `data-edge-type`, `data-evidence`, `data-value`, and `data-weight` provenance directly on vector elements.
- **Full-Width Spanning Multi-Panel Composites (`build.py`) & Self-Healing Layout (`make_figure.py`)**: Supports Nature-style `span: 2` full-width mechanism panels above side-by-side quantitative panels, automatic multi-strategy layout fallback (`preserve_order` / `auto_tier=False`) guaranteeing 0 geometric violations, obstacle-aware above/below arcs, and default evidence-uncertainty auto-dashing synced with the legend.
- **Honest `NA` Heatmaps, Replicate Auto-Aggregation, Auto-`-log10(padj)` Volcano/Dotplot & PDF-Protected Step 1 (`chart.py`, `inspect_inputs.py`, `edit_svg.py`, `bio_lint.py`)**: Renders missing heatmap cells cleanly as soft gray `NA` (zero dropped rows) with automatic numeric `value_cols` detection for wide matrix CSVs, auto-aggregates biological replicates in `from_table` (`mean ± SD` / `mean ± SEM` / `median` + replicate dots), auto-transforms raw `padj`/`FDR` columns via `-log10(p)` in `volcano` and enrichment `dotplot` charts with priority-first `highlight_labels` gene pinning, adds right-edge-safe `vlines` perturbation markers on time-course line charts, verifies gene-vs-protein homonym disambiguation and `data_map` range consistency in `bio_lint.py`, protects full 28 KB PDF paper text + expanded target Figure/Table captions and `mechanism_section_snippets` inside a 48 KB Step 1 summary (trimming raw table rows before ever touching PDF text while retaining column stats & categorical previews), and verifies XML + layer preservation (`layers_preserved`) with depth-safe nested-`<g>` `remove_by_id` and XML-safe entity/cross-`<tspan>` SVG edits.
- **9 Quantitative Chart Types (`mode: "chart"`) + Direct Wide & Long-Format CSV/TSV/XLSX `from_table` Binding**: Unified layered-SVG + PNG/PDF engine for `bar`, `grouped_bar` (with `sig_brackets`), `stacked_bar` (raw or 100% composition), `hbar` (positive and diverging `+/-` NES/log2FC), `line` (numeric or categorical/timepoint X axes + translucent SD confidence ribbons), `scatter`/`volcano` (auto-threshold Up/Down/NS classification with counts + dense-omics `label_top_n` cap & `dot_boxes`-aware 28-offset label avoidance), `heatmap`, `dotplot` (pathway enrichment bubble plot), and `box` (Q1/median/Q3 box-and-whisker + replicate strip + significance brackets), with automatic multi-row wrapping top legends, wide/long-format CSV/TSV/XLSX `from_table` auto-pivoting, and multi-source (tables + PDFs) `data_fidelity` auditing.
- **Composite Multi-Panel Figures (`mode: "composite"`)**: Arranges mechanism and chart panels on a global white canvas with bold `A`/`B`/`C` badges and structured `<g id="panel-A" transform="translate(...)">` SVG groups.
- **One-Shot Input Inspection, 5-Layer Auditing & Byte-Preserving SVG Editing**: Unified input inspector (`inspect_inputs.py` for PDFs with beyond-cutoff Figure/Table snippets, CSV/TSV/XLSX tables with numeric stats, workorders, and SVGs with element coordinates + `action_hints`), IR geometry + `edge_through_node` checker (`viz_check.py`), unit/namespace-hardened raw-SVG + PNG pixel auditor (`check_figure.py`), automatic CSV/TSV/XLSX `data_fidelity` cross-checker, standalone OR paired byte-preserving SVG editor (`edit_svg.py`), and contract validator (`result_contract.py`).

## Directory Structure
- `SKILL.md` — Concise 3-step scientific execution card (≤8.0 KB) with inlined per-element provenance examples, quality-gated `next_action`, and zero binary PNG reads.
- `scripts/` — Pure Python stdlib core engine (`inspect_inputs.py`, `bio_lint.py`, `viz_style.py`, `viz_geom.py`, `viz_layout.py`, `viz_nodes.py`, `viz_edges.py`, `viz_legend.py`, `viz_svg.py`, `build.py`, `chart.py`, `make_figure.py`, `run_case.py`, `edit_svg.py`, `check_figure.py`, `viz_check.py`, `render_preview.py`, `result_contract.py`, `selftest.py`).
- `references/` — Detailed schema (`spec_schema.md`), 14-glyph interaction & node semantics (`arrow_semantics.md`), naming/layout/no-script fallback rules (`layout_rules.md`), and output contract checklist (`checklist.md`).
- `examples/` — Minimal runnable synthetic examples (`minimal_mechanism_spec.json`, `minimal_composite_spec.json`, `minimal_svg_edits.json`) and clearly labeled illustrative contract output (`example_result_output.json`).

## Why This Architecture Outperforms Raw-SVG Agent Authoring (Innovation Summary)
- **Single-IR Dual-Backend Parity**: One layout primitive list emits both Inkscape-layered editable SVG (`data-source`/`data-kind`/`data-edge-type`) and synchronized true-300 DPI PNG + TrueType-embedded PDF (`pdf.fonttype=42`), eliminating SVG-vs-PNG drift and hand-coded coordinate errors.
- **Automated Biological & Geometric Verification**: Combines `bio_lint.py` (~210 HGNC aliases, gene-vs-protein homonym checks, intracellular vs plasma-membrane receptor localization, species-casing & range checks), IR `edge_through_node` + obstacle-aware routing, machine-verified `legend_consistency`, quantitative `data_fidelity` auditing (separating chart/expression numbers from qualitative edge weights), and decoupled `delivery_integrity` status gating.
- **Byte-Preserving SVG Revision**: Edits existing Inkscape/Illustrator SVGs in place (`>99%` untouched-line preservation verified in `selftest.py`) across XML entities, `<tspan>`, and CSS `<style>` classes without rebuilding or destroying layers.

## Requirements & Fallbacks
- **Core engine**: Python 3.8+ standard library only (SVG generation, `bio_lint`, raw-SVG auditing, byte-preserving SVG editing, and `result.json` validation require zero external packages).
- **Raster/PDF export**: `matplotlib` (preferred; embeds editable TrueType fonts in PDF via `pdf.fonttype=42` at true 300 DPI), with automatic fallback chain `cairosvg -> pymupdf (fitz) -> rsvg-convert -> inkscape`.
- **PDF & Excel inspection**: `pymupdf` (`fitz`) → `pdfplumber` → `pypdf` → `pdftotext` for PDFs; `openpyxl` → `pandas` → stdlib `zipfile` for `.xlsx`.

## Minimal Usage Example (Illustrative Synthetic Example Only)
```bash
# 1. Run built-in 13-fixture regression self-test (11 renders + SVG edit + bio_lint)
python3 scripts/selftest.py

# 2. Inspect a case directory and initialize a fallback result.json
python3 scripts/inspect_inputs.py /input \
    --init-output /app/output/result.json --dump-dir /app/work/extracted

# 3. One-shot draw + 5-layer audit + contract validation using the synthetic example
python3 scripts/run_case.py --case-id EXAMPLE-SYNTHETIC-01 --no-case-json \
    --spec examples/minimal_mechanism_spec.json --basename example_fig \
    --workdir /tmp/example_work --output-dir /tmp/example_out --dpi 300
# See examples/example_result_output.json for the illustrative result.json schema output.

# 4. Standalone source-preserving edit on an existing SVG (untouched bytes stay identical)
python3 scripts/run_case.py --case-id EXAMPLE-SYNTHETIC-02 --no-case-json \
    --edit-svg /tmp/example_out/example_fig.svg \
    --edits examples/minimal_svg_edits.json --basename example_fig_rev \
    --workdir /tmp/example_work --output-dir /tmp/example_out --dpi 300
```

## Biological Design Conventions & Troubleshooting
- **Entity disambiguation**: Italicize gene symbols (`kind: "gene"`) and keep proteins roman (`kind: "protein"`); avoid mixing human ALL-CAPS (`TP53`) and mouse Title-case (`Trp53`) unless multi-species is explicitly labeled; place legacy names in `alias` rather than duplicating nodes.
- **Missing directionality & conflicts**: Represent correlative or direction-unknown edges with `type: "undirected"` (never invent an arrowhead); when sources disagree, draw both edges with citations and record the conflict in `exceptions`.
- **Overcrowded pathways**: If `bio_lint` flags `>18` nodes or `>26` edges in one panel, collapse functional complexes via `groups` or split into a multi-panel `composite` figure.

## Scope, Limitations & Maintenance
- Designed for biological mechanism/pathway diagrams, source-bound quantitative charts, and source-preserving SVG revisions.
- Does not perform statistical hypothesis testing, 3D structural modeling, or OCR on image-only scanned PDFs without a text layer (flagged in `scanned_warning` and `exceptions` with `status: "partial"`).
- Every biological entity, interaction, modification, and data value must originate from verified input materials; missing facts are never fabricated.
- Maintained as a self-contained, dependency-minimal Skill package verified by `scripts/selftest.py`.
