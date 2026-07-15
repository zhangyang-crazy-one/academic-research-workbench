---
phase: 06-scientific-integrity-and-audit-dossier
plan: 01
subsystem: scientific-integrity
tags: [pydantic, json-schema, sha256, freshness, immutable-evidence]

# Dependency graph
requires:
  - phase: 05-rebuildable-research-graph-and-evidence-queries
    provides: disposable projection receipts and canonical manifest references
provides:
  - strict arw.integrity-receipt.v1 contract and registry-derived schema
  - canonical receipt sealing, write-once publication, cold loading, and freshness evaluation
  - SCI-01 mutation, expiry, tamper, collision, and replay evidence
affects: [06-02, 06-04, 06-05, audit-dossier, scientific-integrity]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Integrity receipt digest is SHA-256 of canonical JSON with only receipt_sha256 excluded."
    - "Receipt publication is write-once below a safe run root; evaluation is pure and never appends authority."

key-files:
  created:
    - src/arw/integrity.py
    - schemas/v1/integrity-receipt.schema.json
    - tests/schema/test_phase6_contracts.py
    - tests/unit/test_integrity_receipts.py
    - tests/integration/test_integrity_receipts.py
    - tests/fixtures/phase6/representative-run/integrity/receipt.json
  modified:
    - src/arw/schema_registry.py

key-decisions:
  - "JSON arrays are accepted at the wire boundary and retained as immutable tuples; digest and reason arrays must be sorted and unique."
  - "A stored receipt remains immutable when stale; current subject/input digests and an injected clock determine fail-closed evaluation."
  - "The content address is the derived receipt_sha256 over unsigned canonical bytes, so cold loading validates the receipt field/canonical bytes rather than hashing the full file including its own digest."

patterns-established:
  - "Registry-derived Phase 6 schemas are validated independently through Draft 2020-12."
  - "Tamper, missing source, future timestamp, mismatch, and expiry produce deterministic reason codes and replacement references."

requirements-completed: [SCI-01]

# Metrics
duration: 20m
completed: 2026-07-15
---

# Phase 6 Plan 01 Summary

**Immutable, canonical integrity receipts now provide strict SCI-01 evidence with deterministic digest and freshness invalidation.**

## Accomplishments

- Added strict `arw.integrity-receipt.v1` Pydantic models for subject/input identity, method/tool provenance, freshness policy, verdict, reasons, source manifests, and derived receipt hash.
- Added registry-derived Draft 2020-12 schema generation and checked-in contract validation without a new static schema-count authority.
- Added write-once safe-root receipt publication, cold loading, tamper detection, and pure subject/input/freshness evaluation with replacement references.
- Retained fixture-backed tests for canonical hashing, duplicate/noncanonical arrays, digest substitution, expiry, future clocks, collisions, symlinks, and projection-free replay.

## Task Commits

1. **06-01-T01 tests** — `868dbab` (test: strict integrity receipt contract cases)
2. **06-01-T01 implementation** — `42dba4c` (feat: immutable integrity receipt contract)
3. **06-01-T02 tests** — `0e6dbbc` (test: immutable receipt publication and replay)
4. **06-01-T02 implementation correction** — `7900e97` (fix: validate receipt content on cold load)

## Verification

- `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/schema/test_phase6_contracts.py tests/schema/test_schema_drift.py tests/unit/test_integrity_receipts.py` — **15 passed**.
- `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/schema/test_phase4_contracts.py tests/schema/test_graph_contracts.py tests/unit/test_canonical.py tests/unit/test_manifests.py tests/integration/test_passport_lifecycle.py` — **42 passed**.
- `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/unit/test_integrity_receipts.py tests/integration/test_integrity_receipts.py` — **7 passed**.
- `git diff --check` — **passed**.

## Deviations from Plan

1. The plan referenced `tests/schema/test_schema_registry.py`, but this checkout's registry drift coverage is in `tests/schema/test_schema_drift.py`; the existing test was run unchanged.
2. Cold-load validation checks the canonical receipt hash field rather than hashing the full file, because D-01 defines `receipt_sha256` as the unsigned canonical digest and the full file necessarily includes that digest.

## Issues Encountered

None after the above path/authority clarifications.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

SCI-01 is available to Phase 6 provenance and dossier plans through
`seal_integrity_receipt`, `publish_integrity_receipt`, `load_integrity_receipt`,
and `evaluate_integrity_receipt`. The receipt evaluator remains observational
and cannot upgrade a stale or mismatched record.

---
*Phase: 06-scientific-integrity-and-audit-dossier*
*Plan: 01*
*Completed: 2026-07-15*
