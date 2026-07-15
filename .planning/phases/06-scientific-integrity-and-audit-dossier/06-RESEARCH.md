# Phase 6: Scientific Integrity and Audit Dossier — Research

**Researched:** 2026-07-15  
**Domain:** immutable scientific-integrity receipts, externally executed experiment provenance, evidence access states, and deterministic audit dossiers  
**Confidence:** HIGH for composition with the existing ledger/manifests/graph/review contracts; MEDIUM for the first end-to-end dossier implementation until cold-replay and staged evidence are retained

## Research basis and phase boundary

Phase 6 is a layer over the Phase 2 sole-writer runtime, Phase 4 lifecycle and
human-gate records, and Phase 5 disposable graph projections. It should add
strict evidence records and a read-only dossier assembler; it must not create a
second authority database or reinterpret a graph row, Markdown report, or
caller-supplied boolean as scientific truth.

The boundary is deliberately narrow:

- qualify evidence from experiments executed outside ARW through a common,
  digest-bound envelope;
- emit immutable integrity receipts with explicit freshness and invalidation;
- preserve the five access states and prevent claims from being upgraded by
  possession or a self-attested verdict;
- produce one bounded canonical dossier manifest and deterministic JSON/
  Markdown views;
- keep technical qualification distinct from the unresolved SUP-04/P04-09
  legal/intended-use release verdict.

Controlled execution, a general experiment scheduler, OCR and office-format
expansion, desktop UX, cloud synchronization, telemetry, and the Science
Workbench v2 paper AST/export workflow remain deferred. A provenance envelope
must never be rendered as proof that ARW reproduced an experiment.

## Requirements and evidence map

| Requirement | Required behavior | Implementation seam | Minimum retained evidence |
| --- | --- | --- | --- |
| SCI-01 | Every integrity check has a versioned immutable receipt naming inputs, method, tool version, verdict, reasons, and freshness. | New strict receipt model/module built on `canonical_json_bytes`, `sha256_hex`, and `manifests._write_once` semantics; verifier checks subject/input digests and `valid_until`. | Unit canonical/hash fixtures; input mutation and expiry integration tests; receipt files and a cold-replay verdict. |
| SCI-04 | Externally executed datasets, model/config identity, metrics, and artifacts can be ingested under one strict schema. | New `ExperimentProvenance` envelope with nested source/config/environment/runner/metric/artifact records and immutable manifest links; parent-only intake command. | Schema/Pydantic strictness tests, malformed/mismatched digest matrix, valid fixture replay, provenance manifest inventory. |
| SCI-05 | Controlled execution remains disabled until sandbox, approval, environment capture, and provenance-equivalence probe all pass. | Pure policy evaluator returns `BLOCKED` and reason codes unless all four independently bound receipts are present and fresh. No execution path is added in this phase. | Four-gate truth table including forged booleans, stale gates, and missing evidence; no subprocess execution assertion; dossier records blocked decision. |
| SCI-06 | Exact access states are publicly verified, locally supplied, restricted, unavailable, and human-review-required. | Literal `EvidenceAccessState`, access decision record, and claim-level state joins; no implicit conversion from local/restricted to public. | State transition/claim matrix tests, ambiguous or inaccessible fixture, human-review/blocker event and dossier section. |
| SCI-07 | Citation verification, reproduction, independent review, and audit completion cannot be claimed without fresh lifecycle evidence. | Pure claim capability evaluator consumes canonical receipts, review matrix, experiment provenance, access decisions, and freshness clock; emits typed blockers. | Missing/stale/unsupported evidence cases; valid full fixture; no upgrade after projection deletion or Markdown edit. |
| VER-07 | Release candidate emits inspectable dossier with run history, manifests/Passports, receipts, reviews/dissent, waivers, graph receipts, test logs, benchmark versions, and build provenance. | Canonical dossier manifest assembled from replayed ledger and immutable stores; deterministic renderer and bounded secret-safe export; verifier script and staged fixture. | JSON/Markdown byte-identical rerender, cold replay after projection deletion, inventory/SBOM/build identity binding, technical PASS/release BLOCKED verdict. |

