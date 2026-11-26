---
name: "sci-figure-studio"
description: "科研数据图表生成、生物机制图构建与图稿source-preserving编辑：从源数据或论文出发，产出可编辑SVG（<text>不转曲）、投稿级PDF/PNG（预览≤100 DPI）、元素级溯源与变更日志，自动核验可编辑性、图例一致性、数值与几何。"
---

# Sci-Figure-Studio — 科研图表与机制图执行卡

## 触发与原则
- 触发：`/input/case.json` 或 `/input/task.md` 含科研绘图/改图/机制图工单（如 `source_value_chart`、`figure03`）。
- **先科学判读，再作图**：先读懂问题、对照、量纲、误差定义与通路极性；不造数不补零、实体逐字复制、缺口标 `partial`/`limits`。
- 六检查点：科学实体、空间关系、数据编码、图例标注、可编辑源(`<text>`)、导出格式(SVG+PDF+300 DPI PNG+≤100 DPI 预览)。
- 产物（全落 `/app/output/`）：`result.json`（`case_id`、`status`、全部 `output_contract`、`reproducibility`）+ SVG/PDF/PNG + `.provenance.json`。
- **路径自包含**：每次 `bash` 为独立子进程，变量不跨步；每段命令直用 `${SKILL_DIR:-/skills/weekly-skill}`（非该路径则按步骤 0 `skill_dir` 或同块 `find /skills` 定位）。

## 极速三段管线（6–9 步：首轮保底 + 科学复核精修）

### 步骤 0 · 探测输入并保底落盘 `result.json`（1 步）
```bash
mkdir -p /app/work /app/output
find /input -maxdepth 4 -type f | sort
cat /input/case.json 2>/dev/null; echo "=== TASK.MD ==="; cat /input/task.md 2>/dev/null
S="${SKILL_DIR:-/skills/weekly-skill}"; [ -f "$S/scripts/inspect_input.py" ] || S="$(dirname "$(dirname "$(find /skills -name inspect_input.py 2>/dev/null | head -1)")")"
python3 "$S/scripts/inspect_input.py" /input --compact --json /app/work/input_summary.json --init-output /app/output/result.json
```
核清 `skill_dir`/`case_id`/源路径/列名缺测/Figure 页/`output_contract`/`cjk_font`；同时落盘保底 `result.json`（`status:"partial"` + 契约键 + 初步 `limits`）。

### 步骤 1 · P0 首版闭环并落盘草稿（2–3 步）
选路（可组合）：数据表→**A**；既有图稿→**B**；论文机制图→**C**；非标图→**A-自定义**；产出后紧接 **D**。

#### A · 数据图表（`chart_tool.py`）
按 `references/chart_recipes.md` §1 写 `/app/work/fig1.spec.json`：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/chart_tool.py" /app/work/fig1.spec.json --outdir /app/output --base fig1
```
- 图型：`bar/grouped_bar/stacked_bar(normalize_pct)/barh/stacked_barh/line(error_style:"band")/errorbar/step/scatter(fit_line/label_top_n)/bubble/dotplot/box/violin/pie/donut/heatmap(vcenter:0)`；支持横幅表、`"val ± err"`、分组 `box/violin`、双 Y、`width_ratios`、`filter`、`x_order`、`pptx`；预设见 `assets/journal_presets.json`。
- 自动自愈：转碰撞 X 刻度、外移遮挡图例、折行长标题；产出 300 DPI PNG、100 DPI 预览及含 `spec_embedded`/SHA-256/行号索引的 `.provenance.json`。
- **A-自定义**：Matplotlib 绘图 + `kit_common.apply_journal_style()` + `export_and_audit_figure(fig, "/app/output", "fig1", provenance={...})`。

#### B · 源保留编辑（`svg_edit.py --input`）
侦查（多页 PDF 加 `--find-text "Figure 3"`；解析 `<g transform>` 与 CSS 色板）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --inspect --input <原图> [--page 0] [--find-text "Figure 3"]
```
按 `references/chart_recipes.md` §3 写 `/app/work/ops.json`（`replace_text/set_text/set_style/recolor/set_attrs/move/delete/add_*`）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --input <原图> --ops /app/work/ops.json \
  --out-svg /app/output/fig_edited.svg --out-pdf /app/output/fig_edited.pdf \
  --out-png /app/output/fig_edited.png --preview /app/output/fig_edited_preview.png --dpi 100
