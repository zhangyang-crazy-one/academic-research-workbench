---
phase: 04
slug: subagent-orchestration-hooks-and-human-gates
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-14
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + Pydantic + jsonschema + canonical replay |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -q tests/unit/test_orchestration_models.py tests/unit/test_scheduler.py tests/schema/test_phase4_contracts.py` |
| **Full suite command** | `uv run pytest -q -m "not codex_host" tests/unit tests/schema tests/integration tests/staged tests/evals` |
| **Estimated runtime** | ~300 seconds after Wave 0 fixtures exist |

---

## Sampling Rate

- **After every task commit:** Run the directly affected unit/schema test and its nearest integration test
- **After every plan wave:** Run `uv run pytest -q -m "not codex_host" tests/unit tests/schema tests/integration tests/staged tests/evals`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Planned task IDs | Assigned by planner | Wave 0+ | PKG-05, AGT-01..07, SCI-02..03 | T-04-01..08 | Every rejection leaves the authoritative tree unchanged; host-only behavior stays unqualified until staged evidence passes | unit, schema, integration, replay, staged | Commands above plus exact host tuple canaries | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/evals/phase4/corpus/v1/manifest.json` and 48 immutable fixtures — contract/oracle before implementation
- [ ] `tests/unit/test_orchestration_models.py`, `test_scheduler.py`, `test_review.py`, `test_hook_contracts.py` — pure invariant coverage
- [ ] `tests/schema/test_phase4_contracts.py` — Pydantic and independent Draft 2020-12 validation
- [ ] `tests/integration/test_orchestration_lifecycle.py`, `test_orchestration_replay.py`, `test_orchestration_panels.py`, `test_orchestration_hook_parity.py`, `test_human_gates.py` — lifecycle, replay, panel, parity, and gate behavior
- [ ] `tests/staged/test_phase4_host_qualification.py` — explicit credential/environment guard; skipped is never a qualification pass

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Exact Codex host admission | PKG-05, AGT-01..07 | Requires an authenticated exact-version Codex host, isolated HOME/CODEX_HOME, and three fresh runs | Run `tests/staged/test_phase4_host_qualification.py` for each exact host tuple. Treat missing credential as unqualified/BLOCKED, not PASS. |
| Sealed-corpus semantic release review | SCI-02, SCI-03 | Requires two named domain experts and a third adjudicator | Review all 16 sealed cases and all `human_review_required` staged cases; preserve original labels and dissent. |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [ ] Feedback latency < 300 seconds
- [ ] `nyquist_compliant: true` set in frontmatter after planner task IDs are mapped

**Approval:** {pending / approved YYYY-MM-DD}
