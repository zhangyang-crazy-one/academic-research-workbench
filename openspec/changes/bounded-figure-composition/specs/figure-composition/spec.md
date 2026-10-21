## ADDED Requirements

### Requirement: Independent bounded composition
The system SHALL accept an independent versioned composition with 2–4 ordered panels, finite physical sizes, row/column/grid cell ratios, stable encodings and per-panel exact source/renderer identities. Existing v1 contracts MUST remain unchanged.
#### Scenario: Same facts in two layouts
- **WHEN** three sourced panels use row and grid layouts
- **THEN** scientific contents and sources remain identical while IR/output digests differ and repeated rendering is deterministic

### Requirement: Canonical scientific object and child binding
The system MUST resolve each sequence/entity-graph source and accepted v1 child through existing ResearchBinding/AcceptedRef canonical verification, including selected-content hashes and historical prefix scope. Entity relations MUST retain explicit type, label and direction; identity reuse MUST NOT imply a transformation.
#### Scenario: Source or child is changed
- **WHEN** content bytes, source event digest, selected content or accepted child output is replaced
- **THEN** composition fails without accepting a new artifact

### Requirement: Safe editable SVG and honest typography
The compositor SHALL preserve accepted child geometry and scientific values, uniformly scale with no crop, namespace child IDs/internal references and reject scripts, external references, unsafe attributes and duplicate IDs. It SHALL retain editable text and report minimum physical font size. Shared child re-encoding and shared axes MUST be rejected when unsupported.
#### Scenario: Unsafe or conflicting child
- **WHEN** an injected child contains unsafe SVG or incompatible shared semantic encoding
- **THEN** rendering fails rather than modifying and retaining its accepted digest

### Requirement: Parent admission and independent visual evidence
The system MUST reuse parent-owned admission and exact composition IR/output visual-review bindings. Publication-critical compositions require semantic and visual PASS. Mechanical determinism MUST NOT establish visual PASS.
#### Scenario: Publication without review
- **WHEN** a valid publication-critical composition has no exact accepted visual review
- **THEN** qualification is blocked and visual status remains unavailable
