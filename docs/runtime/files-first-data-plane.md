# Files-First Data Plane

The files-first plane separates parent-controlled administration from an
agent-facing, read-only MCP process. One MCP process is authorized for exactly
one registered root and snapshots exactly one selected generation at startup.

## Ownership Boundary

- The parent owns root registration, extraction registration, synchronization,
  rebuild, repair, and generation selection through `arw files`.
- The MCP advertises exactly `list_files`, `read_file`, `search_files`,
  `get_outline`, and `get_context`.
- MCP requests never crawl, extract, synchronize, repair, rebuild, or select a
  generation. A query requiring newer bytes reports stale state instead.
- Control state must be outside the research root. Filesystem root and the
  operator home directory cannot be registered as research roots.

## Administrative Workflow

Register one root:

```bash
bin/arw files root register \
  --control-root /absolute/control \
  --root-id research-root \
  --root-path /absolute/research \
  --policy-id research-files-v1
```

Create and atomically select a complete generation:

```bash
ARW_FILES_NATIVE_BUILDER=/installed/plugin/libexec/file-base-mcp \
  bin/arw files sync \
  --control-root /absolute/control \
  --root-id research-root \
  --extractor-version 1.0.0
```

`sync` scans source truth, builds a sibling SQLite projection, closes and
validates its manifests and database, invokes the native publication gate, and
then atomically replaces the selected-generation pointer. A failed attempt
retains the prior selection and emits a blocked receipt.

Use `files status` for generation and extraction state. `files rebuild`
recreates disposable projection bytes from registered source truth. `files
repair` follows the same closed-generation promotion rules; neither operation
is available over MCP.

## Registered PDF Text

The data plane does not parse raw PDF, run OCR, or infer extraction quality.
The parent may register UTF-8 text only with:

- the source logical file ID and source SHA-256;
- the extracted-text SHA-256;
- extractor name and semantic version;
- extraction timestamp;
- complete/failed/malformed quality state; and
- accessible/missing/denied access state.

Only a complete, accessible registration matching the current source digest
and requested extractor version enters a generation. A missing, failed,
malformed, inaccessible, old-version, or digest-mismatched registration
degrades that PDF without blocking unrelated documents. Integrity failures in
generation artifacts block promotion.

## Launch Contract

The installed launcher receives its capability from the parent at runtime:

```bash
ARW_FILES_CONTROL_ROOT=/absolute/control \
ARW_FILES_ROOT_ID=research-root \
  /installed/plugin/scripts/file-base-mcp
```

Both variables are required together. The control root must already exist and
must not be a symlink. One process cannot add another root after startup. The
launcher resolves the hash-locked installed Python runtime and does not import
the source checkout or user site packages.

## Freshness and Reads

`list_files` and `read_file` inspect live files through component-wise,
no-follow descriptor opens. Search, outline, and context use the selected
immutable generation, then verify the live source digest before returning any
body-derived field.

- Current search hits include `file_id`, indexed/current digests, source
  location, score, snippet, and a signed context anchor.
- A changed, deleted, inaccessible, or replaced source returns metadata-only
  stale state. Score, location, snippet, outline nodes, context, and hit anchor
  are absent.
- A search-following read binds `file_id`, path, and `expected_digest`.
  Mismatch or descriptor replacement returns a no-body conflict.
- Byte reads are base64. Line reads require strict UTF-8.

## Search and Structure

Search mode is mandatory. `exact` is NFC-normalized and case-sensitive.
`full_text` accepts plain terms only, uses NFKC/casefold normalization, and
rejects raw FTS operators. Results declare tokenizer `unicode61-cjk-v1` and
ranking `files-rank-v1`; ties use logical file ID and source location.

Outlines are deterministic for Markdown headings, bounded LaTeX section
commands, BibTeX entries, and declared source definitions. Plain text and
registered PDF extraction text return `no_structure`. Context is adjacent
same-file text around a signed search hit or explicit byte/line location. It
does not perform semantic or cross-file expansion.

## Hard Ceilings

Server limits are part of the generated contract: 200 listed files, 65,536
read bytes, 1,000 read lines, 100 search hits, 2,048 snippet bytes, 200 outline
nodes, 200 combined context lines, 4,096 query/cursor bytes, and a five-second
request deadline. Clients can request lower bounds only. Timeout and budget
errors never return partial pages.

## Recovery

If generation startup reports an integrity or binding error, do not modify the
projection through MCP. Inspect parent receipts and `files status`, restore
registered source/extraction truth, and run `files rebuild` or `files repair`.
The selected pointer is never inferred from directory order. Projection
deletion is recoverable because manifests, registrations, and source files are
authoritative; SQLite is not.
