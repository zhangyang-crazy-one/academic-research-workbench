---
phase: 2
slug: durable-provenance-runtime
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
---

# Phase 2 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 with subprocess crash fixtures |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run --frozen pytest -q <targeted-test-files>` |
| **Full suite command** | `UV_OFFLINE=1 uv run --frozen pytest -q` |
| **Estimated runtime** | Target: quick <30 seconds; full <180 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's targeted `uv run --frozen pytest -q` command.
- **After every plan wave:** Run all Phase 2 unit, schema, integration, and recovery tests.
- **Before `$gsd-verify-work`:** `UV_OFFLINE=1 uv run --frozen pytest -q` must be green.
- **Max feedback latency:** 30 seconds for ordinary tasks; 180 seconds for crash/evidence waves.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | RUN-03, RUN-04, RUN-07 | T-02-01 | Pure reducer and authority table reject illegal transitions without I/O | unit/schema | `uv run --frozen pytest -q tests/unit/test_workflows.py tests/unit/test_reducer.py tests/schema` | No - Wave 0 | pending |
| 02-01-02 | 01 | 1 | RUN-03, RUN-07 | T-02-02 | JSON/text status share one strict reducer model | unit/integration | `uv run --frozen pytest -q tests/unit/test_status.py tests/integration/test_runtime_status.py` | No - Wave 0 | pending |
| 02-02-01 | 02 | 2 | RUN-03, RUN-04 | T-02-03 | Segmented replay preserves sequence/hash/revision and legacy replay | integration | `uv run --frozen pytest -q tests/integration/test_segmented_journal.py tests/integration/test_run_init.py` | No - Wave 0 | pending |
| 02-02-02 | 02 | 2 | RUN-03 | T-02-04 | Invalid, duplicate, stale, out-of-order, and unauthorized commands leave canonical bytes unchanged | integration | `uv run --frozen pytest -q tests/integration/test_runtime_transitions.py` | No - Wave 0 | pending |
| 02-03-01 | 03 | 3 | RUN-05 | T-02-05 | Artifact and Passport manifests are immutable, digest-addressed, and accepted only by events | unit/integration | `uv run --frozen pytest -q tests/unit/test_manifests.py tests/integration/test_passport_lifecycle.py` | No - Wave 0 | pending |
| 02-03-02 | 03 | 3 | RUN-06 | T-02-06 | Exact current Passport resumes once; stale/double resume fails closed | integration | `uv run --frozen pytest -q tests/integration/test_passport_lifecycle.py tests/integration/test_runtime_attempts.py` | No - Wave 0 | pending |
| 02-04-01 | 04 | 4 | RUN-08 | T-02-07 | Only final invalid tail is recoverable; middle/manifest/hash-chain damage blocks | unit/integration | `uv run --frozen pytest -q tests/unit/test_recovery_scan.py tests/integration/test_recovery.py` | No - Wave 0 | pending |
| 02-04-02 | 04 | 4 | RUN-06, RUN-08 | T-02-08 | Recovery preserves exact bytes/hash/offset and starts a bound next segment once | crash/evidence | `uv run --frozen pytest -q tests/integration/test_recovery_crash.py tests/integration/test_journal_replay.py` | No - Wave 0 | pending |
| 02-05-01 | 05 | 5 | RUN-03-RUN-08 | T-02-09 | Fresh-process replay/status and all repository regressions pass from canonical files only | full regression | `UV_OFFLINE=1 uv run --frozen pytest -q` | Existing harness; Phase 2 verifier pending | pending |

*Status values: pending, green, red, flaky.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_workflows.py` - registered definition identity, authority, and legal transition fixtures.
- [ ] `tests/unit/test_reducer.py` - pure normal/illegal/decision/attempt/freshness reductions.
- [ ] `tests/unit/test_status.py` - strict status model and text/JSON parity.
- [ ] `tests/unit/test_manifests.py` - artifact and Passport digest-addressed storage.
- [ ] `tests/unit/test_recovery_scan.py` - byte-offset tail classification.
- [ ] `tests/integration/test_runtime_transitions.py` - RUN-03 mutation invariants.
- [ ] `tests/integration/test_runtime_status.py` - RUN-04/RUN-07 replay and status states.
- [ ] `tests/integration/test_segmented_journal.py` - segmented and legacy replay.
- [ ] `tests/integration/test_passport_lifecycle.py` - RUN-05/RUN-06 checkpoint/resume.
- [ ] `tests/integration/test_runtime_attempts.py` - active attempt reconstruction and stale proposal rejection.
- [ ] `tests/integration/test_recovery.py` - quarantine, recovery binding, and blocked corruption.
- [ ] `tests/integration/test_recovery_crash.py` - recovery failpoints and idempotency evidence.
- [ ] `scripts/verify-phase-2` - one deterministic Phase 2 evidence/verdict entrypoint.

Existing pytest, subprocess, JSON Schema, `tmp_path`, canonical byte, and evidence helpers cover the infrastructure; no new test framework is required.

---

## Manual-Only Verifications

All Phase 2 runtime behaviors must have automated verification. Manual review is limited to inspecting the generated evidence bundle for readability and does not replace any pass/fail assertion.

---

## Validation Sign-Off

- [x] All planned capabilities have a targeted automated command or Wave 0 dependency.
- [x] Sampling continuity: no three consecutive tasks lack automated verification.
- [x] Wave 0 names every missing test/evidence surface.
- [x] No watch-mode flags are used.
- [x] Feedback targets are below 30 seconds quick and 180 seconds full.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** approved for planning 2026-07-13; task IDs may be synchronized after plan-checker convergence.
