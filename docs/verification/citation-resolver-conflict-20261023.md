# Citation resolver / self-report conflict verification — 2026-10-23

已验证：#36 最后一项验收存在实际生产接线缺口，本次补齐。#41 是 umbrella；没有据此扩大其他科研能力范围。

核验输入为主库保留的 `build/verification/upstream-audit-20261023/issues.json` 中完整 #36/#41。#36 的 `comments` 为空，未发现该 issue 的 owner 修订；对应审计索引的 `owner_revisions` 也是空数组。验收原文要求：“`ContaminationSignals` 可以由 resolver receipt 派生，并与模型自报值不一致时产生 conflict 记录。”核对现有 OpenSpec、图和实际代码后，确认图中的 `contamination_signals` 仅有单测 caller，`_canonical_citation_gate` 从 accepted receipts 生成 gate，却从未读取 ARS self-report。原有撤稿/缺失 gate 仍有作用，缺陷局限于污染信号及冲突证据未接入。

基线是本地 `origin/main` 的 `c8760e03df9843a69b68141f1e15a0dbf397a768`。远端 fetch 未响应而停止，因此未验证该 ref 是否为远端最新状态。

## 行为和使用

`citation gate` 始终调用现有 contamination contract 派生观察；新增可选参数 `--literature-entry PATH`，输入是 passport 的一条 `literature_corpus[]` JSON 快照。现有 ARW checkpoint passport 不含这份 ARS 文献条目，因此输入须显式导出和选择，不能从 checkpoint 指针臆造模型自报。

Canonical 路径要求精确输入字节已通过 `artifact-accept` 接受为 `ars-literature-entry`，并核对 citation key、title、authors、year、DOI、arXiv ID。若 reference 带有 `source_manifest_sha256`，还必须存在已接受的 `research-source-manifest`，匹配 reference 和条目完整 canonical bibliographic digest。普通本地 proposal 可以使用未接受的条目，但依旧返回 `parent_admission: required`，不写 gate journal。

```bash
# ARW_PYTHON 指向调用方已有的项目 venv Python。
PYTHONPATH="$PWD/src" "$ARW_PYTHON" -m arw.cli citation gate \
  --reference "$RUN_ROOT/reference.json" \
  --use "$RUN_ROOT/use.json" \
  --store "$RUN_ROOT" --provider crossref \
  --run-root "$RUN_ROOT" --request "$GATE_REQUEST" \
  --literature-entry "$RUN_ROOT/entry.json"
```

CLI JSON 的 `contamination_observation` 与 `gate.evaluated` 的 rationale 末尾 `; contamination=` 后的 canonical JSON 相同；读取持久记录时按最后一个该分隔符提取 JSON。`evidence_sha256` 绑定 reference、use、所有 accepted resolver receipts，以及所选条目和必要的 source manifest 的 artifact manifest digests。观察中的 `literature_entry_sha256` 指向精确条目字节。

- `contamination_signals` 只使用 conclusive `not_found / verified / retracted` 派生 unmatched 布尔值。`retracted` 的 unmatched=false 只表示索引找到身份；撤稿阻断仍由独立 citation gate 保留。
- `lookup_states` 保留 provider 最近观察状态。未查询 provider 没有记录，不能读成 checked-and-clean。`unavailable` 在既有 `contamination_signal_omissions` 中派生 `api_degraded`；unknown/ambiguous 不伪造 true/false 或降级原因。DBLP 没有既有 unmatched 字段，Semantic Scholar 没有此 resolver，均不发明对应信号。
- `self_reported` 原样保留条目显式给出的 signals/omissions；未提供条目是 null，字段缺失和 omission 都不当作 false。preprint heuristic 不被索引观察覆盖。
- `conflicts` 对每个 retained conclusive receipt 保存 `signal / reported_value / resolver_value / receipt_sha256`。后续 agreement/outage 不删除此前冲突；已有 journal 事件也不改写。
- 条目原字节、`user_notes`、manual 来源、`source_acquired`、原始检索失败和人工决定保持原样。模型自报不改变 resolver gate verdict；观察和冲突也不等于对科学论断的裁定或自动 waiver。
- 旧 reference/check receipt/gate event 不迁移。未给 `--literature-entry` 的旧调用继续工作并派生 resolver 观察，`self_reported=null`，不虚构冲突。

## 实际验证

所有命令在修复工作树运行，`PYTHONPATH` 指向该树 `src`，Python 使用主库已有 venv。`ARW_PRIMARY_CHECKOUT` 指向主库根目录；文档用环境变量表达这些位置，不固化个人机器路径。

