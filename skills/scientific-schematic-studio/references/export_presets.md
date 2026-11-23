# 导出预设与合规检查（export_presets.md）
## 期刊通用预设
| 场景 | 画布宽 | 分辨率 | 格式 | 字体 |
|------|--------|--------|------|------|
| 单栏图 | 85–90 mm | 300–600 dpi | PDF/SVG + TIFF/PNG | Arial/Helvetica/DejaVu 嵌入 |
| 双栏图 | 180 mm | 300–600 dpi | PDF/SVG + TIFF/PNG | 同上 |
| 答辩 PPT | 254/338 mm | 150–220 dpi | SVG + PNG | 同上 |

- 矢量主格式：PDF（Type42/TrueType 字体子集嵌入，`pdf.fonttype=42`）。
- 可编辑源：SVG（`svg.fonttype='none'`，文字保持 `<text>` 可编辑，图层带语义 id）。
- 位图导出：PNG 600 dpi（≥300）；如需 TIFF 用 PIL 从 PNG 转换（LZW）。
- 色彩空间：默认 RGB；印刷要求 CMYK 时在出版流程转换，图内避免纯黑四色叠加。

## export_check.py 检查项（全部自动）
1. PNG：dpi 元数据 = 请求值（±5%）；像素宽换算物理宽 = 画布宽（±5%）。
2. PDF：页面物理尺寸（mm）；字体全部嵌入（extract_font 缓冲非空 / ext ≠ n/a）；
   文本层可提取（文字可选中最硬的证据）；探针词（节点标签）逐个出现。
3. SVG：`<text>` 元素计数 > 0（文字未被栅格化）；头部合法。
4. 几何：audit_figure.py 的越界（边距 1.5mm）、节点重叠、图例=数据系列数、
   图表系列值个数=类目数、数值缺单位警告、多面板缺 A/B/C 标签。

## 无脚本兜底（任何环境可完成）
- SVG→PDF：`soffice --headless --convert-to pdf x.svg`，再 `pdftoppm -png -r 300`。
- 若均失败：SVG 本身即导出件（浏览器可开），在 result.json 的 limits 里如实写明
  "位图导出在目标环境不可用，已附 SVG+源码复现路径"，不得伪造 PNG。

## 改数据→图同步
spec JSON 是唯一事实源：改 `chart.series[].values` 或节点/边后重跑 build_figure.py
即得到同源 SVG/PDF/PNG 三件套；禁止手改导出位图。