## Existing architecture to compose

### Canonical authority and immutable storage

`src/arw/runtime.py` is the sole service that turns validated requests into
hash-chained ledger events. Replay (`replay_run`/`reduce_events`) and accepted
manifest validation must be performed before collecting dossier inputs. The
dossier assembler should never append an event merely because a receipt is
missing; a parent command may append a typed evidence-accepted or gate event,
but that command remains outside the renderer.

`src/arw/models.py` already defines strict `ArtifactManifest`,
`MaterialPassport`, event envelopes, `fresh_until`, and SHA-256 bindings.
`src/arw/manifests.py` provides safe-root checks, content-addressed artifact and
Passport stores, canonical bytes, and write-once publication. New receipt,
provenance, access-decision, and dossier files should use these primitives (or
an explicitly shared helper) rather than ordinary replace-in-place writes.

`src/arw/evidence.py` is currently for bounded command/recovery streams and has
an allowlisted environment set. It must not become a generic environment dump:
experiment environment capture should be a strict, redacted, digest-bound
record with an explicit field allowlist. Raw logs should be retained as bounded
artifacts and referenced by digest, never copied wholesale into a dossier.

### Review and human-gate composition

`src/arw/review.py` and the strict models in
`src/arw/orchestration_models.py` already derive `ReviewReport.report_sha256`
from canonical report bytes and require a complete, identity-separated review
matrix. `ReviewSynthesis` binds every exact report hash, and
`HumanDecisionRecord` is append-only with explicit authority, scope,
predecessor, and blocker action. Phase 6 must aggregate these records and
preserve minority/DA dissent; it should not call a new synthesis path or infer
independence from a status flag.

`GateDecision.fresh_until`, human decisions, and the Phase 4 gate history are
inputs to claim qualification. A waiver can release only its exact scoped
blocker and cannot turn a stale or absent receipt into fresh evidence. The
dossier should show the prior decision hash, authority hash, supersession
chain, and current effective blocker without rewriting historical bytes.

### Graph and projection composition

Phase 5's `graph_projection.py`, `graph_store.py`, and `graph_models.py` make
projection inputs, generation manifests, watermarks, query bounds, and receipts
explicit. `GraphStore` is disposable: selected-generation loss, corruption, or
staleness must leave canonical runtime state and claim verdicts unchanged. The
dossier may include projection receipt and watermark metadata, but must either
rebuild from canonical records or record a typed projection-unavailable
blocker. Never include a body-bearing graph query result without checking its
generation digest/watermark.

The existing normalization oracle (`research-graph-normalization-v1`) is a
useful reference for deterministic ordering. Dossier hashes must be computed
from canonical manifest bytes, not SQLite page bytes, temporary paths, process
IDs, or Markdown formatting.

### Schema registry and package boundary

`src/arw/schema_registry.py` derives Phase 4/5 documents from their model
registries, then validates checked-in Draft 2020-12 documents independently.
Phase 6 schemas should be added to a dedicated registry tuple and generated
from the same strict model source where practical. Update the count through the
registry rather than adding another literal count. Check that schema IDs,
`additionalProperties`, required fields, and generated documents are all
identical. `scripts/stage-plugin` is the positive release allowlist; neither
`.gitignore` nor the presence of a build directory determines what ships.
Do not stage run evidence, private text, graph databases, credentials, or
temporary directories.

## Recommended contract design

The exact Python class names are discretionary, but the following decomposition
keeps each record independently hashable and avoids a giant permissive model.

### Integrity receipt (`arw.integrity-receipt.v1`)

Required fields should include:

```text
schema_version, receipt_id, subject_kind, subject_id,
subject_sha256, input_sha256[], method_id, method_version,
tool_identity {name, version, build_sha256},
observed_at, freshness_policy {valid_until, clock_skew_seconds},
verdict {PASS, FAIL, BLOCKED}, reason_codes[], reason_text,
source_manifest_sha256[], created_by, receipt_sha256
```

