---
phase: 02-durable-provenance-runtime
plan: 05
subsystem: runtime-verification
tags: [event-sourcing, json-schema, staged-plugin, crash-recovery, provenance]
requires:
  - phase: 02-durable-provenance-runtime
    provides: workflow reducer, segmented writer, immutable Passports, explicit recovery
provides:
  - complete checked Phase 2 schema and installed build identity
  - staged projection-free crash/recovery/checkpoint/resume qualification
  - repository-owned raw evidence and RUN/D decision verdict
  - deep code and security review closure
affects: [03-secure-files-first-data-plane, 04-subagent-orchestration, 07-release-qualification]
tech-stack:
  added: []
  patterns: [per-event semantic replay, owned destructive roots, raw-evidence verdict closure]
key-files:
  created:
    - scripts/verify-phase-2
    - tests/integration/test_phase2_durable_runtime.py
    - tests/integration/test_phase2_verifier_safety.py
    - docs/runtime/durable-provenance.md
  modified:
    - src/arw/journal.py
    - src/arw/reducer.py
    - src/arw/runtime.py
    - src/arw/manifests.py
    - scripts/stage-plugin
key-decisions:
  - "A structurally valid event is canonical only after the shared reducer and selected-manifest semantics validate it."
  - "Clean verification paths must be repository-owned or carry an explicit prior ownership marker."
  - "Technical Phase 2 PASS never overrides SUP-04 release BLOCKED."
patterns-established:
  - "Trusted-prefix replay: semantic corruption is blocked and inspectable without accepting or repairing the invalid event."
  - "Verdict closure: requirement booleans summarize but do not replace hashed raw command, tree, and recovery evidence."
requirements-completed: [RUN-03, RUN-04, RUN-05, RUN-06, RUN-07, RUN-08]
duration: 56min
completed: 2026-07-13
---

# Phase 2 Plan 05: Staged Qualification Summary

**Twenty-two checked runtime contracts and one staged projection-free fixture now prove the durable provenance runtime through crash, recovery, checkpoint, resume, tampering, and fresh-process replay.**

## Performance

- **Duration:** 56 min
- **Started:** 2026-07-13T13:36:40Z
- **Completed:** 2026-07-13T14:32:44Z
- **Tasks:** 3
- **Files modified:** 22

## Accomplishments

- Closed all Pydantic/JSON Schema/build-identity/staged-launcher contracts at 22 registered schemas.
- Added a staged E2E oracle that preserves 29 command records, 18 tree snapshots, recovery evidence, and a verdict for RUN-03 through RUN-08 and D-01 through D-15.
- Completed full code/security review, fixed every discovered runtime and destructive-path gap, and retained `technical PASS` separately from `release BLOCKED`.
- Reproduced the reviewed first-party wheel/SBOM identity and passed 138 frozen offline tests.

## Task Commits

1. **Task 1: Close schema, build identity, staged package, and compatibility coverage** - `3345651` (feat)
2. **Task 2: Build one projection-free end-to-end durable runtime fixture** - `6549f3d` (feat)
3. **Task 3: Run full offline regression and reconcile validation** - `b5e672b` (fix), `231b02b` (chore)

## Files Created/Modified

- `scripts/verify-phase-2` - Offline owned-root staged qualification and hashed verdict.
- `tests/integration/test_phase2_durable_runtime.py` - Full clean-install runtime/crash/recovery oracle.
- `src/arw/journal.py`, `src/arw/reducer.py` - Per-event structural and semantic trusted-prefix replay.
- `src/arw/manifests.py`, `src/arw/runtime.py` - Full checkpoint-state binding and pre-write rejection invariants.
- `scripts/stage-plugin` - Complete Phase 2 package allowlist and owned clean-root behavior.
- `docs/runtime/durable-provenance.md` - Implemented operator/status/recovery contract.

## Decisions Made

- Semantic replay failures after a trustworthy prefix are `blocked` status, not accepted history and not an unreadable-run error.
- Stable decision, attempt, and artifact IDs are single-use; shared blockers remain until every owning decision resolves.
- CLI status evaluates freshness at current UTC unless an explicit deterministic `--at` is provided.

## Deviations from Plan

### Auto-fixed Issues

**1. [Correctness/Security] Closed replay and legacy-append authority bypasses**
- **Found during:** Task 3 deep code review
- **Fix:** Applied reducer semantics per event, required explicit Phase 2 roles, and confined baseline append to legacy journals.
- **Verification:** Resealed actor attacks produce an unchanged blocked trustworthy prefix.
- **Committed in:** `b5e672b`

**2. [Correctness] Bound manifests and blockers to accepted pre-event state**
- **Found during:** Task 3 deep code review
- **Fix:** Verified complete Passport/artifact state, prevented blocked transitions and stable-ID reuse, and rejected duplicate artifacts before store writes.
- **Verification:** Manifest tamper, shared blocker, reused ID, and full-tree rejection tests pass.
- **Committed in:** `b5e672b`

**3. [Security] Confined recursive clean and writer-lock paths**
- **Found during:** Task 3 STRIDE review
- **Fix:** Added evidence-root confinement, stage ownership markers, and writer lock symlink denial.
- **Verification:** External sentinel paths remain untouched; staged and verifier safety tests pass.
- **Committed in:** `b5e672b`

**4. [Blocking] Refreshed reproducible supply-chain identity**
- **Found during:** Final full regression
- **Fix:** Rebuilt SBOM for reviewed wheel bytes and synchronized its technical evidence hash without changing release classification.
- **Verification:** License matrix passed with a stable SBOM hash after temporary quota cleanup.
- **Committed in:** `231b02b`

---

**Total deviations:** 4 auto-fixed (2 correctness, 1 security, 1 blocking metadata closure).
**Impact on plan:** All fixes tighten declared Phase 2 invariants; no deferred product capability was added.

## Issues Encountered

- Repeated full stage and license copies exhausted the 16 GB `/tmp` quota once. Completed pytest/patch copies were removed, then the exact failed gate passed with 12 GB free.
- One full-suite run correctly caught a stale SBOM evidence hash after review changes; the refreshed identity was reproduced before final qualification.

## User Setup Required

None - no external service configuration is required.

## Verification

- Full frozen offline suite: `138 passed in 160.58s`.
- Source verification: `PASS`.
- Phase 1 verifier: technical `PASS`, release `BLOCKED`.
- Phase 2 verifier: technical `PASS`, release `BLOCKED`, 149 raw evidence files.
- Requirement/decision mapping: RUN-03 through RUN-08 and D-01 through D-15 all true.

## Next Phase Readiness

- Phase 3 can build its bounded files-first data plane on a sole-writer runtime whose canonical state, Passport lineage, and recovery evidence are independently replayable.
- SUP-04 remains an intentional release blocker and must not be treated as technical debt resolved by Phase 2.

## Self-Check: PASSED

- Every Plan 05 artifact, commit, schema, staged command, raw evidence bundle, and final verdict exists.
- No open Phase 2 code-review or plan-time threat finding remains.

---
*Phase: 02-durable-provenance-runtime*
*Completed: 2026-07-13*
