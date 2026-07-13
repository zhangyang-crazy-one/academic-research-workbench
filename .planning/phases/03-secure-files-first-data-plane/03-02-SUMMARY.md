---
phase: 03-secure-files-first-data-plane
plan: 02
subsystem: files-administration
tags: [files, generations, sqlite, extraction, native, atomic-promotion]

requires:
  - phase: 03-secure-files-first-data-plane
    plan: 01
    provides: Strict file, identity, generation, extraction, receipt, cursor, and native-header contracts
provides:
  - Parent-only root and extraction registration under `arw files`
  - Descriptor-safe inventory, stable logical identity reconciliation, immutable SQLite generations, and atomic selection
  - Failure receipts and prior-generation retention at deterministic pre-promotion barriers
  - Ordered native `files-build` publication gate bound to the generated contract header and pinned source tree
affects: [03-03-native-files-mcp, 03-04-research-retrieval, 03-05-security-qualification]

tech-stack:
  added: []
  patterns:
    - Parent administration owns every generation write; query paths never synchronize or repair
    - Generation candidates are sibling directories closed and checked before atomic pointer replacement
    - PDF body text is admitted only through immutable version-matching UTF-8 extraction registrations
    - Native publication opens candidate SQLite read-only and is not an MCP method

key-files:
  created:
    - src/arw/files.py
    - vendor/patches/file-base/0003-phase3-generation-builder.patch
  modified:
    - src/arw/cli.py
    - scripts/build-file-base
    - vendor/source-manifest.json
    - tests/integration/test_files_admin.py
    - tests/integration/test_file_generations.py

key-decisions:
  - "Python parent administration builds the disposable projection; native files-build is a source-bound, read-only publication gate and never selects a generation."
  - "The public administrative syntax is `arw files root register` and `arw files extraction register`; sync, rebuild, repair, and status remain parent-only commands."
  - "Registered extraction persistence excludes computed convenience fields so immutable bytes validate against the strict input schema."
  - "Builds that need the 1.3GB pinned source tree use a worktree-external TMPDIR; repository-internal temporary copies are rejected by patch identity checks."

patterns-established:
  - "Invoke the native builder only after identity, SQLite, and generation manifests are closed."
  - "Run `verify-sources` after every ordered native patch and rebaseline generated binary/evidence digests only through `build-file-base`."

requirements-completed: []

duration: 67 min
completed: 2026-07-14
---

# Phase 3 Plan 2: Parent Generation Administration Summary

**Explicit parent commands now build, validate, retain, and atomically select immutable file generations without exposing mutation through MCP.**

## Accomplishments

- Added strict root registration, extraction registration, status, sync, rebuild, and repair commands under `arw files`.
- Added descriptor-relative no-follow inventory, stable identity transitions, ignore handling, stale-row removal, extractor-version invalidation, SQLite integrity checks, immutable receipts, and atomic selected-generation pointers.
- Added deterministic barriers proving failed candidates cannot replace the selected generation or alter the research root.
- Added ordered patch `0003` with a non-MCP `files-build` gate that rejects duplicate roots, unsafe candidates, ownership violations, incomplete candidates, and corrupt databases.
- Rebuilt the native binary under network denial and bound the patch SHA, post-patch tree, binary, build evidence, and generated contract header into verification.

## Task Commits

1. **Task 1: Define generation administration behavior** - `8746348` (test)
2. **Task 2: Implement parent generation administration** - `70b78e6` (feat)
3. **Task 3: Bind native generation publication gate** - `a5ec3e5` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Correctness] Made duplicate-rename ambiguity test remove inode evidence**
- The initial test used two filesystem renames, which were unambiguous because each retained a unique inode.
- The fixture now copies duplicate bytes and deletes both originals, correctly exercising delete/create ambiguity.

**2. [Contract] Excluded computed extraction fields from immutable registration bytes**
- Pydantic serialization included `search_eligible`, but the strict validation schema correctly forbids it as input.
- Canonical file-model persistence now writes declared contract fields only.

**3. [Compatibility] Extended staged schema identity without weakening prior gates**
- Phase 3 added 15 checked schemas beyond the Phase 2 count of 22.
- The current identity requires all 37 schemas while the historical Phase 2 verifier requires retention of at least its original 22-schema baseline.

**4. [Resource] Moved the reproducible native build outside tmpfs and the Git worktree**
- `/tmp` exhausted space during final linking, and a repository-internal TMPDIR was correctly rejected because patch application discovered the parent Git tree.
- A worktree-external `/home` cache completed the same offline build; temporary bytes were removed after verification.

## Verification

- Parent administration/unit suite - `11 passed`.
- Native source, confinement, administration, and generation suite - `21 passed`.
- `UV_OFFLINE=1 ./scripts/verify-sources` - passed.
- Offline native build verdict - `PASS`, changed network namespace, zero network syscall attempts.
- Prior Phase 1/version/schema regression subset - `13 passed`.
- `git diff --check` - passed.

## Next Plan Readiness

- Plan 03-03 can open only `selected-generation.json`, the selected generation manifests, and `files.sqlite3` read-only.
- Stable `file_id`, source digest, extraction state, body eligibility, and generation identity are available for exactly-five-tool query responses.
- FILE-06 and the administrative half of FILE-08 have implementation evidence; final requirement closure remains deferred to the Phase 3 verifier.

## Self-Check: PASSED

- All three task commits exist and the worktree contains no uncommitted Plan 02 source changes.
- Failed candidates leave the previous pointer exact; successful candidates are complete before native attestation and promotion.
- The research root snapshot remains unchanged by administration.

---
*Phase: 03-secure-files-first-data-plane*
*Completed: 2026-07-14*
