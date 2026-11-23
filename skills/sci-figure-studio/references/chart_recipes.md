# chart_recipes.md — 图表 spec、机制图 diagram 与编辑 ops 语法（按需读取）

## 1. 数据图表 spec JSON 结构（`chart_tool.py`）
```json
{
  "case_id": "…",
  "suptitle": "整图标题（可省）",
  "ncols": 2,
  "style": {"preset": "journal_single|journal_double|thesis|ppt_16x9",
            "width_mm": 89, "panel_h_mm": 55, "font_pt": 8, "despine": true},
  "panels": [ …每个面板一个对象… ],
  "export": {"png_dpi": 300, "pptx": false}
}
```
导出产物：`{base}.svg`（`<text>` 可编辑 + `<metadata>` 溯源）+ `{base}.pdf` + `{base}.png` + `{base}.provenance.json`（可选 `.pptx`）。

### panel 公共字段
- `id`: 面板标号（多面板自动加 `(a)(b)…` 左上角粗体）。
- `kind`: `bar | grouped_bar | stacked_bar | barh | line | errorbar | scatter | box | violin | pie | donut | heatmap`
  - 长分类名优先 `barh`；组成占比（扇区角度）用 `pie`/`donut`（provenance 自动记 `pct`）；分布密度用 `violin`/`box`。
- `xlabel` / `ylabel`: **必须带单位**，如 `"相对表达量 (a.u.)"`、`"浓度 (μM)"`（`annotation_audit` 自动检查轴单位与误差线声明）。
- `series_colors`: 按系列/扇区名精准锁定颜色，如 `{"WT":"#888888","KO":"#0072B2"}`；`grid: true` 加淡灰 y 轴网格线；整图底部图注用顶层 `caption`。
- `numeric_x`: `true` 时按真实数值坐标画 X 轴（`scatter` 数值 X 自动开启，适合回归/剂量曲线/火山图，保留全部点不覆写）。
- `aggregate`: `"mean_sd"`(默认) | `"mean_sem"` | `"median_iqr"` — tidy 表同一 `(series, x)` 含多行原始重复观测且无 error 列时自动聚合，并在 provenance 保留 `raw_values`、`n` 与全部 `source_lines`。
- `show_points`: `true` 在 `bar`/`grouped_bar`/`box`/`violin` 上叠加原始重复散点；`show_values`: `true` 在柱顶/折线点/堆叠段标数值；`show_n`: `true` 在 x 标签下追加 `(n=...)`。
- `normalize_pct`: `true` 在 `stacked_bar` 上将每组自动归一化为 100% 构成图并同步双向审计；`error_style`: `"band"` 在 `line`/`errorbar` 上以半透明误差带 (`fill_between`) 展示不确定区间。
- `fit_line`: `true` 在数值 `scatter` 上自动绘制线性回归拟合线并标注规范方程与 $R^2$、$r$（负斜率自动移右上角、点标签自动避开拟合线与邻近点）；`diag_line`: `true` 绘制 $y=x$ 虚参考线。
- 双 Y 轴组合图：`secondary_series: ["SeriesB"]` + `ylabel2: "右轴物理量 (单位)"`（可选 `ylim2`），支持 `bar`/`grouped_bar`/`line` 柱折线组合，自动右轴同色着色、合并图例与双向图元审计。
- `export`: `{"png_dpi": 300, "preview_png": true, "preview_dpi": 100, "transparent": false, "pptx": false}`（`preview_dpi` 自动上限 108 DPI；透明背景自动记录 `RGBA` 且无裁切误报）。
- `annot`: `true` 在热图格子居中标注数值（`annot_fmt`: `"{:.2f}"`）；`cmap`: 色带。
- `xticklabels_rotate`: 0/30/45/90；`ylim`/`xlim`/`log_y`/`log_x`/`panel_title`；`x_order`/`series_order` 显式锁定分组与系列顺序。
- `legend`: true/false；`legend_loc`: `best | upper left | outer_top | outer_right`（遮挡数据时优先 `outer_top`/`outer_right`；`outer_top` 自动抬高 `panel_title` 间距防重叠）；`legend_title`。

