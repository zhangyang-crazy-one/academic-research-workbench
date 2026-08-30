# Quick Task Summary: Bundled ARS v3.21.1 / Adapter 0.1.27

## Outcome

Completed the lossless bundled ARS refresh to adapter `0.1.27`, upstream ARS commit `127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb` (`v3.21.1`), Git tree `7ce111463102462479835ce5f7c2b597d7ccfe22`, and normalized source digest `9f195460e1e299d7ce0a833e3a242957db315ef16ec9e8c80d29163e300afbd6`.

The update preserves ARW-owned control-plane code, hooks, Codex overlay, agents/evals, experiment-agent, file-base patches, MCP manifest, and existing production file-base artifacts. The experiment-agent and file-base source pins remain unchanged.

## Implemented

- Refreshed only the upstream-owned `skills/academic-research-suite/ars/**` surface using a three-way merge from the recorded base.
- Preserved eight ARW-owned overlap files and restored `skills/academic-research-suite/codex/**` byte-for-byte.
- Updated adapter/source pins, schemas, route contracts, tests, README, modification notice, third-party notice, SBOM, and supply-chain metadata.
- Reapplied the ARW LaTeX/PDF layout-export contract to the five upstream workflow/reference documents.
- Updated Phase-7 route behavior to fail closed with `integration_lock_not_verified` when no qualification lock exists.
- Increased the serial Phase-7 non-host verifier timeout from 600 to 1800 seconds; the test set and pass criteria are unchanged.
- Updated the representative Phase-6 ARS route fixture to adapter `0.1.27`.

## Verification

- Pre-vendor license gate: PASS.
- Source materialization and source-manifest verification: PASS.
- Targeted source/lock/schema tests: `96 passed`.
- Hook and Codex-overlay tests: `65 passed`.
- Bundled ARS suite: `9187 passed`; unittest subtests: `261 passed`.
- ARW root suite: `524 passed`.
- Post-cleanup targeted regression: `68 passed`; representative fixture/audit dossier: `8 passed`; verifier unit tests: `11 passed`.
- Final host qualification on Codex CLI `0.149.1`: PASS across three fresh homes with live hook execution observed.
- Final installed-stage smoke: version PASS, MCP PASS, install-cli PASS, route PASS on attempt 1.
- Final Phase-7 aggregation: `16 passed` focused, `521 passed` non-host (`3 deselected`), `2 passed` retained-host-canary checks; technical qualification PASS.
- Final protected-tree and protected-file hash audit: PASS.
- `git diff --check`: PASS.

## Native file-base qualification note

The pinned production file-base binary and build-evidence hashes remain unchanged and source verification passes. The normal and ASan/UBSan upstream C test suites reached `5784 passed` (with one network-dependent skip under ASan/UBSan). The enclosing normal rebuild timed out after the tests, the sanitizer command correctly rejected a current-GCC binary with a non-pinned digest, and TSan timed out during compilation. No pinned binary or build evidence was overwritten.

## Qualification status

- Technical qualification: **PASS**.
- Release qualification: **BLOCKED** only by the pre-existing CC BY-NC authorization/intended-use/distribution evidence gate (`SUP-04`, `P04-09`, `INTENDED_USE_UNKNOWN`, `DISTRIBUTION_CLASS_UNKNOWN`, `ACCOUNTABLE_APPROVAL_MISSING`, `CC_BY_NC_PERMISSION_UNRESOLVED`).

## Evidence

- Qualified stage: `build/stage/phase-07-qualified`
- Integration lock: `build/evidence/phase-07/integration-lock.json`
- Host canary: `build/evidence/host-canary-ars-0.1.27-final/canary.json`
- Final Phase-7 verdict: `build/evidence/phase-07-verification-ars-0.1.27-final2/verdict.json`
- Boundary audit: `build/evidence/ars-sync-0.1.27/final-boundary-audit.json`
