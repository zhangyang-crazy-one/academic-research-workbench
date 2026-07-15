# Phase 6: Scientific Integrity and Audit Dossier — Pattern Mapping

**Mapped:** 2026-07-15  
**Inputs:** `06-CONTEXT.md`, `06-RESEARCH.md`, the repository architecture in `AGENTS.md`, and the current Phase 1–5 implementation.

## Architectural shape to preserve

Phase 6 is a read/validate/assemble layer over the existing parent-owned
canonical runtime.  It must not add a second authority store, promote the
SQLite graph, or infer scientific claims from Markdown.  The intended flow is:

```text
replay_run + immutable manifests/passports
  -> strict receipt/provenance/access records
  -> freshness + capability gates (pure validation)
  -> graph/review/build/test receipt references
  -> canonical audit-dossier manifest (write-once)
  -> deterministic JSON and Markdown views
```

Publication and installation evidence remains separate from the release/legal
verdict.  The dossier should expose technical qualification and retain the
SUP-04/P04-09 mixed-license blocker rather than laundering it.

## Existing analogs and concrete symbols

| Phase 6 concern | Existing analog | Pattern to reuse | Verification anchor |
| --- | --- | --- | --- |
| Canonical digest bytes | `src/arw/canonical.py`: `canonical_json_bytes`, `sha256_hex`, `canonical_event_bytes` | Hash canonical UTF-8 JSON with sorted keys, no NaN, and omit only the record's self-digest field. Never accept a producer-supplied hash without recomputing it. | `tests/unit/test_canonical.py`; `tests/evals/test_phase4_corpus.py` |
| Immutable publication | `src/arw/manifests.py`: `_write_once`, `_install`, `manifest_bytes_and_sha256`, `load_artifact_manifest`, `load_material_passport` | Publish fsynced content-addressed files and reject replacement, symlink, collision, non-canonical bytes, or digest/path mismatch. New receipts/provenance/dossier records should use the same write-once semantics. | `tests/unit/test_manifests.py::test_artifact_manifest_has_canonical_content_address`; replacement/symlink tests in the same module |
| Canonical runtime truth | `src/arw/journal.py`: `replay_run`, `locked_replay`, `build_runtime_event`, `append_runtime_event_unlocked`; `src/arw/runtime.py`; `src/arw/reducer.py::reduce_events` | Replay and validate the ledger before collecting dossier inputs. Parent code may append typed evidence/gate events; renderers and graph adapters must remain read-only. | `tests/integration/test_journal_replay.py`, `test_recovery.py`, `test_runtime_transitions.py`; `tests/integration/test_orchestration_replay.py` |
| Freshness and accepted evidence | `src/arw/models.py`: `MaterialPassport.fresh_until`, `ArtifactManifest`; `src/arw/orchestration_models.py`: `GateDecision.fresh_until`; `src/arw/reducer.py` freshness/blocker logic | Compare current subject/input digests and an injected clock against `fresh_until`; stale records remain immutable and produce typed blockers. Do not use a mutable `fresh` boolean. | `tests/integration/test_human_gates.py::test_p04_05_t02_stale_evidence_cannot_finalize_run`; passport freshness tests in `tests/integration/test_passport_lifecycle.py` |
| Strict schema registry | `src/arw/schema_registry.py`: `SCHEMA_NAMES`, phase tuples, `validate_checked_in_schemas`, `regenerate_schemas`, `validate_instance` | Add Phase 6 model-generated schema names to one registry tuple and derive counts from it. Keep Draft 2020-12, `additionalProperties: false`, and generated/check-in equality. | `tests/schema/test_schema_drift.py`; `tests/schema/test_graph_contracts.py`; `tests/integration/test_version_report.py` |
| Graph projection is non-authoritative | `src/arw/graph_models.py`: `GraphProjectionReceipt`, `GraphProjectionManifest`; `src/arw/graph_projection.py`: `project_replayed_manifests`; `src/arw/graph_store.py`: `GraphStore.build`, `delete_and_rebuild`, `selected_generation` | Dossier records graph generation/receipt/watermark metadata only. On loss or staleness, rebuild from canonical inputs or retain a typed projection blocker; never use a graph row as a claim decision. | `tests/integration/test_graph_rebuild.py`; `tests/integration/test_graph_authority.py`; `tests/property/test_graph_replay.py` |
| Review and dissent composition | `src/arw/orchestration_models.py`: `ReviewReport`, `review_report_body_sha256`, `ReviewSynthesis`, `ReviewFindingMatrix`, `HumanAuthority`, `HumanDecisionRecord`, `GateDecision` | Collect exact report/synthesis/matrix hashes, preserve minority/DA dissent and blocker history, and bind every report to the frozen panel manifest. Reuse parent-validated authority and append-only decisions instead of creating a new synthesis path. | `tests/integration/test_orchestration_panels.py`; `tests/integration/test_human_gates.py`; `tests/unit/test_review.py` |
| Bounded evidence and secrets | `src/arw/evidence.py`: `write_evidence_bytes`, `write_evidence_json`, `record_command_result`; `src/arw/models.py` artifact contracts | Retain bounded logs as hashed artifacts, use an explicit environment allowlist/redaction, and put only references/digests in the dossier. Do not turn `evidence.py` into an unrestricted environment dump. | `tests/integration/test_phase2_verifier_safety.py`; `tests/integration/test_mcp_confinement.py`; staged private exclusion tests |
| Build/integration identity | `src/arw/build_identity.py::load_packaged_build_identity`; `src/arw/integration_lock.py`; `scripts/verify-phase-5` | Bind dossier build/source/schema/integration-lock/file-base/Codex identities to checked bytes. A missing or changed identity is a blocker, not a caller override. | `tests/integration/test_version_report.py`; `tests/unit/test_integration_lock.py`; `tests/staged/test_supply_chain_inventory.py`; `scripts/verify-phase-5` as verifier template |
| Positive staging boundary | `scripts/stage-plugin`; `tests/staged/test_private_exclusions.py`; `tests/staged/test_supply_chain_inventory.py` | Add only executable Phase 6 modules, schemas, docs, and verifier to the positive allowlist. Never stage generated dossier evidence, SQLite databases, private text, credentials, or temporary directories. | `scripts/stage-plugin --validate-only`; staged inventory/private-exclusion suites |

