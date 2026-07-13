# Phase 3: Secure Files-First Data Plane - Research

**Researched:** 2026-07-14
**Domain:** confined local-file inventory, immutable SQLite/FTS generations, provenance-aware MCP retrieval
**Confidence:** HIGH for boundaries and existing-stack integration; MEDIUM for benchmark-dependent limits, CJK ranking, and pre-sync identity behavior

<user_constraints>
## User Constraints (from CONTEXT.md)

The implementation decisions, discretion areas, and deferred scope below are copied verbatim from 03-CONTEXT.md. [VERIFIED: .planning/phases/03-secure-files-first-data-plane/03-CONTEXT.md]

### Locked Decisions

#### Root capability and administrative boundary
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

#### Stable identity and freshness behavior
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

#### MCP query and continuation contracts
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

#### Format structure and extraction provenance
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

### Deferred Ideas (OUT OF SCOPE)
- Raw PDF parsing, OCR, DOCX, spreadsheet, and slide ingestion remain v2
  requirement ING-01.
- Cross-file semantic context and evidence-chain graph queries belong to Phase
  5 rather than the Phase 3 deterministic file plane.
- Background watcher refresh, one-process multi-root access, an administrative
  MCP, and a parallel MCP Resources interface are intentionally excluded from
  Phase 3; they may be reconsidered only after the single-root read-only model
  is qualified.
</user_constraints>

<phase_requirements>
## Phase Requirements

The descriptions are copied from REQUIREMENTS.md; the support column identifies the research section the planner should turn into tasks. [VERIFIED: .planning/REQUIREMENTS.md]

| ID | Description | Research Support |
|----|-------------|------------------|
| FILE-01 | An authorized client can list files under configured roots with stable file identity, type, size, digest, extraction state, and index freshness. | Durable identity manifests, descriptor-safe live inventory, typed extraction/freshness states, and the list contract below. |
| FILE-02 | An authorized client can read bounded byte or line ranges and receives explicit truncation, encoding, and continuation metadata. | Descriptor-safe expected-digest read algorithm, byte/base64 and line/UTF-8 modes, and continuation binding below. |
| FILE-03 | An authorized client can run bounded exact and full-text searches with pagination, source locations, snippets, and freshness metadata. | Separate literal and compiled FTS paths, versioned CJK indexing/ranking, live freshness gate, and keyset cursor contract below. |
| FILE-04 | An authorized client can request bounded document outlines and context windows for supported research formats. | Normalized outline table, deterministic format adapters, and same-file anchored context algorithm below. |
| FILE-06 | Index updates correctly represent create, modify, rename, delete, ignore-rule, and extraction-version changes without retaining stale searchable content. | Complete-generation build, conservative identity reconciliation, stale suppression, and sync matrix below. |
| FILE-07 | CJK text, Markdown, LaTeX, BibTeX, source code, and declared direct-text or extracted-PDF cases have explicit coverage and extraction provenance. | Multilingual tokenizer/parser strategy, registered extraction contract, and fixture/evidence matrix below. |
| FILE-08 | Agent-facing MCP tools are read-only and bounded, while crawl, extraction, rebuild, and repair operations require parent-controlled administrative commands. | Dedicated five-tool native profile, launcher restrictions, parent-only CLI, and no-write qualification below. |
| VER-03 | Security tests cover traversal, symlink or junction escape, race-sensitive file replacement, sensitive files, malformed input, and output-budget exhaustion. | The detailed VER-03 matrix, deterministic race barriers, canary scans, raw-evidence layout, and full-phase verifier below. |
</phase_requirements>

## Summary

Phase 3 should be planned as a new files-plane execution profile inside the already pinned native binary, not as five handlers added to its default MCP path. The current default path starts a watcher, wires auto-index/session discovery, optionally starts UI state, and advertises fourteen upstream tools plus the Phase 1 `read_file`; its store is path-keyed and its incremental classifier relies on path/mtime/size before hashing. The existing first patch also contains a direct-PDF byte heuristic. Those are concrete conflicts with D-02, D-03, D-05, D-09, D-13, and D-16. [VERIFIED: vendor/sources/file-base/src/main.c; vendor/sources/file-base/src/mcp/mcp.c; vendor/sources/file-base/src/store/store.c; vendor/sources/file-base/src/pipeline/pipeline_incremental.c; vendor/patches/file-base/0001-file-base-server-name.patch; vendor/patches/file-base/0002-phase1-confined-read.patch]

Use the Python parent as the only administrator and promotion authority, with the C binary invoked in a non-MCP build mode to perform confined discovery, hashing, parsing, and SQLite/FTS construction in a staging directory. Publish immutable, fully validated generations through one canonical regular-file pointer. The MCP launcher must select a separate native files profile before generic configuration, watcher, session detection, auto-index, and UI initialization; that profile opens one named root plus one selected generation read-only and advertises exactly the five locked tools. This preserves the established Python/C boundary and the ordered-patch supply chain. [VERIFIED: AGENTS.md; 03-CONTEXT.md D-01 through D-04 and D-09; src/arw/cli.py; scripts/file-base-mcp; scripts/materialize-sources; scripts/stage-plugin]

The hardest correctness rule is not FTS; it is preventing old or race-selected bytes from becoming agent context. Generation queries must first produce metadata-only candidates, then re-open the current source through the confined descriptor path and establish identity plus full expected digest before loading any stored snippet, outline, or context. A mismatch returns metadata-only stale state; `read_file` buffers a bounded page but publishes it only after full-digest and pre/post descriptor/path checks. Validation must therefore treat stale-content canaries and deterministic replacement barriers as primary oracles, not incidental edge tests. [VERIFIED: 03-CONTEXT.md D-06 through D-08 and D-16; .planning/phases/02-durable-provenance-runtime/02-REVIEW.md]

**Primary recommendation:** plan five vertical slices—contracts/generation state, isolated MCP plus live inventory/read, synchronization/search, structure/extraction/context, and staged security/supply-chain qualification—with tests and raw evidence created before each implementation slice.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Root registration and `arw files` administration | API / Backend (Python parent) | Database / Storage | The parent owns mutation, receipts, identity records, and promotion; no MCP request can enter this path. [VERIFIED: D-01 through D-04; AGENTS.md] |
| Confined discovery and live file open | API / Backend (native C) | OS filesystem | The native boundary must resolve relative paths under one root and retain the descriptor through validation/read. [VERIFIED: AGENTS.md; Phase 1 patch and tests] |
| Logical identity reconciliation | API / Backend (parent orchestration) | Database / Storage | Durable ID history is parent-owned; native scan observations are inputs, not authority. [VERIFIED: D-05; Phase 2 authority pattern] |
| Generation construction, FTS, outlines | API / Backend (native C build mode) | Database / Storage (SQLite) | C already owns parsing/indexing and bundled SQLite; the output is a disposable immutable projection. [VERIFIED: AGENTS.md; pinned file-base source] |
| Atomic selection and management receipts | Database / Storage | API / Backend (Python parent) | A regular-file pointer selects one complete generation; immutable receipts retain build/promotion evidence. [VERIFIED: D-04; src/arw/manifests.py; src/arw/evidence.py] |
| `list_files` and `read_file` | API / Backend (native MCP) | OS filesystem | Results are based on current descriptor-safe observations, with the generation used only as identity/history context. [VERIFIED: D-06 and D-08] |
| `search_files`, `get_outline`, `get_context` | API / Backend (native MCP) | Database / Storage + OS filesystem | SQLite supplies one-generation candidates; the live source gate suppresses stale body-bearing output. [VERIFIED: D-06, D-07, D-15] |
| Canonical run/workflow state | API / Backend (Phase 2 runtime) | Immutable run storage | File databases, pointers, cursors, and extractions never advance workflow authority. [VERIFIED: Phase boundary; .planning/STATE.md] |

