# Failure playbook & source-preserving edit mode

## Runtime risk table (detect → handle → record)

| risk | detection | handling | where recorded |
|---|---|---|---|
| Missing key numbers in material | Material read finds no numeric table/values | Render qualitative GA (text/callout/flow/mechanism); NEVER invent numbers | `result.json` `uncertainty` |
| Ambiguous entity / conflicting label | Source text vs filename/tag disagree | Trust primary paper/data file over labels; note discrepancy | `uncertainty` |
| Panel text overflow | `ga_pipeline.py` exit 1 (`overflow_panels`) | Shorten copy, switch to `hero-2x2` or tune `row_weights`/`top_weights`, re-run | `change_log` |
| Mechanism node/label crowd | `ga_check.py` error or footnote warning | Use `hero-2x2` (wider panel) or omit manual `nx/ny` for auto layout | `change_log` |
| External SVG minor quirks | `ga_check.py --external` warnings | Leave untouched source geometry intact; fix only requested targets | `notes` |
| Font missing at render time | Renderer warning / visual inspection | Multi-OS Latin + CJK fallback stack; verify legibility on PNG | `notes` |
| All render engines fail | `ga_pipeline.py` / `ga_render.py` exit 3 | Ship editable SVG + `status: "partial"` | `limits` |
| PDF blank or multi-page | `_build_report.json` `export_check.pdf.ok=false` | Retry `soffice` path; keep PNG + SVG and log honestly | `limits` |

## Source-preserving edit mode (editing an existing SVG)
When the workorder supplies an existing SVG figure to revise:
1. **NEVER regenerate the provided figure from scratch.**
2. Copy the source SVG into `/app/work/edited.svg` and inspect its structure:
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" --svg /app/work/edited.svg --inspect
   ```
   Returns canvas dims, `viewBox`, layers, text nodes (including multi-`<tspan>` & effective CSS `style` font-size/fill), `named_shapes` with IDs, and `colors_used`.
3. Prepare `/app/work/edits.json` with minimal surgical operations:
   ```json
   [
     {"op": "replace_text", "layer": "layer-panel-b", "old": "WT control", "new": "WT (n = 6)"},
     {"op": "replace_text", "old": "p\\s*=\\s*0\\.05", "new": "p = 0.004", "regex": true},
     {"op": "set_text_by_id", "id": "sub-title", "new": "Validated cohort (n = 6)", "font_size": 12.5},
     {"op": "set_text_by_index", "index": 12, "new": "p < 0.01", "font_weight": "bold"},
     {"op": "set_attr", "id": "bar-treated", "attr": "fill", "value": "#0072B2"},
     {"op": "restyle_class", "class": "cls-1", "attr": "fill", "value": "#0072B2"},
     {"op": "replace_color", "old": "#ff0000", "new": "#D55E00"},
     {"op": "translate", "id": "legend-box", "dx": 12, "dy": -6},
     {"op": "hide", "id": "draft-watermark"},
     {"op": "scale_rect", "id": "bar-2", "height": 180, "anchor": "bottom"},
     {"op": "expand_canvas", "bottom": 36},
     {"op": "insert_svg", "parent_id": "layer-main", "xml": "<circle cx=\"200\" cy=\"150\" r=\"6\" fill=\"#0072B2\"/>"},
     {"op": "add_overlay",
      "panel_badges": [{"x": 20, "y": 32, "label": "a"}],
      "scalebar": {"x": 40, "y": 840, "px": 100, "length": "50 μm"},
      "legend": {"x": 960, "y": 24, "items": [{"color": "#0072B2", "label": "Treated"}]},
      "arrows": [{"x1": 320, "y1": 180, "x2": 260, "y2": 240, "kind": "inhibit", "label": "Blocks site"}],
      "sig_brackets": [{"x1": 150, "x2": 410, "y": 115, "label": "p = 0.004"}],
      "callout_box": {"x": 620, "y": 130, "w": 220, "title": "Validated", "text": "n = 5 biological replicates"},
      "footer": {"sources": "Original Fig. 2 revised", "version": "GA-Skill v14 · rev1"}}
   ]
   ```
   Execute (one-shot edit + render + external audit + deliver + `result.json`):
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" --svg /input/<src>.svg --out /app/work/edited.svg \
     --edits /app/work/edits.json --case /input/case.json --deliver /app/output --report /app/work/report.json
   ```
   - `set_attr` and `replace_color` update XML attributes, inline CSS `style="..."`, and `<style>` stylesheets (handling named CSS colors, `#abc`, `#AABBCC`, and `rgb(r,g,b)`), so Illustrator/BioRender/Matplotlib/Inkscape SVGs recolor reliably.
   - Automatically writes `_edit_report.json` with SHA-256 before/after, DOM counts, and `untouched_layers_preserved` proof, auto-merged into `result.json` by `ga_result.py`.
   - `replace_text` handles multi-`<tspan>` text elements safely and refuses ambiguous multi-hit matches unless `"all": true`.
   - Every untouched layer, coordinate, path, ID, and Inkscape namespace stays 100% intact.
4. Re-render at the SVG's native `viewBox` dimensions and run external audit:
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_render.py" --svg /app/work/edited.svg --outdir /app/work && \
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_check.py" --svg /app/work/edited.svg --external
   ```
   `--external` skips `<defs>`/`<clipPath>`/`<marker>`/hidden nodes and transformed local coordinates, while still catching structural corruption.
5. Copy edited SVG/PNG/PDF to `/app/output/`, paste the exact `changes` list into `report.json` `change_log`, and build `result.json` via `ga_result.py`.
6. If the provided source is a raster bitmap (PNG/JPG) rather than SVG: rebuild a faithful layered editable SVG from it, mark `status: "partial"`, and document source-type limitations in `limits`.

## Missing-material triage (honesty first)
- Quantitative chart requested but numbers absent → deliver qualitative GA + `uncertainty: ["chart omitted: numeric source absent from provided materials"]`.
- PDF unreadable / empty text layer → try `fitz` / `pdfplumber`; if scanned/unreadable, build from task text only and flag `status: "partial"` with explanation in `limits`.
- Always write an honest, schema-complete `result.json` early, then refine.