`receipt_sha256` is derived from canonical bytes excluding the digest field (as
`review_report_body_sha256` does). Inputs must be sorted and unique; a missing
input, method, tool, or source digest is invalid. A receipt validator should
take the current subject/input inventory and injected `now`, then return
reason codes such as `subject_digest_mismatch`, `input_digest_mismatch`,
`freshness_expired`, `future_timestamp`, or `missing_source`. The stored receipt
does not mutate when it becomes stale; the validator emits a new observation or
gate result that points to replacement evidence.

Digest comparison is mandatory even when `valid_until` has not elapsed.
`valid_until` is explicit and deterministic; default durations belong in a
versioned policy record rather than a hidden constant. Clock skew must be
bounded and tested. The caller cannot pass `fresh=True` or replace the receipt
hash.

### External experiment provenance (`arw.experiment-provenance.v1`)

Use one envelope with strict nested records:

```text
provenance_id, run_id, experiment_id, schema_version,
source_datasets[{uri_or_path, content_sha256, access_state}],
model_identity[{name, revision, source_sha256}],
configuration[{name, canonical_sha256, content_type}],
metrics[{name, value, unit, metric_sha256}],
artifacts[{artifact_id, media_type, content_sha256, manifest_sha256}],
environment[{key, redacted_value_or_digest, tool_version}],
runner {identity, command_digest, host_digest, started_at, finished_at},
execution_claim {mode: external_only, status: imported|blocked},
qualification_receipts[{kind, receipt_sha256}], source_manifest_sha256[],
created_at, provenance_sha256
```

The schema should model numeric values without coercing strings, reject unknown
fields, require normalized relative artifact references, and enforce unique
metric/artifact IDs. Secrets, API keys, tokens, and raw private text are
forbidden. Environment capture is an explicit allowlist of identity/version
fields; values that could reveal a secret are replaced by a digest and marked
redacted. Dataset and configuration digests must be recomputed from canonical
bytes or an immutable source manifest, not accepted as a producer boolean.

The only accepted execution mode in Phase 6 is `external_only`/`imported`.
`execution_claim=controlled_reproduction` is rejected or returns BLOCKED unless
all four qualification receipts are fresh and bound to the exact subject:

1. approved sandbox identity and policy digest;
2. explicit accountable approval and scope;
3. environment-capture receipt covering the runner/toolchain;
4. provenance-equivalence probe comparing source/config/artifact identities.

Even when the four receipts are later available, a separate implementation
must be introduced and qualified before any subprocess is launched. This phase
should keep the execution adapter absent or hard-disabled and test that no
caller-supplied `sandbox_passed`/`reproduced` booleans affect the result.

### Evidence access and claim capability

Define one literal access state exactly matching the context:

```text
publicly_verified | locally_supplied | restricted |
unavailable | human_review_required
```

An access decision should bind `evidence_sha256[]`, `subject_sha256`, source
and license/permission metadata, deciding authority, rationale, scope, and
created/superseded timestamps. It must be append-only and cannot rewrite a
receipt. `locally_supplied` means bytes are present and digestable; it is not a
public citation check. `restricted` and `unavailable` remain visible even if a
local cache happens to contain metadata.

Represent claim capabilities as a pure function or strict record with required
evidence kinds:

| Claim capability | Minimum evidence | Disqualifiers |
| --- | --- | --- |
| `citation_verified` | Fresh source-integrity receipt plus `publicly_verified` access decision and citation lifecycle record. | Local-only/restricted source, stale receipt, missing source identity, unresolved license. |
| `experiment_reproduced` | Fresh external provenance, exact dataset/model/config/artifact digests, all required qualification receipts, and an explicit reproduction decision. | Imported metrics only, missing environment/probe, digest mismatch, controlled execution blocked. |
| `independent_review_complete` | Fresh Phase 4 panel manifest, every required exact report hash, separate synthesizer identity, matrix/dissent and gate decision. | Missing role, shared identity, omitted dissent, stale panel, blocked gate. |
| `audit_complete` | Fresh receipts for all required claims plus replayable run/passports, graph/test/build receipts, and no unresolved technical blockers. | Projection unavailable, stale evidence, missing dossier section, unresolved mandatory gate. |