## Project Constraints (from AGENTS.md)

- Keep the project Codex-native, private, headless, and local-first; append-only ledger events and immutable manifests remain canonical workflow authority. [VERIFIED: AGENTS.md]
- Support Python `>=3.13,<3.15`; the present development interpreter is 3.14.6. [VERIFIED: pyproject.toml; environment probe 2026-07-14]
- Keep file-base pinned at revision `ee68144af5453addda995a27cce8142999f318fb` and express native changes only as ordered, digest-covered patches. [VERIFIED: vendor/source-manifest.json; AGENTS.md]
- Keep MCP on the project-selected 2025-11-25 stdio protocol and JSON Schema Draft 2020-12. [VERIFIED: AGENTS.md; pinned native source; schemas/v1]
- Use the bundled SQLite 3.51.3 build with FTS5; do not silently substitute the host `sqlite3` CLI, which is 3.51.2 in this environment. [VERIFIED: vendor/sources/file-base/vendored/sqlite3/sqlite3.h; environment probe 2026-07-14]
- Keep the native C data plane responsible for MCP, path checks, indexing, FTS, and structural extraction; keep Python responsible for `arw files`, manifests, receipts, and promotion. [VERIFIED: AGENTS.md]
- Treat SQLite and all retrieval tables as disposable projections, never workflow authority. [VERIFIED: AGENTS.md; Phase 3 boundary]
- Use `unicode61 remove_diacritics 2` and a separate trigram index for CJK/substring fallback; preserve deterministic ranking and source locations. [VERIFIED: AGENTS.md]
- Keep the MCP read-only and bounded. Do not expose watcher refresh, query-side writes, update checks, UI, or administrative tools. [VERIFIED: AGENTS.md; D-02, D-03, D-09, D-12]
- Do not add raw PDF parsing or OCR in this phase; only validated, registered external extraction text may enter a generation. [VERIFIED: D-13; AGENTS.md]
- Regenerate notices/SBOM/build identity and update exact staged allowlists whenever schemas, patches, or native bytes change. [VERIFIED: AGENTS.md; scripts/stage-plugin; scripts/verify-sources]
- Preserve the exact upstream native C test inventory while running normal, ASan+UBSan, and TSan suites; add Phase 3 tests outside the pinned upstream test tree. [VERIFIED: AGENTS.md; vendor/source-manifest.json native_test_suites; scripts/build-file-base]
- Preserve raw command, transport, tree, hash, race, and verdict evidence; a summary verdict must not replace its raw inputs, and technical PASS must remain distinct from the unresolved SUP-04 release block. [VERIFIED: AGENTS.md; .planning/STATE.md; scripts/verify-phase-1; scripts/verify-phase-2]

## Existing Baseline and Required Delta

| Surface | Existing behavior | Phase 3 planning consequence |
|---------|-------------------|------------------------------|
| Native startup | The default native main path creates a watcher, performs session detection/possible auto-indexing, and has UI/config paths. [VERIFIED: vendor/sources/file-base/src/main.c:717-823; vendor/sources/file-base/src/mcp/mcp.c:5820-5938,6128-6129] | Add an early, explicit files-profile branch that bypasses all of these initializers; do not try to disable them only through mutable configuration. |
| Tool registry | Pinned upstream defines fourteen tools and Phase 1 prepends `read_file`; output schemas are currently `additionalProperties:true`, and tool-list cursors are numeric offsets. [VERIFIED: vendor/sources/file-base/src/mcp/mcp.c:430-624; vendor/patches/file-base/0002-phase1-confined-read.patch] | The files profile needs its own static registry/dispatcher containing exactly five tools and strict generated input/output schemas. |
| Launcher | `scripts/file-base-mcp` validates root/cache environment but creates the cache and forwards arbitrary arguments. [VERIFIED: scripts/file-base-mcp] | Require a pre-existing validated cache, reject all caller arguments, and hard-code the files-profile selector. Query launch must be filesystem-write-free. |
| Phase 1 read | The patch walks with descriptor-relative `fstatat/openat`, rejects symlinks/sensitive names, enforces 4096-byte/200-line ceilings, and validates UTF-8. It does not bind logical identity, expected digest, continuation position, or post-read replacement checks. [VERIFIED: vendor/patches/file-base/0002-phase1-confined-read.patch; schemas/v1/mcp-read-*.schema.json] | Reuse the denial taxonomy and harness, but replace the read contract/algorithm with descriptor identity, full digest, pre/post state, and no-output-until-validated semantics. |
| Store/index | `file_hashes` is keyed by project/path and stores SHA-256, mtime, and size; current FTS indexes graph-node fields, not complete file bodies or extraction/outline provenance. [VERIFIED: vendor/sources/file-base/src/store/store.c:226-310,1750-1830] | Add a dedicated files-generation schema; do not stretch graph tables into the file plane. |
| Incremental pipeline | Existing classification is path-centric and uses metadata shortcuts; it mutates one project store. [VERIFIED: vendor/sources/file-base/src/pipeline/pipeline_incremental.c] | Use its parsers/discovery selectively, but build a complete sibling generation from full source digests and reconcile identity before promotion. |
| PDF handling | Patch 0001 samples raw PDF bytes and detects direct text operators. [VERIFIED: vendor/patches/file-base/0001-file-base-server-name.patch:109-234] | Make `CBM_LANG_PDF_TEXT` and every raw-PDF handler unreachable from both files-profile query and files-generation build paths; only registered text is eligible. |
| Schemas/stage | The schema registry and staged payload identity enumerate the current 22 schemas; build identity has a fixed upper bound. [VERIFIED: src/arw/schema_registry.py; scripts/stage-plugin; schemas/v1/build-identity.schema.json] | Replace fixed-count assumptions with exact registry-derived identity, add Phase 3 contracts to the positive allowlist, and compare native embedded schema digests with installed schemas. |
| Tests | The direct native confinement matrix covers traversal, absolute path, symlink, root ID, `.env`, and Phase 1 ceilings; 17 selected confinement/schema tests pass in 8.55 seconds. [VERIFIED: tests/integration/test_mcp_confinement.py; local test run 2026-07-14] | Extend it with exact-five-tools, continuation, stale canaries, deterministic races, malformed framing/contracts, every new budget, generation integrity, and staged execution. |

## Standard Stack

No new external package is needed. Use the reviewed, already locked components below; do not add a Python MCP SDK, PDF parser, Unicode package, search service, or alternate database. [VERIFIED: AGENTS.md; pyproject.toml; vendor/source-manifest.json]

