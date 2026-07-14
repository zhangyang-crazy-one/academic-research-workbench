# Phase 4: Subagent Orchestration, Hooks, and Human Gates - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns the Phase 2 attempt and human-decision skeleton into executable,
auditable parent/worker orchestration. It delivers a versioned role catalog,
immutable assignments, bounded direct-child worker execution, schema-valid
result proposals, deterministic parent acceptance, retry/cancellation recovery,
genuine independent-review isolation, non-authoritative lifecycle hooks, and
append-only human gate decisions.

The parent Python control plane remains the sole canonical writer. Workers may
read declared capabilities and write only to assigned scratch/result locations;
they cannot accept their own output. Hooks may hydrate context, validate or
warn, and request one bounded continuation, but they cannot authorize an
operation or write canonical state. Gate outcomes and human decisions extend
the existing ledger, immutable artifact, Passport, status, and blocker model.

This phase does not execute experiments, define the scientific methods behind
all integrity checks, build the research graph, produce the final audit dossier,
or complete the Phase 7 host-compatibility matrix. Controlled experiment
execution remains disabled; graph projection belongs to Phase 5 and general
scientific evidence receipts belong to Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Role catalog and execution provenance
- **D-01:** Define a stable, versioned role catalog and let each registered
  workflow activate only the roles it needs. Experimental or benchmark research
  must activate a first-class `experiment_designer`; this does not authorize
  experiment execution.
- **D-02:** Prefer configured native Codex role profiles. A normal Codex
  subagent with an immutable assignment-injected role is a supported formal
  fallback. Inline work is allowed only for non-independent support tasks and
  must be recorded as `degraded_inline`; it can never satisfy an independence
  claim. If a required independent role cannot be dispatched, the run is
  `BLOCKED`.
- **D-03:** `experiment_designer` and `methodology_reviewer` are distinct
  first-class roles and cannot use the same worker identity in one run.
  `code_runner` and `study_manager` remain future controlled-execution adapters,
  not Phase 4 experiment executors.
- **D-04:** Enforce a versioned role-conflict matrix. Non-conflicting support
  roles may share a worker, but producer/reviewer,
  experiment-designer/methodology-reviewer, reviewer/synthesizer, and any pair
  of independent reviewers must use distinct worker identities.

### Immutable assignments and attempt lifecycle
- **D-05:** An assignment immutably binds role, run/stage/task identity, base
  revision, exact input hashes, capabilities, allowed read roots, writable
  scratch/result paths, output schema and size, policy snapshot, blind-review
  constraints, deadline, and completion contract. Retries retain
  `assignment_id` and receive a new `attempt_id`. Any change to assignment
  content creates a new assignment that explicitly supersedes the old one.
- **D-06:** The parent freezes a DAG, topological layer, and stable task ordinal
  before dispatch. Independent workers may execute concurrently, but proposals
  are validated and accepted in topological-layer/task-ordinal order. A later
  completed result may wait; arrival timing cannot change canonical history.
- **D-07:** Timeout, process failure, and repairable result-envelope/schema
  failure may receive one automatic retry, for at most two attempts per
  assignment. Permission denial, stale inputs, supersession, cancellation, and
  scientific disagreement are not automatically retried. Exhaustion creates a
  `BLOCKED` human decision.
- **D-08:** Cancellation is two-stage: append/record a cooperative cancellation
  request and deadline, then force termination after the grace period. Late
  proposals remain immutable historical evidence labeled `rejected_stale` and
  can never be accepted. On parent restart, orphaned active attempts become
  `interrupted` and may be requeued only within the existing retry budget; a
  cancelled required task needs a replacement decision or remains blocked.

### Independent review and dissent synthesis
- **D-09:** A formal independent-review panel requires four distinct workers:
  `methodology_reviewer`, `domain_reviewer`, `perspective_reviewer`, and
  `devils_advocate_reviewer`. A separate `editorial_synthesizer` may start only
  after the required reports are accepted. Workflow policy may add statistical,
  experiment, data, ontology, or other specialists. A quick/single review is
  advisory and cannot claim independent-review completion.
- **D-10:** First-round reviewers receive the same immutable subject and rubric
  snapshot through isolated assignments and cannot access peer identity,
  reports, attempts, or synthesis. After every first-round report is accepted,
  the parent may create a separate rebuttal/cross-review round. Original reports
  remain immutable; responses are new assignments and evidence.
- **D-11:** All four base roles are `required`; synthesis cannot start when one
  is missing. Retry exhaustion therefore blocks formal review. Additional
  specialists may be `optional` only when the frozen workflow policy says so,
  and every absence plus uncovered dimension must be included in synthesis and
  the final review limitations.
- **D-12:** Synthesis produces an item-level finding matrix that binds every
  finding to source reports, evidence, severity, and confidence and classifies
  it as `consensus`, `majority`, `split`, or `DA-critical`. Majority cannot erase
  dissent. The synthesizer either resolves a conflict with evidence and a
  rationale or preserves it as unresolved; unresolved `critical` or
  `DA-critical` findings keep the review gate `BLOCKED`.

