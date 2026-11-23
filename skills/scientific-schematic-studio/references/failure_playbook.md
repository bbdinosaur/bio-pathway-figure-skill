# 异常与降级手册（failure_playbook.md）
原则：**先交付诚实的部分结果，再迭代完善**；任何缺失都要写进 result.json，
禁止编造软件状态或科学数据。

## 输入侧
| 症状 | 处置 |
|------|------|
| case.json 缺字段/损坏 | `run_pipeline.py prepare` 自动以 task.md 文案兜底推导并立即写保底 `result.json`（`status=partial`） |
| 长 PDF 仅摘要展示部分页 | 看 `prepare` 输出中的 `[PDF_READ_HINT]` 行号区间 `[Lstart-Lend]`，定向 `read` `/app/work/pdf_extract.txt` 抽全子图与分子剂量 |
| 源数据含堆叠子表或合并单元格 | 查 `/app/work/table_extract.txt` 全量表；在 `chart` 中用 `sheet_name` + `section_match` + `col_range` 切片（自动继承水平/垂直 `<mergeCell>`） |
| 材料与任务描述矛盾 | 以**实际输入文件**为准（原论文与原始数据表是事实依据）；矛盾点写入 `uncertainty` |
| 领域标签与内容不符（标签错标） | 不依据错误标签补造数据，只画材料里实际存在的东西 |
| 提供的是待编辑源文件 | 走 `mode: "edit"`（`edit_svg.py`），自动留 `original_*.svg`；优先用 `from_text`+`to_text` 或 `gid`/`edge_idx` 定位边；遇 `EDIT_ERRORS` 修正 `ops` 重跑一次 |

## 生成侧
| 症状 | 处置 |
|------|------|
| build_figure.py 报 KeyError | spec 字段名对照 references/result_schema.md；逐面板二分定位 |
| audit 报越界/重叠 | 先看 geometry.json 中对应元素坐标；通常是标签过长 → 缩短标签而非调布局参数 |
| 字号缩至 <6pt 警告 | 拆分面板/缩短标签；不要硬调 min_scale 到 0.5 以下 |
| 节点应为包含关系 | 用 groups（区域），不要用节点+箭头表达包含 |
| 图例项 ≠ 数据系列 / 重复系列色 / 同向对立边 | `audit_figure.py` 自动报警；核对 `DELIVER SUMMARY` 中的实绘数值、`edges` 与 `AUDIT_WARNINGS`，修正后重跑 `deliver` |
| `EDIT_ERRORS` 阻断通过 | 核对 `prepare` 打印的语义边清单 `#idx(...) A->B`，改用 `from_text`+`to_text` / `by_text` / `gid` 重跑 |

## 渲染/导出侧
| 症状 | 处置 |
|------|------|
| edit_svg 渲染失败 | 看 render.errors：cairosvg→rsvg→inkscape→soffice 逐级兜底；全失败则交付 SVG 并在 limits 说明 |
| PDF 字体未嵌入告警 | matplotlib 已设 fonttype=42；若仍出现，改用 fig_chart/节点默认 DejaVu，勿用系统花哨字体 |
| LibreOffice 转换卡住 | 超时 180s 后自动降级；不要死等 |
| probe 词在 PDF 找不到 | 说明该标签不在 PDF 或被转曲；核对 SVG 文本层 |

## 预算纪律（64 请求 / 900s / 16k token 每响应）
1. 请求 1–3：读完输入 + 写 inventory.json + **先落一版 result.json（status=partial）**。
2. 请求 4–8：spec → build → audit 修复 ≤2 轮 → 导出检查 → result.json 终态。
3. 之后才做视觉精修（≤2 轮）；每轮必须重跑 audit + export_check 固化证据。
4. 任何时候脚本不可用：按 SKILL.md 的无脚本兜底手工产出（SVG 文本模板手写）。
