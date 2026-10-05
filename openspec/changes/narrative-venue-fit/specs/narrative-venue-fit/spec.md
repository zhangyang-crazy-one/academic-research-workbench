## ADDED Requirements

### Requirement: Read-only accepted manuscript fit
The system SHALL produce an advisory fit report for an accepted manuscript and selected project narrative without modifying an artifact, acceptance decision, narrative plan, or ledger. With a run root and bundled venue ID, it SHALL select the latest accepted draft and freeze the matching bundled venue profile. Explicit accepted artifact and reviewed profile inputs SHALL remain available.

#### Scenario: Minimal bundled target
- **WHEN** the author invokes `arw writing narrative-fit --run-root R --target VENUE_ID` for a paper run with an accepted draft and bundled target
- **THEN** the report binds the accepted event and content digests, selected narrative digest, bundled profile version and exact profile hash, and marks untyped natural-language venue requirements unknown.

#### Scenario: Unknown target or missing draft
- **WHEN** the target is absent from the bundled registry or the run has no accepted draft
- **THEN** capture returns an actionable error without changing the run.

### Requirement: Distinct bounded assessment layers
The system SHALL separate official hard requirements, narrative and venue structural expectations, promoted empirical patterns, and optional reviewer judgment. A natural-language rule SHALL be unknown unless an attributed reviewed typed predicate supports a bounded deterministic check. Page counts SHALL use actual accepted PDF bytes; a listed-marker search SHALL NOT assert comprehensive anonymity. An unselected empirical layer SHALL be `not_evaluated`.

#### Scenario: Typed and untyped rules
- **WHEN** a reviewed profile contains a typed exact heading predicate, a page limit without an accepted PDF, and an untyped prose requirement
- **THEN** the report gives a bounded heading observation, marks page count `not_evaluated`, and leaves the prose requirement unknown.

#### Scenario: Proposed structural failure
- **WHEN** an exact accepted manuscript source is paired with a proposed realization containing an orphan claim
- **THEN** the structural layer reports a stable mechanical failure without altering canonical acceptance.

#### Scenario: Promoted venue heuristic
- **WHEN** a promoted heuristic applies to the target venue and domain with a reviewed typed match
- **THEN** the empirical layer reports its bounded match, promotion provenance, supporting/counterexample/unknown evidence, and no acceptance probability; a run-scoped heuristic from another run is excluded.

### Requirement: Frozen replay and independent freshness
Capture SHALL freeze exact manuscript, realization, venue profile, predecessor and evidence bytes, and any accepted PDF used. Offline replay SHALL verify those bytes and recompute structural validation and PDF page count to produce the same report bytes after active state changes. Freshness SHALL be a separate comparison of active narrative/profile/heuristic state and an explicitly supplied date against the profile review date.

#### Scenario: Offline repeat and tamper
- **WHEN** a saved snapshot is replayed after the active narrative or profile changes
- **THEN** its report bytes are identical; when frozen content or structural result is altered, replay fails integrity validation.

#### Scenario: Profile review due
- **WHEN** the explicit as-of date is after the frozen venue profile review date but the active profile bytes are unchanged
- **THEN** freshness reports `needs_recheck` separately from the frozen fit report.

### Requirement: Optional judgment provenance
Optional human or model-assisted judgment SHALL bind the frozen input digest. Model-assisted judgment SHALL name model, provider and prompt version. The fit command SHALL NOT invoke a model, and judgment SHALL NOT change the official, structural, or empirical assessments.

#### Scenario: Judgment enabled or absent
- **WHEN** no judgment is supplied
- **THEN** the report is complete with `judgment_status=not_supplied`.
- **WHEN** a correctly bound judgment is supplied
- **THEN** it appears with provenance while the first three layers remain byte-equivalent.

### Requirement: Explicit unbound public evidence
The system SHALL offer an explicit `--without-selected-narrative` mode for runs without a selected narrative binding, requiring an accepted artifact ID. It SHALL preserve the selected-narrative snapshot contract and capture public inputs using a separate snapshot schema. It SHALL distinguish retained capsule hashes from external reviewed PDF hashes, mark narrative structure UNKNOWN/not_evaluated, and keep unpromoted empirical evidence not_evaluated. Empty official rule profiles SHALL explicitly report requirements not supplied/not_evaluated.

#### Scenario: Real source capsule without author narrative
- **WHEN** an accepted v2 source capsule is captured with explicit unbound mode
- **THEN** the report binds accepted event/manifest/capsule and exact profile bytes, records the external PDF hash separately, and leaves manuscript-text and actual-PDF predicates unevaluated when those bytes are absent.

#### Scenario: Actual accepted PDF with capsule
- **WHEN** the public source capsule is accompanied by an accepted PDF artifact
- **THEN** capture and replay count actual PDF bytes and require their digest to match the capsule's external PDF digest.

#### Scenario: Preserve author-bound behavior
- **WHEN** the flag is omitted or the run already binds a selected narrative
- **THEN** missing narrative remains an actionable error in the existing path, and explicit public mode does not replace a selected author narrative.
