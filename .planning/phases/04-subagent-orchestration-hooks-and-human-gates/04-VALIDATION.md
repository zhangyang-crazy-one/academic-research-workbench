---
phase: 04
slug: subagent-orchestration-hooks-and-human-gates
status: planned
nyquist_compliant: true
execution_verified: false
wave_0_complete: false
created: 2026-07-15
updated: 2026-07-15
---

# Phase 4 Validation Strategy

## Nyquist Status

`nyquist_compliant: true` is valid at planning time because every executable task ID below has a concrete automated command, every roadmap requirement/success criterion/locked decision has an owning task, and the only human checkpoint also has an automated packet-integrity prerequisite. `execution_verified` remains `false` until Plan 08 records real result and evidence digests; an unavailable host qualification remains `BLOCKED`, never a passing substitute.

## Wave and Dependency Matrix

| Execution wave | Plan | Purpose | Depends on |
|---|---|---|---|
| 1 (Wave 0 contract gate) | 04-01 | Contracts, schemas, corpus, fixtures, deterministic tests | — |
| 2 | 04-02 | Canonical events, reducer, workflow authority, immutable manifests | 04-01 |
| 2 | 04-03 | Pure scheduler/execution seam, blind-panel policy, hook contracts | 04-01 |
| 3 | 04-04 | Parent sole-writer lifecycle, scheduler wiring, recovery/replay | 04-02, 04-03 |
| 4 | 04-05 | Formal panel, dissent synthesis, human/freshness gates | 04-03, 04-04 |
| 4 | 04-06 | Concrete hook behavior and five-state parity | 04-03, 04-04 |
| 5 | 04-07 | Thin Codex adapter and exact staged three-home qualification | 04-05, 04-06 |
| 6 | 04-08 | Full corpus/evidence/stage/regression verifier | 04-05, 04-06, 04-07 |
| 7 | 04-09 | Human sealed-case assessment and adjudication checkpoint | 04-08 |

Same-wave file ownership is exclusive: 04-02 and 04-03 have no shared paths; 04-05 and 04-06 have no shared paths. Every later overlap is expressed as an explicit sequential dependency.

## Task-to-Verification Map

