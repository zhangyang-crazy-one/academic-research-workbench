---
phase: 07-installed-e2e-recovery-and-release-qualification
plan: 02
status: complete
requirements:
  - VER-04
commits:
  - a0d6007
  - caf40b9
  - 13d03d4
  - c6366b9
---

# Phase 7 Plan 02 Summary

## Outcome

VER-04 recovery qualification is implemented as a serial, deterministic fault
matrix.  Stable test-only IDs are guarded by `ARW_TEST_MODE=1`; normal runtime
requests and default processes cannot activate them.  The parent remains the
only canonical writer, and every matrix case uses an independent run root and
fresh subprocess where a process boundary is required.

The matrix proves canonical-before-host ordering through the existing
parent-owned orchestration lifecycle, distinguishes durable fsync outcomes from
pre-write failures, quarantines only a provable terminal torn tail, and keeps
middle-chain/hash/manifest/lock damage blocked.  Host/process/timeout and
repairable envelope outcomes are retryable at most once (two total attempts);
none is relabeled as cancellation.

## Completed Tasks

### 07-02-T1 — Deterministic boundary controls

- Added `src/arw/faults.py` with an explicit stable registry covering canonical
  write, hard/torn write, fsync/I/O/space, lock, host-dispatch, and result
  acceptance boundaries.
- Integrated guarded controls with journal read/write lock acquisition,
  canonical append, fsync, and process-level hard/torn fault seams.
- Added parent-owned `write_fault_sidecar` with bounded streams, relative
  snapshots, secret/path rejection, and a digest sidecar.
- Added fixture registry at
  `tests/fixtures/recovery/phase7_faults/registry.json`.

### 07-02-T2 — Serial fault/replay matrix

- Added `tests/integration/test_phase7_fault_matrix.py` covering hard
  termination, torn final write, middle/hash/manifest corruption, I/O and
  disk-exhaustion simulation, lock death, duplicate/stale delivery, timeout,
  and repairable/malformed result envelopes.
- Every case retains parent-side sidecar evidence with event-sequence and
  sidecar hashes.  Aggregate evidence is written to
  `build/evidence/phase-07/recovery-matrix.json` with technical `PASS` and
  separate legal release `BLOCKED_LEGAL_GATE`.
- The ordered aggregate includes all 18 stable registry boundary/scenario IDs,
  including direct lock, host-dispatch, and result-acceptance receipts.
- Parent sidecars retain bounded subprocess return codes/signals alongside
  their stream, snapshot, replay, and canonical hash bindings.

### 07-02-T3 — Crash/resume and stale rejection

- Fresh subprocesses resume from `run-manifest.json` plus canonical segments
  after pre-write and post-fsync failures; deleted projections do not affect
  replay.
- Duplicate event IDs, stale revisions, and stale worker completions produce
  rejected outcomes without mutating the ledger.  Replayed event-chain hashes
  are deterministic.

## Verification

Focused recovery and matrix command:

```text
UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=$PWD/build/tmp/phase-07/faults \
  .venv/bin/python -m pytest -q \
  tests/integration/test_phase7_fault_matrix.py \
  tests/integration/test_recovery_crash.py
```

Result: **8 passed**.

Plan-level recovery regression:

```text
UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=$PWD/build/tmp/phase-07/faults \
  .venv/bin/python -m pytest -q \
  tests/integration/test_recovery.py \
  tests/integration/test_recovery_crash.py \
  tests/integration/test_phase7_fault_matrix.py \
  tests/unit/test_scheduler.py tests/unit/test_reducer.py
```

Result: **37 passed**.

## Deviations from Plan

**[Rule 1 - Safety] Existing Phase 4 scheduler/orchestration edits were not
staged into this plan's commits** — Found during: T1 close-out | The shared
worktree already contained substantial uncommitted Phase 4 changes in
`src/arw/scheduler.py` and `src/arw/orchestration.py` | Kept the guarded host
and result-boundary lines visible in the shared worktree for the parent Phase 7
close-out, while committing only independent fault controls, journal/evidence
helpers, fixtures, and matrix tests | Verification: 37 focused tests passed;
parent must selectively stage these lines with its existing orchestration
changes.

**Total deviations:** 1 safety-preserving staging deviation. **Impact:** no
existing user work was overwritten or reset; all technical recovery evidence
is retained.

## Self-Check: PASSED

- All task acceptance criteria and plan-level verification commands passed.
- Sidecar hashes match their canonical JSON bytes and sidecars contain no
  absolute paths or secret-like fields.
- No tests were deleted or xfailed.
- Legal release remains blocked independently of the technical matrix verdict.
