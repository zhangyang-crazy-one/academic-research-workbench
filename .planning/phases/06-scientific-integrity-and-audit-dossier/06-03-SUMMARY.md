---
phase: 06-scientific-integrity-and-audit-dossier
plan: 03
subsystem: evidence-access-and-claims
tags: [evidence-access, scientific-claims, pydantic, json-schema, fail-closed, review]

# Dependency graph
requires:
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 01
    provides: immutable integrity receipts and freshness evaluation
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 02
    provides: external-only experiment provenance and disabled execution policy
  - phase: 04-subagent-orchestration-hooks-and-human-gates
    provides: parent-owned review, dissent, human authority, and gate records
  - phase: 05-rebuildable-research-graph-and-evidence-queries
    provides: non-authoritative graph projection receipts and watermarks
provides:
  - exact five-state, digest-bound, append-only evidence access decisions
  - pure scientific claim capability matrix with typed blockers and replacement evidence
  - staged package allowlist coverage for all Phase 6 schemas
affects: [06-04, 06-05, audit-dossier, scientific-integrity]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EvidenceAccessDecision hashes canonical JSON excluding only its own decision_sha256; predecessor/supersession references are immutable."
    - "Claim evaluation consumes typed lifecycle records and an injected clock; caller booleans, Markdown, and graph rows cannot upgrade claims."
    - "Phase 6 schemas are registry-generated and included in the positive stage allowlist."

key-files:
  created:
    - src/arw/evidence_access.py
    - schemas/v1/evidence-access-decision.schema.json
    - tests/unit/test_evidence_access.py
    - tests/integration/test_evidence_access_states.py
    - tests/integration/test_scientific_claim_gates.py
    - tests/integration/test_audit_dossier_blockers.py
  modified:
    - src/arw/integrity.py
    - tests/schema/test_phase6_contracts.py
    - scripts/stage-plugin

key-decisions:
  - "The wire contract uses evidence_sha256[] (sorted, unique) as required by the scientific-integrity research handoff; subject_sha256 remains the frozen claim subject."
  - "Unresolved or ambiguous licenses are accepted only in restricted/unavailable/human-review states and always produce a human-review/blocker claim result."
  - "Citation verification requires publicly_verified access, a citation lifecycle receipt, and an exact fresh integrity receipt; local possession is never public verification."
  - "Imported external provenance cannot produce experiment_reproduced; controlled execution remains disabled even with the four qualification receipts."
  - "Independent-review claims revalidate the Phase 4 panel manifest, every report hash, separate synthesizer, matrix/dissent, and fresh gate."

requirements-completed: [SCI-06, SCI-07]
---

# Phase 6 Plan 03 Summary

**Evidence access and scientific claim boundaries now fail closed across all five access states and the four required claim capabilities.**

## Accomplishments

- Added `EvidenceAccessState` with exactly `publicly_verified`, `locally_supplied`, `restricted`, `unavailable`, and `human_review_required`; unknown values are rejected by strict validation.
- Added canonical `EvidenceAccessDecision` records with evidence/subject/source digests, license metadata, accountable authority, scope/rationale, creation/supersession timestamps, predecessor hashes, and derived decision hashes.
- Added write-once content-addressed publication/load helpers and explicit transition validation. A successor cannot mutate its predecessor or promote local/restricted evidence without an exact public-verification receipt.
- Added pure `evaluate_claim_capability` results for `citation_verified`, `experiment_reproduced`, `independent_review_complete`, and `audit_complete`, including stable blocker reason codes and replacement evidence.
- Composed Phase 4 panel/report/synthesis/dissent/gate records and Phase 5 graph receipt boundaries without creating a second authority store.
- Added registry-generated Phase 6 access schema and staged it through the positive package allowlist.

## Task Commits

1. **06-03-T01 implementation/tests** — `9a0539f` (append-only evidence access state contract)
2. **06-03-T02 integration tests** — `504d99a` (scientific claim capability gates)
3. **06-03 correctness correction** — `701ddea` (restricted ambiguous licenses remain review-bound)
4. **06-03 contract correction** — `22029a1` (evidence digest arrays and citation lifecycle receipt)
5. **06-03 staged package correction** — `b1f6191` (Phase 6 schema allowlist coverage)

## Verification

- `UV_OFFLINE=1 PYTHONNOUSITE=1 .venv/bin/python -m pytest -q tests/unit/test_evidence_access.py tests/schema/test_phase6_contracts.py tests/schema/test_schema_drift.py tests/integration/test_evidence_access_states.py tests/integration/test_scientific_claim_gates.py tests/integration/test_audit_dossier_blockers.py` — **22 passed**.
- Existing Phase 4/5 composition tests (`test_human_gates.py`, `test_orchestration_panels.py`, `test_graph_authority.py`, `test_graph_rebuild.py`, `test_review.py`) — **26 passed**.
- Staged/package subset after allowlist correction — **25 passed** in 131 seconds; direct `scripts/stage-plugin --clean --stage-root build/stage/academic-research-workbench` — **stage ready**.
- Initial non-host regression before the allowlist correction — **409 passed**, with stage-related failures caused by the newly added schemas; the allowlist correction addressed that root cause.
- `git diff --check` for all Plan 03 files — **passed**.

## Deviations from Plan

1. The plan referenced `tests/schema/test_schema_registry.py`, but this checkout keeps registry drift coverage in `tests/schema/test_schema_drift.py`; the existing test was run unchanged.
2. Phase 6 schemas required a direct `scripts/stage-plugin` allowlist update because positive staging, not `.gitignore`, defines the installed artifact boundary. This was a direct dependency of the new checked-in schema contract.
3. A later staged rerun hit `/tmp` disk-quota exhaustion while copying the file-base binary. A controlled repo-local stage run had already passed; no tests were removed or downgraded.

## Issues Encountered

- The repository's full non-host suite initially exposed stale package allowlists after adding the three Phase 6 schemas; fixed in `b1f6191` and verified by direct staging and 25 staged/package tests.
- Fresh installed-route reruns can exhaust the shared `/tmp` quota; subsequent verification should set the test/stage temporary root to a repo-local controlled directory.

## Authentication Gates

None.

## User Setup Required

None. Controlled execution remains intentionally disabled and no credentials are captured by the access/claim evaluator.

## Next Phase Readiness

SCI-06/SCI-07 are available to the audit-dossier collector through the access decision publication/load helpers and `evaluate_claim_capability`. Technical claim gates remain separate from the mixed-license release verdict; unresolved SUP-04/P04-09 intended-use/permission evidence must continue to block release.

## Self-Check: PASSED

- All key files listed above exist.
- Commits `9a0539f`, `504d99a`, `701ddea`, `22029a1`, and `b1f6191` are present in history.
- Plan-level acceptance tests and the existing review/human-gate/graph authority subset pass.

---
*Phase: 06-scientific-integrity-and-audit-dossier*
*Plan: 03*
*Completed: 2026-07-16*
