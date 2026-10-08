## Context

Issue #94 v3 fixes graph authority to immutable parent ledgers and the existing append-only project narrative journal. Q5 selects parent-ledger anchors for future authenticated confirmations.

## Goals / Non-Goals

Goals: bounded deterministic snapshots, original-validator prefix replay, separate occurrence/semantic identities, multi-run evidence projection, explicit coverage and declared attestations.
Non-goals: Phase 1c authenticated authority, hard coverage gates, automatic semantic merging, arbitrary prose/table classification. Figure adapter remains typed unsupported until result_plot verification is integrated.

## Decisions

Snapshot vectors include project identity, journal sequence/hash and explicit sorted run identity/manifest/revision/head tuples plus protocol versions. Current projections double-read all heads; historical views stop original validators at fixed prefixes. Every journal dependency must belong to an included prefix. Manifest digests identify snapshots, not a single revision.

Claim registration and evidence updates append validated project-journal events. Semantic claim revisions have explicit predecessor hashes; occurrence selectors bind UTF-8 manuscript bytes and selected digests. Registration cannot automatically infer scientific support. Evidence updates can invalidate confirmation without changing semantic wording.

Graph construction delegates legacy references to AcceptedRef adapters. Integrity, specified checks, asserted relations, directional advisory assessments and human attestations remain independent. Citation metadata success never implies support. Existing accepted writing citation byte spans are reused; legacy receipts are not rewritten or resegmented.

Declared confirmation embeds the N-1 vector and its digest, claim digest, evidence dependency digest, statement/scope/policy and asserted author. All later views retain history but report stale for changed revisions/dependencies. No declared confirmation becomes authenticated. Existing journal readers accept and ignore new event kinds in narrative strategy projections.

Coverage reports disclose observed artifacts, extraction version, sentence count, MVP candidate occurrences, registered occurrences/claims and unknown/out-of-scope counts. Imported manuscript AI involvement stays unknown; no provenance inference from style.

## Risks / Trade-offs

Incomplete byte provenance → typed unresolved/unsupported and unknown coverage.
Concurrent writers → optimistic vector comparison reports stale; fixed prefix views remain reproducible.
Historical mutated accepted bytes → original validators reject integrity rather than reporting scientific refutation.

## Migration Plan

Add versioned contracts and new journal kinds only. Never alter retained event/receipt bytes; existing strategy and memory projections remain compatible.