### Core

| Component | Version / identity | Purpose | Why standard here |
|-----------|--------------------|---------|-------------------|
| Python | 3.14.6 development; project range `>=3.13,<3.15` | Parent CLI, generation orchestration, identity manifests, receipts, promotion | Existing control-plane runtime and sole administrative writer. [VERIFIED: pyproject.toml; python.org release 3.14.6 dated 2026-06-10] |
| file-base native C | `v0.9.0-2-gee68144`, revision `ee68144af5453addda995a27cce8142999f318fb` | MCP transport, confined I/O, scan/parser/index/query code | Reviewed and supply-chain pinned; changes are ordered patches. [VERIFIED: vendor/source-manifest.json] |
| SQLite + FTS5 | bundled 3.51.3, released 2026-03-13 | Immutable generation store, FTS candidates, metadata/outlines | Already compiled into the native binary with FTS5; avoids runtime service dependencies. [VERIFIED: vendored sqlite3.h; sqlite.org/changes.html] |
| MCP | 2025-11-25 over newline-delimited stdio | Five agent-facing tools | Project-selected protocol; it supports tool input/output schemas and structured content. [CITED: modelcontextprotocol.io/specification/2025-11-25/server/tools] |
| JSON Schema | Draft 2020-12 | Python/native/admin/tool contracts | MCP defaults to 2020-12 and the project already validates it independently. [CITED: modelcontextprotocol.io/specification/2025-11-25/basic] |
| Pinned tree-sitter runtime/grammars | language ABI 15 in pinned tree | Markdown, BibTeX, and source definitions | Already reviewed and bundled; no new grammar package is required for those formats. [VERIFIED: vendor/sources/file-base/internal/cbm/vendored/ts_runtime/include/tree_sitter/api.h; pinned grammar tree] |

### Supporting

| Component | Version | Purpose | Use |
|-----------|---------|---------|-----|
| Pydantic | 2.13.4 | Strict parent models | Validate root/admin/receipt/extraction objects before any write. [VERIFIED: uv.lock; environment import 2026-07-14] |
| jsonschema | 4.26.0 | Independent Draft 2020-12 validation | Cross-language and staged instance validation. [VERIFIED: uv.lock; environment import 2026-07-14] |
| portalocker | 3.2.0 | Parent administrative serialization | One `arw files` mutation per root; never used by MCP queries. [VERIFIED: uv.lock; existing project pattern] |
| pytest | 9.1.1 | Unit/integration/adversarial tests | Existing strict test infrastructure and subprocess harness. [VERIFIED: environment import 2026-07-14; pyproject.toml] |
| Linux `openat2` plus current descriptor walk fallback | kernel API / existing C | One-root path resolution | `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS|RESOLVE_NO_XDEV` applies restrictions to the complete lookup; fallback remains deny-by-default. [CITED: man7.org/linux/man-pages/man2/openat2.2.html] |

### Alternatives Considered

| Instead of | Do not introduce | Reason |
|------------|------------------|--------|
| Bundled SQLite/FTS5 | Tantivy, Lucene, Elasticsearch, another SQLite binding | Contradicts the locked stack and creates a second retrieval/runtime supply chain. [VERIFIED: AGENTS.md] |
| Pinned native MCP | Python MCP SDK/server | Moves the confinement boundary out of the reviewed native process and duplicates contracts. [VERIFIED: D-01, D-09; AGENTS.md] |
| Registered PDF extraction | pypdf, Poppler invocation, OCR | Explicitly deferred by D-13 and ING-01. [VERIFIED: 03-CONTEXT.md] |
| Existing pinned parsers plus bounded LaTeX lexer | newly downloaded parser packages | No package is needed to satisfy the declared structure subset; new packages would require a separate legitimacy and source review. [VERIFIED: pinned grammar inventory; D-14] |

**Installation:** none. Phase 3 must remain buildable with the current frozen environment. [VERIFIED: pyproject.toml; uv.lock]

## Package Legitimacy Audit

Not applicable: this research recommends no external package installation. Therefore the slopcheck/package-registry gate is not triggered. [VERIFIED: Standard Stack above]

## Architecture Patterns

### System Architecture Diagram

~~~text
Parent boundary (mutation)                         Agent boundary (read only)

run start / recovery / explicit sync
                 |
                 v
        arw files (Python parent)          parent launches one root capability
        | root + identity records |                        |
        | extraction registrations|                        v
        +-------------+-----------+             native --arw-files-mcp
                      |                         (no watcher/UI/session/index)
                      v                                  |
         native --arw-files-build                        +--> list_files/read_file
         descriptor-safe full scan                       |    live root FD
          |          |          |                        |
          |          |          +--> integrity fault ----+--> search/outline/context
          |          |                 blocks promotion       exact immutable generation
          |          v                                             |
          |   parse/extract failure                                v
          |   explicit degraded row                      metadata-only candidates
          v                                                       |
  staged index.sqlite + manifests                                 v
          |                                              live identity + digest gate
   schema/DB/FTS/digest validation                       / fresh              stale
          |                                             v                     v
          v                                    bounded body result    metadata only;
 immutable generation + prepared receipt                                  sync_required
          |
 atomic current.json replacement + directory fsync
          |
          v
 next MCP process / cursor-bound retained generation

Phase 2 ledger and immutable run manifests remain separate canonical authority.
~~~

This split is required because SQLite's `immutable=1` skips locking/change detection and can return incorrect results if the database changes; only closed, digest-verified, never-mutated generation files may be opened that way. [CITED: sqlite.org/uri.html]

### Recommended Project Structure

~~~text
src/arw/
├── file_models.py          # strict root, identity, generation, extraction, receipt models
├── file_admin.py           # parent-only arw files commands and serialization
├── file_generations.py     # staging, validation, promotion, recovery/prune
└── cli.py                  # command routing only
schemas/v1/
├── file-root.schema.json
├── file-identity-manifest.schema.json
├── file-generation-manifest.schema.json
├── file-management-receipt.schema.json
├── file-extraction-registration.schema.json
└── mcp-{list,read,search,outline,context}-*.schema.json
vendor/patches/file-base/
└── 0003..NNNN-phase3-*.patch # all native source changes, ordered and digest-covered
tests/
├── unit/test_file_{identity,generations,tokenizer,outlines}.py
├── schema/test_file_contracts.py
├── integration/test_{files_admin,mcp_files_plane,file_sync_matrix}.py
├── integration/test_{mcp_file_races,registered_pdf_extraction}.py
└── fixtures/files-plane/   # CJK/MD/TeX/Bib/source/text/PDF-registration/canaries
scripts/
└── verify-phase-3          # clean staged/raw-evidence phase gate
~~~

The actual pinned source tree remains materialized from its manifest and patches; implementation tasks must not directly edit `vendor/sources/file-base`. [VERIFIED: AGENTS.md; scripts/materialize-sources]

### Pattern 1: Dedicated Native Files Profile

Add a process-launch mode selected before generic config initialization. The launcher takes no user arguments and always executes this mode. The mode:

