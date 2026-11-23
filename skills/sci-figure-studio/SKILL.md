---
name: "sci-figure-studio"
description: "科研数据图表生成、生物机制图构建与图稿source-preserving编辑：从源数据表或原论文出发，产出可编辑SVG（文字保持<text>不转曲）、投稿级PDF/PNG、元素级数据/实体溯源与变更日志，自动执行可编辑性、图例一致性、图元数值双向核验与几何越界/重叠自检。"
---

# Sci-Figure-Studio — 科研图表与机制图执行卡

## 触发与原则
- 触发：`/input/case.json` 或 `/input/task.md` 含科研绘图、改图或机制图工单（如 `source_value_chart`、`figure03`）。
- 六检查点：科学实体、空间关系、数据编码、图例标注、可编辑源文件（`<text>` 不转曲）、导出格式（SVG+PDF+PNG）。
- 终态产物（全落 `/app/output/`）：`result.json`（含 `case_id` 与全部 `output_contract` 字段）+ 可编辑 SVG + PDF/PNG（预览 ≤108 DPI）+ `.provenance.json`。
- 铁律：以实际输入与原论文为准；不造数不补零；实体名逐字复制；不虚构跑分；缺口诚实标 `partial`/`limits`。

## 步骤 0 · 探测输入（1 次 bash）
```bash
mkdir -p /app/work /app/output
find /input -maxdepth 4 -type f | sort
cat /input/case.json 2>/dev/null; echo "=== TASK.MD ==="; cat /input/task.md 2>/dev/null
SKILL_DIR=/skills/weekly-skill
[ -f "$SKILL_DIR/scripts/chart_tool.py" ] || SKILL_DIR=$(dirname "$(dirname "$(find /skills -name chart_tool.py 2>/dev/null | head -1)")")
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/inspect_input.py" /input --compact --json /app/work/input_summary.json
```
读完实际材料后再动工：核清 `case_id`、源数据/原论文路径、图型与样式约束、`output_contract` 必需字段与 `cjk_font`。

## 步骤 1 · P0 最短闭环（≤4 次请求产出首版）
按工单分派（可组合多图）：数据表→**A**；既有 PDF/SVG 修改→**B**；原论文机制图→**C**；产出后紧接 **D** 落盘。

### A · 数据图表生成（三格式 + 导出审计 + 溯源 + 双向自检）
1. 按 `references/chart_recipes.md` §1 写 `/app/work/fig1.spec.json`：
   - 图型：`bar/grouped_bar/stacked_bar(normalize_pct)/barh/line(error_style:"band")/errorbar/scatter(fit_line)/box/violin/pie/donut/heatmap(vcenter:0)`；预设见 `assets/journal_presets.json`；高阶项（双 Y `secondary_series`、`data.filter`、`x_order`、`error_low/high`、`export.transparent`）见 recipe；
   - 数据：支持 CSV/TSV/XLSX(零依赖)/`json_file`、tidy/宽表 `y_cols` 及宽矩阵热图；重复观测自动 `mean±SD` 留行号（`show_points:true` 叠散点）；
   - 标注：轴带单位；>1e4 自动科学计数；散点避障；`legend_loc:"outer_top"/"outer_right"`；显著性 `auto:true`（取自源结论）；默认同步 300 DPI PNG 与 100 DPI 预览。
2. 运行：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/chart_tool.py" /app/work/fig1.spec.json --outdir /app/output --base fig1
```

### B · 既有图稿编辑（source-preserving）
1. 侦查（多页 PDF 先 `--find-text "Figure 3"` 定位页号，再 `--page N` 列坐标/字号/颜色）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --inspect --input <原图> [--page 0] [--find-text "Figure 3"]
```
2. 按 `references/chart_recipes.md` §3 写 `/app/work/ops.json`，运行：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --input <原图> --ops /app/work/ops.json \
  --out-svg /app/output/fig_edited.svg --out-pdf /app/output/fig_edited.pdf \
  --out-png /app/output/fig_edited.png --preview /app/output/fig_edited_preview.png --dpi 100
