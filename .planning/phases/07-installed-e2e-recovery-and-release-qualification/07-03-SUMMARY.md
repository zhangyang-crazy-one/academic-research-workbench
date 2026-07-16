---
phase: 07-installed-e2e-recovery-and-release-qualification
plan: 03
status: complete
requirements:
  - VER-06
commits:
  - b8ac51a
  - 47e06ca
---

# Phase 7 Plan 03 Summary

## Outcome

VER-06 now has one deterministic installed-package journey that traverses a
bounded source/access receipt, claim, imported experiment provenance,
figure/result artifact, four-seat independent review with retained minority
dissent, a failed gate, append-only human resolution evidence, a guarded
post-claim checkpoint, fresh replay, and a canonical audit dossier.  The local
ARS adapter is used only through the explicit external `ARW_ARS_ROOT` route
boundary and its bounded identity/input/output digests; ARW ledger, review,
gate, and dossier records remain canonical.

Technical qualification is `PASS`; release qualification remains `BLOCKED`
for `SUP-04`, `P04-09`, and `CC_BY_NC_PERMISSION_UNRESOLVED`.  No transcript,
credential, private full text, or absolute ARS/repository path is retained in
the fixture, ARS evidence, dossier, or replay comparison.

## Completed Tasks

### 07-03-T1 — Extend the Phase 6 representative fixture

- Added bounded fixture records for source/access, claim, figure/result,
  review/dissent, failed gate, human resolution, recovery checkpoint, and
  external ARS route evidence.
- Added strict panel/report/synthesis construction with exact report hashes,
  separate synthesizer identity, dissent preservation, stale-gate rejection,
  forged-report rejection, and append-only human decision shape validation.
- Existing Phase 6 dossier/review/human-gate suite remains green.

### 07-03-T2 — Installed ARS-backed journey through crash and resume

- The installed test uses the retained exact lock-bound stage from a
  source-hidden local marketplace, sets `ARW_ARS_ROOT` explicitly, disables
  networking, and runs the installed `bin/arw route --json` command.
- A guarded `phase7.journal-fsync` boundary leaves the parent-owned canonical
  checkpoint durable; a fresh `RuntimeCommandService` replays it before dossier
  assembly.  External ARS evidence is bounded and non-authoritative.
- Dossier assembly now passes typed experiment qualification receipts and the
  parent reproduction decision into the pure claim evaluator; graph lifecycle
  receipts are kept distinct from graph projection receipt references.

### 07-03-T3 — Cold replay after projection loss

- Fixed `replay_audit_dossier(..., projection_available=False)` to preserve an
  already parent-derived technical PASS while adding only the in-memory
  `projection_unavailable` blocker.
- Cold replay preserves exact report hashes, dissent, human/gate references,
  technical PASS, and legal release BLOCKED verdicts.
- Retained evidence:
  - `build/evidence/phase-07/representative-dossier.json`
  - `build/evidence/phase-07/representative-dossier-replay.json`
- Human-resolution references are derived from canonical `HumanDecisionRecord`
  bytes, and append-only dossier publication returns a content-addressed
  sibling when a prior retained receipt has a different stage identity.

## Verification

- `UV_OFFLINE=1 PYTHONNOUSITE=1 TMPDIR=$PWD/build/tmp/phase-07/e2e .venv/bin/python -m pytest -q tests/integration/test_phase7_installed_e2e.py tests/staged/test_phase7_qualification.py` — **7 passed**.
- Plan-level Phase 6, installed journey, staged qualification, and human-gate subset — **18 passed**.
- T1 focused fixture and journey — **2 passed**.
- T2 installed journey filter (`journey or crash or ars or review`) — **3 passed**.
- T3 cold replay filter (`cold or dossier or projection`) — **1 passed**.
- `git diff --check` — **passed**.

## Deviations from Plan

**[Rule 1 - Safety] Reused the retained exact lock-bound stage** — Found during:
07-03-T2 setup | Rebuilding from the dirty shared checkout would change the
wheel/runtime digest without a matching retained host canary and would fail
closed.  The fixture reuses `build/stage/phase-07-qualified` only when the
exact lock and canary are present; otherwise it invokes `stage-plugin` and the
journey fails closed if integration status is not PASS.  No package boundary
or qualification gate was weakened.  Verification: installed/staged suite
passed with the retained source-hidden stage.

**[Rule 1 - Correctness] Dossier claim evidence wiring** — Found during:
07-03-T2 dossier assembly | Qualification receipts and graph lifecycle
receipts were not forwarded to their respective pure claim gates, causing a
false technical BLOCKED result.  Passed the typed receipts through without
granting them write authority, and kept graph projection receipts separate
from lifecycle receipts.  Verification: installed journey and cold replay
passed; commit `b8ac51a`.

**[Rule 1 - Safety] Append-only dossier revision** — Found during: final
rerun | A prior retained dossier used a placeholder human-decision digest.
The fixture now derives the digest from canonical human bytes and publishes
the refreshed dossier under a content-addressed sibling instead of replacing
the retained receipt. Verification: representative journey/cold replay
passed; commit `47e06ca`.

**Total deviations:** 3 auto-fixed (safety/correctness/safety). **Impact:** bounded
installed evidence and sole-writer authority are preserved; no tests were
removed or xfailed.

## Authentication Gates

None.

## User Setup Required

None for technical qualification.  Release remains blocked pending the
documented accountable intended-use/distribution/permission evidence.

## Next Phase Readiness

Plan 07-04 can consume the representative dossier, replay comparison, exact
external ARS route evidence, and the existing Phase 7 lock/host/recovery
receipts for final serial aggregation and full-regression verification.

## Self-Check: PASSED

- Key fixture, test, dossier, and source files exist.
- Production commits `b8ac51a` and `47e06ca` are present.
- Plan acceptance and verification commands pass with no skip/xfail
  substitution.
- Technical PASS and legal release BLOCKED remain separate.

---
*Phase: 07-installed-e2e-recovery-and-release-qualification*
*Plan: 03*
*Completed: 2026-07-16*
