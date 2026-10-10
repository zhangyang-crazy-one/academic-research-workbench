## ADDED Requirements

### Requirement: Coherent distribution version
The Python package, platform plugin manifests, CodeMeta and MCP identity SHALL report release 0.2.0. Launcher health SHALL require the matching installed package version.

#### Scenario: Installed successor
- **WHEN** a 0.2.0 wheel is installed for the 0.2.0 plugin
- **THEN** health and version probes succeed and report 0.2.0

### Requirement: Explicit retained runtime compatibility
Runtime bindings SHALL support retained 0.1.0 and current 0.2.0 stages without rewriting old bytes. Staged pyproject, plugin base version and wheel METADATA MUST agree.

#### Scenario: Mixed version stage
- **WHEN** a stage combines a 0.2.0 plugin with a 0.1.0 wheel
- **THEN** qualification rejects the mismatch

#### Scenario: Legacy stage
- **WHEN** a valid retained 0.1.0 stage is read
- **THEN** its original runtime binding remains readable
