## ADDED Requirements

### Requirement: Harness-independent formal release
Formal release SHALL accept retained installed-core evidence without requiring a named harness, model, host launcher, exact host version, integration lock or paid model invocation. Observed tool versions SHALL be informational.

#### Scenario: No model platform installed
- **WHEN** the candidate installs and its core route, bounded artifact inspection, canonical initialization, status and replay probes pass
- **THEN** technical publication checks pass without Codex, Pi, Claude or model credentials

#### Scenario: Platform changes
- **WHEN** a user selects another working harness or updates its version
- **THEN** formal package release eligibility is not invalidated by a platform tuple mismatch

### Requirement: Transferable candidate evidence
The verifier SHALL bind actual command outputs, installed stage and candidate wheel/build evidence to the reviewed source, reject malformed, failed, unsafe or changed receipts, and retain original CI subjects and independent publication authority.

#### Scenario: Evidence mutation
- **WHEN** command logs, stage bytes or candidate identity change after qualification
- **THEN** creation, transfer and ordinary technical release checks reject the evidence

### Requirement: Optional deployment qualification
Specific execution-platform qualifications SHALL remain available as optional diagnostics, and historical Phase 7 receipts SHALL remain readable without being mandatory for the default formal release.

#### Scenario: Existing evidence reader
- **WHEN** a legacy qualified bundle is supplied
- **THEN** the existing reader verifies its original bindings without rewriting the historical receipt