1. validates exactly one root ID, root directory, cache/state paths, and current pointer;
2. opens the root directory once and retains its FD;
3. loads no writable project store and starts no watcher, UI, HTTP server, update check, session detection, or auto-index;
4. advertises and dispatches exactly `list_files`, `read_file`, `search_files`, `get_outline`, and `get_context`;
5. opens generation databases only read-only/immutable after manifest and database digest validation; and
6. performs no `mkdir`, pointer repair, refresh, WAL recovery, logging-file creation, or other filesystem write.

The generic upstream profile may remain for non-agent compatibility, but Phase 3 configuration and staged tests must invoke only the files profile. [VERIFIED: D-01 through D-03 and D-09; current startup audit]

### Pattern 2: Durable Identity, Disposable Generation

Keep durable root/identity/extraction/receipt records outside the disposable index cache. Use this conceptual layout; the parent supplies both roots and requires generation staging/pointer replacement to occur on one filesystem:

~~~text
FILE_STATE_ROOT/roots/<root_id>/
├── root.json
├── identities/sha256/<identity_manifest_sha256>.json
├── extractions/sha256/<registration_sha256>.json
├── extracted-text/sha256/<extracted_text_sha256>.txt
└── receipts/sha256/<receipt_sha256>.json

CBM_CACHE_DIR/files/<root_id>/
├── current.json
├── building/<attempt_id>/...
└── generations/g-<generation_manifest_sha256>/
    ├── manifest.json
    └── index.sqlite
~~~

`root.json` is parent-created and binds root ID, root-instance UUID, canonical administrative root path, policy ID, and schema version. Identity manifests are immutable sorted records, not a mutable path-keyed database. A generation references one identity-manifest digest and extraction-registration digests; deleting the cache does not erase logical IDs or extraction provenance. These records are file-plane identity/evidence, not workflow authority. [VERIFIED: D-04, D-05, phase boundary; established immutable-manifest pattern in src/arw/manifests.py]

### Pattern 3: Complete Generation and Atomic Promotion

Use this exact state transition:

