---
phase: 04-subagent-orchestration-hooks-and-human-gates
plan: 02
subsystem: orchestration
tags: [canonical-events, parent-authority, reducer, deterministic-ordering, manifests, symlink-safety, json-schema]

# Dependency graph
requires:
  - phase: 04-subagent-orchestration-hooks-and-human-gates
    provides: Strict immutable Phase 4 role, assignment, attempt, proposal, review, hook, gate, and human-decision contracts from Plan 04-01.
provides:
  - Parent-only canonical Phase 4 event vocabulary and frozen workflow authority.
  - Pure deterministic Phase 4 reducer/status projection with replayable ordering, retry, gate, and decision history.
  - Immutable, symlink-safe assignment/attempt manifests and bounded raw proposal admission.
affects: [phase-04-later-orchestration-plans, runtime-recovery, staged-plugin-packaging]

# Tech tracking
tech-stack:
  added: []
  patterns: [parent-only canonical writer, frozen acceptance-key reduction, descriptor-safe write-once evidence, schema-compatible legacy projections]

key-files:
  created: [.planning/phases/04-subagent-orchestration-hooks-and-human-gates/deferred-items.md]
  modified: [src/arw/models.py, src/arw/workflows.py, src/arw/reducer.py, src/arw/status.py, src/arw/manifests.py, schemas/v1/event.schema.json, schemas/v1/status.schema.json, schemas/v1/command-outcome.schema.json]

key-decisions:
  - "Every Phase 4 canonical event requires actor_role=parent_control_plane; worker, hook, reviewer, and operator provenance remains payload evidence only."
  - "Proposal projection advances by immutable (layer, task ordinal, assignment ID) keys and excludes superseded assignments from the active cursor."
  - "Raw proposal bytes are retained content-addressed evidence before strict validation and never become canonical state without a parent event."
  - "Legacy Phase 2 active-attempt snapshots stay narrow while Phase 4 lifecycle detail remains in the dedicated replay state history."

patterns-established:
  - "Phase4Payload carries source identity/evidence separately from canonical writer identity."
  - "Write-once manifests use canonical bytes, no-follow file opens, hard-link publication, and replacement/collision rejection."
  - "Status is a direct projection of RuntimeState and never reads evidence directories or derives decisions from wall-clock time."

requirements-completed: [PKG-05, AGT-01, AGT-02, AGT-03, AGT-05, SCI-02, SCI-03]

# Metrics
duration: 31m
completed: 2026-07-14
---

# Phase 04 Plan 02: Parent-only Phase 4 authority and immutable evidence

**Parent-authored Phase 4 events now reduce deterministically from the journal while assignment and raw proposal evidence remain immutable, bounded, and symlink-safe.**

## Performance

- **Duration:** 31 minutes
- **Started:** 2026-07-14T14:28:34Z
- **Completed:** 2026-07-14T14:59:31Z
- **Tasks:** 3/3
- **Files modified:** 14 including implementation, tests, schema compatibility, and deferred tracking

## Accomplishments

- Added strict Phase 4 event payloads, parent-only actor enforcement, frozen workflow stages/transitions, and parent transition authorization.
- Added deterministic reducer/status state for execution mode, assignment revisions, attempts, proposals, review evidence, hooks, gates, human decisions, blockers, and frozen commit cursors.
- Added immutable assignment/attempt manifest publication and bounded direct-file raw proposal intake with canonical validation and retained evidence.
- Extended canonical event/status/command-outcome schemas and preserved the existing Phase 2 passport snapshot shape.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add parent-only canonical Phase 4 event and workflow authority** - `1ace4a0` (test), `e702f52` (feat)
2. **Task 2: Reduce Phase 4 lifecycle state deterministically from journal events** - `886bf77` (test), `fc7b980` (feat)
3. **Task 3: Make assignment and raw-proposal evidence immutable and symlink-safe** - `917bb04` (test), `1b423a2` (feat)

Additional correctness fix: `5f27e90` (fix: schema projections, legacy attempt compatibility, frozen-order and safe-ID invariants).

**Plan metadata:** included in the final docs commit for this plan.

## Files Created/Modified

