# GA-Skill — 确定性科研图形摘要生成与保源编辑 Skill

面向科研论文、机制图与实验数据材料的单页图形摘要（Graphical Abstract）构建与既有图源外科式编辑工具包：将**研究问题 → 方法/机制 → 核心定量结果 → 结论**组织为自洽的分层可编辑 SVG 母版，同步导出 96 DPI 1:1 预览 PNG（≤108 DPI）与单页可检索矢量 PDF（按需支持 `--hires-dpi 300` 印刷位图），并输出可独立复核的 `result.json`。

## 架构与极速两步数据流

```
[路径 A: 新建图稿（4–6 轮极速闭环）]
材料 (PDF/CSV/TSV/XLSX) ──ga_intake.py──> 完整图/表注 + 章节定位 + 多子表/宽表统计
      │
      ▼  (Agent 仅撰写 brief.json，可内嵌 panel/block source 字段与可选 report.json)
ga_pipeline.py --brief ... --data-dir /input --case /input/case.json --deliver /app/output
      ├─ 确定性排版 ──> <stem>.svg (命名分层可编辑母版)
      ├─ 多引擎渲染 ──> <stem>.png (96 DPI 1:1 预览) + <stem>.pdf (单页可检索矢量 PDF)
      ├─ 内置全审计 ──> 越界/溢出/节点碰撞/遮挡/字号/色盲/源数据交叉核验
      └─ 一键交付   ──> /app/output/ 导出件 + result.json (含 scientific_inventory & 审计)

[路径 B: 保源编辑既有 SVG（4 轮极速闭环）]
源 SVG ──ga_svg_edit.py --inspect──> 图层/文本索引/几何坐标/配色清单
      ──ga_svg_edit.py --edits ... --case /input/case.json --deliver /app/output
         └─ 外科 DOM 补丁 + _edit_report.json 保源证明 + 重渲染 + --external 审计 + result.json
```

设计原则：**同一 `brief.json` → 字节级一致的 SVG 输出**（无时间戳、无随机数）。Agent 聚焦科学内容抽取、因果极性判断与证据映射；版式、图标、图表、防碰撞、渲染与导出校验全部由标准库 Python 脚本确定性完成。

## 目录与文件说明

| 路径 | 职责 |
|---|---|
| `SKILL.md` | Agent 执行卡：硬契约、双路径分流、设计清单、降级策略 |
| `scripts/ga_intake.py` | 限流勘察（Turn-1 stdout 硬控 ≤14 KB 防截断 + 全量落盘 `/app/work/_intake_full.json`）：`/input/case.json`、`task.md`、CSV/TSV、纯 stdlib 合并表头 `.xlsx`（支持 `--table <f> --sheet <name>` 定点提表）、`.docx`/`.json`/图片尺寸、SVG 摘要与 PDF 完整图注/目标图深挖/`--pdf-find`/`--pdf-pages` |
| `scripts/ga_pipeline.py` | 主管线：`brief.json` → 分层 SVG（`card`/`journal` 双主题、`hero-2x2`/`1+3`/`left-hero`/`stack`/`grid` 等版式、阶段对齐机制图、`paired`/`volcano`/对数轴 Prism 级图表、内嵌自定义 `svg` 块）+ 96 DPI（含 `pHYs`）PNG / 矢量 PDF + 智能目标文件名 + 内置审计、源数据核验与 `result.json` |
| `scripts/ga_check.py` | 全维静态审计：画布越界、面板溢出、机制节点碰撞、遮挡、文字重叠、字体/色盲/图层审计、`--data-dir` 二分查找源数据核验（支持 2000 行 XLSX、`paired`/`volcano`/箱线四分位/重复散点/`log10`/`-log10(p)` 与 100% 构成比）与文本反馈 `advisories` |
| `scripts/ga_svg_edit.py` | 保源编辑器：`--inspect`（含 `<tspan>`、`transform`、`inkscape:label`、`css_classes` 与 `--find` 全局检索）、`replace_text`（支持 `layer` 含 `inkscape:label`/`id`/`regex`/同步改样式）、`set_text_by_id`/`set_text_by_index`、`set_attr`（穿透 CSS 类）、`restyle_class`、`replace_color`、`scale_rect`、`translate`、`hide`、`delete`、`expand_canvas`（含白底）、`insert_svg`、`add_overlay` + `--deliver` 一键交付 |
| `scripts/ga_render.py` | 任意 SVG 按固有 `viewBox` 尺寸重渲染 96 DPI PNG + 矢量 PDF + 完整性校验 |
| `scripts/ga_result.py` | 扫描实际交付目录，自动抽取 `brief.json` 面板/图表溯源与 `scientific_inventory`，合并 `output_contract`、`export_specs`、`_build_report.json`、`_check_report.json`、`_edit_report.json` 与 `human_confirmation` |
| `scripts/gaconfig.py` | 画布常量、Okabe-Ito 衍生色盲安全系列色、Sequential 与 RdBu Diverging 热图色阶、角色配色与别名解析、SVG 尺寸解析 |
| `scripts/gadoc.py` `galayout.py` | 文档分层组装与自适应多拓扑引擎（`card`/`journal` 双主题、自定义 `badge`、`hero-2x2`/`2x2`/`hero-1+2`/`grid`/`row` + 双向 autofit 与稀疏面板平衡节奏） |
| `scripts/gablocks.py` `gachart.py` `gaicons.py` `gaprims.py` `textmetrics.py` | 内容块（含双层磷脂膜/核膜/细胞器独立标题徽章分区、阶段条 `stages`、白边光晕红 T-bar 抑制箭头、避边框边标签与交叉最小化机制图）、8 类定量图表（`bar`/`hbar`/`stacked`/`line`/`dot`/`box`/`scatter`/`heatmap`，支持对数轴 `xlog`/`ylog`、连接型剂量反应曲线、95% CI 误差带、KM 生存阶梯、生物重复散点、`%` 轴 100 封顶与防碰撞 `sig` 支架）、32 种科研矢量图标、原语与中英混排度量 |
| `references/brief-schema.md` | `brief.json` 完整字段与块类型参考 |
| `references/layout-spec.md` | 网格拓扑、字号阶梯、命名图层与导出规格 |
| `references/palette-and-legend.md` | 配色系统、图例与色觉无障碍阈值 |
| `references/failure-playbook.md` | 运行异常处置表、保源编辑流程与缺失材料诚实降级 |
| `assets/example_brief.json` | 最小调用示例（合成数据，仅演示接口） |
| `assets/example_mechanism_brief.json` | 机制图调用示例（合成数据，仅演示接口） |
| `assets/example_journal_fig_brief.json` | 发表级多面板生物图示例（`theme: "journal"` + 箱线图/KM 生存曲线，合成数据演示） |
| `assets/example_edits.json` | 路径 B 保源 SVG 外科补丁示例（合成数据演示） |

