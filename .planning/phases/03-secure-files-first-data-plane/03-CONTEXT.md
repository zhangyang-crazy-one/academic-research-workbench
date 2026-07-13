# Phase 3: Secure Files-First Data Plane - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 gives authorized agents a useful, bounded, provenance-aware file data
plane over declared research roots. It delivers stable file inventory, safe
current-byte and current-line reads, deterministic exact and full-text search,
format-aware outlines, anchored context windows, explicit extraction and
freshness state, and correct create/modify/rename/delete synchronization.

The agent-facing MCP remains read-only and one-root-per-process. Parent-owned
`arw files` commands create and validate disposable index generations. Canonical
run authority remains the Phase 2 ledger and immutable manifests; file tables,
FTS databases, extracted text, cursors, pointers, and generation metadata are
query projections or evidence, never workflow authority.

This phase does not add raw-PDF parsing or OCR, cross-file semantic/graph
retrieval, background mutation by the MCP, subagent execution, scientific gate
methodology, or a UI. Those capabilities remain in their assigned later phases
or v2 scope.

</domain>

<decisions>
## Implementation Decisions

### Root capability and administrative boundary
- **D-01:** One agent-facing MCP process exposes exactly one named allowed root.
  A request selects the configured capability identifier, never a filesystem
  path. Multiple roots require multiple independently confined MCP instances
  launched by the parent control plane.
- **D-02:** Administrative mutation exists only under a separate parent-owned
  `arw files` CLI. `crawl`, `sync`, `extract`, `rebuild`, and `repair` are not
  MCP tools and cannot be enabled by an agent request or query parameter.
- **D-03:** Refresh happens only at deterministic boundaries: run start, phase
  recovery, or an explicit `arw files sync`. Listing, reading, searching,
  outlining, and context retrieval never refresh or mutate an index implicitly.
- **D-04:** Build, extract, and validate a complete new index generation before
  atomically promoting it. A failed build leaves the prior generation selected,
  marks its freshness accurately, and emits an inspectable management receipt.

### Stable identity and freshness behavior
- **D-05:** Each file has a persistent logical `file_id`. An unambiguous rename
  retains that identity; same-content files remain distinct. Ambiguous rename
  evidence is represented as a delete plus a create rather than an inferred
  lineage.
- **D-06:** `list_files` and `read_file` observe the live filesystem through the
  confined descriptor-safe path. `search_files`, `get_outline`, and
  `get_context` query one atomically promoted generation and report that
  generation, indexed digest, extraction identity, and freshness.
- **D-07:** A stale indexed entry may expose identity, current/previous path,
  prior digest, change reason, and `sync_required`, but it must not return stale
  snippets, outlines, context, or other old body text to the agent.
- **D-08:** A read that follows an indexed result binds both `file_id` and
  `expected_digest`. Digest mismatch, identity mismatch, or replacement during
  the read returns a typed `stale_conflict` with no partial body.

### MCP query and continuation contracts
- **D-09:** Expose five separately authorizable, strictly versioned MCP tools:
  `list_files`, `read_file`, `search_files`, `get_outline`, and `get_context`.
  Do not combine them behind a mode-dispatched mega-tool or split this phase
  across MCP Resources and Tools.
- **D-10:** The first `read_file` request can select either a byte range or a
  line range. Continuation tokens bind allowed root, `file_id`, digest, range
  mode, and next position. List/search/context cursors bind the selected index
  generation and normalized query parameters.
- **D-11:** `search_files` requires an explicit `exact` or `full_text` mode.
  Exact and full-text hits are not implicitly mixed. Full-text tokenization and
  ranking are versioned, and ties use stable `file_id` plus source location.
  Raw backend FTS syntax is never accepted from a client.
- **D-12:** Every tool has server-owned hard ceilings for bytes, lines, hits,
  snippets, context, execution time, and cursor size; clients may only request
  lower values. Over-ceiling input is rejected before work. A successful page
  is complete within its declared boundary and carries a continuation; timeout
  returns a typed error, never an incompletely ranked half-page.

### Format structure and extraction provenance
- **D-13:** The MCP does not parse raw PDF bytes. The parent may register a
  UTF-8 PDF extraction only when it binds the original PDF digest, extractor
  name and version, extraction time, quality/access state, and extracted-text
  digest. The registered extraction then follows ordinary generation rules.
