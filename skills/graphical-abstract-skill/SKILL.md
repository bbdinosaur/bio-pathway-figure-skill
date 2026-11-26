---
name: "graphical-abstract-skill"
description: "Deterministic, source-bound Graphical Abstract builder and source-preserving SVG editor for scientific research: extracts entities, biological/chemical mechanisms, and actual quantitative chart data from papers and tables, renders a layered editable SVG plus 96 DPI preview PNG and searchable vector PDF, runs geometry/accessibility/data-grounding audits, and outputs an auditable result.json."
---

# GA-Skill — 科研图形摘要确定性生成与保源编辑

适用：基于论文 PDF / 实验记录 / Source Data（CSV/TSV/XLSX/DOCX）生成单页 Graphical Abstract 或发表级多面板图（如 `figure03`），或对既有科研 SVG 执行外科式保源编辑并重导出。

## 硬契约
1. **真实原文件为唯一事实依据**：先读 `/input/case.json`、`task.md` 与原始材料；若领域标签与原论文/数据表冲突，**以实际原文件为准**并在 `uncertainty` 披露，严禁补造实体或数值。
2. **标准交付（`/app/output/`）**：可编辑分层 SVG + 96 DPI 1:1 预览 PNG（≤108 DPI）+ 可检索单页矢量 PDF + `result.json`（含 `case_id`、`output_contract` 全字段、`source_map`、`data_mapping`、`scientific_inventory`、`checks`、`human_confirmation`、`uncertainty`、`change_log`）。
3. **诚实边界**：缺数值→改定性并在 `uncertainty` 声明；缺工具/导出失败→标 `status: "partial"` 并写 `limits`。严禁虚构数据、软件状态或跑分。
4. **科学严谨优先（预算 64 轮 / 900 s，建议 8–14 轮）**：严禁跳过原论文精读或漏掉源数据子表；第 6–8 轮先落盘完整可核验首版至 `/app/output/`，再用 2–3 轮精校数据与视觉。

---

## Step 1 — 一键勘察与路径分流（第 1 轮）
每轮 bash 独立无状态，各命令统一用 `${SKILL_DIR:-/skills/weekly-skill}`（脚本通过 `__file__` 自定位）：
```bash
mkdir -p /app/work /app/output
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_intake.py" --case /input/case.json --input-dir /input
```
输出控在 ≤22 KB 合法 JSON（全量自动写入 `/app/work/_intake_full.json`），直接返回 `case_id`、`output_contract`、`task_md`、PDF 首页/章节页码/图注与目标图深挖、CSV/TSV/XLSX 统计（含合并表头、并排子表与汇总行隔离）及 SVG/DOCX 摘要。无脚本降级：Python 读 `/input/case.json` 与 `ls /input`。
- **含既有 SVG 且要求修订/保源编辑 → 走【路径 B】**（严禁整图重画）。
- **要求基于论文/数据新建图稿或发表级多面板图 → 走【路径 A】**。

---

## 路径 A — 源数据绑定图形摘要与多面板图生成

### A1 精读原论文与原始数据（第 2–4 轮）
- **核读原文关键页**：按 `section_pages` 用 `pdftotext -f P -l Q /input/<paper>.pdf -` 或 `ga_intake.py --pdf <p> --pdf-pages P-Q` / `--pdf-find <q>` 精读目标图完整图注与 Results/Methods，核实：**全部子面板与指定文件名、实体原文与空间分区、因果极性（激活/抑制/反馈）、真实数值/单位/`n`/误差类型（SD/SEM/95% CI）/统计检验与 `p` 值、图例与比例尺**。
- **零手抄误差数据绑定**：若有 CSV/TSV/XLSX 原始数据，用 `ga_intake.py --table <f> --sheet <name>` 核查表结构，并推荐写简短 Python 脚本（可直接导入 `ga_intake.read_xlsx_sheets` 或 `csv`）精确计算均值/SD/SEM/四分位并将**全部生物重复散点**直接写入 `/app/work/brief.json`，杜绝手抄误差。

