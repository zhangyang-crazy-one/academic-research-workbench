---
phase: 04-subagent-orchestration-hooks-and-human-gates
plan: "10"
subsystem: evaluation-corpus
tags: [corpus, sealed-evaluation, canonical-json, leakage-tests]
requires:
  - phase: 04-subagent-orchestration-hooks-and-human-gates
    provides: strict Phase 4 contracts and canonical serialization
provides:
  - Digest-bound 32-development/16-sealed synthetic corpus
  - Parent-only sealed labels and worker projection allowlist
  - Exact family-count, digest, canonical-byte, and leakage tests
affects:
  - 04-08 full corpus verifier
  - 04-11 deterministic behavior-test matrix
tech-stack:
  added: []
  patterns:
    - Canonical JSON bytes with SHA-256 manifest bindings
    - Sealed expected labels excluded from worker-visible projections
key-files:
  created:
    - tests/evals/phase4/corpus/v1/manifest.json
    - tests/evals/phase4/corpus/v1/development/cases.json
    - tests/evals/phase4/corpus/v1/sealed-parent-only/cases.json
    - tests/fixtures/orchestration/v1/phase4-fixtures.json
    - tests/evals/test_phase4_corpus.py
  modified: []
key-decisions:
  - "The corpus uses exactly nine locked failure families with counts 6+6+6+6+6+6+5+4+3."
  - "Sealed labels and adjudication keys remain parent-only; manifest entries contain digests but no expected labels."
  - "Execution provenance uses native_profile in corpus expectations; degraded_inline and blocked remain explicit non-independent outcomes."
requirements-completed: [AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, AGT-06, AGT-07, SCI-02, SCI-03]
duration: 5m
completed: 2026-07-14
---

# Phase 04 Plan 10: Digest-Bound Evaluation Corpus Summary

The Phase 4 evaluation corpus now has an exact 48-case split, digest-bound canonical artifacts, and tests that prevent sealed expected labels from crossing into worker-visible payloads.

## Verification

- `UV_OFFLINE=1 uv run --frozen pytest -q tests/evals/test_phase4_corpus.py` — 3 passed.
- `git diff --check` — passed.

## Scope

Only the corpus, fixture, manifest, and corpus test files were changed. Runtime behavior remains owned by later Phase 4 plans.

## Next Phase Readiness

Ready for Plan 04-11, which owns the deterministic behavior-test baseline.

*Phase: 04-subagent-orchestration-hooks-and-human-gates*
*Completed: 2026-07-14*