- **D-14:** Outlines are format-aware and deterministic: Markdown headings,
  LaTeX section commands, BibTeX entries, and source-code definitions map into
  one normalized node shape with kind, title, level, location, and parent.
  Plain text or extraction without declared structure returns `no_structure`;
  the runtime does not guess headings.
- **D-15:** `get_context` requires a search hit, source location, or outline
  node anchor. It returns the target, containing section/definition, and
  bounded neighboring text from the same file and generation. It does not
  perform cross-file semantic expansion.
- **D-16:** Ordinary parse/extraction failure may produce a promoted
  `degraded` generation when every failed file and reason is explicit. Such a
  file remains listable and live-readable but is excluded from search, outline,
  and context. Path replacement, digest mismatch, corrupt generation manifests,
  or another integrity failure blocks promotion. Extractor-version change
  invalidates and re-extracts every affected file before promotion.

### the agent's Discretion
- Choose the durable logical-ID record format and conservative rename-detection
  algorithm, provided ambiguous cases cannot silently inherit identity.
- Choose generation directory names, manifest schema, atomic-pointer layout,
  cursor encoding and validation mechanism, provided every request remains
  independently bounded and all bindings above survive process restart.
- Choose concrete hard limits, exact-match normalization, CJK-capable FTS
  tokenizer, and ranking constants after benchmark evidence is available.
- Choose deterministic parsers for the declared text formats and the exact
  taxonomy of ordinary extraction failures versus promotion-blocking integrity
  failures, while preserving D-13 through D-16.
- Choose whether Phase 3 changes land as one or more ordered file-base patches,
  provided source materialization, patch digests, notices, SBOM, staged-package
  allowlists, and build identity remain reproducible.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product scope and inherited authority
- `.planning/PROJECT.md` - Core value, files-first product requirement,
  domain-neutral scope, and prohibition on authoritative graph/index state.
- `.planning/REQUIREMENTS.md` - FILE-01 through FILE-08, VER-03, acceptance
  criteria, supported-format boundary, and v2 ingestion exclusions.
- `.planning/ROADMAP.md` - Phase 3 goal, dependency, MVP designation, and four
  observable success criteria.
- `.planning/STATE.md` - Current release, race-safety, and trust concerns plus
  inherited Phase 1/2 decisions.
- `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`
  - Installed MCP, named-root confinement, packaging, and evidence decisions.
- `.planning/phases/02-durable-provenance-runtime/02-CONTEXT.md` - Parent-only
  canonical writing, immutable evidence, pure replay, and status boundaries.
- `.planning/phases/02-durable-provenance-runtime/02-REVIEW.md` - Residual
  race-sensitive replacement requirement assigned to Phase 3 VER-03.

### Files-first architecture and failure model
- `.planning/research/ARCHITECTURE.md` - Two-process local architecture,
  disposable file/FTS projections, and parent/MCP ownership split.
- `.planning/research/FEATURES.md` - TS-6/TS-7 files-first capabilities,
  supported formats, anti-features, and identified CJK/LaTeX/PDF benchmarks.
- `.planning/research/PITFALLS.md` - Filesystem escape, stale projection,
  unbounded output, hidden extraction, and mutable-authority failure modes.
- `.planning/research/STACK.md` - Pinned native file-base, SQLite/FTS, Python
  control-plane, JSON Schema, and testing stack constraints.
