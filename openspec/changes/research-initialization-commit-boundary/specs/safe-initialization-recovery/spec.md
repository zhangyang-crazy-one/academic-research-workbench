## ADDED Requirements

### Requirement: Missing committed history is refused
Research status and resume MUST refuse missing committed history without writing replacement events or reporting healthy readiness.

#### Scenario: Accepted record loses first segment
- **WHEN** a revision-2 run has an accepted artifact and its first journal segment disappears
- **THEN** status and resume reject damaged history, preserve all remaining bytes, and do not recreate revision 1

### Requirement: Partial recovery has positive transaction evidence
Empty partial initialization SHALL resume only with exact durable prepared transaction evidence and safe storage; writer entry MUST seal initialization before later changes.

#### Scenario: Initializer is killed before or after first event
- **WHEN** a new initialization is interrupted at a durable boundary
- **THEN** resume retains the same identity/request and exactly one first event

#### Scenario: Another parent accepts material after interrupted initialization
- **WHEN** the first event is durable but completion sealing was interrupted
- **THEN** the parent writer seals completion before accepting later material, and subsequent history loss is refused

### Requirement: Legacy and unsafe boundaries fail truthfully
Intact legacy runs SHALL remain readable; absent, forged, changed or unsafe transaction evidence MUST NOT authorize history reconstruction.

#### Scenario: Old manifest-only run lacks transaction evidence
- **WHEN** a legacy run manifest remains but its canonical journal is absent
- **THEN** automatic initialization recovery is refused and the scene is preserved

#### Scenario: Transaction is changed or symlinked
- **WHEN** a prepared or completed transaction differs from the exact request or is a symlink
- **THEN** status/resume reject it without modifying canonical or transaction bytes
