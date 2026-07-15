# Phase 5: Rebuildable Research Graph and Evidence Queries — Research

**Researched:** 2026-07-15
**Domain:** disposable research-graph projections, deterministic rebuilds, bounded evidence-chain queries
**Confidence:** HIGH for authority boundaries and protocol reuse; MEDIUM for native graph projection implementation until the first clean-build benchmark is retained

## Planning basis

No `05-CONTEXT.md` was created. Planning continues from the locked roadmap and
requirements, the Phase 3 files-plane contract, the Phase 4/04.1 qualification
evidence, and the pinned upstream file-base implementation. The phase does not
invent a second transport or a new research protocol. Existing upstream
protocols remain authoritative: MCP `2025-11-25` over newline-delimited stdio,
JSON Schema Draft 2020-12, and the pinned file-base graph/Cypher engine where
the ARW profile can prove its narrower read-only boundary.

## Requirements covered

| Requirement | Required truth | Planned evidence |
|---|---|---|
| GRAPH-01 | Validated canonical manifests project to Run, Stage, Artifact, Claim, Source, Dataset, Experiment, Figure, Review, and Gate nodes/edges. | Parent projection contract, fixture corpus, node/edge inventory, staged query transcript. |
| GRAPH-02 | Every entity carries stable identity, source digest, schema version, supersession state, and canonical ledger watermark. | Strict schemas, canonical bytes, identity collision tests, receipt binding. |
| GRAPH-03 | Delete graph/file indexes and rebuild from unchanged canonical inputs with equivalent normalized query results. | Full-rebuild/delete/rebuild oracle, before/after canonical snapshots, retained receipt and normalized result hashes. |
| GRAPH-04 | Incremental projection equals clean full rebuild after modify, rename, delete, correction, migration, and supersession. | Mutation matrix and pairwise normalized-result comparison. |
| GRAPH-05 | Authorized clients use bounded allowlisted traces from claims to sources, datasets, experiments, figures, reviews, and gate evidence. | Strict query request/result schemas, allowlisted templates/compiler, depth/row/byte/time ceilings, negative raw-query tests. |
| GRAPH-06 | Projection corruption, staleness, deletion, or unavailability cannot alter provenance, gate verdicts, accepted state, or next legal transition. | Canonical state/gate before/after snapshots, tamper and unavailable-index probes, fail-closed query receipts. |
| VER-05 | Clean, full, incremental, delete, rename, migration, correction, and supersession results are compared under a declared normalization oracle. | `scripts/verify-phase-5`, raw mutation fixtures, oracle version/digest, verdict JSON. |

## Existing architecture and gaps

Phase 2 and Phase 4 make the Python parent, append-only ledger, immutable
manifests, reducer, and human-gate records authoritative. Phase 3 already
implements parent-only generation administration and a five-tool read-only
files MCP. Those boundaries are prerequisites, not things to weaken:

- `src/arw/runtime.py`, `reducer.py`, `journal.py`, `manifests.py`, and
  `orchestration.py` own accepted state and event order.
- `src/arw/files.py` and `file_models.py` own disposable file generations and
  atomic selection; the selected index is never a provenance source.
- `src/arw/schema_registry.py` is the checked-in schema registry and must be
  extended by registry-derived Phase 5 names rather than a second hard-coded
  count.
- `vendor/sources/file-base` is the exact pinned tree at
  `ee68144af5453addda995a27cce8142999f318fb`. It contains a SQLite graph store
  and a read-only Cypher subset. Its generic MCP advertises broad graph/index
  tools, including mutation-capable administrative paths; those tools must not
  be exposed through the ARW agent profile.
- `vendor/patches/file-base` currently contains the ordered Phase 1/3 patches.
  Any native graph projection change is a new numbered patch applied only to a
  clean materialized tree and recorded in the source manifest, SBOM, and build
  identity. Never edit the materialized upstream checkout in place.

The missing capability is a research-ontology projection and a stable query
surface that can be rebuilt without reading chat history or treating SQLite as
authority. The first implementation should keep canonical manifest traversal
in Python, produce deterministic projection input records, and use the native
store only as a disposable execution/index layer. This makes a projection
failure observable without changing a legal transition.

