---
phase: 04-subagent-orchestration-hooks-and-human-gates
plan: "03"
subsystem: execution-review-hooks
tags: [scheduler, blind-panel, hooks, deterministic, parent-authority]

requires:
  - phase: 04-subagent-orchestration-hooks-and-human-gates
    provides: immutable Phase 4 orchestration contracts and digest-bound corpus
provides:
  - host-neutral execution adapter and bounded deterministic scheduler
  - formal four-seat blind-review policy with separate synthesis and dissent matrix
  - observational hook contracts with parent parity and one-shot continuation budgets
affects:
  - 04-04 parent lifecycle integration
  - 04-06 native hook delivery
  - 04-07 host qualification

requirements-completed: [PKG-05, AGT-03, AGT-04, AGT-05, AGT-06, AGT-07]
completed: 2026-07-15
---

# Phase 04 Plan 03: Execution, Review, and Hook Contracts

## Accomplishments

- Added a journal-free `ExecutionAdapter` seam, deterministic fake adapter, frozen policy snapshot, bounded concurrency, frozen acceptance ordering, bounded retry taxonomy, and cooperative-cancel/force-terminate observations.
- Added `FormalPanelPolicy` with exactly four isolated reviewer seats and a separate editorial synthesizer. Reviewer envelopes omit peer identity, reports, attempts, and synthesis data; synthesis preserves source reports, evidence, severity, confidence, dissent, limitations, and critical blockers.
- Added strict observational hook wire contracts for all five trust statuses, parent-owned parity across runtime/MCP/integrity/gate/provenance, malformed and privilege-bearing output rejection, and one-shot `SubagentStop`/`Stop` continuation budgets.

## Task Commits

1. **Scheduler RED** — `74f4f27`
2. **Scheduler GREEN** — `1f4f219`
3. **Formal-panel RED** — `5463979`
4. **Formal-panel GREEN** — `2a0fed2`
5. **Hook-contract RED** — `c1c7b42`
6. **Hook-contract GREEN** — `fe38a7f`

## Verification

- `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_scheduler.py tests/unit/test_review.py tests/unit/test_hook_contracts.py -ra` — **7 passed**.
- The scheduler fake exposes no journal/event writer surface; hook and review records are observational and immutable.

## Deviations and Follow-up

- The existing Plan 01 vocabulary currently uses `native_formal` as an umbrella execution mode while the locked Phase 4 decision and evaluation corpus require distinct `native_profile` and `assignment_injected_subagent` modes. This is a contract integration correction before Plans 04-07, not a change to the authority model.

## Self-Check

The three owned modules and their focused tests exist, the required command passes, and no canonical journal dependency is imported by the scheduler, review policy, or hook contracts.

---
*Phase: 04-subagent-orchestration-hooks-and-human-gates*
*Completed: 2026-07-15*
