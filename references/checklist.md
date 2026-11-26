# Pre-Submit Checklist, Edit Ops & Output Contract Template

## Multiple Deliverables in One Case
When a workorder requests BOTH a mechanism diagram and quantitative chart(s), either:
- Combine them into a single multi-panel figure (`"mode": "composite"`), OR
- Pass `--spec mech.json --spec2 chart.json --basename2 fig_chart` (or repeatable `--extra name:spec.json`)
  to `run_case.py` — all SVG/PNG/PDF exports and prefixed `content_map` entries are assembled automatically.

## Source-Preserving SVG Edit Ops (`edit_svg.py` / `run_case.py --edit-svg`)
Only matched fragments change; all untouched SVG bytes remain byte-identical. Supported ops:
- `{"op": "set_text_by_id", "id": "label-EGFR", "text": "EGFR (ERBB1)"}` (preserves `<tspan>`)
- `{"op": "set_style_by_id", "id": "shape-EGFR", "prop": "fill", "value": "#fef3c7"}` (CSS `style` or XML attr)
- `{"op": "set_css_class_style", "class": "cls-1", "prop": "fill", "value": "#e2f4ea"}` (updates `<style>` CSS class rule in place)
- `{"op": "set_attr_by_id", "id": "shape-EGFR", "attr": "stroke-width", "value": "2.4"}`
- `{"op": "translate_by_id", "id": "label-EGFR", "dx": 10, "dy": -5}`
- `{"op": "hide_by_id", "id": "badge-1"}` / `{"op": "remove_by_id", "id": "badge-1"}`
- `{"op": "replace_label", "find": "OldName", "replace": "NewName", "all": false}` (`<text>`/`<tspan>` leaf nodes first, XML-entity & multi-line aware)
- `{"op": "replace_text", "find": "raw", "replace": "new", "all": false}`
- `{"op": "add_text", "x": 40, "y": 24, "text": "Note", "size": 12, "weight": "bold", "italic": true, "id": "note-1", "layer_id": "layer-annotations"}`
- `{"op": "add_shape", "shape": "arrow|tbar|rect|circle|ellipse|line|polyline", "x1": 100, "y1": 50, "x2": 160, "y2": 50, "stroke": "#dc2626", "dashed": true, "id": "rev-1", "layer_id": "layer-edges"}`
- `{"op": "insert_in_layer", "layer_id": "layer-annotations", "svg": "<circle .../>"}`

Every run emits `<out>.edit-record.json` with `before`/`after` values, `SequenceMatcher` `preservation.unchanged_line_ratio`, and `layers_preserved`.

## Pre-Finish Gate (ALL must hold)
1. Triple audit passes: IR geometry + `edge_through_node` (`n_violations: 0`), raw-SVG audit (`svg_audit.n_violations: 0`), and real PNG `pixel_audit.ok: true` (heuristic advisories remain non-fatal with `status: "ok"` once valid SVG/PNG/PDF and required contract fields exist, and are recorded honestly in `compliance_checks` and `exceptions`/`exceptions_and_limitations`; only missing/corrupted core exports or critical spec parse errors set `status: "partial"`/`"failed"`).
2. In text-only runtimes, do NOT read binary PNGs; verify `run_case.py`'s automated `pixel_audit` + `visual_inspection` summary. (When vision is available locally, also inspect `<basename>.preview.png`.)
3. Every node, edge, group, and chart data series in `content_map` cites its exact source location.
4. Editable `.svg` + `.png` (300 DPI) + `.pdf` + `.edit-record.json` exist inside `/app/output/` and pass magic-byte checks.
5. `run_case.py` reports `valid: true`, `problems: []`, and zero placeholder warnings.

## Example `/app/output/result.json` (Illustrative Format Example Only)
```json
{
  "case_id": "EXAMPLE-CASE-01",
  "status": "ok",
  "editable_source": {
    "path": "/app/output/fig.svg",
    "format": "svg",
    "canvas_wh": [1420, 720],
    "layers_named": true
  },
  "export_artifact": [
    {"path": "/app/output/fig.png", "format": "png", "dpi": 300},
    {"path": "/app/output/fig.pdf", "format": "pdf", "dpi": 300}
  ],
  "content_map": [
    {"element": "EGFR", "kind": "node", "relation": "receptor in mb; mods=P",
     "source": "Materials §3.1 p.4"},
    {"element": "RAF1->MAP2K1", "kind": "edge", "relation": "phosphorylation (P-S218/S222)",
     "source": "Materials §3.3 Fig.4B"}
  ],
  "compliance_checks": {
    "geometry": {"n_violations": 0, "scale": "regular", "svg_audit": {"n_violations": 0, "layers_named": true}},
    "legend_consistency": "auto-generated directly from rendered styles and verified",
    "export_checks": [
      {"file": "/app/output/fig.svg", "ok": true, "bytes": 18420},
      {"file": "/app/output/fig.png", "ok": true, "bytes": 245100},
      {"file": "/app/output/fig.pdf", "ok": true, "bytes": 42800}
    ],
    "visual_inspection": "Inspected fig.preview.png: zero overlap/clipping, receptors span bilayer, all legend glyphs match edges/nodes/mods."
  },
  "exceptions": [
    {"issue": "Interaction X reported without direct binding assay",
     "handling": "Drawn dashed as indirect/reported and noted in caption."}
  ]
}
```
