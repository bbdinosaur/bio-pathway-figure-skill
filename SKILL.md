---
name: "bio-pathway-figure"
description: "Source-bound 3-step biological mechanism, pathway & quantitative figure Skill (3-6 calls, <180s): Step 1 parses PDFs (28K excerpt + page_index + target/mechanism snippets), CSV/TSV/XLSX/DOCX/workorders & SVGs (layers/CSS/IDs) and saves fallback /app/output/result.json; Step 2 authors traceable spec.json/edits.json with per-element provenance (examples inlined); Step 3 runs run_case.py (0-violation layout, 14 edge glyphs, dual encoding, 9 charts, bio_lint, Inkscape SVG + 300 DPI PNG + TrueType PDF, byte-preserving SVG edits & quality-gated result.json) — zero PNG reads."
---

# Bio-Pathway Figure Skill — 3-Step Execution Card

Inputs: `/input/case.json`, `task.md`, `figure-workorder.json`, PDFs/tables/SVGs. Work: `/app/work`. Output: `/app/output/result.json` + deliverables.
**Discipline**: Target **3–6 calls (max 10)** (<900 s). **NEVER `read` binary `.png`/`.pdf` or `scripts/*.py`**; verify via `run_case.py` JSON (`valid`, `n_violations`, `pixel_ok`, `legend_ok`, `bio_issues`, `spec_warnings`, `data_fidelity`, `next_action`).

## Step 1 — Inspect ALL Inputs & Save Fallback `result.json` (1 call)
```bash
mkdir -p /app/work /app/output
SK=/skills/weekly-skill; [ -f "$SK/scripts/run_case.py" ] || SK=$(dirname "$(dirname "$(find /skills /app/skills -maxdepth 3 -name run_case.py 2>/dev/null | head -n1)")")
python3 "$SK/scripts/inspect_inputs.py" /input --init-output /app/output/result.json --dump-dir /app/work/extracted
```
Prints `action_hints` (`case_id`, `suggested_basenames`, `target_figure_table_refs`, `existing_svgs`, `data_tables`, `scanned_pdfs`, `suggested_command`), `task_md`, `workorders`, tables (stats + ≤25 rows), PDF `page_index`/`target_ref_snippets`/`figure_captions`/`text_excerpt` (28K protected), and SVG `layers`/`css_classes`/`texts`/`shape_ids`, **and saves fallback `result.json`**.
- If `truncated: true` and key Results/Figure pages lie beyond `text_excerpt`, slice them from `/app/work/extracted/<name>.txt` in **1 call** first.

## Step 2 — Author `/app/work/spec.json` (and/or `edits.json`) (1 call)
Use **ONLY verified `/input` facts** (zero fabrication) covering every requested entity, edge, compartment, encoding, and deliverable:
- **Biology**: italic genes (`kind:"gene"`), roman proteins; consistent species casing (`TP53` vs `Trp53`); old names in `alias` (in-node italic); complexes via `kind:"complex"` (+ `subunits`) or `groups`; compartments `exterior->membrane->cytosol->organelle->nucleus` (surface receptors in `membrane`; intracellular e.g. `ESR1`/`NLRP3`/`STING1` ok in cytosol/nucleus).
- **14 edges & dual encoding**: `inhibition`=T-bar `⊣`; `phosphorylation`/`ubiquitination`/`modification`=tip badge `P`/`Ub`/`M` + `mods:["P","Ub","Ac","GTP","Me","SUMO"]`; self-loops ok; missing direction=`undirected` (`○—○`); `"evidence":"inferred"|"indirect"|"reported"|"putative"` auto-dashes (`"weak"` auto-dots); `"weight"`+`width_map`, `"value"`+`data_map`, `"size_value"`+`size_map`.
- **Provenance**: Cite exact `"source"` (`"Paper Fig.3A"`, `"Table S1 r4"`, `"§2.3"`) on **every node, edge, group, datum, and map**.

