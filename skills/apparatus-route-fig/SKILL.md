---
name: "apparatus-route-fig"
description: "科研绘图 Skill：依据真实论文、实验材料、原始数据表或既有 SVG，生成或保源编辑实验装置图、生物机制/流程图、技术路线图、数据图表与多面板复合图，交付分层可编辑 SVG + 300dpi PNG/PDF + 逐元素溯源与完整 result.json。"
---

# apparatus-route-fig — 实验装置与技术路线图绘制

**触发与路由**（读完 `/input/case.json`、`/input/task.md` 与随附真实材料后直选管线；脚本默认 `/skills/weekly-skill`，挂载于别处可设 `SKILL_DIR`）：
- **装置 / 生物实验 / 机制 / 流程** → `SIR(kind=apparatus|flow)` + `run_all.py`（`group` 平行臂/子系统、`step` 编号、`activate`/`inhibit` T-bar/`energy`/双向箭头、`zoom` 局部放大、`figures[]` 拆图）
- **阶段 / 里程碑 / 技术路线** → `SIR(kind=roadmap)` + `run_all.py`
- **真实源数据图表** → `chart_spec.json`（直连 CSV/TSV/XLSX/JSON 宽/长表、`agg` 均值误差棒散点、拆 `"均值±误差"`、容忍 Unicode 负号 `−` 与表尾注、直连 `p_col` 自动 `-log10`）+ `chart_kit.py`（line/step 生存曲线/分组 bar/barh/stacked_bar/scatter+OLS/volcano 火山图/box/heatmap/双Y/对数/多面板；缺 matplotlib 自动纯标准库 SVG 兜底）
- **多面板复合图（如生物 Figure 3 机制 A + 数据 B/C）** → 写单个 `compose.json`（每格直接内联 `"sir":{...}`、`"chart":{...}` 或引用既有 `"svg"`），**一条命令**调用 `compose_panels.py` 自动产子图、隔离 `defs`/`clipPath`、加 `A/B/C` 徽标、合并溯源与 `result_skel.json`（复杂空间解剖/光路可直写分层 SVG 再拼版或 `render.py` 导出）
- **保源编辑既有 SVG** → `svg_edit.py`（**原件不动**；兼容多 `<tspan>` 与 `\n` 换行、CSS `<style>`、`transform` 绝对坐标 `abs_xy`，支持单步、`batch`、`replace-color` 批量换色 + `diff`/`untouched_ratio` + 导出 PNG/PDF）

**科学铁律**：必须读取真实材料与原始数据，严禁凭文件名/领域标签臆造连接、反向箭头或改值；忠实还原试剂、剂量、条件、上下游/抑制方向与原值。每实体/连接/系列附 `source.quote` + `source.loc`；缺参写 `"TBD"` 并记入 `uncertainty`。

## 两段极速闭环（前 4–6 步先落盘首版图件与 `result.json`，总步数尽量 <= 10；适配 64 请求 / 900s）

1. **读输入与真实材料（零截断）**：
   - 速览 `/input/case.json` 并全文读 `/input/task.md`（若存在）与 `/input/case.json`：
     `python3 -c "import json;d=json.load(open('/input/case.json'));[print(k,type(v).__name__,str(v)[:140]) for k,v in d.items()]"`
     抄录 `case_id`、`output_contract` 全字段与指定文件名（如 `figure03`，用作 `--name`）。
   - 读随附真实文件：PDF 优先用平台 `pdf-text`/`pdf-render`/`ocr` 工具（无平台工具再用 `pdf_probe.py`）；多工作表 `.xlsx`/宽表用 `table_probe.py <表>` 一次索引全表；`.csv`/`.json`/`.txt` 直接读；既有 `.svg` 用 `svg_edit.py info <原图.svg>`。
2. **写结构化输入至 `/app/work/`**（速查见 `references/sir-spec.md`）：
   - 示意图/路线图：`/app/work/sir.json`（中文长方法段可选 `extract.py` 起草后逐条核对）。
   - 数据图表：`/app/work/chart_spec.json`（优先直连 `"table"` 零抄写误差）。
   - 多面板复合图：`/app/work/compose.json`（每格支持 `"sir":{...}` / `"chart":{...}` 内联直出或 `"svg":"..."`，一步到位免拆多步）。
   - 保源 SVG 编辑：单处直接命令行；多处写 `/app/work/edits.json`，如 `{"ops":[{"action":"set-text","id":"t1","old":"旧","value":"新","reason":"p3"},{"action":"set-attr","id":"b1","attr":"fill","value":"#EBF8FF"}]}`。