1. Acquire the parent per-root administration lock and re-read the selected pointer/identity state.
2. Create an owned `building/<attempt_id>` directory with no symlink components.
3. Descriptor-scan the complete root, calculate full SHA-256 values, reconcile IDs, ingest only valid registered extraction text, and build SQLite in deterministic file-ID/path order.
4. Record every ordinary parser/extractor failure as a typed degraded file; abort on every integrity failure.
5. In the build transaction run foreign-key checks, `PRAGMA integrity_check`, and each FTS5 `integrity-check`; close SQLite and reject leftover `-wal`, `-shm`, or journal files. SQLite documents the FTS command and warns that external-content inconsistency makes results unpredictable. [CITED: sqlite.org/fts5.html]
6. Compute the closed database digest; write canonical identity/generation manifests and a content-addressed candidate receipt; fsync files and directories.
7. Rename the completed generation into `generations/g-<manifest_sha256>`.
8. Write a canonical temporary `current.json` that binds root, generation, manifest, identity manifest, database digest, and receipt; fsync it; atomically replace `current.json); fsync the parent directory.
9. Release the lock. Pruning is a separate parent-only operation and must retain every generation within the declared cursor-retention window.

Atomic rename prevents a missing destination during replacement, while file fsync alone does not durably publish the containing directory entry; directory fsync is also required. [CITED: man7.org/linux/man-pages/man2/renameat.2.html; man7.org/linux/man-pages/man2/fsync.2.html]

A failed attempt writes a failure receipt but never changes `current.json` or the selected identity manifest. A crash may leave an unselected building directory, candidate receipt, or complete generation; `arw files repair` may classify/remove or reselect it only after the same validation, never from MCP. [VERIFIED: D-02, D-04; Phase 2 crash/publication pattern]

### Pattern 4: Conservative Logical Identity

Use persistent opaque IDs unrelated to path or content. Reconcile a new scan against the previously selected identity manifest in this order:

1. Same normalized relative path retains its `file_id`, even when content changes.
2. For unmatched old/new rows, accept an OS-identity rename only when the descriptor-derived fingerprint is unique on both sides and the file type is unchanged.
3. Otherwise accept a digest-based rename only for a one-old/one-new group with identical full digest, size, and type.
4. Any one-to-many, many-to-one, duplicate-content, conflicting-fingerprint, or missing-evidence group becomes explicit deletes plus creates.
5. Never mutate identity state until the complete candidate generation passes validation.

This gives same-content files separate IDs and intentionally prefers lost lineage over false lineage. The exact fingerprint and behavior when birth time is unavailable require a Wave 0 platform test; this is an agent-discretion choice, not yet implementation-verified. [ASSUMED]

For a live file created after the selected generation, `list_files` may return a deterministic provisional ID only when a stable descriptor fingerprint is available; the next successful sync must adopt that ID. Otherwise return `identity_state: sync_required` and no claim of persistent identity. Do not derive durable IDs from path alone, because delete/recreate at one path would silently reuse identity. [ASSUMED]

### Pattern 5: Generation Schema

Use a dedicated SQLite schema, not graph tables:

| Table | Required content |
|-------|------------------|
| `generation_meta` | schema, root, generation, identity manifest, policy, parser/tokenizer/ranker versions |
| `files` | rowid, file_id, relative path/type/size, source digest, descriptor fingerprint, encoding, eligibility, degraded reason, extraction ID |
| `file_content` | rowid/file_id, source kind, indexed body bytes/digest, deterministic line-offset map |
| `extractions` | registration/source/extracted digests, extractor name/version/time, quality/access states |
| `outline_nodes` | node ID, file ID, normalized kind/title/level, half-open byte range, line/byte-column location, parent, ordinal, parser version |
| `file_fts` | contentless FTS5 candidate index over path/title/body/CJK-term columns using `unicode61 remove_diacritics 2` |
| `file_trigram` | contentless FTS5 trigram candidates for three-or-more-character substring/CJK fallback |

Join FTS rowids to ordinary tables; never treat FTS copies as provenance. Contentless tables avoid external-content trigger drift, and immutable generations never need incremental deletes. SQLite documents that trigram searches shorter than three Unicode characters do not match and that contentless columns cannot be read back, so short-CJK support and snippets must come from the ordinary body/CJK-term path. [CITED: sqlite.org/fts5.html]

### Pattern 6: Descriptor-Safe Live Observation and Read

On Linux, prefer one `openat2(root_fd, relative_path, ...)` with `O_RDONLY|O_CLOEXEC|O_NOFOLLOW` and `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS|RESOLVE_NO_XDEV`. The kernel API applies restrictions to all path components and reports races/escapes; retain the Phase 1 component walk only as an `ENOSYS` fallback and fail closed if equivalent checks cannot be made. [CITED: man7.org/linux/man-pages/man2/openat2.2.html; kernel.org/doc/html/v6.6/filesystems/path-lookup.html]

Use the following no-leak read sequence:

1. Validate the strict request and requested limits before opening anything.
2. Resolve `file_id` to the expected relative path/fingerprint; treat the client path only as a checked hint.
3. Open beneath the retained root FD; reject symlinks, mount crossings, non-regular files, sensitive policy names, and multiply linked files under the conservative Phase 3 policy.
4. `fstat` the opened FD and capture identity/size/time fields.
5. Stream the entire file through SHA-256 while retaining only the requested bounded byte or line page. Byte mode returns base64 plus half-open byte offsets; line mode requires valid UTF-8 and returns text, 1-based line numbers, and the next byte/line position.
6. `fstat` again and re-resolve/stat the path beneath the root; require unchanged opened identity, unchanged post-path identity, full `expected_digest`, and matching `file_id`.
7. Only then serialize the retained page. Any mismatch, disappearance, replacement, timeout, or I/O error discards the buffer and returns `stale_conflict` or the typed error with no body.

An open descriptor remains attached to its opened object across a rename, so the post-path check is required to establish that the returned bytes are still the current named file. [CITED: man7.org/linux/man-pages/man2/renameat.2.html]

`list_files` performs the same descriptor-safe live observations. For restart-safe pagination, the first page computes a bounded sorted live-inventory fingerprint over path, logical/provisional ID, descriptor identity, size, and digest. Its opaque cursor binds that fingerprint, selected generation, filters, last sort key, and contract version; a continuation re-observes the inventory and returns `live_view_changed` instead of mixing snapshots if the fingerprint differs. This is intentionally more expensive than a mutable watcher and must be benchmarked against the declared root cap. [ASSUMED]

### Pattern 7: Metadata-First Stale Suppression

Generation-backed tools execute in two phases:

1. Query only row IDs, rank, file ID, indexed path/digest, extraction ID, and candidate locations from one generation.
2. For every candidate that could contribute body text, open the live source descriptor and validate identity plus full source digest. For registered PDF text, validate the live PDF source digest and the generation's extraction-registration binding.

Only fresh candidates may load `file_content`, outlines, or snippet/context bytes. A stale candidate may return `file_id`, current/previous path, indexed digest, current digest when safely known, `change_reason`, and `sync_required:true`; set body, snippet, outline, and source-location text fields absent/null. Do not call SQLite `snippet()` before this gate. [VERIFIED: D-06 through D-08, D-13]

Collect and validate the complete requested page in memory before emitting the JSON-RPC response. If any page-level deadline expires, return one typed timeout and no partial ranking. [VERIFIED: D-12]

### Five MCP Tool Contracts

Every request/result includes `schema_version` and `root_id`; every result includes `limits_applied`, `status`, and either complete data or a typed error. Generation-backed results also include `generation_id`, `generation_manifest_sha256`, `indexed_digest`, `tokenizer/parser/ranker` identity as applicable, extraction identity, and freshness. Tool names remain exactly those locked in D-09; versioning lives in strict schemas/payloads, not mode parameters or alternate unversioned names. [VERIFIED: D-09 through D-12]

| Tool | Required request shape | Success semantics | Continuation binding |
|------|------------------------|-------------------|----------------------|
| `list_files` | root, optional allowlisted prefix/type/state filters, requested page size or cursor | Descriptor-safe live inventory with file ID/identity state, type, size, live digest, extraction/index/freshness metadata | root, selected generation, normalized filters, live-view fingerprint, last `(path,file_id)` |
| `read_file` | root, file ID, relative-path hint, expected digest, exactly one byte-range or line-range; or continuation | Current bytes only; byte mode base64, line mode UTF-8; digest, encoding, offsets/lines, truncation | root, file ID, expected digest, path, mode, next byte and line position |
| `search_files` | root, explicit `exact` or `full_text`, query, allowlisted filters, requested hit/snippet limits or cursor | Deterministically ranked one-generation hits; stale hits metadata-only | root, generation, mode, normalized query/filters, ranking version, last rank/file/location |
| `get_outline` | root, file ID, optional cursor/node limit | Fresh normalized nodes or typed `no_structure`; never guessed structure | root, generation, file/digest, parser version, last ordinal |
| `get_context` | root and exactly one tagged anchor: hit token, source location, or outline node; bounded neighbor request or cursor | Fresh target + deepest containing node + same-file/generation neighbors | root, generation, file/digest, normalized anchor, context policy, next position |

MCP 2025-11-25 requires valid input schemas, permits output schemas, and requires structured results to conform when an output schema is supplied. Return canonical JSON in `structuredContent` and the same serialized object in one text content item for compatibility. [CITED: modelcontextprotocol.io/specification/2025-11-25/server/tools]

Malformed tool arguments are tool execution errors with a strict schema-shaped error result; malformed JSON-RPC/framing remains a protocol error. Unknown tools, duplicate fields, additional properties, invalid UTF-8, overlong lines, oversized cursors, and unsupported schema versions must be rejected before handler work. [CITED: modelcontextprotocol.io/specification/2025-11-25/basic; modelcontextprotocol.io/specification/2025-11-25/changelog]

### Cursor Design

Encode a canonical versioned cursor payload as base64url plus SHA-256 checksum. The checksum detects corruption, not hostile forgery; authorization remains the configured root/process, and the server independently revalidates every decoded root, generation, parameter, limit, and sort position. Accept only the current generation or a parent-retained, manifest/digest-valid generation inside the retention policy. Expired/pruned generations return `cursor_expired`, never silently restart against current. This scheme is stateless and survives process restart without introducing a cryptographic-key lifecycle. [VERIFIED: D-10; project decision that unkeyed hashes provide consistency, not authenticity in .planning/STATE.md]

The MCP specification defines cursors as opaque, server-sized tokens and says clients must not parse, modify, or persist them across sessions; Phase 3's stronger restart binding is a local contract, not a claim that MCP guarantees cross-session persistence. [CITED: modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination]

### Candidate Hard Ceilings and Benchmark Gate

The values below are initial qualification candidates, not verified performance facts. Plan 03-01 must benchmark them on repository-owned small/large/CJK/pathological fixtures, record latency and response size, and freeze one generated native/schema constant set before later plans. [ASSUMED]

| Budget | Candidate server ceiling | Enforcement |
|--------|--------------------------|-------------|
| JSON-RPC input line | 32 KiB | Reject framing before parse/allocation growth |
| Relative path / query / cursor | 1024 / 512 / 2048 UTF-8 bytes | Strict schema plus native byte check |
| Live inventory | 25,000 files, 2 GiB aggregate hashing, 2 s/page | Complete fingerprint or typed timeout; no page |
| List page | 100 files | Client may request 1-100 |
| Read page | 64 KiB raw or 400 lines; 128 KiB serialized response | Base64 expansion included in response cap |
| Hashable live source | 256 MiB per request | Larger source returns typed budget error unless later benchmark lowers/raises contract |
| Search | 50 hits, 512 UTF-8 bytes/snippet, 32 KiB snippets/page, 200 metadata candidates | Rank/validate entire page before output |
| Outline | 200 nodes, 64 KiB serialized | Stable ordinal continuation |
| Context | 32 KiB text, at most two neighbor blocks each side | Same file/generation only |
| Index/parser input | 16 MiB direct text per file; root-level declared cap | Larger files list/read but become explicit degraded/excluded |
| Handler deadline | 2 s monotonic; build/admin separately bounded | Timeout discards response buffer |
| Retention | current plus two prior generations, minimum 15 minutes | Freeze after cursor benchmark; prune parent-only |

All constants must have one machine-readable source used to generate JSON Schemas and C constants; tests assert just-over-ceiling rejection before any open/query. [VERIFIED: D-12; existing schema-drift pattern]

### Exact and Full-Text Search

**Exact mode:** define v1 as a literal sequence of UTF-8 bytes with no case folding, stemming, regex, wildcard, or Unicode normalization. Use the trigram table only to obtain candidates for three-or-more-codepoint queries, then byte-verify against `file_content`; scan bounded content for shorter queries. This makes exact semantics independent of backend query syntax. The no-normalization choice must be documented in result metadata and benchmark fixtures. [ASSUMED]

**Full-text mode:** use one contentless `file_fts` table with `unicode61 remove_diacritics 2` over path/title/body plus an indexed generated CJK-term column. Invoke the table's tokenizer API from C for prose terms; never concatenate client text into MATCH syntax. The server constructs only quoted/column-scoped expressions from bounded tokens. SQLite documents Unicode61's Unicode 6.1 classification/case behavior and that FTS query strings have operators/special syntax, which is why raw input cannot be passed through. [CITED: sqlite.org/fts5.html]

**Deterministic CJK v1:** for Han, Hiragana, Katakana, and Hangul code points, generate versioned ASCII unigram and adjacent-bigram tokens (for example code-point-encoded `u...` and `b..._...`) into the CJK column; tokenize queries identically. Use the separate trigram index for three-or-more-character substring candidates. Persist `tokenizer_id`, script-range-table digest, and normalization policy in the generation. This avoids an unreviewed segmentation dependency and covers the documented trigram short-query gap, but the range table, mixed-script behavior, and weights require fixture benchmarks. [ASSUMED]

Rank full-text hits with one fixed FTS5 `bm25` configuration, then deterministic tie keys `file_id,start_byte,end_byte`. SQLite's BM25 returns better matches as numerically smaller values and supports fixed column weights. Store the exact rank tuple in cursors; do not compare scores from separate FTS tables. [CITED: sqlite.org/fts5.html]

Build source locations/snippets after freshness validation by rescanning the stored fresh body with the same tokenizer/term policy. Byte ranges are normative and half-open; lines are 1-based; columns are zero-based UTF-8 byte columns. Never expose generated CJK tokens or FTS markup as source text. [VERIFIED: D-03, D-07, D-11]

### Deterministic Outlines and Anchored Context

Normalize every node to:

~~~json
{
  "node_id": "on_...",
  "file_id": "f_...",
  "kind": "heading|section|entry|definition",
  "title": "verbatim bounded title",
  "level": 1,
  "location": {
    "start_byte": 0,
    "end_byte": 12,
    "start_line": 1,
    "end_line": 1,
    "start_byte_column": 0,
    "end_byte_column": 12
  },
  "parent_node_id": null,
  "ordinal": 0,
  "parser_id": "..."
}
~~~

Use these adapters:

| Format | Parser | Deterministic rule |
|--------|--------|--------------------|
| Markdown | pinned tree-sitter Markdown grammar | ATX/setext headings; derive level from syntax; heading stack supplies parent. [VERIFIED: pinned grammar/source extraction inventory] |
| LaTeX | bounded native lexer | Recognize only `part/chapter/section/subsection/subsubsection/paragraph/subparagraph`, skip escaped comments and declared verbatim environments, parse one balanced title argument, and perform no macro/include expansion. [ASSUMED] |
| BibTeX | pinned tree-sitter BibTeX grammar | Each top-level entry yields kind `entry`, title from entry type + key, level 1, no inferred hierarchy. [VERIFIED: pinned BibTeX grammar symbols] |
| Source | existing pinned tree-sitter definition extraction | Normalize definitions; parent is the smallest enclosing definition range; level is containment depth with deterministic ties. [VERIFIED: pinned file-base extraction surface] |
| Plain text / registered PDF text | none | Return `no_structure`; do not infer headings. [VERIFIED: D-14] |

`get_context` resolves a server-issued hit token, explicit generation/file/digest byte location, or outline node. It validates freshness, returns the target range, deepest containing node if any, and bounded predecessor/successor blocks from the same `file_content` row and generation. It never follows citations, imports, includes, semantic neighbors, or another file. [VERIFIED: D-15]

### Registered External PDF Extraction

Expose registration only as a parent command such as `arw files extract register --request <json>`. The request names a configured root/file ID and an external UTF-8 text input, but the parent/native verifier computes rather than trusts both digests. Required immutable registration fields are source PDF digest, extracted-text digest, extractor name/version, UTC extraction time, quality state, access state, registration schema/version, and source file identity. Copy verified UTF-8 text into a content-addressed parent store; never index an arbitrary external path. [VERIFIED: D-02, D-13]

Only a `quality_state=complete` and `access_state=accessible` registration is search/context eligible in v1. A fresh extractor attempt may explicitly report `partial`, `failed`, `encrypted`, or `image_only`; that permits a degraded generation with no extracted body. When the configured extractor version changes, every affected PDF needs either a new complete registration or a new version-bound failure registration before promotion. Carrying an old registration is blocking, not degradation. [ASSUMED; constrained by D-16]

The native files profile must contain a regression assertion that no raw PDF parser/detector is reached and that PDF bytes/canaries never appear in snippets unless their separately registered text contains them. [VERIFIED: D-13; current patch-0001 risk]

### Failure Taxonomy

| Class | Examples | Promotion | Query behavior |
|-------|----------|-----------|----------------|
| Ordinary degraded | unsupported/invalid text encoding, parser syntax/error budget, direct text over index cap, fresh external extraction failure/encrypted/image-only, honest `no_structure` | May promote only with file ID/path/digest/reason/parser-or-extractor identity in manifest/receipt | List + live read; excluded from search/outline/context |
| Stale live state | create/modify/delete/rename after generation, ignore-policy change pending sync | Generation stays selected; freshness changes | Metadata only, `sync_required`; no old body |
| Integrity blocker | traversal/symlink/mount/hardlink policy violation during build, descriptor replacement, source digest change while scanning, extraction digest/source/version mismatch, duplicate file ID, identity ambiguity encoded incorrectly, corrupt/noncanonical manifest/pointer, SQLite/FTS check failure, DB digest mismatch, schema/embedded-contract mismatch | Abort; pointer byte-identical; failure receipt | Existing prior generation remains available subject to live stale gates |
| Query conflict | expected digest/identity/path replacement mismatch | No mutation | `stale_conflict`, no body |
| Resource/input error | malformed/over-ceiling/cursor invalid/timeout | No mutation | Typed complete error, no partial results |

This table is prescriptive; do not downgrade an integrity blocker to keep a refresh convenient. [VERIFIED: D-04, D-07, D-08, D-12, D-16]

### Schema Identity, Cross-Language Validation, and Packaging

Create separate strict request/result schemas for all five tools plus root, identity, generation, extraction, and receipt contracts. Every object uses Draft 2020-12, `additionalProperties:false`, a local project `$id`, and a constant `schema_version`. Bundle all native tool schemas into a deterministic generated C header from checked-in JSON; do not maintain hand-copied C schema strings. CI regenerates and byte/digest-compares the header, while `tools/list` schemas and every native result are independently validated by Python `jsonschema`. [VERIFIED: VER-01 established pattern; MCP schema requirements]

Update `SCHEMA_NAMES`, remove the build-identity `maxItems:22` assumption, stage the exact new schemas/header identity, and include schema aggregate, embedded native contract digest, SQLite version, tokenizer/parser/ranker IDs, patch list/tree, and native binary digest in build identity. Stage no root registry, index generation, extraction text, cache, database, receipt instance, or test secret. [VERIFIED: src/arw/schema_registry.py; scripts/stage-plugin; current build identity]

Native implementation changes must be one or more ordered Phase 3 patches. Update pre/post tree hashes, patch hashes, source manifest, notices, SBOM, and staged payload identity through the existing commands. Keep the upstream C test-tree digest unchanged and add direct-process Phase 3 tests in the first-party Python test tree. [VERIFIED: AGENTS.md; vendor/source-manifest.json; scripts/materialize-sources; scripts/build-file-base]

## Don't Hand-Roll

| Problem | Do not build | Use instead | Why |
|---------|--------------|-------------|-----|
| Root confinement | string prefix/realpath check | root FD + `openat2` restrictions, descriptor fallback, pre/post checks | String canonicalization cannot close replacement races. [CITED: kernel.org path lookup docs] |
| Generation durability | in-place mutable index + backup flag | closed sibling generation, full validation, atomic pointer + fsync | Readers must never observe partial index state. [VERIFIED: D-04] |
| PDF extraction/OCR | native byte scraping or subprocess extraction | registered external UTF-8 text and immutable provenance | Explicit phase boundary and parser attack surface. [VERIFIED: D-13] |
| FTS language | client-provided MATCH/regex | bounded server tokenizer/query compiler | FTS operators change semantics and resource cost. [CITED: sqlite.org/fts5.html] |
| Unicode normalization/word breaking | undocumented locale-dependent behavior | explicit `none-v1`, SQLite Unicode61, versioned CJK term encoder | Reproducibility and CJK fixture coverage. [VERIFIED: D-11; AGENTS.md] |
| Snippet/outline freshness | trust mtime/size or stored body | descriptor identity + full live source digest before body load | Same-size/restored-mtime changes otherwise leak stale text. [VERIFIED: D-07, D-08] |
| Rename lineage | content hash alone | unique fingerprint, then unique digest bipartite reconciliation | Duplicate content must stay distinct. [VERIFIED: D-05] |
| Tool/schema duplication | handwritten native schema strings | generated header from checked JSON schemas | Prevents staged/native drift. [VERIFIED: established schema identity pattern] |
| Cursor authorization crypto | bespoke MAC/key store | stateless bound cursor plus independent root/generation/limit validation | Cursor is not an authority token; unkeyed SHA is only corruption evidence. [VERIFIED: project hash policy] |

**Key insight:** every convenient mutable shortcut—watcher refresh, in-place FTS, path-key identity, pre-gate snippets, or raw extraction—crosses a locked trust boundary. The implementation should spend complexity on immutable publication and live revalidation, not on hidden automation.

## Common Pitfalls

### Pitfall 1: Reusing the generic MCP main path
**What goes wrong:** hidden watcher/session/auto-index/config writes remain reachable, and more than five tools are advertised.  
**Avoidance:** branch to the files profile before generic initialization and assert exact side effects/tool names from a direct binary process. [VERIFIED: current startup audit]

### Pitfall 2: Calling an SQLite file immutable before it is immutable
**What goes wrong:** SQLite skips locks/change detection and may return incorrect/corrupt results if the file changes.  
**Avoidance:** close/check/hash/fsync/finalize first; never rename, unlink, or mutate a generation while any query may use it. [CITED: sqlite.org/uri.html; sqlite.org/howtocorrupt.html]

### Pitfall 3: Emitting a snippet before checking live source
**What goes wrong:** even if a later field says stale, old body text has already entered the agent response.  
**Avoidance:** metadata-only candidate query, live full-digest gate, then body load; scan responses/evidence for stale canaries. [VERIFIED: D-07]

### Pitfall 4: Treating mtime and size as freshness
**What goes wrong:** same-size rewrites or restored mtimes retain stale searchable text.  
**Avoidance:** full SHA-256 plus descriptor identity for build and body-bearing query paths. [VERIFIED: existing pipeline gap; D-08]

### Pitfall 5: Inferring rename from duplicate content
**What goes wrong:** a copied paper silently inherits another file's identity.  
**Avoidance:** only one-to-one candidates; ambiguous groups are delete/create and tested with duplicates. [VERIFIED: D-05]

### Pitfall 6: Assuming trigram covers short CJK
**What goes wrong:** one- and two-character queries return no FTS rows.  
**Avoidance:** versioned CJK unigrams/bigrams; trigram remains the three-plus fallback. [CITED: sqlite.org/fts5.html]

### Pitfall 7: Letting query text reach MATCH
**What goes wrong:** operators, column filters, NEAR, prefixes, or future syntax alter semantics/cost.  
**Avoidance:** server tokenize and quote bounded terms; test adversarial punctuation/operators. [CITED: sqlite.org/fts5.html]

### Pitfall 8: Partial output on timeout
**What goes wrong:** ranking order and continuation are not reproducible, and limits become advisory.  
**Avoidance:** build a bounded page privately, check deadline throughout, serialize only after complete validation. [VERIFIED: D-12]

### Pitfall 9: Letting schema count and stage allowlists drift
**What goes wrong:** source tests pass while staged native contracts differ or required schemas are absent.  
**Avoidance:** registry-derived aggregate, generated C schema digest, staged `tools/list`/instance validation, exact negative canaries. [VERIFIED: current fixed-count gap]

### Pitfall 10: Treating a verdict as evidence
**What goes wrong:** a green summary can conceal leaked canaries, wrong binary, or unexecuted race schedule.  
**Avoidance:** hash raw commands, requests, streams, process status, environment allowlist, pre/post trees, barrier schedule, and canary scan into the verdict. [VERIFIED: Phase 1/2 evidence pattern]

## Validation Architecture

Phase 3 needs layered, fail-closed validation. A passing Python unit suite alone
cannot prove that the staged native process advertises only five tools, opens
its SQLite projection read-only, suppresses stale body text, or survives a
deterministically scheduled replacement race. Each plan therefore adds its
behavior to the same staged evidence chain instead of creating isolated smoke
tests.

### Validation Layers

| Layer | Purpose | Primary command | Required evidence |
|-------|---------|-----------------|-------------------|
| Contract/unit | Canonical generation, identity, cursor, extraction, limit, and receipt models | `UV_OFFLINE=1 uv run --frozen pytest -q tests/unit tests/schema` | Exact rejection codes, canonical bytes, schema parity, no partial writes |
| Parent integration | `arw files` registration/sync/rebuild/repair, rename/delete/ignore/version semantics, atomic generation promotion | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_admin.py tests/integration/test_file_generations.py` | Before/after trees, manifests, receipts, pointer bytes, SQLite integrity/hash |
| Native MCP integration | Exact five-tool profile, live list/read, generation-backed search/outline/context, no-write queries | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_mcp.py` | Raw JSON-RPC requests/results, tool list, cache/root trees, process status |
| Format/search matrix | CJK, Markdown, LaTeX, BibTeX, source, direct text, and registered PDF extraction | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_formats.py` | Deterministic hits/ranking/locations/outlines/context and extraction identity |
| Security/adversarial | Traversal, symlink, deterministic replacement races, malformed payload/cursor/DB, sensitive files, ceilings/timeouts | `UV_OFFLINE=1 uv run --frozen pytest -q tests/integration/test_files_security.py` | Barrier schedule, canary scan, unchanged trees, typed no-body denials |
| Staged E2E | Exact installed bytes, source hidden, network denied, projection deletion/rebuild, full requirement verdict | `UV_OFFLINE=1 ./scripts/verify-phase-3 --clean --evidence-root build/evidence/phase-03` | Hashed command ledger, stage inventory, generation trees, raw responses, verdict |