**Minimal Mechanism `spec.json` (Example — full schema: `references/spec_schema.md`):**
```json
{
  "mode":"mechanism","title":"Example: RTK-MAPK signaling",
  "caption":"Solid: direct; dashed: inferred. Source: Ex PDF §2-3.",
  "compartments":[
    {"id":"ext","label":"Extracellular","kind":"exterior"},
    {"id":"mb","label":"Plasma membrane","kind":"membrane"},
    {"id":"cyt","label":"Cytosol","kind":"cytosol"},
    {"id":"nuc","label":"Nucleus","kind":"nucleus"}
  ],
  "groups":[{"id":"g1","label":"Core module","members":["RAF1","MAPK1"],"source":"Ex §2.1"}],
  "nodes":[
    {"id":"EGF","label":"EGF","kind":"protein","compartment":"ext","source":"Ex Fig.1"},
    {"id":"EGFR","label":"EGFR","alias":"ERBB1","kind":"receptor","compartment":"mb","mods":["P"],"source":"Ex Fig.1"},
    {"id":"RAF1","label":"RAF1","kind":"protein","compartment":"cyt","value":2.4,"source":"Ex T1"},
    {"id":"MAPK1","label":"MAPK1","kind":"protein","compartment":"cyt","mods":["P"],"value":4.1,"source":"Ex T1"},
    {"id":"MYC","label":"MYC","kind":"gene","compartment":"nuc","source":"Ex Fig.2"}
  ],
  "edges":[
    {"from":"EGF","to":"EGFR","type":"binding","source":"Ex Fig.1"},
    {"from":"EGFR","to":"RAF1","type":"activation","weight":0.9,"source":"Ex Fig.1"},
    {"from":"RAF1","to":"MAPK1","type":"phosphorylation","label":"pT/Y","weight":0.8,"source":"Ex §2.2"},
    {"from":"MAPK1","to":"MYC","type":"transcription","evidence":"inferred","source":"Ex §3.1"},
    {"from":"MAPK1","to":"EGFR","type":"inhibition","route":"feedback","source":"Ex §3.2"}
  ],
  "data_map":{"palette":"blues","min":0,"max":5,"caption":"log2FC (Ex T1)","source":"Ex T1"},
  "width_map":{"min":0.2,"max":1.0,"caption":"Confidence (Ex §2)","source":"Ex §2"}
}
```
- `kind`: `protein|receptor|gene|complex|metabolite|drug|process|cell|dna`. `type`: `activation|recruitment|inhibition|binding|phosphorylation|ubiquitination|modification|transport|translocation|expression|transcription|degradation|undirected` (+ `route:"direct"|"arc"|"feedback"`, `dashed`, `dotted`, `evidence`, `weight`).

**Chart (`from_table` OR inline) & Composite (Example):**
```json
{"mode":"chart","title":"Example volcano","chart":{"kind":"volcano","x_label":"log2FC","y_label":"-log10(padj)","x_thresh":1.0,"y_thresh":1.3,"label_top_n":10,"highlight_labels":["MYC"],"from_table":{"file":"/input/deg.csv","x_col":"log2fc","y_col":"padj","label_col":"gene"}}}
```
- `kind`: `bar` (`bars` or `from_table` mean±SD), `grouped_bar` (`categories`,`series`,`sig_brackets`, or `category_col`+`group_col`+`value_col`), `stacked_bar` (`normalize:true`), `hbar` (`+/-`), `line` (`series`,`vlines`), `scatter`/`volcano` & `dotplot` (auto `-log10` on `padj`/`fdr`), `heatmap` (`rows,cols,values`, `NA`), `box` (`groups`,`sig_brackets`).
- Composite: `{"mode":"composite","title":"...","layout":{"cols":2},"panels":[{"id":"A","span":2,"spec":{...}},{"id":"B","spec":{...}}]}`.

**Byte-Preserving SVG `edits.json` (Example):**
```json
[{"op":"replace_label","find":"Old","replace":"New"},{"op":"set_css_class_style","class":"cls-1","prop":"fill","value":"#e2f4ea"},{"op":"set_text_by_id","id":"label-X","text":"Updated"}]
```
- Ops: `set_text_by_id`, `replace_label`, `replace_text`, `set_attr_by_id`, `set_style_by_id`, `set_css_class_style`, `translate_by_id`, `hide_by_id`, `remove_by_id`, `add_text`, `add_shape`, `insert_in_layer`.

## Step 3 — One-Shot Render, 5-Layer Audit & Delivery (1 call)
```bash
python3 "$SK/scripts/run_case.py" --spec /app/work/spec.json --basename figure03 \
    [--spec2 /app/work/chart.json --basename2 fig_chart] [--edit-svg /input/existing.svg --edits /app/work/edits.json] \
    [--exceptions '[{"issue":"...","handling":"..."}]'] [--status partial]
# Standalone SVG edit:
python3 "$SK/scripts/run_case.py" --edit-svg /input/<existing.svg> --edits /app/work/edits.json --basename <name> --source-note "workorder revision"
```
`run_case.py` auto-heals layout, exports Inkscape SVG + 300 DPI PNG + TrueType PDF, runs 5-layer audits (`geometry`, `svg`, `pixel`, `bio_lint`, `legend`, `data_fidelity`, `traceability`), validates `result.json`, and prints `next_action`:
- `COMPLETE` → **FINISH** and report deliverables & citations.
- `REPAIR_REQUIRED`/`REPAIR_OPTIONAL` → fix flagged items once and re-run Step 3 (max 1–2 passes), then finish.

## Honesty & Fallbacks
- Missing direction / scanned PDF / conflicts: `type:"undirected"`; never fabricate; log in `--exceptions`, `--status partial`.
- Export chain: `matplotlib->cairosvg->rsvg-convert->resvg->pymupdf->inkscape->convert->SVG-only partial`. Without scripts: emit layered `<svg xmlns="http://www.w3.org/2000/svg">` (`layer-compartments|layer-edges|layer-nodes|layer-legend`), rasterize (or `status:"partial"`), write `/app/output/result.json` (`case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`).
- Docs: `references/{spec_schema,arrow_semantics,layout_rules,checklist}.md`, `examples/`. Test: `python3 "$SK/scripts/selftest.py"`.
