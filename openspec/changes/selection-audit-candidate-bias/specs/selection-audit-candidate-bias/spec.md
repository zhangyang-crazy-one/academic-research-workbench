## ADDED Requirements

### Requirement: Bound retained candidate evidence to canonical provenance
The system SHALL export an offline, typed, bounded selection receipt only from one healthy parent run's accepted query plan, retrieval input, and candidate ledger, after normative ARS replay, with the expected run head and each accepted event, manifest, and content digest recorded.

#### Scenario: Stale, changed, or cross-run reference
- **WHEN** the head, event, manifest, or retained bytes differ or an artifact is not uniquely accepted in that run
- **THEN** export or receipt replay fails closed without modifying the run.

#### Scenario: Missing bundled ARS
- **WHEN** the installed plugin lacks the bundled normative builder
- **THEN** the optional selection export is unavailable while core replay remains usable.

### Requirement: Distinguish retrieval, selection, and reading
The system SHALL report query, pool, raw rank, family/version deduplication, selected candidate families, and explicit readings separately. It SHALL NOT infer reading from final citations or selected candidates.

#### Scenario: No complete reading log
- **WHEN** no accepted complete reading trace exists
- **THEN** actual reading coverage, round reach, and stop status remain unknown.

#### Scenario: Explicit reading log
- **WHEN** a same-run accepted trace names a selected family, member raw hit, round, order, and author assertion
- **THEN** export records those exact fields and rejects stale or out-of-pool positions.

### Requirement: Deterministic paired sensitivity replay
The system SHALL replay a fixed self-authored synthetic pool in original, support-first, and oppose-first order with an identical reading budget, preserving each scenario and reporting read-set and direction differences.

#### Scenario: Early stop and unread opposition
- **WHEN** the fixed fixture stops after two reads
- **THEN** opposite first ordering can expose a direction change while the original and unread pool remain visible, even though the original synthetic citation has a valid exact byte locator.

### Requirement: Sampling uncertainty stays explicit
The system SHALL remain descriptive without a verified design and known inclusion, selection, and round-reach probabilities. It SHALL NOT invent propensities or infer scientific stance from publication metadata.

#### Scenario: Synthetic finite SRS
- **WHEN** a separate enumerated synthetic SRS example has four items and two reads
- **THEN** it shows the six draws, inclusion probability 1/2, and recomputable estimator, labeled as a teaching example.

#### Scenario: Zero or unknown coverage
- **WHEN** the complete trace has zero reads or any stance is unknown
- **THEN** direction is unknown or bounded, and no population correction is emitted.
