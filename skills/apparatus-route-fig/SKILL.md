---
name: "apparatus-route-fig"
description: "科研绘图 Skill：依据真实实验材料、原始数据表或既有 SVG，生成或保源编辑实验装置图、生物机制/流程图、技术路线图与数据图表，交付分层可编辑 SVG + 300dpi PNG/PDF + 逐元素溯源与完整 result.json。"
---

# apparatus-route-fig — 实验装置与技术路线图绘制

**触发与路由**（读完 `/input/case.json`、`/input/task.md` 与随附真实材料后直选一条管线；脚本位于 `/skills/weekly-skill/scripts/`，若挂载他处取本文件同级 `scripts/`）：
- **装置 / 生物机制 / 流程** → `SIR(kind=apparatus|flow)` + `run_all.py`（`group` 平行臂、`step` 编号、`activate`/`inhibit` T-bar/`energy`/`loop`、自动负反馈破环、`zoom` 放大；>14 节点用 `figures: [...]`）
- **阶段 / 里程碑 / 路线图** → `SIR(kind=roadmap)` + `run_all.py`
- **真实源数据图表** → `chart_spec.json` + `chart_kit.py`（直连 CSV/TSV/XLSX/JSON 宽/长表、`p_col` 自动 `-log10`、拆 `"均值±误差"`、`agg` 均值误差棒+散点；支持 line/step/bar+括号/barh/stacked_bar/scatter+OLS/volcano/box/violin/hist/heatmap/双Y/对数/多面板；非常规统计图如气泡图/聚类热图/不等分 GridSpec 用简洁 matplotlib 设 `svg.fonttype="none", pdf.fonttype=42`）
- **保源编辑既有 SVG** → `svg_edit.py`（原件不动；兼容多 `<tspan>`/`\n`/CSS `<style>`/`transform`，支持单步、`batch`、`replace-color`、`diff`/`untouched_ratio` + 导出 PNG/PDF）

**科学铁律**：必须读取真实材料与原始数据，严禁凭文件名或领域标签臆造连接、反向箭头或改值；每个实体/连接/系列须附 `source.quote`（原句短摘录）+ `source.loc`（文件/页/节/表）；缺参写 `"TBD"` 并记入 `uncertainty`。

## 两步核心极速闭环（总步数 ≤ 10，前 4–5 步一步落盘全套图件与完整 `result.json`；适配 64 请求 / 900s）

1. **读输入与真实材料**：
   单行查看 `/input/case.json` 全部键与材料路径，并读 `/input/task.md`（若存在）：
   `python3 -c "import json;d=json.load(open('/input/case.json'));[print(k,type(v).__name__,str(v)[:140]) for k,v in d.items()]"`
   读取随附文件：PDF 用平台 `pdf-text`/`pdf-render`/`ocr` 工具提取原文并记页码；多表 `.xlsx`/宽表用 `python3 /skills/weekly-skill/scripts/table_probe.py <表>` 一步看全表列名与统计；`.csv`/`.json`/`.txt` 直接读；既有 `.svg` 用 `svg_edit.py info <原图.svg>`（含 `colors_top` 精确色号与 `abs_xy`）。
   **抄录 `case_id`、`output_contract` 全字段与指定文件名（如 `figure03`，直接用作 `--name`）**。

2. **步一：写单份结构化输入（内嵌 `result_fields` 与 `uncertainty`）到 `/app/work/`**（字段速查见 `references/sir-spec.md`）：
   - **示意图/路线图**：写 `/app/work/sir.json`，核实实体、分组（`group`）、试剂/剂量/时间/n 值（入 `attrs`）与箭头语义（`activate`/`inhibit` T-bar/`energy`/`loop`）；中文长方法段可选 `extract.py` 起草后逐条核对。
   - **数据图表**：写 `/app/work/chart_spec.json`，优先用 `"table"` 直连磁盘源表（自动大小写/空白列名容错 + Unicode 科学计数解析），保留轴单位、括号与逐系列 `source`。
   - **保源编辑**：单处直接命令行；多处写 `/app/work/edits.json`（`{"ops":[...], "result_fields":{...}}`）用 `batch` 一次完成。
   - **关键提速**：在输入 JSON 顶层填入 `"result_fields": {<非路径 output_contract 科学字段>}` 与 `"uncertainty": [...]`，后续单条命令同步落盘顶层与 `output_contract`（重跑保留已填字段，零覆盖）。

