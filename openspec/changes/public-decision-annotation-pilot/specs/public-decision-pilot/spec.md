## ADDED Requirements

### Requirement: Independent human ground truth
The pilot MUST retain ten pinned public source locators and leave actual human labels pending until the owner annotates them.

#### Scenario: Unannotated material
- **WHEN** the source kit is prepared without human annotations
- **THEN** no human disposition or agreement count is fabricated and readiness remains pending

#### Scenario: Owner annotates through conversation
- **WHEN** the owner supplies actual responses and a selected option and requests CSV transcription
- **THEN** the CSV retains their annotation text, selected option, identity, response locator and recording time without inventing source-history labels

#### Scenario: Owner response is not historical evidence
- **WHEN** a row contains owner adoption or reporting instructions
- **THEN** validation counts it as a recorded owner annotation, does not declare historical comparison ready, and rejects encoding the same row as source-history status/reason ground truth

### Requirement: Source scope and unknown reasons
The pilot SHALL distinguish source metadata, machine encoding, human status and human reason, with explicit unknown where the annotator cannot verify a claim.

#### Scenario: Deferred proposal
- **WHEN** a source says deferred without an explicit abandonment decision
- **THEN** the protocol does not infer abandonment or a motive

### Requirement: Complete pilot after annotation
The pilot SHALL compare all ten annotated decisions with exported narrative trails and retain two rounds of real handoff/resume before reporting completion.

#### Scenario: Pending annotation
- **WHEN** one or more annotations are absent
- **THEN** full pilot acceptance remains incomplete
