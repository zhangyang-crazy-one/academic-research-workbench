---
phase: 01-contract-license-and-executable-baseline
plan: 05
subsystem: canonical-runtime
tags: [pydantic, portalocker, jsonl, sha256, fsync, sigkill, replay]

requires:
  - phase: 01-contract-license-and-executable-baseline
    provides: Installed Python CLI and read-only route boundary from Plan 02
provides:
  - Strict immutable run manifest and two-event canonical schemas
  - Sole-writer locked JSONL initialization, append, and full replay validation
  - Inspectable post-fsync SIGKILL and duplicate-free recovery evidence
affects: [phase-02-runtime-lifecycle, schema-registry, evidence-aggregation, installed-qualification]

tech-stack:
  added: []
  patterns:
    - Compact sorted UTF-8 JSON with one trailing newline and unsigned-event SHA-256
    - Lock-replay-validate-append-flush-fsync sole-writer protocol
    - Parent-side allowlisted evidence capture outside canonical authority

key-files:
  created:
    - src/arw/models.py
    - src/arw/canonical.py
    - src/arw/journal.py
    - src/arw/evidence.py
    - schemas/v1/run-manifest.schema.json
    - schemas/v1/event.schema.json
    - tests/integration/test_journal_replay.py
  modified:
    - src/arw/cli.py
    - SBOM.cdx.json
    - supply-chain/use-distribution.json

key-decisions:
  - "The writer owns sequence, resulting revision, previous hash, and event hash; operator requests supply only strict identity and typed payload data."
  - "Replay validates the canonical manifest and every complete JSONL line under the same inter-process lock before any append."
  - "The test-only failpoint is validated before mutation and sends SIGKILL immediately after journal fsync, before CLI output or observer evidence."
  - "Recovery evidence records only relative argv/cwd, allowlisted environment keys, raw streams, status/signal, byte snapshots, hashes, replay result, and verdict."

patterns-established:
  - "Canonical event hash: SHA-256 covers exact compact newline-terminated UTF-8 bytes with event_sha256 omitted."
  - "Crash recovery: a fresh process needs only run-manifest.json and events.jsonl; projections, hooks, transcripts, and evidence are never replay inputs."

requirements-completed: [RUN-01, RUN-02]

duration: 25 min
completed: 2026-07-13
---

# Phase 1 Plan 5: Sole-Writer Canonical Run and Forced-Stop Replay Summary

**A strict short-lived Python writer now initializes and fsyncs hash-chained canonical JSONL, survives post-fsync SIGKILL, and replays revision 2 exactly once from manifest plus journal bytes.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-13T04:04:31Z
- **Completed:** 2026-07-13T04:29:53Z
- **Tasks:** 3
- **Files modified:** 17

## Accomplishments

- Added strict Draft 2020-12 contracts and Pydantic models for immutable run identity and exactly `run.initialized` plus `baseline.probe_recorded` events.
- Implemented byte-exact canonical serialization, SHA-256 chaining, expected-revision enforcement, inter-process locking, complete-tail validation, append flush/fsync, and duplicate event/command rejection.
- Proved a real `SIGKILL` after the second event fsync and before CLI output, followed by fresh-process replay with one durable baseline event and unchanged journal bytes.
- Retained raw runtime evidence under `build/evidence/phase-01/runtime/seed/` with relative commands, allowlisted environment, streams, signal/status, journal snapshots/hashes, replay JSON, and a technical PASS verdict.
- Rebound the legal/SBOM evidence chain to the new first-party runtime wheel while preserving release qualification as BLOCKED.

## Task Commits

Each task was committed atomically, with separate RED/GREEN gates where required:

1. **Task 1: Define strict run/event contracts and execute RED canonical tests** - `4c98fc5` (test)
2. **Task 2 RED: Cover sole-writer contention and duplicate identity** - `51f3976` (test)
3. **Task 2 GREEN: Implement strict init and sole-writer append/replay** - `8caa26c` (feat)
4. **Task 3 RED: Define post-fsync kill and replay proof** - `d3ceea0` (test)
5. **Task 3 GREEN: Implement failpoint and recovery evidence** - `01da5ef` (feat)

Additional correctness commit:

- **Supply-chain evidence closure** - `c14c941` (fix)

## Files Created/Modified

