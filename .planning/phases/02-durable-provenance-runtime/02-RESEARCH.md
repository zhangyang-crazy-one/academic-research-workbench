# Phase 2: Durable Provenance Runtime - Research

**Researched:** 2026-07-13
**Scope:** Local repository architecture and implementation planning
**Confidence:** HIGH for runtime invariants and test strategy; MEDIUM for the
exact schema migration surface until the first dual-version fixture is built

## Executive Summary

Phase 2 should turn the Phase 1 single-file journal into a small event-sourced
runtime, not add another mutable workflow store. The safest implementation is
a pure reducer over an immutable run manifest, registered workflow definition,
validated journal segments, and referenced immutable manifests. Every command
that can change canonical state must replay under the existing run lock, check
the caller's expected revision and event authority, stage immutable files, and
append exactly one fsynced event. Status and replay use the same reducer and do
not write projections or repair bytes.

Recovery needs a segmented journal. A damaged segment is never truncated or
rewritten. Explicit `arw recover` copies its exact bytes into a quarantine
bundle, records byte count, SHA-256, fault offset, last valid revision/head,
operator, and reason, then creates a new segment whose first event is
`recovery.completed`. Replay may ignore a prior segment's invalid tail only
when that recovery event validates and binds both the unchanged damaged segment
and quarantine copy. Damage before the final record, a manifest mismatch, or a
broken accepted hash chain remains blocking.

Material Passports are immutable checkpoint manifests, not mutable state
files. Each revision is stored by its canonical SHA-256 and accepted by a
`passport.accepted` event. `passport.json` is an atomic, rebuildable pointer.
Resume validates the requested Passport hash under the run lock and rejects a
superseded or already consumed boundary with the current Passport and revision.

## Existing Baseline

### Assets to preserve

- `src/arw/canonical.py` already defines exact canonical JSON bytes, strict JSON
  parsing, SHA-256 hashing, and event sealing.
- `src/arw/journal.py` already enforces one advisory writer lock, replay before
  append, sequence/revision/hash continuity, duplicate identities, fsync, and a
  post-fsync SIGKILL failpoint.
- `src/arw/models.py` already uses strict, frozen Pydantic models with forbidden
  unknown fields and constrained identifiers.
- `src/arw/evidence.py` already writes exact raw bytes and allowlisted command
  evidence through temp-file, fsync, and atomic replacement.
- `tests/integration/test_run_init.py` proves rejected requests do not mutate
  canonical bytes; `tests/integration/test_journal_replay.py` proves a
  post-fsync event survives SIGKILL exactly once.
- `schemas/v1/*.schema.json` and `src/arw/schema_registry.py` already provide an
  independent Draft 2020-12 validation path.

### Gaps in the Phase 1 kernel

- `CanonicalEvent` admits only `run.initialized` and
  `baseline.probe_recorded`; there is no workflow reducer or actor-role
  authority table.
- `ReplayState` contains only identity sets and the ledger tip. It cannot report
  stage, blockers, decisions, attempts, Passports, or legal transitions.
- A single `events.jsonl` cannot preserve an invalid tail while continuing the
  accepted chain without either rewriting bytes or adding segment semantics.
- Errors are strings. Rejections do not have a stable code, current revision,
  current Passport, or legal-next-transition contract.
- There are no artifact, Passport, recovery receipt, status, transition,
  decision, attempt, checkpoint, or resume schemas.
- `replay_run()` creates a missing run directory through `_validated_root()`;
  read-only commands should instead reject absent roots without filesystem
  side effects.
- The schema registry is named and hard-coded for Phase 1. Phase 2 needs a
  version-neutral registry while retaining the checked-in schema drift gate.

## Recommended Runtime Architecture

### Module boundaries

Keep `arw.journal` as the filesystem and hash-chain layer, then add narrow pure
or command-service modules:

