---
phase: 06
status: passed-technical-release-blocked
verified: 2026-07-16
review_status: resolved_with_qualification_block
requirements: [SCI-01, SCI-04, SCI-05, SCI-06, SCI-07, VER-07]
---

# Phase 06 Verification — Scientific Integrity and Audit Dossier

## Result

Phase 6 technical qualification is **PASS**. The release qualification is
**BLOCKED**, independently of the technical result, by `SUP-04`, `P04-09`,
and unresolved CC BY-NC intended-use, distribution, accountable-approval, and
permission evidence. This verification does not authorize publication,
distribution, or a push.

The final serial verifier is retained at
`build/evidence/phase-06-final-verifier/`. Its machine-readable verdict binds
HEAD `92354292d8dd92e99650d81daf09e62aa6037ba3`, Codex CLI `0.144.4`, the
current dirty-tree identity, source manifest, schema registry, SBOM,
wheelhouse, retained license verdict, and the exact Phase 04.1 integration
lock. The final verifier reports:

```text
technical_qualification: PASS
release_qualification: BLOCKED
release_blockers: SUP-04, P04-09, permission_unresolved
```

## Evidence gates

| Gate | Retained evidence | Result |
| --- | --- | --- |
| Phase 6 focused schema/unit/integration/property suite | `build/evidence/phase-06-final-verifier/commands/phase6-tests/` — 79 passed, no skip/xfail | PASS |
| Phase 4/5 composition and replay subset | `commands/prior-phase-regressions/` — 34 passed | PASS |
| Source and license input verification | `commands/source-verification/`, `identities.json`, retained `license-verdict.json` | PASS technically; release blocked |
| Locked positive stage | `commands/stage-build/`, `commands/stage-validate/`, `stage/inventory-diff.json` — no missing/unexpected files | PASS |
| Exact host/integration qualification | `build/evidence/phase-04.1-host-canary-20260715i/` — integration lock and host canary | PASS |
| Serial full non-host regression | `build/evidence/phase-06-final-full/full/pytest.stdout.log` — 448 passed in 372.05s | PASS |

The full regression was run with an absolute repository-owned temporary root.
Its stdout SHA-256 is
`f313c55b0e4eb4c137ad4d071e8b8da2cf519b99b88a4a7503ad67883c4ef5d6`; stderr
is empty with SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The locked stage uses tree identity
`c4095eb25d5c3ed5d8d25a2c74f2af06a1995914d9a7b8ee26b39914b5411046`.
The integration lock is
`build/evidence/phase-04.1-host-canary-20260715i/integration-lock.json` with
SHA-256 `9d6ea3514e6abaed34e1223fbe3631e0e53a6d74b7f6945ebb29666aaf2be0c6`.
It binds ARS adapter `0.1.20`, the pinned ARS commits/trees, file-base commit
`ee68144af5453addda995a27cce8142999f318fb` and ordered patch digests, the
ARW wheel/source identities, Codex `0.144.4`, hook definition and evidence
digests, and the retained mixed-license verdict.

The exact host canary reports `technical_qualification: PASS`,
`three_home_isolation: PASS`, `assignment_identity_mapping: PASS`,
`controlled_result_channel: PASS`, `hook_status_classification: PASS`, and
`credential_hygiene: PASS`. Three fresh HOME receipts are retained; no secret
material or absolute-path material is retained. Hook observations cover
trusted/enabled, disabled, untrusted, timeout, and failure states while the
parent authority remains unchanged.

## Requirement verification

| Requirement | Verification evidence | Status |
| --- | --- | --- |
| SCI-01 | Immutable versioned integrity receipts, canonical SHA-256 sealing, write-once publication, subject/input mutation and freshness invalidation tests; Plans 06-01/06-04; final verifier requirements map | PASS |
| SCI-04 | Strict external-only experiment provenance envelope, digest-bound datasets/config/metrics/artifacts, parent acceptance event, cold-load tests; Plan 06-02; final verifier requirements map | PASS |
| SCI-05 | Four-gate controlled-execution policy (sandbox, accountable approval, environment capture, provenance-equivalence) fails closed and launches no subprocess, including all-four-present hard-disabled case | PASS |
| SCI-06 | Exact five-state access contract with append-only decisions, predecessor/supersession binding, and no local/restricted-to-public upgrade | PASS |
| SCI-07 | Claim capability evaluator requires fresh typed lifecycle evidence for citation, reproduction, independent review, and audit; imported evidence, stale records, missing dissent, and projection loss block | PASS |
| VER-07 | Canonical replay-first dossier, deterministic JSON/Markdown rendering, typed projection-loss blocker, review/dissent/human/build/test/source references, staged inventory and verifier evidence | PASS |

The 06-01 through 06-05 summaries and the Phase 6 code review provide the
plan-level implementation and adversarial evidence. The review status is
`resolved_with_qualification_block` with zero remaining critical or warning
findings; direct forged dossier PASS paths are rejected and positive cold-load
qualification is bound to replay and typed evidence.

## Scope and remaining blockers

Phase 6 closes scientific-integrity and dossier technology only. ARS remains
an external exact installation (`0.1.20`) rather than silently bundled
workflows. The dossier and verifier preserve the mixed-license identity and
do not upgrade private-repository status into intended-use or distribution
permission. Accountable human assessment for `P04-09` and the `SUP-04`
intended-use/distribution/permission evidence remain required before any
release verdict can change.

Science Workbench paper AST/export is still a v2/deferred capability; this
phase does not claim to replace a complete research-to-paper workflow.

## Planning reconciliation

- `ROADMAP.md`: Phase 6 is marked `5/5`, technical complete on 2026-07-16,
  with release blocked.
- `REQUIREMENTS.md`: `SCI-01`, `SCI-04`, `SCI-05`, `SCI-06`, `SCI-07`, and
  `VER-07` are marked complete from the retained technical evidence; this is
  not a release authorization.
- `STATE.md`: Phase 6 is at plan 5/5 with technical closeout complete and the
  release/legal blocker retained. Phase 4's separate `P04-09` blocker and
  Phase 7's not-started status are unchanged.

