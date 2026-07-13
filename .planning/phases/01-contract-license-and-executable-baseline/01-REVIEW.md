---
phase: 01-contract-license-and-executable-baseline
reviewed: 2026-07-13
scope: Phase 01 implementation files and installed/evidence boundaries
status: passed-with-fixed-finding
---

# Phase 1 Code Review

## Result

No open Critical, Warning, or Info findings remain after the review fix in `21d13fc`.

## Fixed Finding

| Severity | Location | Finding | Resolution |
|---|---|---|---|
| Warning | `src/arw/build_identity.py` | The installed version path validated identity using staged schemas but did not verify that those schema bytes matched the identity's individual and aggregate digests. A changed staged schema could therefore weaken self-validation while leaving identity bytes unchanged. | `21d13fc` verifies every `schemas.files` entry is a regular file under the packaged schema root, checks each SHA-256, and checks the aggregate before returning identity. `tests/integration/test_version_report.py` now proves tampering is rejected. |

## Reviewed Areas

| Area | Evidence | Result |
|---|---|---|
| Package and wheel isolation | `bin/arw`, `scripts/stage-plugin`, staged tests | PASS: frozen hashes, no-index install, cache-local venv, source-independent launcher. |
| Native filesystem boundary | patch 0002, `tests/integration/test_mcp_confinement.py`, retained sanitizer evidence | PASS: typed no-content denials, descriptor-relative traversal, separate ASan+UBSan/TSan evidence. |
| Canonical runtime | `src/arw/canonical.py`, `journal.py`, recovery tests | PASS: sole-writer replay/hash/fsync and post-fsync kill evidence. |
| Build identity and installed version | `src/arw/build_identity.py`, `cli.py`, staged version tests | PASS after fixed schema digest binding. |
| Evidence/legal semantics | `scripts/verify-phase-1`, `license-gate`, use-distribution tests | PASS: all technical gates are explicit; release remains BLOCKED rather than inferred. |

## Residual Risk

- `verify-phase-1 --clean` creates a clean identity-named dossier from the current retained raw evidence. It verifies all domain verdicts and binds their digests into the packaged identity; rerunning expensive upstream native suites remains an explicit build operation, not an implicit verifier side effect.
- Release authorization remains externally blocked by SUP-04. This is an intentional legal state, not a software defect.

## Verification

- Focused schema/version/walking-skeleton tests: `3 passed` after the fix.
- Formal dossier gate: technical `PASS`, release `BLOCKED`.
- Full Phase 1 regression was rerun before this final review fix; the final focused tests cover the modified files.