| Module | Responsibility | Must not own |
|--------|----------------|--------------|
| `arw.workflows` | Immutable registered workflow definitions, identities, transition lookup, event-category authority | Run-specific mutable state |
| `arw.reducer` | Pure fold from manifest + validated events/manifests to `RuntimeState` | Filesystem I/O, locks, CLI rendering |
| `arw.journal` | Segment discovery/scanning, exact offsets, lock, append/fsync, legacy journal compatibility | Lifecycle legality or Passport policy |
| `arw.runtime` | Sole-writer command transaction: replay, authorize, validate, stage, append, derive result | User-facing argparse logic |
| `arw.manifests` | Immutable artifact/Passport installation and digest/path verification | Event acceptance decisions |
| `arw.recovery` | Tail classification, quarantine receipt, new recovery segment creation | Implicit repair from replay/status |
| `arw.status` | Versioned status model plus JSON/text renderers over one `RuntimeState` | Independent inference or mutation |
| `arw.cli` | Argument parsing, strict request loading, stable output/exit mapping | Business rules duplicated from runtime/reducer |

`models.py` may remain the shared wire-model module for this phase, but split it
if it becomes difficult to review. The important boundary is pure models and
reduction versus filesystem mutation, not a particular file count.

### Registered workflow identity

Use a code-owned registry of immutable definitions. A definition should contain
at least:

- `definition_id` and `definition_version`;
- ordered domain-neutral stages and terminal stages;
- transition IDs with exact from/to stages;
- required actor roles and coherent-checkpoint flags;
- decision-choice-to-transition mappings where applicable;
- canonical definition SHA-256.

The initial definition may be a compact academic-research lifecycle such as
`initialized -> intake -> work -> review -> completed`, with explicit revise,
abort, decision, checkpoint, and resume edges. It must not encode a language,
dataset, ontology, military domain, or paper topic. The ARS stage adapter can be
a separately registered definition later.

New run manifests must bind `workflow_definition_id` and the exact definition
SHA-256. Preserve replay of Phase 1 fixtures by treating the existing
`workflow_family`/`workflow_mode` pair as an immutable legacy definition, or by
introducing an explicit new manifest/event wire version and keeping the old
reader. Do not reinterpret old events through a changed definition.

### Event and authority model

Use one common event envelope and typed payload variants. The minimum Phase 2
event set is:

- `lifecycle.transitioned`;
- `human_decision.requested` and `human_decision.resolved`;
- `attempt.started` and `attempt.closed`;
- `artifact.accepted`;
- `passport.accepted`;
- `resume.accepted`;
- `recovery.completed`.

Keep `run.initialized` and `baseline.probe_recorded` replay-compatible. Event
payloads carry stable IDs and referenced manifest hashes, never mutable embedded
files. The writer continues to derive sequence, resulting revision, previous
hash, and event hash.

Represent actor role separately from actor identity. A small static authority
matrix should allow operator-authored human decisions/recovery/resume and
parent-control-plane lifecycle/artifact/attempt/Passport acceptance. Worker and
hook roles must be rejected at every canonical mutation command. They may
create immutable proposals outside the ledger, but only the parent command
service can accept them.

Every rejection should return a strict object with at least:

- `schema_version`, stable `code`, and concise `message`;
- `run_id` when trustworthy;
- `accepted_revision` and `ledger_head_sha256`;
- `current_passport_sha256` when present;
- `legal_next_transitions` from the accepted reducer state;
- `recovery_health` when the ledger is degraded.

The error path must not update the journal, manifests, pointer, quarantine, or
derived state. Duplicate commands may either return the original accepted
outcome idempotently or reject with the original revision/event identity, but
must never append twice. Preserve the Phase 1 duplicate-event and duplicate-
command distinction.

## Reducer and Status Contract

### Pure reducer state

`reduce_run(manifest, workflow, accepted_events, referenced_manifests, now)`
should return a frozen state containing:

- run ID, workflow definition identity, current stage, accepted revision,
  sequence count, and ledger-head hash;
- current Passport hash and accepted Passport history;
- blockers and recovery health;
- pending human decisions keyed by stable decision ID;
- active/closed attempts keyed by stable attempt ID;
- accepted and superseded artifact manifest hashes;
- consumed checkpoint/Passport boundaries;
- legal next transitions from the registered definition;
- reducer and schema versions.

Historical replay must not depend on wall time. Freshness is the only dynamic
projection: the reducer or status layer may compare an explicit `now` with
timestamps and freshness rules frozen in accepted manifests, but it must not
rewrite those manifests or events. Tests pass a fixed clock.

### Status behavior

