# SIR 与全管线输入规范速查

所有输入 JSON 均用 UTF-8；每个科学实体/连接/系列须带 `source: {"quote": "原句短摘录", "loc": "文件/页/节/表"}`。
引擎已内置常见字段同义容错（如 `edges`→`links`、`target`→`to`、`values`→`y`、`op`/`new`→`action`/`value`），减少无效重试。

## 1. 装置图 / 流程图 / 生物机制图（`kind = "apparatus" | "flow"`）

```json
{
  "kind": "apparatus", "title": "图题", "subtitle": "补充说明(可选)", "language": "zh|en",
  "nodes": [
    {"id": "p1", "step": "1", "label": "注射泵A", "type": "input", "group": "进料单元",
     "attrs": {"流速": "1.0 mL/min"}, "zoom": ["细目1", "细目2"],
     "source": {"quote": "…", "loc": "paper.pdf p3"}}
  ],
  "links": [
    {"from": "p1", "to": "mix", "kind": "material", "label": "载液", "bidirectional": false,
     "source": {"quote": "…", "loc": "paper.pdf p3"}}
  ],
  "legend_note": "可选", "prov_footer": "可选"
}
```

- **节点 `type`**：`apparatus` 装置、`process` 步骤/处理、`decision` 判定、`start`/`end` 起止、`input`/`output` 输入输出、`waste` 废料、`storage` 缓冲/样本库、`measure` 检测/成像（自动兼容 `sample`/`reagent`/`assay`/`sensor`/`cell`/`treatment`/`device`/`reactor` 等自然别名）。
- **连接 `kind`**：`material` 物料/主流程（蓝实线）、`activate` 激活/促进（绿实线）、`inhibit` 抑制/阻断（红实线+平头 T-bar）、`energy` 能量/光热（琥珀虚线）、`signal` 信号/控制（紫虚线）、`data` 数据/读出（青点线）、`loop` 回流/循环（橙虚线，底总线绕行）。设 `bidirectional: true` 画双向箭头。
- **增强字段**：`step` 编号徽章（左上圆角标）；`group` 同类部件/平行实验臂分组（同带成员自动绘制虚线子系统框+平行泳道对齐，跨带降级左侧色条）；`icon` 显式图元（缺省按 label 自动匹配：基因/DNA/CRISPR、抗体/受体、小鼠/动物、质谱/色谱、流式/FACS、显微/荧光、测序、PCR、凝胶、离心、细胞/培养、移液、泵/阀/混合/盘管/光/反应/瓶/检测/控制/塔/滤/分离/加热/冷却，设 `"none"` 关闭）；`layer` 显式列号；`zoom` 局部放大面板；顶层 `figures: [子SIR1, ...]` 多图拆分。单图建议 ≤14 节点（`--maxcols 4..6`）。

## 2. 技术路线图（`kind = "roadmap"`）

```json
{
  "kind": "roadmap", "title": "技术路线", "language": "zh|en",
  "phases": [
    {"id": "ph1", "name": "阶段一", "duration": "M1–M3",
     "goals": ["…"], "methods": ["…"], "tasks": ["…"], "milestones": ["M1 …"],
     "inputs": ["…"], "outputs": ["…"], "deliverables": ["…"], "criteria": ["…"],
     "source": {"quote": "…", "loc": "…"}}
  ],
  "phase_links": [
    {"from": "ph1", "to": "ph2", "kind": "handoff|feedback", "label": "交付物",
     "source": {"quote": "…", "loc": "…"}}
  ]
}
```
各内容节均可省略；阶段建议 2–6 个；`handoff` 绿实线交付（跨阶走顶部拱桥），`feedback` 橙虚线底部回绕。

## 3. 源数据表探针与科研图表（`table_probe.py` + `chart_kit.py`）

- 探查 CSV/TSV/JSON/XLSX（纯标准库兜底，自动跳过表题行并重命名重复表头）：
  `python3 <skill>/scripts/table_probe.py /input/data.xlsx [--sheet Sheet1] [--head 5]`
