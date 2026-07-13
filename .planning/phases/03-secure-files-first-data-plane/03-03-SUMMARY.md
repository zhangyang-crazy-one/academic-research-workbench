---
phase: 03-secure-files-first-data-plane
plan: 03
subsystem: files-mcp
tags: [mcp, read-only, one-root, descriptors, cursors, live-freshness]

requires:
  - phase: 03-secure-files-first-data-plane
    plan: 02
    provides: Registered roots, cursor keys, selected immutable generations, stable IDs, and native publication validation
provides:
  - Installed one-root line-delimited JSON-RPC MCP profile with exactly five read-only tools
  - Live descriptor-safe list_files and bounded byte/line read_file
  - MAC-bound restart-safe list/read continuations and no-body stale conflicts
  - Query-side deadline, size, root, identity, sensitive-path, symlink, and startup integrity gates
affects: [03-04-research-retrieval, 03-05-security-qualification]

tech-stack:
  added: []
  patterns:
    - Query MCP is shipped in the hash-locked first-party wheel and started through the installed bootstrap runtime
    - One process snapshots one root and one selected generation before reading stdin
    - Live bytes are opened component-by-component with O_NOFOLLOW and descriptor/path identity rechecks
    - Continuations bind operation, root, query, generation, file, digest, range mode, position, and expiry

key-files:
  created:
    - src/arw/files_mcp.py
  modified:
    - src/arw/files.py
    - scripts/file-base-mcp
    - bin/arw
    - tests/integration/test_files_mcp.py
    - tests/staged/test_mcp_launcher.py

key-decisions:
  - "The dedicated files MCP runs from the locked Python wheel instead of patching the upstream generic native MCP; the existing native binary remains the Phase 1 compatibility server and generation publication gate."
  - "The new launcher mode requires exactly one ARW_FILES_CONTROL_ROOT and ARW_FILES_ROOT_ID pair; partial or repeated capabilities fail startup."
  - "Byte range content is base64 with encoding=bytes; line ranges require strict UTF-8 and never return partial content on encoding or budget failure."
  - "List exposes selected metadata plus live digest/freshness; read returns live bytes only and a digest conflict structurally has no content or cursor."

patterns-established:
  - "Use the hidden installed `_files-mcp` bootstrap command only from scripts/file-base-mcp; it is not an MCP tool or administrative API."
  - "Preserve the CBM_* launcher path as an explicit Phase 1 compatibility profile until final installed migration evidence closes it."

requirements-completed: []

duration: 25 min
completed: 2026-07-14
---

# Phase 3 Plan 3: One-Root Read-Only Files MCP Summary

**An installed process now advertises exactly five files tools while list/read are live, bounded, restart-safe, and incapable of query-side synchronization or mutation.**

## Accomplishments

- Added strict startup validation for one registered root, one selected generation, manifest/identity/database digests, SQLite integrity, and one 32-byte parent-created cursor key.
- Added exact `list_files`, `read_file`, `search_files`, `get_outline`, and `get_context` discovery with no crawl, sync, extraction, repair, rebuild, or upstream indexing aliases.
- Added deterministic stable-order list pagination and live freshness metadata without body-derived list fields.
- Added descriptor-safe live reads, byte and line ranges, strict UTF-8 handling, output ceilings, MAC continuations, digest conflict results, and five-second no-partial deadlines.
- Added a staged-wheel test proving the installed launcher starts the profile without importing source bytes and leaves root/control trees unchanged.

## Task Commits

1. **Task 1: Define one-root files MCP behavior** - `aba8da3` (test)
2. **Task 2: Implement installed read-only profile and live list/read** - `ef16e1e` (feat)
3. **Task 3: Qualify installation and harden cursor/deadline/startup boundaries** - `0d74d52`, `4ba71fe` (test/fix)

## Deviations from Plan

### Architecture Deviation

**Dedicated MCP implemented in the locked Python package; no native patch `0004` was added.**
- Patching the upstream generic MCP would require retaining or conditionally hiding a broad write-capable registration and dispatch surface.
- The first-party Python server installs only five descriptors, has no administration imports in its dispatch table, uses descriptor-relative no-follow opens, and is exercised from exact staged wheel bytes.
- The pinned native binary remains responsible for Phase 1 confined-read compatibility and the Plan 02 read-only generation publication gate. Adding an unused native patch would increase source identity and audit surface without strengthening the active trust boundary.

### Auto-fixed Issues

**1. [Security] Rejected duplicate startup capability arguments**
- `argparse` otherwise accepts repeated options and keeps the final value.
- Startup now requires each root capability option exactly once, with an executable duplicate-root test.

**2. [Security] Added one request-wide live verification deadline**
- File size was bounded, but a page of many files could exceed the response-time ceiling.
- List/read now share the contract's five-second deadline and emit no partial page/body on timeout.

**3. [Testing] Kept staged tests independent of the source test package**
- `tests/staged` intentionally is not a Python package.
- Installed evidence helpers are local and the launched wheel runs with PYTHONPATH unset.

## Verification

- Focused MCP, launcher, confinement, and schema suite - `30 passed`.
- Full Plan 01-03 unit/schema/admin/generation/MCP/confinement/staged regression - `97 passed`.
- Installed files profile subset - `3 passed`.
- `UV_OFFLINE=1 ./scripts/verify-sources` - passed.
- Root and control snapshots remained byte-identical across initialize, tools/list, forbidden tools, list, read, restart continuation, and staged launch.
- `git diff --check` - passed.

## Next Plan Readiness

- Plan 03-04 can reuse the immutable generation snapshot, SQLite path, cursor codec, live digest helper, exact tool dispatch, and deadline handling.
- `search_files`, `get_outline`, and `get_context` are advertised but deliberately return typed `tool_not_ready` until their Plan 03-04 implementations land.
- FILE-01, FILE-02, and agent-facing FILE-08 have implementation evidence; final requirement closure remains deferred to `verify-phase-3`.

## Self-Check: PASSED

- Exact tools, one-root startup, no-write snapshots, cursors, ranges, stale conflicts, malformed UTF-8, sensitive paths, and deadlines are executable.
- Existing Phase 1 native confinement and staged launcher behavior remain green.
- No query handler invokes sync, rebuild, repair, extraction registration, or pointer selection.

---
*Phase: 03-secure-files-first-data-plane*
*Completed: 2026-07-14*
