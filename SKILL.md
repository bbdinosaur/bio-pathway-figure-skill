---
name: "bio-pathway-figure"
description: "Source-bound 3-step bio mechanism/pathway & chart figure Skill (3-6 calls, <180s): Step 1 inspects PDFs (28K excerpt, EN/ZH page_index/snippets), CSV/TSV/XLSX/DOCX/workorders & SVGs (layers/CSS/IDs) and writes fallback /app/output/result.json; Step 2 authors traceable spec.json/edits.json; Step 3 runs run_case.py (0-violation layout, 14 edge glyphs, triple encoding, 9 charts, bio_lint, Inkscape SVG + 300 DPI PNG + TrueType PDF, byte-preserving SVG edits & audited result.json) - zero PNG reads."
---

# Bio-Pathway Figure - 3-Step Execution Card
Inputs: `/input/case.json`, `task.md`, `figure-workorder.json`, PDFs/tables/SVGs. Work: `/app/work`. Output: `/app/output/result.json` + deliverables.
**Discipline**: Target **3-6 calls (max 10)** (<900s). **NEVER `read` binary `.png`/`.pdf` or `scripts/*.py`**; verify via `run_case.py` JSON (`valid`, `n_violations`, `pixel_ok`, `legend_ok`, `bio_issues`, `spec_warnings`, `data_fidelity`, `next_action`).

## Step 1 - Inspect ALL Inputs & Save Fallback `result.json` (1 call)
```bash
mkdir -p /app/work /app/output
SK=/skills/weekly-skill; [ -f "$SK/scripts/run_case.py" ] || SK=$(dirname "$(dirname "$(find /skills /app/skills -maxdepth 3 -name run_case.py 2>/dev/null | head -n1)")")
python3 "$SK/scripts/inspect_inputs.py" /input --init-output /app/output/result.json --dump-dir /app/work/extracted
```
Outputs `action_hints` (`case_id`, `suggested_basenames`, `target_figure_table_refs`, `existing_svgs`, `data_tables`, `scanned_pdfs`, `suggested_command`), `task_md`, `workorders`, tables (<=70 rows+stats), PDF `page_index`/`target_figure_captions`/`target_ref_snippets`/`figure_captions`/`text_excerpt` (pre-References), SVG `layers`/`css_classes`/`texts`/`shape_ids`, **plus fallback `result.json`**.
- If `truncated: true`, slice `/app/work/extracted/<name>.txt` (or use `from_table`) in **1 call**.

## Step 2 - Author `/app/work/spec.json` (and/or `edits.json`) (1 call)
Use **ONLY verified `/input` facts** (no fabrication) covering every requested entity, edge, compartment, encoding & deliverable:
- **Biology**: italic genes (`kind:"gene"`), roman proteins; species casing (`TP53` vs `Trp53`); old names in `alias` (italic); complexes via `kind:"complex"` (+`subunits`) or `groups`; compartments `exterior->membrane->cytosol->organelle->nucleus` (surface receptors in `membrane`; intracellular `ESR1`/`NLRP3`/`STING1` ok in cytosol/nucleus).
- **14 edges & dual encoding**: `inhibition`=T-bar `⊣`; `phosphorylation`/`ubiquitination`/`modification`=tip badge `P`/`Ub`/`M` + `mods:["P","Ub","Ac","GTP","Me","SUMO"]`; self-loops ok; missing direction=`undirected` (`○—○`); `"evidence":"inferred"|"indirect"|"reported"|"putative"` auto-dashes (`"weak"` auto-dots); `"weight"`+`width_map`, `"value"`+`data_map`, `"size_value"`+`size_map`.
- **Provenance**: Cite `"source"` (`"Paper Fig.3A"`, `"Table S1 r4"`, `"§2.3"`) on **every node, edge, group, datum & map**.

