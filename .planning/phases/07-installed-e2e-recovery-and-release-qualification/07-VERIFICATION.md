---
phase: 07-installed-e2e-recovery-and-release-qualification
verified: 2026-07-16T03:53:18Z
status: passed
score: 12/12 must-have truths verified
---

# Phase 7: Installed E2E Recovery and Release Qualification Verification

**Phase Goal:** An installed staged package earns v1.0 qualification only by
completing the representative research audit through crash/resume and
satisfying every release evidence gate.

**Verified:** 2026-07-16T03:53:18Z
**Status:** passed (technical qualification); release remains BLOCKED by the
explicit legal/permission gates recorded in the receipts.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Installed tests exercise a source-hidden staged package and retain manifest, route, launcher, MCP, hook, and version evidence. | ✓ VERIFIED | `build/evidence/phase-07-final-11/phase-7-verification.json` binds the qualified stage, lock, host canary, and four serial command receipts; stage validation passed and the installed qualification receipt reports no retained absolute paths or secrets. |
| 2 | The external ARS adapter is explicit, exact, lock-bound, and not bundled. | ✓ VERIFIED | `build/evidence/phase-07/installed-qualification.json` and `integration-lock.json` bind adapter/stage/host digests; staged qualification and installed smoke passed with external ARS input. |
| 3 | Codex 0.144.4 compatibility, hook observation, isolation, and controlled result-channel evidence are retained. | ✓ VERIFIED | `build/evidence/phase-07/host-canary/canary.json` records the exact host tuple, hook digest/status, controlled result channel, credential hygiene, and three fresh-home receipts; all three isolation receipts pass. |
| 4 | Canonical write, fsync, lock, and host-dispatch faults have stable IDs and a test-only injection seam. | ✓ VERIFIED | `tests/fixtures/recovery/phase7_faults`, `src/arw/faults.py`, and the serial fault matrix enumerate 18 registered scenarios and pass the focused recovery suite. |
| 5 | Hard termination, torn writes, I/O/space failure, lock death, duplicate/stale delivery, timeout, and proposal faults recover, retry, reject, or block deterministically. | ✓ VERIFIED | `build/evidence/phase-07/recovery-matrix.json` is serial, covers all 18 IDs, records bounded retry counts, and reports technical `PASS`; focused matrix and crash tests pass. |
| 6 | Recovery never launders failures as cancellation and non-tail/hash/manifest/lock damage remains blocked. | ✓ VERIFIED | Recovery matrix classifications include `BLOCKED`, `REJECTED`, `RECOVERED_TAIL`, and bounded `RETRYABLE`; journal/replay and verifier tamper probes pass. |
| 7 | One installed representative journey covers source/access, claim, experiment, figure/result, independent review with dissent, failed gate, human resolution, crash/resume, and dossier. | ✓ VERIFIED | `build/evidence/phase-07/representative-dossier.json` contains the canonical run history, experiment/artifact/review/human hashes, dissent reference, and separate technical/release verdicts. |
| 8 | ARS contributes only bounded validated route/handoff/result evidence; ARW ledger, manifests, gates, and dossier remain authoritative. | ✓ VERIFIED | Installed E2E and dossier tests pass; ARS evidence is digest-bound and the dossier is assembled from ARW canonical records. |
| 9 | Cold replay after projection loss is hash-stable and preserves identities, report hashes, dissent, human resolution, and the release blocker. | ✓ VERIFIED | `build/evidence/phase-07/representative-dossier-replay.json` reports warm/cold technical `PASS`, `projection_unavailable`, all report hashes, and release `BLOCKED`. |
| 10 | A serial aggregate verifier validates installed, ARS, host, recovery, E2E, inventory/SBOM/build, and prior-phase evidence under one owned root. | ✓ VERIFIED | `scripts/verify-phase-7` produced `build/evidence/phase-07-final-11/phase-7-verification.json` with `evidence_bound: true`, four ordered command receipts, prior Phase 5/4.1 bindings, and a clean code-review status. |
| 11 | Missing, stale, tampered, incompatible, source-leaking, or legally unresolved evidence fails closed with named blockers. | ✓ VERIFIED | Verifier tamper/adversarial tests pass; final receipt names `SUP-04`, `P04-09`, `INTENDED_USE_UNKNOWN`, `DISTRIBUTION_CLASS_UNKNOWN`, `ACCOUNTABLE_APPROVAL_MISSING`, and `CC_BY_NC_PERMISSION_UNRESOLVED`. |
| 12 | Focused, non-host, staged, exact-host, and full regression results are retained without masking defects or parallel memory-heavy installs. | ✓ VERIFIED | Final retained logs show focused 16 passed, host 2 passed, non-host 490 passed/3 deselected, and stage validation passed; the verifier executes serially and the live follow-up focused suite passes 27 tests. |

**Score:** 12/12 truths verified.

## Required Artifacts

