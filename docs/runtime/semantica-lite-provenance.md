# Semantica Lite Provenance

`knowledge.provenance` is an optional accountability projection. It is not a
source of authority: the ARW append-only ledger and immutable artifacts remain
canonical.

## Lite profile

The Lite adapter owns a SQLite sidecar (`*.semantica.sqlite3`) configured with
WAL, `busy_timeout=5000`, and explicit transactions. It records only:

- source artifact ID;
- canonical ledger event ID and digest;
- agent/activity attribution;
- deterministic SHA-256 record checksum; and
- bounded `derived_from` lineage.

A record without a non-empty artifact ID and an exact pair present in the
replay-validated event mapping is rejected before persistence. A valid
sidecar checksum never authorizes a state transition. `verify()` reports
checksum drift through ARW audit-fault receipts.

The capability is registered only when composition receives both an explicit
`semantica_store_path` and the extension can be imported. Otherwise resolving
`knowledge.provenance` returns `CapabilityUnavailable`; L0 operations remain
available.

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