### A2 编写 `brief.json` 与 `report.json`（第 5 轮）
全字段与 32 图标见 `references/brief-schema.md`，版式与配色见 `references/layout-spec.md`、`palette-and-legend.md`，接口示例见 `assets/example_*.json`。要点：
- **主题与版式**：图形摘要用 `theme: "card"` + `hero-2x2`（A–D）；发表级多面板图（如 `figure03`）用 `theme: "journal"`（可选 `border: false`）+ 小写 `badge: "a".."f"`，按面板数选 `1+3`、`1+4`/`2+3`/`3+2`、`grid`/`2x3`、`hero-1+2`/`left-hero`，宽面板内支持 `row` 并排双图。
- **机制与示意**：`mechanism` 支持列对齐 `stages`、自动磷脂膜/核膜/细胞器 `zones`、`activate`/`inhibit`（红 T-bar）/`bidirectional`/`dashed` + `legend`，省略 `nx/ny` 自动分层防碰撞；特写示意用 `{"type": "svg", "viewBox": "...", "svg": "<g>...</g>"}`。
- **真实数据图（`chart`）**：`bar`/`hbar`/`strip`（生物重复散点+均值±SD横线）/`box`/`stacked`/`line`（`band`/`ci_lo`/`ci_hi`/`step` KM）/`paired`/`scatter`（`xlog`/`ylog`/`connect`/`trend` OLS+R²）/`volcano`/`forest`（OR/HR 95% CI 森林图）/`heatmap`（负值自动 RdBu 发散）；均支持 `points`、`sig`、`reflines` 与 `note`（必写单位、`n`、误差定义与来源）。
- **可复核溯源**：在 panel/block 写 `"source"`，并用 `/app/work/report.json` 补 `uncertainty`（含标签冲突）、`change_log` 与图注 `notes`。主标题 ≤85 字符；多块面板 `flow` 勿设 `fill: true`。

### A3 构建、审计与视觉精修（第 6–10 轮）
单条命令完成 **SVG → 96 DPI PNG + 矢量 PDF → 全维几何/色盲/源数据/像素边缘审计 → `/app/output/` + 全字段 `result.json`**：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_pipeline.py" \
  --brief /app/work/brief.json --outdir /app/work \
  --data-dir /input --case /input/case.json --deliver /app/output \
  --report /app/work/report.json
```
（workorder 指定文件名时显式加 `--stem <name>`；仅明确要求印刷大图时加 `--hires-dpi 300`，默认严格 96 DPI ≤ 108 DPI。）
- **必做闭环精修**：核查返回 JSON 的 `overflow`/`overflow_hints`、`errors`、`warnings`、`advisories`、`data_grounding.unmatched`、`export_check`（`dpi_ok`、`ink_ratio`、`edge_clip_px == 0`）与 `result.missing`；若支持读图，检查 `/app/output/<stem>.png` 的层级、图例、因果方向与留白，修正后重跑同命令覆盖更新。

---

## 路径 B — 保源编辑既有 SVG（严禁整图重绘）
详见 `references/failure-playbook.md`，100% 保留未改图层、坐标、ID、样式与命名空间：
1. **结构勘察**：
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" --svg /input/<src>.svg --inspect
   ```
   （大文件可加 `--find <关键词>`；自动识别 `inkscape:label`、CSS 类与 matplotlib/Prism 矩形 `<path>`/`<polygon>` 柱体。）
2. **编写最小补丁**：写 `/app/work/edits.json`（示例见 `assets/example_edits.json`；支持 `replace_text`/`set_text_by_id`/`set_text_by_index`/`add_text`、`set_attr`、`restyle_class`、`replace_color`、`scale_rect` 兼容 `<rect>`/`<path>`/`<polygon>` 柱体、`translate`、`hide`、`delete`、`expand_canvas`、`insert_svg`、`add_overlay`）及 `/app/work/report.json`。
3. **外科编辑、重渲染与交付**：
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" \
     --svg /input/<src>.svg --out /app/work/<target>.svg --edits /app/work/edits.json \
     --case /input/case.json --deliver /app/output --report /app/work/report.json
   ```
   核对 `errors == []`、`untouched_layers_preserved == true`、`result.missing == []`；支持读图时目检 `/app/output/<target>.png`。

---

## 降级与参考文档
- **无脚本降级**：手写 1600×900 分层 SVG（纯 SVG 1.1 原语、可编辑文字 ≥11 px）→ `soffice --headless --convert-to pdf` + `pdftoppm -png -r 96` → 输出含 `case_id` 与全 `output_contract` 字段的 `result.json`。
- **渲染自动降级**：`chrome/chromium → soffice+pdftoppm(96 DPI) → rsvg-convert → ImageMagick(96 DPI)`；全失败仍交付 SVG + `status: "partial"` + `limits`。
- 详参：`references/brief-schema.md`、`layout-spec.md`、`palette-and-legend.md`、`failure-playbook.md`。
