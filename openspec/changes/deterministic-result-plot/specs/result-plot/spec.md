## ADDED Requirements

### Requirement: Exact accepted-source plots
The system SHALL consume AcceptedRef-backed CsvSelection and shared exact derivations, and SHALL record every plot value's derivation identity, expression, layer, series, category, units, scale, display and revision. Coordinates MUST use exact values.

#### Scenario: Same display different exact
- **WHEN** two distinct exact values round to the same label
- **THEN** distinct value identities and exact coordinates are retained and a swapped caption binding is rejected

### Requirement: Closed layer grammar
The system SHALL support one panel with point, line, bar, strip and rule layers, separate observation/aggregate/interval roles, explicit series and order for lines, checked pair identity, and deterministic stable-row jitter along a display axis only.

#### Scenario: Interleaved paired lines
- **WHEN** CSV rows interleave series or have missing or duplicate pair IDs
- **THEN** series are ordered independently or pairing fails explicitly; no CSV-order line is inferred

### Requirement: Explicit imported uncertainty
The system SHALL accept only precomputed lower/upper endpoints and require sampling unit, effective n source, missing policy, method, assumptions, CI confidence and SD ddof when applicable. Source resolution MUST NOT assert statistical recomputation.

#### Scenario: Invalid interval
- **WHEN** lower exceeds upper or SD/SE recomputation is requested
- **THEN** invalid_interval or unsupported is reported without silently correcting it

### Requirement: Separate checks and safe deterministic output
The system SHALL emit only safe XML SVG using a fixed palette and deterministic bytes. It SHALL separate integrity failures from named versioned advisory heuristics and human visual review, preserve raw_unavailable, and require real accepted visual evidence for publication-critical acceptance.

#### Scenario: Malicious label
- **WHEN** a label contains XML or TeX special characters
- **THEN** it is inert escaped text and SVG scripts, event handlers and external resources fail output validation

#### Scenario: Summary-only small sample
- **WHEN** a small continuous independent sample has no observation layer
- **THEN** arw.plot-heuristics.v1 emits advisory; category counts and raw_unavailable do not produce fabricated points

### Requirement: Additive research artifact lifecycle
Result plots SHALL use the existing parent-only immutable artifact lifecycle with independent IR/receipt schemas and Figure rendered_from source refs, IR hash and renderer identity. Existing schematic bytes MUST remain unchanged.

#### Scenario: Reproduce accepted plot
- **WHEN** an accepted result plot is inspected or reproduced
- **THEN** all output digests and retained source identities are checked and reproduction yields the accepted SVG bytes
