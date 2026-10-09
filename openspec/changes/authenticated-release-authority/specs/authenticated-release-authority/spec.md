## ADDED Requirements

### Requirement: Independent exact-candidate authority
Formal publication SHALL require cryptographically verified GitHub-hosted owner authority from an original main workflow_dispatch. The signed strict predicate MUST bind repository, source SHA, version/tag, candidate run/artifact, qualified bundle, draft release/asset and all publication subject digests.

#### Scenario: Candidate substitution
- **WHEN** a wheel, SBOM, source SHA, archive, artifact ID or draft asset differs from the signed declaration
- **THEN** publication fails closed

#### Scenario: Unauthenticated approval
- **WHEN** approval is only a JSON PASS or an unverified assertion
- **THEN** the formal gate refuses publication

#### Scenario: Owner rerun
- **WHEN** an authority run is rerun or triggered by another actor
- **THEN** it cannot establish a new release declaration

### Requirement: Accountable permission declaration
The authority SHALL require the actual intended use and distribution class and validate pinned component licenses and preserved notices. Unknown use and unsupported commercial permission MUST remain blocked. Historical declarations MUST remain immutable.

#### Scenario: Missing declaration
- **WHEN** the user has not supplied intended use
- **THEN** technical preparation can proceed but authority signing and publication remain blocked

### Requirement: Genuine technical qualification
Signing SHALL verify original main CI artifact attestations and the qualified bundle's actual Phase 7 stage, lock and canary. Qualification MUST preserve original CI subjects and build evidence byte-for-byte. Technical-only validation MUST NOT authorize publication.

#### Scenario: Rebuilt candidate
- **WHEN** a qualified archive replaces the original CI wheel or build evidence
- **THEN** authorization refuses the transfer

### Requirement: Controlled draft publication
Publication SHALL reverify live exact IDs and signatures, upload only bound publication subjects, remove only the bound intermediate asset, and publish the exact existing draft. Conflicting or unrelated draft assets MUST block publication.

#### Scenario: Interrupted upload retry
- **WHEN** an already uploaded publication asset has the same bound bytes
- **THEN** publication may reuse that asset without replacing it

### Requirement: Explicit native model policy
Fresh-home Codex qualification SHALL select gpt-6.1-sol with high reasoning explicitly and use existing native platform authentication. Strict test subprocesses MUST forward only enumerated qualification inputs and exclude credentials.

#### Scenario: Fresh configuration directory
- **WHEN** a qualification home has no user model settings
- **THEN** both native dispatch types still select gpt-6.1-sol/high
