---
phase: 05-rebuildable-research-graph-and-evidence-queries
slug: rebuildable-research-graph-and-evidence-queries
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-15
---

# Phase 05 — Validation Strategy

> Validation is defined before implementation. The graph is a disposable
> projection; all authority and rebuild claims are tested against canonical
> ledger/manifests and retained raw evidence.

## Test Infrastructure

| Property | Value |
|---|---|
| Framework | Frozen `.venv` pytest 9.1.1, jsonschema 4.26.0, bundled file-base C tests |
| Config | `pyproject.toml`, `uv.lock`, `vendor/python/wheelhouse.lock.json` |
| Quick run | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema tests/unit -k 'graph or schema'` |
| Phase run | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema tests/unit tests/integration/test_graph_projection.py tests/integration/test_graph_queries.py tests/integration/test_graph_rebuild.py` |
| Staged gate | `UV_OFFLINE=1 ./scripts/verify-phase-5 --clean --evidence-root build/evidence/phase-05` |
| Full run | `UV_OFFLINE=1 .venv/bin/python -m pytest -q` |
| Estimated runtime | quick under 60s; phase under 180s; staged/native qualification under 10m |

## Sampling Rate

- Run each task's narrow command immediately after the task.
- Run all Phase 5 modules and `git diff --check` after each plan.
- Run schema registry/source patch checks after every native patch or schema change.
- Run the staged verifier after the final plan and before any requirement status changes.
- No more than two implementation tasks may land without a phase-module run.

## Threat Register

| Ref | Threat | Required secure behavior |
|---|---|---|
| T05-01 | Projection rows or database are tampered | Receipt/database digest verification returns `projection_corrupt`; no canonical mutation. |
| T05-02 | Stale graph answers current evidence/gate question | Watermark and source-digest binding rejects stale body-bearing results. |
| T05-03 | Delete/unavailable projection is treated as authority | Canonical status, gates, and transitions work without projections; queries return typed unavailable. |
| T05-04 | Raw query/write or unbounded traversal | Named allowlist only; strict schemas, max depth/fanout/rows/bytes/deadline; write clauses rejected. |
| T05-05 | Incremental projection omits rename/delete/correction/supersession | Mutation matrix compares normalized incremental and clean rebuild outputs. |
| T05-06 | Normalization hides meaningful provenance differences | Oracle preserves stable IDs, exact digests, supersession, watermarks and evidence hashes. |
| T05-07 | Private graph/index/run data enters stage | Positive stage allowlist, inventory/SBOM/build identity and private canary scan stay green. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirements | Threat refs | Test type | Automated command | Status |
|---|---:|---:|---|---|---|---|---|
| 05-01-T01 | 01 | 1 | GRAPH-01, GRAPH-02 | T05-05, T05-06 | schema/unit | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/schema/test_graph_contracts.py tests/unit/test_graph_projection.py` | passed |
| 05-01-T02 | 01 | 1 | GRAPH-01, GRAPH-02 | T05-01, T05-06 | unit/integration | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/unit/test_graph_projection.py tests/integration/test_graph_projection.py` | passed |
| 05-02-T01 | 02 | 2 | GRAPH-03, GRAPH-05 | T05-01, T05-03, T05-04 | native/integration | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/integration/test_graph_queries.py tests/integration/test_graph_mcp_profile.py` | passed |
| 05-02-T02 | 02 | 2 | GRAPH-05, VER-05 | T05-04 | adversarial | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/integration/test_graph_queries.py -k 'allowlist or bound or timeout or readonly'` | passed |
| 05-03-T01 | 03 | 3 | GRAPH-03, GRAPH-04, VER-05 | T05-05, T05-06 | mutation/oracle | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/integration/test_graph_rebuild.py -k 'full or incremental or rename or delete or correction or migration or supersession'` | passed |
| 05-03-T02 | 03 | 3 | GRAPH-06 | T05-01, T05-02, T05-03 | crash/tamper | `UV_OFFLINE=1 .venv/bin/python -m pytest -q tests/integration/test_graph_authority.py` | passed |
| 05-04-T01 | 04 | 4 | GRAPH-01..06, VER-05 | T05-01..T05-07 | staged E2E | `UV_OFFLINE=1 ./scripts/verify-phase-5 --clean --evidence-root build/evidence/phase-05` | passed |
| 05-04-T02 | 04 | 4 | GRAPH-01..06, VER-05 | T05-01..T05-07 | serial verifier/regression | `UV_OFFLINE=1 ./scripts/verify-phase-5 --clean --evidence-root build/evidence/phase-05`; non-host regression `371 passed, 1 deselected` | passed |

## Wave 0 Requirements

- [x] Create strict graph node, edge, projection receipt, query, result, and oracle contracts.
- [x] Create deterministic fixture corpus for all ten node kinds and all required mutations.
- [x] Add test module paths referenced by the plans before implementation tasks begin.
- [x] Define the staged verifier evidence layout and private-canary scan.

## Manual-Only Verifications

None. A reviewer may inspect the retained evidence, but a required technical
behavior is not accepted on an unrecorded manual assertion.

## Full-Phase Sign-Off Gates

- [ ] GRAPH-01 through GRAPH-06 are true in the raw-evidence-bound top verdict.
- [ ] VER-05 oracle compares clean, full rebuild, incremental, delete, rename, migration, correction, and supersession cases.
- [ ] Every projected node/edge has stable identity, source digest, schema version, supersession state, and ledger watermark.
- [ ] Allowlisted queries are bounded, read-only, and typed for stale/corrupt/unavailable generations.
- [ ] Canonical event/state/gate snapshots are identical before and after projection failure or deletion.
- [ ] Exact staged package contains no private graph/index/run data and all stage identity/SBOM checks pass.
- [ ] Frozen full pytest, source verifier, prior Phase 1–4.1 technical verifiers, and Phase 5 verifier pass.
- [ ] SUP-04/P04-09 release blockers remain separately truthful.

The Phase 5 verifier, source verification, and all non-host regression tests pass.
The frozen host-inclusive run recorded 370 passed and five failures: three were
temporary `/tmp` quota exhaustion (the repo-local staging root now prevents
this), while the two Codex-host route checks are blocked by the installed host's
external usage-limit response. This is retained as an environment qualification
blocker, not converted into an xfail or a technical pass.

## Validation Sign-Off

- [x] Every planned task has an automated verify command.
- [x] Sampling continuity is defined and no watch-mode/network-dependent command is used.
- [x] `nyquist_compliant: true` and `wave_0_complete: true` are declared for planning; execution must replace pending rows with evidence.
