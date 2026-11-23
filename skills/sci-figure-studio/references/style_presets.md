# style_presets.md — 期刊/论文/演示样式预设与色板（按需读取）

## 预设（chart_tool 内置）
| preset | 总宽 mm | 基准字号 pt | 面板高 mm | 适用 |
|---|---|---|---|---|
| journal_single | 89 | 8 | 55 | 单栏期刊图（Nature/Science/PLOS 单栏） |
| journal_double | 183 | 8 | 55 | 双栏通栏图 |
| thesis | 140 | 10.5 | 70 | 学位论文正文插图 |
| ppt_16x9 | 254 | 14 | 95 | 汇报幻灯片大图 |

自定义：`style.width_mm / panel_h_mm / font_pt` 直接覆盖。字号下限：印刷 ≥5pt（≈7px），汇报 ≥12pt。

## 色板（Okabe-Ito 色盲友好，chart_spec.PALETTE 顺序）
`#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9 #F0E442 #000000`
规则：同一 series 全图同色；分组柱相邻色对比拉开；打印黑白时依赖线型/填充纹理区分。
自定义 `style.colors` 可覆盖（hex 列表）。

## 线宽与刻度
- 轴线/刻度线 0.6pt；数据线 1.0–1.5pt；误差线 0.8pt capsize 2。
- 去顶右框线（despine，chart_tool 默认开）；刻度字号 = 基准 ×0.9。
- 热图色条 fraction 0.046 pad 0.03，色条标签必须带单位。

## 中文与字体回退
- 检测顺序：Noto Sans CJK SC → JP/TC/HK → Source Han → WenQuanYi → SimHei → YaHei → Droid Sans Fallback → AR PL UMing。
- `axes.unicode_minus=False` 防负号方框；全图禁用"宋体正文"混排西文。
- 检测结果写入 provenance.fonts；**无 CJK 字体时**：中文标签必须改用英文并在 result.json uncertainty 注明。
- SVG 必须 `svg.fonttype=none`（chart_tool 已设）：文字保持 `<text>` 可再编辑，绝不转曲。
- PDF 必须 `pdf.fonttype=42`（TrueType 嵌入）。

## 版式硬规则
- 内容四边留白 ≥ 画布 2%（png_edge_check 会报 clipping_suspect）。
- x 轴分类标签 >6 字符或面板窄 → rotate 30–45°。
- 图例不得压数据：优先 best，遮挡时换 upper left/outer。
- 多面板 (a)(b) 标号左上角粗体，字号 = 基准+1。
