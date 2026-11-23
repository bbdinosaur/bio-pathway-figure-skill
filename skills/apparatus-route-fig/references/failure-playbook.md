# 异常处置手册（failure-playbook）

| 情形 | 识别 | 处置 | result.json 记录 |
|---|---|---|---|
| 部件参数缺失 | 材料无流速/温度/尺寸等数值 | attrs 写 `"TBD"`，不编造；图上保留参数位 | uncertainty 列出缺失参数+建议补测 |
| 工艺描述歧义 | 同一步骤两种可能顺序 | 选与正文动词/时序一致的方案；另一候选不画 | uncertainty 写两候选+选择依据 |
| 接口/连接冲突 | 材料前后文连接矛盾 | 以方法节末尾/总结性句子为准 | uncertainty 引用冲突两处原文 |
| SIR 校验失败(退出码2) | checks_report.stage=sir_validate | 修 id 重复/断头连接/缺 label 后重跑 | — |
| SVG→PNG/PDF 全失败 | render_meta 含 error | run_all 自动落 matplotlib 镜像；或用平台 office-renderer 转换 | render 字段记录实际引擎 |
| 中文字体缺失(豆腐块) | render_meta.cjk_family=null 或看图异常 | render.py 自动 fc-list 探测；仍失败→英文标签重出图 | uncertainty 注明语言降级 |
| 画布溢出 | checks errors 含"越界" | `--maxcols 4` 分带；缩短 label；重跑 | — |
| 节点重叠 | checks errors 含"重叠" | 多由 label 过长引起，精简或换行 | — |
| 节点过多(>14) | 布图拥挤 | 拆主图+局部放大两图；两图分列 result.json deliverables | change_records 记拆分 |
| 材料为扫描件 | pdf-text 抽不出文字 | 用 ocr-tool；OCR 结果照常做 quote，loc 标页码 | uncertainty 注明 OCR 置信 |
| 输出目录只读 | 写失败 | 降级写 /app/work 并在 result.json 指明路径 | limits 写明 |
| 预算紧张 | 已用>40 请求 | 跳过精修 pass，保完整交付：SIR→run_all→result.json | status=partial 说明 |

**降级底线**：任何异常下至少交付 ①合法 SVG 源文件 ②一张可用位图 ③checks_report.json
④含 status/uncertainty 的 result.json。宁可 partial，不可静默丢弃。