| Task ID | Automated verification command | Evidence expected | Execution status |
|---|---|---|---|
| P04-01-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_orchestration_models.py tests/schema/test_phase4_contracts.py` | strict model/schema output | planned |
| P04-01-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/evals/test_phase4_corpus.py` | 48-case manifest, digest/count report | planned |
| P04-01-T03 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_orchestration_models.py tests/unit/test_scheduler.py tests/unit/test_review.py tests/unit/test_hook_contracts.py tests/schema/test_phase4_contracts.py tests/integration/test_orchestration_lifecycle.py tests/integration/test_orchestration_replay.py tests/integration/test_orchestration_panels.py tests/integration/test_orchestration_hook_parity.py tests/integration/test_human_gates.py tests/evals/test_phase4_corpus.py tests/staged/test_phase4_host_qualification.py -m 'not codex_host'` | deterministic collection and owner-mapped strict expected failures | planned |
| P04-02-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_orchestration_models.py tests/unit/test_workflows.py` | parent-only event/workflow proof | planned |
| P04-02-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_reducer.py tests/integration/test_journal_replay.py` | deterministic replay/state output | planned |
| P04-02-T03 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_manifests.py` | immutable assignment/proposal path evidence | planned |
| P04-03-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_scheduler.py` | bounded/order/retry/cancel schedule evidence | planned |
| P04-03-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_review.py` | blind-panel/finding-matrix classifications | planned |
| P04-03-T03 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_hook_contracts.py` | parity and continuation contract results | planned |
| P04-04-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_orchestration_lifecycle.py tests/integration/test_runtime_attempts.py` | frozen run/assignment journal evidence | planned |
| P04-04-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_orchestration_lifecycle.py tests/unit/test_scheduler.py` | ordered parent admission/rejection evidence | planned |
| P04-04-T03 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_orchestration_replay.py tests/integration/test_runtime_attempts.py tests/integration/test_recovery.py tests/integration/test_recovery_crash.py` | cold replay/cancel/orphan evidence | planned |
| P04-05-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_orchestration_panels.py tests/unit/test_review.py` | identity/isolation/reports/dissent evidence | planned |
| P04-05-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_human_gates.py tests/integration/test_orchestration_panels.py` | fresh gate/scoped-decision evidence | planned |
| P04-06-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_hook_contracts.py` | strict hook observation output | planned |
| P04-06-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_orchestration_hook_parity.py tests/unit/test_hook_contracts.py` | five-state parity/no-bypass evidence | planned |
| P04-07-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/staged/test_phase4_host_qualification.py -m 'not codex_host'` | native/degraded/blocked adapter classification | planned |
| P04-07-T02 | `ARW_REQUIRE_CODEX_HOST=1 UV_OFFLINE=1 uv run --frozen pytest -q tests/staged/test_phase4_host_qualification.py -m codex_host` | three fresh-home exact-stage host tuples | planned; requires authenticated Codex |
| P04-08-T01 | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_phase4_verifier.py && UV_OFFLINE=1 ./scripts/verify-phase-4 --clean --evidence-root build/evidence/phase-04 --allow-host-blocked` | fail-closed verifier and BLOCKED-or-PASS verdict | planned |
| P04-08-T02 | `UV_OFFLINE=1 uv run --frozen pytest -q --runxfail tests/evals/test_phase4_corpus.py tests/integration/test_orchestration_replay.py tests/integration/test_orchestration_lifecycle.py tests/integration/test_orchestration_panels.py tests/integration/test_orchestration_hook_parity.py tests/integration/test_human_gates.py` | all 48 parent-evaluated cases and replay matrix | planned |
| P04-08-T03 | `ARW_REQUIRE_CODEX_HOST=1 UV_OFFLINE=1 ./scripts/verify-phase-4 --clean --evidence-root build/evidence/phase-04 --require-host && UV_OFFLINE=1 uv run --frozen pytest -q --runxfail` | top technical verdict plus full regression evidence | planned; requires authenticated Codex |
| P04-09-T01 | `UV_OFFLINE=1 ./scripts/verify-phase-4 --evidence-root build/evidence/phase-04 --prepare-human-review` | digest-bound review packet | planned; blocking human assessment |

No task lacks an automated check. Plan 08 must remove all Phase 4 strict expected failures using `--runxfail`; no test skip or host-auth absence can support a technical PASS.

## Source Coverage Audit

