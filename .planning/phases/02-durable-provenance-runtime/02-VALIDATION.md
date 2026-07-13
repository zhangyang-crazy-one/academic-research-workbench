---
phase: 2
slug: durable-provenance-runtime
status: complete
nyquist_compliant: true
wave_0_complete: true
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
| 02-01-01 | 01 | 1 | RUN-03, RUN-04, RUN-07 | T-02-01 to T-02-03 | Pure reducer and authority table reject illegal transitions without I/O | unit/schema | `uv run --frozen pytest -q tests/unit/test_workflows.py tests/unit/test_reducer.py tests/schema` | Yes | green |
| 02-01-02 | 01 | 1 | RUN-03, RUN-07 | T-02-04 | JSON/text status share one strict reducer model | unit/integration | `uv run --frozen pytest -q tests/unit/test_status.py tests/integration/test_runtime_status.py` | Yes | green |
| 02-02-01 | 02 | 2 | RUN-03, RUN-04 | T-02-05 | Segmented replay preserves sequence/hash/revision and legacy replay | integration | `uv run --frozen pytest -q tests/integration/test_segmented_journal.py tests/integration/test_run_init.py` | Yes | green |
| 02-02-02 | 02 | 2 | RUN-03 | T-02-06 to T-02-08 | Invalid, duplicate, stale, out-of-order, and unauthorized commands leave canonical bytes unchanged | integration | `uv run --frozen pytest -q tests/integration/test_runtime_transitions.py` | Yes | green |
| 02-03-01 | 03 | 3 | RUN-05 | T-02-09, T-02-10 | Artifact and Passport manifests are immutable, digest-addressed, and accepted only by events | unit/integration | `uv run --frozen pytest -q tests/unit/test_manifests.py tests/integration/test_passport_lifecycle.py` | Yes | green |
| 02-03-02 | 03 | 3 | RUN-06 | T-02-11, T-02-12 | Exact current Passport resumes once; stale/double resume fails closed | integration | `uv run --frozen pytest -q tests/integration/test_passport_lifecycle.py tests/integration/test_runtime_attempts.py` | Yes | green |
| 02-04-01 | 04 | 4 | RUN-08 | T-02-13 | Only final invalid tail is recoverable; middle/manifest/hash-chain damage blocks | unit/integration | `uv run --frozen pytest -q tests/unit/test_recovery_scan.py tests/integration/test_recovery.py` | Yes | green |
| 02-04-02 | 04 | 4 | RUN-06, RUN-08 | T-02-14 to T-02-16 | Recovery preserves exact bytes/hash/offset and starts a bound next segment once | crash/evidence | `uv run --frozen pytest -q tests/integration/test_recovery_crash.py tests/integration/test_journal_replay.py` | Yes | green |
| 02-05-01 | 05 | 5 | RUN-03-RUN-08 | T-02-17 to T-02-20 | Fresh-process replay/status and all repository regressions pass from canonical files only | full regression | `UV_OFFLINE=1 uv run --frozen pytest -q` | Yes; staged verifier included | green |

*Status values: pending, green, red, flaky.*

---

## Wave 0 Requirements

- [x] `tests/unit/test_workflows.py` - registered definition identity, authority, and legal transition fixtures.
- [x] `tests/unit/test_reducer.py` - pure normal/illegal/decision/attempt/freshness reductions.
- [x] `tests/unit/test_status.py` - strict status model and text/JSON parity.
- [x] `tests/unit/test_manifests.py` - artifact and Passport digest-addressed storage.
- [x] `tests/unit/test_recovery_scan.py` - byte-offset tail classification.
- [x] `tests/integration/test_runtime_transitions.py` - RUN-03 mutation invariants.
- [x] `tests/integration/test_runtime_status.py` - RUN-04/RUN-07 replay and status states.
- [x] `tests/integration/test_segmented_journal.py` - segmented and legacy replay.
- [x] `tests/integration/test_passport_lifecycle.py` - RUN-05/RUN-06 checkpoint/resume.
- [x] `tests/integration/test_runtime_attempts.py` - active attempt reconstruction and stale proposal rejection.
- [x] `tests/integration/test_recovery.py` - quarantine, recovery binding, and blocked corruption.
- [x] `tests/integration/test_recovery_crash.py` - recovery failpoints and idempotency evidence.
- [x] `scripts/verify-phase-2` - one deterministic Phase 2 evidence/verdict entrypoint.

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

## Final Evidence

- Full frozen offline suite: `138 passed in 160.58s`.
- `scripts/verify-sources`: `source verification PASS`.
- `scripts/verify-phase-1`: technical `PASS`, release `BLOCKED`, identity `c4ed683d4460697c1ce462501335d9d0b34cda8d74bb51347ad79f711ebaa719`.
- `scripts/verify-phase-2`: technical `PASS`, release `BLOCKED`, 149 raw evidence files; RUN-03 through RUN-08 and D-01 through D-15 are true.
- License/pre-vendor/inventory matrix: `6 passed`; SBOM digest reproduced as `43d09853d9a4cfd5b7f541033e2ec1f4ae0a736c4d7dbc9acabed5f67f22af6e`.

**Approval:** validated 2026-07-13. All automated rows are green; no manual-only behavior or open Phase 2 threat remains.
