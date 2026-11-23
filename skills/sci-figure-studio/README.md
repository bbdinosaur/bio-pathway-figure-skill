# Sci-Figure-Studio — 科研数据图表生成、生物机制图构建与源保留编辑 Skill

面向科研论文、学位论文与学术汇报场景的端到端科研绘图与编辑 Skill。核心原则：**图元忠实于源数据与原始文献、文字保持 `<text>` 可再编辑、全链路自动化双向溯源与几何自检**。

## 目录结构

```text
.
├── SKILL.md                     # Agent 主执行卡（精炼 P0→P1→P2 闭环）
├── README.md                    # 本说明文档（接口、依赖、预设与限制）
├── assets/
│   └── journal_presets.json     # 可直接复用的期刊/论文/PPTX 样式预设
├── references/
│   ├── chart_recipes.md         # 数据图 spec、机制图 --diagram 与编辑 ops 语法
│   ├── style_presets.md         # 期刊字号、线宽、Okabe-Ito 色盲友好色板与中文字体规则
│   ├── export_and_checks.md     # 导出参数、六类检查点与 result.json 契约说明
│   └── checklists.md            # P0/P1/P2 终审速查清单
└── scripts/
    ├── inspect_input.py         # 步骤 0 一步式输入全景侦查（case/contract/数据表统计/PDF 候选实体/SVG 文本/字体与路由建议）
    ├── chart_tool.py            # 数据图主入口（绘图 + SVG/PDF/PNG/PPTX + 溯源 + 自检）
    ├── chart_spec.py            # 数据解析（CSV/TSV 跳注释与 GBK 容错/零依赖 XLSX/JSON/filter/x_order/sort_x/非对称误差/重复聚合）
    ├── chart_render.py          # 12 种图型 + 双 Y 轴 + 线性回归(fit_line/R²) + 语义显著性括线 + 双向图元数值审计
    ├── svg_edit.py              # 源保留编辑(多页 PDF 同步+差分审计)、PDF 提取(--extract-pdf)与 TB/LR 机制图(--diagram, role/complexes)
    ├── svg_ops.py               # SVG 原语（replace_text/set_style 斜体字号/按色或按 id 变色/质膜区室/PTM 徽章/T-bar/圆角走廊）
    ├── check_layout.py          # 无外部依赖 SVG 几何越界/重叠静态检查 + PNG 边缘裁切检查
    ├── make_result.py           # 幂等组装 result.json、六检查点汇总并按 output_contract 校验补全
    └── kit_common.py            # 公共工具（字体探测、脏 CSV 读取、Unicode 负号/Inf 过滤、SVG/PDF/PNG 转换降级链）
```

## 核心能力与六类检查点

1. **科学实体保真与接地审计**：`inspect_input.py --compact` 与 `--extract-pdf` 一次提取原论文 PDF 全文、单/双换行完整 Figure 图注（上限 2,500 字）、因果 `mechanism_sentences`、高频候选科学实体词表、**命中页空间矢量标签 `spatial_labels(x,y)`** 与 100 DPI 页图渲染；`--diagram --verify-pdf` 清理 PDF 断行连字符后逐字校验全部节点实体拼写并给出纠错建议。
2. **空间关系与生物机制图 (`svg_edit.py --diagram`)**：支持纵向细胞分层 (`direction:"TB"`) 与横向通路流程 (`direction:"LR"`) 双模式；支持节点生物学角色自动语义配色 (`role`)、多蛋白复合物包络框 (`complexes`)、统一区室框（含质膜双线 `style:"membrane"`）、PTM 修饰徽章 (`badge:"P"/"Ub"`)、**平滑正交 90° 入框曲线 (`route:"smooth"`, 消除斜切 T-bar)**、同层双向反馈平行分离、外侧圆角走廊防穿框、长标题/长图注自动换行与语义图例，同步输出 `.svg/.pdf/.png(300 DPI)/_preview.png(100 DPI)` 与 `.provenance.json`。
3. **数据编码与双向图元数值审计 (`chart_tool.py`)**：支持 12 种图型（`bar/grouped_bar/stacked_bar(normalize_pct)/barh/line(error_style:"band")/errorbar/scatter/box/violin/pie/donut/heatmap`）、双 Y 轴柱折线组合图 (`secondary_series`+`ylabel2` 右轴同色着色)、数值散点线性拟合 (`fit_line`/干净回归方程与 $R^2$/点标签避让拟合线)、宽矩阵热图自动识别与逐格溯源、tidy/宽表/零依赖 `.xlsx`、`data.filter`（保原始物理行号）、`x_order`/`series_order`/`sort_x`、非对称误差棒、零中心发散热图 (`vcenter`)、语义显著性括线与重复观测自动聚合 (`mean±SD`)；渲染后自动执行 **`glyph_value_audit`**、MathText 兼容 `svg_text_audit` 与 `annotation_audit`。
4. **源保留编辑 (`svg_edit.py --input`)**：改前 `--inspect` 输出精准坐标、字号与颜色；SVG 支持保留多行 `<tspan>` 的 `replace_text`、穿透子 `<tspan>` 的 `set_style`、按色/按 id `recolor`、按 id/文本 `move`/`delete` 与新增原语；PDF 严格对齐 `exact`/`contains`/`regex` 整 span 红改保彩底，含 `recolor`/`set_style`/`move`/`delete` 时单/多页 PDF 自动同步重导该页，并自动输出 `--out-png`（300 DPI + `png_edge`）、`edit_diff_audit` 与 `.provenance.json`。
5. **可编辑源文件与投稿级导出**：强制 `svg.fonttype="none"` 与 `pdf.fonttype=42`，同步交付 `.svg` + `.pdf` + `.png`（可选 `.pptx`），并提供 `assets/journal_presets.json`（Nature / Science / Cell / 通用期刊 / 学位论文 / 16:9 汇报预设）。
6. **自动自检与六检查点汇总**：每次成图自动执行 `editable_svg`、`legend_series_match`、`glyph_value_audit`、`svg_text_audit`、`annotation_audit`、`svg_geometry`（越界/重叠）与 `png_edge`（裁切/留白），由 `make_result.py` 汇总写入 `result.json`。

