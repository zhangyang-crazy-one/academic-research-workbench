---
phase: 02-durable-provenance-runtime
plan: 04
subsystem: journal-recovery
tags: [tail-classification, quarantine, recovery, fsync, sigkill, forensics]

requires:
  - phase: 02-durable-provenance-runtime
    provides: Segmented journal, pure reducer, immutable manifests, Material Passport, and sole-writer runtime from Plans 01-03
provides:
  - Read-only trustworthy-prefix classification for healthy, recoverable-tail, and blocked journals
  - Immutable quarantine raw copy and canonical recovery receipt cross-bound to one recovery-first segment
  - Crash-safe idempotent explicit recovery with evidence at each durable boundary
affects: [02-05-runtime-verifier, phase-04-orchestration, phase-06-audit, phase-07-release]

tech-stack:
  added: []
  patterns:
    - Only a terminal parse/UTF-8 failure after a trustworthy prefix is recoverable
    - Damaged canonical bytes remain in place and continuation starts in the next numeric segment
    - Existing recovery is accepted on retry only when request, event, receipt, and raw evidence match exactly

key-files:
  created:
    - src/arw/recovery.py
    - schemas/v1/recovery-request.schema.json
    - schemas/v1/recovery-receipt.schema.json
    - tests/unit/test_recovery_scan.py
    - tests/integration/test_recovery.py
    - tests/integration/test_recovery_crash.py
  modified:
    - src/arw/journal.py
    - src/arw/runtime.py
    - src/arw/reducer.py
    - src/arw/status.py
    - src/arw/cli.py

key-decisions:
  - "Recovery eligibility is limited to a final malformed, incomplete, or truncated-UTF-8 record after at least one fully validated event."
  - "A recovered chain is healthy only when the next segment begins with recovery.completed and its event, original segment, raw copy, and canonical receipt all cross-validate."
  - "Status and replay return the last trustworthy prefix for recoverable or blocked damage; only explicit operator recovery writes quarantine or continuation bytes."

patterns-established:
  - "Recovery writes raw and receipt evidence with file/directory fsync before atomically publishing the next segment."
  - "Conflict preflight occurs before any evidence write; exact post-publication retry returns the accepted event without duplication."

requirements-completed: [RUN-04, RUN-06, RUN-07, RUN-08]

duration: 16 min
completed: 2026-07-13
---

# Phase 2 Plan 4: Evidence-Preserving Recovery Summary

**Terminal journal damage can now be classified without writes, quarantined with exact forensic evidence, and continued once through a recovery-bound next segment.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-07-13T13:19:21Z
- **Completed:** 2026-07-13T13:34:59Z
- **Tasks:** 3
- **Files modified:** 19

## Accomplishments

- Added a shared byte-offset scanner that exposes the last trustworthy event prefix while separating recoverable terminal parse failures from accepted-event, middle-chain, manifest, or recovery-binding corruption.
- Added immutable raw quarantine and canonical receipt evidence binding segment path/count/hash, accepted end, fault offset/class, operator, reason, command/event identity, and timestamp.
- Added explicit operator-only recovery that publishes one recovery-first next segment and supports exact idempotent retry after three SIGKILL boundaries.
- Proved recovery evidence tampering, forged continuation, unbound next segments, and conflicting orphan evidence remain blocked without silent repair.
- Proved a recovery boundary can feed the standard recovery Passport checkpoint path and later legal lifecycle transitions.

## Task Commits

1. **Task 1: Build the adversarial tail, middle-corruption, and recovery crash oracle** - `3e42338` (test)
2. **Task 2: Implement read-only fault classification and recovery-aware replay/status** - `228b179` (feat)
3. **Task 3: Implement explicit locked quarantine and recovery continuation** - `3d827eb` (feat)
4. **Regression fix: Refuse Phase 1 append after damaged replay** - `e5843f6` (fix)

## Files Created/Modified

- `src/arw/journal.py` - Trusted-prefix scan, fault metadata, recovery-bound replay, partial append failpoint, and next-segment publication.
- `src/arw/recovery.py` - Safe evidence paths, immutable raw/receipt writes, cross-binding validation, failpoints, and atomic recovery segment publication.
- `src/arw/runtime.py` - Operator authorization, stale/conflict checks, exact retry, and locked recovery transaction.
- `src/arw/reducer.py` - Recovery-event prefix validation and recovery health blockers/legal transition projection.
- `schemas/v1/recovery-*.schema.json` - Independent request and forensic receipt contracts included in staged schema identity.
- `tests/integration/test_recovery*.py` - Exact bytes, status, tampering, checkpoint, continuation, crash, retry, and retained command evidence.

