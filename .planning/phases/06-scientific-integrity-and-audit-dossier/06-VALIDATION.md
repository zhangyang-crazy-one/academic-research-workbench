---
phase: 06
slug: scientific-integrity-and-audit-dossier
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-15
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for scientific-integrity receipts, external
> provenance, access-state claim gates, and the deterministic audit dossier.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 with the repository `.venv`; JSON Schema validation through the existing registry tests |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema/test_phase6_contracts.py tests/unit/test_integrity_receipts.py tests/unit/test_experiment_provenance.py` |
| **Full suite command** | `UV_OFFLINE=1 .venv/bin/python -m pytest -q` |
| **Estimated runtime** | quick < 20s; full suite serial and bounded, measured during execution |

---

## Sampling Rate

- **After every task commit:** Run the focused unit/schema command above.
- **After every plan wave:** Run the focused integration command and retain
  output under `build/evidence/phase-06`.
- **Before `$gsd-verify-work`:** Run `./scripts/verify-phase-6 --clean` and the
  full suite serially; both must be green for technical qualification.
- **Max feedback latency:** 60 seconds for a focused command; staged/full
  commands are explicitly serial to avoid the prior memory incident.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01 | 01 | 1 | SCI-01 | T-06-01 | Digest and freshness changes invalidate immutable receipts | unit/integration | `pytest -q tests/unit/test_integrity_receipts.py tests/integration/test_integrity_receipts.py` | ❌ W0 | ⬜ pending |
| 06-02 | 02 | 2 | SCI-04, SCI-05 | T-06-04/T-06-05/T-06-06 | External provenance is strict; controlled execution is blocked without all four bound gates | unit/integration | `pytest -q tests/unit/test_experiment_provenance.py tests/integration/test_experiment_provenance.py tests/integration/test_controlled_execution_blocked.py` | ❌ W0 | ⬜ pending |
| 06-03 | 03 | 3 | SCI-06, SCI-07 | T-06-07/T-06-08/T-06-09 | Five exact access states and claim capabilities cannot silently upgrade evidence | unit/integration | `pytest -q tests/unit/test_evidence_access.py tests/integration/test_evidence_access_states.py tests/integration/test_scientific_claim_gates.py` | ❌ W0 | ⬜ pending |
| 06-04 | 04 | 4 | SCI-01, SCI-06, SCI-07, VER-07 | T-06-10/T-06-11/T-06-12/T-06-13 | Canonical dossier rerenders byte-identically and survives projection loss/cold replay | integration/property | `pytest -q tests/unit/test_audit_dossier.py tests/integration/test_audit_dossier_replay.py tests/property/test_audit_dossier_replay.py` | ❌ W0 | ⬜ pending |
| 06-05 | 05 | 5 | VER-07 | T-06-14/T-06-15/T-06-16/T-06-17 | Staged package contains executable artifacts only and records separate technical/release verdicts | staged/full | `UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=build/tmp/phase-06 ./scripts/verify-phase-6 --clean --evidence-root build/evidence/phase-06` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/schema/test_phase6_contracts.py` — strict Phase 6 schema and
  registry-derived count coverage
- [ ] `tests/unit/test_integrity_receipts.py` — canonical receipt/hash/freshness
  cases
- [ ] `tests/unit/test_experiment_provenance.py` — strict external envelope
- [ ] `tests/unit/test_evidence_access.py` — exact five-state and capability
  matrix
- [ ] `tests/unit/test_audit_dossier.py` — canonical manifest/rendering checks
- [ ] `tests/fixtures/phase6/representative-run/` — bounded canonical fixture

Wave 0 is implementation work, not an excuse to delete or xfail a missing
test. The plan must create these tests before the corresponding implementation
slice is considered complete.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Confirm a human accountable actor reviews unresolved legal/intended-use blockers and does not treat technical PASS as release permission | VER-07 | Approval/permission evidence is external human authority | Inspect staged verifier dossier and `supply-chain/use-distribution.json`; confirm technical qualification and release qualification remain distinct and SUP-04/P04-09 stays BLOCKED. |
| Confirm staged install on the exact retained Codex host tuple does not export private dossier evidence | VER-07 | Host trust and local permission state are environment-dependent | Run the bounded staged install/host smoke command from `scripts/verify-phase-6`, inspect positive allowlist/inventory, and verify no secrets, private text, SQLite cache, or generated evidence is staged. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s for focused checks
- [ ] `nyquist_compliant: true` set in frontmatter after phase verification

**Approval:** pending
