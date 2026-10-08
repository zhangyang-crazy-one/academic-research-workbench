## ADDED Requirements

### Requirement: Parent-owned contract admission
The system SHALL accept a contract digest through the existing parent writer transaction and SHALL treat a published contract file without an accepted event as having no timing authority.

#### Scenario: Freeze and stale retry
- **WHEN** a parent freezes a valid contract at the current revision
- **THEN** one hash-chained event records its digest and version; a duplicate command or stale revision cannot append another event.

#### Scenario: Invalid successor
- **WHEN** a successor names a missing, different-claim, forked, or wrong-version predecessor
- **THEN** the parent rejects it without an acceptance event.

### Requirement: Journal-derived timing
Evaluator 1.2.0 SHALL derive contract and provenance admission order only from a validated run journal. Caller-supplied timestamps and sequences SHALL NOT strengthen predeclaration. An altered journal or an accepted event with mismatched immutable bytes SHALL fail closed.

#### Scenario: Normal, reverse and absent order
- **WHEN** both matching admission events exist
- **THEN** the result uses their journal sequences and identifies the evidence as parent acceptance order only.
- **WHEN** one event is absent
- **THEN** the timing remains unverified.

#### Scenario: Post hoc successor
- **WHEN** a relaxed successor contract is accepted after a provenance admission
- **THEN** its own timing is contradicted, even if its predecessor was accepted earlier; old failed and new passed results replay independently.

### Requirement: Historical receipt integrity
The system SHALL replay stored evaluator receipts using their recorded evaluator version and preserve canonical bytes.

#### Scenario: Old receipt
- **WHEN** a 1.0.0 or 1.1.0 receipt is loaded after the new event reader is installed
- **THEN** its previous arithmetic and digest remain replayable.
