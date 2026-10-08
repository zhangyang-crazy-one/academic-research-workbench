## ADDED Requirements

### Requirement: Exact bounded numeric acceptance
Evaluator 1.1.0 SHALL decide numeric reproduction, ranges, tolerances, thresholds, and budgets using exact rational values within its documented numeric domain. It SHALL render bounded deterministic decimal observations without allowing display rounding to affect the decision.

#### Scenario: Cancellation and order
- **WHEN** a sum of `1e50`, `1`, and `-1e50` is reported as zero with zero tolerance, in any row order
- **THEN** the numeric check fails; a report of one passes.

#### Scenario: Inclusive boundaries
- **WHEN** an exact value is at a range, tolerance, or threshold boundary
- **THEN** the evaluator includes equality and does not round an out-of-bound value into a pass.

#### Scenario: Scientific notation and unsupported magnitude
- **WHEN** accepted inputs contain `1e-100` or `1e100`
- **THEN** the result is schema-valid and deterministic.
- **WHEN** an exponent or coefficient exceeds the documented numeric domain
- **THEN** the evaluator returns a typed blocking check instead of raising a numeric or validation exception.

### Requirement: Version-specific replay
The evaluator SHALL replay each stored result with its recorded evaluator version and require byte-identical canonical output.

#### Scenario: Old receipt
- **WHEN** a stored 1.0.0 receipt is replayed after 1.1.0 is installed
- **THEN** the prior arithmetic and output representation are used and its digest is unchanged.
