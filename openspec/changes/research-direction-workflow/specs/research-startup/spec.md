## ADDED Requirements

### Requirement: Core project-bound startup
The system SHALL expose core project initialization and research start/status/resume without memory retrieval or a model harness. Broad directions SHALL enter scoping without an invented narrative or completed research stage.

#### Scenario: Fresh direction
- **WHEN** a user starts a broad direction in an explicitly selected clean project directory
- **THEN** one stable project identity and one canonical initialized run bind the retained intent, and status distinguishes scoping intent from RUNNING lifecycle and initialized workflow stage

### Requirement: Exact interruption recovery
Startup SHALL retain exact requests and committed steps, resume identical partial initialization safely, and reject project/run/input conflicts or corrupt history. Paper operations SHALL use existing narrative selection and stale guards.

#### Scenario: Interrupted or moved project
- **WHEN** startup stops after a durable step or the complete project moves to another directory
- **THEN** resume uses the same identity and request without duplicate acceptance, and explicit mismatched identity or changed input is rejected

#### Scenario: Killed receipt writer
- **WHEN** initialization is killed while writing a prepared or committed receipt
- **THEN** only complete fsynced bytes are published exclusively as a final receipt, and resume uses the retained exact request without duplicate initialization events
- **AND** unpublished fragments remain non-authoritative and preserved; malformed published receipts and unsafe staging paths are rejected

### Requirement: Layered readiness
Status SHALL independently report core integrity, project/stage, material availability, selected operation checks, executor readiness and scientific admission; unchecked operations SHALL remain not_evaluated.

#### Scenario: Unconfigured execution
- **WHEN** editable integrity is UNVERIFIED, legacy routing is BLOCKED, and no model or retrieval provider was checked
- **THEN** valid local scoping administration remains available without claiming experiments run or scientific validation passed
