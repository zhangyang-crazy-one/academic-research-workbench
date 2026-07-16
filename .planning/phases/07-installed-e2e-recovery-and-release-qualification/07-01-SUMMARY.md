---
phase: 07-installed-e2e-recovery-and-release-qualification
plan: 01
status: complete
requirements:
  - VER-02
commits:
  - ee6f129
  - 0b50173
  - 9d9ac6c
  - 638db0e
---

# Phase 7 Plan 01 Summary

## Outcome

The first Phase 7 installed qualification slice is complete. The staged ARW
package is source-hidden and contains no ARS tree; the local ARS adapter is an
explicit external exact installation bound to its manifest, `VERSION`, router,
upstream commit/tree identities, full adapter tree, and `ars/` content tree.
The retained host baseline is Codex CLI `0.144.4` with a fresh three-HOME,
hook, credential, isolation, and controlled-result-channel canary.

Technical qualification is `PASS`. Release qualification remains `BLOCKED`
only for the existing legal/intended-use gate (`INTENDED_USE_UNKNOWN`,
`DISTRIBUTION_CLASS_UNKNOWN`, `ACCOUNTABLE_APPROVAL_MISSING`, and
`CC_BY_NC_PERMISSION_UNRESOLVED`). No legal status was inferred from the
technical receipt.

## Completed Tasks

### 07-01-T1 — Exact external ARS integration lock

- Added table-driven fail-closed coverage for manifest/version/router drift,
  local ARS content drift, upstream commit drift, missing roots, symlink roots,
  and silently bundled ARS.
- Preserved the external-only dependency model (`bundled: false`) and the
  existing source-manifest/upstream identity checks.
- Focused result: `51 passed` (`tests/unit/test_integration_lock.py` plus
  `tests/integration/test_version_report.py`).

### 07-01-T2 — Source-hidden installed ARS smoke

- Added `tests/integration/test_phase7_installed_e2e.py`.
- Builds an exact stage, copies it into a local-marketplace-shaped directory,
  hides the checkout from import lookup, sets `ARW_ARS_ROOT` explicitly, and
  runs the installed `bin/arw route --json` command offline.
- Retains only bounded ARS route/handoff digests and redacted command identity;
  full workflow text, credentials, absolute roots, and transcripts are absent.
- Focused result: `2 passed`; final combined installed/staged qualification
  probe result: `5 passed` with the exact lock-bound stage.

### 07-01-T3 — Stage and host compatibility probes

- Added `tests/staged/test_phase7_qualification.py` covering positive
  allowlist/inventory, `hooks/arw_hook.py`, SBOM/build-identity parity, MCP/CLI
  surface exposure, official observational hook inputs, and unsupported host
  version rejection.
- Added a fail-closed exact host baseline: `build_integration_lock` and
  staged-lock validation reject any CLI other than `codex-cli 0.144.4`.
- Final stage validation:
  `scripts/stage-plugin --validate-only --integration-lock ...` → `stage valid`.
- Earlier full staged suite (`phase7 qualification`, manifest install, MCP
  launcher, and installed skill route) completed `9 passed` in `87.79s`.

## Retained Evidence

- `build/stage/phase-07-qualified/`
- `build/evidence/phase-07/integration-lock.json`
- `build/evidence/phase-07/host-canary/canary.json`
- `build/evidence/phase-07/installed-qualification.json`

The current lock records ARS adapter `0.1.20`, the pinned upstream commits,
Codex `0.144.4`, technical `PASS`, and release `BLOCKED`. The host canary
records three fresh-home receipts, default untrusted-hook behavior, observed
official hook execution under the audited bypass, credential hygiene, and
controlled result-channel `PASS`.

## Deviations from Plan

**[Rule 1 - Bug] Staged lock verifier omitted the newly imported exact-version constant** — Found during: final lock-bound stage refresh | The first refresh failed with `NameError: EXPECTED_CODEX_CLI_VERSION` in the final stage-validation block | Added the missing import and reran the stage build/validation | File: `scripts/stage-plugin` | Verification: lock-bound stage validates and all Phase 7 staged probes pass | Commit: `638db0e`.

**Total deviations:** 1 auto-fixed (one staged-verifier import defect). **Impact:** no qualification boundary weakened; the failure was fail-closed before publication and the refreshed exact host/stage/lock evidence passed.

## Self-Check: PASSED

- All task acceptance criteria were rerun after the final refresh.
- `git diff --check` passed.
- No tests were deleted or xfailed.
- Existing Phase 4/04.1 dirty work was preserved and not included in the
  plan commits.
