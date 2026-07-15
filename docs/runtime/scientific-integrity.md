# Scientific integrity and audit dossier

Phase 6 records scientific evidence as immutable, digest-bound receipts. The
audit dossier is a deterministic, non-authoritative view over the parent ledger
and content-addressed manifests; deleting a SQLite/graph projection cannot
change provenance.

## Evidence boundaries

Evidence access is one of `publicly_verified`, `locally_supplied`, `restricted`,
`unavailable`, or `human_review_required`. A local copy is not public
verification, and an unresolved licence or inaccessible source remains a
human-review/blocker condition.

Experiment provenance is imported as `external_only`. Imported metrics and
artifacts do not claim ARW reproduction. Controlled execution remains disabled
unless a separately qualified adapter supplies fresh sandbox approval,
accountable approval, environment capture, and provenance-equivalence evidence.

## Dossier and release qualification

`arw.audit-dossier.v1` is the canonical JSON source for its JSON and Markdown
renderings. It contains hashes and bounded metadata, never private full text,
credentials, temporary trees, or graph databases. Technical qualification and
release qualification are independent: this repository retains SUP-04/P04-09
and unresolved CC BY-NC intended-use/permission evidence as release blockers.

The Science Workbench paper AST/export workflow remains a v2 scope item; this
headless runtime does not claim to replace the complete research-to-paper
workflow.