## 运行环境与依赖

- **必需**：Python 3.9+，`matplotlib`，`numpy`，`Pillow`（均为常见科研容器预装包；`.xlsx` 已内置纯标准库解析器，无需 `openpyxl` 即可直读多工作表）。
- **可选（均内置优雅降级，缺失不中断核心交付）**：
  - `PyMuPDF (pymupdf/fitz)`：PDF 文本与空间标签提取、编辑与栅格化（缺失时文本提取降级至 `pdfplumber`）。
  - `openpyxl`：可选加速 `.xlsx` 读取（缺失时自动切换纯标准库 `zipfile`+XML 解析器）。
  - `python-pptx`：启用 `export.pptx=true` 时产出可编辑汇报幻灯片。
  - `rsvg-convert` / `inkscape` / `cairosvg` / `chromium`：SVG→PDF/PNG 渲染（自动按可用链切换）。
- **中文字体回退**：按 `Noto Sans CJK → Source Han → WenQuanYi → SimHei → YaHei` 自动探测；无 CJK 字体时写入 `provenance.fonts.cjk_font=null`，提示切换英文并在 `uncertainty` 如实记录。

## 最小调用示例（Example，非正式案例结果）

```bash
# 1. 示例：数据图生成（宽表/长表 CSV/XLSX/JSON 均支持）
python3 scripts/chart_tool.py /app/work/fig1.spec.json --outdir /app/output --base fig1

# 2. 示例：从原论文 PDF 提取 Figure 3 相关文本并构建生物机制图
python3 scripts/svg_edit.py --extract-pdf /input/paper.pdf --query "Figure 3|Fig\. 3" --out-txt /app/work/paper.txt --render-hits /app/work/hits
python3 scripts/svg_edit.py --diagram /app/work/mech.json --verify-pdf /input/paper.pdf \
  --out-svg /app/output/figure03.svg --out-pdf /app/output/figure03.pdf \
  --out-png /app/output/figure03.png --preview /app/output/figure03_preview.png --dpi 100

# 3. 示例：既有图稿源保留编辑
python3 scripts/svg_edit.py --inspect --input /input/orig.pdf --page 0
python3 scripts/svg_edit.py --input /input/orig.pdf --ops /app/work/ops.json \
  --out-svg /app/output/fig_edited.svg --out-pdf /app/output/fig_edited.pdf \
  --out-png /app/output/fig_edited.png --preview /app/output/fig_edited_preview.png --dpi 100

# 4. 示例：几何终检与自动汇总 result.json
python3 scripts/check_layout.py /app/output/fig1.svg --json /app/work/fig1.layout.json
python3 scripts/check_layout.py --png /app/output/fig1.png
python3 scripts/make_result.py --case-json /input/case.json --out /app/output/result.json \
  --case-id auto --auto-collect /app/output --check /app/work/fig1.layout.json
```

## 适用范围与已知限制

- 聚焦科研数据可视化、机制/流程示意图与图稿源保留编辑，不代替原始实验统计假设检验（显著性标记须来自源材料给定结论）。
- 导出色彩空间默认 sRGB（白底）；若期刊要求 CMYK，需在 `result.json` 的 `uncertainty` 中注明由印刷端转换。
- 若输入图稿为纯位图或文字已转曲（`editable_svg.text_count=0`），无法直接修改原文字，将采用叠加标注并在 `limits` 如实说明。
