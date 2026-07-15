# Research graph runtime contract

The research graph is a disposable projection of canonical ARW manifests and
ledger prefixes. The append-only ledger, immutable manifests, gate decisions,
and their hashes remain authoritative. A missing, stale, corrupt, or deleted
projection can only produce a typed query failure; it cannot change a runtime
transition or a human gate.

## Parent lifecycle

The parent writes a canonical `GraphProjectionInput` bundle, builds a sibling
generation, verifies the SQLite integrity/counts and database digest, writes a
closed manifest and receipt, and atomically replaces the selected-generation
pointer. Full, incremental, migration, delete/rebuild, and repair are parent
operations. Repeated input is idempotent and reuses the closed receipt.

Generation directories, SQLite files, input bundles, receipts, and mutation
fixtures are evidence or runtime state and are never staged in the plugin.

## Query profile

`scripts/file-base-graph-mcp` starts the installed Python graph adapter with an
explicit control root and root ID. It speaks MCP `2025-11-25` JSON-RPC over
stdio and exposes only these fixed, read-only tools:

`trace_claim`, `trace_source`, `trace_experiment`, `trace_review`,
`trace_gate_evidence`, and `graph_health`.

Requests contain a stable entity ID and lower-than-server depth, fanout, row,
byte, deadline, and watermark limits. Raw Cypher, SQL, paths, generation
selectors, administrative operations, and unknown fields are rejected before
execution. Every successful page binds the operation, selected generation,
manifest digest, ledger watermark, semantic rows, and evidence digests. Budget
exhaustion and all freshness/integrity failures return no partial semantic
page.

## Evidence and rebuilds

`research-graph-projection-v1` and
`research-graph-normalization-v1` are build-identity inputs. The normalization
oracle removes only backend coordinates such as row IDs and temporary paths;
source, payload, evidence, supersession, and ledger digests remain semantic.
The Phase 5 verifier retains MCP transcripts, mutation receipts, normalized
bytes/digests, and canonical before/after authority snapshots.
