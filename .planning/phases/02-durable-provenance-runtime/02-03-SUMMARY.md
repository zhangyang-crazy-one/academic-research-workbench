---
phase: 02-durable-provenance-runtime
plan: 03
subsystem: immutable-passport-runtime
tags: [content-addressing, material-passport, checkpoint, resume, freshness, json-schema]

requires:
  - phase: 02-durable-provenance-runtime
    provides: Segmented sole-writer transactions, attempts, decisions, reducer, and status from Plans 01-02
provides:
  - Immutable content-addressed artifact manifests selected only by accepting events
  - Coherent Material Passport checkpoints with rebuildable non-authoritative pointer
  - Dynamic freshness and exact linear single-use resume
affects: [02-04-recovery, 02-05-runtime-verifier, phase-04-orchestration, phase-06-audit]

tech-stack:
  added: []
  patterns:
    - Immutable files are installed and fsynced before one accepting event selects them
    - Passport pointer loss or corruption never changes replay authority
    - Resume consumes only the current Passport under the sole-writer lock

key-files:
  created:
    - src/arw/manifests.py
    - schemas/v1/material-passport.schema.json
    - schemas/v1/passport-pointer.schema.json
    - schemas/v1/checkpoint-request.schema.json
    - schemas/v1/resume-request.schema.json
    - tests/integration/test_passport_lifecycle.py
  modified:
    - src/arw/models.py
    - src/arw/runtime.py
    - src/arw/reducer.py
    - src/arw/cli.py

key-decisions:
  - "Installed artifact or Passport files are non-authoritative until a hash-binding event accepts them."
  - "Passport lineage is exact and linear: based-on revision, parent, and superseded hash must match the pre-event reducer state."
  - "Freshness is evaluated from an injected clock and blocks lifecycle/resume without changing historical Passport bytes."

patterns-established:
  - "Content-addressed stores reject traversal, symlink components, non-regular content, digest mismatch, and unequal collisions."
  - "The current Passport is replay-derived; passport.json is replaced atomically only as a rebuildable convenience projection."

requirements-completed: [RUN-05, RUN-06, RUN-07]

duration: 14 min
completed: 2026-07-13
---

# Phase 2 Plan 3: Immutable Artifacts and Material Passport Summary

**Accepted artifacts and resumable checkpoints now live in immutable digest stores, with event-selected Passport lineage, dynamic freshness, and exact single-use resume.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-13T12:58:31Z
- **Completed:** 2026-07-13T13:12:32Z
- **Tasks:** 3
- **Files modified:** 19

## Accomplishments

- Added canonical artifact manifests with exact content/path/hash validation, exclusive content-addressed publication, and event-only acceptance authority.
- Added coherent explicit, stage-handoff, human-decision, and recovery Passport boundaries containing artifact, decision, attempt, stage, revision, head, lineage, and freshness snapshots.
- Added replay-derived current Passport state, atomic but non-authoritative pointer replacement/rebuild, and a SIGKILL proof between event fsync and pointer write.
- Added stale, superseded, consumed, expired, and branching rejection proofs that preserve the complete canonical tree.

## Task Commits

1. **Task 1: Specify immutable artifact, Passport, freshness, and resume behavior as RED tests** - `62c85c3` (test)
2. **Task 2: Implement content-addressed artifact acceptance** - `a4cebbe` (feat)
3. **Task 3: Implement Passport checkpoint, pointer, freshness, and exact resume** - `04d898a` (feat)

## Files Created/Modified

- `src/arw/manifests.py` - Safe content validation, immutable manifest/Passport installation, accepted-event validation, and pointer replacement.
- `src/arw/runtime.py` - Artifact acceptance, coherent checkpoint, exact resume, freshness enforcement, and explicit pointer rebuild commands.
- `src/arw/reducer.py` - Linear Passport acceptance/consumption and injected-clock blocker projection.
- `src/arw/models.py` - Strict artifact, Passport, pointer, checkpoint, resume, and event contracts.
- `schemas/v1/*.schema.json` - Independently validated artifact and Passport request/storage contracts included in staged identity.
- `tests/integration/test_passport_lifecycle.py` - Orphan, rejection, snapshot, lineage, pointer, expiry, resume, and SIGKILL proofs.

## Decisions Made

- Store presence is not acceptance; only immutable hashes named by accepted events affect canonical state.
- A Passport must bind the exact pre-event revision/head and current lineage, preventing implicit branches during replay or resume.
- Status never reads or repairs `passport.json`; pointer repair is an explicit locked command derived from accepted events.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Compatibility] Preserved required null payload fields without changing Phase 1 event bytes**
- **Found during:** Task 3 canonical Passport replay
- **Issue:** Recursive `exclude_none` removed required nullable payload fields, while dumping all nulls would alter frozen Phase 1 top-level event bytes.
- **Fix:** Added one event wire mapping that preserves payload nulls and omits only the legacy absent top-level actor role.
- **Verification:** Passport lifecycle and Phase 1 journal regression tests pass together.
- **Committed in:** `04d898a`

**2. [Rule 1 - Security] Hardened manifest store creation and Passport replay invariants**
- **Found during:** Task 3 threat-model review
- **Issue:** Store directory components and replayed Passport lineage needed explicit symlink/exact-revision/first-supersession defenses.
- **Fix:** Rejected unsafe store components and required exact revision, parent, supersession, and unique Passport identity during reduction.
- **Verification:** Reducer adversarial tests and complete canonical-tree rejection checks pass.
- **Committed in:** `04d898a`

**3. [Rule 3 - Blocking] Extended staged schema identity from 14 to 18 files**
- **Found during:** Task 3 package closure
- **Issue:** New Passport and request schemas were outside the exact packaged schema inventory.
- **Fix:** Registered and explicitly staged all four schemas and updated build identity bounds/version assertions.
- **Verification:** Installed version and offline staged CLI tests report 3 passed.
- **Committed in:** `04d898a`

---

**Total deviations:** 3 auto-fixed (2 correctness/security, 1 package closure).
**Impact on plan:** All fixes enforce the planned immutable and exact-resume semantics without expanding canonical authority.

## Issues Encountered

- A final test patch temporarily placed pointer-corruption assertions in the wrong test; it was corrected before verification and no production behavior was affected.

## User Setup Required

None - no external configuration is required.

## Verification

- Plan acceptance matrix: `41 passed`.
- Focused Passport/reducer/schema matrix after invariant tightening: `22 passed`.
- Installed version and offline staged CLI: `3 passed`.
- Python compilation and whitespace validation completed successfully.

## Next Phase Readiness

- Ready for Plan 02-04 to distinguish recoverable terminal tail damage from blocking interior corruption and record explicit quarantine recovery.
- Recovery checkpoints already have a reserved event boundary but cannot be created until the recovery command is implemented.

## Self-Check: PASSED

- All declared immutable stores, schemas, event links, request routes, lifecycle tests, and three task commits exist.
- Pointer deletion/corruption, event-before-pointer SIGKILL, expired evidence, and exact single-use resume are executable and green.

---
*Phase: 02-durable-provenance-runtime*
*Completed: 2026-07-13*
