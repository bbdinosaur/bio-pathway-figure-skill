---
name: "scientific-schematic-studio"
description: "Scientific schematic generation & editing: extracts source-bound entity-relation inventories, figure captions, and real data tables (XLSX/CSV/TSV, PDF, DOCX, PPTX, OCR, SVG), renders layered editable SVG + journal PDF/PNG via group-aware TB/LR layout, performs source-preserving SVG edits (gid/by_text/edge_idx/auto-connect), audits geometry/provenance/SHA-256 data fidelity/export compliance, and emits result.json with output_contract fields. Trigger on /input/case.json schematic, mechanism, flowchart, chart, or figure-edit workorders."
---

# Scientific Schematic Studio（出版级两步快轨）

触发：`/input/case.json` 存在且任务涉及科研示意图、机制图、信号通路、流程图、关系图、源数据图表或既有图稿保源编辑。

## 核心纪律
- **两步快轨**：单案例 **≤ 7 步 / < 220s**（硬限 64 请求 / 900s；> 600s 收尾）；**勿 `read` `.png`/`.pdf`**，直接看 `deliver` 纯文本摘要；见 `NEXT: ALL CHECKS PASSED` 即收尾。
- **事实唯一来源 + 科学完整**：一次在 `plan.json` 忠实还原原论文目标图（如 `Fig. 3`）全部关键分子/复合物、剂量/时间/修饰、上下游方向、亚细胞区室与真实源数据；**严禁编造基因名/浓度/数值**；冲突以原文为准记入 `uncertainty`。
- **同源交付**：`/app/output` 必含分层可编辑 `.svg`（`<text>` 可选、语义 `id`）+ 嵌字 `.pdf` + 300 DPI `.png` + 100 DPI `_preview.png` + `result.json`（含 `case_id`、`output_contract` 顶层字段、`status`/`sources`/`uncertainty`/`change_records`）；编辑留 `original_*.svg`。

## 两步一键管线（`run_pipeline.py`，每次 bash 自包含路径）

### Step 1 — 一键侦察与保底落盘（1 次 bash）
```bash
python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/run_pipeline.py prepare --input /input --work /app/work --out /app/output
```
读全 `case.json`/`task.md`（给 `suggested_stem`），抽取 PDF（完整主图注 + 高相关页 + 表格 → `pdf_extract.txt`）、DOCX/PPTX、`A|B|C` 列标及堆叠子表 XLSX/CSV（→ `table_extract.txt`）、图片 OCR、SVG 清单，并**立即写保底 `result.json`（`partial`）**。
- 若出现 `[PDF_READ_HINT]` 或 `[TRUNCATED]`，按 `[Lstart-Lend]` 定向 `read` `pdf_extract.txt`（1–2 步）抽全所有子图/分子/剂量。

### Step 2 — 写完整 `/app/work/plan.json` 并一键交付（2 步）
写入全部实体/关系/区室/源表绑定 + `output_contract` 顶层字段后执行：
```bash
python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/run_pipeline.py deliver /app/work/plan.json --input /input --work /app/work --out /app/output
```
一步完成渲染（或保源编辑）→ 几何/区室/穿节点边/溯源/SHA-256 核验 → 导出合规 → 终态 `result.json` → 纯文本摘要。存在 `AUDIT_ERRORS`/`EXPORT_ERRORS`/`EDIT_ERRORS`/`missing_contract_fields` 或实绘数值不符时修 `plan.json` 重跑一次。

## 科研语义与造型
- **语义边（自动着色同步图例）**：激活 `activates`（深蓝箭头）；抑制 `inhibits`（深红 T 杠 ⊣）；间接抑制 `inhibits_dashed`；易位 `translocates`（蓝虚空心箭头）；结合 `binds`（紫 ↔）；流程 `flows`；自反馈 `from==to`；**区室放 `groups`（嵌套 + `"membrane":true`），不画箭头**。
- **节点造型**：配体 `ellipse` `#FDEBD0` · 复合物 `complex` `#EAF2FB` · 抑制剂 `hexagon` `#FADBD8` · 核心 `round` `#0072B2`（深底白字）· 基因 `gene` `#D5F5E3` · 效应 `stadium` `#D5F5E3` · 决策 `diamond` `#E8DAEF`；支持 `"badge"`/`"sublabel"`。
- **网格与预设**：同 `"row"` 并排（配 `"width_weight"`）；`"preset":"nature_double"|"nature_single"|"cell_double"|"slide_16_9"`；`"footnote"`。

