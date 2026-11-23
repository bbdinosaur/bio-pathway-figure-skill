---
name: "graphical-abstract-skill"
description: "Deterministic, source-bound Graphical Abstract builder and source-preserving SVG editor for scientific research: extracts entities, biological/chemical mechanisms, and actual quantitative chart data from papers and tables, renders a layered editable SVG plus 96 DPI preview PNG and searchable vector PDF, runs geometry/accessibility/data-grounding audits, and outputs an auditable result.json."
---

# GA-Skill — 科研图形摘要生成与保源编辑（极速两步闭环）

适用：基于论文 PDF / 实验记录 / Source Data（CSV/TSV/XLSX）生成单页 Graphical Abstract 或发表级多面板生物图（问题→方法/机制→核心结果→结论），或对既有科研 SVG 执行外科式保源编辑并重导出。

## 硬契约
1. **真实原文件为唯一事实依据**：先读 `/input/case.json`、`task.md` 与原始材料（PDF/CSV/TSV/XLSX/SVG）；若领域标签与原论文/数据表冲突，**以实际原文件为准**并在 `uncertainty` 披露，严禁补造实体或数值。
2. **标准交付（`/app/output/`）**：可编辑分层 SVG + 96 DPI 1:1 预览 PNG（≤108 DPI）+ 可检索单页矢量 PDF + `result.json`（含 `case_id`、`output_contract` 全字段、`source_map`、`data_mapping`、`checks`、`scientific_inventory`、`human_confirmation`、`uncertainty`、`change_log`）。
3. **诚实边界**：缺数值→改定性表达并在 `uncertainty` 声明；缺工具/导出失败→标 `status: "partial"` 并写 `limits`。严禁虚构数据、软件状态或跑分。
4. **极速预算（64 轮 / 900 s，目标 ≤8 轮完成）**：第 4 轮内一键落盘完整首版到 `/app/output/`，余量做 1 轮数据与版式精修。

---

## Step 1 — 限流一键勘察与路径分流（第 1 轮）
每轮 bash 独立无状态，各命令统一用 `${SKILL_DIR:-/skills/weekly-skill}`（脚本通过 `__file__` 自定位）：
```bash
mkdir -p /app/work /app/output
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_intake.py" --case /input/case.json --input-dir /input
```
输出硬控 ≤14 KB（防多表 XLSX 截断，完整结果自动保存 `/app/work/_intake_full.json`），涵盖 `case_id`、`output_contract`、`task_md`、PDF 首页/章节/目标图注与正文引用、SVG/图片/DOCX 摘要与数据表索引。按需定点精读：
- 读指定 PDF 页或检索：`ga_intake.py --pdf <p> --pdf-pages P-Q` 或 `--pdf-find <q>`
- 读指定 Excel 表/CSV 精确统计：`ga_intake.py --table <file> --sheet <name>`
无脚本降级：用 Python 读 `/input/case.json` 与 `ls /input`。
- **含既有 SVG 且要求修订/保源编辑 → 走【路径 B】**（严禁整图重画）。
- **要求基于论文/数据新建图稿或机制图 → 走【路径 A】**。

---

## 路径 A — 极速确定性图形摘要生成（4–6 轮完成）

### A1 核验原始材料并写 `brief.json`（第 2–3 轮）
- 按需用 `--pdf-pages` / `--table --sheet` 核对四要素：**实体原文与空间分区、因果极性（激活/抑制/反馈）、真实量化值（均值/SD/SEM/replicates/n/单位/p 值）、workorder 指定图型与文件名**。
- 编写 `/app/work/brief.json`（完整字段与 32 图标见 `references/brief-schema.md`，示例见 `assets/example_*.json`）；在 panel/block 直接写 `"source"` 即自动生成 `source_map`/`data_mapping`，也可另写 `/app/work/report.json` 补 `uncertainty` 与 `change_log`。核心要点：
  - **主题与版式**：图形摘要用 `theme: "card"` + `hero-2x2`（A–D）；发表级多面板生物图（如 Fig. 3）设 `theme: "journal"` + `badge: "a"/"b"/"c"/"d"`；支持 `1+3`、`hero-1+2`、`2+1`、`left-hero`、`stack`、`2x2`、`grid`（5–8 面板）、`row`、自定义 `canvas`、宽面板内 `row` 并排双图与 `table`。
  - **机制与示意图**：`mechanism` 支持 `stages`（与列自动对齐）、`zones`（自动双层磷脂膜/双虚线核膜/细胞器）、`activate`/`inhibit`（红 T-bar）/`bidirectional`/`dashed` + `legend`，省略 `nx/ny` 自动分层防碰撞；需解剖/器件/分子特写时可用 `{"type": "svg", "viewBox": "...", "svg": "<g>...</g>"}` 嵌入自动缩放矢量块。
  - **真实数据图（`chart`）**：`bar`/`hbar`/`stacked`/`line`（`band`/`ci_lo`/`ci_hi`/`step` KM）/`dot`/`box`/`paired`（配对前后连线）/`scatter`（`xlog`/`ylog`/`connect` 剂量反应/`trend`）/`volcano`（自动 Up/Down/NS 阈值着色）/`heatmap`（负值自动 RdBu 发散）；支持 `ylog`、`points` 重复散点、`reflines`、`sig` 防碰撞支架与 `%`/Survival 自动封顶 100。缺数值改定性并在 `uncertainty` 声明。
  - **防溢出**：多块面板中 `flow` 勿设 `fill: true`；主标题 ≤85 字符。

