---
name: "bio-pathway-figure"
description: "Turns biological mechanism/pathway text material into auditable scientific figures: deterministic engine builds layered editable SVG plus PNG/PDF exports with semantic arrow taxonomy (activation/inhibition/binding/modification/transport), compartment & transmembrane layout, auto legend, data encoding, geometry self-check, source-preserving SVG edit mode, and contract-complete result.json."
---

# Bio-Pathway Figure Skill

Trigger: any task asking to draw / edit a biological mechanism diagram, pathway map,
signalling cascade, cell-compartment diagram, or data chart tied to such a figure.

Runtime facts: input `/input/case.json` (+ `artifacts/figure-workorder.json`, material
files, sometimes an existing SVG to edit); work in `/app/work`; deliver under `/app/output`
including `result.json` (fields: case_id, status, editable_source, export_artifact,
content_map, compliance_checks, exceptions). Budget 64 requests / 900 s for 3 cases —
spend ~6–8 per case. Python + matplotlib assumed; scripts use stdlib otherwise.

## Fast loop (do this, in order)

1. **Read inputs.** `/input/case.json`, `task.md`, workorder JSON, and the material
   (paper text/tables, or existing SVG). Extract: entities (kinds), interactions (verbs),
   compartments, directionality, quantitative data, provenance locations, and — for edit
   cases — exactly which labels/elements must change.
2. **Write `spec.json`** (schema: `references/spec_schema.md`; wording→arrow mapping:
   `references/arrow_semantics.md`; naming rules: `references/layout_rules.md`).
   Give EVERY node/edge a `source` string citing the material.
3. **Render + self-check in one step:**
   `python3 "$SK/scripts/make_figure.py" --spec spec.json --outdir /app/work/out --basename fig --dpi 300`
   (set `SK=/skills/weekly-skill`; if missing, locate via `ls /skills/*/scripts/make_figure.py`).
   It tries compact/regular/roomy layouts, picks the fewest-violation one, writes
   `fig.svg` (layered, named, editable), `fig.png`, `fig.pdf`, `fig.checks.json`,
   `fig.summary.json`, a provenance draft `fig.content-map.json` (element→source from your
   spec — enrich relations and paste into result.json), and prints the summary JSON.
4. **Look at `fig.png`** (image view). Fix layout problems in the spec — never hand-edit
   the SVG — then rerun step 3. Ship only with `n_violations: 0` or honest exceptions.
5. **Edit cases** (existing SVG given): apply changes with
   `python3 "$SK/scripts/edit_svg.py" --svg <in.svg> --edits edits.json --out fig_v2.svg`
   (ops: replace_text / set_text_by_id / set_attr_by_id / add_text). It only rewrites
   matched fragments (source-preserving) and emits `.edit-record.json` — include it in
   output. Then rasterize a preview and LOOK at it:
   `python3 "$SK/scripts/render_preview.py" fig_v2.svg -o fig_v2.png --width 2400`,
   re-check with `check_figure.py`. Engine-generated SVGs carry element ids
   (`shape-<NODE>`, `label-<NODE>`, `edge-<n>-<FROM>-<TO>`), so labels can be edited by id
   with set_text_by_id; for engine figures, prefer editing the spec and re-running step 3.
6. **Deliver.** Copy final `fig.svg/png/pdf` (+ edit record) to `/app/output`, write
   `result.json` exactly as the template in `references/checklist.md`, then validate:
   `python3 "$SK/scripts/result_contract.py" --check /app/output/result.json` (exit 0).

## Contract mapping
- `editable_source` → the layered SVG (path + format + canvas).
- `export_artifact` → list of PNG/PDF entries with dpi (from summary.json).
- `content_map` → element-by-element provenance: build from the `source` fields in your
  spec (nodes first, then edges, then legend/data_map claims).
- `compliance_checks` → paste `fig.checks.json` (geometry), legend note, export file checks,
  and one line on your PNG visual inspection.
- `exceptions` → material gaps, ambiguous directions, conflicts, partial coverage.

## Fallbacks (never stop the loop)
- No matplotlib: the engine falls back to cairosvg/rsvg-convert for PNG and reports the
  path used; PDF may be absent — say so in `compliance_checks.export_checks`.
- No scripts at all: minimal hand-written SVG template + manual export recipe are in
  `references/layout_rules.md` (bottom). Keep the same arrow/color/legend conventions.
- Material lacks direction/confidence: draw `dashed:true` + `type:"other"`, explain in
  caption + exceptions. Never invent entities, edges, numbers or citations.

## Design guarantees (why results stay consistent)
- One geometry model drives SVG and PNG/PDF, so exports match the editable source.
- Legends are generated from the styles actually used — legend can never contradict the map.
- Edge endpoints are computed on node borders; `check_figure.py` re-audits the delivered
  SVG bytes independently (bounds, overlaps, legend presence).
- Deterministic layout (same spec → same figure): reruns are stable for reviewers.

References: `references/spec_schema.md`, `references/arrow_semantics.md`,
`references/layout_rules.md` (incl. naming + no-script fallback), `references/checklist.md`
(result.json template, honesty rules, budget discipline).
