# Phase 3: Secure Files-First Data Plane - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 03-secure-files-first-data-plane
**Areas discussed:** Root capability and administration, file identity and freshness, read/search/pagination contracts, document structure and extraction

---

## Root Capability And Administrative Boundary

### Root exposure

| Option | Description | Selected |
|--------|-------------|----------|
| One named root per process | Least privilege; parent launches isolated instances for multiple roots | Yes |
| Multiple named roots per process | Request selects a root ID, but one process holds broader authority | |
| Single-root default with optional multi-root manifest | Flexible but expands Phase 3 contract and security matrix | |

**User's choice:** One named root per MCP process.

### Administrative command surface

| Option | Description | Selected |
|--------|-------------|----------|
| Parent-only `arw files` CLI | MCP binary exposes only read/query operations | Yes |
| Administrative mode in the same binary | Extra startup mode and capability token enable mutation | |
| Separate administrative MCP | Independent privileged protocol and approval surface | |

**User's choice:** Parent-only `arw files` CLI.

### Refresh trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic boundary refresh | Run start, recovery, or explicit sync; query never writes | Yes |
| Background watcher | Automatically reindexes after changes | |
| Boundary refresh plus optional watcher | Two consistency paths and larger test matrix | |

**User's choice:** Deterministic boundary refresh.

### Generation publication

| Option | Description | Selected |
|--------|-------------|----------|
| Build and atomically promote a new generation | Preserve prior generation on failure and emit a receipt | Yes |
| Transactionally update the active index | Lighter but harder to audit across extraction failures | |
| In-place incremental updates plus generational rebuild | Different publication semantics for sync and rebuild | |

**User's choice:** New generation with atomic promotion.
**Notes:** The user accepted all recommended least-privilege and deterministic-publication choices without modification.

---

## File Identity And Freshness

### Stable identity across rename

| Option | Description | Selected |
|--------|-------------|----------|
| Persistent logical file ID | Preserve unambiguous rename lineage; keep duplicate files distinct | Yes |
| Path-derived identity | Rename becomes deletion plus creation | |
| Content-derived identity | Duplicate content collides and edits require extra lineage rules | |

**User's choice:** Persistent logical file ID with conservative rename lineage.

### Live versus indexed view

| Option | Description | Selected |
|--------|-------------|----------|
| Live list/read plus generation queries | Current descriptor-safe bytes for reads; promoted snapshot for search/outline/context | Yes |
| All queries use the index snapshot | Perfect generation consistency but stale direct reads | |
| All queries require a current root | Any edit blocks every query until sync | |

**User's choice:** Separate live reads from generation-backed queries.

### Stale body handling

| Option | Description | Selected |
|--------|-------------|----------|
| Return stale identity/location only | Suppress old snippet, outline, and context text | Yes |
| Return full stale result with warning | More convenient but old text can be mistaken for evidence | |
| Fail the whole query | One stale file blocks otherwise fresh results | |

**User's choice:** Return stale metadata without stale body text.

### Read-after-search replacement

| Option | Description | Selected |
|--------|-------------|----------|
| Bind `file_id` and `expected_digest` | Mismatch or replacement yields no-body `stale_conflict` | Yes |
| Always read latest by path | Search and read may refer to different bytes | |
| Read a retained generation content copy | Reproducible old bytes but expands private-content retention | |

**User's choice:** Digest- and identity-bound reads.
**Notes:** A stale index can aid navigation, but stale content must not enter the agent context.

---

## Read, Search, And Pagination Contracts

### MCP tool surface

| Option | Description | Selected |
|--------|-------------|----------|
| Five single-purpose tools | Separate list, read, search, outline, and context schemas and authorization | Yes |
| One mode-dispatched query tool | Smaller list but complex unions and coarse authorization | |
| MCP Resources for list/read plus Tools for search/extract | Two protocol surfaces and URI/error models | |

**User's choice:** Five single-purpose tools.

### Continuation model

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit initial range plus bound continuation | Direct line/byte targeting with identity-safe continuation | Yes |
| Explicit offset/limit on every request | Simple but clients can drift across file versions | |
| Opaque cursors only | Consistent but prevents direct source-range requests | |

**User's choice:** Explicit initial range followed by bound continuation tokens.

### Exact and full-text behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit `exact` or `full_text` mode | Versioned, reproducible behavior without hidden mixing | Yes |
| Automatically mix exact and full-text hits | Convenient but ranking is harder to explain and reproduce | |
| Expose raw FTS syntax | Expressive but backend-specific and potentially expensive | |

**User's choice:** Explicit, non-mixed search modes.

### Budget exhaustion

| Option | Description | Selected |
|--------|-------------|----------|
| Hard ceilings and complete resumable pages | Reject oversized input; timeout has no partial page | Yes |
| Return computed partial results | Useful but may omit better-ranked unseen hits | |
| Treat every truncation as failure | Strict but makes large-file retrieval impractical | |

**User's choice:** Hard server ceilings with complete resumable pages.
**Notes:** Clients may lower budgets but cannot raise server ceilings or request raw backend queries.

---

## Document Structure And Extraction Semantics

### PDF handling

| Option | Description | Selected |
|--------|-------------|----------|
| Parent-registered PDF extraction | MCP indexes UTF-8 extraction plus original/extractor provenance | Yes |
| Built-in text-layer PDF extraction | Adds a pinned PDF parser but no OCR | |
| Built-in and external extraction paths | Broadest coverage but requires equivalence and precedence rules | |

**User's choice:** Parent-registered PDF extraction only.

### Outline normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Format-aware deterministic structure | Normalize native Markdown/LaTeX/BibTeX/source structures; no guessing | Yes |
| Heuristic outline for every format | Broader but may invent structure and drift across versions | |
| Markdown and LaTeX only | Too narrow for the declared BibTeX/source coverage | |

**User's choice:** Format-aware normalized outlines without heuristics.

### Context construction

| Option | Description | Selected |
|--------|-------------|----------|
| Anchor plus containing structure | Same file/generation, target plus section/definition and bounded neighbors | Yes |
| Fixed line radius | Simple but can cut structural units | |
| Cross-file semantic expansion | Richer but belongs to graph/semantic retrieval work | |

**User's choice:** Anchored, same-file structural context.

### Extraction and integrity failure

| Option | Description | Selected |
|--------|-------------|----------|
| Distinguish content failure from integrity failure | Explicit degraded generation for parse failures; block integrity failures | Yes |
| Block generation on every file failure | One unsupported file prevents root refresh | |
| Silently skip failed files | Search cannot honestly report corpus gaps | |

**User's choice:** Typed degraded publication with fail-closed integrity.
**Notes:** Extractor-version changes require affected files to be re-extracted before promotion.

---

## the agent's Discretion

- Logical-ID persistence format and conservative rename-detection algorithm.
- Generation layout, cursor encoding, schema decomposition, and atomic pointer mechanics.
- Concrete hard budgets, CJK tokenizer, exact-match normalization, and ranking constants after benchmarks.
- Deterministic parser choices and detailed failure taxonomy within the locked promotion rules.
- Number and shape of ordered upstream file-base patches.

## Deferred Ideas

- Raw PDF parsing, OCR, and office-format ingestion remain v2 ingestion work.
- Cross-file semantic context belongs to Phase 5 graph/evidence queries.
- Background watcher refresh, one-process multi-root operation, administrative MCP tools, and a parallel MCP Resources interface are excluded from Phase 3.
