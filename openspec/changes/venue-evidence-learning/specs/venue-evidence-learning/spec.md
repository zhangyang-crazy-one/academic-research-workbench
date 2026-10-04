# Venue evidence learning

## ADDED Requirements

### Requirement: Source-bound accepted exemplars
An exemplar SHALL reference accepted source bytes by digest and accepted artifact ID and a prior exact accepted reviewer declaration of official URL/DOI, category, year and access basis. Full-text annotations SHALL identify each of the six narrative functions with a section and locator. Metadata-only records SHALL NOT assert figure, section, evidence-form, or prose patterns. Repeated DOI, canonical URL, or source hash SHALL NOT add independent support. Accepted publication status and official URL are reviewer-supplied metadata and do not become a venue rule.

#### Scenario: Exact reviewed source
- **WHEN** a parent admits an accepted exemplar annotation
- **THEN** its retained source digest and prior exact review are verified, its observed functions have locators, and duplicate identity cannot add support.

### Requirement: Authentic narrative-bound outcomes
An observed venue outcome SHALL bind the narrative digest/version selected for its originating paper run, retained evidence bytes, and any historically promoted and used heuristic IDs. The selected digest/version SHALL exist in the project narrative history. Later author-approved narrative changes SHALL NOT invalidate an authentic historical outcome observation; a digest/version unrelated to that run or unmatched source digest SHALL fail before the observation event. New Phase 2 suggestions still require the currently selected narrative.

#### Scenario: Historical narrative outcome
- **WHEN** a venue outcome binds the selected narrative from its originating paper run
- **THEN** an authentic historical narrative remains valid after later narrative edits, while unrelated digests fail before observation.

### Requirement: Independent counterexample evaluation
A venue evidence policy SHALL bind an exact independent exemplar subset. Its reviewed samples SHALL preserve supporting, counterexample, and unknown classifications. Evaluation SHALL FAIL when counterexamples are at least supporting. Earlier mean-delta policies and receipts SHALL remain replayable. Qualification and promotion SHALL retain human approval, consent, and cross-project evidence rules.

#### Scenario: Counterexamples reject a pattern
- **WHEN** reviewed independent samples have counterexamples at least equal to supporting samples
- **THEN** evaluation fails and earlier mean-delta receipts remain replayable.

### Requirement: Advisory applicability and legacy migration
Venue/domain fit SHALL be checked separately from approved sharing scope. Phase 2 suggestions SHALL expose only promoted, applicable advisory heuristics with counts and source IDs; they SHALL NOT mutate the selected narrative or become official venue requirements. Quantity guidance SHALL state that it is nonmandatory and name exception and counterexample needs. A selected legacy prose clause MAY become a rebuildable ledger candidate bound to an accepted profile observation, with zero asserted support and explicit unknown evidence. Such a candidate SHALL NOT evaluate or promote; actual source-bound observations require a new verified successor.

#### Scenario: Unverified legacy guidance
- **WHEN** an accepted legacy profile clause becomes a candidate
- **THEN** its support remains zero with explicit unknown evidence and it cannot evaluate or promote; actual verified observations require a new successor.

### Requirement: Explicit bounded source capsules
An additive v2 exemplar MAY retain a structural capsule instead of a full PDF. Its `source_sha256` SHALL bind retained capsule bytes; its separate reviewed PDF provenance SHALL bind official PDF URL, SHA-256, byte count, page count, extractor, agent reviewer, read scope, and review limitations. The prior v2 review SHALL use `AGENT_REVIEW_RECORDED`; neither source admission nor ledger replay SHALL represent this as user-attested reading, author approval, scientific validation, or retained PDF verification. Full PDFs SHALL remain transient and SHALL NOT receive a larger accepted-artifact read budget.

