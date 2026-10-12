## Context

#124 measures 30/60 anchors at 0.96/3.77 seconds despite linear run replay. `_attestations` repeats historical input reconstruction and anchor verification, including original parent replay and journal validation.

## Goals / Non-Goals

Goals: original validation once at each participating run's included maximum prefix, exact historical sub-prefixes, query-local keyed memo, unchanged outputs and unavailable-proof semantics. No persisted cache, cross-query trust, event reconstruction or scientific authority from projections.

## Decisions

Each operation owns a private cache whose base vector and journal have already been read by the original reader. Historical sub-prefixes require exact manifest/head/revision identities. Parent prefix loading still acquires the original read lock (or respects a caller-held writer lock) and uses original canonical validation; failures are never cached as successes. Current projections retain the final uncached double read. Fixed historical queries do not validate irrelevant later tails.

Shared historical inputs are keyed by snapshot digest; anchor proof entries also bind anchor event digest. AcceptedRef memo retains its full context keys. Dependency closure may extend an already validated vector only when every participating prefix and journal prefix monotonically extends it; different vectors fall back to the complete existing checker. No cache survives an operation or supplies caller-provided validation state.

## Risks / Trade-offs

- Writer lock or external bytes unavailable -> original load fails, projection remains unverifiable.
- Non-monotonic snapshot -> full original validation, not weaker assumptions.
- Mutable cached objects -> preserve private immutable replay/envelope identities and copy verdict dictionaries before use.
- Performance assertions -> count original replay work, compare canonical graph bytes, and record timings informationally rather than impose flaky CI wall-clock gates.

## Migration Plan

No event or receipt migration. Old public reader calls preserve their original default path.

## Open Questions

None for this issue.
