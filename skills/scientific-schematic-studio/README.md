# Scientific Schematic Studio — 科研示意图生成与编辑 Skill

用途：从科研原始材料（论文 PDF / Word / PPTX / CSV / TSV / 多表 XLSX / 既有 SVG / 草图）生成或保源编辑**可直接进论文、答辩稿与基金本子**的科学示意图：机制通路、实验流程、结构关系、多面板网格组合图及源数据直连定量面板。  
交付同源件：分层可编辑 `.svg`（语义 `<g id>` + 可选 `<text>`）+ 嵌字 `.pdf` + 300/600 DPI `.png` + 100 DPI `_preview.png` + 含来源溯源、SHA-256 源数据核验、审计与修改记录的 `result.json`。

## 适用条件与边界
- **平台契约**：Harbor Skill（输入 `/input/case.json` + `task.md`，输出 `/app/output/result.json` 与可编辑/导出文件；预算 64 请求 / 900s / 16k tokens）。
- **适用图型**：分子机制与信号通路（含嵌套亚细胞区室与双层膜顶边）、实验流程图、结构关系图、多面板网格组合图、源数据直连定量图（`bar`/`barh`/`stacked_bar`/`line`/`scatter`/`box`/`heatmap`，支持长表/宽表多列重复自动汇总 `mean±SD/SEM` + 原始散点 + 显著性括号 + 同 sheet 多子表/分列块切片）、外部 SVG 保源精改。
- **明确不负责**：统计检验方法选择与假设检验推导、封面艺术插画、论文正文综述写作。

## 依赖、路径与字体配置
- **必需运行环境**：Python ≥ 3.8 + `matplotlib` + `numpy` + `Pillow`（平台 `scientific-python` 已预装）；XML/CSV/XLSX/DOCX/PPTX 均采用 Python 标准库零依赖解析（坐标对齐 `<c r="C5">` 避免稀疏表错列）。
- **可选系统工具（自动降级链）**：PDF 读取与核验 `pymupdf(fitz)` → `poppler-utils` (`pdfinfo`/`pdffonts`/`pdftotext`)；SVG 渲染 `cairosvg` → `rsvg-convert` → `inkscape` → `libreoffice + pdftoppm`；图片草图文字识别 `tesseract`（可选）。
- **字体与跨平台安装**：默认嵌入 TrueType（`pdf.fonttype=42`, `svg.fonttype='none'`），优先 `DejaVu Sans` / `Liberation Sans` / `Arial`，含中文时自动切换 `Noto Sans CJK SC` / `WenQuanYi Zen Hei`。Linux 安装命令：`apt-get install -y fonts-dejavu-core fonts-liberation fonts-noto-cjk`；核查命令：`fc-list : family | sort -u`。
- **路径与免安装**：全部脚本通过 `Path(__file__).resolve().parent` 自定位，加载于 `/skills/weekly-skill` 时直接运行，无硬编码本机路径。

## 可复用资产与参考规范
| 路径 | 用途 |
|------|------|
| `assets/journal_presets.json` | 运行时加载的期刊导出预设（`nature_single`/`nature_double`/`cell_double`/`science_double`/`pnas_double`/`grant_figure`/`slide_16_9`）、Okabe-Ito 色盲安全色板与关系图形语法 |
| `assets/templates.json` | 3 套领域无关可复用图稿骨架模板（`signaling_pathway_tb` / `experimental_workflow_lr` / `mechanism_plus_source_data_grid`） |
| `references/layout_rules.md` | 分层排布、避障路由、边距与防重叠规则 |
| `references/style_tokens.md` | 字号层级、语义配色与命名图层规范 |
| `references/export_presets.md` | 期刊物理尺寸、DPI、嵌字与合规检查标准 |
| `references/result_schema.md` | `result.json` 与 `plan.json` 完整 Schema |
| `references/failure_playbook.md` | 材料缺失、矛盾、渲染降级与异常处理手册 |

## 完整调用步骤（推荐两步一键管线）
1. **输入侦察与保底落盘**：
   ```bash
   python3 /skills/weekly-skill/scripts/run_pipeline.py prepare --input /input --work /app/work --out /app/output
   ```
   自动解析 `case.json`/`task.md`、抽全 PDF 至 `pdf_extract.txt`（置顶目标图注与行号）、解析 DOCX/PPTX/坐标对齐 XLSX/CSV/SVG（含未命名边 `edges`）/图片 OCR，并立即写保底 `/app/output/result.json`（`status=partial`）。
2. **单份 `plan.json` 一键生成/编辑、审计与终态交付**：
   ```bash
   python3 /skills/weekly-skill/scripts/run_pipeline.py deliver /app/work/plan.json --input /input --work /app/work --out /app/output
   ```
   自动完成布局渲染或保源编辑 → 几何/溯源/SHA-256 源数据保真审计 → 期刊导出合规检查 → 装配终态 `/app/output/result.json` → 输出纯文本 `DELIVER SUMMARY`。

独立模块亦可按需单步调用：`read_case.py`、`build_figure.py`、`edit_svg.py`、`build_pptx.py`、`audit_figure.py`、`export_check.py`、`make_result.py`。