## Likely implementation seams

The following paths are the natural seams identified by the research handoff.
Exact class names remain implementation discretion, but each seam should stay
strict and independently testable.

| Path | Role | Inputs | Outputs / authority boundary |
| --- | --- | --- | --- |
| `src/arw/integrity.py` | Versioned receipt model, canonical receipt hashing, subject/input digest and freshness evaluator | canonical subject/source manifests, method/tool identity, injected `now` | immutable receipt + `PASS`/`FAIL`/`BLOCKED` reason codes; no ledger writes |
| `src/arw/experiment_provenance.py` | External-only experiment provenance envelope and controlled-execution policy | dataset/model/config/metric/artifact digests, redacted environment, runner identity, four qualification receipts | imported provenance or explicit blocked policy decision; no subprocess execution |
| `src/arw/evidence_access.py` | Exact five-state access decisions and capability evaluator | evidence/source/license metadata, receipts, lifecycle records, review/gate records | append-only access record and claim capability verdicts; never upgrades local/restricted evidence |
| `src/arw/audit_dossier.py` | Parent-owned collector, canonical manifest hash, deterministic renderers, cold-replay checks | replayed ledger/manifests/passports, Phase 4 reports/gates, Phase 5 receipts, tests/build identity | write-once dossier manifest plus JSON/Markdown views; renderers do not mutate canonical state |
| `schemas/v1/*phase6*.schema.json` | Checked-in strict wire contracts for receipt/provenance/access/dossier | model projections | Draft 2020-12 documents validated through the one registry |
| `scripts/verify-phase-6` | Serial bounded verifier and evidence writer | repository/staged tree, representative fixture, frozen clock | repo-local evidence, inventory/build identity, technical/release verdicts |
| `docs/runtime/scientific-integrity.md` | Contract and claim-state explanation | implementation and retained evidence | operator/reviewer documentation, not authority |
| `docs/runtime/audit-dossier.md` | Dossier sections, replay and blocker semantics | canonical manifest contract | deterministic view contract, not an alternate source of truth |

Suggested test seams from `06-RESEARCH.md` are deliberately parallel to the
implementation seams: schema/unit tests first, then integration tests for
freshness/provenance/access/claims, then replay/projection-loss, followed by a
serial staged verifier and full regression. Keep fixtures under
`tests/fixtures/phase6/` and generated evidence under the verifier-owned
`build/evidence/phase-06` root.

## Data-flow and ownership notes

1. The parent replays `src/arw/journal.py::replay_run`, validates accepted
   manifests with `src/arw/manifests.py::validate_accepted_event_manifests`, and
   obtains a stable ledger head before assembling a dossier.
2. New record models should derive their digest from canonical bytes (as
   `ReviewReport` and `GraphProjectionInput` do), use immutable stores (as
   artifact manifests/passports do), and expose exact replacement evidence on
   invalidation.
3. External experiment metrics are evidence of an external run, not proof that
   ARW reproduced it. The only Phase 6 execution mode is imported/external;
   caller booleans such as `sandbox_passed` or `reproduced` must not influence
   qualification.
4. Access decisions are five-state literals. A local cache does not imply
   `publicly_verified`; restricted/unavailable/ambiguous license evidence stays
   human-review-required or blocked.
5. Review matrix, dissent, human decisions, graph receipts, and test/build
   records are references to existing canonical material. A Markdown renderer
   must not append an event, alter a gate, or become the authority for a claim.
6. Technical qualification may pass while release qualification remains
   `BLOCKED` for SUP-04/P04-09 and unresolved intended-use/permission evidence.

## Verification pattern to carry forward

Run narrow tests serially before integration and staged verification to avoid
the prior full-install memory incident. Every failure should be retained as a
typed evidence record; do not delete tests or convert a genuine defect to
`xfail`. The phase verifier should:

- own and clean only `build/evidence/phase-06`;
- run schema/unit/integration suites with `UV_OFFLINE=1`,
  `PYTHONNOUSERSITE=1`, and controlled repo-local temporary storage;
- rerender a frozen representative dossier byte-for-byte;
- delete/rebuild the disposable graph and compare cold replay results;
- scan for secrets/private full text and require bounded paths;
- bind all report, graph, test, benchmark, source, build, and integration-lock
  hashes;
- run stage/inventory/SBOM/build-identity checks and record distinct technical
  versus release verdicts.

This follows the existing quick → phase → staged → full progression without
changing the dirty Phase 4/04.1 worktree.

## Deferred or out of scope

- Controlled experiment execution/native scheduler adapter until a separately
  qualified sandbox, approval, environment-capture, and provenance-equivalence
  design exists.
- Science Workbench v2 paper AST/export and complete research-to-paper
  replacement claims.
- Desktop UX, OCR/image-only PDF recovery, office-format expansion, cloud
  synchronization, telemetry, and multi-user coordination.
- License remediation or commercial permission acquisition beyond recording
  the accurate mixed-license blocker.

---

*Phase: 06-scientific-integrity-and-audit-dossier*  
*Pattern mapping completed: 2026-07-15*