## 内联 `plan.json` 示例（EXAMPLE）
**生成模式（机制 + 源表直连数据图）：**
```json
{"case_id": "EX-01", "stem": "figure03", "preset": "nature_double",
 "footnote": "Source: paper.pdf Fig.3; source_data.xlsx (mean ± SD).",
 "panels": [
  {"id": "p1", "row": 0, "type": "schematic", "title": "Example Cascade", "direction": "TB",
   "nodes": [
    {"id": "L", "label": "Ligand", "sublabel": "20 ng/mL", "shape": "ellipse", "fill": "#FDEBD0", "rank": 0, "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"id": "R", "label": "Receptor", "shape": "complex", "fill": "#EAF2FB", "rank": 1, "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"id": "K", "label": "Kinase", "shape": "round", "fill": "#0072B2", "badge": "↑ 6.8×", "rank": 2, "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"id": "I", "label": "Inhibitor", "shape": "hexagon", "fill": "#FADBD8", "rank": 2, "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"id": "G", "label": "Target Gene", "shape": "gene", "fill": "#D5F5E3", "rank": 3, "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}}],
   "edges": [
    {"from": "L", "to": "R", "kind": "binds", "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"from": "R", "to": "K", "kind": "activates", "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"from": "I", "to": "K", "kind": "inhibits", "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}},
    {"from": "K", "to": "G", "kind": "translocates", "label": "nuclear entry", "source": {"file": "paper.pdf", "locator": "p.6 Fig.3A"}}],
   "groups": [{"id": "cell", "label": "Cytoplasm", "members": ["K", "I", "G"], "membrane": true},
              {"id": "nuc", "label": "Nucleus", "members": ["G"]}]},
  {"id": "p2", "row": 1, "type": "chart", "title": "Quantification", "height_mm": 54,
   "chart": {"kind": "bar", "data_file": "/input/source_data.xlsx", "sheet_name": "Fig3", "col_range": "B:D",
             "orient": "columns", "y_cols": ["Ctrl", "Stim", "Stim+Inh"], "agg": "mean_sd", "show_points": true,
             "y_label": "Signal", "unit": "fold", "sig_brackets": [{"x1": "Ctrl", "x2": "Stim", "label": "***"}]}}],
 "uncertainty": [], "notes": "Grounded in primary paper and source table."}
```
图表：`bar`/`barh`/`stacked_bar`/`line`/`scatter`/`box`/`heatmap`、`err_cols`（自拆 `mean±SD`）、长表 `hue_col`+`agg` / 散点 `label_col`+`top_labels` / 宽表 `orient:"columns"`/`col_groups`、`col_range`/`sheet_name`/`section_match`、`sig_brackets`（支持组内 `x`+`s1`/`s2`）、`hlines`/`vlines`；修订加 `"post_edit_ops"`；PPT 加 `"pptx":true`；`output_contract` 透传。

**保源编辑模式（保留 `original_*.svg`，自动收割实体与关系）：**
```json
{"case_id": "EX-02", "mode": "edit", "edit_svg": "/input/orig.svg", "stem": "orig_edited",
 "ops": [
  {"op": "replace_text", "find": "Old", "replace": "New"},
  {"op": "set_attr", "by_text": "Target", "attr": "fill", "value": "#FADBD8"},
  {"op": "set_marker", "from_text": "Target", "to_text": "Kinase", "marker": "tbar"},
  {"op": "add_node", "id": "node-M", "label": "mTORC1", "sublabel": "Ser2448-P", "shape": "stadium", "right_of": "Kinase", "fill": "#0072B2"},
  {"op": "add_edge", "id": "edge-new", "from_text": "Target", "to_text": "mTORC1", "marker": "arrow", "label": "activates"},
  {"op": "add_legend", "items": [{"kind": "activates", "label": "Activation"}, {"kind": "inhibits", "label": "Inhibition"}]}]}
```
ops：`retext`/`replace_text`/`set_attr`(暗底自适配白字)/`set_dash`/`move`(连边跟随)/`swap_edge`/`set_marker`(`arrow|tbar|open|none`+`dash`)/`add_node`(相对避障/多行)/`add_edge`(避障)/`add_group`/`add_legend`/`delete`(自清连边)/`add_note`（支持 `gid`/`from_text`+`to_text`/`edge_idx`，超界扩 `viewBox`）。

## 无脚本兜底与资源
仅 `run_pipeline.py` 连续失败才手写 SVG → `soffice --headless --convert-to pdf` + `pdftoppm -png -r 300` → `result.json`。
资产：`assets/`(`journal_presets`·`templates`) · `references/`(`layout_rules`·`style_tokens`·`export_presets`·`result_schema`·`failure_playbook`)。