**Minimal Mechanism `spec.json` (schema: `references/spec_schema.md`):**
```json
{
 "mode":"mechanism","title":"RTK-MAPK signaling",
 "caption":"Solid: direct; dashed: inferred. Source: PDF §2-3.",
 "compartments":[
  {"id":"ext","label":"Extracellular","kind":"exterior"},
  {"id":"mb","label":"Membrane","kind":"membrane"},
  {"id":"cyt","label":"Cytosol","kind":"cytosol"},
  {"id":"nuc","label":"Nucleus","kind":"nucleus"}],
 "groups":[{"id":"g1","label":"Core","members":["RAF1","MAPK1"],"source":"§2.1"}],
 "nodes":[
  {"id":"EGF","label":"EGF","kind":"protein","compartment":"ext","source":"Fig.1"},
  {"id":"EGFR","label":"EGFR","alias":"ERBB1","kind":"receptor","compartment":"mb","mods":["P"],"source":"Fig.1"},
  {"id":"RAF1","label":"RAF1","kind":"protein","compartment":"cyt","value":2.4,"source":"T1"},
  {"id":"MAPK1","label":"MAPK1","kind":"protein","compartment":"cyt","mods":["P"],"value":4.1,"source":"T1"},
  {"id":"MYC","label":"MYC","kind":"gene","compartment":"nuc","source":"Fig.2"}],
 "edges":[
  {"from":"EGF","to":"EGFR","type":"binding","source":"Fig.1"},
  {"from":"EGFR","to":"RAF1","type":"activation","weight":0.9,"source":"Fig.1"},
  {"from":"RAF1","to":"MAPK1","type":"phosphorylation","label":"pT/Y","weight":0.8,"source":"§2.2"},
  {"from":"MAPK1","to":"MYC","type":"transcription","evidence":"inferred","source":"§3.1"},
  {"from":"MAPK1","to":"EGFR","type":"inhibition","route":"feedback","source":"§3.2"}],
 "data_map":{"palette":"blues","min":0,"max":5,"caption":"log2FC (T1)","source":"T1"},
 "width_map":{"min":0.2,"max":1.0,"caption":"Confidence (§2)","source":"§2"}
}
```
- `kind`: `protein|receptor|gene|complex|metabolite|drug|process|cell|dna`. `type`: `activation|recruitment|inhibition|binding|phosphorylation|ubiquitination|modification|transport|translocation|expression|transcription|degradation|undirected` (+ `route:"direct"|"arc"|"feedback"`, `dashed`, `dotted`, `evidence`, `weight`).

**Chart (`from_table` OR inline) & Composite:**
```json
{"mode":"chart","title":"Volcano","chart":{"kind":"volcano","x_label":"log2FC","y_label":"-log10(padj)","x_thresh":1.0,"y_thresh":1.3,"label_top_n":10,"highlight_labels":["MYC"],"from_table":{"file":"/input/deg.csv","x_col":"log2fc","y_col":"padj","label_col":"gene"}}}
```
- `kind`: `bar` (`bars`/`sig` or `from_table` mean±SD), `grouped_bar`, `stacked_bar` (`normalize:true`), `hbar` (`+/-`), `line` (`series`,`vlines`), `scatter`/`volcano` & `dotplot` (auto `-log10` on `padj`/`fdr`), `heatmap` (`rdbu`/`fold`/`blues`/`viridis`, `NA`), `box` (`groups`,`sig_brackets`).
- Composite: `{"mode":"composite","title":"...","layout":{"cols":2},"panels":[{"id":"A","title":"...","span":2,"spec":{...}},{"id":"B","spec":{...}}]}`.

**Byte-Preserving SVG `edits.json`:**
```json
[{"op":"replace_label","find":"Old","replace":"New"},{"op":"set_css_class_style","class":"cls-1","prop":"fill","value":"#e2f4ea"},{"op":"set_text_by_id","id":"label-X","text":"Updated"}]
```
- Ops: `set_text_by_id`, `replace_label`, `replace_text`, `set_attr_by_id`, `set_style_by_id`, `set_css_class_style`, `translate_by_id`, `hide_by_id`, `remove_by_id`, `add_text`, `add_shape`, `insert_in_layer`.

## Step 3 - One-Shot Render, 5-Layer Audit & Delivery (1 call)
```bash
python3 "$SK/scripts/run_case.py" --spec /app/work/spec.json --basename figure03 \
  [--spec2 /app/work/chart.json --basename2 fig_chart] [--edit-svg /input/existing.svg --edits /app/work/edits.json] \
  [--exceptions '[{"issue":"...","handling":"..."}]'] [--status partial]
# Standalone SVG edit:
python3 "$SK/scripts/run_case.py" --edit-svg /input/<existing.svg> --edits /app/work/edits.json --basename <name> --source-note "workorder revision"
```
Auto-reads `/input/case.json`, heals layout, exports Inkscape SVG + 300 DPI PNG + TrueType PDF, runs 5-layer audits (`geometry`, `svg`, `pixel`, `bio_lint`, `legend`, `data_fidelity`, `traceability`), validates `result.json`, prints `next_action`:
- `COMPLETE`: **FINISH** & report deliverables/citations.
- `REPAIR_REQUIRED`: fix flagged items (`bio_issues`, `not_found_details.suggestions`, `unmatched_sample`, `problems`) & re-run Step 3 once.

## Honesty & Fallbacks
- Missing direction / scanned PDF / conflicts: `type:"undirected"`; never fabricate; log in `--exceptions`, `--status partial`.
- Export chain: `matplotlib->cairosvg->rsvg-convert->resvg->pymupdf->inkscape->convert->SVG-only partial`. Without scripts: emit layered `<svg xmlns="http://www.w3.org/2000/svg">` (`layer-compartments|layer-edges|layer-nodes|layer-legend`), rasterize (or `status:"partial"`), write `/app/output/result.json` (`case_id, status, editable_source, export_artifact, content_map, compliance_checks, exceptions`).
- Docs: `references/{spec_schema,arrow_semantics,layout_rules,checklist}.md`, `examples/`. Test: `python3 "$SK/scripts/selftest.py"`.
