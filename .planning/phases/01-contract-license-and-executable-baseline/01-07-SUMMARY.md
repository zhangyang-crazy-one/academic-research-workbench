---
phase: 01-contract-license-and-executable-baseline
plan: 07
subsystem: build-identity-verification
tags: [json-schema, sha256, build-identity, codex-plugin, evidence, legal]

requires:
  - phase: 01-contract-license-and-executable-baseline
    provides: Installed native MCP, three sanitizer evidence domains, legal classifier, and canonical runtime from Plans 01-06
provides:
  - Deterministic registry for all eight Phase 1 Draft 2020-12 schemas
  - Stage-relative packaged identity and installed version report
  - Identity-named, technical/release-separated Phase 1 evidence dossier
affects: [phase-02-runtime-lifecycle, phase-03-files-data-plane, release-audit, installed-qualification]

tech-stack:
  added: []
  patterns:
    - Checked-schema regeneration with aggregate SHA-256 over ordered path/digest pairs
    - Build identity generated after required source, native, legal, wheelhouse, and schema evidence exists
    - Installed version reads only launcher-provided stage-relative resources
    - Identity-named evidence dossier with technical PASS and independent release BLOCKED

key-files:
  created:
    - src/arw/schema_registry.py
    - src/arw/build_identity.py
    - schemas/v1/build-identity.schema.json
    - schemas/v1/version-report.schema.json
    - scripts/verify-phase-1
  modified:
    - src/arw/cli.py
    - bin/arw
    - scripts/stage-plugin
    - scripts/smoke-staged-plugin
    - SBOM.cdx.json
    - supply-chain/use-distribution.json

key-decisions:
  - "Phase 1 identity is a stage payload, not a source constant; installed version rejects absent, outside-root, symlinked, or schema-invalid identity bytes."
  - "Schema resources are independently checked with Draft 2020-12 and an aggregate digest over all eight contracts."
  - "Technical qualification requires all retained evidence gates; release qualification remains BLOCKED until human legal evidence resolves SUP-04."

patterns-established:
  - "The stage inventory includes build-identity.json but identity staged_payloads intentionally exclude itself to avoid recursive hashing."
  - "The final dossier is stored under build/evidence/phase-01/<build-identity-sha256>/ and copies every mandatory raw evidence domain."

requirements-completed: [PKG-04, VER-01]

duration: 10 min
completed: 2026-07-13
---

# Phase 1 Plan 7: Final Build Identity and Evidence Gate Summary

**The plugin now reports a validated packaged build identity from installed bytes, while the final Phase 1 gate retains every required evidence domain under that identity and honestly separates technical PASS from release BLOCKED.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-13T08:13:19Z
- **Completed:** 2026-07-13T08:23:06Z
- **Tasks:** 3
- **Files modified:** 15

## Accomplishments

- Added strict build-identity and version-report contracts, plus an eight-schema registry that validates Draft 2020-12 schemas, rejects contract-surface drift, regenerates deterministic projections, and computes an aggregate digest.
- Added independent Python manifest and native MCP fixture validation with `jsonschema`; deliberate extra fields and incompatible version command edits fail.
- Generates `share/arw/build-identity.json` only after the stage verifies source/native/legal evidence, schema generation, current native binary, wheelhouse, and exact staged payloads.
- Added `arw version --json`; the installed launcher supplies only stage-relative plugin, schema, and identity locations. The runtime rejects absent, outside-root, symlinked, or invalid identity resources.
- Added `verify-phase-1`, which stages, installed-version-smokes, validates all mandatory retained domains, and writes an identity-named dossier with technical PASS/release BLOCKED summaries.
- Re-ran the legal gate after the new first-party wheel, updated the SBOM provenance hash, and preserved the unresolved SUP-04 release block.

## Task Commits

1. **Task 1: Deterministic schemas and independent validation** - `d9e16da` (feat)
2. **Task 2: Packaged build identity and installed version JSON** - `468c5aa` (feat)
3. **Task 3: Clean integrated walking-skeleton evidence gate** - `237fc67` (feat)

