# Phase 6 Discussion Log

**Date:** 2026-07-15
**Phase:** 06 — Scientific Integrity and Audit Dossier
**Mode:** Default discussion, all recommended defaults accepted by user

## Discussion Outcome

The user delegated the recommended choices for every discussion branch. The
selected design is therefore the strict, fail-closed option in each area and
is recorded in `06-CONTEXT.md` as D-01 through D-14.

## Area 1 — Integrity receipts and freshness

Options considered:

1. Invalidate only when subject/input digests change.
2. Use only a time-to-live window.
3. Combine digest invalidation with an explicit freshness window and
   `valid_until` (selected).

Selected because scientific inputs can change without a caller changing a
route, while a time window alone cannot detect changed content. The receipt
must expose both the exact digest mismatch and the freshness reason.

## Area 2 — External experiment provenance

Options considered:

1. Execute experiments from the workbench by default.
2. Accept a small metrics-only result envelope.
3. Validate externally executed evidence through a strict common schema and
   keep controlled execution blocked until sandbox, approval, environment
   capture, and provenance-equivalence gates pass (selected).

The selected path records dataset/model/config/metrics/artifacts, runner and
environment identity, source digests, and immutable links. It prevents a
provenance record from being mistaken for a locally reproduced experiment.

## Area 3 — Evidence access state and claim language

Options considered:

1. Collapse all evidence into verified/unverified.
2. Treat locally supplied or restricted material as equivalent to public
   verification.
3. Use the exact five-state model and enforce claim-level gates without state
   upgrades (selected).

The selected states are `publicly_verified`, `locally_supplied`, `restricted`,
`unavailable`, and `human_review_required`. Citation verification,
reproduction, independent review, and audit completion require their own fresh
lifecycle evidence.

## Area 4 — Audit dossier shape

Options considered:

1. Produce Markdown as the primary report.
2. Generate an ad-hoc JSON summary from graph/projection state.
3. Build one canonical machine-readable dossier manifest and deterministically
   render JSON and Markdown from it (selected).

The dossier must include all canonical run, manifest/Passport, integrity,
external provenance, access-state, review/dissent, waiver/correction,
projection, test/benchmark, build/source, blocker, and verdict references. It
must be bounded, secret-safe, cold-replayable, and explicitly non-authoritative.

## Follow-up Planning Constraints

- Compose Phase 4 lifecycle/review/human-gate records and Phase 5 graph
  projection receipts; do not introduce a competing authority store.
- Use strict schema/version validation and canonical-byte hashes; caller-supplied
  verdicts, hashes, or freshness booleans are not evidence.
- Keep technical qualification separate from legal/intended-use release
  status. The known SUP-04/P04-09 blocker remains visible in the dossier.
- Include unit, integration, cold-replay, and staged package tests in the plan;
  retain the positive stage allowlist as the distribution boundary.

---

*Discussion complete: 2026-07-15*
