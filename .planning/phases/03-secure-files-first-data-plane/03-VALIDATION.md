---
phase: 03
slug: secure-files-first-data-plane
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 03 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest through the frozen `uv` environment; native C exercised by repository build and subprocess JSON-RPC fixtures |
| **Config file** | `pyproject.toml`, `uv.lock`, `vendor/python/wheelhouse.lock.json` |
| **Quick run command** | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit tests/schema` |
| **Phase run command** | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit tests/schema tests/integration/test_files_admin.py tests/integration/test_file_generations.py tests/integration/test_files_mcp.py tests/integration/test_files_formats.py tests/integration/test_files_security.py` |
| **Full suite command** | `UV_OFFLINE=1 uv run --frozen pytest -q` |
| **Staged gate** | `UV_OFFLINE=1 ./scripts/verify-phase-3 --clean --evidence-root build/evidence/phase-03` |
| **Estimated runtime** | quick under 60 seconds; phase suite under 180 seconds; full staged qualification under 10 minutes |

---

## Sampling Rate

- **After every task commit:** Run the narrow automated command named by that task.
- **After every plan:** Run the complete Phase 3 module set and `git diff --check`.
- **After every wave:** Run all tests made available through that wave plus schema/native drift checks.
- **Before `$gsd-verify-work`:** Frozen full suite and source/Phase 1/Phase 2/Phase 3 verifiers must be green technically.
- **Max feedback latency:** 60 seconds for task-local tests; no more than two task commits between phase-module runs.

---

## Threat Register

| Ref | Threat | Required secure behavior |
|-----|--------|--------------------------|
| T03-01 | Root traversal, symlink/junction claim, mount or sensitive-path escape | Native descriptor-safe root confinement rejects before content and preserves canaries. |
| T03-02 | Agent invokes administration or query path mutates root/cache/index | MCP advertises exactly five read-only tools; query trees remain byte-identical. |
| T03-03 | Crash or failure publishes partial/corrupt generation | Only a closed, checked, hashed generation is atomically selected; prior pointer remains on failure. |
| T03-04 | Stale/replaced bytes leak through read, snippet, outline or context | Live digest/descriptor gate precedes all body output; conflicts return metadata/error with no body. |
| T03-05 | Malformed input, raw FTS syntax, oversized cursor/query or timeout causes resource abuse/partial output | Strict schemas and hard ceilings reject early; timeout returns no partial page. |
| T03-06 | Unregistered/old/failed PDF extraction or private cache content becomes searchable/packaged | Only complete accessible registered extraction is eligible; package/canary scans exclude all private instances. |
| T03-07 | JSON Schema, embedded native contract, patch, binary or source identity drifts | Independent validation and source/stage digest gates fail qualification. |

---

## Per-Task Verification Map

The planner may split a row into more tasks, but it must preserve every row and
its automated oracle. Final plan IDs are reconciled before execution.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | FILE-01, FILE-02 | T03-04, T03-05, T03-07 | Strict identity/generation/read/cursor contracts reject drift | schema/unit | `UV_OFFLINE=1 uv run --frozen pytest -q tests/schema/test_files_contracts.py tests/unit/test_file_models.py` | No - W0 | pending |
| 03-01-02 | 01 | 1 | FILE-06, FILE-07 | T03-03, T03-06 | Canonical generation/extraction manifests and receipts distinguish degraded/blocking | unit | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_file_generations.py` | No - W0 | pending |
| 03-02-01 | 02 | 2 | FILE-06, FILE-08 | T03-02, T03-03 | Parent-only sync builds a sibling generation and atomically promotes after validation | integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_admin.py` | No - W0 | pending |
| 03-02-02 | 02 | 2 | FILE-01, FILE-06 | T03-03, T03-04 | Create/modify/rename/delete/ignore/version matrix preserves identity and removes stale searchability | integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_file_generations.py` | No - W0 | pending |
| 03-03-01 | 03 | 3 | FILE-08, VER-03 | T03-01, T03-02, T03-07 | Installed files profile advertises only five tools and performs no query-side writes | native integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_mcp.py -k 'profile or read_only or tools'` | No - W0 | pending |
| 03-03-02 | 03 | 3 | FILE-01, FILE-02 | T03-01, T03-04, T03-05 | Live list/read is bounded, resumable and no-body on replacement conflict | native integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_mcp.py -k 'list or read or continuation'` | No - W0 | pending |
| 03-04-01 | 04 | 4 | FILE-03 | T03-04, T03-05 | Exact/FTS pagination is deterministic, CJK-capable and stale-body-free | integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_formats.py -k 'search or cjk or stale'` | No - W0 | pending |
| 03-04-02 | 04 | 4 | FILE-04, FILE-07 | T03-04, T03-06 | Deterministic outlines/context and registered extraction provenance match all formats | integration | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_formats.py -k 'outline or context or pdf'` | No - W0 | pending |
| 03-05-01 | 05 | 5 | VER-03 | T03-01 through T03-07 | Deterministic barrier races, malformed cases, sensitive paths and budgets fail closed | adversarial | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_security.py` | No - W0 | pending |
| 03-05-02 | 05 | 5 | FILE-01 through FILE-08, VER-03 | T03-01 through T03-07 | Exact staged package emits raw-evidence-bound requirement/D-01..D-16 verdict | staged E2E | `UV_OFFLINE=1 ./scripts/verify-phase-3 --clean --evidence-root build/evidence/phase-03` | No - W0 | pending |