The capsule SHALL contain the exact sections, figure roles, evidence forms and observed patterns asserted by its exemplar. Admission and ledger reconstruction SHALL verify exact capsule/review/exemplar agreement. Each of the six functions SHALL be recorded once as observed with section, locator and paraphrase, or unknown with a reason and no asserted locator. Metadata-only v1 and existing full-text v1 contracts SHALL remain unchanged. Duplicate physical PDF digest SHALL NOT add independent support, including across v1 retained-PDF and v2 capsule records.

#### Scenario: Transient PDF and offline reconstruction
- **WHEN** an agent supplies a reviewed full PDF and its bounded structural capsule
- **THEN** local E2E tooling verifies actual PDF size, digest and page count before source acceptance, records the capsule and reviewed PDF hashes separately, and reconstructs the learning inventory from retained artifacts after deleting the disposable index.
- **WHEN** the transient PDF is unavailable during later replay
- **THEN** replay verifies capsule bytes and agent declarations, and does not claim to reverify absent PDF bytes.

#### Scenario: Missing function or changed provenance
- **WHEN** a reviewed source lacks an identifiable narrative function
- **THEN** its v2 entry records unknown rather than inventing a locator.
- **WHEN** capsule annotations, official metadata, PDF provenance, or prior review differ
- **THEN** observation admission fails without appending a learning observation.

### Requirement: Honest survey source versions
V2 full-text source records SHALL distinguish publisher full text, accepted author manuscripts, and author preprints. Non-publisher full-text access SHALL declare the matching document version, repository authority, and a reviewed version-relationship note. Related formal-publication URLs and DOI identifiers MAY be recorded as metadata but SHALL NOT establish publisher byte equivalence, final venue, scientific correctness, or author approval. Citation-count provenance MAY remain in research audit records and SHALL NOT grant candidate authority.

Only newly added absent optional source-version fields SHALL be omitted when serializing historical v2 capsules; established nullable fields SHALL remain unchanged. Previously retained ten-source capsule bytes and frozen report bytes SHALL remain replayable.

#### Scenario: Accepted author survey or preprint
- **WHEN** an accepted-author survey or author preprint is observed from transient repository PDF bytes
- **THEN** its access basis and document version are explicit and exactly bound across capsule, prior review and exemplar; missing or contradictory declarations fail before observation.

#### Scenario: Survey argument evidence
- **WHEN** a reviewed survey uses taxonomy, cited comparison, synthesis and bounded open questions rather than a new method experiment
- **THEN** its functions and evidence forms record those observed review roles, a survey-specific candidate uses a reviewed source classification, and no experiment or citation-count endorsement is invented.

#### Scenario: Unresolved formal venue
- **WHEN** a reviewed preprint's final formal venue linkage is unresolved
- **THEN** a declared preprint venue group is preserved and that source does not add support to a disputed formal-journal candidate.

### Requirement: Phase 2 planner consumes governed context
The existing ARS plan/outline planner SHALL accept an explicit complete project/run/venue/domain/applicability opt-in and call the read-only Phase 2 suggestion capability. It SHALL provide the exact advisory snapshot and applicability input digest to the structure architect's task context, or the inline plan context. A call without the opt-in SHALL retain its original plan shape. Advice SHALL remain nonexecutable and require author choice; the planner SHALL NOT change project narrative, run journal, candidate status, or approved scope.

#### Scenario: Governed promoted advice reaches outline planning
- **WHEN** an academic-paper plan, outline-only or full request opts in with a currently bound paper run and matching promoted lesson
- **THEN** its inline/structure-architect context includes the selected narrative digest, advice-set digest, input digest and approved lesson, while candidate or rejected lessons are absent.

#### Scenario: Unsafe or unrelated planning context
- **WHEN** options are incomplete, the requested workflow is unrelated, selection is absent/stale, the run binds a different project, or the applicability source is unsafe
- **THEN** the planner fails explicitly without falling back to unbound or self-declared advice.

#### Scenario: Research corpus has no author selection
- **WHEN** the source-review corpus has no selected author paper narrative
- **THEN** it cannot supply Phase 2 paper context; synthetic governed integration fixtures do not count as production domain adoption or candidate promotion.
