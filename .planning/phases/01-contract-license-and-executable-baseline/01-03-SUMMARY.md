---
phase: 01-contract-license-and-executable-baseline
plan: 03
subsystem: supply-chain
tags: [licensing, vendoring, offline-build, digest-closure, provenance]
requires:
  - phase: 01-contract-license-and-executable-baseline
    plan: 01
    provides: pinned dependency locks and executable baseline
provides:
  - exact pinned upstream license gate with raw pre-vendor evidence
  - receipt-bound offline source materialization for all three upstreams
  - network-denied source verification and native file-base build
  - manifest closure over sources, patches, legal inputs, locks, wheelhouse, binary, and build evidence
affects: [01-04, 01-06, 01-07]
tech-stack:
  added: [ScanCode 32.5.0, strace 7.1]
  patterns: [pre-vendor legal gate, receipt-bound materialization, namespace-plus-syscall network denial, digest-closed source manifest]
key-files:
  created:
    - scripts/verify-sources
    - scripts/offline-exec
    - scripts/build-file-base
    - vendor/source-manifest.json
    - vendor/patches/file-base/0001-file-base-server-name.patch
    - vendor/sources/academic-research-skills
    - vendor/sources/experiment-agent
    - vendor/sources/file-base
    - schemas/v1/source-manifest.schema.json
    - tests/integration/test_pre_vendor_license_gate.py
    - tests/integration/test_source_materialization.py
    - tests/integration/test_digest_drift.py
  modified:
    - scripts/pre-vendor-license-gate
    - .gitignore
key-decisions:
  - Receipt-bound source archives are the only permitted input to materialization before vendor/sources exists.
  - Offline execution requires a changed network namespace plus syscall tracing and rejects every AF_INET or AF_INET6 attempt.
  - The generated file-base binary remains ignored while its exact digest and build-evidence digest are bound into the source manifest.
requirements-completed: [SUP-01, SUP-02]
metrics:
  duration: 39m
  completed: 2026-07-13
  tasks: 3
  files: 2877
---

# Phase 1 Plan 3: Pre-vendoring License Gate and Digest Closure Summary

Exact upstream snapshots are now admitted only after the pinned native legal gate succeeds, then reconstructed and built under independently evidenced network denial with every supply-chain input and output digest-closed by a strict manifest.

## Performance

- **Duration:** 39 minutes
- **Started:** 2026-07-13T02:45:10Z
- **Completed:** 2026-07-13T03:24:27Z
- **Tasks:** 3
- **Files changed:** 2,877

## Accomplishments

- Ran each exact pinned upstream legal workflow before populating `vendor/sources`, preserving native gate output, ScanCode results, policy checks, notices, and raw receipt evidence.
- Materialized the three audited source snapshots exclusively from receipt-bound archives while a denied network namespace and syscall trace proved no network-capable operation occurred.
- Applied and bound the exact file-base server-name patch, built the native binary offline, and closed the manifest over source trees, legal evidence, locks, wheelhouse, patch, binary, and build evidence.
- Added integration coverage that rejects pre-vendor ordering violations, network-capable commands, materialization drift, and mutations in every manifest-bound artifact class.

## Task Commits

1. **Task 1: Define vendoring and digest-closure contracts** — `fa82082` (`test`)
2. **Task 2: Execute the exact pinned pre-vendor license gate** — `636cd78` (`feat`)
3. **Task 3: Materialize and verify digest-closed offline sources** — `2a62e6e` (`feat`)

## Key Files Created/Modified

- `scripts/pre-vendor-license-gate` — executes each upstream's pinned legal workflow and emits a clean-tree-bound receipt.
- `scripts/offline-exec` — combines network-namespace denial with syscall auditing and fails on any Internet-family socket attempt.
- `scripts/verify-sources` — validates the strict manifest and every declared digest without fetching or rebuilding.
- `scripts/build-file-base` — reconstructs, patches, compiles, and promotes file-base under the offline runner.
- `vendor/source-manifest.json` — records exact source, legal, lock, wheelhouse, patch, binary, and artifact digests.
- `tests/integration/test_digest_drift.py` — proves mutations across all eight bound artifact classes fail verification.

## Verification

