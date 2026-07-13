---
phase: 02-durable-provenance-runtime
verified: 2026-07-13
status: passed
score: 6/6 requirements; 15/15 design decisions; 4/4 success criteria
---

# Phase 2 Verification

## Goal

Operators can trust canonical run state to survive invalid input and process failure without losing, duplicating, or silently rewriting accepted research work.

## Requirement Evidence

| Requirement | Result | Evidence |
|---|---|---|
| RUN-03 | PASS | Invalid, duplicate, stale, out-of-order, unauthorized, blocked, and reused-identity requests preserve canonical trees and report the accepted revision. |
| RUN-04 | PASS | Fresh installed processes reconstruct revision/head/stage/Passport from accepted events and immutable manifests after pointers and projections are deleted; resealed semantic tampering blocks. |
| RUN-05 | PASS | Artifact and Passport manifests are canonical, content-addressed, event-selected, pre-state-bound, and linearly superseded. |
| RUN-06 | PASS | Exact current Passport resumes once; stale, superseded, expired, and duplicate resumes reject; crash/recovery does not repeat accepted work. |
| RUN-07 | PASS | One strict status model reports stage, revision, head, Passport, recovery, blockers, decisions, attempts, and legal transitions in JSON and text. |
| RUN-08 | PASS | Only a terminal parse/UTF-8 tail is recoverable; raw segment/receipt/offset/operator/reason evidence is preserved and bound to one recovery-first segment. |

## Design Intent

- D-01 through D-15 are all true in `build/evidence/phase-02/verdict.json`.
- The runtime and fixture are domain-neutral; no Chinese-language, military-event, dataset, model, or paper-topic assumption appears in canonical workflow authority.
- Canonical authority remains run manifest, accepted journal events, and immutable manifests. Pointers, status, indexes, graphs, transcripts, hooks, and quarantine files cannot independently advance state.
- Observation and repair remain separate: status/replay are read-only; recovery is explicit and operator-authorized.

## Success Criteria

| Criterion | Result |
|---|---|
| Side-effect-free rejection with accepted revision | PASS |
| Projection-free replay from canonical events/manifests | PASS |
| Crash-safe checkpoint/resume and forensic recovery evidence | PASS |
| Complete status after normal, recoverable, and blocked replay | PASS |

## Executed Gates

- `UV_OFFLINE=1 uv run --frozen pytest -q`: `138 passed in 160.58s`.
- `./scripts/verify-sources`: `source verification PASS`.
- `./scripts/verify-phase-1`: technical `PASS`, release `BLOCKED`, identity `c4ed683d4460697c1ce462501335d9d0b34cda8d74bb51347ad79f711ebaa719`.
- `UV_OFFLINE=1 ./scripts/verify-phase-2 --clean --evidence-root build/evidence/phase-02`: technical `PASS`, release `BLOCKED`, 149 raw evidence files.
- License/pre-vendor/inventory matrix: `6 passed`; reproduced SBOM digest matches the technical evidence record.

## Security And Review

`02-REVIEW.md` has no open finding. `02-SECURITY.md` closes all 20 plan-time threats. Deterministic symlink and destructive-root cases are closed; the broader race-sensitive replacement matrix remains explicitly assigned to Phase 3 VER-03.

## Release Boundary

Phase 2 is technically complete. SUP-04 still lacks intended-use, distribution, accountable approval, or separate permission evidence, so release qualification correctly remains `BLOCKED`.

## Verdict

**PASS. Phase 2 fully satisfies its declared technical goal, six requirements, four roadmap success criteria, and all 15 locked design decisions. No human-only verification or gap-closure plan is required.**
