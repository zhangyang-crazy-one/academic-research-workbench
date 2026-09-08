# Semantica Lite Provenance

`knowledge.provenance` is an optional accountability projection. It is not a
source of authority: the ARW append-only ledger and immutable artifacts remain
canonical.

## Lite profile

The Lite adapter owns one run-scoped SQLite sidecar created with `0600`
permissions and explicit transactions. It uses SQLite's in-memory journal and
temporary store so no attacker-controlled `-wal`, `-shm`, or `-journal` path is
opened; the disposable sidecar is rebuilt from canonical artifacts after an
interrupted write. It records only:

- schema-versioned source artifact assertions;
- replay-injected canonical ledger event ID and digest;
- agent/activity attribution;
- deterministic artifact and binding SHA-256 checksums; and
- bounded `derived_from` lineage.

The immutable provenance artifact excludes acceptance-event fields, so its
checksum is calculable before `artifact.accepted`. Every checksum-bearing field is
required by the published Draft 2020-12 `provenance-record.schema.json`; the
schema is registered in the packaged schema inventory and build identity. Replay
injects the accepted event ID/digest and the adapter stores a separate binding
checksum. Accepted artifact digest mappings are mandatory whenever the capability
is enabled. Canonical provenance manifests use the explicit
`artifact_kind: provenance-record` discriminator; unrelated JSON artifacts are not
classified by content guessing. `rebuild` validates bounded regular artifact files and atomically
replaces the sidecar. `verify()` and `lineage()` compare stored rows with the
replay-derived canonical record inventory; modified, malformed, extra, or missing
rows fail closed and verification emits run-scoped ARW audit-fault receipts.
Sidecar checksums never authorize canonical state transitions.

`status --store` never treats an empty audit directory as proof of current
canonical equivalence. When provenance is active but no ledger-bound success
receipt exists, health reports `semantica_health_unknown` rather than `clean`.

The capability is registered only when composition receives both an explicit
`semantica_store_path` and the extension can be imported. Otherwise resolving
`knowledge.provenance` returns `CapabilityUnavailable`; L0 operations remain
available.

The Lite provenance provider currently requires POSIX descriptor-relative
filesystem primitives (`openat`/`dir_fd` and `O_NOFOLLOW`) for safe sidecar and
audit operations. On Windows the composition root deliberately leaves
`knowledge.provenance` unregistered, so resolution fails with
`CapabilityUnavailable` rather than attempting an unsafe fallback.

## Explicit exclusions

The default profile does **not** import or activate GraphRAG, FAISS, Neo4j,
FalkorDB, embeddings, torch, transformers, REST/MCP servers, or Explorer/UI.
The Lite implementation adds no Semantica or RDF dependency. A future explicit
PROV-O/RDF profile must introduce and qualify its own dependency group.

## Upgrade path

A full Semantica profile needs a separate approved change that adds explicit
capabilities (for example `knowledge.provenance_rdf_export` or
`knowledge.semantic_search`), a new supply-chain/license qualification, and
independent tests. It must not silently widen the Lite import surface.


## Complete traceability contract (provenance 2.0.0)

The parent artifact-accept command validates `provenance-record` payloads with
`schema_version: 2.0.0` before appending acceptance. `source_locator` binds the
source artifact and SHA-256, its already accepted event ID/digest, the producing
activity, an exact location, and the selected quote SHA-256. The source must be
retained under the run root and match its canonical acceptance. The assertion's
own acceptance binding is added only after append, avoiding a future-event hash
cycle. Locator fields participate in both artifact and sidecar checksums.

Supported locations are one-based inclusive text line ranges; one-based pages
in UTF-8 text separated by form feed; Markdown ATX sections selected by heading
and occurrence; and zero-based half-open byte chunks. Section spans include the
heading and end before the next heading of equal or higher level. Text locations
preserve exact UTF-8 bytes and newline spelling. Binary PDF page inference is
not performed: retain an accepted text extraction or use an exact byte chunk.
Reads are capped at 8 MiB and reject symlinks, traversal and nonregular files.

Lineage and rebuild resolve v2 locations against retained sources again. They
fail closed on source or locator drift. Legacy 1.0.0 records retain their original
schema and checksum and return `traceability: legacy_incomplete`; v2 returns
`complete` only after resolution. Removing the optional sidecar does not remove
historical event decoders or accepted source evidence.

Validation: 159 focused Semantica, locator, compatibility and schema tests passed
on 2026-09-08; all 18 locator tests passed again after the final input-digest recheck. The source-locator
suite covers actual parent admission, CLI lineage, sidecar deletion/rebuild,
locator tampering with a recomputed checksum, changed source bytes, unknown and
malformed locations, out-of-range spans, UTF-8/CRLF, and legacy byte stability.
