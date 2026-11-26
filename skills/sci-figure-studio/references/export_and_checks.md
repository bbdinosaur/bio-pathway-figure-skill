# export_and_checks.md — 导出规范、六类检查点与 result.json 字段指南（按需读取）

## 导出参数（chart_tool 默认，已达投稿要求；可选 PPTX）
spec 加 `"export": {"pptx": true}` 额外产出 {base}.pptx：可编辑标题/图注文本框 + 嵌入高清图 + 溯源自检页（需 python-pptx 可选依赖，失败不影响 svg/pdf/png）。启用时图内不重复标题，标题改放可编辑文本框。
| 产物 | 参数 | 用途 |
|---|---|---|
| `.svg` | svg.fonttype=none，文字保持 `<text>`，分层 | 可编辑源文件（Inkscape/AI 可再改） |
| `.pdf` | pdf.fonttype=42 TrueType 嵌入，RGB | 矢量投稿/打印 |
| `.png` | 600 dpi，白底 RGB | 位图导出/预览 |
| `.provenance.json` | 元素级数据映射 + sha256 + 行号 | 溯源复核 |

色彩空间 RGB；如需 CMYK 在 uncertainty 注明"导出为 RGB，CMYK 需印刷端转换"。
透明背景：默认白底（期刊多要求白底）；需要透明时在 result.json 注明。

## 六类检查点 ↔ 产物对照（评分硬指标）
1. **科学实体**：实体名与源材料逐字一致 → provenance.panels.groups/series_names + svg_edit change_log。
2. **空间关系**：机制图/流程图箭头连接、模块位置 → check_layout.svg_geometry + 渲染预览。
3. **数据编码**：柱高/点位置/色阶↔数值 → provenance.panels.elements（值+行号+列名）。
4. **图例标注**：图例↔系列、轴↔单位、误差线↔SD/SEM、显著性↔给定结论 → 自检清单。
5. **可编辑源文件**：SVG `<text>` 未转曲（`grep -c "<text" fig.svg` > 0）。
6. **导出格式**：PNG dpi≥300、PDF 可打开、svg_geometry.ok=true、png_edge 无裁切。

## result.json 字段指南（写入 /app/output/result.json，带 case_id）
必需骨架（make_result.py 自动生成，未知 output_contract 字段自动置 null 提醒补齐）：
```json
{
  "case_id": "…",
  "status": "complete | partial | failed",
  "deliverables": {"editable_source": [...], "exports": [...], "previews": [...]},
  "source_mapping": { …provenance.json 原样内嵌… },
  "checks": {"svg_geometry": …, "png_edge": …},
  "change_log": [{"change": "…"}],
  "uncertainty": ["…"],
  "limits": []
}
```
- status=complete 且无真实缺口时 limits 为空列表 `[]`；status=partial/failed 时 limits 必须写清缺什么、为什么。
- 不确定 ≠ 失败：字体回退、单位缺失、显著性无依据等写进 uncertainty。
- **示例（Example，非正式结果）**：`python3 make_result.py --case-json case.json --out result.json --status auto --deliverable editable_source:fig1.svg --deliverable export:fig1.pdf --deliverable export:fig1.png --provenance fig1.provenance.json --check fig1.layout.json`

## 自查方法（纯文本 JSON 闭环核验）
1. `python3 check_layout.py fig.svg --json fig.layout.json`（几何：越界/重叠）。
2. `python3 check_layout.py --png fig.png`（边缘裁切/留白比例/空白检测）。
3. 严禁对二进制 `.png`/`.pdf` 调用 `read`（避免纯文本执行环境报错或上下文膨胀），统一依据脚本输出的几何/边缘/数值核验 JSON 闭环修正。
4. 修复顺序：先 error（越界/重叠>50%）→ 再 warning → 最后美学微调。