```bash
PYTHONPATH="$PWD/src" "$ARW_PYTHON" -m pytest -q \
  tests/unit/test_citations.py \
  tests/unit/test_citation_contamination.py \
  tests/integration/test_citation_gate_canonical.py \
  tests/integration/test_citation_contamination_cli.py \
  tests/integration/test_scholarly_cli.py
# 63 passed in 52.63s

# 测试快照改用独立保留路径后，仅重跑受影响的完整 CLI 文件。
PYTHONPATH="$PWD/src" "$ARW_PYTHON" -m pytest -q tests/integration/test_citation_contamination_cli.py
# 12 passed in 45.87s

PYTHONPATH="$PWD/src" "$ARW_PYTHON" -m pytest -q -m v2_compat tests/compat
# 74 passed, 3 skipped in 67.12s

ruff check src/arw/kernel/policy/citations.py src/arw/cli_scholarly.py \
  tests/unit/test_citation_contamination.py tests/integration/test_citation_contamination_cli.py
# All checks passed!

pyright --venvpath "$ARW_PRIMARY_CHECKOUT" \
  src/arw/kernel/policy/citations.py src/arw/cli_scholarly.py
# 0 errors, 0 warnings, 0 informations

openspec validate citation-resolver-retraction-gate --strict
# Change 'citation-resolver-retraction-gate' is valid

git diff --check
# 无输出，退出 0
```

TDD RED：新增策略测试最先得到 `13 failed`（缺少 observation 函数）；完整 CLI 测试先执行 init → reference/use/entry artifact acceptance → fixture check → receipt acceptance，然后在 gate 得到退出 2，`--literature-entry` 未识别。随后实现生产接线，才得到上述 GREEN。原有的 34 项 citation 回归也独立通过。完整 CLI 测试会为每一步创建新 Python 进程，覆盖 init、artifact-accept、citation check、canonical/local gate 和冷 replay；并在每个进程禁止 Python socket connect 和 urllib HTTP 入口。HTTP 503 是 transport seam 的 fixture `HTTPError`，不冒充真实服务运行。

| 验收场景 | 结果 | 证据 |
| --- | --- | --- |
| not_found + self-report false / verified + self-report true | PASS：两个方向均持久保留不同布尔值和 receipt digest | `test_full_cli_retains_conflict_and_never_overwrites_self_report` |
| not_found + true / verified + false | PASS：一致值不产生冲突，原 gate FAIL/PASS 保持 | 同上参数化用例 |
| 服务 503 + 两种布尔 self-report | PASS：BLOCKED / unavailable / api_degraded，无 not_found/retracted/conflict | `test_full_cli_service_unavailable_is_degraded_not_missing_or_retracted` |
| 没有 resolver receipt但模型声称 matched | PASS：BLOCKED，signals/omissions/conflicts 为空 | `test_full_cli_unchecked_provider_keeps_unknown_even_if_model_reports_match` |
| manual、缺失 signal、self-report api_degraded、人工批注、原文未取得 | PASS：不补造布尔矛盾，不改字节和 source_acquired | `test_full_cli_legacy_missing_self_report_and_manual_annotations` |
| not_found 后 verified recheck | PASS：旧 conflict 和 blocker 保留；原事件 bytes 不变 | `test_full_cli_historical_conflict_survives_later_agreement` |
| 未接受/篡改/身份不匹配条目 | PASS：canonical gate 拒绝，不生成 gate event | `test_full_cli_rejects_unaccepted_changed_or_wrong_entry` |
| source-bound reference 与完整条目快照绑定 | PASS：缺 accepted source 或 bibliographic digest 不同即拒绝 | `test_full_cli_bound_source_requires_accepted_exact_passport_entry` |
| 本地 proposal 比较未接受条目 | PASS：同样产生 conflict，仍需 parent admission | `test_full_cli_local_proposal_has_same_observation_without_admission` |
| Crossref/OpenAlex/arXiv、撤稿身份、ambiguous/unknown、后续 outage | PASS：按既有字段契约派生，不覆盖未支持字段/heuristic | `tests/unit/test_citation_contamination.py` |
| 旧 parser replay、旧 canonical gate、kernel dependency/CLI/replay baseline | PASS（native 前提除外） | 既有 citation tests、compat suite |

可复查运行输出保留在工作树 `build/verification/citation-conflict-20261023/` 下的 `targeted.txt`、`cli-final.txt`、`compat.txt` 和 `static.txt`，该 build 目录按项目规则不提交。Ruff 对 `src/arw/cli.py` 的检查发现一处既有 I001（无关导入排序）；对 `origin/main` 同文件重跑同样命中，未顺手改动。Pyright 初次将 `--pythonpath` 和 `--venvpath` 同用，被工具拒绝；上面的最终命令仅使用 `--venvpath`。

## 未验证

未进行 live provider 查询、真实 Codex 宿主 qualification、release 或全仓测试。兼容套件 3 项因工作树缺少 native `.file-base/bin/file-base` 而 skip。离线证据是受 guard 的 Python CLI 子进程和 retained-byte replay，未运行操作系统 network namespace 隔离门禁。

原有 gate rationale 上限仍为 4096 字符，evidence 上限仍为 128 项；添加完整冲突后超限会明确拒绝，不能截断或静默丢失冲突。此补丁不提供整份 ARS passport 自动发现/写回、科学真值判决、人工 waiver 签字或自动释放历史 blocker。

阻塞：无本地实现/提交阻塞。远端 freshness、native 门禁和真实在线服务不计为已验证。
