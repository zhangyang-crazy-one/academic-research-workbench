# Writing rule review

## ADDED Requirements

### Requirement: Actionable review tasks
The writing workflow SHALL emit a source/candidate-bound plan for argument structure, fact integrity, claim strength, definitions and boundaries, and traceable revision. It SHALL not infer semantic correctness from word matches, surface metrics or text detector scores.

#### Scenario: Candidate prepared without reviewer
When a candidate is prepared, all five tasks are available and the rule-review status is `not_run`; semantic review remains required.

### Requirement: Bound reviewer report
The writing workflow SHALL validate the accepted review artifact's structured report against its task-plan digest and the exact source/candidate text. It SHALL retain the findings, category coverage, severity, confidence, evidence, reason and proposed minimal change with the accepted review binding. A current-version review without the optional rule report SHALL remain `not_run`. Previously accepted bundles SHALL stay readable; pending reviews bound to an older verification digest SHALL be regenerated.

#### Scenario: Submitted report has stale text or unlocated quote
When a report has a changed candidate hash or incorrect exact span, approval fails rather than presenting it as reviewed.

#### Scenario: Reviewer completes all tasks
When every task is reviewed or explicitly not applicable, no finding is open, and the existing human approval checks pass, the bundle records `reviewed` and the original findings. This status does not claim semantic equivalence is proven.

### Requirement: Mechanical and semantic separation
The workflow SHALL reserve automatic rejection for existing mechanical fact/preservation failures. Semantic rule findings SHALL remain advisory and SHALL not turn reviewer confidence into a machine-proven fact.

#### Scenario: Reviewer makes a low-confidence suggestion
A bound suggestion retains `severity=suggestion` and `confidence=low` without changing mechanical fact-lock status or creating an automatic block.