All file-plane test modules above are Wave 0 requirements if they do not yet
exist. Each implementation task runs the smallest relevant module; each plan
finishes with all Phase 3 modules; the final plan runs the frozen repository
suite plus source, Phase 1, Phase 2, and Phase 3 verifiers. No watch mode,
network fallback, source-checkout import, or unretained manual observation may
count as verification.

### Requirement And Decision Oracles

| Target | Observable oracle |
|--------|-------------------|
| FILE-01 / D-01, D-05, D-06 | One-root `list_files` returns stable logical IDs, current digest/type/size, extraction state, generation freshness, and distinct IDs for duplicate content; unambiguous rename preserves ID. |
| FILE-02 / D-08, D-10, D-12 | Byte and line reads are bounded and complete, report encoding/truncation/continuation, survive restart, and return no content on expected-digest or replacement conflict. |
| FILE-03 / D-07, D-11, D-12 | Exact and full-text modes paginate deterministically; CJK one/two/three-plus term fixtures work; stale candidates contain metadata only; raw FTS syntax and over-ceiling requests reject. |
| FILE-04 / D-14, D-15 | Deterministic normalized outlines match each declared structured format; plain/extracted text reports `no_structure`; context stays in one file/generation and honors its anchor and budget. |
| FILE-06 / D-03, D-04, D-05, D-16 | Create/modify/rename/delete/ignore/extractor-version matrices produce complete generations, no stale searchable canary, atomic pointer changes only after validation, and exact degraded/blocking receipts. |
| FILE-07 / D-13 through D-16 | Every declared format has explicit provenance; only registered complete/accessible PDF text is searchable; raw PDF bytes and failed/old extraction text never appear. |
| FILE-08 / D-01 through D-04, D-09 | Installed MCP advertises exactly five read-only tools and leaves root/cache/pointer/DB trees byte-identical; admin verbs exist only under parent `arw files`. |
| VER-03 / D-08, D-12, D-16 | Traversal, symlink/junction claim boundary, rename/swap/truncate/write races, sensitive paths, malformed JSON/UTF-8/cursors/manifests/DBs, and budget exhaustion all fail closed with retained raw evidence. |