### Hooks and human gates
- **D-13:** Installed hook definitions require explicit operator trust. Status
  exposes at least `trusted_enabled`, `disabled`, `untrusted`, `timeout`, and
  `failed`. Missing or failed hooks degrade hydration, warnings, and continuation
  convenience only; paired hook-enabled/disabled evidence must show identical
  runtime authority, MCP confinement, gate, and provenance enforcement.
- **D-14:** `SubagentStop` may identify a malformed/incomplete envelope and
  request at most one directed continuation for that attempt. `Stop` may request
  one parent continuation when an explicitly requested deliverable or mandatory
  gate remains open. The parent independently validates the result and decides
  attempt outcome. Hooks never accept proposals or append canonical events.
- **D-15:** Require a rationale-bearing human event for a waiver, correction of
  an accepted conclusion, scoped release of a `FAIL`/`BLOCKED` blocker,
  restricted-evidence access, worker capability or root escalation, replacement
  after retry exhaustion, unresolved critical dissent, and final `complete`.
  Ordinary intermediate PASS transitions may advance automatically when the
  registered workflow and fresh evidence allow them.
- **D-16:** Never rewrite an original PASS, FAIL, or BLOCKED verdict. A waiver is
  a separate immutable decision bound to exact gate, subject/evidence hashes,
  applicable transition, rationale, accountable actor, and scope; it releases
  only that blocker and does not turn FAIL into PASS. A correction creates a
  superseding version and invalidates dependent evidence. An approval authorizes
  only the next legal transition.

### the agent's Discretion
- Choose the concrete assignment/result directory layout, schema decomposition,
  event names, and stable ID encoding while preserving all immutable bindings
  and Phase 2 replay compatibility.
- Choose bounded concurrency limits, task timeout defaults, cancellation grace
  periods, and the detailed repairable/non-repairable failure taxonomy, with
  deterministic tests and no hidden unbounded retries.
- Map the remaining pinned ARS role assets into the versioned role catalog and
  choose non-conflicting support-role combinations. The minimum role identities,
  forbidden combinations, and formal-review panel above are fixed.
- Choose hook command implementation and idempotent observation format. Hook
  ordering cannot be required because matching hooks may run concurrently.
- Choose the detailed finding, waiver, correction, approval, and hook-status
  schemas provided they preserve the locked semantics and are independently
  validated from exact staged bytes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scope, requirements, and inherited authority
- `.planning/PROJECT.md` - Domain-general workbench scope, core value, headless
  boundary, and sole-authority architecture.
- `.planning/REQUIREMENTS.md` - PKG-05, AGT-01 through AGT-07, SCI-02, SCI-03,
  acceptance criteria, and explicit worker/hook exclusions.
- `.planning/ROADMAP.md` - Phase 4 goal, dependencies, requirements, and five
  observable success criteria.
- `.planning/STATE.md` - Current architecture decisions, release blocker, and
  trust concern carried into Phase 4.
- `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`
  - Installed plugin, honest execution-mode fallback, hook, packaging, and
  evidence boundaries.
- `.planning/phases/02-durable-provenance-runtime/02-CONTEXT.md` - Sole-writer
  authority, attempts, pending human decisions, Passports, replay, and status.
- `.planning/phases/03-secure-files-first-data-plane/03-CONTEXT.md` - One-root
  read-only worker retrieval, parent administration, freshness, and capability
  constraints.

### Orchestration, independence, and gate design
- `.planning/research/ARCHITECTURE.md` - Parent-writer/worker-proposal pattern,
  assignment/result minimum fields, direct-child orchestration, hook event
  limits, reviewer blinding, and evidence receipts.
- `.planning/research/FEATURES.md` - TS-8 through TS-11 and DF-5 requirements
  for real execution, visible hooks, human queues, status, and preserved dissent.
- `.planning/research/PITFALLS.md` - Fake orchestration, reviewer-independence
  theater, stale/late proposal, hook-boundary, and mutable-provenance failures.
