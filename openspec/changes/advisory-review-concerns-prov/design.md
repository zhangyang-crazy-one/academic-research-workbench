## Context

ClaimGraph and precise source validators already identify bounded source occurrences and registered claim revisions. Existing RO-Crate export explicitly selects original parent-accepted files and verifies their bytes without mutating them.

## Goals / Non-Goals

Give author-visible source-linked suggestions and interoperable provenance with exact target replay. No scores, gates, corpus-based accuracy claims, external corpus payloads or automatic review verdicts. Clickable manuscript HTML remains optional/deferred.

## Decisions

ReviewConcern is a strict advisory-only record with a discriminated claim/occurrence target and exact SnapshotManifest. Original `_read_inputs`, closure, claim registration and occurrence validators independently check its target; neither a graph label nor the concern itself decides truth. Optional seven-class Argumentative Zoning is an explicit annotation. AMPERE proposition labels are a taxonomy reference; NLPeer motivates traceability to manuscript/review versions, not a trained predictor.

Read-only rule diagnostics suggest evidence clarification for claims lacking support and explicit registration/verification for occurrences. Requests are deterministic and carry their source/rule identity. Replay validates exact target provenance and record bytes, not whether a human judgment is correct. PROV JSON-LD associates immutable target/snapshot entities, advisory concern entities and generating annotation/rule activities. It is accepted as a normal `claims-prov` artifact before selection by the original RO-Crate exporter. No existing archive/metadata is rewritten; an additional newly created crate has its own digest. Existing structure, byte and source-binding checks are reused. Profile completeness remains the original verifier's separate judgment.

## Risks / Trade-offs

Taxonomy mistaken for validated prediction -> explicit advisory_only and no scores. Public review data rights -> only taxonomy/source links, no corpus install or redistribution until separate license review. Stale manuscript -> frozen vector replay with current applicability separately unknown. Exported remarks may be private -> explicit original artifact selection/privacy policy, no automatic publication.

## Owner review amendment

Expose review through the public launcher, bound diagnosis by count/bytes with omitted_concern_count, preserve zero-omission legacy digests, and reject non-object CLI input.
