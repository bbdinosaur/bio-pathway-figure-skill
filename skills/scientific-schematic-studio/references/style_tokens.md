# 视觉令牌（Style Tokens）与字号层级
配色：Okabe-Ito 色盲安全子集（顺序即优先级）：
`#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9 #8C8C8C`
- 节点默认：fill `#EAF2FB` / stroke `#2E5E8C` / 文字 `#10243B`
- 抑制物/负调：fill `#FADBD8`；产物/输出：fill `#D5F5E3`；刺激物：fill `#FDEBD0`
- 分组区：fill `#F4F4F4` / 虚线 `#9AA5B1`；边与箭头：`#33404F`
- 边标签白底衬垫（alpha 0.92）保证压线可读。

## 字号层级（画布 180mm 双栏基准）
| 元素 | 字号 |
|------|------|
| 面板标签 A/B/C | 12pt bold |
| 面板标题 | 9.5pt bold |
| 节点主标签 | 9pt bold（默认，随整体缩放） |
| 节点副标签 | 0.8×主标签 |
| 边标签 | 0.8×主标签 |
| 图例/坐标刻度 | 7.2pt |

## 线宽与箭头
边 1.5pt；节点描边 1.3pt；分组 1.0pt。箭头长 2.6mm 宽 1.5mm；T 杠 1.9mm。
全部随整体缩放因子联动，禁止混合比例。

## 命名复合图层（可编辑性核心）
输出 SVG 经复合图层后处理并保证 W3C XML `id` 全局唯一，支持 Inkscape/Illustrator 整组拖拽与 `edit_svg.py` 单步精改：
- `panel-<id>` 面板容器组
- `node-<id>`（`data-layer="node"`, `data-source="..."`）复合节点组，内含 `node-<id>-shadow` / `node-<id>-shape` / `text-<id>` / `sublabel-<id>` / `badge-<id>`
- `edge-<from>-<to>`（`data-layer="edge"`, `data-kind="..."`, `data-source="..."`）复合边组，内含 `-line` / `-head` / `elabel-*`
- `group-<id>`（`data-layer="compartment"`）区室组（含 `group-<id>-box` 与可选双层膜 `group-<id>-membrane-1/2`）
- `legend-panel-<id>`（`data-layer="legend"`）图例组；数据系列 `series-<i>[-bar-<j>]`

## 语义边默认着色（与图例 100% 同步）
- `activates` / `catalyzes` / `flows`：深蓝 `#1E3A5F`（实心箭头）
- `inhibits` / `inhibits_dashed`：深红 `#C0392B`（T 杠 ⊣；自动归一化 `represses`/`blocks`/`downregulates` 等同义词）
- `translocates`：蓝 `#0072B2`（虚线空心箭头）
- `binds`：紫灰 `#5B4B8A`（双箭头 ↔）

## 文本规则
- 节点标签 ≤ 3 词；细节放 sublabel；单位一律写进标签或坐标轴（如 `5 mM`）。
- 上下箭头用 Unicode（↑↓→），DejaVu Sans 原生支持。
- 标签文字必须逐词来自来源材料（禁止臆造基因名/浓度/时间点）。