- `docs/architecture/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
  - Original subagent/hook phase, assignment envelope, and independence exit
  gate that Phase 4 operationalizes.

### Existing executable runtime boundaries
- `src/arw/models.py` - Strict attempt, human-decision, artifact, Passport, and
  actor-role models to evolve compatibly.
- `src/arw/runtime.py` - Sole-writer attempt start/close, human decision,
  artifact acceptance, checkpoint, and rejection transactions.
- `src/arw/workflows.py` - Registered lifecycle, actor-category authority, and
  legal-transition definitions.
- `src/arw/reducer.py` - Pure projection of active attempts, pending decisions,
  blockers, and accepted history.
- `src/arw/manifests.py` - Content-addressed artifact and Passport validation
  that proposal acceptance must reuse.
- `src/arw/status.py` - Pure status projection where worker, hook, review, and
  gate state becomes operator-visible.
- `src/arw/cli.py` - Parent-only command surface and current attempt/decision
  integration points.
- `hooks/hooks.json` - Existing observational SessionStart baseline to replace
  with trusted, visible, bounded Phase 4 adapters.
- `skills/academic-research-workbench/SKILL.md` - Installed route and current
  assignment-injected subagent fallback contract.

### Pinned role assets
- `vendor/sources/academic-research-skills/agents/research_architect_agent.md`
  - Existing general research architecture role behavior.
- `vendor/sources/academic-research-skills/academic-paper-reviewer/agents/methodology_reviewer_agent.md`
  - Required methodology reviewer source role.
- `vendor/sources/academic-research-skills/academic-paper-reviewer/agents/domain_reviewer_agent.md`
  - Required domain reviewer source role.
- `vendor/sources/academic-research-skills/academic-paper-reviewer/agents/perspective_reviewer_agent.md`
  - Required perspective reviewer source role.
- `vendor/sources/academic-research-skills/academic-paper-reviewer/agents/devils_advocate_reviewer_agent.md`
  - Required adversarial reviewer source role.
- `vendor/sources/academic-research-skills/academic-paper-reviewer/agents/editorial_synthesizer_agent.md`
  - Separate synthesis role and finding-matrix behavior.
- `vendor/sources/experiment-agent/agents/study_manager_agent.md` - Existing
  study-design material to mine for `experiment_designer`, without enabling
  human-study execution in Phase 4.
- `vendor/sources/experiment-agent/agents/code_runner_agent.md` - Deferred
  execution adapter whose commands must remain disabled in this phase.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RuntimeCommandService`: already validates base revision and consumed hashes,
  starts/closes attempts, resolves human decisions, and accepts immutable
  artifacts under one lock.
- `AttemptStartedPayload`, `AttemptClosedPayload`, and reducer attempt state:
  provide a replay-safe skeleton for assignment/attempt lifecycle expansion.
- `HumanDecisionRequestedPayload` and `HumanDecisionResolvedPayload`: provide
  stable IDs, allowed choices, rationale requirements, source events, and
  transition-unlock semantics for scoped gates.
- Artifact manifests and Material Passports: already bind producer, attempt,
  base revision, consumed hashes, active attempts, and pending decisions.
- The Phase 3 files MCP: supplies exactly five bounded read-only capabilities
  that assignments can grant without filesystem paths or administration.
- Pinned ARS reviewer prompts and experiment-agent study protocol: provide role
  semantics that can be normalized into a versioned catalog rather than copied
  into ad hoc assignments.

### Established Patterns
- Strict frozen Pydantic models generate checked Draft 2020-12 schemas; malformed
  or extra fields fail before canonical mutation.
- The parent control plane derives sequence, hashes, and revision under lock;
  every rejection is side-effect free and reports accepted state.
- Artifacts are installed content-addressably before a referencing event and
  remain non-authoritative until parent acceptance.
- Status and replay are pure projections; hooks, transcripts, scratch data, and
  graph/index state never become authority.
- Installed/staged qualification preserves raw evidence and separates technical
  PASS from legal release BLOCKED.

### Integration Points
- Extend `src/arw/models.py`, generated schemas, and `src/arw/schema_registry.py`
  with role catalog, assignment, result proposal, review matrix, gate, waiver,
  correction, approval, hook observation, and lifecycle contracts.
- Extend `RuntimeCommandService`, reducer, registered workflows, status, and CLI
  with parent-only dispatch preparation, proposal validation/acceptance,
  deterministic scheduling, cancellation/retry, and human gate commands.
- Replace the single observational hook with staged command adapters that read
  immutable assignment/status data and emit bounded non-authoritative outputs.
- Add installed evidence fixtures proving real worker identities, blind inputs,
  distinct nonces, malformed/stale/late rejection, hook-disabled parity,
  preserved dissent, and final human approval blocking.

</code_context>

<specifics>
## Specific Ideas

- Formal independent review means four accepted, distinct, blind first-round
  reports plus a separately produced finding matrix; merely naming four roles
  in a plan is insufficient.
- Make execution provenance a required enum such as native profile,
  assignment-injected subagent, or degraded inline, with a separate explicit
  independence-eligibility field.
- Freeze one subject/rubric snapshot digest across all first-round reviewer
  assignments and deny every peer-result path/capability until the round closes.
- Preserve late, stale, cancelled, superseded, malformed, and dissenting outputs
  as evidence even when they cannot become accepted research state.
- An experiment-design expert is a general research role, not a military-domain
  role and not permission to run code or human studies.
- Treat `BLOCKED` as a valid inspectable state. Human waiver can release a
  precise blocker but cannot relabel failed scientific evidence as passing.

</specifics>

<deferred>
## Deferred Ideas

- Controlled `code_runner` and `study_manager` execution belongs to Phase 6 and
  remains disabled until sandbox, approval, environment capture, and provenance
  equivalence are proven.
- Research graph projection of assignments, reviews, findings, and gates belongs
  to Phase 5; Phase 4 emits canonical manifests/events for that projector.
- General citation, claim, temporal, statistical, experiment, figure, and format
  verification methods plus the complete audit dossier belong to Phase 6.
- Full installed Codex compatibility and representative crash/resume release
  qualification remain Phase 7 responsibilities.

</deferred>

---

*Phase: 04-subagent-orchestration-hooks-and-human-gates*
*Context gathered: 2026-07-14*