`arw status --json` serializes a checked schema; `arw status` renders the same
model. The text renderer should consume the JSON-model object and contain no
transition or freshness logic.

Exit zero when a trustworthy accepted prefix produces complete status,
including `BLOCKED`, waiting-human, stale-evidence, and
tail-recovery-required. Exit nonzero only for an unreadable/absent run,
invalid/incompatible manifest/schema, or no trustworthy prefix. Automation
must inspect `recovery_health`, `blockers`, and legal transitions instead of
treating status exit zero as readiness.

Read-only entry points must not call a helper that creates directories. Split
root validation into `require_existing_run_root()` for replay/status and
`prepare_new_run_root()` for init.

## Segmented Journal and Recovery

### Storage layout

Recommended new-run layout:

```text
run-manifest.json
journal/segments/00000001.jsonl
manifests/artifacts/sha256/<manifest_sha256>.json
passports/sha256/<passport_sha256>.json
passport.json
quarantine/<recovery_id>/segment.raw
quarantine/<recovery_id>/receipt.json
.journal.lock
```

Support existing `events.jsonl` as a legacy, closed first segment during the
migration. Do not silently move or rewrite an accepted legacy file. New runs
should declare their journal layout in immutable identity data.

### Segment scan result

The scanner should return structured data rather than throw away location
information:

- ordered accepted events and segment identities;
- last valid byte offset, event sequence, revision, and head hash;
- full segment byte count and SHA-256;
- fault class, segment name, fault offset, and raw tail bytes;
- health: `healthy`, `recoverable_tail`, or `blocked`.

A fault is recoverable only when it is confined to bytes after the last valid
event in the final active segment and there is no valid later event/segment not
already authorized by a recovery boundary. A malformed or incomplete final
record can be treated as an unverifiable tail. An invalid manifest, changed
accepted event, chain gap, event deletion/reordering, corruption followed by a
later record, or mismatch in a prior recovery binding is `blocked`.

### Explicit recovery transaction

Under the run lock, `arw recover` should:

1. rescan and require the exact expected accepted revision/head and
   `recoverable_tail` classification;
2. copy the complete damaged segment bytes to a unique quarantine bundle,
   fsync the raw file and canonical receipt, and verify both digests;
3. create the next segment with a single canonical `recovery.completed` event
   through a temp-file, fsync, atomic rename, and directory fsync;
4. bind previous valid head/revision, original segment path/digest/byte count,
   quarantine path/digest, fault offset/class, operator identity, command ID,
   and reason code in the event payload;
5. leave the original damaged segment bytes unchanged.

On later replay, the new segment is admissible only if its first event is that
recovery event and all bindings validate against both the unchanged original
segment and quarantine receipt. This establishes why the prior tail is ignored
without deleting evidence.

Crash before the recovery event may leave an unreferenced quarantine bundle;
it is non-canonical and a retry can reuse it only after exact digest checks.
Crash after the new segment is published is replayable; a duplicate recovery
command must not create another segment.

## Immutable Artifacts and Material Passports

### Artifact acceptance

An artifact manifest should identify the artifact, content path, content
SHA-256, media type/kind, producer/attempt when relevant, input hashes, creation
time, and schema version. Acceptance verifies that the path stays below the run
root, rejects symlinks and mutable special files, re-hashes content, installs
the canonical manifest at its digest path, then appends `artifact.accepted`.
The event is the acceptance boundary; an installed but unreferenced manifest is
an orphan, not accepted state.

Stale attempt/result proposals carry their base revision and consumed input
hashes. The parent rejects them when their attempt is no longer active, the
base revision/freshness policy fails, or any input hash changed. Phase 2 can use
a conservative strict base-revision rule; later deterministic parallel merging
may weaken it only with an explicit conflict/freshness proof.

### Passport revision

A Passport revision should include:

- run and workflow definition identity;
- Passport hash input fields, parent Passport hash, and superseded Passport
  hash;
- based-on accepted revision and ledger head;
- checkpoint kind and stage;
- accepted artifact/evidence manifest hashes;
- pending decisions and active attempts needed to resume;
- frozen evidence timestamps and freshness rules;
- creation actor/time and schema version.

