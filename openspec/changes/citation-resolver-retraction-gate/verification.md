# Verification and delivery scope

The 2026-10-23 #36 follow-up verifies the missing production receipt-derived contamination/conflict path. Exact scope, executable CLI commands, TDD RED/GREEN evidence, assertions and limitations are recorded in `docs/verification/citation-resolver-conflict-20261023.md`.

- Citation policy/CLI regression suite: 63 passed. Complete CLI subprocess cases include both conflict directions, agreement, missing self-report, manual notes, acquisition unknown/failure state, accepted source/entry binding, HTTP 503, old blockers and offline journal replay.
- Compatibility suite: 74 passed, 3 native file-base prerequisite skips. Legacy parser 1.0/1.1 receipt decisions remain replayable; no old document or ledger event is rewritten.
- OpenSpec strict validation, focused Ruff and Pyright checks pass. `cli.py` has a pre-existing unrelated I001, confirmed on the baseline and left unchanged.
- Provider fixtures and a transport-seam HTTPError are simulations, with Python socket/HTTP access denied in every E2E subprocess. No live provider or real-host qualification is claimed.

Canonical `citation gate --literature-entry PATH` requires a parent-accepted exact `ars-literature-entry` and, for a source-bound reference, an accepted matching `research-source-manifest`. Receipt history is replayed from retained response bytes. The structured contamination observation is persisted in the append-only gate rationale and returned in CLI JSON; all accepted evidence manifests are bound to the gate. Standalone gate output remains a proposal with `parent_admission: required`.

Resolver data and model self-reports remain separate observations. Conflicts never overwrite passport bytes or manual annotations, never treat an outage as not_found/retracted and never turn a self-report into scientific truth. Retraction supporting/research-object policy and parent-owned explicit human reconciliation remain unchanged. Existing gate rationale/evidence bounds reject oversized observations rather than truncate them. Live service behavior, OS network-isolation qualification, native prerequisite tests and complete release gates remain unverified.

No third-party dependency, vendored source, lockfile, runtime schema or event version was changed. The OpenSpec source was present only in the primary checkout's ignored directory, so this citation-specific change is now retained in the repair branch for review.
