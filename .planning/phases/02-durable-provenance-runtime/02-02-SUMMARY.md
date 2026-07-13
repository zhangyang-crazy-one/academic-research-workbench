---
phase: 02-durable-provenance-runtime
plan: 02
subsystem: segmented-journal-runtime
tags: [event-sourcing, fsync, segments, transactions, pydantic, json-schema]

requires:
  - phase: 02-durable-provenance-runtime
    provides: Registered workflow, actor authority, pure reducer, rejection, and status contracts from Plan 01
provides:
  - Legacy-compatible strict numeric segment scanner with per-segment digest and accepted offsets
  - Locked replay-validate-pre-reduce-append sole-writer transaction
  - Replayable lifecycle, human-decision, and attempt command surfaces
affects: [02-03-passports, 02-04-recovery, 02-05-runtime-verifier, phase-04-orchestration]

tech-stack:
  added: []
  patterns:
    - New runs explicitly declare segmented-v1 while legacy events.jsonl remains immutable and read-only to Phase 2 commands
    - Candidate events are semantically reduced before fsynced append
    - Caller requests never contain sequence, resulting revision, previous hash, or event hash

key-files:
  created:
    - src/arw/runtime.py
    - schemas/v1/transition-request.schema.json
    - schemas/v1/attempt-request.schema.json
    - tests/integration/test_segmented_journal.py
    - tests/integration/test_runtime_transitions.py
    - tests/integration/test_runtime_attempts.py
  modified:
    - src/arw/journal.py
    - src/arw/models.py
    - src/arw/cli.py
    - schemas/v1/run-manifest.schema.json

key-decisions:
  - "A segmented-v1 manifest must bind a registered workflow ID and digest; undeclared legacy and segmented paths cannot coexist."
  - "The command service rejects legacy journals before append and is the sole route for lifecycle, decision, and attempt events."
  - "A candidate event must pass the same pure reducer used by replay/status before its bytes are appended."

patterns-established:
  - "Segment discovery admits only contiguous eight-digit JSONL names and rejects gaps, symlinks, directories, and extra files."
  - "Every safe rejection contains accepted state and leaves the complete canonical tree byte-identical."

requirements-completed: [RUN-03, RUN-04, RUN-06, RUN-07]

duration: 9 min
completed: 2026-07-13
---

# Phase 2 Plan 2: Segmented Journal and Runtime Transactions Summary

**New runs now use strictly discovered hash-chained segments, and one locked Python transaction accepts lifecycle, decision, or attempt events only after replay, authorization, and candidate reduction.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-13T12:46:19Z
- **Completed:** 2026-07-13T12:55:29Z
- **Tasks:** 3
- **Files modified:** 15

## Accomplishments

- Added `segmented-v1` run identity and durable initialization at `journal/segments/00000001.jsonl` while preserving byte-exact Phase 1 `events.jsonl` replay.
- Added strict segment discovery, global sequence/revision/hash continuity, and per-segment path, byte count, digest, accepted offset, and event records.
- Added a sole-writer command service for registered transitions, decision request/resolution, and attempt start/close with replayable state after fresh process restart.
- Added structured duplicate, stale, illegal, and unauthorized rejection matrices proving no canonical byte changes.

## Task Commits

1. **Task 1: Define segmented replay and transaction rejection fixtures** - `03f7e26` (test)
2. **Task 2: Refactor journal into structured legacy-compatible segment scan and append** - `fa3313a` (feat)
3. **Task 3: Implement the sole-writer transition, decision, and attempt transaction** - `b8ecc04` (feat)

## Files Created/Modified

- `src/arw/journal.py` - Declared layout initialization, strict segment discovery/scan, lock context, and fsynced append primitive.
- `src/arw/runtime.py` - Replay-authorize-prevalidate-reduce-append transaction and strict accepted/rejected outcomes.
- `src/arw/models.py` - Segmented identity and caller-owned lifecycle/decision/attempt request contracts.
- `src/arw/cli.py` - Thin transition, decision, and attempt routes to the runtime service.
- `schemas/v1/transition-request.schema.json`, `schemas/v1/attempt-request.schema.json` - Independently checked request boundaries.

## Decisions Made

- Existing Phase 1 runs are replayable but cannot receive Phase 2 mutations; migration must be explicit rather than silently changing journal semantics.
- Attempt consumed hashes must already be represented by the current ledger head, an accepted artifact manifest, or an accepted Passport.
- Duplicate event and command identities are checked before expected revision so retries receive their exact identity error without appending.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Security] Added pre-append candidate reduction**
- **Found during:** Task 3 transaction design
- **Issue:** Re-reducing only after fsync could discover semantic invalidity after canonical bytes had changed.
- **Fix:** Build the writer-owned candidate, reduce the complete candidate stream, append only on success, then compare post-append reduction.
- **Verification:** Runtime rejection and replay suite reported 23 passed.
- **Committed in:** `b8ecc04`

**2. [Rule 1 - Compatibility] Made legacy journals read-only to Phase 2 commands**
- **Found during:** Task 3 compatibility review
- **Issue:** Appending a Phase 2 event to `events.jsonl` would cause the legacy scanner to reject only after the write.
- **Fix:** Replay carries declared layout; service and append primitive both reject non-segmented mutation before writing, with a byte snapshot test.
- **Verification:** Legacy transaction rejection leaves the tree unchanged and all Phase 1 crash tests pass.
- **Committed in:** `b8ecc04`

**3. [Rule 3 - Blocking] Extended exact packaged schema identity from 10 to 12**
- **Found during:** Task 3 schema staging
- **Issue:** New request contracts were outside the exact stage/build identity allowlist.
- **Fix:** Registered and explicitly staged both schemas while keeping old 8-10-schema identities valid.
- **Verification:** Installed version and offline staged CLI tests reported 3 passed.
- **Committed in:** `b8ecc04`

---

**Total deviations:** 3 auto-fixed (2 correctness/security, 1 blocking package closure).
**Impact on plan:** The fixes close partial-write and compatibility hazards without broadening the runtime's authority.

## Issues Encountered

- The initial RED attempt test imported another test module, but `tests/` is intentionally not a package. Helpers were localized so all 17 RED cases collected before implementation.

## User Setup Required

None - no external configuration is required.

## Verification

- Runtime, attempts, segments, crash replay, and status: `23 passed`.
- Schemas, Phase 1 init, reducer, and status units: `13 passed`.
- Installed version and offline staged CLI: `3 passed`.
- Python compilation and whitespace validation completed successfully.

## Next Phase Readiness

- Ready for Plan 02-03 to install immutable artifact manifests and Material Passports, then accept them through this transaction boundary.
- Physical tail classification and recovery segment authorization remain assigned to Plan 02-04.

## Self-Check: PASSED

- All declared source, schema, tests, and three task commits exist.
- Segmented and legacy replay, no-write rejection, CLI routing, and exact-stage schema identity are executable and green.

---
*Phase: 02-durable-provenance-runtime*
*Completed: 2026-07-13*