Create a Passport only at stage handoff, completed human decision, explicit
checkpoint, or recovery boundary. Write it immutably by content hash, append
`passport.accepted`, then atomically refresh `passport.json`. If the process
dies after event fsync but before pointer replacement, replay still identifies
the accepted Passport and can rebuild the pointer through a separate explicit
derived-state command; status itself remains read-only.

`arw resume` receives the exact Passport hash and expected revision. It rejects
a superseded Passport, hash mismatch, double consumption, stale revision, or
expired evidence that blocks the chosen transition. The rejection names the
current Passport/revision. No command creates an implicit branch.

## Schema and Compatibility Strategy

Add checked-in Draft 2020-12 schemas for artifact manifest, Passport, Passport
pointer, status, rejection, recovery receipt, and command requests/results.
Expand the event schema with typed conditional payload validation; a generic
`payload: object` without a matching discriminator is insufficient.

Rename the registry's `PHASE1_SCHEMA_NAMES` and public validation functions to
version-neutral names while preserving compatibility aliases if staged Phase 1
tests import them. Validate all `$id`, required fields, unknown-field policy,
and schema-instance fixtures independently from Pydantic.

Prefer a dual-reader migration:

- existing Phase 1 manifest/events and `events.jsonl` remain exactly replayable;
- new initialized runs bind the workflow definition and segmented layout;
- no migration rewrites an accepted run in place;
- an explicit future migration event is required before a run can change its
  workflow definition.

If implementation cost forces a single wire version, update all golden bytes
and state clearly that no external run was released under the old version. Do
not leave an ambiguous mixed interpretation.

## CLI Surface and Exit Codes

Recommended Phase 2 commands:

- `arw transition --run-root ... --request ...`
- `arw checkpoint --run-root ... --request ...`
- `arw resume --run-root ... --request ...`
- `arw recover --run-root ... --request ...`
- `arw status [--json] --run-root ... [--at ...]`
- `arw replay --run-root ...` for strict machine replay diagnostics

Use stable sysexits-style classes: zero for accepted commands and trustworthy
status, 64 for CLI usage, 65 for invalid canonical/request data, 73/74 for
creation/I/O failures if useful, and a distinct temporary-contention code such
as 75. Exact numeric choices are less important than checked JSON rejection
codes and tests.

## Validation Architecture

### Test layers

1. **Pure unit tests** for workflow lookup, actor authority, legal transition
   lookup, reducer event application, decision/attempt state, freshness with a
   fixed clock, status rendering parity, and tail classification.
2. **Schema tests** for every Pydantic/wire fixture, unknown fields, wrong
   payload discriminators, invalid IDs/hashes/timestamps, and checked-schema
   regeneration drift.
3. **Integration tests** through `python -m arw.cli` for transition rejection,
   duplicate commands, stale revisions, unauthorized actors, checkpoint,
   Passport pointer rebuild semantics, resume, and read-only status.
4. **Recovery tests** using child processes and deterministic failpoints before
   append, after partial append, after event fsync, after quarantine fsync, and
   after recovery-segment publication. Preserve raw bytes, hashes, offsets,
   commands, streams, exits, and oracle results.
5. **Adversarial corruption fixtures** for incomplete final JSON, malformed
   newline-terminated tail, changed final accepted event, middle-record damage,
   deleted/reordered events, changed manifest, changed artifact, changed
   quarantine bytes, and forged recovery binding.
6. **Full regression** for Phase 1 exact replay, staged plugin, confinement,
   source/license gates, and schema drift.

### Requirement-to-proof mapping

| Requirement | Primary automated proof |
|-------------|-------------------------|
| RUN-03 | Parameterized transaction tests assert invalid, duplicate, stale, out-of-order, unauthorized requests return structured rejection and byte-for-byte unchanged canonical trees |
| RUN-04 | Delete all derived pointers/projections, replay from manifest + segments + immutable manifests in a fresh process, compare canonical status bytes |
| RUN-05 | Digest-addressed artifact/Passport fixtures, supersession history, pointer deletion/rebuild, and tamper rejection |
| RUN-06 | SIGKILL at commit boundaries, exact Passport resume, double/stale resume rejection, active-attempt reconstruction, and no duplicate accepted event |
| RUN-07 | JSON Schema validation plus JSON/text parity from the same reducer after normal, waiting-human, blocked, active-attempt, stale-evidence, and recovered states |
| RUN-08 | Explicit tail quarantine/recovery fixture proves raw segment preservation, fault offset, digest bindings, last valid revision, recovery-first next segment, and middle-chain blocking |