- `src/arw/models.py` - Strict manifest, request, payload, and canonical event models with normalized relative input identity.
- `src/arw/canonical.py` - Compact UTF-8 serializer, strict JSON parser, unsigned event hashing, and event sealing.
- `src/arw/journal.py` - Sole-writer lock, immutable init, full-chain replay, expected-revision append, fsync, and post-fsync test failpoint.
- `src/arw/evidence.py` - Non-authoritative atomic capture of allowlisted commands, environment, streams, status, and recovery artifacts.
- `src/arw/cli.py` - Preserves route behavior and adds `init`, `append`, and `replay` surfaces backed only by the journal module.
- `schemas/v1/run-manifest.schema.json`, `schemas/v1/event.schema.json` - Independently validated strict Phase 1 wire contracts.
- `tests/fixtures/recovery/seed/` - Fixed multilingual input, requests, manifest bytes, initial event bytes, IDs, timestamps, and hashes.
- `tests/unit/test_canonical.py`, `tests/integration/test_run_init.py`, `tests/integration/test_journal_replay.py` - RED/GREEN canonical, contention, mutation-safety, forced-stop, and replay proofs.
- `SBOM.cdx.json`, `supply-chain/use-distribution.json` - Exact first-party wheel and technical-provenance digest closure after runtime changes.

## Decisions Made

- The manifest is immutable and the journal is one append-only `events.jsonl` for Phase 1; full lifecycle/checkpoint segmentation remains deferred to Phase 2.
- Operator requests cannot choose accepted sequence, resulting revision, previous hash, or event hash. The locked writer derives all four from validated durable state.
- Every append performs a full canonical replay under lock before mutation, including byte canonicality, manifest binding, event and command uniqueness, contiguous sequence/revision, and hash linkage.
- Recovery evidence is an observer generated by the parent test process after the killed writer exits; it never participates in replay or canonical mutation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Rebound legal evidence to the changed first-party wheel**
- **Found during:** Overall non-host regression verification
- **Issue:** The legal gate regenerated the CycloneDX first-party wheel digest after canonical runtime code changed, but `use-distribution.json` still referenced the pre-Plan-05 SBOM bytes. This broke the digest-closed technical provenance contract.
- **Fix:** Committed the regenerated deterministic SBOM and updated its exact technical-provenance SHA-256 reference without changing the release BLOCKED classification.
- **Files modified:** `SBOM.cdx.json`, `supply-chain/use-distribution.json`
- **Verification:** All seven license/inventory/private-exclusion tests pass; the full non-host suite passes 32 tests.
- **Committed in:** `c14c941`

---

**Total deviations:** 1 auto-fixed (1 missing critical supply-chain closure).
**Impact on plan:** The fix keeps exact installed-byte provenance synchronized with the new canonical runtime; no runtime or lifecycle scope was added.

## Issues Encountered

- The first full non-host run passed 31 tests but exposed the stale SBOM reference in one Plan 04 classifier assertion. The direct runtime-wheel cause was identified, digest closure was updated, and the full suite then passed.

## Authentication Gates

None.

## Known Stubs

None. Phase 2 lifecycle transitions, checkpoints, and projections remain intentionally out of this plan rather than stubbed.

## Verification

- Task 1 RED: 15 tests collected; expected failures were only absent serializer/models/init behavior.
- Task 2 GREEN: canonical/init suite passed all 16 tests.
- Task 3 RED: append returned normally before failpoint implementation, producing the expected boundary assertion failure.
- Task 3 GREEN: forced-stop replay test passed with return code `-9` / `SIGKILL` and empty killed-writer stdout.
- Plan suite: `17 passed`.
- License/inventory/private regression: `7 passed`.
- Full non-host regression: `32 passed, 2 deselected` (authenticated Codex-host tests intentionally excluded).
- Retained verdict: technical `PASS`, one durable baseline event, revision `2`, unchanged replay journal SHA-256 `e477c98d720d22dc9423076c696386387ae5c0f9f88d815330abe92ba97a4087`.

## Next Phase Readiness

- RUN-01 and RUN-02 are complete; Plan 01-06 can build the root-confined MCP fixture against a proven canonical runtime baseline.
- Phase 2 can extend lifecycle/checkpoint semantics without changing accepted Phase 1 manifest/event bytes or promoting projections to authority.
- Release remains intentionally BLOCKED pending intended-use, distribution, approval, and permission evidence.

## Self-Check: PASSED

- All declared key files and retained recovery evidence exist.
- Task, TDD gate, recovery, and supply-chain fix commits are present in git history.
- RUN-01/RUN-02 metadata and exact recovery verdict/hash claims match the checked artifacts.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
