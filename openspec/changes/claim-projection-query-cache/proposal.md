## Why

Issue #124 shows repeated full historical replay for every authenticated claim confirmation. Human review and hard-caption checks need bounded, responsive read-only projections without weakening provenance or changing graph bytes.

## What Changes

- Reuse original-validator run prefixes and project journal prefixes within one query only.
- Bind memoized inputs and anchor proofs to exact snapshot vectors and event hashes.
- Extend monotonically validated dependency closure within a query; reset for non-extending vectors.
- Preserve unavailable external proof, writer-lock failure, optimistic current-head checks and fixed historical replay.

## Capabilities

### New Capabilities
- `claim-query-cache`: bounded query-local reuse of validated immutable prefixes.

### Modified Capabilities
None.

## Impact

ClaimGraph read composition, anchor proof reader, AcceptedRef operation memo and regression fixtures. No persistent cache, canonical events, new dependencies or model calls. One PR for #124, independent of #125, awaiting owner review before merge.