### Commands and feedback latency

- Per-task quick command: targeted `pytest -q` file(s) named by the plan.
- Per-wave runtime command: `uv run --frozen pytest -q tests/unit tests/schema tests/integration/test_runtime_* tests/integration/test_recovery_*`.
- Final command: `UV_OFFLINE=1 uv run --frozen pytest -q` plus the repository's
  verification script extended for Phase 2.
- Run `ruff check`/`ruff format --check` only if ruff is added to the committed
  development lock; do not rely on an unpinned global executable.
- Target quick feedback below 30 seconds and full local feedback below 180
  seconds. Crash/evidence suites may be marked and run once per wave if they
  exceed that budget, but never omit them from final verification.

### Required evidence assertions

Tests must compare bytes and hashes, not only return codes. At minimum retain:

- pre-command and post-command canonical tree inventories;
- exact damaged segment and quarantine bytes/digests;
- fault segment, byte offset, last valid event/revision/head;
- recovery event and receipt cross-bindings;
- accepted Passport/artifact hashes and supersession chain;
- fresh-process replay/status JSON before and after pointer deletion;
- rejection JSON and unchanged-ledger verdicts;
- failpoint command, allowlisted environment, stdout/stderr, signal/exit code.

## Implementation Order

1. Freeze schemas, workflow registry, reducer state, rejection/status contracts,
   and tests for legal/illegal transitions.
2. Refactor journal replay into a structured segment scanner while preserving
   Phase 1 replay; add the sole-writer command service.
3. Add immutable artifact and Passport stores, coherent checkpoint, pointer,
   and strict resume.
4. Add explicit quarantine recovery and crash fixtures.
5. Complete status renderers, schema/regression gates, and evidence verifier.

This order keeps each wave vertically testable. Recovery should build on the
same scanner used by ordinary replay, and status should build on the same
reducer used by mutation validation.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| A malformed final record is confused with accepted corruption | Recover only the final suffix after a fully validated event; block any earlier/later-chain inconsistency; bind original and quarantine digests in the recovery event |
| Recovery becomes a hidden rewrite | Never truncate/rename away the damaged segment; require explicit command and next-segment recovery event |
| `status` creates directories or refreshes pointers | Separate existing-root validation and prohibit all writes in replay/status tests with tree snapshots |
| Pointer or state becomes authority | Derive current Passport and legal transitions from replay; test after deleting pointer/projections |
| Old runs replay under a new workflow definition | Bind definition hash for new runs and freeze a legacy reader/definition identity |
| Artifact installed before event appears accepted | Reducer considers only manifests referenced by accepted events; orphan files remain non-canonical |
| Dynamic freshness makes replay nondeterministic | Keep historical reduction time-independent; inject `now` only into status/transition freshness evaluation |
| Schema and Pydantic validators drift together | Keep independent `jsonschema` validation and golden invalid fixtures |
| Large plan produces shallow implementation | Split by vertical capability and require byte-level acceptance criteria plus targeted tests in every task |

## Sources Consulted

- `.planning/phases/02-durable-provenance-runtime/02-CONTEXT.md`
- `.planning/REQUIREMENTS.md`
- `.planning/ROADMAP.md`
- `.planning/STATE.md`
- `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`
- `.planning/research/ARCHITECTURE.md`
- `.planning/research/FEATURES.md`
- `.planning/research/PITFALLS.md`
- `docs/architecture/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
- `vendor/sources/academic-research-skills/shared/handoff_schemas.md`
- `vendor/sources/academic-research-skills/academic-pipeline/references/pipeline_state_machine.md`
- `src/arw/models.py`, `src/arw/journal.py`, `src/arw/cli.py`,
  `src/arw/canonical.py`, `src/arw/evidence.py`, and
  `src/arw/schema_registry.py`
- `schemas/v1/event.schema.json` and `schemas/v1/run-manifest.schema.json`
- `tests/integration/test_run_init.py` and
  `tests/integration/test_journal_replay.py`

## RESEARCH COMPLETE
