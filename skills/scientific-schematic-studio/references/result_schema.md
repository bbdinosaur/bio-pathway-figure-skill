# result.json 与 figure spec 契约（含最小示例）
## /app/output/result.json（每案例必产出；保留 case.json output_contract 全部顶层字段）
```json
{
  "case_id": "<来自 case.json>",
  "task_type": "generate | edit",
  "status": "ok | partial | failed",
  "version": "1.0",
  "generated_at": "ISO8601",
  "main_result": {
    "editable_source": {"path": "/app/output/figure1.svg", "format": "svg", "layers": ["panel-*", "node-*", "edge-*", "group-*", "legend-*"]},
    "exports": [{"path": "/app/output/figure1.png", "format": "png", "dpi": 300},
                {"path": "/app/output/figure1.pdf", "format": "pdf"},
                {"path": "/app/output/figure1_preview.png", "format": "png", "dpi": 100, "role": "preview"}]
  },
  "entity_inventory": [{"id": "K", "entity": "Kinase", "type": "round", "compartment": "Cytoplasm",
    "role": "phospho-active", "source": {"file": "paper.pdf", "locator": "p.3 Fig.3A"}, "confidence": "high"}],
  "relation_inventory": [{"subject": "Stimulus", "object": "Kinase", "kind": "activates",
    "evidence": "phosphorylation", "source": {"file": "paper.pdf", "locator": "p.3 Fig.3A"}, "confidence": "high"}],
  "compartments": [{"panel": "p1", "id": "cyto", "label": "Cytoplasm", "members": ["Kinase"], "membrane": true}],
  "legend_mapping": {"p1": {"panel_type": "schematic", "entries": [...]}, "p2": {"panel_type": "chart", "unit": "nM", "entries": [{"label": "treat", "color": "#0072B2", "n_points": 3}]}},
  "data_mapping": {"p2": {"kind": "line", "data_file": "source_data.xlsx", "sheet_name": "Fig3", "source_sha256": "...", "categories": [...], "series": [...], "unit": "nM"}},
  "provenance_summary": {"entities_sourced": "3/3", "relations_sourced": "2/2", "charts_sha256_verified": "1/1", "editable_text_verified": true, "source_preserved": true},
  "checks": {"geometry_audit": {...}, "export_compliance": {...}},
  "sources": ["paper.pdf", "source_data.xlsx"],
  "source_manifest": [{"file": "paper.pdf", "type": "pdf", "bytes": 123456, "sha256": "..."}],
  "uncertainty": [{"item": "...", "note": "...", "impact": "low"}],
  "limits": ["部分完成的明确边界"], "change_records": [{"step": "deliver_generate", "what": "...", "why": "..."}],
  "notes": "..."
}
```
- `make_result.py` 自动透传 `plan.json` 中额外的 `output_contract` 顶层字段；传入 `--case-json /input/case.json` 时自动校验并别名映射（`editable_source`/`editable_svg`/`svg_path`/`pdf_path`/`png_path`/`entities`/`relations`/`legend`/`export_checks`/`geometry_checks`/`data_verification`/`provenance`/`change_log` 等）。
- status 判定：任一必需清单缺失 / audit 或 export 或 edit 有 error → `partial`；fatal → `failed`。

## figure spec（build_figure.py 输入）最小示例 —— EXAMPLE，非真实案例结果
```json
{"canvas": {"width_mm": 180},
 "panels": [
  {"id": "p1", "type": "schematic", "title": "Example signaling cascade", "direction": "LR",
   "nodes": [
    {"id": "S", "label": "Stimulus", "shape": "ellipse", "fill": "#FDEBD0", "rank": 0,
     "source": {"file": "paper.pdf", "locator": "p.2"}},
    {"id": "K", "label": "Kinase", "sublabel": "phospho-active", "shape": "round", "rank": 1,
     "source": {"file": "paper.pdf", "locator": "p.2"}},
    {"id": "T", "label": "Target", "shape": "stadium", "fill": "#D5F5E3", "rank": 2,
     "source": {"file": "paper.pdf", "locator": "p.3"}}],
   "edges": [{"from": "S", "to": "K", "kind": "activates", "label": "phosphorylation",
              "source": {"file": "paper.pdf", "locator": "p.2"}},
             {"from": "K", "to": "T", "kind": "inhibits", "label": "repression",
              "source": {"file": "paper.pdf", "locator": "p.3"}}],
   "groups": [{"id": "nuc", "label": "Nucleus", "members": ["T"], "dash": true}],
   "legend": {"title": "Interaction types",
              "items": [{"kind": "activates", "label": "activation"},
                        {"kind": "inhibits", "label": "inhibition"}]}},
  {"id": "p2", "type": "chart", "title": "Example dose response", "height_mm": 54,
   "chart": {"kind": "line", "unit": "nM", "categories": ["0", "1", "10"],
     "series": [{"name": "ctrl", "values": [1.0, 1.1, 0.9], "errors": [0.1, 0.1, 0.1], "color": "#8C8C8C"},
                {"name": "treat", "values": [1.0, 2.3, 4.1], "errors": [0.1, 0.2, 0.3], "color": "#0072B2"}],
     "y_label": "Expression", "x_label": "Dose"}}]}
```
注：图表面板支持 `"data_file"`（CSV/TSV/多 sheet XLSX，含水平与垂直 `<mergeCell>` 继承、Unicode 负号/科学计数法、`"mean ± SD"` 拆解、`"section_match"` 先于 `"col_range"` 定位子表、`"orient": "columns"` / `"col_groups"` / 2行重复表头自动聚合、`"agg": "mean_sd|mean_sem|median_iqr"`、`"show_points"`、`"sig_brackets"`、`"color_by_sign"`/`"bar_colors"`、`"hlines"`/`"vlines"`）实现数据表改动后自动重绘并经 SHA-256 独立复核；支持 `bar` / `barh` / `stacked_bar` / `line` / `scatter` / `box` / `heatmap`；生成态支持 `"post_edit_ops"`，编辑态支持 `"from_text"`+`"to_text"` 语义定位边。

推荐两步一键命令：
`python3 scripts/run_pipeline.py prepare --input /input --work /app/work --out /app/output`
`python3 scripts/run_pipeline.py deliver /app/work/plan.json --input /input --work /app/work --out /app/output`

分步单模块命令：
`python3 build_figure.py spec.json --out-dir /app/output --stem figure1 --geom /app/work/geometry.json`
`python3 audit_figure.py /app/work/geometry.json --spec spec.json --out /app/work/audit.json`
`python3 export_check.py --png f.png --pdf f.pdf --svg f.svg --width-mm 180 --dpi 300 --probe "Kinase"`
`python3 make_result.py --case-id ID --task-type generate --case-json /input/case.json --manifest manifest.json --audit audit.json --export-checks checks.json --out /app/output/result.json`