### data 三种形态
1. **tidy 长表或宽表**（推荐，溯源最强，支持 CSV/TSV(跳 `#` 注释+GBK 容错)/XLSX(零依赖)/JSON 与内联表）：
   `"data": {"file": "data.csv", "filter": {"CellLine": "HeLa"}}`（`filter` 原生按列值或值列表过滤行并 **100% 保留原始物理行号**；`.xlsx` 可加 `"sheet": "Sheet1"`）
   + `"mapping": {"x": "列", "y": "列", "series": "列(可省)", "error": "对称误差列(可省)", "error_low": "下界(可省)", "error_high": "上界(可省)", "label": "点标注列(可省)"}`
   - 面板级排序：`"sort_x": "asc" | "desc" | "by_value_desc" | "by_value_asc"`（适合富集通路/基因排行图）。
   - **宽表直读**：`"mapping": {"x": "Gene", "y_cols": ["WT", "KO"]}` 自动转长表并保留原列名与行号。
   - `box` / `violin` 同样支持 tidy 表（按 `mapping.x` 分组收集全部样本值）。
2. **显式 series**：
   `"data": {"x_labels": ["WT","KO"], "series": [{"name":"TP53","y":[5.2,8.7],"error":[0.4,0.6]}]}`（连续 X 可加 `"x": [...]`）。
3. **热图**：`"data": {"matrix": [[...]], "row_labels": [...], "col_labels": [...]}`、tidy `{"file":…, "mapping":{"row","col","value"}}` 或**宽矩阵 CSV 自动识别**（首列为行标签、其余列为热图数值列，逐格保留 `source_line`/`source_col`）；`panel.unit` 写色条标签；设 `"vcenter": 0` 自动启用零中心对称发散色带 (`RdBu_r`)，`NaN` 格以浅灰显示。

### annotations（数据坐标系）
- 显著性括线（支持语义定位免心算坐标，自动定位高度+防多重括线重叠+自动扩 ylim，支持 bar/grouped_bar/box/violin）：
  `{"type":"signif","group":"IFNG","series1":"WT","series2":"KO","text":"***","auto":true}`
  或跨组 `{"type":"signif","group1":"WT","group2":"KO","text":"**","auto":true}`（也兼容数字 `x1`/`x2`；`*`/`**`/`***` 须取自源材料给定结论，禁止自推 p 值）。
- 文字：`{"type":"text","x":..,"y":..,"text":"..","axes_frac":true?}`。
- 参考线：`{"type":"hline","y":..,"text":"阈值=…","ls":"--"}`；`vline` 同理。

---

