# Writing detection audit

## ADDED Requirements

### Requirement: Distinct opt-in detector observations
The writing workflow SHALL distinguish text classification from algorithm-specific watermark detection. It SHALL record version, public parameters, input SHA-256, score meaning, status and failure class for each invocation. Unconfigured, incompatible and failed detectors SHALL not produce a fabricated score.

#### Scenario: No watermark generator key is known
When a watermark detector has no exact generator key and vocabulary, its result is `not_run` and no score or delta is reported.

### Requirement: Reproducible local backends
The writing workflow SHALL offer an offline, fixed-model classification adapter and a statistical watermark adapter runnable against a matching synthetic generator without downloading weights or sending manuscript text away.

#### Scenario: Local synthetic fixture
Given the checked-in synthetic classification model and exact watermark generator inputs, the CLI reports raw before/after scores and hashes. These scores make no authorship or evasion claim.

### Requirement: Explicit external transmission
The writing workflow SHALL require an explicit CLI flag for HTTP transmission, restrict destinations to HTTPS or loopback, and avoid exposing credentials or response bodies in reports.

#### Scenario: Network flag omitted
When an HTTP adapter is configured without `--allow-network`, both observations remain `not_run` and no manuscript bytes are transmitted.

### Requirement: Separate preservation verdicts
The writing workflow SHALL reuse fact-lock numeric/citation checks where available and retain an unresolved human semantic-review status even if mechanical checks pass. A mechanical failure SHALL reject a writing proposal; a detector score SHALL never approve one.

#### Scenario: Changed claim quantity
When a revision changes a numeric claim, the fact-lock mechanical status is `failed`; semantic review remains unresolved and the proposal is rejected.
