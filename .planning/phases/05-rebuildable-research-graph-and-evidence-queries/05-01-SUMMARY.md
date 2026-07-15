---
phase: 05-rebuildable-research-graph-and-evidence-queries
plan: 01
subsystem: graph-contracts
tags: [pydantic, json-schema, projection, oracle, provenance]

requires:
  - phase: 04.1
    provides: Exact integration lock, staged identity and parent-only canonical authority
provides:
  - Strict Phase 5 graph node/edge/generation/receipt/query/result/oracle contracts
  - Registry-derived seven-schema Phase 5 contract set and deterministic checked schemas
  - Parent-only canonical manifest projector with stable ordering and digest binding
  - research-graph-normalization-v1 semantic equivalence oracle
affects: [05-02-native-graph-profile, 05-03-rebuild-equivalence, 05-04-staged-verifier]

tech-stack:
  added: []
  patterns:
    - Graph rows are disposable records bound to canonical source digest and ledger watermark
    - Graph projection input is canonical JSON and sorted independent of manifest arrival order
    - Query contracts contain named operations only; arbitrary Cypher/SQL is not a field

key-files:
  created:
    - src/arw/graph_models.py
    - src/arw/graph_projection.py
    - src/arw/graph_oracle.py
    - schemas/v1/graph-node.schema.json
    - schemas/v1/graph-edge.schema.json
    - schemas/v1/graph-projection-manifest.schema.json
    - schemas/v1/graph-projection-receipt.schema.json
    - schemas/v1/graph-query-request.schema.json
    - schemas/v1/graph-query-result.schema.json
    - schemas/v1/graph-oracle.schema.json
    - tests/schema/test_graph_contracts.py
    - tests/integration/test_graph_projection.py
  modified:
    - src/arw/schema_registry.py
    - scripts/stage-plugin

key-decisions:
  - "The Phase 5 schema registry derives its graph names from the model registry; schema consumers no longer need a stale numeric count."
  - "Projection code verifies payload/evidence digests and contiguous replay sequences, and never appends or rewrites runtime events."
  - "The stage allowlist includes regenerated Phase 5 schema artifacts immediately so existing installed-package gates remain green."

requirements-completed: [GRAPH-01, GRAPH-02]

duration: 25 min
completed: 2026-07-15
---

# Plan 05-01 Summary

Phase 5 now has strict contracts and a deterministic parent-side projection
input/oracle boundary. The implementation deliberately does not make SQLite,
the native graph store, or query output authoritative.

## Accomplishments

- Added seven Draft 2020-12 schemas for graph nodes, edges, projection
  manifests/receipts, query requests/results and oracle comparisons.
- Added ten required research entity labels and explicit evidence,
  correction, dissent and supersession edge types.
- Added stable source/payload/evidence digest and ledger watermark validation,
  canonical ordering, duplicate detection, and typed stale/unavailable result
  contracts.
- Added a read-only projector for canonical manifest records and replay prefixes;
  it rejects missing targets, digest substitution and non-contiguous event
  sequences.
- Added `research-graph-normalization-v1`, which removes only backend noise and
  preserves semantic IDs, exact evidence digests, states and watermarks.
- Added a ten-entity fixture and independent tests for replay stability,
  malformed input, and oracle behavior.

## Deviations from Plan

**[Rule 1 - Missing critical integration] Stage allowlist update** — Found
during: schema registry verification. Adding seven generated Phase 5 schemas
caused the existing positive stage inventory gate to reject otherwise valid
stages. Added the seven regenerated `share/arw/schemas/*` paths to
`scripts/stage-plugin`; no private or runtime graph data is staged. Verified by
the existing staged inventory and version tests.

**Total deviations:** 1 auto-fixed (packaging allowlist closure). **Impact:**
No authority or license boundary changed; the exact stage now covers the new
contract artifacts.

## Verification

- `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema/test_graph_contracts.py tests/schema/test_schema_drift.py tests/schema/test_phase4_contracts.py tests/schema/test_files_contracts.py tests/unit/test_orchestration_models.py tests/unit/test_graph_projection.py tests/integration/test_graph_projection.py` — **30 passed**.
- Existing staged inventory/version smoke after schema addition — **2 passed** focused and the inventory stage gate passes.
- `git diff --check` — **passed**.

## Task Commits

1. `746e1ef` — test(05-01): add graph contract and projection fixtures
2. `f2f8534` — feat(05-01): add strict research graph contracts
3. `aa405c0` — feat(05-01): add deterministic graph projector and oracle

## Self-Check: PASSED

- All created contract/projector/oracle files exist.
- GRAPH-01 and GRAPH-02 are covered by executable schema and projection tests.
- Phase 5 remains technically in progress; no release or legal verdict was changed.

