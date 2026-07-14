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
| 04-01-01 | 01 | 1 | PKG-05, AGT-01, AGT-02, AGT-04, AGT-06, SCI-02, SCI-03 | T-04-01 | Strict immutable contracts, role conflicts, and execution provenance reject malformed/inline-independent claims | unit + schema | `uv run pytest -q tests/unit/test_orchestration_models.py tests/schema/test_phase4_contracts.py` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | AGT-01..07, SCI-02, SCI-03 | T-04-02 | 48 immutable cases and sealed labels remain parent-only | eval | `uv run pytest -q tests/evals/test_phase4_corpus.py` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 2 | AGT-01, AGT-02, AGT-03, SCI-02 | T-04-03 | Sole-writer lifecycle commands journal valid changes and leave rejected trees byte-identical | integration | `uv run pytest -q tests/integration/test_orchestration_lifecycle.py` | ❌ | ⬜ pending |
| 04-02-02 | 02 | 2 | AGT-03, AGT-05 | T-04-04 | Frozen ordering, retry cap, stale result, cancellation and orphan recovery are deterministic | unit + replay | `uv run pytest -q tests/unit/test_scheduler.py tests/integration/test_orchestration_replay.py` | ❌ | ⬜ pending |
| 04-03-01 | 03 | 3 | PKG-05, AGT-04 | T-04-05 | Four blind reviewer identities, separate synthesis, and dissent preservation are enforced | unit + integration | `uv run pytest -q tests/unit/test_review.py tests/integration/test_orchestration_panels.py` | ❌ | ⬜ pending |
| 04-03-02 | 03 | 3 | SCI-02, SCI-03 | T-04-06 | Scoped human decisions preserve original verdict bytes and one legal transition | integration | `uv run pytest -q tests/integration/test_human_gates.py` | ❌ | ⬜ pending |
| 04-04-01 | 04 | 4 | PKG-05, AGT-05 | T-04-07 | Adapter observations remain untrusted and unqualified host behavior blocks formal claims | integration | `uv run pytest -q tests/integration/test_orchestration_lifecycle.py tests/integration/test_orchestration_replay.py` | ❌ | ⬜ pending |
| 04-04-02 | 04 | 4 | AGT-06, AGT-07 | T-04-08 | Five hook modes preserve authority and one-continuation limit | unit + integration | `uv run pytest -q tests/unit/test_hook_contracts.py tests/integration/test_orchestration_hook_parity.py` | ❌ | ⬜ pending |
| 04-05-01 | 05 | 5 | AGT-01..07, SCI-02, SCI-03 | T-04-09 | Full corpus/replay/panel/hook/gate evidence has zero Critical invariant violations | full deterministic | `uv run pytest -q -m "not codex_host" tests/unit tests/schema tests/integration tests/staged tests/evals` | ❌ | ⬜ pending |
| 04-05-02 | 05 | 5 | PKG-05, AGT-01..07 | T-04-10 | Exact host tuple is PASS only after three fresh-home canary runs; absent credentials are unqualified | staged host | `ARW_EXPECT_CODEX_VERSION=<exact> uv run pytest -q -m codex_host tests/staged/test_phase4_host_qualification.py` | ❌ | ⬜ pending |

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
