## Context

Issue #94 v3 fixes graph authority to immutable parent ledgers and the existing append-only project narrative journal. Q5 selects parent-ledger anchors for authenticated confirmations.

## Goals / Non-Goals

Goals: bounded deterministic snapshots, original-validator prefix replay, separate occurrence/semantic identities, multi-run evidence projection, explicit coverage and declared attestations.
Non-goals: automatic semantic merging and arbitrary prose/table classification. Figure adapter remains typed unsupported until result_plot verification is integrated.

## Decisions

Snapshot vectors include project identity, journal sequence/hash and explicit sorted run identity/manifest/revision/head tuples plus protocol versions. Current projections double-read all heads; historical views stop original validators at fixed prefixes. Every journal dependency must belong to an included prefix. Manifest digests identify snapshots, not a single revision.

Claim registration and evidence updates append validated project-journal events. Semantic claim revisions have explicit predecessor hashes; occurrence selectors bind UTF-8 manuscript bytes and selected digests. Registration cannot automatically infer scientific support. Evidence updates can invalidate confirmation without changing semantic wording.

Graph construction delegates legacy references to AcceptedRef adapters. Integrity, specified checks, asserted relations, directional advisory assessments and human attestations remain independent. Citation metadata success never implies support. Existing accepted writing citation byte spans are reused; legacy receipts are not rewritten or resegmented.

Declared confirmation embeds the N-1 vector and its digest, claim digest, evidence dependency digest, statement/scope/policy and asserted author. All later views retain history but report stale for changed revisions/dependencies. No declared confirmation becomes authenticated. New journal readers accept and ignore claim kinds in narrative strategy projections. Pre-claim readers do not understand these kinds; projects using claims require this reader generation or later, and downgrade requires restoring the pre-claim project snapshot.

Coverage reports disclose observed artifacts, extraction version, sentence count, MVP candidate occurrences, registered occurrences/claims and unknown/out-of-scope counts. Imported manuscript AI involvement stays unknown; no provenance inference from style.

## Risks / Trade-offs

Incomplete byte provenance → typed unresolved/unsupported and unknown coverage.
Concurrent writers → optimistic vector comparison reports stale; fixed prefix views remain reproducible.
Historical mutated accepted bytes → original validators reject integrity rather than reporting scientific refutation.

## Migration Plan

Add versioned contracts and new journal kinds only. Never alter retained event/receipt bytes; existing strategy and memory projections remain compatible.

## Authenticated extension (Phase 1c)

Authenticated-intent confirmations use a distinct v2 payload and remain unanchored until a `claim.attestation_anchored` parent event accepts the exact journal event hash. Its reducer verifies an authority accepted within N-1, the exact run prefix/manifest, actor/role/kind/gate/scope and parsed UTC time window. Before parent admission, the writer validates actual journal bytes, the full vector closure and semantic/evidence dependencies. Canonical run replay validates only the local anchor, N-1 run prefix and reducer authority envelope; it does not read project files or acquire sibling run locks. Projections independently reverify cross-log bindings. Missing, changed or locked external evidence produces an unverifiable projection rather than blocking canonical run health. Existing declared v1 bytes remain declared.

Historical authorization always uses anchor event time. Current applicability compares semantic/evidence identity independently, with optional explicit evaluation time; otherwise expiry uses the latest parent event time in the fixed snapshot. Optional hard checks only cover registered claims and observed MVP occurrences, disclose the denominator, fail for unknown/unbound observations, absent evidence/check failures or missing current authentication, and leave out-of-scope science unknown.

Each query freshly validates retained source bytes. Cross-log proof work does not recurse through canonical anchor replay, and no replay-only anchor count can poison an accepted run. Project-journal replay retains an incremental registration map within each read, validating each registration once. The shared 1 MiB journal reserves 256 KiB for core narrative events by refusing claim writes above the 768 KiB ceiling; existing bytes remain readable up to the original limit.

Hard caption checks require an explicit evaluation instant. Parent qualification binds the verifier to the request's occurred_at; a supplied earlier instant cannot override it. Read-only hard capture without an explicit instant cannot authenticate. Historical graph defaults remain deterministic at the snapshot's latest parent event time; that is not a current wall-clock authorization assertion.
