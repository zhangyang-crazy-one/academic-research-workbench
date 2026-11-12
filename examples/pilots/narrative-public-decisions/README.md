# #120 公开研究决策标注材料

[annotations.csv](annotations.csv) 已录入作者在阅读来源解释后给出的十项历史状态判定：第 1–6、10 项为 `kept`，第 7 项为 `unknown`，第 8–9 项为 `abandoned`。`human_annotation` 保留本次回答原文，包括第 8 项“撤销”和第 9 项“放弃”；这是来源解释辅助下的人工判定，不声称为盲标或独立复标。

本次回答只确认状态，未确认具体历史理由。因此 `reason_status=unknown`，`human_reason` 留空，不将此前提供的候选理由自动记为人工确认。`annotation_basis=source_history`；`evidence_locator` 同时定位本次会话回答和固定版本来源。`annotator_id=owner`，`annotated_at_utc` 为代录时间，不声称是原消息发送时间。

此前十项采用、报备等意见原样保存在 [owner-policy-responses.csv](owner-policy-responses.csv)，包括第 3 项 **B：允许维度缺省**。该文件仍使用 `annotation_basis=owner_response`，不转译为历史标签，也不替换本次回答。

第 10 项人工判定为 `kept`，固定来源的状态观察为 `Superseded`。两者均原样保留；后续比对应报告差异，不能修改人工回答或已冻结机器映射以消除差异。

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

运行 `python3 scripts/check-narrative-pilot-annotations`，校验本次十项历史状态标签。历史比对准备状态为 true；旧版 CSV 保持可读。该检查不会将人工填写自动算作 ARW 输出或 pilot 一致率。此前作者意见另存，不与当前历史状态表混计。checker 只检查输入，因此其中 agreement/handoff 字段仍为 not_evaluated；实际运行结论以 evidence/report.json 和离线重放结果为准。

## 当前证据范围

材料在 2026-10-12 检索，使用 materials.json 中固定的 NumPy commit 和逐文件 SHA-256。只保存原始简述和来源元数据，不复制上游正文；原文版权仍归 NumPy 作者。protocol.json 在人工标注前冻结机器状态映射。

十项历史状态已确认并录入，理由均保持 unknown。真实 narrative 导出、比对及两轮 handoff/resume 已执行并留存；公开来源的冻结机器映射未因作者回答而调整。#120 的验收材料已补齐，等待本 PR 审查后合并关闭。


## 实际运行与比对

[evidence/report.json](evidence/report.json) 保存十项实际导出及逐条比对，[comparison.csv](comparison.csv) 提供便于阅读的同一比对表。[evidence/inventory.json](evidence/inventory.json) 绑定保留文件的字节摘要。每个项目的 `.arw/narrative/events.jsonl` 是实际命令生成的规范事件链，`commands/` 保留 CLI 参数、时间、退出码及原始 stdout/stderr。初始化 registration 返回 `missing_selection` / exit 65 是预期状态；随后必须真实选择，其他意外失败均中止执行。

| 样本 | 人工状态 | 实际 trail 状态 | 比对 |
|---|---|---|---|
| nep-0019 | kept | kept | 一致 |
| nep-0018 | kept | kept | 一致 |
| nep-0020 | kept | kept | 一致；固定／可缺省维度获接受，广播扩展暂缓 |
| nep-0034 | kept | kept | 一致 |
| nep-0038 | kept | kept | 一致 |
| nep-0050 | kept | kept | 一致 |
| nep-0011 | unknown | unknown | 明确不确定，单列 |
| nep-0016 | abandoned（撤销） | abandoned | 一致 |
| nep-0017 | abandoned（放弃） | abandoned | 一致 |
| nep-0037 | kept | superseded | 差异：人工选择保留，公开来源记录被替代 |

已知状态中 **8 项一致、1 项差异**，另有 **1 项明确不确定**。包含双方 unknown 的字面相等数为 9；不将 unknown 算成已确认采用／撤回，也不以此宣称普遍准确率。历史原因的人工判定均 unknown，已评估的具体历史理由为 0；导入命令的操作说明不算原作者动机。

## 两轮交接与恢复

NEP 16 与 NEP 17 各运行两轮，共四次：真实 `memory handoff` → `checkpoint` → 新进程 `resume --memory-handoff`。每次恢复都记录 `resume.accepted`，使用当轮新的 Material Passport；第二轮 handoff 明确 supersede 第一轮 memory。保存与恢复返回的 narrative summary 相等，当前 choice ID 不变，被放弃 choice 始终在 `abandoned_routes` 中，未进入 `current_choices`。规范 author-target artifact、memory body、Passport、run manifest 和 segmented journal 一并保留。

这是 **CLI 控制平面的恢复证据**：验证弃用提示与操作员写明的后续动作，没有运行付费模型，也不声称验证模型自由生成的推荐内容或真实 NumPy 作者的研究会话。

## 复现与证据边界

导入器读取固定来源文件的实际 `Status`，按已冻结映射通过现有 narrative 命令录入；直到比对阶段才读取人工标签。每项使用隔离项目。待定／弃用案例所需的初始选择是明确标记的 scaffold；这些辅助 choice 不参与十项比对。superseded 案例的 successor 也是回放 scaffold，不声称重建了原作者完整的论文叙事或决策时间线。

`--author-confirmed` 在这些回放中只记录 `pilot.source-replay` 操作员基于公开状态执行导入的声明，不能作为 NumPy 作者在 ARW 内认证或授权的证据。固定来源的全文在运行前逐文件核对 SHA-256，未重新分发上游全文。原始研究动机没有从变更 diff 推测。

使用本仓库已安装依赖的 Python，先将 materials.json 指定的固定源文件保存为 SOURCE_CACHE/<sample_id>.rst；脚本会逐一验证摘要。输出目录必须不存在：

```sh
.venv/bin/python scripts/run-public-narrative-pilot \
  --source-cache SOURCE_CACHE --output build/narrative-pilot-new
.venv/bin/python scripts/run-public-narrative-pilot \
  --verify-evidence examples/pilots/narrative-public-decisions/evidence
```

`--verify-evidence` 离线重新投影实际规范事件链、读取并校验 canonical memory、检查四次 resume 接纳事件，重算比对报告并核对字节清单。它不重新下载上游全文；全文摘要核对发生在原始执行时。SQLite 是可重建缓存，未纳入证据清单和提交。

运行采用 `bin/arw` 的 local-dev 路径，并显式绑定本仓库 `.codex-plugin/plugin.json`。当前启动器的通用 resume 分支未自动传入 manifest，单独复现会得到 `memory_request_invalid`；显式绑定后恢复成功。此配置问题已独立登记为 [#145](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/145)，不在 #120 中修改运行时。实际 Python 版本和执行源码摘要见 [evidence/execution.json](evidence/execution.json)，属于观察记录，不是兼容性精确版本要求。
