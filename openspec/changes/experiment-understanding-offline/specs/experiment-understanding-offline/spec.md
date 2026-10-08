## ADDED Requirements

### Requirement: Frozen independent four-factor tasks
The system SHALL provide three original, versioned four-binary-factor CPU
arithmetic surrogate tasks with frozen seeds, eight approved observations,
sixteen hidden responses, observation budget, scoring scales and stopping
rules. It SHALL keep the existing 32-case evaluation corpus unchanged and SHALL
NOT redistribute unreviewed external benchmark data.

#### Scenario: Public task input
- **WHEN** an operator prepares one task input
- **THEN** the output contains its eight approved rows and task/observation
  digests, but no hidden response table, seed or formula.

### Requirement: Distinct all-attempt scoring
The offline scorer SHALL separately report true selection regret, conditional
effect error, pair-interaction error and full-table delivery rate. It SHALL
retain predeclared missing slots and extra submissions in all-attempt counts,
assign zero bounded metric credit to undelivered attempts, and leave their raw
errors null. It SHALL also report delivered-only errors and quality.

#### Scenario: Correct choice with wrong effects
- **WHEN** an attempt chooses the true best configuration but predicts wrong
  responses for other configurations
- **THEN** selection regret is zero while conditional and pair-interaction
  errors are positive.

#### Scenario: Incomplete or invalid delivery
- **WHEN** a slot is absent, a response row is missing or repeated, an
  unapproved observation is used, a budget is exceeded, or a value is nonfinite
- **THEN** the receipt retains that attempt with typed reasons, zero delivery
  and bounded quality, and null raw errors.

### Requirement: Shared-data baseline and receipt replay
The system SHALL fit a deterministic pair-effect ridge baseline from exactly
the same eight observations. It SHALL bind exact fixture and attempt bytes in a
canonical receipt and reproduce that receipt from retained inputs. Missing cost
fields SHALL be unavailable rather than zero. Until a separately authorized
same-model comparison occurs, live comparison SHALL be `not_measured`.

#### Scenario: Offline acceptance workflow
- **WHEN** an operator runs `prepare`, `ridge`, `score`, and `verify` over the
  frozen fixture and retained attempts
- **THEN** the scorer reports three delivered ridge rows, each of four axes,
  and verification reproduces the exact receipt bytes.