The final verifier must also emit booleans for D-01 through D-16. A requirement
or decision is true only when its raw evidence files exist, hash into the top
verdict, and the staged command used the selected installed binary and schema
identity. Summary booleans do not substitute for raw evidence.

### Deterministic Race Harness

Use test-only named barriers in the native files profile at these boundaries:

1. after parent/root component open but before final file open;
2. after final descriptor open but before hashing/content read;
3. after bounded page buffering but before post-read descriptor/path checks;
4. after generation DB close/hash but before pointer promotion.

The parent test process waits for the barrier receipt, performs one exact
replacement action, releases the child, and records both trees and process
streams. Cover regular-file swap, symlink swap, rename-out/rename-in,
same-size/restored-mtime rewrite, truncate, append, and generation pointer/DB
replacement. Tests must be deterministic and never rely on sleep timing.

### Evidence Layout And Verdict

`scripts/verify-phase-3` should own and clean only a marked directory beneath
`build/evidence/phase-03/`. Preserve at least:

```text
build/evidence/phase-03/
├── commands/                 # stage, version, admin, MCP, tests, prior gates
├── stage/                    # exact inventory, canary scan, build identity
├── admin/                    # scan observations, generations, receipts, pointers
├── mcp/                      # tools/list and every tools/call request/result
├── races/                    # barrier schedules and before/after trees
├── formats/                  # normalized expected/actual fixtures
├── security/                 # denials, malformed cases, budget cases
├── rebuild/                  # delete/rebuild normalized equivalence
└── verdict.json              # hashes every retained file and maps requirements/Ds
```

