## ADDED Requirements

### Requirement: Frozen accepted inputs
The diagnosis SHALL read only parent-accepted, digest-verified acceptance, failed receipt, and change artifacts. The acceptance admission SHALL precede the failed receipts, and missing, corrupt, ambiguous, or stale references SHALL fail closed. No diagnosis request SHALL contain a hidden-cause field.

#### Scenario: Accepted failure
- **WHEN** a failed receipt cites an earlier accepted criterion and its observed cases conflict with that criterion
- **THEN** the diagnosis cites the exact source events and artifact hashes without changing any input bytes.

#### Scenario: Missing or altered source
- **WHEN** an artifact or journal digest is absent or inconsistent
- **THEN** the command returns a typed failure and no diagnosis.

### Requirement: Competing falsifiable explanations
The report SHALL use `arw.failure-diagnosis.v1`, include at least two distinct mechanisms, a discriminating probe with separate expected outcomes, nullable actual probe evidence, `kept`/`ruled_out`/`unresolved` judgments, and canonical sources for each judgment. Recurrence, opposing edits, and expectation mismatch SHALL be evidence-backed or unknown. Causality SHALL remain unknown.

#### Scenario: Three minimal cases
- **WHEN** independently accepted observations exhibit a sign reversal, unit mismatch, or sample mapping mismatch
- **THEN** the diagnostic step, without a hidden cause field, returns competing hypotheses and suppresses conclusions unsupported by available evidence.

### Requirement: Read-only handoff continuation
The command SHALL revalidate a prior accepted diagnosis and optional memory handoff through existing memory identity, source-link, and successor rules. A previously ruled-out mechanism SHALL not be recommended again without an explicit conflict signal.

#### Scenario: Two handoffs
- **WHEN** successive handoffs reference one accepted diagnosis chain
- **THEN** both resumes read the same canonical evidence and an old ruled-out probe stays suppressed.

#### Scenario: Optional extension absent
- **WHEN** no handoff is requested and the memory extension is unavailable
- **THEN** base diagnosis still runs; requesting the absent extension returns `CapabilityUnavailable`.