```
`recolor` 穿透属性/内联/CSS `<style>`(`rgb()`/命名色)/`<g id>`；`set_attrs` 改几何；PDF 自动出 `<text>` SVG、`.provenance.json` 与同页重导。

#### C · 论文生物机制图（`svg_edit.py --diagram`）
1. 提取完整图注、`mechanism_sentences`、PTM/定量事实与 `figure_interior_labels(nx,ny)`：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --extract-pdf <paper.pdf> --query "Figure 3|Fig\. 3" --out-txt /app/work/paper.txt --render-hits /app/work/hits
```
2. 按 `references/chart_recipes.md` §2 写 `/app/work/mech.json`（`TB|LR`、`panels`、`role`、`receptor/dna/mitochondria/vesicle/outcome`、`compartments.nodes`、`bilayer/nucleus`、`complexes`、`badge/step`、`custom_ops`）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --diagram /app/work/mech.json --verify-pdf <paper.pdf> \
  --out-svg /app/output/figure03.svg --out-pdf /app/output/figure03.pdf \
  --out-png /app/output/figure03.png --preview /app/output/figure03_preview.png --dpi 100
```

#### D · 草稿落盘 `result.json`（标 `partial`）
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/make_result.py" --case-json /input/case.json \
  --out /app/output/result.json --status partial --case-id auto --auto-collect /app/output
```
`--auto-collect` 归集产物与 `.provenance.json` 并跑几何/边缘体检；缺契约字段用 `--set k=v` 或 `--extra extra.json`。

### 步骤 2 · 科学复核与精修定稿（1–3 步）
1. **JSON 闭环清零告警**：**严禁对二进制 `.png`/`.pdf` 调用 `read`**（避免纯文本环境报错或上下文膨胀），统一按脚本输出的 `action_required`、`glyph_value_audit`、`data_fidelity`、`svg_geometry`、`editable_svg`、`svg_text_audit`、`typo_suspects`、`annotation_audit`、`png_edge` JSON 闭环修正。
2. **科学核查（`references/checklists.md`）**：抽查 `source_line/col`；轴单位/量级、图例=系列、误差与 `n`、显著性源自源结论；机制图实体/PTM 逐字一致、区室与激活/T-bar 无误；无 CJK 改英文记 `uncertainty`。
3. **终版定稿**：`make_result.py`（`--status auto` 全通过升格 `complete` 且 `limits:[]`，否则 `partial` 并列 `action_required`；仅真有缺口加 `--limit`）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/make_result.py" --case-json /input/case.json \
  --out /app/output/result.json --case-id auto --auto-collect /app/output \
  --change '完成科学核查、数值/实体溯源与版式精修'
```

## 异常处理
| 情况 | 处置 |
|---|---|
| 缺列/空值 | 不补零不插值；柱图留空、热图灰底 NA；记 `missing_cells`/`uncertainty` |
| 重复观测 / >4 量级 | 自动聚合 `mean±SD` 留行号；科学计数或 `log_y`/SI |
| 长标签/图例遮挡 | 自动自愈，或 `barh`/`xticklabels_rotate:35`/`legend_loc:"outer_top"` |
| 无 CJK 字体 | `cjk_font=null` → 改英文记 `uncertainty` |
| 位图/转曲源图 | `text_count=0` → 叠加标注，`limits` 写明原字不可改 |
| 无脚本回退 | Matplotlib(`svg.fonttype="none"`, `pdf.fonttype=42`)或 XML 写 SVG 并手工落盘 `result.json` |

## 最小示例（Example）
`case.json` → `inspect_input.py --init-output` → `fig1.spec.json` → `chart_tool.py` → `make_result.py --status partial` → JSON 精修 → `make_result.py --auto-collect /app/output` → 示意输出 `fig1.svg/pdf/png` + `.provenance.json` + `result.json`(`complete`, `limits:[]`)。

## 资源与依赖
- `scripts/`：`inspect_input`、`chart_tool/spec/render`、`svg_edit/ops`、`check_layout`、`make_result`、`kit_common`；`references/`：`chart_recipes`、`style_presets`、`export_and_checks`、`checklists`；`assets/journal_presets.json`。
- 依赖：Python3 + matplotlib/Pillow/numpy；可选 PyMuPDF/python-pptx/chrome/rsvg-convert（`.xlsx/.pptx/.docx` 摘要零依赖）。
