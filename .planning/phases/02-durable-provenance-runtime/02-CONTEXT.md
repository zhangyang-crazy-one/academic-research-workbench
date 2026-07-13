# Phase 2: Durable Provenance Runtime - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 turns the Phase 1 `init` / `append` / `replay` walking skeleton into a
complete durable provenance runtime. It delivers strict legal transitions,
pure replay from canonical files, immutable artifact and Material Passport
revisions, explicit checkpoint/resume behavior, evidence-preserving recovery,
and operator/machine status output.

The sole-writer event ledger and immutable manifests remain authoritative.
Mutable state, latest-passport pointers, hooks, transcripts, SQLite, FTS, and
graphs are rebuildable observations or projections. This phase does not add
production file retrieval, subagent execution, scientific gate methodology,
graph projection, or release qualification.

</domain>

<decisions>
## Implementation Decisions

### Runtime lifecycle and transition authority
- **D-01:** Use a fixed, domain-neutral core lifecycle with controlled
  extensions selected from registered workflow definitions. A run manifest
  cannot invent arbitrary states, events, or transition rules.
- **D-02:** The parent Python control plane is the only canonical committer.
  It validates actor role and event-category authority before accepting a
  transition. Workers and hooks can only return immutable proposals.
- **D-03:** Every rejection is side-effect free and reports the accepted
  revision and legal next transitions that remain in force.

### Recovery and quarantine
- **D-04:** `replay` and `status` are read-only and fail closed. They report
  the last valid revision but never repair canonical bytes implicitly.
- **D-05:** Recovery requires an explicit, locked `arw recover` command. The
  damaged segment is preserved byte-for-byte with its digest, fault offset,
  and quarantine evidence; accepted bytes are never edited in place.
- **D-06:** Recovery continues in a new journal segment from the last valid
  event. Its first canonical event is `recovery.completed`, binding the prior
  valid head, quarantined bytes, fault location, operator identity, and reason.
- **D-07:** Only an incomplete or unverifiable tail after the last valid event
  is recoverable. Damage to an accepted event, run manifest, or middle of the
  accepted hash chain makes the run `BLOCKED` and requires explicit human
  forensic resolution.

### Immutable artifacts and Material Passport revisions
- **D-08:** Generate a new Passport only at a coherent checkpoint: legal
  stage handoff, completed human decision, explicit checkpoint, or recovery
  boundary. Ordinary accepted events retain their own immutable manifests and
  do not force a Passport revision.
- **D-09:** Store each Passport revision as an immutable content-addressed
  file accepted by a `passport.accepted` event. `passport.json` is only an
  atomically replaced latest pointer and must be rebuildable from replay.
- **D-10:** A Passport revision records its parent and superseded Passport
  hashes. Superseded revisions remain available for audit but cannot resume
  the current run. A stale resume request is rejected with the current
  Passport hash and accepted revision; implicit branching is forbidden.
- **D-11:** A Passport freezes evidence state, timestamps, and freshness rules
  as accepted. `status` computes current freshness without mutating old
  Passports. Expired evidence blocks affected transitions until new evidence
  and a new Passport are accepted.

### Status and human decisions
- **D-12:** Provide both strict versioned `arw status --json` and concise
  operator-oriented `arw status`. Both render one pure replay reducer result;
  the text renderer cannot infer separate state.
- **D-13:** The minimum JSON contract includes run ID, current stage,
  accepted revision, ledger-head hash, current Passport hash, recovery health,
  blockers, pending human decisions, active attempts, next legal transitions,
  reducer version, and schema version.
- **D-14:** Status is read-only. Pending decisions expose stable decision IDs,
  blocker codes, source evidence/events, starting revision, allowed choices,
  rationale requirements, and transitions each choice may unlock. Decisions
  are submitted through separate validated commands and become events.
- **D-15:** `status` exits zero whenever a trustworthy accepted prefix can
  produce a complete status, including `BLOCKED`, waiting-human, and
  tail-recovery-required states. It exits nonzero only when no trustworthy
  canonical prefix can be established, the manifest/schema is invalid or
  incompatible, or state cannot be read. Automation gates inspect fields,
  not the query command's exit code.

### the agent's Discretion
- Choose the exact registered-workflow-definition format and decide whether a
  definition remains fixed for the full run or can change only through an
  explicit migration event. Any choice must bind exact definition identity
  into canonical data and preserve byte-equivalent historical replay.
- Choose segment names, directory layout, checkpoint projection format,
  recovery reason taxonomy, and numeric CLI exit codes while preserving the
  decisions above and cross-platform atomicity.
- Choose the precise domain-neutral core stage and event vocabulary, provided
  it supports all RUN-03 through RUN-08 behaviors without embedding a paper
  topic, language, dataset, or Chinese-military assumption.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product requirements and prior decisions
