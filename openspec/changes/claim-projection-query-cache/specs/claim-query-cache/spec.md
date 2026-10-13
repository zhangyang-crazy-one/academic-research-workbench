## ADDED Requirements

### Requirement: Reuse only within one validated query
The projection SHALL reuse original-validated prefixes only within one query and bind all reads to exact roots, manifest digests, revisions, heads and held-lock scope.

#### Scenario: Many confirmations
- **WHEN** one query projects 60 authenticated anchors
- **THEN** original parent replay work does not grow quadratically and graph bytes equal the uncached result

### Requirement: Preserve refusal semantics
Caching MUST NOT promote unavailable or changed external proof or hide participating head changes.

#### Scenario: Sibling writer or changed source
- **WHEN** a participating sibling is locked or external proof changes before a subsequent query
- **THEN** original refusal/unverifiable behavior is retained with no cross-query cache hit

### Requirement: Exact historical closure
A historical sub-prefix SHALL retain the original dependency closure and bounded validation; non-extending vectors MUST receive complete checking.

#### Scenario: Fixed older snapshot
- **WHEN** an explicit valid historical vector is queried after unrelated later events
- **THEN** historical bytes remain unchanged and future/out-of-prefix dependencies are refused
