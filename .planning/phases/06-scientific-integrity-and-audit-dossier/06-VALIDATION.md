---
phase: 06
slug: scientific-integrity-and-audit-dossier
status: passed-technical-release-blocked
nyquist_compliant: true
wave_0_complete: true
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
| 06-01 | 01 | 1 | SCI-01 | T-06-01 | Digest and freshness changes invalidate immutable receipts | unit/integration | `pytest -q tests/unit/test_integrity_receipts.py tests/integration/test_integrity_receipts.py` | ✅ | verified in `06-01-SUMMARY.md` |
| 06-02 | 02 | 2 | SCI-04, SCI-05 | T-06-04/T-06-05/T-06-06 | External provenance is strict; controlled execution is blocked without all four bound gates | unit/integration | `pytest -q tests/unit/test_experiment_provenance.py tests/integration/test_experiment_provenance.py tests/integration/test_controlled_execution_blocked.py` | ✅ | verified in `06-02-SUMMARY.md` |
| 06-03 | 03 | 3 | SCI-06, SCI-07 | T-06-07/T-06-08/T-06-09 | Five exact access states and claim capabilities cannot silently upgrade evidence | unit/integration | `pytest -q tests/unit/test_evidence_access.py tests/integration/test_evidence_access_states.py tests/integration/test_scientific_claim_gates.py` | ✅ | verified in `06-03-SUMMARY.md` |
| 06-04 | 04 | 4 | SCI-01, SCI-06, SCI-07, VER-07 | T-06-10/T-06-11/T-06-12/T-06-13 | Canonical dossier rerenders byte-identically and survives projection loss/cold replay | integration/property | `pytest -q tests/unit/test_audit_dossier.py tests/integration/test_audit_dossier_replay.py tests/property/test_audit_dossier_replay.py` | ✅ | verified in `06-04-SUMMARY.md` |
| 06-05 | 05 | 5 | VER-07 | T-06-14/T-06-15/T-06-16/T-06-17 | Staged package contains executable artifacts only and records separate technical/release verdicts | staged/full | `UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=build/tmp/phase-06 ./scripts/verify-phase-6 --clean --evidence-root build/evidence/phase-06` | ✅ | verifier PASS; release remains BLOCKED |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/schema/test_phase6_contracts.py` — strict Phase 6 schema and
  registry-derived count coverage
- [x] `tests/unit/test_integrity_receipts.py` — canonical receipt/hash/freshness
  cases
- [x] `tests/unit/test_experiment_provenance.py` — strict external envelope
- [x] `tests/unit/test_evidence_access.py` — exact five-state and capability
  matrix
- [x] `tests/unit/test_audit_dossier.py` — canonical manifest/rendering checks
- [x] `tests/fixtures/phase6/representative-run/` — bounded canonical fixture

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

## Phase 6 closeout evidence

The final serial verifier completed with `technical_qualification: PASS` and
`release_qualification: BLOCKED` at
`build/evidence/phase-06-final-verifier/verdict.json`. It binds HEAD
`92354292d8dd92e99650d81daf09e62aa6037ba3`, Codex CLI `0.144.4`, the exact
Phase 04.1 integration lock
`build/evidence/phase-04.1-host-canary-20260715i/integration-lock.json`
(SHA-256
`9d6ea3514e6abaed34e1223fbe3631e0e53a6d74b7f6945ebb29666aaf2be0c6`), stage
tree `c4095eb25d5c3ed5d8d25a2c74f2af06a1995914d9a7b8ee26b39914b5411046`, and
the source-manifest, schema-registry, SBOM, wheelhouse, and retained license
identities. Locked stage build and validate both returned zero with no inventory
drift.

The verifier's Phase 6 focused command passed all selected tests and the prior
Phase 4/5 composition command passed. The bounded full non-host regression ran
serially with an absolute repository-owned temporary root and completed
**448 passed** in 372.05 seconds. Output is retained at
`build/evidence/phase-06-final-full/full/pytest.stdout.log` (SHA-256
`f313c55b0e4eb4c137ad4d071e8b8da2cf519b99b88a4a7503ad67883c4ef5d6`) and
`pytest.stderr.log` (SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`). The
exact staged host/codex evidence is retained by the Phase 04.1 canary and
reports three fresh HOME receipts, hook parity, controlled result channels,
and no retained credentials or absolute-path material. No tests were skipped,
xfailed, or xpassed.

The native legal gate remains represented by the retained
`supply-chain/license-verdict.json`: technical qualification is PASS, but
release qualification is BLOCKED for `SUP-04`, `P04-09`, and unresolved
CC-BY-NC intended-use/permission evidence. A memory-heavy native ScanCode
rerun is not part of the serial Phase 6 verifier; no legal blocker was
silently cleared.

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s for focused checks (full regression explicitly bounded)
- [x] `nyquist_compliant: true` set in frontmatter after phase verification

**Approval:** technical qualification complete; release approval remains blocked
by SUP-04/P04-09 and unresolved CC-BY-NC intended-use, distribution,
accountable-approval, and permission evidence. This record does not authorize
publication or distribution.