## 最小调用示例（合成数据演示）

```bash
python3 scripts/ga_pipeline.py --brief assets/example_brief.json --outdir /tmp/ga_demo
python3 scripts/ga_check.py --svg /tmp/ga_demo/example_brief.svg --brief assets/example_brief.json
```

保源编辑示例：

```bash
python3 scripts/ga_svg_edit.py --svg /tmp/ga_demo/example_brief.svg --inspect
python3 scripts/ga_svg_edit.py --svg /tmp/ga_demo/example_brief.svg --out /tmp/ga_demo/edited.svg \
        --old "100 uM" --new "100 μM"
python3 scripts/ga_render.py --svg /tmp/ga_demo/edited.svg --outdir /tmp/ga_demo
python3 scripts/ga_check.py --svg /tmp/ga_demo/edited.svg --external
```

## 依赖与环境兼容性

- **SVG 生成 / 审计 / 保源编辑 / 结果合并**：Python 3.8+ 纯标准库，零第三方依赖。
- **渲染导出链（自动降级）**：`google-chrome` / `chromium` → `soffice --headless` + `pdftoppm`（96 DPI）→ `rsvg-convert` → ImageMagick `convert`（96 DPI）。若全部不可用，仍交付完整可编辑 SVG 并在 `result.json` 中诚实标注 `status: "partial"`。
- **可选依赖**：Pillow（用于 PNG 非空白与精确裁剪校验，缺失时安全跳过）。
- **字体栈**：`DejaVu Sans, Arial, Helvetica, Noto Sans CJK SC, Noto Serif CJK SC, WenQuanYi Zen Hei, sans-serif`，支持中英文混排与基本 CJK 行首避头点禁则。

## 导出件规格

| 产物 | 规格 |
|---|---|
| `<stem>.svg` | 默认 1600×900（支持自定义 `canvas`），纯 SVG 1.1 原语，含 Inkscape 兼容命名图层（`layer-background` / `layer-title` / `panel-P*` / `layer-links` / `layer-footer`），全部文字保持可编辑 |
| `<stem>.png` | 与 SVG 画布 1:1 等尺寸位图（严格 96 DPI ≤ 108 DPI 预览），经非空白方差校验 |
| `<stem>.pdf` | 单页矢量 PDF（1600×900 px = 1200×675 pt），保留真实可检索文本层与无限打印分辨率 |
| `<stem>_300dpi.png` | 可选高分印刷位图（仅当显式传入 `--hires-dpi 300` 时按需生成） |

## 已知边界与诚实限制

- 所有定量数值与统计显著性必须来自真实输入材料；若材料缺数值，退化为定性结构图并在 `uncertainty` 中声明，绝不虚构数据。
- 文字宽度为基于 DejaVu Sans 校准的估算值（含 +6% 安全裕度），在缺乏对应系统字体的极端混排环境下建议配合 PNG 目检确认。
- 机制图自动分层面向有向因果/通路拓扑；强环状或空间自由排布可显式提供 `nx`/`ny`（引擎内置防撞分离）。
- 若需编辑的既有图源为纯位图（PNG/JPG）而非矢量 SVG，脚本无法直接做 DOM 级保源修改，需按 `failure-playbook.md` 重建分层 SVG 并标注 `status: "partial"` 与差异说明。
