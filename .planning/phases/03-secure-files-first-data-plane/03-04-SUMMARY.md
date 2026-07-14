---
phase: 03-secure-files-first-data-plane
plan: 04
subsystem: research-retrieval
tags: [search, cjk, outline, context, pdf-extraction, freshness]

requires:
  - phase: 03-secure-files-first-data-plane
    plan: 03
    provides: One-root MCP, immutable generation snapshot, descriptor-safe live digest checks, and MAC cursors
provides:
  - Bounded exact and plain-text full-text retrieval over selected immutable generations
  - Deterministic CJK-capable normalization, ranking, pagination, snippets, and signed hit anchors
  - Markdown, LaTeX, BibTeX, and source outline adapters with typed no_structure fallback
  - Same-file, same-generation line context and registered-PDF-only text retrieval
  - Indexed/current digest plus extraction registration provenance on body-derived results
affects: [03-05-security-qualification, phase-05-evidence-queries]

tech-stack:
  added: []
  patterns:
    - SQLite generation databases open read-only and immutable with a write-denying authorizer and deadline progress handler
    - Search syntax is compiled from strict exact/full_text contracts and never interpolated from client grammar
    - Every body-derived response is suppressed unless the live source digest still matches the selected generation
    - Search hit anchors are deterministic MAC envelopes bound to generation, file, source digest, and location

key-files:
  modified:
    - src/arw/files_mcp.py
    - src/arw/file_models.py
    - schemas/v1/files-search-result.schema.json
    - schemas/v1/files-outline-result.schema.json
    - schemas/v1/files-context-result.schema.json
    - generated/file-contracts.h
    - scripts/build-file-base
    - vendor/source-manifest.json
    - tests/integration/test_files_formats.py

key-decisions:
  - "Exact search is NFC-normalized and case-sensitive; full_text is NFKC/casefolded plain-term matching under tokenizer/ranking v1."
  - "Current search hits return a signed hit_id usable by get_context; stale hits remove hit_id, score, location, and snippet together."
  - "BibTeX entries are structural nodes because D-14 explicitly includes them, despite one plan task describing BibTeX as unsupported."
  - "Raw PDF bytes are used only for source freshness hashing; searchable text comes exclusively from a complete, accessible, digest/version-matched parent registration."

requirements-completed: []

duration: 18 min
completed: 2026-07-14
---

# Phase 3 Plan 4: Deterministic Research Retrieval Summary

**All five files tools now provide bounded multilingual retrieval while stale or invalid source state structurally removes every body-derived field.**

## Accomplishments

- Added explicit exact and full-text search with UTF-8 input ceilings, fixed Unicode normalization, versioned tokenizer/ranking identifiers, deterministic score/file/location ordering, stable pagination, and no raw FTS grammar.
- Added live digest gates that retain only selected-generation metadata for changed, deleted, replaced, or inaccessible files; stale search hits contain no score, location, snippet, or hit anchor.
- Added deterministic Markdown, LaTeX, BibTeX, and source-code outlines with exact byte/line spans, parser versions, bounded continuations, and `no_structure` for plain text and extracted PDF text.
- Added signed search-hit and explicit-location context anchors bound to the same generation, file, and digest, with line and byte ceilings and no semantic or cross-file expansion.
- Added PDF retrieval through complete parent-registered UTF-8 extraction only, including extraction registration SHA-256 in search, outline, and context results; extractor-version changes degrade only the affected document.
- Regenerated six affected JSON Schemas and the native contract header, then rebuilt the native publication gate under denied networking with the contract digest included in build evidence.

## Task Commits

1. **Task 1: Define multilingual retrieval and stale-body behavior** - `7da1eeb` (test)
2. **Task 2: Implement search, freshness, formats, and anchored context** - `d9e3738` (feat)
3. **Task 3: Rebind the native publication binary to generated contracts** - `4430cc2` (build)

## Deviations from Plan

### Architecture Deviation

**No native patches `0005` or retrieval code in the generic upstream MCP were added.**
- Plan 03 established the dedicated five-tool server in the hash-locked first-party Python wheel because the upstream MCP carries a broad write-capable registration and dispatch surface.
- Search, outline, and context extend that active server and preserve its exact five-tool, no-administration boundary.
- The native binary remains the read-only candidate publication gate and was rebuilt solely to embed the changed generated contract identity. An unused native retrieval patch would add audit surface without executing in the installed profile.

### Auto-fixed Issues

**1. [Contract] Closed the search-hit to context loop**
- The context request accepted `hit_id`, but search results did not expose one.
- Search now returns a deterministic signed anchor for current hits and structurally removes it for stale hits.

**2. [Provenance] Added indexed and extraction identities to body-derived results**
- Outline/context lacked the indexed digest and extraction registration identity required by D-06 and D-13.
- Search, outline, and context schemas now carry the selected source digest and optional extraction-registration SHA-256.

**3. [Build] Made generated contracts a first-class native build input**
- The build script previously allowed rebaselining only when ordered patches changed.
- Build evidence now records `file_contract_sha256`, and contract changes authorize a deterministic binary/evidence rebaseline without weakening unchanged-input drift checks.

## Verification

- Focused retrieval, generation, MCP, schema, and model suite - `30 passed`.
- Plan 03-04 joint admin/generation/MCP/format/confinement/staged suite - `54 passed`.
- `UV_OFFLINE=1 ./scripts/verify-sources` - passed before and after native rebuild.
- Native build network namespace and syscall audit - technical `PASS`, zero network syscall attempts.
- New binary SHA-256 - `43b4a6f81c3d7888a94fe1e89caaf44c84e83ba02cd9d01c3af7b027b3f1efc7`.
- Generated contract header SHA-256 - `3cdc203ec0c762744995eb9f5b7d4652ca92eabfe7f824f32a98dbe0d091e7b1`.
- `python -m compileall`, generated-header drift check, and `git diff --check` - passed.
- Ruff was unavailable in the frozen environment; no dependency was added solely for linting.

## Next Plan Readiness

- Plan 03-05 can exercise all five implemented tools against stale canaries, malformed contracts, output ceilings, pointer/generation tampering, staged relocation, and projection rebuild.
- FILE-03, FILE-04, FILE-06, and FILE-07 have direct implementation coverage; final requirement closure remains owned by the Phase 3 verifier.

## Self-Check: PASSED

- Exact/full-text modes, CJK, deterministic order, pagination, four structural formats, no-structure fallback, hit/location context, PDF extraction registration, and extractor invalidation are executable.
- Changed files never return snippets, outlines, contexts, scores, locations, or hit identities.
- Query paths open the generation read-only and expose no sync, repair, extraction, rebuild, or pointer mutation operation.

---
*Phase: 03-secure-files-first-data-plane*
*Completed: 2026-07-14*
