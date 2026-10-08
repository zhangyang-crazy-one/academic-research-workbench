# Bind accepted writing candidates into narrative fit

Issue #73 blocks advisory venue fit after a reviewer accepts a writing revision
in a paper run. The accepted `writing-derived` artifact contains a receipt with
a nested draft realization and separately retained candidate bytes, while the
fit reader currently expects an accepted realization or manuscript byte string.
The paper-production workflow therefore cannot inspect that accepted revision
or replay a frozen fit report from it.

Add a versioned `writing_candidate_receipt` binding to the selected-narrative
fit snapshot. Capture and replay use the same receipt, candidate, realization,
manifest, event, run and review checks. Preserve the two existing snapshot
binding modes and their exact byte comparisons. The fit remains read-only and
advisory; it invokes no model and makes no acceptance decision.