The function returns `PASS`, `BLOCKED`, or `FAIL` plus stable reason codes and
the exact required replacement evidence. It must never return a stronger state
because a caller requested one or because a Markdown dossier says “verified.”

### Canonical dossier manifest and renderers

Use a strict `arw.audit-dossier.v1` manifest as the only source of truth for
output. It should contain:

```text
schema_version, dossier_id, run_id, generated_at, ledger_head_sha256,
run_history[], run_manifest_sha256, passport_sha256[], artifact_manifest_sha256[],
integrity_receipt_sha256[], experiment_provenance_sha256[],
access_decisions[], claim_capabilities[], review_matrix_sha256,
review_report_sha256[], dissent_refs[], human_decision_sha256[],
graph_projection_receipt_sha256[], graph_watermark,
test_logs[{name, command_digest, result, stdout/stderr_digest}],
benchmark_versions[], build/source/integration-lock refs,
technical_qualification, release_qualification, blocker[]
```

All references are normalized relative paths or SHA-256s. `generated_at` is
part of the manifest and should be injected/frozen for deterministic tests;
avoid embedding current wall time in renderer-only output. Sort every list by
stable ID/digest. The canonical manifest hash excludes its own digest and is
written once under a content-addressed dossier store. JSON output is the
canonical bytes. Markdown is a deterministic presentation that links each
section to exact hashes and explicitly labels projection/review/rendering
inputs as non-authoritative.

The assembler should collect only validated canonical records and bounded
metadata. It should redact or omit secrets, private full text, credentials,
uncontrolled paths, and unresolved-license material; omission becomes a
blocker/reference, not silent success. Technical qualification can be PASS
while release qualification remains BLOCKED with SUP-04/P04-09.

## Lifecycle and authority flow

1. Parent replays the run and validates event/manifests/Passport lineage.
2. Parent discovers receipt/provenance/access/review records by explicit
   content-addressed references; missing files are typed blockers.
3. Parent validates canonical bytes, digest bindings, schema versions, source
   inventories, and freshness against an injected clock.
4. Parent evaluates SCI claim capabilities and the four controlled-execution
   prerequisites without launching an experiment.
5. Parent validates graph projection receipt/watermark; if selected generation
   is unavailable, dossier generation continues with a bounded blocker or
   returns BLOCKED according to `VER-07` policy, never using stale body rows.
6. Parent creates one canonical dossier manifest from sorted references, writes
   it once, then renders JSON/Markdown from those bytes.
7. A verifier recomputes every digest, deletes/rebuilds projections, rerenders
   cold, and checks that technical and release verdicts remain distinct.

No worker, hook, SQLite projection, or Markdown renderer may append canonical
   state. Human corrections/waivers are additional accepted records and are
   included by exact predecessor/supersession hashes.

## Validation architecture

Validation should follow the existing quick → phase → staged → full pattern and
retain raw command output under a repo-local, owned evidence root. Do not run a
large unconstrained all-install job after the prior memory incident; use
serial commands, `UV_OFFLINE=1`, `PYTHONNOUSERSITE=1`, and controlled `TMPDIR`.

### Contract and unit checks

- Generate/validate all Phase 6 Draft 2020-12 schemas through
  `src/arw/schema_registry.py`; assert registry-derived count and no checked-in
  drift.
- Round-trip strict models with unknown-field, type-coercion, duplicate-ID,
  non-canonical-byte, and caller-supplied-digest mutations.
- Assert receipt/provenance/access/dossier digests equal SHA-256 of canonical
  bytes with the digest field removed.
- Test deterministic ordering, redaction, path normalization, max list/byte
  bounds, and rejection of non-finite numbers/secrets.

Suggested files:

```text
tests/schema/test_phase6_contracts.py
tests/schema/test_schema_drift.py                 # extend registry assertions
tests/unit/test_integrity_receipts.py
tests/unit/test_experiment_provenance.py
tests/unit/test_evidence_access.py
tests/unit/test_audit_dossier.py
```

### Integrity and provenance integration