- `src/arw/models.py` - Phase 4 canonical payload union and parent-only event validation.
- `src/arw/workflows.py` - Frozen Phase 4 workflow definition and transition authority.
- `src/arw/reducer.py` - Pure deterministic Phase 4 state reduction and backward-compatible active-attempt projection.
- `src/arw/status.py` - Read-only Phase 4 status projection.
- `src/arw/manifests.py` - Immutable assignment/attempt trees and bounded raw proposal evidence intake.
- `schemas/v1/event.schema.json` - Phase 4 event types and parent actor contract.
- `schemas/v1/status.schema.json`, `schemas/v1/command-outcome.schema.json` - Phase 4 state fields in both status contracts.
- `tests/unit/test_orchestration_models.py`, `tests/unit/test_workflows.py`, `tests/unit/test_reducer.py`, `tests/unit/test_manifests.py`, `tests/integration/test_journal_replay.py` - Focused authority, replay, ordering, intake, and schema coverage.

## Decisions Made

- Canonical mutation remains exclusively parent-controlled; source actor/host/evidence fields cannot grant writer authority.
- Superseded assignments are removed from the active frozen cursor, and later proposals cannot bypass a missing earlier active assignment.
- Phase 4 detail is retained in replay-native history rather than widening legacy Passport snapshot models.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical contract] Extended checked-in status schemas**

- **Found during:** overall runtime/schema verification.
- **Issue:** `StatusReport` gained Phase 4 fields, but `status.schema.json` and the nested runtime state in `command-outcome.schema.json` rejected them as additional properties.
- **Fix:** Added the Phase 4 status fields and required-field contracts to both schemas.
- **Files modified:** `schemas/v1/status.schema.json`, `schemas/v1/command-outcome.schema.json`
- **Verification:** Runtime status and schema cross-language/drift/Phase 4 tests pass.
- **Committed in:** `5f27e90`

**2. [Rule 1 - Regression] Preserved legacy active-attempt snapshots**

- **Found during:** full repository regression run.
- **Issue:** Extending `AttemptState` caused existing Passport snapshot conversion to receive Phase 4-only fields.
- **Fix:** Kept Phase 4 active-attempt detail in an internal reducer model and projected the original narrow `AttemptState` shape for legacy snapshots.
- **Files modified:** `src/arw/reducer.py`
- **Verification:** Passport lifecycle, runtime attempts/transitions, reducer, and the complete focused matrix pass.
- **Committed in:** `5f27e90`

**3. [Rule 2 - Missing critical boundary] Completed event-schema and intake hardening**

- **Found during:** schema and adversarial intake review.
- **Issue:** The checked-in canonical event schema did not enumerate Phase 4 events, and assignment lookup accepted unvalidated path-like IDs before path construction.
- **Fix:** Added Phase 4 event schema branches/parent actor conditions, validated the event fixture against that schema, and validated assignment IDs with the stable runtime identifier contract before filesystem lookup. Frozen proposal ordering also now ignores superseded assignments and buffers every later outcome behind a missing active key.
- **Files modified:** `schemas/v1/event.schema.json`, `src/arw/manifests.py`, `src/arw/reducer.py`, focused tests.
- **Verification:** Focused Phase 4 and schema suites pass.
- **Committed in:** `5f27e90`

---

**Total deviations:** 3 auto-fixed (1 Rule 1, 2 Rule 2).
**Impact on plan:** All fixes were required for compatibility, schema integrity, deterministic ordering, or trust-boundary correctness; no Plan 03-owned production module was changed.

## Verification

- Focused Phase 4, runtime, recovery, and schema matrix: **106 passed**.
- Task 1 verify: **10 passed**.
- Task 2 verify: **14 passed**.
- Task 3 verify: **14 passed**.
- Recovery regressions (`recovery_scan`, `recovery`, `recovery_crash`, `segmented_journal`): **29 passed**.
- Full repository run: **196 passed, 18 xfailed, 13 failed**. One direct legacy projection regression was fixed; the remaining 12 failures share the out-of-scope staged-plugin allowlist error recorded in `deferred-items.md`.
- Ruff was unavailable in the offline environment (`Failed to spawn: ruff`); no package installation was attempted.

## Known Stubs

None introduced by Plan 04-02. Existing strict xfails remain mapped to later Phase 04 plans (P04-03 through P04-07) and were not altered.

## Issues Encountered

- Full staged/installed-plugin tests currently reject the eight existing Phase 4 schema files as unexpected stage outputs; this is logged for the owning packaging/inventory work and was not changed here.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The canonical parent-only event/reducer/evidence boundary is ready for later scheduler, panel, hook, and human-gate adapters. The staged-plugin allowlist issue must be resolved by its owning packaging work before the full installed qualification suite can be green.

---
*Phase: 04-subagent-orchestration-hooks-and-human-gates*
*Completed: 2026-07-14*

## Self-Check: PASSED

- Summary and deferred-items files exist.
- All seven implementation/test commits are present in the repository history.
- The final focused verification matrix completed with 106 passing tests.