3. **步二：单命令生成全套图件 + 96 DPI 轻图 + 正式 `/app/output/result.json`**（正式 PNG 300 DPI，`--preview` 默认 96 DPI ≤ 108 DPI）：
   - 示意图 / 路线图 / 多图：
     ```bash
     python3 /skills/weekly-skill/scripts/run_all.py --sir /app/work/sir.json --out /app/output \
       --name diagram --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-out /app/output/result.json
     ```
   - 真实数据图表：
     ```bash
     python3 /skills/weekly-skill/scripts/chart_kit.py --spec /app/work/chart_spec.json --out /app/output \
       --name chart --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-out /app/output/result.json
     ```
   - 保源 SVG 编辑（多处改用 `batch 原图.svg --ops /app/work/edits.json`）：
     ```bash
     python3 /skills/weekly-skill/scripts/svg_edit.py set-text 原图.svg --old "旧文本" --value "新文本" \
       --out /app/output/edited.svg --reason "依据材料p3" --log /app/work/change_log.json \
       --export-dir /app/output --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-out /app/output/result.json
     ```
   （确需将多张已生成的独立子 SVG 拼为单张 A/B/C 复合图时，可按 `references/sir-spec.md` §4 调用 `compose_panels.py`。）

4. **核验 `unfilled_contract_fields` 与 96 DPI 视觉快检精修**：
   - 检查命令输出 JSON 中 `unfilled_contract_fields` 为 `[]` 且 `errors=0`（若有未填项，补入输入 JSON 的 `result_fields` 或直接补写 `/app/output/result.json` 消除全部 `<待填`）。
   - 用读图工具检查 `/app/work/preview.png`（96 DPI）：确认无重叠/越界/截断、部件与箭头/T-bar 方向忠实原文、数值与单位一致、保源编辑仅改目标；若发现瑕疵，改输入 JSON 重跑一步同步更新图件与 `/app/output/result.json`。

## 最小调用示例（示例，非正式案例结果）

输入 `/app/work/sir.json`：
```json
{"kind": "flow", "title": "最小示例",
 "nodes": [{"id": "a", "label": "样品进料", "type": "input", "source": {"quote": "样品溶于缓冲液", "loc": "m.pdf p2"}},
           {"id": "b", "label": "离心收集", "type": "output", "source": {"quote": "离心后收集上清", "loc": "m.pdf p3"}}],
 "links": [{"from": "a", "to": "b", "kind": "material", "source": {"quote": "混匀后转移离心", "loc": "m.pdf p3"}}]}
```
命令：`python3 /skills/weekly-skill/scripts/run_all.py --sir /app/work/sir.json --out /app/output --name diagram --case-id DEMO`
示意输出：`/app/output/diagram.svg|.png|.pdf + checks_report.json(ok,errors=0) + provenance.json`。

## 异常降级与无脚本兜底（详见 `references/failure-playbook.md`）

- **校验退出码 2**：按报错 JSON 修重复 id、断头边、对数 `<=0` 或缺 `source.quote` 后重跑。
- **渲染降级**：`run_all.py` 按 `rsvg-convert → cairosvg → inkscape → pymupdf → soffice` 降级，全失败自动落 `mirror.py`；`chart_kit.py` 缺 matplotlib 时自动降级纯标准库可编辑 SVG；单图重渲染用 `render.py --svg a.svg --png a.png --pdf a.pdf`。
- **无脚本/定制兜底**：非常规统计图按 `references/style-guide.md` §4 手写 matplotlib（设 `svg.fonttype="none", pdf.fonttype=42`）；SVG 编辑可用标准库 `xml.etree.ElementTree` 保命名空间修改。
- **缺字体 / 超宽 / 材料冲突**：降级英文标签并声明、`--maxcols 4` 或 `figures[]` 拆图、按正文主句绘制并在 `uncertainty` 并列记录冲突原文。

## 交付前核对

- [ ] 六要素齐备：科学实体 · 空间关系 · 数据编码 · 图例标注 · 可编辑源文件(.svg) · 导出件(300dpi .png + .pdf)
- [ ] `checks_report.json` / `*_checks.json` 无 error，96 DPI 预览已肉眼核验无重叠/截断/反向
- [ ] 100% 真实材料溯源（`provenance.json` / `data_mapping`），未臆造实体或篡改源数据
- [ ] `/app/output/result.json` 含 `case_id` + `output_contract` 全字段（零 `<待填`）+ `status/sources/uncertainty/change_records`
