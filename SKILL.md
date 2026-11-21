---
name: "bio-pathway-figure"
description: "Turns biological mechanism/pathway material into auditable scientific figures inside the runtime container: deterministic engine builds layered editable SVG plus PNG/PDF exports with semantic arrow taxonomy, compartment & transmembrane layout, auto legend, data encoding, dual geometry audits, source-preserving SVG edit mode, and a contract-complete /app/output/result.json."
---

# Bio-Pathway Figure Skill — runtime execution card

Facts you run under: input `/input/case.json` (+ `task.md`, `artifacts/figure-workorder.json`,
material files; PDFs are read directly), work dir `/app/work`, deliverables in `/app/output`
including `result.json`. Budget: 64 requests / 900 s for 3 cases → **≤7 working steps per
case**; engine calls take seconds, so the budget is spent on reading + one render + one
inspection. Skill files live at `/skills/weekly-skill` (`SK=/skills/weekly-skill`; if the
path differs, locate with `ls /skills/*/scripts/make_figure.py`).

## Per-case loop (follow exactly; keep a running result.json from step 2 on)

1. **Read inputs (1 step).** `cat /input/case.json`; note `case_id` verbatim. Read
   `task.md` + workorder JSON; locate the material (md/txt/json; if PDF:
   `python3 -c "import fitz; d=fitz.open('<pdf>'); print(chr(10).join(p.get_text() for p in d))"`
   and cite page numbers). Decide draw-vs-edit (existing figure file given?).
2. **Contract first (1 step).** `mkdir -p /app/output /app/work &&
   python3 $SK/scripts/result_contract.py --init <case_id> /app/output/result.json`
   This skeleton now guarantees a valid partial deliverable exists no matter what.
3. **Write `/app/work/spec.json` (1 step).** Extract ONLY what the material states:
   entities (kinds: receptor/protein/gene/complex/metabolite/cell/dna), interactions with
   their verbs, compartments in biological order (exterior → membrane → cytosol →
   nucleus), direction, quantitative values, and per-element `source` citations
   (section/page/table). Schema & worked examples: `references/spec_schema.md`.
   Verb→arrow mapping: `references/arrow_semantics.md`. Uncertain relation →
   `"dashed":true`; never invent entities, edges or numbers.
4. **Render + self-audit (1 step).**
   `python3 $SK/scripts/make_figure.py --spec /app/work/spec.json --outdir /app/work/out --basename fig --dpi 300`
   Writes layered `fig.svg` (element ids `shape-*`/`label-*`/`edge-*`), `fig.png`,
   `fig.pdf`, `fig.checks.json` (geometry + `spec_warnings` + legend), `fig.summary.json`,
   and provenance draft `fig.content-map.json`. Pick the layout automatically (compact/
   regular/roomy). Optional spec `layout` flags: `auto_arc`, `tighten_bands`,
   `evidence_auto_style` (reported→dashed, weak→dotted).
5. **Inspect + enrich (1 step).** View `fig.png`. Fix layout problems in the spec
   (never hand-edit the SVG) and rerun step 4 if needed. Requirements: 0 violations,
   arrows anchored on node borders, no text overlap, compartments match the mechanism.
   Then merge `fig.content-map.json` into result.json `content_map` (enrich `relation`
   wording; every entry keeps a source citation).
6. **Edit cases** (existing SVG given): apply changes with
   `python3 $SK/scripts/edit_svg.py --svg <in.svg> --edits edits.json --out fig_v2.svg`
   (ops: replace_text / set_text_by_id / set_attr_by_id / add_text; namespace-prefix
   tolerant). It rewrites only matched fragments and emits `.edit-record.json` — ship it.
   Preview via `python3 $SK/scripts/render_preview.py fig_v2.svg -o fig_v2.png --width 2400`
   and audit via `check_figure.py`. For engine figures, prefer spec edits + rerun.
7. **Deliver + validate (1 step).** Copy `fig.svg/png/pdf` (+ edit record) to
   `/app/output`; finalize `result.json` (template in `references/checklist.md`;
   paste `fig.checks.json` into `compliance_checks.geometry`, add your visual-inspection
   line and export checks; list every material gap in `exceptions`). Validate:
   `python3 $SK/scripts/result_contract.py --check /app/output/result.json` — fix until
   no problems; `status:"partial"` with precise `exceptions` beats a wrong "ok".

Engine changes: run `python3 $SK/scripts/selftest.py` (6-figure suite, must print
`SELFTEST PASS`).

## Contract field map (exact names; extra keys allowed)
- `case_id` — verbatim from `/input/case.json`.
- `status` — ok | partial | failed (honest).
- `editable_source` — `{path, format:"svg", canvas_wh, layers_named:true}`.
- `export_artifact` — list of `{path, format, dpi}` for PNG + PDF (all files must exist).
- `content_map` — every element → `{element, kind, relation, source, notes}`; sources cite
  the case material (section/page/table). The draft comes from `fig.content-map.json`.
- `compliance_checks` — `{geometry, legend_consistency, export_checks, visual_inspection}`.
- `exceptions` — material gaps, ambiguous directions, conflicts; a partial figure lists
  exactly what is missing.

## Failure & fallback discipline (never stop, never fake)
- No matplotlib: engine falls back to cairosvg/rsvg-convert for PNG (reported in
  `export_checks`); PDF may be absent — say so.
- Scanned/image-only PDF (no text layer): state it in `exceptions`, then work from the
  workorder + any text files; never guess values from an unreadable source.
- Scripts missing: minimal hand-SVG template + export recipe in
  `references/layout_rules.md` (bottom); keep the same arrow/color/legend conventions.
- Material lacks direction/confidence: draw `dashed:true`, explain in caption+exceptions.
- Chart values: copy numbers verbatim from the material; cite the table/page in
  `y_note`/`source`; if no numbers exist, do not fabricate a chart — note it.
- Partial budget (running out of steps): finish result.json as `partial` with what exists.

References: `references/spec_schema.md`, `references/arrow_semantics.md`,
`references/layout_rules.md`, `references/checklist.md`.
