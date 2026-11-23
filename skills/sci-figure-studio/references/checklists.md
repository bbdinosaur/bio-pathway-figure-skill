# checklists.md — 六检查点速查与常见错误对照表（按需读取）

## 六类检查点 → 交付动作（每个案例走完打勾）
| # | 检查点 | 动作 | 证据落点 |
|---|---|---|---|
| 1 | 科学实体 | 实体名逐字取自源材料；编辑用 replace_text 而非手改 | provenance.groups/series_names; change_log before/after |
| 2 | 空间关系 | 箭头连接、模块布局合理；箭头起终点贴边 | check_layout.svg_geometry + 渲染预览 |
| 3 | 数据编码 | 每个图元能回溯源表行列 | provenance.panels.elements (值+行号+列名) |
| 4 | 图例标注 | 图例↔系列逐字一致；轴↔单位；误差线↔SD/SEM/CI；显著性↔给定结论 | 自检清单步骤2 |
| 5 | 可编辑源文件 | SVG 文字保持 <text> 未转曲 | `grep -c "<text" *.svg` > 0 |
| 6 | 导出格式 | PNG≥300dpi、PDF 可打开、无越界裁切、字体嵌入 | checks.svg_geometry / png_edge |

## 常见错误 ↔ 预防（平台对照中高频失分点）
| 错误 | 预防机制 |
|---|---|
| 数值与柱高对不上 | tidy 表 mapping + provenance 行号映射 + P1 数值抽查 |
| 图例与系列错配 | 图例由系列名自动生成；self_check 真实比对渲染图例文本与系列名；多面板共享图例时其余面板设 legend:false |
| 轴单位/量级写错 | ylabel 必填单位；scale_notes 自动提示 log/SI；长标签优先用 barh 或 rotate 30-45° |
| 原始重复观测丢失 | tidy 表重复 (series,x) 自动聚合 mean±SD 并保留 raw_values 与全部 source_lines；可选 show_points 叠加散点 |
| 生物机制图抑制/激活混淆 | --diagram 明确区分 style=activate(箭头) 与 style=inhibit(平头 T-bar) 及 dashed(间接调控) |
| 科学实体拼错 | replace_text 从源材料复制；--inspect 先列原文 |
| 中文变方框 | CJK 回退链；fonts.cjk_font=null 时改英文并记 uncertainty |
| 多面板错位 | 统一 preset 尺寸；(a)(b) 标号自动；图例自动去重 |
| 导出位图/文字转曲 | svg.fonttype=none + pdf.fonttype=42 固定 |
| 分辨率/色彩不达标 | PNG 600dpi RGB 白底默认；PDF 矢量 |
| 无人能复现 | .provenance.json + make_result result.json 契约校验 |

## 提交前 60 秒终检（顺序执行）
1. `check_layout.py *.svg` 全部 ok=true（error=0）。
2. `check_layout.py --png *.png` 无 clipping_suspect。
3. result.json missing_contract_fields=[] 且 status 如实。
4. change_log/uncertainty/limits 三处措辞与事实一致（不夸大、不隐瞒）。
5. 输出目录只含交付物（svg/pdf/png/pptx/provenance/result.json）。
