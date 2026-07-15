---
phase: 06-scientific-integrity-and-audit-dossier
plan: 02
subsystem: scientific-integrity
tags: [external-provenance, pydantic, json-schema, fail-closed, no-subprocess]

# Dependency graph
requires:
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 01
    provides: immutable integrity receipts, canonical hash/freshness primitives
provides:
  - strict arw.experiment-provenance.v1 external evidence envelope
  - parent-owned immutable provenance publication and canonical acceptance event
  - four-gate controlled-execution policy that remains hard-disabled
affects: [06-03, 06-04, 06-05, scientific-integrity, audit-dossier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "External provenance is imported evidence only; no Phase 6 function starts a process."
    - "Canonical component and envelope digests are derived from strict JSON bytes and checked on replay."
    - "Parent runtime owns experiment.provenance.accepted; producer envelopes cannot append authority."

key-files:
  created:
    - src/arw/experiment_provenance.py
    - schemas/v1/experiment-provenance.schema.json
    - tests/unit/test_experiment_provenance.py
    - tests/integration/test_experiment_provenance.py
    - tests/integration/test_controlled_execution_blocked.py
    - tests/fixtures/phase6/representative-run/experiment/provenance.json
  modified:
    - src/arw/integrity.py
    - src/arw/models.py
    - src/arw/reducer.py
    - src/arw/runtime.py
    - src/arw/workflows.py
    - schemas/v1/event.schema.json
    - tests/schema/test_phase6_contracts.py

key-decisions:
  - "Only execution_claim.mode=external_only is accepted; imported metrics never imply ARW reproduction."
  - "Qualification receipts bind exact provenance/configuration/artifact digests and an injected clock; all four fresh receipts still return controlled_execution_adapter_disabled."
  - "Caller booleans such as sandbox_passed/reproduced are rejected as authority and produce caller_supplied_gate_flag."
  - "Local references are checked against the allowed root when present; symlink/path escapes and digest mismatches fail before publication."

requirements-completed: [SCI-04, SCI-05]
---

# Phase 6 Plan 02 Summary

**Strict external experiment provenance is now replayable and parent-owned while controlled execution remains explicitly BLOCKED.**

## Accomplishments

- Added strict nested provenance records for datasets/access states, model and configuration identity, typed metrics, artifacts, redacted environment, runner identity, execution claim, qualification references, source manifests, and derived `provenance_sha256`.
- Added component digest checks, duplicate/order/path/secret/unknown-field validation, bounded canonical publication, cold loading, and allowed-root local-file verification.
- Added `experiment.provenance.accepted` as a parent-only hash-chained event and reducer evidence reference; `ingest_experiment_provenance` publishes write-once bytes before asking the parent runtime to append the event.
- Added a pure four-gate policy for sandbox approval, accountable approval, environment capture, and provenance-equivalence probe. It reports stable missing/stale/mismatch/unauthorized reasons, never launches a subprocess, and remains blocked even when every gate is fresh and exact.
- Added Draft 2020-12 registry schema and representative fixture, plus all-16 truth-table, stale/forged receipt, no-self-attestation, no-secret, and no-subprocess tests.

## Task Commits

1. **06-02-T01 tests** — `9acc8a8` (strict external provenance contract cases)
2. **06-02-T01 implementation** — `c1615e8` (provenance model, registry schema, parent acceptance event)
3. **06-02-T02 tests** — `68fe07b` (parent ingest and controlled-execution truth table)
4. **06-02-T02 implementation correction** — `46e5161` (component digest binding and qualification receipt canonicalization)
5. **06-02-T02 forged-object correction** — `49a5c24` (revalidate model-copied qualification receipts before policy)
6. **06-02-T02 authority correction** — `cacc7b7` (enforce parent role and runtime-root binding for typed envelopes)
7. **06-02-T02 local-source correction** — `ea8fc16` (defer local byte digest comparison to allowed-root intake)
8. **06-02-T02 event-schema correction** — `d287b97` (keep the parent acceptance payload schema-tight and validate the emitted event)

## Verification

- `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/unit/test_experiment_provenance.py tests/schema/test_phase6_contracts.py tests/schema/test_schema_drift.py` — **22 passed**.
- `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/integration/test_experiment_provenance.py tests/integration/test_controlled_execution_blocked.py` — **20 passed**.
- Existing schema/runtime/canonical/manifests/recovery/cross-language subset — **71 passed**.
- `python -m compileall` for modified runtime/provenance modules — **passed**.
- `git diff --check` on all Phase 6 plan files and direct dependencies — **passed**.
- Emitted `experiment.provenance.accepted` event validated with the checked-in `event.schema.json` — **passed**.

## Deviations from Plan

1. The plan named `tests/schema/test_schema_registry.py`, but this checkout has registry drift coverage in `tests/schema/test_schema_drift.py`; the existing test was run unchanged.
2. The canonical acceptance event requires direct Phase 2/4 model, reducer, workflow, and event-schema dependencies; these were added without changing the execution adapter or introducing a subprocess path.

## Issues Encountered

None after the above test-path clarification.

## User Setup Required

None — external provenance is imported from bounded local/URI references and no credentials or network service are required.

## Next Phase Readiness

SCI-04/SCI-05 evidence is available to Phase 6 Plan 03 through `seal_experiment_provenance`, `publish_experiment_provenance`, `load_experiment_provenance`, `ingest_experiment_provenance`, and `evaluate_controlled_execution_policy`. The execution adapter remains intentionally absent/hard-disabled, so later claim gates must not upgrade imported evidence to `experiment_reproduced`.

---
*Phase: 06-scientific-integrity-and-audit-dossier*
*Plan: 02*
*Completed: 2026-07-15*