- `uv run pytest -q tests/integration/test_pre_vendor_license_gate.py tests/integration/test_source_materialization.py tests/integration/test_digest_drift.py` — **6 passed**.
- `./scripts/verify-sources` — **PASS**.
- Materialization evidence: `build/evidence/phase-01/materialize/verdict.json` — namespace denied, syscall audit enabled, no AF_INET/AF_INET6 attempts.
- Source-verification evidence: `build/evidence/phase-01/source/verdict.json` — **PASS** under the same denial controls.
- Native-build evidence: `build/evidence/phase-01/build/verdict.json` — **PASS** under the same denial controls.
- File-base binary SHA-256: `7cf325817f9f3520e6942dd929e2d18679655edd18b15af321c9fcf8c2dff2a3`.
- Build-evidence SHA-256: `4966d21903e8a81c3960a6955ae971964449879cc1c6ef38b16b03b95e24cad6`.

## Decisions Made

- Bound materialization to the pre-vendor legal receipt rather than accepting repository URLs or mutable working trees.
- Required both a distinct denied network namespace and syscall-level auditing; merely avoiding fetch commands is insufficient.
- Kept generated native output out of Git while preserving exact binary and provenance closure in the committed manifest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed ephemeral npm output before sealing the legal receipt**
- **Found during:** Task 3
- **Issue:** The upstream notice workflow left `graph-ui/node_modules` untracked, so the receipt tree digest included transient generated content.
- **Fix:** Removed the ephemeral tree after legal generation and required the pinned checkout to be fully clean before receipt sealing; reran the gate while `vendor/sources` was still absent.
- **Files modified:** `scripts/pre-vendor-license-gate`
- **Commit:** `2a62e6e`

**2. [Rule 1 - Bug] Corrected strict schema composition for extended artifact records**
- **Found during:** Task 3
- **Issue:** Referenced schemas with `additionalProperties: false` rejected the legal-input and artifact extension fields.
- **Fix:** Defined both strict object shapes directly, retaining required fields and unknown-key rejection.
- **Files modified:** `schemas/v1/source-manifest.schema.json`
- **Commit:** `2a62e6e`

**3. [Rule 1 - Bug] Avoided native-build path collision**
- **Found during:** Task 3
- **Issue:** The temporary output filename collided with the reconstructed `file-base` source directory.
- **Fix:** Emitted the compiler output as `file-base.bin` before verified promotion.
- **Files modified:** `scripts/build-file-base`
- **Commit:** `2a62e6e`

**4. [Rule 3 - Blocking] Supplied syscall tracing without changing host packages**
- **Found during:** Task 3
- **Issue:** The host had bubblewrap but no `strace`, preventing the required independent network-attempt audit.
- **Fix:** Verified and extracted the official signed Fedora strace RPM into ignored build tooling and used that exact binary for evidence collection.
- **Files modified:** none tracked; generated under `build/tools/strace`
- **Commit:** `2a62e6e` (runner integration)

**5. [Rule 3 - Blocking] Made exhaustive drift testing bounded and filesystem-safe**
- **Found during:** Task 3
- **Issue:** Recopying the 1.3 GB source bundle for every mutation stalled execution, and the first hard-link fixture crossed filesystem boundaries.
- **Fix:** Created one same-filesystem hard-linked candidate under ignored `build/`, unlinked each target before mutation, and restored it between all eight drift classes.
- **Files modified:** `tests/integration/test_digest_drift.py`
- **Commit:** `2a62e6e`

**6. [Rule 2 - Missing Critical Functionality] Ignored generated native output**
- **Found during:** Task 3
- **Issue:** The materialized `.file-base` binary and build record are generated verification outputs and would otherwise remain untracked.
- **Fix:** Added `.file-base/` to `.gitignore`; exact output digests remain committed in the source manifest.
- **Files modified:** `.gitignore`
- **Commit:** `2a62e6e`

## Authentication Gates

None.

## Known Stubs

None. The ignored native binary and evidence directories are generated outputs bound by committed digests, not placeholders.

## Deferred Issues

None.

## User Setup Required

None.

## Self-Check: PASSED

- All declared key scripts, schemas, manifests, patches, and source snapshots exist.
- Task commits `fa82082`, `636cd78`, and `2a62e6e` are present in repository history.
- The required integration suite and source verifier pass against the committed state.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