- 单面板或 `panels: [panel1, ...]` 多面板（支持 `ncols`、`panel_label`、`figsize`、`legend_loc: "outside_top"|"outside_right"`）：
```json
{
  "title": "主标题", "subtitle": "可选", "xlabel": "X轴(单位)", "ylabel": "Y轴(单位)",
  "kind": "line | step | bar | barh | stacked_bar | scatter | volcano | box | violin | hist | heatmap",
  "xscale": "linear|log", "yscale": "linear|log", "xlim": [0, 60], "ylim": [0, 100], "y2label": "右侧Y轴(可选)",
  "hlines": [{"y": 50, "label": "IC50"}], "annotations": [{"x": "KO", "y": 82, "text": "***"}],
  "brackets": [{"x1": "Ctrl", "x2": "High", "text": "***", "s1": "可选组内系列", "s2": "可选组内系列"}],
  "series": [
    {"name": "WT", "table": "/input/data.csv", "x_col": "dose", "y_col": "expr", "yerr_col": "sd",
     "filter": {"genotype": "WT"}, "agg": "mean_sd|mean_sem(可选)", "band": false, "y2": false,
     "source": {"quote": "Table S1", "loc": "data.csv"}}
  ],
  "prov_footer": "Source: data.csv"
}
```
- **直连源表**：支持长表（`x_col`/`y_col`+`group_col`+可选 `label_col`）或宽表多列（`y_cols: [...]`+可选 `yerr_cols`）；重复行设 `agg: "mean_sd"|"mean_sem"` 自动算均值/误差棒并叠加原始散点；自动拆分 `"42.5 ± 3.1"`、兼容 Unicode 负号 `−`/Excel 公式错误与剥离末尾表注，记录 `sha256_12`/`data_sha12`/`verified_exact`/`total_points_plotted`。支持 1D 对称与 2D 非对称 `yerr: [[lo...], [hi...]]`。
- **专用图型**：`kind="step"`（`survival`/`km`）支持 KM 阶梯曲线、`y_lo`/`y_hi` 置信带与 `censored_x` 删失刻度；`kind="volcano"` 支持直连原始 `p_col`/`padj_col`（自动 `-log10(p)`）或 `y_col`、`fc_thresh`/`p_thresh` 三色分类、阈值虚线与防重叠 `label_col` 标注；`scatter` 支持 `trendline: true`（OLS `R²/r`）；`box` 自动叠散点；`heatmap` 支持矩阵或直连表；`brackets` 兼容对数及分组柱状图组内（`s1`/`s2`）括号。

## 4. 一键多面板学术复合图拼版（`compose_panels.py`）

将任意面板无损合成为单张可编辑 SVG + 300dpi PNG/PDF：**每个面板既可传既有 `"svg"`，也可直接内联 `"sir":{...}`（或 `"sir_file"`）与 `"chart":{...}`（或 `"chart_file"`）由单条命令一步生成并拼合**（临时目录渲染子 SVG，不污染 `/app/output/`），自动隔离 `id`/`defs`/`clipPath`、剥离重复标题/页脚、汇总子面板检查与合并 `provenance.json`：
```json
{"title": "Figure 3. Mechanism & Quantification",
 "rows": [[{"label": "A", "title": "Experimental Workflow", "sir": {"kind": "flow", "nodes": [], "links": []}}],
          [{"label": "B", "title": "Volcano DEGs", "chart": {"kind": "volcano", "table": "/input/deg.csv", "x_col": "log2FC", "y_col": "neglog10p", "label_col": "gene"}},
           {"label": "C", "title": "Survival Curve", "svg": "/app/work/panel_c.svg"}]],
 "footer": "Source: paper.pdf Fig. 3; SourceData_Fig3.xlsx"}
```

## 5. 保源 SVG 编辑（`svg_edit.py`）

兼容分层 `data-id` 及外部标准 `id`/嵌套与多 `<tspan>`/`\n` 真多行/CSS `<style>`/`transform` 绝对坐标 `abs_xy`，保留原 XML 命名空间：
- 探查：`info 原图.svg` / `find 原图.svg [--text 词] [--id 标识]`
- 单步：`set-text` / `set-attr [--recursive --tag rect]` / `translate` / `add-text` / `remove` / `diff` / `export`
- 批量（推荐多处修改一次完成）：`batch 原图.svg --ops edits.json --out /app/output/edited.svg --export-dir /app/output --preview /app/work/preview.png --case-id CASE --contract /input/case.json --result-skel /app/work/result_skel.json`
  `edits.json` 支持操作：`set-text`、`set-attr`（`attr`/`attrs` + `recursive`/`tag`）、`replace-color`（全局或按 `scope_id` 批量色盲友好换色 `map` 覆盖属性与 CSS）、`translate`、`add-text`（支持 `\n`）、`add-rect`、`add-arrow`（直线/折线 `pts` + `label` + `tbar`/`arrowboth`）、`pad-canvas`、`remove`。输出 `diff` 与 `untouched_ratio`。

## 6. 辅助工具（按需）

- **多表探针**：`table_probe.py /input/SourceData.xlsx [--all-sheets]` 一次索引多工作表列名、行数与统计（纯标准库兜底）。
- **PDF 探针（仅当平台无 `pdf-text`/`pdf-render` 工具时）**：`pdf_probe.py /input/paper.pdf --summary | --search "Figure 3" | --pages 3-5 | --render-page 4 --out /app/work/p4.png --dpi 100`
- **交付前契约复核（可选）**：`audit_delivery.py --out /app/output --contract /input/case.json`（校验 `result.json`、`case_id`、必填键无 `<待填`、PNG IHDR 与 SVG `<text>`）。
