---
phase: 06-scientific-integrity-and-audit-dossier
plan: 05
subsystem: qualification-and-packaging
tags: [serial-verifier, staging, sbom, build-identity, full-regression, release-blocked]

requires:
  - phase: 06-scientific-integrity-and-audit-dossier
    plan: 04
    provides: canonical replay-first audit dossier and projection-loss blockers
  - phase: 04.1-phase-4-qualification-closure-ars-integration-lock-and-insta
    provides: retained ARS/file-base/Codex integration-lock and host evidence
provides:
  - serial fail-closed Phase 6 verifier with owned evidence and identity binding
  - positive staging for Phase 6 schemas, docs, and verifier
  - technical/release qualification reconciliation and bounded full regression
affects: [phase-06-closeout, release-qualification]

tech-stack:
  added: []
  patterns:
    - "Phase 6 qualification runs serially with absolute build/tmp/phase-06 and an owned evidence root."
    - "Current HEAD, dirty tree digest, Codex CLI, schema/source/SBOM/wheelhouse, and retained integration-lock identities are recorded."
    - "Technical PASS and release BLOCKED are independent verdicts; SUP-04/P04-09 are never cleared by tests."

key-files:
  created:
    - scripts/verify-phase-6
    - tests/integration/test_phase6_verifier.py
    - tests/staged/test_phase6_audit_dossier.py
    - docs/runtime/scientific-integrity.md
  modified:
    - scripts/stage-plugin
    - .planning/phases/06-scientific-integrity-and-audit-dossier/06-VALIDATION.md

key-decisions:
  - "The verifier binds the retained license verdict without rerunning the memory-heavy native ScanCode gate; the legal release blocker remains explicit."
  - "The stage positive allowlist includes audit-dossier.schema.json, scientific-integrity.md, and verify-phase-6 while preserving prior entries."
  - "The full regression is retained as 448 passed; no skipped/xfail evidence is accepted."

requirements-completed: [SCI-01, SCI-04, SCI-05, SCI-06, SCI-07, VER-07]
---

# Phase 6 Plan 05 Summary

**Phase 6 is technically qualified by a serial verifier and clean positive
stage; release qualification remains BLOCKED only by the documented mixed
license/intended-use gate.**

## Accomplishments

- Added `scripts/verify-phase-6 --clean --evidence-root ...`, which rejects
  unsafe/unowned roots, captures bounded command evidence, checks source and
  retained license verdicts, binds HEAD/dirty tree/schema/source/SBOM/
  wheelhouse/integration-lock/Codex identities, rejects skipped/xfail output,
  validates the clean stage, and emits machine-readable requirements and
  separate technical/release verdicts.
- Extended the existing positive stage allowlist with the Phase 6 audit schema,
  runtime documentation, and verifier; staging remains private-data free and
  build identity/inventory bound.
- Added safety, stage, and private-exclusion tests and documented external-only
  experiment provenance, exact five evidence-access states, non-authoritative
  dossier rendering, and Science Workbench v2 deferral.
- Reconciled `06-VALIDATION.md` with all five plans and retained evidence.

## Task Commits

1. **06-05-T01** — `eabd860` (`feat(06-05): add serial Phase 6 verifier safety checks`)
2. **T01 license-binding correction** — `64a5605` (`fix(06-05): bind retained license verdict evidence`)
3. **06-05-T02** — `49adc19` (`feat(06-05): stage scientific integrity artifacts`)
4. **06-05-T03 validation reconciliation** — `1fc1acd` (`docs(06-05): reconcile technical validation and legal block`)

## Verification

- Phase 6 verifier: `UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=build/tmp/phase-06 ./scripts/verify-phase-6 --clean --evidence-root build/evidence/phase-06` — **PASS** (`technical_qualification: PASS`, `release_qualification: BLOCKED`). Final evidence binds HEAD `1fc1acd3f5d036a20bd18ab6bc91c09ccd5ada92`, `codex-cli 0.144.4`, the retained Phase 04.1 integration lock, schema/source/SBOM/wheelhouse identities, and stage tree digest.
- Phase 6 verifier safety tests — **5 passed**.
- Staged audit dossier tests — **2 passed**; direct `stage-plugin --clean` and
  `--validate-only` both pass, including audit schema/docs/verifier paths and
  private exclusion.
- Focused Phase 6 schema/unit/integration/property suite used by the verifier —
  **36 passed**; prior Phase 4/5 composition subset used by the verifier also
  passed.
- Full non-host regression, serial and repo-local — **448 passed in 372.05s**;
  stdout SHA-256 `f313c55b0e4eb4c137ad4d071e8b8da2cf519b99b88a4a7503ad67883c4ef5d6`,
  stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `scripts/verify-sources --inputs-only` — **PASS**. Stage inventory, build
  identity, SBOM, and retained license verdict are present under
  `build/evidence/phase-06`.

## Deviations from Plan

1. The full suite's native legal-gate test materializes a temporary SBOM hash;
   after the run the generated root `SBOM.cdx.json` mutation was restored to
   the pre-existing worktree content before the final verifier run. No user
   Phase 4/04.1 edits were reverted or staged.
2. A direct native ScanCode license-gate rerun is intentionally not part of the
   Phase 6 verifier because it previously exhausted the host memory/tmp
   environment. The verifier consumes the retained technical-PASS,
   release-BLOCKED verdict and fails closed if that legal state changes.

**Total deviations:** 2 environment/safety clarifications; no scientific or
packaging requirement was weakened. **Impact:** technical evidence is fully
retained and the legal release block remains explicit.

## Issues Encountered

None after using absolute repository-owned temporary roots and restoring the
test-generated SBOM mutation. The environment-dependent native legal scan remains
recorded as a release qualification boundary, not a green release signal.

## Authentication Gates

None.

## User Setup Required

None for technical qualification. Release still requires accountable intended-
use/distribution and CC BY-NC permission evidence; no publication or push was
performed.

## Next Phase Readiness

Phase 6 technical work is complete. `$gsd-verify-work` may inspect the retained
`build/evidence/phase-06` bundle and the separate legal blocker, but must not
convert the technical PASS into release authorization.

## Self-Check: PASSED

- All key files listed above exist.
- Task commits `eabd860`, `64a5605`, `49adc19`, and `1fc1acd` are present.
- Final verifier verdict is technical PASS/release BLOCKED; full regression is
  448 passed with no skip/xfail substitution.

---
*Phase: 06-scientific-integrity-and-audit-dossier*
*Plan: 05*
*Completed: 2026-07-16*