```
   PDF 自动产出 `<text>` SVG 与 `.provenance.json`；`exact/contains/regex` 同步红改保彩底；`recolor/move/delete` 自动重导该页 PDF。

### C · 生物机制图 / 通路图（读原文 + 区室 + 90° T-bar + 双向分离）
1. **先读原论文再画图**：提取完整图注、`mechanism_sentences`、实体、`spatial_labels(x,y)` 与 100 DPI 页图，核清实体原名、修饰(P/Ub)、区室与抑制 T-bar（严禁把抑制画成箭头）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --extract-pdf <paper.pdf> --query "Figure 3|Fig\. 3" --out-txt /app/work/paper.txt --render-hits /app/work/hits
```
2. 按 `references/chart_recipes.md` §2 写 `/app/work/mech.json`（`TB|LR`、`role` 配色、`complexes`、`badge`、`style:"membrane"`、平滑 90° 入框与双向平行分离），运行（`--verify-pdf` 查拼错）：
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py" --diagram /app/work/mech.json --verify-pdf <paper.pdf> \
  --out-svg /app/output/figure03.svg --out-pdf /app/output/figure03.pdf \
  --out-png /app/output/figure03.png --preview /app/output/figure03_preview.png --dpi 100
```
   （反馈/跨泳道自动走外侧圆角走廊防穿框；手工坐标用 `--blank 宽x高 --ops ops.json`。）

### D · 立即落盘首版 result.json（诚实，默认 `--status auto`）
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/make_result.py" --case-json /input/case.json \
  --out /app/output/result.json --case-id auto --auto-collect /app/output
```
查看 `missing_contract_fields`，自定义字段用 `--set key=val` 或 `--extra extra.json` 补齐。

## 步骤 2 · 精修与科学核查（P1，≤3 次请求）
1. 修错误：`glyph_value_audit`/`svg_geometry`/`editable_svg`/`svg_text_audit` 报错、`typo_suspects` 非空、`annotation_audit` 警告或 `png_edge` 裁切 → 修正重跑。
2. 科学核查（`references/checklists.md`）：抽查 `source_line/col`；轴单位+量级、图例=系列、误差线含义（SD/SEM/95%CI）与 `n`、显著性取自源结论；实体逐字一致、激活与 T-bar 无误；无 CJK 字体改英文并写 `uncertainty`。
3. 有图像读取能力时查看 100 DPI 预览 PNG 确认零重叠零裁切。

## 步骤 3 · 终检与定稿（P2，≤2 次请求）
```bash
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/check_layout.py" /app/output/<主图>.svg --json /app/work/layout.json
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/check_layout.py" --png /app/output/<主图>.png
python3 "${SKILL_DIR:-/skills/weekly-skill}/scripts/make_result.py" --case-json /input/case.json \
  --out /app/output/result.json --case-id auto --auto-collect /app/output \
  --check /app/work/layout.json --change '完成视觉复核/溯源与导出校验' --limit '无'
```
确保 `missing_contract_fields=[]` 且 `status="ok"`（若仍有客观缺口诚实标 `partial` 与 `limits`）。

## 异常处理速查
| 情况 | 处置 |
|---|---|
| 缺列/空值 | 不补零不插值；柱图留空、热图灰底 NA；记 `missing_cells`/`uncertainty` |
| 重复观测 / >4 量级 | 自动聚合 `mean±SD` 留行号；线性轴自动科学计数或 `log_y`/SI 词头 |
| 标签长/图例遮挡 | `barh`/`xticklabels_rotate:35`；散点避障；`legend_loc:"outer_top"/"outer_right"` |
| 无 CJK 字体 | `cjk_font=null` → 改英文标签并写 `uncertainty` |
| 位图/转曲源图 | `editable_svg.text_count=0` → 叠加标注编辑，`limits` 注明原文字不可改 |

## 无脚本兜底与最小示例（Example，非正式结果）
- 手绘 matplotlib 必设 `{"svg.fonttype":"none","pdf.fonttype":42,"axes.unicode_minus":False}`，产出 `.svg/.pdf/.png` + provenance + `result.json`。
- 示例：`case.json` → `fig1.spec.json` → `chart_tool.py` → `check_layout.py` + `make_result.py --auto-collect /app/output` → 示意输出 `fig1.svg/pdf/png` + `result.json`。

## 资源清单
- `scripts/`：`inspect_input`、`chart_tool/chart_spec/chart_render`、`svg_edit/svg_ops`、`check_layout`、`make_result`、`kit_common`。
- `references/` & `assets/`：`chart_recipes.md`、`style_presets.md`、`export_and_checks.md`、`checklists.md`、`journal_presets.json`、`README.md`。
- 依赖：Python3 + matplotlib/Pillow/numpy；可选 PyMuPDF/python-pptx/chrome/rsvg-convert（`.xlsx` 零依赖内置）。
