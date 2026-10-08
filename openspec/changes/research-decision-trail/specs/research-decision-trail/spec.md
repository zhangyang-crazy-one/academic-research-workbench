## ADDED Requirements

### Requirement: Deterministic source-linked trajectory
The system SHALL export a read-only project paper trajectory from the validated narrative event chain. Every selected or proposed route SHALL have a stable source event digest, disposition (`kept`, `superseded`, `abandoned`, or `unknown`), and any explicitly recorded successor or reason. An unrecorded motive SHALL remain unknown.

#### Scenario: Approved replacement
- **WHEN** an exact proposed replacement is approved
- **THEN** the previous selected route is `superseded`, points to the approved successor, and cites the proposal reason and approval event.

#### Scenario: Pending branch
- **WHEN** a route has only been proposed
- **THEN** the selected route remains `kept` and the proposal's disposition is `unknown`.

#### Scenario: Historical view
- **WHEN** a caller selects an older event sequence from a valid history
- **THEN** the system validates the full current chain and deterministically projects only events through that sequence, naming both the view head and full history head.

### Requirement: Explicit withdrawal without successor
The parent writer SHALL allow an author-confirmed withdrawal of only the current pending proposal by exact digest, with bounded author ID and reason. Withdrawal SHALL append one event, leave the selected plan active, and allow a later proposal. It SHALL NOT imply a successor where none was recorded.

#### Scenario: Withdrawn branch
- **WHEN** a pending proposal is withdrawn and a new proposal is later submitted
- **THEN** the withdrawn proposal is `abandoned` without a successor, and the later proposal has its own independent event source.

### Requirement: Fail closed and bound output
The exporter SHALL distinguish an unregistered non-paper project from a registered paper project missing selection. It SHALL reject corrupt history, stale expected heads, invalid sequence requests, unsafe paths, and output above declared limits. It SHALL NOT return an empty trajectory in place of an error.

#### Scenario: Corrupt tail or stale head
- **WHEN** history has a corrupt tail or the expected head differs from the current head
- **THEN** export fails with `corrupt_history` or `stale_narrative` and emits no partial choices.

#### Scenario: Explicit run relations
- **WHEN** the caller supplies one canonical paper run
- **THEN** the export includes only accepted artifact references and successor links explicitly recorded in that run's healthy journal, names their source events, and does not attribute unlinked records to a narrative route.

### Requirement: Continuation summary
Paper handoff and resume SHALL expose the same current route, abandoned routes, and unresolved pending choice derived from current history, with source digests. Superseded and withdrawn routes SHALL NOT become suggested next actions solely because they appear in history. Non-paper continuation SHALL remain applicable without a paper narrative.

#### Scenario: Two continuations from unchanged history
- **WHEN** a paper handoff is read and resumed twice with no intervening history change
- **THEN** both responses carry identical current and abandoned choices and the same history head.
