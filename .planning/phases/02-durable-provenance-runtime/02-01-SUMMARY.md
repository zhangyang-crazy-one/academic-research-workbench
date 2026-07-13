---
phase: 02-durable-provenance-runtime
plan: 01
subsystem: runtime-state-contracts
tags: [event-sourcing, json-schema, reducer, workflow-registry, status, provenance]

requires:
  - phase: 01-contract-license-and-executable-baseline
    provides: Canonical sole-writer journal, immutable run manifest, checked schemas, and installed build identity
provides:
  - Hash-bound domain-neutral workflow registry and closed actor/category authority matrix
  - Strict typed Phase 2 event payloads and filesystem-free deterministic runtime reducer
  - Shared versioned JSON/text status projection with read-only CLI behavior
affects: [02-02-segmented-journal, 02-03-passports, 02-04-recovery, phase-04-orchestration]

tech-stack:
  added: []
  patterns:
    - Immutable workflow definitions identified by canonical SHA-256
    - Pure event fold is the sole source for JSON and text status
    - Legacy manifests omit paired workflow identity fields without changing accepted bytes

key-files:
  created:
    - src/arw/workflows.py
    - src/arw/reducer.py
    - src/arw/status.py
    - schemas/v1/rejection.schema.json
    - schemas/v1/status.schema.json
  modified:
    - src/arw/models.py
    - src/arw/journal.py
    - src/arw/cli.py
    - schemas/v1/event.schema.json
    - schemas/v1/run-manifest.schema.json

key-decisions:
  - "New manifests bind a registered workflow ID and digest as an inseparable pair; legacy Phase 1 bytes map to one frozen compatibility identity."
  - "Only parent control-plane and explicit operator categories can commit canonical events; workers and hooks remain proposal-only."
  - "Status opens only an existing lock and reduces canonical events without creating roots, locks, projections, or refreshed artifacts."

patterns-established:
  - "Every new event discriminator has a strict matching payload in both Pydantic and Draft 2020-12 JSON Schema."
  - "Rejected JSON status paths emit a strict Rejection and leave the filesystem byte-identical."

requirements-completed: [RUN-03, RUN-04, RUN-07]

duration: 12 min
completed: 2026-07-13
---

# Phase 2 Plan 1: Workflow, Reducer, and Status Contracts Summary

**A hash-bound domain-neutral lifecycle, closed event authority model, pure runtime reducer, and one read-only JSON/text status contract now define Phase 2 state semantics.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-13T12:30:09Z
- **Completed:** 2026-07-13T12:41:57Z
- **Tasks:** 3
- **Files modified:** 19

## Accomplishments

- Registered a topic-, language-, and dataset-neutral research workflow with deterministic identity, exact transition lookup, and fail-closed actor/category authority.
- Added strict lifecycle, decision, attempt, artifact, Passport, resume, and recovery event variants plus a filesystem-free reducer for stage, blockers, decisions, attempts, freshness, and legal transitions.
- Added `arw status` and `arw status --json` over one strict report, with deterministic `--at` evaluation and no writes on valid, absent, or damaged roots.
- Preserved byte-exact Phase 1 manifest/event fixtures while allowing new manifests to bind the registered workflow ID and digest.

## Task Commits

1. **Task 1: Specify workflow, reducer, rejection, and status behavior as RED tests** - `2aed030` (test)
2. **Task 2: Implement registered workflow identity, authority, strict models, and pure reducer** - `23f28d2` (feat)
3. **Task 3: Implement shared status/rejection rendering and read-only CLI behavior** - `3703c12` (feat)

## Files Created/Modified

