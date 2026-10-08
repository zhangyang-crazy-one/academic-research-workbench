## ADDED Requirements

### Requirement: Scoped accepted references
The resolver SHALL bind parent artifacts to their run manifest and acceptance event, or journal payloads to their event sequence and digest. It MUST preserve original adapter objects and distinguish resolved, unresolved, unsupported and proven scope.

#### Scenario: Missing and ambiguous provenance
- **WHEN** a hashless memory link, claim edge, absent acceptance, or duplicate artifact across runs is adapted
- **THEN** it returns unsupported or unresolved with a typed reason without upgrading evidence

#### Scenario: Source and capsule validation
- **WHEN** a source locator or venue capsule is adapted
- **THEN** full original validation applies and selected digest/activity are preserved, while capsules prove structural bytes only

### Requirement: Bounded exact arithmetic
The evaluator SHALL use bounded canonical rational numbers and a sealed versioned expression vocabulary. Unsupported operations, incompatible contexts and zero denominators MUST return typed outcomes.

#### Scenario: Nonterminating and percentage calculations
- **WHEN** mean of 0,0,1 and comparisons from 0.80 to 0.831 are evaluated
- **THEN** exact values are 1/3,31/1000 percentage-point difference and 31/800 relative change

### Requirement: Stable selection and identity
The evaluator SHALL preserve unique CSV row IDs, explicit row sets, grouping and missing policies. Derivation identity MUST include accepted references, expression, comparison context and evaluator version, excluding presentation.

#### Scenario: Selection and display independence
- **WHEN** row groups differ or decimal precision changes
- **THEN** group selection changes identity while presentation changes do not

### Requirement: Legacy preservation
The implementation SHALL preserve existing receipt and replay semantics and MUST NOT interpret legacy observed display text as an exact value.

#### Scenario: Legacy receipts
- **WHEN** a rounded old receipt is supplied as numeric evidence
- **THEN** it remains unchanged and cannot be upgraded to exact numeric provenance
