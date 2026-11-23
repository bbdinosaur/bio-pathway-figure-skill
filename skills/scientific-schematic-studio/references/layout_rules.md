# 关系—图形语法（Relation → Glyph Grammar）
所有关系类型必须在图例中出现且与数据/材料一致。

| kind | 语义 | 图形 | 常见误用 | 论文常见触发词 |
|------|------|------|----------|----------------|
| activates | 激活/促进/磷酸化 | 实线 + 实心三角箭头 | 误用于抑制 | promotes, enhances, induces, phosphorylates, activates, upregulates |
| inhibits  | 抑制/阻断/滞留 | 实线 + T 形短杠（⊣） | 画成箭头（方向反） | suppresses, inhibits, blocks, retains, represses, attenuates |
| translocates | 易位/转运/扩散 | 虚线 + 空心箭头 | 与 activates 混淆 | translocates, shuttles, exports, imports, traffics |
| binds     | 结合/相互作用（无方向因果） | 实线 + 双端箭头 | 单箭头暗示因果 | binds, interacts, associates, forms complex |
| flows     | 流程/物料流向 | 实线 + 箭头 | 机制图中滥用 | proceeds to, feeds into, yields |
| assoc     | 关联（无方向） | 实线无箭头 | 画成箭头 | correlates with, linked to |
| compare   | 对比 | 点线无箭头 | — | versus, compared to |
| *(groups)* | 包含/定位区室 | **虚线区室框（不画边）** | 画成箭头 | contains, localized in, resides in, part of |

## 包含与并列（结构层级）
- 包含（containment）：**分组区域**（虚线底色框 + 左上角标签），不是"包含箭头"。
- 并列：同层同排节点，尺寸一致。
- 上下游/因果：rank 单调递增（LR：从左到右；TB：从上到下）。
- 反馈回路：自动绕行（detour）画在行外侧，不得穿过其他节点。

## 布局算法（build_figure.py 内置，确定性）
1. rank：最长路径分层，DFS 破环（back-edge 绕行）。
2. order：层内 barycenter 排序（3 轮扫荡）减少交叉。
3. 尺寸：文本实测（matplotlib renderer），盒宽 = 文本 + 2×pad，非字符数估算。
4. 坐标：列宽累加 + 层内居中堆叠；行宽超限自动换行（多行 serpentine-free）。
5. 缩放：先按原字号布局；超宽则缩至 min_scale（默认 0.8 ≈ 7pt 印刷下限）并换行；
   仍超宽再迭代收缩（≥0.4 下限，audit 会警告过小字号）。
6. 边路由：相邻层直线；跨层肘形；同行/回边绕行；肘线被节点阻挡时自动绕行顶通道。
7. 边标签：自动收缩字号至间隙可容（≥5pt），钳位于画布内，交错高度防碰撞。

## 节点形状语义
rect=过程/复合物；round=分子/状态；stadium=输出/终态；ellipse=刺激/环境因素；
diamond=决策/分支；double 边框=区室/大复合物。分组区域 members 建议给 compartment
（如 Nucleus、Membrane），不要给 compartment 单独建无连线的节点。