- `src/arw/workflows.py` - Immutable definitions, canonical workflow digest, legal transitions, and authority lookup.
- `src/arw/reducer.py` - Pure canonical-event reduction into strict runtime state.
- `src/arw/status.py`, `src/arw/cli.py` - Shared report plus JSON/text read-only status command.
- `src/arw/models.py`, `schemas/v1/event.schema.json` - Typed Phase 2 envelope variants with strict discriminator pairing.
- `schemas/v1/status.schema.json`, `schemas/v1/rejection.schema.json` - Closed automation and rejection contracts.
- `src/arw/journal.py` - Legacy-compatible `exclude_none` canonicalization, workflow binding validation, and existing-root replay.

## Decisions Made

- New workflow identity is explicit and digest-bound, while absence of the paired fields unambiguously selects the frozen Phase 1 compatibility mapping.
- Dynamic freshness is calculated by the pure reducer at query time; accepted events and Passport bytes remain immutable.
- Text status only renders a completed `StatusReport`; it cannot independently infer stage, blockers, or legal transitions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Compatibility] Prevented optional actor metadata from changing Phase 1 canonical bytes**
- **Found during:** Task 2 regression tests
- **Issue:** Pydantic serialized absent `actor_role` as `null`, changing golden event bytes and hash coverage.
- **Fix:** All canonical event write, compare, and hash paths exclude absent optional fields.
- **Verification:** Phase 1 init/append/replay fixtures and Phase 2 reducer/schema tests passed.
- **Committed in:** `23f28d2`

**2. [Rule 2 - Missing Critical] Closed the new workflow identity at the manifest boundary**
- **Found during:** Task 2 acceptance review
- **Issue:** The workflow registry existed, but new manifests did not yet bind its ID and digest.
- **Fix:** Added paired optional identity fields, registry digest validation, and a no-write mismatch test while preserving legacy bytes.
- **Verification:** Focused suite reported 12 passed.
- **Committed in:** `23f28d2`

**3. [Rule 1 - Security] Prevented status from creating a missing lock on damaged runs**
- **Found during:** Task 3 read-only threat review
- **Issue:** Existing replay used `a+b`, which could create `.journal.lock` before rejecting damaged state.
- **Fix:** Replay/status now require an existing regular lock and open it read-only; a filesystem snapshot test covers the damaged case.
- **Verification:** Status/version/staged suite reported 7 passed; journal/reducer/schema regression reported 13 passed.
- **Committed in:** `3703c12`

**4. [Rule 3 - Blocking] Extended exact packaged schema inventory from 8 to 10 contracts**
- **Found during:** Task 3 installed-stage smoke
- **Issue:** Build identity and exact stage allowlist still admitted only the Phase 1 schema count.
- **Fix:** Kept old eight-schema identities valid while permitting the two new checked schemas and explicitly allowlisted both staged paths.
- **Verification:** Offline staged installation and installed version smoke passed.
- **Committed in:** `3703c12`

---

**Total deviations:** 4 auto-fixed (2 security/correctness, 1 compatibility, 1 blocking packaging closure).
**Impact on plan:** All changes were required to satisfy the locked workflow identity, byte compatibility, and read-only status contracts; no domain-specific behavior was added.

## Issues Encountered

- `ruff` is not installed in the frozen project environment, so static verification used `compileall`, strict schema validation, `git diff --check`, and the executable test suites.

## User Setup Required

None - no external services or credentials are required.

## Verification

- Workflow/reducer/schema/Phase 1 journal regression: `13 passed`.
- Status, installed version, and offline staged CLI: `7 passed`.
- Python compilation and whitespace validation completed successfully.

## Next Phase Readiness

- Ready for Plan 02-02 to replace the single-file append boundary with segmented durable transactions and attempt/proposal acceptance.
- Recovery health is modeled but physical tail detection and quarantine remain intentionally assigned to Plans 02-04 and 02-05.

## Self-Check: PASSED

- All declared artifacts and three task commits exist.
- Legacy byte fixtures, checked schemas, read-only status inventories, and installed-stage packaging pass their executable checks.

---
*Phase: 02-durable-provenance-runtime*
*Completed: 2026-07-13*
