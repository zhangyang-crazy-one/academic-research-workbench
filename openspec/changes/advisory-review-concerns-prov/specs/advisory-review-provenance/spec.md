## ADDED Requirements

### Requirement: Advisory-only diagnostics
Concerns MUST remain advisory with no scores and no changes to scientific hard checks or qualify decisions.

#### Scenario: Concerns generated
- **WHEN** review patterns suggest a clarification
- **THEN** only an advisory record is returned and canonical source files and hard-check output are unchanged

### Requirement: Exact replayable targets
Every concern SHALL bind a concrete occurrence or exact claim revision and a full historical snapshot validated through original provenance readers.

#### Scenario: Target bytes changed
- **WHEN** manuscript bytes or target claim digest differs from its saved binding
- **THEN** concern target replay is refused rather than treated as current

### Requirement: Optional rhetorical annotations and corpus boundary
Argumentative Zoning SHALL be optional and external corpora MUST NOT be redistributed before license review.

#### Scenario: No classifier or corpus
- **WHEN** a concern is generated without explicit rhetorical annotation
- **THEN** its zone remains absent and no empirical classifier accuracy is claimed

### Requirement: Immutable crate packaging
Exported PROV JSON-LD SHALL be selected through original parent artifact and RO-Crate contracts without rewriting an existing crate.

#### Scenario: Additional provenance crate
- **WHEN** PROV JSON-LD is accepted and selected into a new crate
- **THEN** original structure/byte/source checks validate it and the previous crate digest stays unchanged