| Artifact | Status | Details |
|---|---|---|
| `tests/integration/test_phase7_installed_e2e.py` | ✓ EXISTS + SUBSTANTIVE | Installed ARS smoke, representative journey, crash/resume, and cold replay tests. |
| `tests/staged/test_phase7_qualification.py` | ✓ EXISTS + SUBSTANTIVE | Source-hidden stage, lock, hook, MCP, host, inventory, SBOM, and release-boundary probes. |
| `build/evidence/phase-07/installed-qualification.json` | ✓ EXISTS + VERIFIED | Technical PASS, external ARS/stage/lock/host digests, no secrets/absolute paths. |
| `tests/integration/test_phase7_fault_matrix.py` | ✓ EXISTS + SUBSTANTIVE | Serial 18-scenario fault and replay assertions. |
| `tests/fixtures/recovery/phase7_faults` | ✓ EXISTS + VERIFIED | Stable fault IDs and expected recovery classifications. |
| `build/evidence/phase-07/recovery-matrix.json` | ✓ EXISTS + VERIFIED | Serial matrix with bounded retries and technical PASS. |
| `tests/fixtures/phase6/representative-run` | ✓ EXISTS + VERIFIED | Deterministic scientific journey records. |
| `build/evidence/phase-07/representative-dossier.json` | ✓ EXISTS + VERIFIED | Canonical dossier with review/dissent and human-resolution hashes. |
| `build/evidence/phase-07/representative-dossier-replay.json` | ✓ EXISTS + VERIFIED | Warm/cold replay comparison and projection-loss result. |
| `scripts/verify-phase-7` | ✓ EXISTS + SUBSTANTIVE | Serial, owned-root, fail-closed aggregate verifier. |
| `tests/integration/test_phase7_verifier.py` | ✓ EXISTS + SUBSTANTIVE | Positive, missing, stale, tamper, command-identity, and legal-block probes. |
| `build/evidence/phase-07-final-11/phase-7-verification.json` (content-addressed revision of the plan's `build/evidence/phase-07/phase-7-verification.json` target) | ✓ EXISTS + VERIFIED | Canonical append-only aggregate: technical `PASS`, release `BLOCKED`, `evidence_bound: true`; the revisioned root avoids overwriting earlier receipts. |

**Artifacts:** 12/12 verified.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Installed E2E tests | `src/arw/integration_lock.py` | External ARS lock and digest validation | ✓ WIRED | Installed receipt and lock digest are bound and tested. |
| `scripts/stage-plugin` | `scripts/qualify-codex-host` | Stage identity and locked host qualification | ✓ WIRED | Stage validation and exact host canary share the recorded stage/lock identity. |
| Fault matrix | `src/arw/recovery.py` | Registered `fault_id` scan/replay/recover classification | ✓ WIRED | All 18 scenario IDs are exercised serially with bounded retry outcomes. |
| `src/arw/runtime.py` | `src/arw/journal.py` | Parent-owned canonical append/fsync boundary | ✓ WIRED | Crash/replay tests verify canonical-before-host and non-tail fail-closed behavior. |
| Installed E2E | `src/arw/audit_dossier.py` | Canonical replay and dossier reconstruction | ✓ WIRED | Representative dossier and cold replay receipts are present and hash-bound. |
| `src/arw/review.py` | Representative fixture | Exact report hashes and dissent preservation | ✓ WIRED | Dossier retains four report hashes and minority/dissent reference. |
| `scripts/verify-phase-7` | Owned evidence root | Canonical digests and serial command receipts | ✓ WIRED | Final receipt has `evidence_bound: true` and four expected command identities. |
| `scripts/verify-phase-7` | `.planning/REQUIREMENTS.md` | VER-02/04/06/08 mapping | ✓ WIRED | Final receipt reports all four requirement statuses `PASS`. |

**Wiring:** 8/8 connections verified.

## Requirements Coverage

| Requirement | Status | Evidence / boundary |
|---|---|---|
| VER-02 | ✓ SATISFIED (technical) | Installed/staged qualification, external ARS lock, exact host canary, hooks/MCP/version evidence. |
| VER-04 | ✓ SATISFIED (technical) | 18-case serial recovery matrix, crash/replay tests, bounded retry and fail-closed corruption handling. |
| VER-06 | ✓ SATISFIED (technical) | Installed representative source→dossier journey with independent review, dissent, gate/human resolution, crash/resume, and cold replay. |
| VER-08 | ✓ SATISFIED (qualification behavior) | Aggregate verifier fails closed on missing/tampered/incompatible evidence and keeps the unresolved legal release verdict blocked. |

**Coverage:** 4/4 Phase 7 requirements technically satisfied.

## Anti-Patterns Found

None in the final reviewed Phase 7 scope. Code review status is `clean`; the
final remediation review reports no remaining HIGH or MEDIUM findings. The
working tree still contains unrelated/pre-existing Phase 4 and 04.1 changes;
they were not folded into this verification commit.

## Human Verification Required

### Legal and accountable approval

**Test:** Supply and append canonical intended-use, distribution class,
accountable human approval, and CC BY-NC permission evidence for the external
ARS content, then rerun the release gate.

**Expected:** The legal receipt is independently authorized and hash-bound;
until then `release_qualification` remains `BLOCKED`.

**Why human:** Intended use, distribution permission, and accountable approval
cannot be fabricated or inferred from local test output.

## Gaps Summary

No technical gaps found. Phase 7 technical qualification is complete. Release
qualification remains intentionally blocked by the named legal/permission
gates; this is the required fail-closed result, not a technical failure.

## Verification Metadata

**Verification approach:** Goal-backward with retained serial verifier evidence.
**Must-haves source:** Four Phase 7 PLAN.md `must_haves` blocks and ROADMAP
success criteria.
**Automated checks:** Focused follow-up 27 passed; retained final logs show
16 focused passed, 490 non-host passed with 3 host tests deselected, 2 exact
host/staged probes passed, and stage validation passed.
**Human checks required:** 1 legal/accountable approval gate.
**Decision coverage:** No trackable decisions in `07-CONTEXT.md` (GSD query
returned `skipped: true`, `total: 0`).
**Final evidence:** `build/evidence/phase-07-final-11/phase-7-verification.json`.

---
*Verified: 2026-07-16T03:53:18Z*
*Verifier: Codex GSD phase verifier*
