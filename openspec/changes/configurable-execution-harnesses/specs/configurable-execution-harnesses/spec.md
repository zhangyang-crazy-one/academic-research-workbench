## ADDED Requirements

### Requirement: Explicit extensible harness selection
ARW SHALL select configured named harnesses by assignment, role or default. Native platforms, external command drivers and API transports MUST use the common parent scheduler. Unknown selectors and conflicting native/API options MUST fail before dispatch.

#### Scenario: Non-Codex selection
- **WHEN** an assignment selects an external command or API harness
- **THEN** no Codex installation or Codex-specific identity field is required for that transport

### Requirement: Controlled credentials and model configuration
API credentials SHALL be resolved only from explicitly named runtime environment variables or a selected local `.env`. Secret values MUST NOT enter model input, canonical configuration, receipts or diagnostics. Non-Codex models MUST follow their explicit platform configuration.

#### Scenario: Missing credential
- **WHEN** a selected API harness requires an unavailable credential
- **THEN** dispatch fails before any HTTP request and identifies the missing variable without exposing values

### Requirement: Bounded isolated execution and parent admission
Each harness SHALL bind the exact assignment and attempt, use a fresh task context, enforce bounded output and preserve parent-owned timeout/cancellation. Proposals and artifacts MUST pass the existing strict identity, digest, nonce, confinement and acceptance checks.

#### Scenario: Forged proposal or escaped artifact
- **WHEN** a harness returns another attempt identity or an escaping artifact path
- **THEN** the parent refuses admission and cannot mutate scientific provenance

#### Scenario: Oversized or stalled worker
- **WHEN** output exceeds the frozen limit or a worker exceeds its deadline
- **THEN** the parent terminates the local worker and records the actual terminal outcome without claiming remote inference cancellation

### Requirement: Platform-neutral versioned evidence
Host identity v2 SHALL represent any configured harness with exact configuration and retained evidence bindings. Original v1 Codex identity bytes and replay MUST remain supported. Capability proof MUST determine independence, rather than the selected harness name.

#### Scenario: Legacy replay
- **WHEN** an existing run contains a v1 Codex identity receipt
- **THEN** its original digest and canonical replay remain unchanged

#### Scenario: API identity
- **WHEN** an API worker supplies valid retained mapping and isolation evidence
- **THEN** parent identity acceptance and panel preparation use the platform-neutral receipt without inventing a Codex version
