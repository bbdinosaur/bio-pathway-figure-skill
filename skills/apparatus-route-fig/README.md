# apparatus-route-fig — 实验装置与技术路线图 Skill

面向科研场景的可复用绘图 Skill：从论文方法段、装置清单、生物实验流程、原始表格数据或既有 SVG 源文件出发，
产出**分层可编辑 SVG 源文件 + 300 dpi PNG/PDF 导出件 + 逐元素溯源（`data-prov` / `provenance.json`）+ 静态几何/溯源检查报告 + 完整 `result.json`**。

## 文件地图

```
SKILL.md                    精简四步执行卡（<=8KB）：路由、快速闭环、最小示例、降级与自查
scripts/
  sir.py                    SIR 校验 + 自然图字段别名零重试归一化 + activate/energy/inhibit + 中英双语自适应 + PIL 精确度量
  scene.py                  图面原语(rect/line/text/ellipse)与包围盒
  layout_flow.py            装置/流程：动态标题留白、主干优先拓扑分层、平行实验臂泳道对齐与虚线分组防碰撞、图元/柔影
  layout_edges.py           布线：直连主干中轴钉扎端口（消除平直臂锯齿）+ 分组框外让道/肘形/外廊/顶跨/底总线回流
  layout_roadmap.py         技术路线：动态标题与时长留白、自适应列宽、阶段卡片分节线与柔影、时间轴、里程碑
  roadmap_edges.py          路线：阶段交付与反馈迭代连线（多反馈错位）、跨阶顶落边、双行时长正确排布
  glyphs.py                 中英文化学/物理/生物学器件图元库（显微/病毒LNP/质谱光谱/抗体/DNA/孔板/动物/测序/离心/细胞/泵/阀/反应等）
  build.py                  组装：期刊级标题竖条与分隔线（空标题紧凑子面板模式）/右上角图标局部放大/虚线一致图例/边标签避线/溯源表
  svgfig.py                 scene→分层可编辑 SVG（显式矢量箭头与 T-bar + 跨引擎虚线 + data-role + data-prov 溯源）
  render.py                 SVG→PNG/PDF 五级渲染链 + CJK 字体探测 + 自有 SVG 零改写直通 + 外部 CSS/tspan 兼容层
  mirror.py                 matplotlib 镜像渲染兜底
  checks.py                 越界/节点重叠/文本重叠与超宽/边标签穿线/端点贴合/穿框/图例/溯源覆盖率检查
  run_all.py                一键总管线（单图+多图 + 96dpi 预览 + 严格路径映射 result_skel）
  compose_panels.py         一键多面板学术复合图无损 SVG 合成器（支持内联 sir/chart 与既有 svg + ID/defs 隔离 + A/B/C + 合并溯源与自检）
  extract.py                中文工艺文本→SIR 草稿启发式起草（需逐条核对）
  pdf_probe.py              科研论文 PDF 探针与按页提取（无平台 PDF 工具时备用：pymupdf→pdftotext→pypdf→限时 pdfplumber）
  table_probe.py            零依赖源数据表探针与加载器（CSV/TSV/JSON/XLSX 纯标准库兜底，Unicode 负号/均值±误差/表题与表尾注剥离）
  chart_kit.py              科研数据图一键（宽表/长表 + 别名容错 + volcano 火山图/点标注/step 生存曲线/2D非对称误差/组内括号/OLS/热图/双Y轴）
  svg_edit.py               保源 SVG 编辑（嵌套与多 tspan 换行/批处理别名容错与多属性 attrs/变换 abs_xy/折线箭头/diff untouched_ratio）
  audit_delivery.py         交付前零依赖契约与落盘核验（严格区分 schema 必填键与描述键，零误报）
references/
  sir-spec.md               SIR、chart_kit 与 svg_edit 完整字段/参数规范
  style-guide.md            配色、版式、导出规范与无脚本 matplotlib 模板
  failure-playbook.md       12 类异常与降级处置矩阵
```

## 依赖与可移植性

- 核心布图、静态检查、SVG 生成与保源编辑仅依赖 Python 3.8+ 标准库（`PIL` 可选，用于更精准的字宽测量）。
- SVG 渲染按序尝试：`rsvg-convert` → `cairosvg` → `inkscape` → `pymupdf` → `soffice` → `matplotlib` 镜像渲染；
  任一引擎可用即可产出 PNG/PDF。无中文字体时自动探测并在结果中诚实记录降级。
- `chart_kit.py` 依赖 `matplotlib`，并设置 `svg.fonttype=none` 与 `pdf.fonttype=42` 以保留可编辑文本。
- 所有脚本通过 `Path(__file__).resolve().parent` 定位，无工作目录硬编码依赖。

## 适用边界与限制

- 聚焦实验装置、生物/工艺流程、材料流向、技术路线、真实数据绘图与保源 SVG 修改；不编造缺失参数（缺参标 `"TBD"` 并写入 `uncertainty`），不改动原始实验数据。
- 单张流程图/装置图建议 ≤14 节点；超出时使用顶层 `figures: [...]` 拆分为主图与子图或借助 `zoom` 局部放大面板。
