## Why
Accepted experiment data cannot yet be rendered as reproducible result figures. Add a single-panel result plot contract that consumes the shared accepted-reference and exact numeric core while retaining provenance and human visual review.

## What Changes
- Add layered point, line, bar, strip and endpoint-rule plots with stable CSV identity, explicit ordering, pairing and exact coordinates.
- Bind caption numeric occurrences to specific plot values or metadata and separate integrity, statistical verification, advisory heuristics and visual review.
- Add deterministic safe SVG rendering and an additive receipt integrated with the existing parent artifact lifecycle.

## Capabilities
### New Capabilities
- `result-plot`: Declarative result plots and accepted Figure provenance.
### Modified Capabilities
None. Existing schematic IRs, receipts and renderer bytes remain unchanged.

## Impact
Kernel result_plot contracts, research-artifact extension dispatch/rendering/policy, additive schemas, targeted tests and docs. No new runtime dependencies, arbitrary code execution, TeX exporter, facets or box marks.