| Source | Item | Covered by task IDs | Coverage |
|---|---|---|---|
| GOAL | Immutable proposals under a sole-writer canonical runtime with auditable, replayable, deterministic, accountable specialized agents/reviews/hooks/humans | P04-01-T01, P04-02-T01..T03, P04-04-T01..T03, P04-05-T01..T02, P04-06-T01..T02, P04-08-T01..T03, P04-09-T01 | covered |
| ROADMAP | SC-01 — scoped/schema-valid assignments and no worker canonical mutation | P04-01-T01, P04-02-T01..T03, P04-04-T01..T02 | covered |
| ROADMAP | SC-02 — deterministic scheduler with bounded concurrency, timeout, cancellation, retry, and orphan recovery | P04-03-T01, P04-04-T02..T03, P04-08-T02 | covered |
| ROADMAP | SC-03 — distinct isolated independent reports, dissent, synthesis, and honest degraded/block classification | P04-03-T02, P04-05-T01, P04-07-T01..T02, P04-09-T01 | covered |
| ROADMAP | SC-04 — hook parity across runtime/MCP/integrity/gate/provenance with no bypass | P04-03-T03, P04-04-T02, P04-06-T01..T02, P04-07-T02 | covered |
| ROADMAP | SC-05 — PASS/FAIL/BLOCKED freshness and scoped nonrewrite human decisions | P04-02-T02, P04-05-T02, P04-08-T01..T03, P04-09-T01 | covered |
| REQ | PKG-05 — recorded execution mode and truthful formal/degraded/blocked claims | P04-01-T01, P04-02-T01, P04-03-T02, P04-04-T01, P04-07-T01..T02, P04-08-T01 | covered |
| REQ | AGT-01 — immutable parent dispatch assignment | P04-01-T01, P04-02-T03, P04-04-T01 | covered |
| REQ | AGT-02 — schema-valid immutable worker proposal, no canonical worker mutation | P04-01-T01, P04-02-T01..T03, P04-04-T02 | covered |
| REQ | AGT-03 — deterministic parent accept/reject/retry/cancel/supersede | P04-02-T02, P04-03-T01, P04-04-T02..T03 | covered |
| REQ | AGT-04 — formal independent panel/dissent/synthesis | P04-03-T02, P04-05-T01, P04-09-T01 | covered |
| REQ | AGT-05 — concurrency, timeout, cancellation, retry, orphan recovery | P04-03-T01, P04-04-T03, P04-08-T02 | covered |
| REQ | AGT-06 — noncanonical hooks | P04-03-T03, P04-06-T01..T02 | covered |
| REQ | AGT-07 — disabled/failed hooks cannot bypass controls | P04-03-T03, P04-06-T02, P04-08-T02 | covered |
| REQ | SCI-02 — fresh PASS/FAIL/BLOCKED gates deny premature finalization | P04-02-T02, P04-05-T02, P04-08-T01..T02 | covered |
| REQ | SCI-03 — scoped append-only waiver/correction/access/approval | P04-01-T01, P04-02-T02, P04-05-T02, P04-09-T01 | covered |
| RESEARCH | strict contracts/event/reducer/workflow/manifest architecture and no new dependency | P04-01-T01, P04-02-T01..T03, P04-08-T01 | covered |
| RESEARCH | deterministic scheduler, fake adapter, frozen-order parent admission, recovery | P04-03-T01, P04-04-T02..T03, P04-08-T02 | covered |
| RESEARCH | formal blind panel, finding matrix, dissent, and human gates | P04-03-T02, P04-05-T01..T02, P04-09-T01 | covered |
| RESEARCH | observational hook parity and continuation limits | P04-03-T03, P04-06-T01..T02 | covered |
| RESEARCH | Codex adapter, exact staged canary, identity qualification, no transcript authority | P04-07-T01..T02, P04-08-T01..T03 | covered |
| RESEARCH | 32 development + 16 sealed corpus, full evaluations, evidence verdict | P04-01-T02..T03, P04-08-T01..T03, P04-09-T01 | covered |
| CONTEXT | D-01 — versioned role catalog and experiment designer only | P04-01-T01, P04-04-T01 | covered |
| CONTEXT | D-02 — native profile preferred; assignment-injected fallback degraded; unavailable independence BLOCKED | P04-01-T03, P04-02-T01, P04-07-T01..T02 | covered |
| CONTEXT | D-03 — no controlled experiment execution roles | P04-01-T01, P04-04-T01 | covered |
| CONTEXT | D-04 — role conflict matrix | P04-01-T01, P04-02-T01, P04-03-T02, P04-05-T01 | covered |
| CONTEXT | D-05 — immutable assignment/retry/supersession bindings | P04-01-T01, P04-02-T03, P04-04-T01..T02 | covered |
| CONTEXT | D-06 — frozen DAG/layer/ordinal order | P04-01-T01, P04-02-T02, P04-03-T01, P04-04-T02 | covered |
| CONTEXT | D-07 — one eligible retry and blocked exhaustion | P04-01-T01, P04-02-T02, P04-03-T01, P04-04-T03 | covered |
| CONTEXT | D-08 — cooperative cancellation, grace, termination, stale/interrupt/replacement | P04-01-T01, P04-02-T02, P04-03-T01, P04-04-T03 | covered |
| CONTEXT | D-09 — four formal workers and separate synth | P04-01-T01, P04-03-T02, P04-05-T01 | covered |
| CONTEXT | D-10 — same rubric, isolated reviewers, later cross-review only via new assignment | P04-01-T01, P04-03-T02, P04-05-T01 | covered |
| CONTEXT | D-11 — required reports/optional policy/limitations/blocker | P04-01-T01, P04-02-T02, P04-03-T02, P04-05-T01 | covered |
| CONTEXT | D-12 — finding matrix/dissent/critical blocker | P04-01-T01, P04-02-T02, P04-03-T02, P04-05-T01..T02 | covered |
| CONTEXT | D-13 — five hook trust states and parity | P04-01-T01, P04-03-T03, P04-06-T01..T02 | covered |
| CONTEXT | D-14 — one bounded SubagentStop/Stop continuation and parent validation | P04-01-T01, P04-03-T03, P04-04-T02, P04-06-T01..T02 | covered |
| CONTEXT | D-15 — rationale-required human gate triggers and automatic intermediate PASS only when fresh | P04-01-T01, P04-02-T02, P04-05-T02, P04-09-T01 | covered |
| CONTEXT | D-16 — no rewrite; scoped waiver/correction/approval semantics | P04-01-T01, P04-02-T01..T02, P04-05-T02, P04-09-T01 | covered |

