## ADDED Requirements

### Requirement: Content-bound paper realization
The system SHALL validate an outline, blueprint, or draft against retained source bytes, a current project narrative digest, and exact annotated spans before parent acceptance.

#### Scenario: Changed source bytes
- **WHEN** a sidecar names a digest or span that differs from the retained manuscript
- **THEN** acceptance fails with a stable source or span reason code.

#### Scenario: Stale narrative
- **WHEN** a realization names an earlier selected narrative digest
- **THEN** acceptance fails with `stale_narrative`.

#### Scenario: Heading-only function annotation
- **WHEN** new output binds an argument function only to explicit Markdown ATX or Setext heading syntax
- **THEN** admission fails with `narrative_heading_only`; a heading with body prose remains eligible for semantic review.
- **AND** historical accepted events retain their original reports and source-byte replay checks.

#### Scenario: Supplied source confinement
- **WHEN** an admission path supplies candidate source bytes directly
- **THEN** the same source-size budget and symlink-root confinement apply as for retained-file reads.

### Requirement: Deterministic mechanical completeness
The system SHALL require all six argument functions, a valid contribution-to-evidence-to-boundary graph, and no orphan claim. It SHALL check first occurrence order and require a reason for interleaving.

#### Scenario: Missing or disconnected function
- **WHEN** evidence is absent or a claim is orphaned
- **THEN** acceptance fails with a stable mechanical reason code.

#### Scenario: Explained interleaving
- **WHEN** a function appears out of order and its node contains a reason
- **THEN** the mechanical result remains admissible but a human review item is returned.

### Requirement: Scientific support stays reviewable
The system SHALL distinguish structural completeness from semantic evidence support and SHALL NOT infer unannotated post hoc explanations or freeze future conclusions.

#### Scenario: Negative result or short proof
- **WHEN** a short proof or negative result carries complete annotations and graph links
- **THEN** it is mechanically admissible without a minimum number of sections or positive findings.

#### Scenario: Survey evidence synthesis
- **WHEN** a survey maps literature synthesis or comparison evidence to the `other` evidence form with complete graph annotations
- **THEN** it is mechanically admissible without inventing an experiment, while semantic source support remains unknown.

#### Scenario: Unsupported certainty
- **WHEN** annotations assert claim support or boundary membership without human validation
- **THEN** the reported semantic status remains unknown and requests review.

### Requirement: Canonical admission and schema
The system SHALL publish the realization schema in the checked registry and enforce the check at paper outline, blueprint, draft, and accepted writing revision admission.

#### Scenario: Ordinary draft bypass
- **WHEN** a paper run submits a draft with an ordinary artifact kind or writing revision lacking valid realization
- **THEN** it cannot be accepted as paper prose.
