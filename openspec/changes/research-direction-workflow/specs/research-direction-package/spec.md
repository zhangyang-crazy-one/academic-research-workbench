## ADDED Requirements

### Requirement: Replaceable bounded direction content
Direction packages SHALL be external versioned data, validated against original ARS profiles and branch replay, carrying source/license/scope/unknown declarations without granting execution or author adoption.

#### Scenario: Two research families
- **WHEN** interpretive and computational packages are loaded through the same adapter
- **THEN** both preserve intentionally_absent/unresolved_fit stages, and replacement requires no domain-specific core code

### Requirement: Cross-stage provenance checks
Explicit bindings SHALL connect ARS project_ref and ARW project/run using exact snapshots, delegate AcceptedRef/citation/experiment validation to original readers, and report stale/missing/unsupported separately. Reports SHALL include checked denominators and human-review limits.

#### Scenario: Changed or cross-project content
- **WHEN** a profile/branch/source/definition changes or another project's reference is supplied
- **THEN** affected downstream bindings are stale or rejected without rewriting historical snapshots or treating candidate branches as author-adopted

### Requirement: Versioned reading and operationalization
Intake preparation SHALL distinguish versions/carriers and preserve reading, bibliographic, byte availability, record admission, support and experiment statuses. It SHALL generate ordinary artifact candidates and existing acceptance requests without making scientific claims.

#### Scenario: Inconsistent abstract and source revisions
- **WHEN** two synthetic full-text versions and a contradictory abstract are supplied with partial/missing source bytes
- **THEN** notes remain attached to exact versions/carriers, affected conclusions wait for review, and citation replay retains original verified/not_found/unavailable states

### Requirement: Offline bounded walkthrough
The implementation SHALL provide an offline synthetic/replayed walkthrough with source disputes, operational definitions, frozen contracts, accepted evidence and scoped candidate narrative; human choices and actual paid costs SHALL never be fabricated.

#### Scenario: Negative and unsupported evidence
- **WHEN** controls/costs/attempts are missing, philosophical source support is absent, or original experiment replay is failed/unsupported
- **THEN** mechanical missing/review rows remain visible and no generic scientifically passed verdict or manuscript occurrence is created