The top verdict reports `technical_qualification` separately from
`release_qualification`. SUP-04 may keep release `BLOCKED`; it cannot turn a
technical failure into PASS and does not prevent a technically complete Phase
3 when all declared gates pass.

### Sampling And Full-Phase Gates

- After every task commit: run the directly affected unit/schema/integration
  module, with a target feedback latency below 60 seconds.
- After every plan: run all Phase 3 unit/schema/integration modules plus
  `git diff --check` and schema/header drift checks.
- Before staged qualification: run native build/test, source materialization,
  license/pre-vendor gates, and the complete frozen pytest suite offline.
- Final: run `scripts/verify-sources`, `scripts/verify-phase-1`,
  `scripts/verify-phase-2 --clean`, and `scripts/verify-phase-3 --clean`; inspect
  the top Phase 3 verdict and independently recount/hash its raw evidence.
- No manual-only item is expected. If the runtime cannot deterministically
  schedule a required race, that requirement remains unverified rather than
  being waived through visual inspection.

## Sources

### Repository Sources

- `.planning/phases/03-secure-files-first-data-plane/03-CONTEXT.md` - locked
  Phase 3 decisions and canonical references.
- `.planning/REQUIREMENTS.md` and `.planning/ROADMAP.md` - requirement and
  success-criterion authority.
- `vendor/sources/file-base/src/main.c`, `src/mcp/mcp.c`, `src/store/store.c`,
  and `src/pipeline/pipeline_incremental.c` - pinned native startup, query,
  storage, and incremental baselines.
- `vendor/patches/file-base/0002-phase1-confined-read.patch` and
  `tests/integration/test_mcp_confinement.py` - existing confined-read and
  adversarial evidence patterns.
- `src/arw/manifests.py`, `src/arw/evidence.py`, `src/arw/schema_registry.py`,
  `scripts/stage-plugin`, and `scripts/verify-phase-2` - immutable metadata,
  schema, stage, and qualification patterns.

### Primary Technical References

- Linux `openat2(2)` and path-resolution documentation - descriptor-relative
  confinement and `RESOLVE_*` semantics.
- SQLite FTS5 documentation - tokenizer, query syntax, ranking, and trigram
  constraints.
- SQLite URI and corruption documentation - read-only/immutable database
  lifecycle requirements.
- JSON Schema Draft 2020-12 - strict request/result contract validation.

---

*Research completed: 2026-07-14*
