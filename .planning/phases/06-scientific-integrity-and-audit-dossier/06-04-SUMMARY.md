---
phase: 06-scientific-integrity-and-audit-dossier
plan: 04
subsystem: audit-dossier
tags: [canonical-bytes, replay, projection-loss, secret-safety, json-schema]

# Dependency graph
requires:
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 01
    provides: immutable integrity receipts and freshness evaluation
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 02
    provides: external-only provenance and disabled controlled execution
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 03
    provides: five-state access decisions and claim-capability gates
  - phase: 05-rebuildable-research-graph-and-evidence-queries
    provides: disposable graph receipts and non-authoritative projection
provides:
  - strict arw.audit-dossier.v1 canonical manifest and registry schema
  - write-once content-addressed dossier publication and cold loading
  - deterministic JSON/Markdown renderers with explicit authority boundary
  - replay-first assembly, typed projection-loss blocker, bounded references,
    and secret/private-output rejection
affects: [06-05, scientific-integrity, audit-dossier, verifier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dossier digest is SHA-256 of canonical JSON with only dossier_sha256 excluded."
    - "JSON and Markdown are renderings; replayed ledger/manifests remain authority."
    - "Projection loss is represented by an in-memory projection_unavailable blocker."

key-files:
  created:
    - src/arw/audit_dossier.py
    - schemas/v1/audit-dossier.schema.json
    - docs/runtime/audit-dossier.md
    - tests/unit/test_audit_dossier.py
    - tests/integration/test_audit_dossier_replay.py
    - tests/property/test_audit_dossier_replay.py
    - tests/fixtures/phase6/representative-run/dossier/manifest.json
  modified:
    - src/arw/integrity.py
    - src/arw/schema_registry.py

key-decisions:
  - "Technical and release qualifications are separate; default release evidence retains CC_BY_NC_PERMISSION_UNRESOLVED, P04-09, and SUP-04 blockers."
  - "Graph receipt metadata is accepted only after strict validation; SQLite rows cannot supply dossier authority."
  - "Missing projection adds a typed blocker to the regenerated dossier bytes without appending ledger/events or mutating graph state."
  - "Strict JSON arrays are canonicalized to sorted unique immutable tuples; generated_at is caller-injected for frozen rerender checks."

patterns-established:
  - "Typed integrity/provenance/access objects are revalidated before reducing to exact digest references."
  - "Bounded dossier strings reject secret markers, private paths, and private full text; raw evidence is never embedded."

requirements-completed: [SCI-01, SCI-06, SCI-07, VER-07]
---

# Phase 6 Plan 04 Summary

**A replay-first scientific audit dossier now provides deterministic, bounded,
non-authoritative JSON and Markdown views while preserving technical versus
legal/release qualification.**

## Accomplishments

- Added strict `arw.audit-dossier.v1` Pydantic models for run history, exact
  manifest/Passport/receipt/provenance/access/review/dissent/human/graph/test/
  benchmark/build/source/integration-lock references, claim capabilities,
  qualifications, and typed blockers.
- Added registry-derived Draft 2020-12 schema and checked-in
  `audit-dossier.schema.json` without changing the legacy Phase 6 tuple used by
  existing receipt tests.
- Added canonical digest sealing, write-once publication/load, frozen JSON
  rendering, and deterministic Markdown presentation explicitly labelled as
  non-authoritative.
- Added parent-owned assembly over replay state, strict revalidation of typed
  integrity/provenance/access/graph records, bounded output and secret/private
  path rejection, and projection-loss replay that adds only an in-memory
  `projection_unavailable` blocker.
- Added representative fixture plus unit, integration, and stdlib property
  permutation tests for byte-identical rerender, digest/ordering rejection,
  authority boundaries, projection loss, and mixed-license release blocking.

## Task Commits

1. **06-04-T01** — `537eb95` (`feat(06-04): add canonical audit dossier contract`)
2. **06-04-T02** — `a118bf9` (`feat(06-04): harden dossier replay and projection loss`)

## Verification

- `UV_OFFLINE=1 PYTHONNOUSITE=1 .venv/bin/python -m pytest -q tests/schema/test_phase6_contracts.py tests/schema/test_schema_drift.py tests/unit/test_integrity_receipts.py tests/unit/test_experiment_provenance.py tests/unit/test_evidence_access.py tests/unit/test_audit_dossier.py tests/integration/test_integrity_receipts.py tests/integration/test_experiment_provenance.py tests/integration/test_controlled_execution_blocked.py tests/integration/test_evidence_access_states.py tests/integration/test_scientific_claim_gates.py tests/integration/test_audit_dossier_blockers.py tests/integration/test_audit_dossier_replay.py tests/property/test_audit_dossier_replay.py` — **68 passed**.
- `UV_OFFLINE=1 PYTHONNOUSITE=1 .venv/bin/python -m pytest -q tests/integration/test_audit_dossier_replay.py tests/property/test_audit_dossier_replay.py tests/integration/test_graph_rebuild.py tests/integration/test_graph_authority.py tests/integration/test_orchestration_replay.py` — **24 passed**.
- `UV_OFFLINE=1 PYTHONNOUSITE=1 .venv/bin/python -m compileall -q src/arw tests/unit/test_audit_dossier.py tests/integration/test_audit_dossier_replay.py tests/property/test_audit_dossier_replay.py` — **passed**.
- `git diff --check` — **passed**.

## Deviations from Plan

1. The environment has no `hypothesis` module; the property test uses all six
   standard-library permutations instead of adding a dependency or weakening
   coverage with an xfail.
2. Existing Phase 6 tests intentionally retain their three-name
   `PHASE6_SCHEMA_NAMES` assertion. The audit schema is added through a
   separate registry-derived `AUDIT_SCHEMA_NAMES` tuple so legacy contract
   tests remain green while the checked-in registry includes the new schema.

## Issues Encountered

None after the above dependency/test-path clarifications.

## Authentication Gates

None.

## User Setup Required

None. Dossier assembly is offline and never starts an experiment or requires
credentials.

## Next Phase Readiness

Plan 06-05 can use `assemble_audit_dossier`, `publish_audit_dossier`,
`load_audit_dossier`, `replay_audit_dossier`, and the registry-generated schema
for serial verifier, staged-package, and full-regression qualification.

## Self-Check: PASSED

- All key files listed above exist.
- Commits `537eb95` and `a118bf9` are present in history.
- Plan-level focused, replay, graph, schema, and claim-gate checks pass.

---
*Phase: 06-scientific-integrity-and-audit-dossier*
*Plan: 04*
*Completed: 2026-07-16*
