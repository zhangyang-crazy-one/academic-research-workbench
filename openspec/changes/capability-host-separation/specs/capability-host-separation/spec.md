## ADDED Requirements

### Requirement: Provider-neutral core route
The system SHALL expose a versioned provider-neutral `route --core --json` report. It SHALL distinguish staged integrity, editable checkout verification, provider presence, unresolved configuration, and execution adapter qualification. It SHALL not claim a Claude or generic execution adapter exists.

#### Scenario: Local core route without host qualification
- **WHEN** a complete staged bundle is inspected without Codex host qualification or model credentials
- **THEN** the core route reports staged integrity and bounded provider observations without granting execution adapter authority.

#### Scenario: Editable source checkout
- **WHEN** the route is invoked from an explicit editable source checkout
- **THEN** it reports `UNVERIFIED` rather than staged integrity PASS.

### Requirement: Integrity before installed operations
Installed ARW commands and Python MCP entry points SHALL reject a drifted or incomplete staged bundle before operating. Verification SHALL cover the live closed inventory, build identity and payload digests, first-party wheel, source/build evidence, candidate and license inventory relationships, and SBOM. Host canary, Codex executable version, and model credentials SHALL not be prerequisites for the local core.

#### Scenario: Drifted stage
- **WHEN** an inventoried payload, candidate wheel, or required stage file drifts from its bound evidence
- **THEN** installed operations reject the stage before doing work.

### Requirement: Separate execution authority
The legacy route schema and IntegrationLock v2 SHALL remain the only authority for Codex Phase 4 execution dispatch. Core-route PASS SHALL NOT be converted into execution permission.

#### Scenario: Core passes while host remains unqualified
- **WHEN** staged core integrity passes but Codex host qualification is absent
- **THEN** local core operations remain available within their own bounds and Phase 4 dispatch remains blocked.

### Requirement: Explicit file authority
Local file operations SHALL continue to require explicit allowed roots and bounded file access. Provider presence SHALL NOT imply file authorization.

#### Scenario: Path outside an allowed root
- **WHEN** a local file operation requests a path outside its explicitly allowed roots
- **THEN** the operation rejects the path even when the provider is present and staged core integrity passes.