## Explicit Exclusions

The following deferred ideas are intentionally absent from every plan and test: controlled `code_runner`/`study_manager` experiment execution, research graph projection, general scientific methods/dossier work, and full installed compatibility/release qualification. The Phase 4 technical verifier preserves the separate SUP-04 release status as `BLOCKED`.

## Final Technical and Human Gates

1. Run `UV_OFFLINE=1 ./scripts/verify-phase-4 --clean --evidence-root build/evidence/phase-04 --require-host` in an authenticated environment. Technical PASS requires all requirement/decision/roadmap/task verdicts, exact stage, all 48 cases, no Phase 4 xfail/skip, and three qualified fresh host tuples.
2. If the host path is unavailable, retain its schema-valid BLOCKED verdict and exit 77; do not reinterpret it as technical PASS.
3. Run `UV_OFFLINE=1 ./scripts/verify-phase-4 --evidence-root build/evidence/phase-04 --prepare-human-review`, then complete Plan P04-09-T01's independent assessor/adjudicator review.
4. Set `execution_verified: true` only after steps 1 and 3 have retained their required evidence and a lawful append-only human decision or explicit BLOCKED outcome exists.

## 2026-07-15 Qualification Closure Reconciliation

The stale pre-04.1 command examples above are superseded by the retained,
resource-bounded verifier evidence below. Commands were run serially so staged
installation probes do not accumulate their peak memory.

| Area | Retained evidence | Result |
|---|---|---|
| ARS/ARW/file-base/Codex/hook integration lock | `build/evidence/phase-04.1-host-canary-20260715e/integration-lock.json` | PASS; digest `b84c888a6d4716efe5419e37ddf99ed2f2af8a6ed05924fc435e0554a11e372d` |
| Exact locked stage and inventory/SBOM/build identity | `build/tmp/qualification-stage-final-20260715e/`, `commands/stage/exit.json` | PASS |
| Codex 0.144.4 three fresh HOME canary and hook parity | `build/evidence/phase-04.1-host-canary-20260715e/{canary,evidence-bundle}.json` | PASS |
| Parent lifecycle, replay, panel, gates, human authority | `commands/full-pytest/exit.json`, `commands/durable-runtime/exit.json`, Phase 4 integration exits | PASS |
| Staged families and exact route | `commands/staged-*/exit.json` | PASS |
| Phase 1/2/3 regression verifiers | `commands/phase-{1,2,3}-regression/exit.json` | PASS |
| Parent-only 48-case corpus | `corpus/evaluation-summary.json` and case digests | PASS |
| Technical parent verdict | `build/evidence/phase-04.1-verifier-final-20260715f/verdict.json` | PASS |
| P04-09 human assessor/adjudicator | `review-packet/manifest.json` exists; attestations absent | BLOCKED checkpoint |
| SUP-04/CC BY-NC intended-use/distribution/approval/permission | license/use-distribution evidence | BLOCKED release gate |

Paper AST/export and full research-to-paper workflow remain explicitly v2.