3. **一键生成与导出**（`--preview` 产 96 DPI 轻图快检，正式 PNG 保持 300 DPI）：
   - 示意图/路线图/多图：
     `python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/run_all.py --sir /app/work/sir.json --out /app/output --name diagram --dpi 300 --preview /app/work/preview.png --preview-dpi 96 --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json`
   - 真实数据图表：
     `python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/chart_kit.py --spec /app/work/chart_spec.json --out /app/output --name chart --dpi 300 --preview /app/work/preview.png --preview-dpi 96 --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json`
   - 多面板复合拼版（按需）：
     `python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/compose_panels.py --spec /app/work/compose.json --out /app/output --name figure03 --dpi 300 --preview /app/work/preview.png --preview-dpi 96 --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json`
   - 保源 SVG 编辑（多处改 `set-text ...` 为 `batch 原图.svg --ops /app/work/edits.json ...`）：
     `python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/svg_edit.py set-text 原图.svg --old "旧文本" --value "新文本" --out /app/output/edited.svg --reason "依据p3" --log /app/work/change_log.json --export-dir /app/output --dpi 300 --preview /app/work/preview.png --preview-dpi 96 --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json`
4. **先落盘首版 `result.json`，再视觉自检精修**：
   - 立即以 `/app/work/result_skel.json` 为基座写 `/app/output/result.json`：**依据真实材料填满各字段**（零 `<待填`），顶层含 `case_id`、`output_contract` 全字段、`status`、具体 `sources`、真实 `change_records` 与诚实 `uncertainty`/`limits`。
   - 读图检查 `/app/work/preview.png`（96 DPI）：无重叠/越界/截断、实体与箭头/T-bar 方向准确、数值单位无误、保源编辑仅改目标；有问题再针对性改输入重跑并更新 `result.json`（可选 `audit_delivery.py --out /app/output --contract /input/case.json` 复核）。

## 最小调用示例（示例，非正式案例结果）

输入 `/app/work/sir.json`：
```json
{"kind": "flow", "title": "最小示例",
 "nodes": [{"id": "a", "label": "样品进料", "type": "input", "source": {"quote": "样品溶于缓冲液", "loc": "m.pdf p2"}},
           {"id": "b", "label": "离心收集", "type": "output", "source": {"quote": "离心后收集上清", "loc": "m.pdf p3"}}],
 "links": [{"from": "a", "to": "b", "kind": "material", "source": {"quote": "混匀后转移离心", "loc": "m.pdf p3"}}]}
```
命令：`python3 ${SKILL_DIR:-/skills/weekly-skill}/scripts/run_all.py --sir /app/work/sir.json --out /app/output --name diagram --case-id DEMO`
输出：`/app/output/diagram.svg|.png|.pdf + checks_report.json(ok,errors=0) + provenance.json`。

## 异常降级与无脚本兜底（详见 `references/failure-playbook.md`）

- **校验退出码 2**：按报错修重复 id、断头边、对数 `<=0` 或缺 `source.quote` 后重跑。
- **渲染失败**：`run_all.py` 按 `rsvg-convert → cairosvg → inkscape → pymupdf → soffice` 降级，全失败自动落 `mirror.py`；单图导出用 `render.py --svg a.svg --png a.png --pdf a.pdf`。
- **无脚本兜底**：数据图按 `references/style-guide.md` §4 手写 matplotlib（设 `svg.fonttype="none"`）；SVG 编辑用标准库 `xml.etree.ElementTree` 保命名空间修改。
- **缺字体/超宽/材料冲突**：降级英文标签并声明、`--maxcols 4` 或 `figures[]` 拆图、按正文主句绘制并在 `uncertainty` 并列记录冲突原文。

## 交付前核对

- [ ] 六要素齐备：科学实体 · 空间关系 · 数据编码 · 图例标注 · 可编辑源文件(.svg) · 导出件(300dpi .png + .pdf)
- [ ] `checks_report.json` / `*_checks.json` 无 error，预览 PNG 已肉眼核验无重叠/截断/反向
- [ ] 100% 真实材料溯源（`provenance.json` / `data_mapping`），未篡改源数据
- [ ] `/app/output/result.json` 含 `case_id` + `output_contract` 全字段（零 `<待填`）+ `status/sources/uncertainty/change_records`
