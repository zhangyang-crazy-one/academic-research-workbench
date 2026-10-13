## Why

#122 asks for source-bound review diagnostics and interoperable provenance to help authors inspect and revise manuscript arguments. Review patterns must remain advisory and cannot determine scientific acceptance.

## What Changes

- Add versioned ReviewConcern records bound to exact occurrences or claim revisions and historical snapshot vectors.
- Provide optional Argumentative Zoning labels and AMPERE-inspired proposition types without external corpus redistribution or predictive scores.
- Add explicit advisory diagnose/verify/replay and deterministic PROV JSON-LD export.
- Demonstrate original parent artifact admission and RO-Crate packaging/verification with existing crate digests unchanged.

## Capabilities

### New Capabilities
- `advisory-review-provenance`: bounded source-linked advisory concerns and PROV exchange.

### Modified Capabilities
None. No hard-check or qualify changes.

## Impact

Additive models/reader/CLI, schemas/docs/tests. No corpus download, trained classifier, new dependency or model invocation. Optional clickable manuscript view is deferred; core diagnostics/export are independent. One unmerged PR for #122.
