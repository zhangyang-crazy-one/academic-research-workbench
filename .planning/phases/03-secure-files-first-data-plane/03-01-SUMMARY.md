---
phase: 03-secure-files-first-data-plane
plan: 01
subsystem: files-first-contracts
tags: [files, json-schema, identity, generation, cursor, native-contract]

requires:
  - phase: 02-durable-provenance-runtime
    provides: Strict model/schema conventions, canonical JSON, evidence infrastructure, and frozen offline tests
provides:
  - Strict cross-language contracts for all five files MCP operations and parent generation administration
  - Deterministic stable file identity reconciliation and generation/extraction failure taxonomy
  - MAC-bound operation/query/generation/read cursors with hard server ceilings
  - Generated C header binding exact tools, modes, limits, versions, and checked schema digests
affects: [03-02-files-administration, 03-03-native-files-mcp, 03-04-research-retrieval, 03-05-security-qualification]

tech-stack:
  added: []
  patterns:
    - Checked Draft 2020-12 schemas are generated from frozen strict Pydantic models
    - Native constants are generated from checked schema bytes and versioned Python constants
    - Stale read conflicts are a discriminated no-body result variant

key-files:
  created:
    - src/arw/file_models.py
    - src/arw/file_contracts.py
    - generated/file-contracts.h
    - scripts/generate-file-contract-header
    - tests/fixtures/files-first/
  modified:
    - src/arw/schema_registry.py
    - tests/schema/test_files_contracts.py

key-decisions:
  - "Same-path identity wins; then unique descriptor identity; then one-to-one digest rename. Duplicate or ambiguous digest matches are delete/create."
  - "Every cursor is canonical, MAC-bound, expiring, operation/query/root/generation-specific, and read cursors additionally bind file, digest, and range mode."
  - "A stale_conflict read schema structurally cannot carry content or continuation fields."
  - "Ordinary unsupported/extraction failures degrade one document; descriptor, confinement, database, manifest, or schema failures block promotion."

patterns-established:
  - "Run `scripts/generate-file-contract-header --check` whenever a files schema or contract constant changes."
  - "Later Phase 3 integration suites have explicit owning-plan skips rather than false-green placeholders."

requirements-completed: []

duration: 23 min
completed: 2026-07-14
---

# Phase 3 Plan 1: Files-First Contracts Summary

**One strict identity, freshness, generation, extraction, pagination, and five-tool contract now governs Python, JSON Schema, and the future patched native profile.**

## Accomplishments

- Added deterministic file identity reconciliation covering same-path updates, OS-identity rename, unique-digest rename, duplicate isolation, and ambiguity delete/create.
- Added strict parent administration and five-tool request/result models, including hard ceilings, exact/full-text separation, no-body stale conflicts, deterministic generation manifests, extraction eligibility, and promotion receipts.
- Added 15 checked Draft 2020-12 schemas and registered them without changing existing Phase 1/2 contracts.
- Added a synthetic multilingual research fixture corpus and collectable Wave 0 tests for administration, MCP, formats, races, budgets, and private canaries.
- Added a deterministic generated C header with exact tool names, modes, limits, tokenizer/ranking versions, individual schema digests, and an aggregate contract digest.

## Task Commits

1. **Task 1: Establish the complete Phase 3 Wave 0 RED corpus** - `47b9844` (test)
2. **Task 2: Implement strict Python and JSON Schema file contracts** - `24d0b39` (feat)
3. **Task 3: Generate and verify the native contract boundary** - `0e8fb63` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Execution Runtime] Recovered a silent executor run from filesystem evidence**
- **Found during:** Task 1
- **Issue:** The `gsd-executor` ran for 15 minutes without a completion signal or response to an interrupt request.
- **Fix:** Applied the execute-phase spot-check fallback, preserved its complete RED corpus commit, closed the agent, and executed Tasks 2/3 inline.
- **Verification:** Commit `47b9844` contained all 35 Wave 0 files; 34 tests collected and the focused contract suite failed only for absent production modules before implementation.

**2. [Rule 1 - Correctness] Allowed nullable integrity-failure paths without weakening path confinement**
- **Found during:** Task 2 GREEN run
- **Issue:** The shared relative-path validator rejected `None` for generation-wide integrity failures.
- **Fix:** Optional paths bypass normalization only when absent; every non-null path still uses strict POSIX root-relative normalization.
- **Verification:** Focused schema/model suite passed `27` tests and full unit/schema regression passed `68` before Task 3.

**3. [Rule 2 - Missing Critical] Added explicit generator tamper tests**
- **Found during:** Task 3 acceptance review
- **Issue:** Wave 0 covered schema/model regeneration but did not yet exercise header `--check`, header drift, or checked-schema drift.
- **Fix:** Added subprocess generation/check tests, exact macro assertions, and schema-tamper failure coverage before implementing the generator.
- **Verification:** Native contract subset observed RED, then the complete unit/schema suite passed `71` tests.

## Verification

- `UV_OFFLINE=1 ./scripts/generate-file-contract-header --check` - passed.
- Plan contract/schema/generation suite - `27 passed`.
- Full unit/schema regression - `71 passed`.
- Later Phase 3 integration Wave 0 modules - `13 tests collected` under explicit Plan 03-02 through 03-05 ownership.
- `git diff --check` - passed.

## Next Plan Readiness

- Plan 03-02 can consume `FileRoot`, `FileIdentityManifest`, `FileGenerationManifest`, `ExtractionRegistration`, `FileAdminReceipt`, identity reconciliation, promotion validation, and `generated/file-contracts.h`.
- No Phase 3 requirement is marked complete yet; this plan intentionally establishes the executable contract and Wave 0 foundation.

## Self-Check: PASSED

- All three task commits and declared contract artifacts exist.
- Checked schemas regenerate byte-stably and the native header fails closed on drift.
- Stale conflicts, duplicate identity, cursor binding, extraction invalidation, and generation blocking have executable tests.

---
*Phase: 03-secure-files-first-data-plane*
*Completed: 2026-07-14*
