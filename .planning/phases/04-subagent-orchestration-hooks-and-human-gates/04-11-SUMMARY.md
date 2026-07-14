---
phase: 04-subagent-orchestration-hooks-and-human-gates
plan: "11"
subsystem: behavior-test-matrix
tags: [pytest, red-tests, deterministic, host-qualification]
requires:
  - phase: 04-subagent-orchestration-hooks-and-human-gates
    provides: strict contracts and digest-bound corpus
provides:
  - Owner-mapped deterministic red tests for scheduler, review, lifecycle, replay, hooks, gates, and host qualification
affects:
  - 04-02 parent event/reducer implementation
  - 04-03 scheduler, panel, and hook implementation
  - 04-04 through 04-08 runtime and verification plans
tech-stack:
  added: []
  patterns:
    - Strict xfail with owning task IDs for behavior not yet implemented
    - Non-host qualification asserts BLOCKED; live host tests use codex_host
key-files:
  created:
    - tests/unit/test_scheduler.py
    - tests/unit/test_review.py
    - tests/unit/test_hook_contracts.py
    - tests/integration/test_orchestration_lifecycle.py
    - tests/integration/test_orchestration_replay.py
    - tests/integration/test_orchestration_panels.py
    - tests/integration/test_orchestration_hook_parity.py
    - tests/integration/test_human_gates.py
    - tests/staged/test_phase4_host_qualification.py
  modified: []
key-decisions:
  - "Every not-yet-implemented behavior has a strict owner-mapped xfail rather than a skip or empty test."
  - "Hostless qualification is tested as BLOCKED; formal host tests are isolated behind codex_host."
requirements-completed: [PKG-05, AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, AGT-06, AGT-07, SCI-02, SCI-03]
duration: 5m
completed: 2026-07-14
---

# Phase 04 Plan 11: Behavior-Test Matrix Summary

The Phase 4 behavior surface is now represented by deterministic owner-mapped tests. Runtime plans must replace each strict expected failure with a normal assertion before final qualification.

## Verification

- `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit/test_scheduler.py tests/unit/test_review.py tests/unit/test_hook_contracts.py tests/integration/test_orchestration_lifecycle.py tests/integration/test_orchestration_replay.py tests/integration/test_orchestration_panels.py tests/integration/test_orchestration_hook_parity.py tests/integration/test_human_gates.py tests/staged/test_phase4_host_qualification.py -m 'not codex_host'` — expected failures reported as strict xfails; no skipped tests.
- `git diff --check` — passed.

## Next Phase Readiness

Wave 1 is complete; Wave 2 can implement parent events/reducer and the scheduler/panel/hook seams.

*Phase: 04-subagent-orchestration-hooks-and-human-gates*
*Completed: 2026-07-14*
