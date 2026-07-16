---
phase: 07
slug: installed-e2e-recovery-and-release-qualification
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-16
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for installed package qualification,
> deterministic crash/recovery, representative research E2E, and release
> fail-closed evidence.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 with the repository `.venv`; JSON/canonical evidence through existing ARW validators |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `UV_OFFLINE=1 PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -q tests/unit/test_integration_lock.py tests/integration/test_recovery.py tests/integration/test_recovery_crash.py tests/staged/test_manifest_install.py tests/staged/test_mcp_launcher.py` |
| **Full suite command** | `UV_OFFLINE=1 PYTHONNOUSERSITE=1 TMPDIR=$(pwd)/build/tmp/phase-07/full .venv/bin/python -m pytest -q -m 'not codex_host'` followed by the exact staged host canary |
| **Estimated runtime** | quick < 60s; full non-host bounded serial run ~6–10 min; host canary serial and environment-dependent |

## Sampling Rate

- **After every task commit:** Run the focused command for the modified slice.
- **After every plan wave:** Run the installed/recovery E2E subset and retain
  evidence below `build/evidence/phase-07`.
- **Before `$gsd-verify-work`:** Run the serial Phase 7 verifier, full non-host
  regression, locked stage validation, and exact host canary.
- **Max feedback latency:** 60 seconds for focused tests; heavy stage/install
  commands are serial and explicitly bounded.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01 | 01 | 1 | VER-02 | T-07-01/T-07-02 | Installed bytes and external local ARS identity are lock-bound; source checkout and bundled ARS are rejected | staged/integration | `pytest -q tests/integration/test_integration_lock.py tests/staged/test_manifest_install.py tests/staged/test_mcp_launcher.py tests/staged/test_skill_route.py` plus locked stage/canary | ✅ existing, new probes W0 | ✅ PASS |
| 07-02 | 02 | 2 | VER-04 | T-07-03/T-07-04/T-07-05 | Fault classes produce deterministic replay/recovery/block verdicts with parent-owned sidecar evidence and bounded retry | unit/integration/property | `pytest -q tests/integration/test_recovery.py tests/integration/test_recovery_crash.py tests/unit/test_recovery_scan.py` plus Phase 7 fault matrix | ✅ existing, new matrix W0 | ✅ PASS |
| 07-03 | 03 | 3 | VER-06 | T-07-06/T-07-07 | Installed representative fixture completes ARS route, scientific evidence, review/gate/human resolution, crash/resume, and dossier cold replay | installed E2E/integration | `pytest -q tests/staged/test_phase6_audit_dossier.py tests/integration/test_audit_dossier_replay.py` plus installed fixture command | ✅ existing, new E2E W0 | ✅ PASS |
| 07-04 | 04 | 4 | VER-08 | T-07-08/T-07-09 | Missing, stale, tampered, incompatible, or legally unresolved evidence yields technical/release verdict separation and named blockers | staged/full/adversarial | `./scripts/verify-phase-7 --clean --evidence-root build/evidence/phase-07-final-11` plus serial non-host/full host checks | ✅ verifier | ✅ PASS (technical) / BLOCKED (legal) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

## Wave 0 Requirements

- [x] `tests/integration/test_phase7_installed_e2e.py` — installed
  representative journey and ARS bounded evidence
- [x] `tests/integration/test_phase7_fault_matrix.py` — deterministic fault
  injection, replay classification, retry budget, and sidecar evidence
- [x] `tests/staged/test_phase7_qualification.py` — stage/source-hidden,
  external ARS root, compatibility and release aggregation probes
- [x] `scripts/verify-phase-7` — serial evidence-bound verifier
- [x] Existing pytest, stage-plugin, qualify-codex-host, integration-lock, and
  Phase 6 dossier/recovery fixtures cover the remaining infrastructure

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Confirm an accountable human/legal reviewer has supplied compatible CC BY-NC intended-use, distribution, approval, and permission evidence | VER-08 | Authority and permission cannot be fabricated by local automation | Inspect `supply-chain/license-verdict.json`, `supply-chain/use-distribution.json`, and final verifier dossier; technical PASS must remain release BLOCKED until the external evidence is append-only and hash-bound. |
| Confirm the current local ARS adapter root is intentionally provisioned and not an accidental mutable user checkout | VER-02/VER-08 | Host path and operator intent are environment-dependent | Record explicit `ARW_ARS_ROOT`, compare the local manifest/version/tree digests to the integration lock, and reject any symlink, missing root, or drift. |

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s for focused checks (heavy commands serial)
- [x] `nyquist_compliant: true` set in frontmatter after phase verification

**Approval:** technical qualification complete; release remains BLOCKED by
SUP-04/P04-09 and unresolved CC-BY-NC intended-use, distribution,
accountable-approval, and permission evidence.

## Retained Phase 7 evidence

- `build/evidence/phase-07-final-13/phase-7-verification.json`
- `build/evidence/phase-07-final-13/commands/phase7-focused/result.json`
- `build/evidence/phase-07-final-13/commands/phase7-nonhost/result.json`
- `build/evidence/phase-07-final-13/commands/phase7-host-canary/result.json`
- `build/evidence/phase-07-final-13/prior-phase-receipts.json`
