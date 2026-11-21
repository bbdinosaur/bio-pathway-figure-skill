# Pre-submit checklist & result.json template

## Multiple deliverables in one case
If the workorder asks for a mechanism figure AND data panels, render each with its own
`--spec`/`--basename` (fig03, fig_chart, ...). Put the main mechanism SVG in
`editable_source` and list every export under `export_artifact`; cover all figures in
one `content_map` (prefix element names with the basename).

## Before finishing a case, ALL of these must hold
1. `check_figure.py <out>.svg` → `n_violations: 0` (or violations listed in exceptions with reason).
2. You visually inspected the PNG: no text overlap, no clipped/overflowing elements,
   arrows attach to node borders, compartment positions match the mechanism.
3. Every edge type used appears in the legend (automatic — verify legend rendered).
4. Every node/edge in spec carries a `source` string pointing into the case material.
5. Direction sanity pass: upstream→downstream, receptor in membrane, feedback routed
   around, dashed = uncertainty. Wrong topology = wrong scientific claim.
6. Exports exist: `.svg` (editable source) + `.png` + `.pdf` at requested dpi.
7. If the case asked to EDIT an existing SVG: `edit_svg.py` produced `.edit-record.json`
   with before/after for every change; untouched regions byte-identical.

## result.json (exact fields, plus case_id)
```json
{
  "case_id": "<from /input/case.json>",
  "status": "ok | partial | failed",
  "editable_source": {"path": "/app/work/fig.svg", "format": "svg",
                      "canvas_wh": [1300, 850], "layers_named": true},
  "export_artifact": [
    {"path": "/app/output/fig.png", "format": "png", "dpi": 300},
    {"path": "/app/output/fig.pdf", "format": "pdf", "dpi": 300}
  ],
  "content_map": [
    {"element": "EGFR", "kind": "node", "relation": "receptor in membrane",
     "source": "case material §3.1 p4", "notes": "spans membrane band"},
    {"element": "RAF1->MAP2K1", "kind": "edge", "relation": "phosphorylation P-S218/S222",
     "source": "case material §3.3 fig4B"}
  ],
  "compliance_checks": {
    "geometry": {"n_violations": 0, "tool": "check_figure.py", "scale": "regular"},
    "legend_consistency": "auto-generated from used styles; verified visually",
    "export_checks": [{"file": "fig.png", "format": "png", "dpi": 300, "ok": true}],
    "visual_inspection": "inspected PNG: no overlap/clipping; arrows attach on borders"
  },
  "exceptions": [
    {"issue": "interaction X described without direction in material",
     "handling": "drawn dashed as other-type; not invented"}
  ]
}
```
Validate before finishing: `python3 result_contract.py --check /app/output/result.json`
(exit 0 = structurally valid + referenced files exist).

## Honesty rules
- Never fabricate: entities, edges, numbers, IDs, page/section numbers, or "verified" claims.
- `status:"partial"` + precise `exceptions` is always better than a confident wrong figure.
- If material contradicts itself, draw the version you can cite and record the conflict.
- Do not claim benchmark scores or compare against hidden whiteboards.

## Budget discipline (64 requests / 900 s / 16384 tok per response)
- ~6–8 requests per case: read material (1–2) → write spec (1) → run engine (1) →
  inspect PNG (1) → fix+rerun (0–2) → result.json (1).
- If the first render has violations, fix the spec (data model) — do not hand-edit SVG.
