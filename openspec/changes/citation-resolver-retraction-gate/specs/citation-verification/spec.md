## ADDED Requirements

### Requirement: Versioned reference identity and per-use role

ARW SHALL represent reference identity in a strict versioned record and SHALL evaluate each citation use with its declared role and claim. PDF extraction SHALL reuse this record rather than define another reference identity.

#### Scenario: Same retracted paper has distinct uses

- **WHEN** a retracted work supports one claim and is the research object for another
- **THEN** the supporting use is blocked and the research-object use is routed to human review without automatic waiver or ordinary PASS

### Requirement: Deterministic, offline replayable provider checks

ARW SHALL parse bounded response bytes from Crossref, OpenAlex, DBLP and arXiv into versioned immutable check receipts containing the response SHA-256, query, parser version, observation time and result. Network lookup SHALL be disabled by default and require explicit opt-in. Tests SHALL use fixture or mock responses only.

#### Scenario: Offline recheck

- **WHEN** retained provider bytes and receipt are supplied for replay
- **THEN** the same result is obtained or digest/contract mismatch is rejected without contacting the provider

### Requirement: Distinct lookup states and conservative matching

ARW SHALL distinguish verified, not_found, retracted, unknown, unavailable and ambiguous. It SHALL not infer not_found from timeout, malformed data, incomplete coverage or multiple candidate identities.

#### Scenario: One index is unavailable

- **WHEN** other providers have no match and one applicable provider is unavailable
- **THEN** the aggregate remains unavailable or unknown, never not_found

### Requirement: Append-only retraction gate and contamination signals

Each recheck SHALL append a new receipt. An earlier blocking result SHALL remain visible after a later PASS until an explicit parent reconciliation. Contamination flags SHALL be derived only from conclusive matching receipts; unavailable and ambiguous outcomes SHALL remain omissions/unknown.

#### Scenario: Supporting citation disappears and later reappears

- **WHEN** a supporting reference receives not_found and a subsequent verified check
- **THEN** the earlier blocker remains in the gate history and no silent PASS occurs

#### Scenario: One provider misses a work that another verifies

- **WHEN** one explicit batch contains a not_found receipt and a verified receipt from another applicable provider
- **THEN** the batch is verified and the single-provider miss creates no historical blocker

### Requirement: Resolver and self-report conflict observations

The citation gate SHALL derive contamination booleans using the existing contamination contract, retain conflicts with explicitly supplied ARS self-report values, and bind canonical observations to parent-accepted immutable entry and resolver evidence. Resolver outcomes SHALL remain observations and SHALL NOT rewrite passport fields, human annotations, source-acquisition state or scientific truth. Self-reported values SHALL NOT override the resolver gate.

#### Scenario: Self-report disagrees in either direction

- **WHEN** an accepted conclusive not_found receipt disagrees with a false self-reported unmatched value, or a verified receipt disagrees with a true value
- **THEN** the canonical gate retains both booleans and the receipt digest in a conflict observation, with both immutable inputs in gate evidence

#### Scenario: Degraded, missing and manual evidence

- **WHEN** a provider is unavailable, unknown, ambiguous or unchecked, or an ARS entry omits a lookup signal
- **THEN** no contrary boolean is invented, unavailability is attributed as api_degraded, and manual notes and source/retrieval state remain unchanged

#### Scenario: Historical conflict and legacy gate

- **WHEN** a later receipt agrees with self-report after an earlier conflict, or no ARS entry was supplied for a legacy reference
- **THEN** retained historical conflicts remain visible, while the legacy gate remains valid without inferred self-report, and all checks replay without network access