- `docs/architecture/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
  - Original files-table, retrieval, extraction, security, and phase-gate plan.

### Existing executable boundary
- `scripts/file-base-mcp` - Installed one-root launcher and mandatory root/cache
  configuration.
- `vendor/patches/file-base/0002-phase1-confined-read.patch` - Native
  descriptor-relative `read_file`, sensitive-path, symlink, and budget baseline.
- `schemas/v1/mcp-read-request.schema.json` - Current strict Phase 1 confined
  read request to evolve compatibly.
- `schemas/v1/mcp-read-result.schema.json` - Current typed bounded read/denial
  response to evolve compatibly.
- `tests/integration/test_mcp_confinement.py` - Existing native transport,
  traversal, symlink, root, sensitive-path, and output-budget evidence fixture.
- `vendor/sources/file-base/src/mcp/mcp.c` - Pinned MCP tool registry,
  dispatch, pagination, and read-only/query handlers extended by patches.
- `vendor/sources/file-base/src/store/store.h` - Existing read-only SQLite open,
  project/file-hash structures, list/search APIs, transaction, and checkpoint
  surface.
- `vendor/sources/file-base/src/pipeline/pipeline_incremental.c` - Existing
  create/modify/delete incremental indexing behavior to audit and adapt.
- `vendor/sources/file-base/src/watcher/watcher.c` - Existing background watcher
  implementation that Phase 3 must not expose as implicit query-side mutation.

### Build and schema integration
- `src/arw/cli.py` - Parent control-plane CLI integration point for `arw files`.
- `src/arw/schema_registry.py` - Checked-in schema registry and cross-boundary
  contract identity.
- `scripts/stage-plugin` - Positive package allowlist and staged build identity.
- `vendor/source-manifest.json` - Pinned file-base source and ordered patch
  provenance that all Phase 3 native changes must preserve.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `vendor/patches/file-base/0002-phase1-confined-read.patch`: already provides
  descriptor-relative, no-follow traversal beneath one configured root,
  sensitive-name denial, fixed byte/line ceilings, and typed denial results.
- `vendor/sources/file-base/src/mcp/mcp.c`: already has a static tool registry,
  JSON-RPC dispatch, paginated tool listing, strict argument helpers, and
  read-only store opening patterns.
- `vendor/sources/file-base/src/store/store.h`: already tracks project-relative
  paths, SHA-256, mtime, and size and exposes read-only query stores, SQLite
  transactions, backup/checkpoint primitives, file listing, and structured
  search results.
- `src/arw/canonical.py`, `src/arw/evidence.py`, and `src/arw/manifests.py`:
  canonical JSON, digest identity, allowlisted raw evidence, and immutable
  manifests can support generation and administration receipts without making
  the index authoritative.
- `tests/integration/test_mcp_confinement.py`: existing subprocess JSON-RPC and
  hostile-path harness can grow into race, malformed-input, and budget tests.

### Established Patterns
- Upstream native code is changed through ordered, digest-covered patches; the
  materialized source tree is not an undocumented mutable fork.
- Cross-language payloads use strict checked-in Draft 2020-12 schemas and fail
  staged builds on schema or payload drift.
- The native MCP itself enforces confinement. Launchers, hooks, tool allowlists,
  and parent behavior are defense in depth, not the security boundary.
- Query paths open projections read-only and must not create databases,
  pointers, cache state, or canonical events.
- Staged qualification preserves raw command, filesystem, hash, and verdict
  evidence and keeps technical PASS separate from release BLOCKED.

### Integration Points
- Extend `src/arw/cli.py` with the parent-only `arw files` command family while
  keeping Phase 2 runtime authority unchanged.
- Add strict request/result/generation/extraction schemas under `schemas/v1/`,
  register them in `src/arw/schema_registry.py`, and package them through the
  current stage allowlist and build identity.
- Extend the pinned file-base MCP/store/pipeline through reviewed ordered
  patches and update `vendor/source-manifest.json`, notices, SBOM, and staged
  source identity through the existing supply-chain workflow.
- Add repository-owned multilingual fixtures and staged native tests for CJK,
  Markdown, LaTeX, BibTeX, source, direct text, registered PDF extraction,
  generation replacement, and VER-03 races.

</code_context>

<specifics>
## Specific Ideas

- Keep root selection capability-based: tool payloads carry a short root ID,
  never a local absolute path.
- A stale search result remains useful for navigation through identity and
  location metadata, but old body text must not enter an agent prompt.
- Preserve a direct evidence chain from search hit to live read through
  `file_id`, generation, indexed digest, expected digest, and returned digest.
- Make every successful page self-describing: schema version, root ID,
  generation or live-view identity, freshness, truncation, continuation, and
  applicable extractor/tokenizer versions.
- Keep format behavior honest: deterministic structure where declared,
  `no_structure` where absent, and `degraded` where extraction failed.

</specifics>

<deferred>
## Deferred Ideas

- Raw PDF parsing, OCR, DOCX, spreadsheet, and slide ingestion remain v2
  requirement ING-01.
- Cross-file semantic context and evidence-chain graph queries belong to Phase
  5 rather than the Phase 3 deterministic file plane.
- Background watcher refresh, one-process multi-root access, an administrative
  MCP, and a parallel MCP Resources interface are intentionally excluded from
  Phase 3; they may be reconsidered only after the single-root read-only model
  is qualified.

</deferred>

---

*Phase: 03-secure-files-first-data-plane*
*Context gathered: 2026-07-13*