## 最小调用示例（EXAMPLE — 仅示意接口，非评测案例）
- **示例输入**（`/app/work/plan.json`）：
  ```json
  {"case_id": "EX-01", "stem": "demo_fig", "preset": "nature_double",
   "panels": [{"id": "p1", "type": "schematic", "direction": "LR", "title": "Example Cascade",
     "nodes": [{"id": "A", "label": "Stimulus", "shape": "ellipse", "rank": 0, "source": {"file": "paper.pdf", "locator": "p.2"}},
               {"id": "B", "label": "Effector", "shape": "gene", "rank": 1, "source": {"file": "paper.pdf", "locator": "p.2"}}],
     "edges": [{"from": "A", "to": "B", "kind": "activates", "label": "activates", "source": {"file": "paper.pdf", "locator": "p.2"}}]}]}
  ```
- **示例调用**：`python3 scripts/run_pipeline.py deliver /app/work/plan.json --input /input --work /app/work --out /app/output`
- **示例输出**（EXAMPLE 示意）：`/app/output/demo_fig.svg` + `.pdf` + `.png` + `_preview.png` + `result.json`（含 `status: "ok"`、`entity_inventory`、`relation_inventory`、`checks.geometry_audit`、`checks.export_compliance`、`sources`、`change_records`）。

## 关键方法与创新点
1. **确定性出版级布局与复合 SVG 图层引擎**：renderer 实测文本尺寸 + 组感知 barycenter 排布 + LR/TB 双向区室边界自动加宽（零区室碰撞）+ 避障自反馈环 + 同义词规范化 + 语义自动着色边 + 节点造型与边双态图例 + 面板序号防重复/窄栏标题自适应缩放 + SVG 复合图层后处理（`<g id="node-X" data-layer="node" data-source="...">`、全局唯一 XML `id`），零重叠零越界可审计。
2. **坐标对齐真实源表直连与 SHA-256 均值+误差棒核验**：零依赖解析稀疏单元格与水平合并表头（`<mergeCell>`）XLSX、`section_match` 垂直多子表定位、`col_range` 分块、`orient:"columns"` 宽表多列重复自动聚合、`"mean ± SD"` 单元格自动拆解均值与误差棒、容错列名匹配与按类别语义着色；审计阶段独立重读源文件逐点比对并写入 `result.json.data_mapping`/`compartments`/`legend_mapping` 与 `source_sha256`。
3. **无盲区外部与复合 SVG 保源编辑**：`edit_svg.py` 支持嵌套 `translate()`/`scale()`/`matrix()` 仿射世界坐标与 `<tspan>` 坐标读取、CSS `<style>` 类覆盖（内联 `style` 同步写入）、弯曲贝塞尔箭头（`C`/`Q`）识别与精确反转、复合图层整组安全编辑（`retext` 自动保护 `badge`）、命名/未命名边 `edge_idx`/`by_text`/`gid` 定位、`from_text`+`to_text` 自动连线、着色同步箭头/T 杠与多行自动换行图例，始终保留 `original_*.svg`。
4. **一步吃透原论文 + 双审计闭环**：`prepare` 置顶目标 `Fig. N`/`Table N` 完整图注与全文结果段引用、抽取 PDF 内嵌结构化表格（`[TABLE p.N]`）、打印 XLSX `A|B|C` 列标；几何/穿节点边/分组误包/溯源/数据审计 + 期刊导出合规检查（含 SVG 复合图层与 XML ID 唯一性）；失败与边界如实记入 `limits`/`uncertainty`。

## 自查与维护
- 一键回归自检：`python3 scripts/self_test.py`（涵盖 43 项端到端检查：机制图/自反馈环/邻层双向平行反馈/TB 同层非邻避障弧/折行多排 LR 零穿节点路由/LR+TB 双向多区室防撞与非成员自动外推/节点造型图例/标题序号去重/水平+垂直合并单元格+重复列名自动聚合+`col_groups`+Unicode 负号科学计数法+`section_match` 跨列区+对数显著性括号+长标签自动换行 `barh` 散点+零剂量 `symlog` 护栏+`"mean ± SD"`+部分缺失误差棒容错+长表多子表扫描/SHA-256 均值+误差棒核验/LLM Schema 容错规范化/复合 SVG 图层与干净 XML 命名空间/Illustrator CSS+`matrix()`+弯曲贝塞尔+孤立多边形箭头清理+外部 `<marker>` 克隆同步换色+多节点 `<g>` 安全 `move`/`delete`+`from_text`+`to_text` 语义边定位与编辑后关系图收割+SVG 1.1 安全白底胶囊标签+`add_group` 区室保源编辑/多 PDF 零页码冲突+跨空行多段主图注+扫描 PDF OCR 兜底+中文 PDF 探针+`[PDF_READ_HINT]`+`EDIT_ERRORS` 强拦截/十六进制 `legend_mapping`+`provenance_summary`+`source_manifest`+对立边与悬空组审计/纯文本实绘数值核验/两步极速管线）。
