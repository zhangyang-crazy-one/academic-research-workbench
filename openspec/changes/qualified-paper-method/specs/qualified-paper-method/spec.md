## ADDED Requirements

### Requirement: Paper-bound independent method
The optional extension SHALL implement the Gale–Shapley deferred-acceptance
algorithm for strict, complete, equal-sized rankings of at most 64 members on
each side. It SHALL bind a factual author Example 2 input and unique matching,
DOI, reviewed PDF digest and printed page locations without redistributing the
paper or third-party code.

#### Scenario: Author golden
- **WHEN** Example 2 preferences are executed
- **THEN** the matching is alpha→C, beta→D, gamma→A and delta→B exactly,
  and the result is independently checked for blocking pairs.

### Requirement: Qualification before MCP exposure
The tool SHALL be omitted from MCP `tools/list` and rejected by `tools/call`
unless an immutable-source capsule, actual environment, and locally replayed
test receipt all validate. Missing, tampered, drifted or failed evidence SHALL
retain a typed gate diagnostic and SHALL NOT turn a declared PASS into access.

#### Scenario: Failed qualification
- **WHEN** a test failure is injected or source, metadata, receipt or
  environment drifts
- **THEN** neither legacy nor modern MCP lists or invokes the tool.

### Requirement: Bounded isolated result
Execution SHALL use bounded input, output, proposals and wall time with a
clean, network-denied and read-only worker environment. The result SHALL
distinguish `planned`, `executed` and typed `failed`, identify whether execution
was observed, and bind input/output digests. Invalid rankings and isolation
failure SHALL be explicit. The tool SHALL NOT write a scientific admission or
parent ledger event, and the base installation SHALL NOT enable it.

#### Scenario: Real workflow
- **WHEN** an operator qualifies the committed source, checks status and
  invokes the tool over old and modern MCP stdio frames
- **THEN** the golden matching executes with digests, a plan has no execution
  observation, and an invalid ranking returns a typed failure.

#### Scenario: Portable opt-in installation
- **WHEN** an operator explicitly creates or extracts the extension package
  and moves it away from the source checkout
- **THEN** its separate launcher verifies the pinned source through commit/tree
  witnesses, runs qualification and the golden call using only the standard
  library, and leaves the base wheel and default MCP configuration untouched.
