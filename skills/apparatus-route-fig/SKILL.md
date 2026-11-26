---
name: "apparatus-route-fig"
description: "科研绘图 Skill：依据真实实验材料、原始数据表或既有 SVG，生成或保源编辑实验装置图、生物机制/流程图、技术路线图与数据图表，交付分层可编辑 SVG + 300dpi PNG/PDF + 逐元素溯源与完整 result.json。"
---

# apparatus-route-fig — 实验装置与技术路线图绘制

**触发与路由**（读完 `/input/case.json`、`/input/task.md` 与随附真实材料后直选一条管线；脚本位于 `/skills/weekly-skill/scripts/`，若挂载他处取本文件同级 `scripts/`）：
- **装置 / 生物机制 / 实验流程** → `SIR(kind=apparatus|flow)` + `run_all.py`（支持 `group` 平行臂/子系统、`step` 编号、`activate`/`inhibit` T-bar/`energy`/`loop`、`zoom` 局部放大；>14 节点用 `figures: [...]`）
- **阶段 / 里程碑 / 技术路线** → `SIR(kind=roadmap)` + `run_all.py`
- **真实源数据图表** → 常规图表（line/step/分组 bar+括号/barh/stacked_bar/scatter+OLS/volcano/box/violin/hist/heatmap，支持直连 CSV/TSV/XLSX）用 `chart_spec.json` + `chart_kit.py`；**复杂多面板、非对称 `GridSpec`、并列重复列宽表或定制统计图直接写简洁 `matplotlib`**（设 `svg.fonttype="none", pdf.fonttype=42`，模板见 `references/style-guide.md` §4）
- **保源编辑既有 SVG** → `svg_edit.py`（原件不动；兼容 `<tspan>`/`\n`/CSS `<style>`/`transform`，支持单步与 `batch` 原子修改 + 自动导出 PNG/PDF + `diff` 变更日志）

**铁律**：必须读取真实材料原文与原始数据，严禁凭文件名/领域标签臆造连接、反向箭头或改动数值；每个实体/连接/数据系列必须附 `source.quote`（原句短摘录）+ `source.loc`（文件/页/节/表）；缺参写 `"TBD"` 并记入 `uncertainty`。

## 四步极速闭环（前 4–6 步落盘首版完整交付物与 `result.json`，再精修；适配 64 请求 / 900s）

1. **读输入与真实材料**：
   单行查看 `/input/case.json` 全部键与材料路径，并读 `/input/task.md`（若存在）：
   `python3 -c "import json;d=json.load(open('/input/case.json'));[print(k,type(v).__name__,str(v)[:140]) for k,v in d.items()]"`
   逐个核验并读取随附真实文件：PDF 用平台 `pdf-text`/`pdf-render`/`ocr` 提取原文并记页码；`.xlsx`/`.csv`/`.tsv` 用 `python3 /skills/weekly-skill/scripts/table_probe.py <表>` 或 Python 读取；既有 `.svg` 用 `svg_edit.py info <原图.svg>` 查看文本、色号与坐标。
   **完整抄录 `case_id`、`output_contract` 全字段与指定输出文件名（如 `figure03`，直接用作 `--name`）**。

2. **构建结构化输入（写到 `/app/work/`）**（完整字段速查见 `references/sir-spec.md`）：
   - **示意图/路线图**：写 `/app/work/sir.json`，核实每个实体、平行分组（`group`）、试剂/剂量/时间/n 值（入 `attrs`）与箭头/T-bar 方向；中文长方法段可选 `extract.py` 起草后逐条核对。
   - **数据图表**：常规图写 `/app/work/chart_spec.json`（优先 `"table"` 直连源表，保留轴单位、误差棒与逐系列 `source`）；复杂多面板或非常规布局直接写简洁 `matplotlib` 脚本读取原表，同步写出 `.svg/.pdf/.png(300dpi)`、`preview.png(96dpi)` 与 `provenance.json`。
   - **保源编辑**：单处直接命令行；多处写 `/app/work/edits.json`（`{"ops":[...]}`）用 `batch` 一次完成，**原件不动**。

3. **一键生成、导出与轻图预览**（正式 PNG 写 300 DPI 元数据，`--preview` 自动降采样产 96 DPI ≤ 108 DPI 轻图）：
   - 示意图 / 路线图 / 多图：
     ```bash
     python3 /skills/weekly-skill/scripts/run_all.py --sir /app/work/sir.json --out /app/output \
       --name diagram --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json
     ```
   - 真实数据图表：
     ```bash
     python3 /skills/weekly-skill/scripts/chart_kit.py --spec /app/work/chart_spec.json --out /app/output \
       --name chart --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json
     ```
   - 保源 SVG 编辑（多处改用 `batch 原图.svg --ops /app/work/edits.json`）：
     ```bash
     python3 /skills/weekly-skill/scripts/svg_edit.py set-text 原图.svg --old "旧文本" --value "新文本" \
       --out /app/output/edited.svg --reason "依据材料p3" --log /app/work/change_log.json \
       --export-dir /app/output --dpi 300 --preview /app/work/preview.png \
       --case-id "<case_id>" --contract /input/case.json --result-skel /app/work/result_skel.json
     ```

4. **立即落盘完整 `/app/output/result.json`，再做 96 DPI 视觉快检精修**：
   - 立即以 `/app/work/result_skel.json` 为基座写出正式 `/app/output/result.json`：**依据真实材料与科学判断填满顶层与 `output_contract` 全部字段（零 `<待填`）**，补齐 `case_id`、`status`、具体 `sources`、`uncertainty`/`limits` 与真实 `change_records`。
   - 用读图工具检查 `/app/work/preview.png`（96 DPI）：无重叠/越界/截断、部件与箭头/T-bar 方向忠实原文、数值/单位/n 值与源数据一致、保源编辑仅改目标；发现瑕疵则改输入重跑并同步更新 `/app/output/result.json`。

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

- **校验退出码 2**：按报错 JSON 修重复 id、断头边、错误工作表/列名、对数 `<=0` 或缺 `source.quote` 后重跑。
- **渲染降级**：`run_all.py` 按 `rsvg-convert → cairosvg → inkscape → pymupdf → soffice` 降级，全失败落 `mirror.py`；`chart_kit.py` 缺 matplotlib 自动降级纯标准库 SVG；单图重渲染用 `render.py --svg a.svg --png a.png --pdf a.pdf`。
- **无脚本兜底**：定制统计图按 `references/style-guide.md` §4 手写 matplotlib（`svg.fonttype="none", pdf.fonttype=42`）；SVG 编辑用标准库 `xml.etree.ElementTree` 保命名空间修改。
- **缺字体 / 超宽 / 材料冲突**：降级英文标签并声明、`--maxcols 4` 或 `figures[]` 拆图、按正文主句绘制并在 `uncertainty` 并列记录冲突原文。

## 交付前核对

- [ ] 六要素齐备：科学实体 · 空间关系 · 数据编码 · 图例标注 · 可编辑源文件(.svg) · 导出件(300dpi .png + .pdf)
- [ ] `checks_report.json` / `*_checks.json` 无 error，96 DPI 预览已肉眼核验无重叠/截断/反向
- [ ] 100% 真实材料溯源（`provenance.json` / `data_mapping`），未臆造实体或篡改源数据
- [ ] `/app/output/result.json` 含 `case_id` + `output_contract` 全字段（零 `<待填`）+ `status/sources/uncertainty/change_records`
