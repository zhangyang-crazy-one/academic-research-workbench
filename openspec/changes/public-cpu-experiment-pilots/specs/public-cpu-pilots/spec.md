## ADDED Requirements

### Requirement: Real bounded executions
The pilot SHALL retain three actual CPU runner outputs, contracts, parent provenance admissions, offline acceptance receipts and replay evidence without model calls.

#### Scenario: Three numerical pilots
- **WHEN** the inspected public runner executes after the initial contract freeze
- **THEN** raw observations, measured wall/CPU time and replay results are retained with digests

### Requirement: Failed version retention
The pilot MUST retain a failing v1 and a passing relaxed v2 without transferring v1 predeclaration to v2.

#### Scenario: Threshold relaxed after provenance acceptance
- **WHEN** v2 is frozen after the original provenance was accepted
- **THEN** v2 reports contradicted predeclaration and v1 remains identically replayable

### Requirement: Scoped proof and truthful costs
The report SHALL distinguish parent admission order from pre-data-collection timing and keep unmeasured costs unknown.

#### Scenario: Billing unavailable
- **WHEN** no monetary charge evidence exists
- **THEN** monetary cost is unknown and no zero-cost assertion is emitted