## Locked protocol and boundary decisions

1. **Reuse upstream protocols.** MCP remains `2025-11-25` JSON-RPC over stdio;
   tool definitions include strict input and output schemas. Do not add a
   newline custom RPC, HTTP service, or raw Cypher contract.
2. **Parent is sole projection administrator.** Build, migrate, delete,
   rebuild, and atomically publish graph generations are parent-controlled
   operations. Agent-facing queries are read-only and cannot select roots,
   generations, budgets, or administrative modes.
3. **Graph is disposable.** Canonical events, manifests, source digests,
   ledger watermarks, gate decisions, and their hashes decide provenance and
   legality. Graph/file indexes may only answer a query or return a typed
   `projection_unavailable`, `projection_stale`, or `projection_corrupt`
   result.
4. **Separate research labels from code labels.** The existing upstream
   code-knowledge schema is not silently reinterpreted as research truth.
   Research nodes use a versioned ARW projection schema and explicit labels;
   upstream store fields are adapters, not authority.
5. **Allowlisted query templates.** Expose named operations such as
   `trace_claim`, `trace_source`, `trace_experiment`, `trace_review`, and
   `trace_gate_evidence`. A request contains a validated stable ID, an
   operation-specific direction/depth and lower-than-server limits. It never
   contains arbitrary Cypher, SQL, a path, or a generation pointer.
6. **Canonical-before-projection.** A projection receipt binds the source
   ledger head, manifest digests, schema/projection algorithm version, input
   inventory digest, output generation digest, and normalized oracle digest.
   Publish only after the complete generation is closed, checked, and atomically
   selected. A retry starts from the same canonical watermark.

## Projection data model

Each node is a canonicalized record with:

```text
entity_type, entity_id, source_digest, schema_version,
supersession_state, ledger_watermark, payload_digest
```

`entity_id` is derived from the authoritative manifest identity and namespace,
not from row order or a mutable path. `source_digest` is the digest of the
canonical source manifest/event/artifact bytes that justify the node. The
watermark identifies the last accepted ledger event included in the record.
Supersession is explicit (`active`, `superseded`, `corrected`, `deleted`, or
`unavailable`) and never inferred from a missing row.

Edges are records with deterministic `(edge_type, from_id, to_id, evidence_digest,
ledger_watermark)` keys. Project only relationships explicitly represented by
validated manifests or accepted events, for example:

- Run `contains` Stage; Stage `produces` Artifact;
- Claim `supported_by` Source/Dataset/Experiment/Figure;
- Review `reviews` Claim/Artifact and `dissent_for` or `synthesizes` Review;
- Gate `requires` or `evidenced_by` the exact artifact/review/report hashes.

The projection must preserve minority/dissent and supersession edges rather
than collapsing them into one current row. Every node/edge row is sorted by
stable type/id/key before serialization. The parent writes an input bundle and
receipt; the native builder reads only that bundle and emits a validated
generation. A generation contains its manifest, node/edge counts, schema and
algorithm versions, database digest, and a closed-generation receipt.

## Rebuild and equivalence oracle

The oracle is versioned (`research-graph-normalization-v1`) and checked into
the evidence bundle. It compares semantic rows, not SQLite page bytes:

1. Load only validated node/edge records and query result envelopes.
2. Remove backend row IDs, planner timing, process IDs, filesystem paths to
   temporary directories, and nondeterministic timestamps.
3. Normalize object keys recursively, sort nodes/edges by stable identity and
   relationships by `(edge_type, from_id, to_id, evidence_digest)`, and retain
   explicit state/digest/watermark fields.
4. Normalize query pages by operation, requested IDs, result identity, exact
   evidence digests, and continuation binding; no score or insertion order may
   decide equality unless it is part of the declared contract.
5. Compare full clean build, delete/rebuild, and incremental outputs. Record
   both normalized bytes and their SHA-256, the input watermark, generation
   receipt, and a diff on failure.

The mutation corpus must exercise independent and combined operations:

| Mutation | Expected identity/evidence behavior |
|---|---|
| modify payload | Same logical entity, new source/payload digest, supersession/correction edge. |
| unambiguous rename | Same file/source lineage and entity identity; path is non-authoritative metadata. |
| delete | Explicit deleted/superseded state or tombstone; no stale body-bearing query result. |
| correction | New correction artifact/claim lineage plus append-only supersedes edge. |
| migration/schema bump | New projection generation/schema version with identical semantics where fixtures are compatible; incompatible schema fails closed. |
| supersession | Old node remains addressable as superseded and exact new node/edge is visible. |

## Query and resource budgets

The Phase 3 five-tool ceilings remain the lower-level safety boundary. Phase 5
adds graph-specific server ceilings: maximum result rows, hop depth, edge fanout,
serialized bytes, query time, and continuation size. Clients can request lower
values only. A timeout or budget exhaustion returns no partial semantic page.
Each result includes operation/schema/projection generation/watermark and a
typed freshness/availability state. Query handlers do not write caches, advance
the ledger, or repair a generation.

## Threat model

| Threat | Required mitigation/evidence |
|---|---|
| Graph row or SQLite page is tampered | Verify generation/receipt/database digests before query; return `projection_corrupt`; canonical state unchanged. |
| Stale generation answers a current gate question | Bind query to requested watermark and live source/manifest digests; reject stale or return metadata-only unavailable state. |
| Projection is deleted or builder is unavailable | Canonical status/reducer/gate commands still work; rebuild is an explicit parent operation; query returns typed unavailable. |
| Raw Cypher/SQL causes traversal or write | Do not accept raw query text; compile named templates and reject unknown operation/fields. Native write clauses remain disabled and tested. |
| Large fanout/deep traversal exhausts host | Enforce server-owned depth, rows, bytes, fanout and deadline before execution; no partial page. |
| Incremental omission after rename/delete/correction | Mutation matrix compares incremental against clean full rebuild under the oracle, including tombstones and supersession. |
| Graph becomes a hidden authority | Before/after canonical event/state/gate snapshots and forced projection failures prove identical legal transitions. |
| Stage leaks private graph/index/run data | Positive stage allowlist, SBOM/inventory/build identity and private-canary scan remain required; no generated graph database is staged. |

## Dependency and license posture

No new runtime package is recommended. Use the existing Python/Pydantic/
jsonschema/pytest stack and bundled SQLite/C implementation. Native changes are
an ordered patch over the pinned MIT file-base tree; notices and SBOM entries
must be regenerated. ARS remains an external exact installation under the
Phase 4 integration lock and is not silently re-licensed or bundled. The
collective plugin's mixed license verdict remains separate from Phase 5's
technical qualification.

## Official protocol references

- [MCP specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP tools and structured output](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- [Pinned file-base Cypher API](../../../../vendor/sources/file-base/src/cypher/cypher.h)
- [Phase 3 files-plane contract](../../../../docs/runtime/files-first-data-plane.md)
- [Project requirements](../../REQUIREMENTS.md) and [roadmap](../../ROADMAP.md)

## Validation Architecture

The phase uses the existing frozen environment and evidence conventions. No
network or package installation is required.

| Gate | Command | Purpose |
|---|---|---|
| Quick | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema tests/unit -k 'graph or schema'` | Contract, canonical bytes, identity and oracle feedback. |
| Phase | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema tests/unit tests/integration/test_graph_projection.py tests/integration/test_graph_queries.py tests/integration/test_graph_rebuild.py` | Projection, query, mutation and authority behavior. |
| Native | `UV_OFFLINE=1 ./scripts/verify-sources` plus the clean file-base normal/ASan+UBSan/TSan suites | Pinned source/patch and native safety regression. |
| Staged | `UV_OFFLINE=1 ./scripts/verify-phase-5 --clean --evidence-root build/evidence/phase-05` | Exact stage, MCP transcript, oracle, mutation corpus and verdict. |
| Full | `UV_OFFLINE=1 .venv/bin/python -m pytest -q` | Cross-phase regression after staged evidence. |

Every task has a narrow command and retained raw evidence. A required check
cannot be represented by an xfail or an unrecorded manual assertion. Technical
PASS remains distinct from the unresolved SUP-04/P04-09 release gates.