## Decisions Made

- Syntactically valid but hash/revision/chain-invalid events are never disposable tails, including the final accepted record.
- Quarantine stores the complete unchanged damaged segment, not only the malformed suffix, while the receipt records the exact accepted/fault offset.
- Recovery does not auto-create mutable state or a special Passport; a normal `checkpoint_kind=recovery` command is legal immediately after the accepted recovery event.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Correctness] Blocked malformed recovery-boundary records**
- **Found during:** Task 2 scanner verification
- **Issue:** A malformed first record in the segment after a damaged tail was initially reclassified as a new recoverable tail.
- **Fix:** Any pending recovery boundary whose first record fails now becomes `recovery-binding` and `blocked`.
- **Verification:** Scanner matrix reports 26 passed.
- **Committed in:** `228b179`

**2. [Rule 1 - Security] Preflighted conflicting orphan evidence before raw publication**
- **Found during:** Task 3 threat-model audit
- **Issue:** A conflicting pre-existing receipt could be discovered only after writing a new raw copy.
- **Fix:** Validate both target paths and exact existing bytes before creating directories or writing either evidence file.
- **Verification:** Full-tree conflict test and recovery/crash matrix report 22 passed.
- **Committed in:** `3d827eb`

**3. [Rule 1 - Compatibility] Restored the Phase 1 damaged-append rejection boundary**
- **Found during:** Full offline repository regression
- **Issue:** Legacy replay could expose a blocked prefix, but the Phase 1 append writer did not check recovery health before appending.
- **Fix:** Require healthy replay before baseline append, preserving the malformed journal byte-for-byte.
- **Verification:** The exact Phase 1 stale/malformed append regression passes.
- **Committed in:** `e5843f6`

**4. [Rule 3 - Blocking] Extended staged schema identity from 18 to 20 files**
- **Found during:** Task 3 package closure
- **Issue:** Recovery request and receipt schemas were absent from the exact staged allowlist/build identity.
- **Fix:** Registered and explicitly staged both contracts and updated installed version assertions.
- **Verification:** Installed version/offline staged CLI report 3 passed.
- **Committed in:** `3d827eb`

---

**Total deviations:** 4 auto-fixed (3 correctness/security/compatibility, 1 package closure).
**Impact on plan:** Fixes enforce the planned fail-closed and crash-safe recovery semantics without granting recovery to non-tail corruption.

## Issues Encountered

- Repeated staged tests filled the `/tmp` quota with 8.6 GB of test-owned copies; removing the completed pytest directory restored 12 GB free and the three affected staged tests then passed.
- The staged test regenerated `SBOM.cdx.json` after schema inventory changed, so one supply-chain evidence hash is intentionally stale until Plan 02-05 rebuilds the complete Phase 1/staged evidence closure.

## User Setup Required

None - no external configuration is required.

## Verification

- Scanner/status/reducer/schema task matrix: `26 passed`.
- Recovery, crash, Passport, runtime, Phase 1 replay, and schema matrix: `56 passed`.
- Installed version and offline staged CLI: `3 passed`.
- Full offline repository probe: `117 passed`; one runtime regression was fixed, three quota failures were cleared and retested as `5 passed`, and the remaining generated supply-chain hash closure is assigned to Plan 02-05.
- Python compilation and whitespace validation completed successfully; `ruff` is not installed in the frozen environment.

## Next Phase Readiness

- Ready for Plan 02-05 to produce one staged projection-free end-to-end fixture, rebuild schema/SBOM/supply-chain identity, and run both phase verifiers plus the full offline suite.
- No recovery requirement or Plan 02-04 threat remains unimplemented; final repository qualification still requires the expected generated evidence refresh.

## Self-Check: PASSED

- All declared scanner, recovery service, schemas, fixtures, crash evidence, and task commits exist.
- Original damaged bytes, quarantine copies, receipt/event bindings, exact retries, status exits, standard recovery checkpoint, and post-recovery continuation are executable and green.

---
*Phase: 02-durable-provenance-runtime*
*Completed: 2026-07-13*
