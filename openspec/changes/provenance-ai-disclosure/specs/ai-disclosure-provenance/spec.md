## ADDED Requirements

### Requirement: Provenance inventory
The reader SHALL cover accepted material independent of claim anchors and retain observed, human-declared and unknown coverage with exact original references.

#### Scenario: Imported draft without history
- **WHEN** a manuscript, figure or code artifact has no participation receipt or declaration
- **THEN** its involvement is unknown and no human-authorship label is inferred

### Requirement: Receipt integrity and explicit usage
The reader MUST validate original accepted receipt/target bindings and preserve imported, external editing, mixed, grammar-only, AI-drafted and human-edited AI histories distinctly.

#### Scenario: Mismatched receipt target
- **WHEN** participation evidence does not bind the exact accepted target bytes
- **THEN** it cannot supply observed involvement

### Requirement: Frozen venue drafts
Drafts SHALL bind a dated versioned policy snapshot and exact provenance prefixes and remain byte-replayable with human final approval pending.

#### Scenario: Policy updated
- **WHEN** a new venue policy is provided after an earlier draft
- **THEN** the old draft replays with its embedded old snapshot and does not acquire a fabricated approval
