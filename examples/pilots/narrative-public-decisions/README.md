# #120 公开研究决策标注材料

[annotations.csv](annotations.csv) 已逐条录入作者在当前会话给出的十项人工标注；第 3 项选择 **B：允许维度缺省**。`human_annotation` 保留回答原文，`selected_option` 记录 B，其余项没有补造选项。

这些回答以 `annotation_basis=owner_response` 记录，内容包括采用意见和报备、转换、优化的条件。它们是真实人工输入，不自动等于 NumPy 的历史结论。因此 `human_status`、`reason_status`、`human_reason` 的历史判定字段保持空白，未从回答中补造四类状态或原作者动机。`annotator_id=owner`，`evidence_locator` 定位当前会话中的回答；`annotated_at_utc` 为代录时间，不声称是原消息发送时间。

样本限定为 NumPy 的科学计算方法与研究基础设施提案。它们会影响数值研究和实验实现，但不是十篇独立论文；不能据此宣称普遍准确率。来源页面的 Status 只是已记录的公开元数据，不是替你填写的判定。

每项请阅读固定 commit 的 Status、Resolution、Abstract 和理由讨论；如文档链接到决议，可继续查阅，并在 evidence_locator 记录具体标题、行号或决议链接。若动机无法确认，请将 reason_status 填为 `unknown`，human_reason 留空。不要从 diff 推测动机。

| 样本 | 待核实的决策 | 固定来源 |
|---|---|---|
| nep-0019 | 随机数流兼容策略 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0019-rng-policy.rst) · [阅读版](https://numpy.org/neps/nep-0019-rng-policy.html) |
| nep-0018 | 高层数组函数分派 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0018-array-function-protocol.rst) · [阅读版](https://numpy.org/neps/nep-0018-array-function-protocol.html) |
| nep-0020 | 广义通用函数签名扩展 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0020-gufunc-signature-enhancement.rst) · [阅读版](https://numpy.org/neps/nep-0020-gufunc-signature-enhancement.html) |
| nep-0034 | 不自动推断不规则序列为 object | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0034-infer-dtype-is-object.rst) · [阅读版](https://numpy.org/neps/nep-0034-infer-dtype-is-object.html) |
| nep-0038 | SIMD 向量化优化 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0038-SIMD-optimizations.rst) · [阅读版](https://numpy.org/neps/nep-0038-SIMD-optimizations.html) |
| nep-0050 | Python 标量类型提升 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0050-scalar-promotion.rst) · [阅读版](https://numpy.org/neps/nep-0050-scalar-promotion.html) |
| nep-0011 | 延迟 UFunc 求值 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0011-deferred-ufunc-evaluation.rst) · [阅读版](https://numpy.org/neps/nep-0011-deferred-ufunc-evaluation.html) |
| nep-0016 | 识别 duck arrays 的抽象基类 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0016-abstract-array.rst) · [阅读版](https://numpy.org/neps/nep-0016-abstract-array.html) |
| nep-0017 | 将 masked arrays 拆出 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0017-split-out-maskedarray.rst) · [阅读版](https://numpy.org/neps/nep-0017-split-out-maskedarray.html) |
| nep-0037 | NumPy-like 模块分派 | [源码与行号](https://github.com/numpy/numpy/blob/db8bac3fa50b6843fd72db54b145e04253447d38/doc/neps/nep-0037-array-module.rst) · [阅读版](https://numpy.org/neps/nep-0037-array-module.html) |

## 标注规则

- `human_status`：`kept`（明确保留/采用）、`superseded`（明确由新方案替代）、`abandoned`（明确撤回/拒绝）、`unknown`（无法由公开证据确认）。暂缓不自动等于放弃。
- `reason_status`：`documented` 或 `unknown`。documented 时用自己的话填写 human_reason 并给出证据定位；unknown 不填写猜测理由。
- `annotator_id`：你的标注身份；`annotated_at_utc`：实际标注时间，形如 `2026-10-12T12:00:00Z`，不要提前填写。
- `sample_id` 和 `source_sha256` 保持不变；表格编辑器需按文本保存摘要。

运行 `python3 scripts/check-narrative-pilot-annotations`，检查分别统计作者回答和来源历史判定。十项作者回答已完整记录；来源历史比对准备状态仍为 false。旧版仅包含历史判定字段的 CSV 保持可读。该检查不会将人工填写自动算作 ARW 输出或 pilot 一致率。

## 当前证据范围

材料在 2026-10-12 检索，使用 materials.json 中固定的 NumPy commit 和逐文件 SHA-256。只保存原始简述和来源元数据，不复制上游正文；原文版权仍归 NumPy 作者。protocol.json 在人工标注前冻结机器状态映射。

作者回答已录入；来源历史的结构化判定、真实 narrative 导出与比对、两轮 handoff/resume 尚未完成。#120 保持开放，PR 不宣称完成这些验收项。公开来源的冻结机器映射未因作者回答而调整。