Use `tmp_path`, injected clocks, and a fixture with a dataset, config, model,
metric, and artifact manifest. Verify:

- unchanged inputs inside `valid_until` pass;
- subject/input byte mutation returns `input_digest_mismatch` even when the
  prior receipt is otherwise fresh;
- expiry returns `freshness_expired` with the exact replacement requirement;
- malformed or unknown fields fail before publication;
- artifact/config/source digests are recomputed and cannot be self-attested;
- each of the four controlled-execution prerequisites is required, stale
  prerequisites fail closed, and no subprocess or fake “reproduced” status is
  produced;
- external-only imported metrics remain `locally_supplied`/appropriate state,
  never `experiment_reproduced` by implication.

Suggested files:

```text
tests/integration/test_integrity_receipts.py
tests/integration/test_experiment_provenance.py
tests/integration/test_controlled_execution_blocked.py
```

### Access-state and claim-gate integration

Create one fixture per exact access state and a matrix of claim capabilities.
Check that local possession cannot become public verification, restricted or
ambiguous-license material enters `human_review_required`/BLOCKED, and stale or
missing lifecycle records block citation, reproduction, independent-review,
and audit claims. Append a human access decision/waiver and verify history,
scope, predecessor, and blocker release are exact and append-only.

Suggested files:

```text
tests/integration/test_evidence_access_states.py
tests/integration/test_scientific_claim_gates.py
tests/integration/test_audit_dossier_blockers.py
```

### Cold replay and projection-loss checks

Build a representative run from canonical events, artifact manifests,
Passports, a Phase 4 panel/review matrix, human decision, Phase 5 graph input,
integrity receipt, external provenance, and access decisions. Generate the
dossier twice with a frozen clock and compare canonical JSON and Markdown bytes.
Delete the selected SQLite generation and any non-authoritative projection
cache; replay from run events/manifests and regenerate. The regenerated dossier
must be equivalent or explicitly contain the same typed projection blocker; it
must not change accepted state or gate verdicts.

Suggested files:

```text
tests/integration/test_audit_dossier_replay.py
tests/property/test_audit_dossier_replay.py
tests/fixtures/phase6/representative-run/
```

Property cases should permute input record order, duplicate command/event IDs,
stale receipt references, superseded decisions, deleted projections, and
bounded output limits. A replay failure must preserve the last canonical
prefix and raw evidence as in Phase 2 recovery; do not “repair” by rewriting
the ledger.

### Staged and full qualification

Add a serial `scripts/verify-phase-6` modeled on `scripts/verify-phase-5`:

1. own/clean only a repo-local `build/evidence/phase-06` root;
2. record Python, dependency/schema, source, and current HEAD identity;
3. run Phase 6 schema/unit/integration tests with bounded output;
4. build a representative dossier from fixture canonical records;
5. verify byte-identical JSON/Markdown rerender and cold replay after graph
   loss;
6. inspect the dossier for required sections, no secret/private payloads,
   bounded paths, and explicit SUP-04/P04-09 release blockers;
7. bind graph projection receipts, review/report hashes, test logs, benchmark
   versions, file-base/source/build/integration-lock identities;
8. write requirements, technical/release verdict, and summary JSON with all
   command and artifact digests.

The staged tree must contain only runtime code, schemas, docs, hooks, and
launchers required by the positive allowlist. It must not contain generated
   dossier evidence, SQLite databases, user run roots, secrets, private source
   text, or temporary build trees. Run `./scripts/stage-plugin --validate-only`
   and the existing inventory/SBOM/build-identity checks after adding Phase 6
   artifacts.

Recommended command progression (serial to avoid memory pressure):

```text
UV_OFFLINE=1 .venv/bin/python -m pytest -q \
  tests/schema/test_phase6_contracts.py \
  tests/unit/test_integrity_receipts.py \
  tests/unit/test_experiment_provenance.py

UV_OFFLINE=1 .venv/bin/python -m pytest -q \
  tests/integration/test_integrity_receipts.py \
  tests/integration/test_experiment_provenance.py \
  tests/integration/test_evidence_access_states.py \
  tests/integration/test_scientific_claim_gates.py \
  tests/integration/test_audit_dossier_replay.py

UV_OFFLINE=1 ./scripts/verify-phase-6 --clean \
  --evidence-root build/evidence/phase-06

UV_OFFLINE=1 .venv/bin/python -m pytest -q
```

