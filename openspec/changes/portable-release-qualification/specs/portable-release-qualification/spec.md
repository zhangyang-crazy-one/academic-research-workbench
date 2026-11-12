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
- **WHEN** command logs, stage bytes, executable permission bits or candidate identity change after qualification
- **THEN** creation, transfer and ordinary technical release checks reject the evidence

#### Scenario: Explicit supported interpreter outside PATH
- **WHEN** the selected compatible Python interpreter is outside PATH and PATH exposes only an older interpreter
- **THEN** the private installed-core probe passes the selected interpreter explicitly to the launcher without forwarding model credentials or imposing an exact Python version

#### Scenario: Large staged payload
- **WHEN** an installed build identity or integrity verifier hashes a large native payload
- **THEN** its SHA-256 matches the original bytes while hashing allocation is bounded independently of file size, and existing path, coverage and tamper checks are preserved
- **AND** no persistent digest trust cache or parent-process success flag replaces independent verification

#### Scenario: Invocation-local digest reuse
- **WHEN** one integration verification rebuilds a lock and validates its live audit manifests, or a standalone build, audit or build-identity observation runs
- **THEN** only private cache state owned by that invocation may reuse a digest; public entrypoints SHALL NOT accept caller cache state across invocations
- **AND** reuse requires a live regular-file descriptor and matching path/descriptor device, inode, size, mtime, ctime and mode before/after access; observed identity drift, replacement, unsafe paths and read errors reject the invocation even if replacement bytes match
- **AND** cached paths are rechecked before return, unusable inode/POSIX change-time identity requires independent reads, and subsequent public invocations hash independently

### Requirement: Optional deployment qualification
Specific execution-platform qualifications SHALL remain available as optional diagnostics, and historical Phase 7 receipts SHALL remain readable without being mandatory for the default formal release.

#### Scenario: Existing evidence reader
- **WHEN** a legacy qualified bundle is supplied
- **THEN** the existing reader verifies its original bindings without rewriting the historical receipt

#### Scenario: New stability package identity
- **WHEN** a 0.2.1 stage is inspected or an optional IntegrationLock is produced
- **THEN** package, plugin and wheel identities must agree on 0.2.1, including a valid optional plugin cache suffix
- **AND** retained 0.1.0 and 0.2.0 locks remain readable without rewriting them or treating them as fresh release qualification
