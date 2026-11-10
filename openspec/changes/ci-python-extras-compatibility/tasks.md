## 1. Reproduce and define the regression

- [x] 1.1 Inspect the actual failed job log and baseline workflow; retain source-linked evidence.
- [x] 1.2 Add CI compatibility regression tests and record failure against the unchanged workflow.

## 2. Implement and verify

- [x] 2.1 Select Python 3.14 for complete extras and add independent floating latest-Python core coverage.
- [x] 2.2 Document the CI support matrix and unchanged runtime/dependency policy.
- [x] 2.3 Run targeted workflow/core regressions, attempt full optional resolution on 3.14, and record actual results and remaining hosted/cp315 limits.

## 3. Revalidate newest-Python coverage

- [x] 3.1 Audit the original hosted run's selected interpreter and separate the #170 stack prerequisite from #177's scope.
- [x] 3.2 Require latest stable interpreter lookup and fail-closed core steps, with a failing-before/fixed-after regression.
- [x] 3.3 Recheck the core workflow and CI contracts locally and record the exact interpreter and remaining hosted limits.