If host/staged environment capacity is insufficient, retain the exact typed
BLOCKED evidence and continue non-host validation. A missing external legal
approval is a release blocker, not a reason to mark a scientific integrity test
as xfail.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Receipt hash is accepted from a producer and never recomputed. | Derive hashes from canonical bytes; reject mismatched supplied digests and test byte mutation. |
| Freshness is represented by a mutable boolean or wall-clock race. | Inject clock, record `valid_until`/skew policy, compare subject/input digests first, and keep stale receipts immutable. |
| External metrics are presented as ARW reproduction. | Make `external_only` the only Phase 6 execution mode; require four separate qualification receipts for any future controlled mode and emit BLOCKED otherwise. |
| Environment capture leaks API keys or private paths. | Explicit allowlist, digest/redaction fields, bounded logs, secret-pattern tests, and no raw environment export. |
| Restricted/local evidence is silently upgraded to public. | Exact five-state literal, append-only access decisions, claim capability matrix, and negative tests for every upgrade path. |
| Dossier becomes a second source of truth. | Canonical manifest only references replayed events/manifests; JSON/Markdown are renderings; no renderer writes ledger or graph state. |
| Projection loss changes audit verdict. | Graph is disposable; cold replay either rebuilds or records typed projection blocker while canonical state remains unchanged. |
| Review dissent is flattened. | Include exact report hashes, synthesis hash, finding matrix, minority/DA dissent and unresolved critical blockers. |
| Schema static count drifts again. | Registry-derived Phase 6 names and independent generated-vs-checked-in test. |
| Large staged/full installation exhausts memory/tmpfs. | Serial verifier, repo-local scratch, offline mode, bounded captures, and no parallel full install. |
| Technical PASS is misread as permission to distribute. | Dossier has separate technical/release verdicts and retains SUP-04/P04-09 blockers and mixed-license identity. |

## File and test plan recommendations

Likely new implementation seams (exact names are for planning, not a mandate):

```text
src/arw/integrity.py                 # receipt model, digest/freshness evaluator
src/arw/experiment_provenance.py     # strict external envelope and gate policy
src/arw/evidence_access.py            # five states, access decisions, claim gates
src/arw/audit_dossier.py              # canonical manifest, replay assembler, renderers
schemas/v1/integrity-receipt.schema.json
schemas/v1/experiment-provenance.schema.json
schemas/v1/evidence-access-decision.schema.json
schemas/v1/audit-dossier.schema.json
scripts/verify-phase-6
docs/runtime/scientific-integrity.md
docs/runtime/audit-dossier.md
```

Likely tests are listed in the validation sections above. Add fixtures only
under `tests/fixtures/phase6/` and keep generated evidence under
`build/evidence/phase-06` (ignored and owned by the verifier). Extend
`src/arw/schema_registry.py` and the cross-language schema tests rather than
hard-coding a second schema count. Add stage requirements to
`tests/staged/test_supply_chain_inventory.py` only for executable Phase 6
artifacts; do not stage fixture evidence or private run data.

## Planning handoff

Split implementation into independently verifiable vertical slices:

1. strict receipt model, immutable storage, digest/freshness evaluator, and
   schemas;
2. external provenance envelope and controlled-execution BLOCKED policy;
3. five access states, claim capability gates, and append-only human decision
   composition;
4. canonical dossier assembler/renderers with replay and projection-loss
   behavior;
5. staged verifier, inventory/build identity binding, docs, and full regression.

Each slice should have unit tests before integration tests and should retain
evidence before the next slice. Phase 6 technical qualification may pass only
when every SCI/VER requirement has fresh, digest-bound evidence; release must
remain BLOCKED for unresolved legal/intended-use/permission evidence even when
all technical tests pass.

---

*Phase: 06-scientific-integrity-and-audit-dossier*  
*Research completed: 2026-07-15*
