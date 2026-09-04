# Semantica Lite Provenance

`knowledge.provenance` is an optional accountability projection. It is not a
source of authority: the ARW append-only ledger and immutable artifacts remain
canonical.

## Lite profile

The Lite adapter owns one run-scoped SQLite sidecar created with `0600`
permissions and configured with WAL, `busy_timeout=5000`, and explicit
transactions. It records only:

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