## 2. 生物学机制图 / 流程图 schema（`svg_edit.py --diagram mech.json`）
用于从原始论文/文字描述重建或绘制机制图（如信号通路、实验流程、结构示意），自动排版、自动折行、自动贴边连线、自动图例，并产出 SVG + PDF + PNG + `.provenance.json`：
```json
{
  "case_id": "…",
  "title": "机制图标题",
  "source": "原论文 Figure 3 / 章节定位",
  "compartments": [
    {"id": "c_cyto", "title": "Cytoplasm", "lanes": [1, 2], "fill": "#F5F9FD", "stroke": "#7B98B6", "dashed": true}
  ],
  "nodes": [
    {"id": "lig", "label": "EGF", "sublabel": "Ligand", "lane": 0, "order": 0, "shape": "pill", "fill": "#FDF1E7", "stroke": "#D55E00", "source_ref": "p.4"},
    {"id": "rec", "label": "EGFR", "sublabel": "Dimerization", "lane": 1, "order": 0, "shape": "rounded", "fill": "#EEF3FA", "stroke": "#0072B2"},
    {"id": "inh", "label": "Gefitinib", "lane": 1, "order": 1, "shape": "pill", "fill": "#FDECEC", "stroke": "#C0392B"}
  ],
  "edges": [
    {"from": "lig", "to": "rec", "style": "activate", "label": "binding"},
    {"from": "inh", "to": "rec", "style": "inhibit", "label": "TKI block"},
    {"from": "rec", "to": "tf", "style": "activate", "dashed": true, "label": "translocation"}
  ],
  "legend": true
}
```
- `direction`（兼容别名 `layout`/`orientation`）: `"TB"`(默认纵向细胞分层) | `"LR"`(横向左→右流程/通路，区室自动等高列对齐，反馈走顶/底走廊)。
- `role`: 节点生物学角色自动科研配色 `ligand|receptor|kinase|protein|tf|gene|drug|inhibitor|process`（可用 `fill`/`stroke` 覆盖）；节点兼容 `sublabel`/`subtitle`，区室兼容 `title`/`label`/`name`。
- `complexes`: `[{"id":"cx1","label":"mTORC1","members":["mtor","raptor"]}]` 自动绘制多蛋白复合物虚线包络框。
- `shape`: `rounded`(默认) | `rect` | `pill`(小分子/药物/配体) | `ellipse`(复合物/细胞器) | `diamond`(开关/判断)；节点可加 `"badge": "P"`/`"Ub"`/`"Ac"` 在右上角画可编辑生化修饰徽章。
- 区室可设 `"style": "membrane"` 绘制生物质膜双线边界；顶层可设 `"caption"`（缺省时自动以 `"source"` 生成底部来源行）。
- `style`: `activate`(实心箭头) | `inhibit`/`tbar`(平头抑制 T-bar，严禁把抑制画成箭头！) | `both`(双向) | `line`(关联)；`dashed: true` 表间接/转运/转录；`route`: `straight`/`smooth`(斜向跨泳道自动 90° 平滑正交入框，消除斜 T-bar)/`elbow`/`detour`(反馈或跨 ≥2 泳道自动走外侧圆角走廊)；同层双向边自动 ±10px 平行分离。

---

## 3. 既有图稿编辑 ops 语法（`svg_edit.py --input <原图> --ops ops.json`）
**坐标约定**：顶部原点坐标系（y 向下增大）；先 `--inspect --input <原图>` 获取准确文字/坐标/颜色后再写 ops。
```json
{"ops": [
  {"op":"replace_text","find":"错名","replace":"正名","match":"exact|contains|regex"},
  {"op":"set_text","id":"lbl-1","text":"新文本"},
  {"op":"set_style","find":"TP53","match":"contains","font_style":"italic","font_size":11},
  {"op":"recolor","fill_from":"#FF0000","to_fill":"#0072B2"},
  {"op":"recolor","id":"bar-1","to_fill":"#0072B2"},
  {"op":"move","id":"…","dx":10,"dy":0},
  {"op":"add_compartment","id":"c1","x":20,"y":60,"w":400,"h":200,"title":"Nucleus","dashed":true},
  {"op":"add_box","id":"b1","x":40,"y":90,"w":120,"h":50,"shape":"rounded","label":"TP53","sublabel":"TF"},
  {"op":"add_arrow","from_id":"b1","to_id":"b2","style":"inhibit","dashed":false,"label":"repression"},
  {"op":"add_text","x":40,"y":40,"text":"注记","font_pt":11,"fill":"#1A2B3C"},
  {"op":"delete","target":{"find":"…","match":"contains"}}
]}
```
- PDF 输入自动导出保留 `<text>` 的 SVG 副本与同名 `.provenance.json`，文字替换(`exact/contains/regex`)与新增元素同步写入 PDF；含 `move/delete/recolor` 时单页与多页 PDF 均自动同步重导该页保持视觉一致。