- `.planning/PROJECT.md` - Core value, sole-authority invariant, v1 scope, and
  domain-neutral product boundary.
- `.planning/REQUIREMENTS.md` - RUN-03 through RUN-08 and milestone acceptance
  criteria.
- `.planning/ROADMAP.md` - Phase 2 goal, success criteria, dependencies, and
  MVP designation.
- `.planning/STATE.md` - Phase 1 decisions that constrain canonical writing,
  replay, evidence, and installed behavior.
- `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`
  - Walking-skeleton authority, recovery, and evidence decisions inherited by
  this phase.

### Runtime and Passport architecture
- `.planning/research/ARCHITECTURE.md` - Canonical directory model, state
  reducer, immutable Passport revisions, checkpoint/resume, and recovery
  architecture.
- `.planning/research/FEATURES.md` - TS-4/TS-5 lifecycle, state, artifact, and
  Passport requirements.
- `.planning/research/PITFALLS.md` - Mutable-authority, silent recovery,
  stale-worker, and false-provenance failure modes.
- `docs/architecture/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
  - Prior runtime/passport integration boundaries and hook behavior.
- `vendor/sources/academic-research-skills/shared/handoff_schemas.md` - ARS
  Material Passport Schema 9 semantics, versioning, freshness, and integrity
  fields to preserve at the adapter boundary.
- `vendor/sources/academic-research-skills/academic-pipeline/references/pipeline_state_machine.md`
  - Existing ARS stage and resume semantics that inform the registered
  workflow adapter without becoming canonical runtime authority.

### Existing executable contracts
- `src/arw/models.py` - Strict Phase 1 run, request, and event models.
- `src/arw/journal.py` - Sole-writer lock, deterministic append, fsync, and
  replay baseline to extend.
- `src/arw/cli.py` - Current `init`, `append`, and `replay` command boundary.
- `src/arw/canonical.py` - Canonical JSON bytes and event hashing.
- `schemas/v1/event.schema.json` - Checked-in cross-language event contract.
- `schemas/v1/run-manifest.schema.json` - Immutable run identity contract.
- `tests/integration/test_journal_replay.py` - Existing post-fsync SIGKILL and
  duplicate-retry evidence fixture.
- `tests/integration/test_run_init.py` - Existing strict initialization,
  append, lock, and replay behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/arw/canonical.py`: deterministic JSON serialization, SHA-256 sealing,
  and strict JSON parsing can remain the byte-identity foundation.
- `src/arw/journal.py`: exclusive writer lock, directory fsync, exact replay,
  duplicate identity sets, and failpoint support form the runtime kernel.
- `src/arw/models.py`: frozen strict Pydantic models and discriminated event
  payloads can grow into the lifecycle, artifact, Passport, and recovery
  contracts.
- `src/arw/evidence.py`: allowlisted command and byte evidence writers can
  retain recovery fixtures without becoming canonical writers.

### Established Patterns
- Requests never select sequence, resulting revision, previous hash, or event
  hash; the locked writer derives them after replay.
- Canonical files are exact canonical JSON bytes validated independently by
  Pydantic and checked-in Draft 2020-12 schemas.
- Mutation is accepted only after full replay under one advisory lock; stale,
  malformed, duplicate, and contended operations leave bytes unchanged.
- Test failpoints preserve raw before/after bytes, streams, status, hashes,
  replay results, and verdicts.

### Integration Points
- Extend `arw.models`, `arw.journal`, and `arw.cli` rather than adding a second
  runtime authority.
- Add schemas under `schemas/v1/` and package them through the existing schema
  registry and stage allowlist.
- Expand recovery fixtures under `tests/fixtures/recovery/` and integration
  tests before implementation.
- Phase 4 will consume the actor, proposal, attempt, decision, and transition
  contracts; Phase 5 projections must consume replay output only.

</code_context>

<specifics>
## Specific Ideas

- Preserve damaged journal bytes, exact fault offsets, and quarantine hashes
  so recovery claims can be independently checked.
- Make rejection responses operationally useful by returning the accepted
  revision and next legal transitions, not only an error string.
- Keep Passport files compact and reference immutable artifact/evidence
  manifests by identity and digest rather than embedding mutable content.
- Treat blocked research as a valid inspectable state, not a failed status
  query.

</specifics>

<deferred>
## Deferred Ideas

- Phase 4 should add an independent `experiment_designer` role and keep it
  distinct from experiment execution, statistical validation, and methodology
  review. Phase 2 only provides the generic role/proposal/acceptance provenance
  substrate needed later.

</deferred>

---

*Phase: 02-durable-provenance-runtime*
*Context gathered: 2026-07-13*