---

## Wave 0 Requirements

- [ ] `tests/schema/test_files_contracts.py` - cross-language request/result/manifest instance and drift tests.
- [ ] `tests/unit/test_file_models.py` - identity, cursor, limit and freshness contracts.
- [ ] `tests/unit/test_file_generations.py` - canonical manifests, receipts, degradation and promotion validation.
- [ ] `tests/integration/test_files_admin.py` - parent-only administration and atomic publication fixtures.
- [ ] `tests/integration/test_file_generations.py` - create/modify/rename/delete/ignore/extractor-version matrix.
- [ ] `tests/integration/test_files_mcp.py` - direct native JSON-RPC five-tool and no-write fixtures.
- [ ] `tests/integration/test_files_formats.py` - CJK and research-format search/outline/context fixtures.
- [ ] `tests/integration/test_files_security.py` - deterministic barrier race and malformed/budget matrix.
- [ ] `tests/fixtures/files-first/` - multilingual, duplicate, stale-canary, sensitive and PDF registration corpus.
- [ ] `scripts/verify-phase-3` - owned-root staged qualification and raw evidence verdict.

Existing `pytest`, subprocess, schema registry, source materialization, staging,
offline execution, and evidence infrastructure require no new test framework.

---

## Manual-Only Verifications

None. Every Phase 3 behavior, including race schedules and no-write assertions,
must have deterministic automated evidence. An unschedulable race remains
unverified rather than being accepted manually.

---

## Full-Phase Sign-Off Gates

- [ ] FILE-01 through FILE-08 mapped requirements are true in the top verdict.
- [ ] VER-03 traversal/symlink/race/sensitive/malformed/budget matrix is true.
- [ ] D-01 through D-16 are independently true and raw-evidence-bound.
- [ ] Four ROADMAP success criteria pass from exact staged bytes.
- [ ] Projection deletion and rebuild reproduce normalized query results.
- [ ] MCP root, cache, pointer and database trees remain unchanged by every query tool.
- [ ] Stale and private canary scans report zero body leakage.
- [ ] Frozen full pytest suite passes offline.
- [ ] `scripts/verify-sources`, Phase 1, Phase 2 and Phase 3 technical gates pass.
- [ ] Release remains separately BLOCKED if SUP-04 evidence remains absent.

---

## Validation Sign-Off

- [ ] All tasks have an automated verify command or explicit Wave 0 dependency.
- [ ] Sampling continuity: no three consecutive tasks without automated verification.
- [ ] Wave 0 creates every currently missing test/verifier artifact.
- [ ] No watch-mode flags, implicit network access, or unretained manual checks.
- [ ] Task-local feedback latency remains below 60 seconds.
- [ ] `nyquist_compliant: true` and `wave_0_complete: true` set after plan reconciliation.

**Approval:** pending plan reconciliation
