## Context

Research source manifests bind ARS entries to bytes, and integrity receipts are immutable observations. No reference resolver currently connects these records to indexed bibliographic metadata or retraction state. The parent alone owns accepted evidence and gates.

## Goals / Non-Goals

**Goals:** Deterministic, replayable index checks; distinct failure states; citation-use gates; append-only rechecks; a reference contract shared with PDF extraction.

**Non-Goals:** Proving that a paper's claims are true, treating a lookup result as source acceptance, or making hook/graph state authoritative.

## Decisions

1. `ReferenceRecord` v1 identifies DOI, arXiv ID or title/authors/year and declares each `ReferenceUse` as `supporting`, `background`, or `research_object`. A use belongs to a claim and has its own gate; the PDF change imports this same contract.
2. A provider adapter accepts exact response bytes or an injected transport. Network transport starts disabled and requires explicit opt-in. Provider URLs, timeout and response size are fixed; tests supply local fixtures. Each checked response is SHA-256 addressed and its immutable receipt names parser version, query, provider, observed time and raw digest. Offline replay parses the same bytes and checks digest.
3. Match DOI/arXiv IDs exactly after conservative normalization; title fallback requires year and normalized title, with author agreement where present. Multiple candidates are ambiguous. Provider errors/unavailability never become not_found. An explicit empty successful response is not_found for that provider; aggregate not_found requires all applicable providers to answer conclusively within one explicitly identified batch. Legacy unbatched receipts each form a singleton batch; equal timestamps do not imply common coverage.
4. Retraction indication is preserved as evidence with provider attribution. A supporting use with not_found or retracted is BLOCK; a retracted research object is HUMAN_REVIEW. No automatic waiver or PASS is emitted.
5. Rechecks publish new receipts and preserve earlier receipts and blockers. Historical verification replays the retained response bytes before evaluating each batch. A subsequent PASS cannot erase an earlier BLOCK; release requires an explicit parent reconciliation of the historical contradiction. Parent artifact acceptance validates a canonical reference record and offline-replayable receipt, and canonical `citation gate` binds accepted manifests to `gate.evaluated`. Explicit reconciliation remains human-owned.
6. The citation policy calls the existing ledger manifest and retained-byte APIs to publish immutable receipts and verify parent-accepted artifacts. This accepts one `policy -> ledger` kernel subpackage edge. The current ledger dependency closure reaches `core` and `state`, not `policy`, so this edge introduces no return path. The compatibility ratchet pins the full edge set; future changes still require explicit review.

## Risks / Trade-offs

- Indexes disagree or lag → expose ambiguous/unknown and retain raw responses for review.
- Provider formats evolve → version parsers and preserve raw bytes for repeatable reevaluation.
- Network data can be hostile → enforce response/time limits and validate URLs and schema before interpreting.

## Migration Plan

Existing sources remain valid with no inferred verification. Their citation gate is unknown until receipts are produced. No old record is rewritten.

## Open Questions

Provider-specific retraction metadata coverage varies; missing data remains unknown until independently checked.

## Issue #36 conflict follow-up

The existing receipt helper has no production caller and the canonical gate never compares the ARS entry. Add `citation gate --literature-entry PATH` for one exact JSON export of `literature_corpus[]`. Canonical evaluation requires the entry bytes to be a parent-accepted `ars-literature-entry` artifact and requires matching reference bibliographic identity; a source-bound reference additionally requires the accepted source manifest and its exact bibliographic digest. Proposal mode can compare explicit local bytes but remains noncanonical. Absence of the argument remains compatible with legacy references and produces no invented self-report.

Append a bounded, canonical JSON `contamination` observation to the existing gate rationale and return the same observation in CLI JSON. The journal binds accepted entry/source/receipt manifest digests. Reuse `ContaminationSignals` and `ContaminationSignalOmissions`: only conclusive receipts produce booleans; latest unavailable yields `api_degraded`; unknown/ambiguous/missing remain explicit lookup states. Every retained conclusive receipt that disagrees with an explicitly present self-report boolean remains a conflict, including older receipts after a later agreement. Neither missing self-report nor an omission is a contradictory boolean. Preserve exact entry bytes, manual notes, source-acquisition fields and human review state; do not overwrite the passport or let self-report alter the resolver gate verdict.