### A2 一键构建、全维审计与交付（第 4 轮落盘首版，第 5–6 轮精修）
单条命令完成 **SVG 构建 → 96 DPI 预览 PNG + 可检索矢量 PDF → 几何/字体/色盲/源数据交叉核验 → 复制交付 `/app/output/` → 生成全字段 `result.json`**：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_pipeline.py" \
  --brief /app/work/brief.json --outdir /app/work \
  --data-dir /input --case /input/case.json --deliver /app/output \
  --report /app/work/report.json
```
（自动从 `brief.stem` 或 `case.json` 推断目标文件名，亦可用 `--stem <name>` 显式指定；仅当明确要求印刷大图时加 `--hires-dpi 300`，默认预览严格 96 DPI ≤ 108 DPI。）
- **纯文本闭环自检**：检查返回 JSON 的 `overflow`（含 `overflow_hints`）、`panel_fill`、`errors`、`warnings`、`advisories`、`data_grounding.unmatched` 与 `result.missing`；有异常只改 `brief.json` / `report.json` 重跑同命令 1 轮即覆盖交付（若支持读图，仅看 `/app/output/<stem>.png`）。

---

## 路径 B — 保源编辑既有 SVG（4 轮完成，严禁整图重绘）
详见 `references/failure-playbook.md`，100% 保留未改图层、坐标、ID、内联样式与命名空间：
1. **结构勘察（第 2 轮）**：
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" --svg /input/<src>.svg --inspect
   ```
   （大文件可加 `--find <关键词>` 全局检索文本/图形 ID。）
2. **编写最小补丁（第 3 轮）**：写 `/app/work/edits.json`（示例见 `assets/example_edits.json`；支持 `replace_text` 多 `<tspan>`/`layer` 含 `inkscape:label`/`id`/`regex`/同步改样式、`set_text_by_index`/`set_text_by_id`、`set_attr` 穿透 CSS 类、`restyle_class`、`replace_color`、`scale_rect`、`translate`、`hide`、`delete`、`expand_canvas` 含白底、`insert_svg`、`add_overlay` 比例尺/图例/T-bar 箭头/`panel_badges`/显著性支架/标注框/脚注）及可选 `/app/work/report.json`。
3. **一键编辑、重渲染、外源审计与交付（第 4 轮）**：
   ```bash
   python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/ga_svg_edit.py" \
     --svg /input/<src>.svg --out /app/work/edited.svg --edits /app/work/edits.json \
     --case /input/case.json --deliver /app/output --report /app/work/report.json
   ```
   单命令完成外科修改、生成 `_edit_report.json` 保源证明、渲染 96 DPI PNG + 矢量 PDF、执行 `--external` 审计、交付 `/app/output/` 并合并 `source_preservation` 与 `change_log` 到 `/app/output/result.json`（需指定文件名改 `--out /app/work/<name>.svg`）。

---

## 降级与参考文档
- **无脚本降级**：手写标准 1600×900 分层 SVG（纯 SVG 1.1 原语、可编辑文字、字号 ≥11）→ `soffice --headless --convert-to pdf` + `pdftoppm -png -r 96` → 手工输出含 `case_id` 与全 `output_contract` 字段的 `result.json`。
- **渲染自动降级**：`chrome/chromium → soffice+pdftoppm(96 DPI) → rsvg-convert → ImageMagick(96 DPI)`；全失败仍交付 SVG + `status: "partial"` + `limits`。
- 详参：`references/brief-schema.md`（块与 32 图标）、`references/layout-spec.md`（网格与导出）、`references/palette-and-legend.md`（色盲安全配色）、`references/failure-playbook.md`（异常与保源编辑）。
