# 视觉与导出规范（style-guide）

## 1. 配色（色盲友好、打印安全）

节点底色/描边（由 sir.py 自动应用，无需手填）：
- 装置/步骤 `#E8F1FB/#2B6CB0`；判定 `#FFF4E0/#C05621`；起点 `#E6FFED/#2F855A`；终点 `#FED7D7/#C53030`
- 输入 `#F0FFF4/#38A169`；输出 `#FAF5FF/#6B46C1`；废料 `#F7FAFC/#718096`
- 储存 `#FEFCBF/#B7791F`；检测 `#EBFBFF/#00838F`
- 路线阶段强调色序：`#2B6CB0 #2C7A7B #6B46C1 #C05621 #2F855A #B83280`
连接：物料 `#2B6CB0` 实线；信号 `#805AD5` 虚线6,4；数据 `#2C7A7B` 点线2,4；
回流 `#C05621` 虚线7,4；阶段交付 `#2F855A` 实线；反馈 `#C05621` 虚线。
文字：主 `#1A202C`、次 `#4A5568`、弱 `#718096`；深底上用白字。新增颜色必须登记进图例。

## 2. 版式

- 字号：标题 20bold、副标题 12.5、节点标签 13.5bold、属性 11.5、边标签 11.5、图例 12。
- 边距：图左/右 56–64px，标题带 ≥100px；节点盒宽 200px；列间距 112px；行距 44px。
- 路线图：列宽 260px、列距 96px、时间轴带 150px。
- 边标签放线段上方，白底衬垫防压线；多标签同源错开 13px。
- 图例在底部独立条带；溯源脚注右下角 10.5pt 灰字。

## 3. 导出规范

- PNG 300dpi（论文正式导出件）、视觉自检预览 96–100dpi（严格 ≤108dpi）；PDF 矢量（字体随渲染器嵌入或转曲）。
- SVG 分层：`layer_frame/nodes/links/labels/legend/footer`，逐元素 `data-prov`/`data-prov-loc` 溯源。
- 单栏图 ≤1600px 宽、双栏 ≤2200px、汇报横版 16:9 建议 1600×900 构思。
- 字体链：Noto Sans CJK SC → Noto Sans SC → Source Han Sans SC → WenQuanYi → sans-serif。
- 检查命令：`checks_report.json` errors=0；人工核对 PNG：无重叠/无越界/无截断。

## 4. 数据图表（matplotlib 模板）

```python
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.sans-serif": ["Noto Sans CJK SC", "Noto Sans SC", "sans-serif"],
                     "axes.unicode_minus": False, "font.size": 11,
                     "axes.grid": True, "grid.alpha": .3, "figure.dpi": 300,
                     "svg.fonttype": "none", "pdf.fonttype": 42})
PAL = ["#2B6CB0", "#C05621", "#2F855A", "#6B46C1", "#B83280"]
fig, ax = plt.subplots(figsize=(6.0, 3.6))          # 单栏6in宽
for i,(name,y) in enumerate(series.items()):
    ax.plot(x, y, "-o", ms=3.5, lw=1.4, color=PAL[i], label=name)  # 数据必须来自材料
ax.set_xlabel("时间 (min)"); ax.set_ylabel("降解率 (%)")   # 单位不可省
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig("chart.png", dpi=300); fig.savefig("chart.pdf"); fig.savefig("chart.svg")
```
散点/柱状同理；多子图用 `constrained_layout=True`；每条曲线在 result.json 记录数据出处。