## Files Created/Modified

- `src/arw/schema_registry.py` - Schema loading, independent validation, deterministic projection, aggregate hashing, and packaged-schema support.
- `schemas/v1/build-identity.schema.json`, `schemas/v1/version-report.schema.json` - Strict identity/report contracts with no unknown fields.
- `src/arw/build_identity.py`, `src/arw/cli.py`, `bin/arw` - Stage-relative identity loading and installed `version --json` output.
- `scripts/stage-plugin`, `scripts/smoke-staged-plugin` - Build identity generation, schema staging, installed version smoke, and exact inventory binding.
- `scripts/verify-phase-1`, `tests/integration/test_phase1_walking_skeleton.py` - Identity-named raw-evidence dossier and end-to-end assertion.
- `SBOM.cdx.json`, `supply-chain/use-distribution.json` - Current first-party wheel provenance closure without altering release authorization semantics.

## Decisions Made

- The build identity uses relative paths and SHA-256 digests for component revisions, ordered patches, native binary, wheelhouse, schema set, three sanitizer domains, legal/pre-vendor receipts, and every staged payload except identity itself.
- `ARW_BUILD_IDENTITY`, `ARW_SCHEMA_ROOT`, and `ARW_PLUGIN_ROOT` are set only by the installed launcher. They are validation inputs, never fallback source paths.
- The final verifier treats missing evidence domains, non-PASS native/legal verdicts, or a release value other than BLOCKED as Phase 1 failures under the currently unresolved legal state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Closed SBOM provenance after the new first-party runtime wheel**
- **Found during:** Final legal gate rerun
- **Issue:** Build identity and installed version code changed the first-party wheel digest, leaving `use-distribution.json` with the prior technical SBOM hash.
- **Fix:** Re-ran `scripts/license-gate` and updated the sole affected `technical-provenance-only` SBOM digest.
- **Verification:** Legal gate reported technical PASS/release BLOCKED; license, inventory, schema, version, and walking-skeleton tests passed.
- **Committed in:** `237fc67`

---

**Total deviations:** 1 auto-fixed provenance closure.
**Impact on plan:** Identity, legal, and installed-byte claims now reference the same first-party wheel generation; no release authorization was inferred.

## Issues Encountered

- Full repository runs retain large exact-stage pytest copies. A dedicated `/tmp` base directory was used and removed after verification to avoid quota-only failures; the final run completed normally.

## Authentication Gates

None for the final identity/version/dossier gate. It uses local exact-stage installation and does not require a model-authenticated route invocation.

## Known Stubs

None for PKG-04/VER-01. Future lifecycle, file-plane, orchestration, graph, and scientific-integrity behavior remains intentionally assigned to later phases.

## Verification

- Schema drift and cross-language contracts: `4 passed`.
- Installed version, walking skeleton, and legal classifier subset: `8 passed in 74.03s`.
- Formal gate: `./scripts/verify-phase-1 --clean --evidence-root build/evidence/phase-01` completed with identity `b482dcbbb44390d238b3dadca34aeb4394e42cbe607222abbc34fb246061b539`, technical `PASS`, release `BLOCKED`.
- Full repository regression: `53 passed in 115.19s`.
- Legal gate: technical `PASS`; release `BLOCKED` because intended use, distribution class, accountable approval, and compatible permission evidence remain absent.

## Next Phase Readiness

- Phase 1 is complete: PKG-01 through PKG-04, SUP-01 through SUP-05, RUN-01/RUN-02, FILE-05, and VER-01 have executable evidence.
- Phase 2 can now add lifecycle/checkpoint semantics using the installed identity and sole-writer boundary without weakening source, native, or release claims.
- The repository remains private, but release must stay blocked until SUP-04 is resolved with accountable external evidence.

## Self-Check: PASSED

- All declared contracts, registry, packaged identity, version launcher, verifier, tests, and dossier paths exist.
- All three task commits are present, and the formal identity is present under `build/evidence/phase-01/`.
- Test counts, legal status, and verification claims match the executed outputs.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
