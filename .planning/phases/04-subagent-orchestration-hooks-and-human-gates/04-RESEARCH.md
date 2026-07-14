# Phase 4: Subagent Orchestration, Hooks, and Human Gates - Research

**Researched:** 2026-07-14  
**Domain:** deterministic parent/worker orchestration, Codex host adapters, independent review, hooks, and accountable human gates  
**Confidence:** MEDIUM — the durable Python kernel and test seams are implemented and inspected; native Codex dispatch, cancellation, and hook behavior must still be qualified for each exact host tuple.

<user_constraints>
## User Constraints (from CONTEXT.md)

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] The locked decisions, discretion, and deferred ideas below are copied verbatim and constrain every recommendation in this research.

### Locked Decisions

#### Role catalog and execution provenance

- **D-01:** Define a stable, versioned role catalog and let each registered
  workflow activate only the roles it needs. Experimental or benchmark research
  must activate a first-class <code>experiment_designer</code>; this does not authorize
  experiment execution.
- **D-02:** Prefer configured native Codex role profiles. A normal Codex
  subagent with an immutable assignment-injected role is a supported formal
  fallback. Inline work is allowed only for non-independent support tasks and
  must be recorded as <code>degraded_inline</code>; it can never satisfy an independence
  claim. If a required independent role cannot be dispatched, the run is
  <code>BLOCKED</code>.
- **D-03:** <code>experiment_designer</code> and <code>methodology_reviewer</code> are distinct
  first-class roles and cannot use the same worker identity in one run.
  <code>code_runner</code> and <code>study_manager</code> remain future controlled-execution adapters,
  not Phase 4 experiment executors.
- **D-04:** Enforce a versioned role-conflict matrix. Non-conflicting support
  roles may share a worker, but producer/reviewer,
  experiment-designer/methodology-reviewer, reviewer/synthesizer, and any pair
  of independent reviewers must use distinct worker identities.

#### Immutable assignments and attempt lifecycle

- **D-05:** An assignment immutably binds role, run/stage/task identity, base
  revision, exact input hashes, capabilities, allowed read roots, writable
  scratch/result paths, output schema and size, policy snapshot, blind-review
  constraints, deadline, and completion contract. Retries retain
  <code>assignment_id</code> and receive a new <code>attempt_id</code>. Any change to assignment
  content creates a new assignment that explicitly supersedes the old one.
- **D-06:** The parent freezes a DAG, topological layer, and stable task ordinal
  before dispatch. Independent workers may execute concurrently, but proposals
  are validated and accepted in topological-layer/task-ordinal order. A later
  completed result may wait; arrival timing cannot change canonical history.
- **D-07:** Timeout, process failure, and repairable result-envelope/schema
  failure may receive one automatic retry, for at most two attempts per
  assignment. Permission denial, stale inputs, supersession, cancellation, and
  scientific disagreement are not automatically retried. Exhaustion creates a
  <code>BLOCKED</code> human decision.
- **D-08:** Cancellation is two-stage: append/record a cooperative cancellation
  request and deadline, then force termination after the grace period. Late
  proposals remain immutable historical evidence labeled <code>rejected_stale</code> and
  can never be accepted. On parent restart, orphaned active attempts become
  <code>interrupted</code> and may be requeued only within the existing retry budget; a
  cancelled required task needs a replacement decision or remains blocked.

#### Independent review and dissent synthesis

- **D-09:** A formal independent-review panel requires four distinct workers:
  <code>methodology_reviewer</code>, <code>domain_reviewer</code>, <code>perspective_reviewer</code>, and
  <code>devils_advocate_reviewer</code>. A separate <code>editorial_synthesizer</code> may start only
  after the required reports are accepted. Workflow policy may add statistical,
  experiment, data, ontology, or other specialists. A quick/single review is
  advisory and cannot claim independent-review completion.
- **D-10:** First-round reviewers receive the same immutable subject and rubric
  snapshot through isolated assignments and cannot access peer identity,
  reports, attempts, or synthesis. After every first-round report is accepted,
  the parent may create a separate rebuttal/cross-review round. Original reports
  remain immutable; responses are new assignments and evidence.
- **D-11:** All four base roles are <code>required</code>; synthesis cannot start when one
  is missing. Retry exhaustion therefore blocks formal review. Additional
  specialists may be <code>optional</code> only when the frozen workflow policy says so,
  and every absence plus uncovered dimension must be included in synthesis and
  the final review limitations.
- **D-12:** Synthesis produces an item-level finding matrix that binds every
  finding to source reports, evidence, severity, and confidence and classifies
  it as <code>consensus</code>, <code>majority</code>, <code>split</code>, or <code>DA-critical</code>. Majority cannot erase
  dissent. The synthesizer either resolves a conflict with evidence and a
  rationale or preserves it as unresolved; unresolved <code>critical</code> or
  <code>DA-critical</code> findings keep the review gate <code>BLOCKED</code>.

#### Hooks and human gates

- **D-13:** Installed hook definitions require explicit operator trust. Status
  exposes at least <code>trusted_enabled</code>, <code>disabled</code>, <code>untrusted</code>, <code>timeout</code>, and
  <code>failed</code>. Missing or failed hooks degrade hydration, warnings, and continuation
  convenience only; paired hook-enabled/disabled evidence must show identical
  runtime authority, MCP confinement, gate, and provenance enforcement.
- **D-14:** <code>SubagentStop</code> may identify a malformed/incomplete envelope and
  request at most one directed continuation for that attempt. <code>Stop</code> may request
  one parent continuation when an explicitly requested deliverable or mandatory
  gate remains open. The parent independently validates the result and decides
  attempt outcome. Hooks never accept proposals or append canonical events.
- **D-15:** Require a rationale-bearing human event for a waiver, correction of
  an accepted conclusion, scoped release of a <code>FAIL</code>/<code>BLOCKED</code> blocker,
  restricted-evidence access, worker capability or root escalation, replacement
  after retry exhaustion, unresolved critical dissent, and final <code>complete</code>.
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

### Deferred Ideas (OUT OF SCOPE)

- Controlled <code>code_runner</code> and <code>study_manager</code> execution belongs to Phase 6 and
  remains disabled until sandbox, approval, environment capture, and provenance
  equivalence are proven.
- Research graph projection of assignments, reviews, findings, and gates belongs
  to Phase 5; Phase 4 emits canonical manifests/events for that projector.
- General citation, claim, temporal, statistical, experiment, figure, and format
  verification methods plus the complete audit dossier belong to Phase 6.
- Full installed Codex compatibility and representative crash/resume release
  qualification remain Phase 7 responsibilities.
</user_constraints>

<phase_requirements>
## Phase Requirements

[CITED: .planning/REQUIREMENTS.md] The requirements below are Phase 4's mapped requirement set; the research-support column names the implementation boundary that enables each one.

| ID | Description | Research Support |
|---|---|---|
| PKG-05 | A run records whether each requested role used a native subagent, an assignment-injected role, or an explicitly degraded inline mode. | Versioned <code>ExecutionMode</code>, role catalog, immutable assignment, adapter observation receipt, and status projection. |
| AGT-01 | The parent orchestrator can dispatch a specialized worker from an immutable assignment containing scoped inputs, capabilities, attempt identity, and output schema. | Canonical assignment manifest, parent-only <code>prepare_assignment</code> transaction, <code>DispatchSpec</code>, and qualified adapter. |
| AGT-02 | A worker can only return a schema-valid immutable proposal and cannot directly mutate canonical run state. | Sealed proposal inbox, strict Pydantic plus independent Draft 2020-12 validation, manifest acceptance, and sole-writer rejection oracle. |
| AGT-03 | The parent accepts, rejects, retries, cancels, or supersedes worker proposals in deterministic order and records each lifecycle event. | Frozen DAG cursor, bounded state machine, reducer/event extensions, replay tests, and exact terminal-state rules. |
| AGT-04 | Independent-review workflows use distinct worker identities and isolated assignments, preserve individual reports and dissent, and record synthesis separately. | Conflict matrix, panel planner, blind capability construction, report manifests, finding matrix, and distinct synthesizer assignment. |
| AGT-05 | Bounded concurrency, timeout, cancellation, and retry policies prevent orphaned attempts from blocking run recovery. | Finite semaphore, deterministic <code>TaskGroup</code> collection, two-attempt cap, cancellation ledger events, and orphan recovery rule. |
| AGT-06 | Hooks can hydrate context, validate envelopes, surface policy warnings, and request continuation without becoming canonical writers or the sole security boundary. | Bounded hook contracts/observations, one-continuation counters, parent validation, and hook-parity suite. |
| AGT-07 | Disabling or bypassing hooks cannot bypass runtime state rules, MCP filesystem confinement, integrity gates, or provenance recording. | Paired trusted/disabled/untrusted/timeout/failed runs compared with an authority-normalized replay digest. |
| SCI-02 | Gate outcomes distinguish PASS, FAIL, and BLOCKED and prevent finalization when required fresh evidence is absent or unresolved. | Immutable gate verdict payload, workflow legality check, blocker projection, fresh-evidence binding, and finalization denial tests. |
| SCI-03 | A human can record an explicit waiver, correction, access decision, or approval with rationale and scope without rewriting prior evidence. | Scoped human-decision payloads, supersession/invalidation semantics, immutable original verdicts, and before/after ledger assertions. |
</phase_requirements>

## Project Constraints (from AGENTS.md)

[CITED: AGENTS.md] The Phase 4 plan must preserve every applicable project directive below.

- The deliverable remains a headless, testable Codex-native plugin and MCP contract; it must not become a design-only document, desktop application, or second application runtime.
- The append-only ledger and immutable manifests remain the system of record. SQLite/file/graph projections, transcripts, scratch paths, hooks, and host state are non-authoritative.
- The Python control plane owns strict schemas, canonical CLI commands, locks, ledger/state transitions, manifests, gates, hooks, and audit evidence. The data plane remains the bounded files MCP; Phase 4 must not turn it into a general filesystem bridge.
- Canonical records use strict frozen Pydantic models, discriminated envelopes, explicit schema versions, constrained IDs/paths/digests/timestamps, and no implicit coercion.
- Workers and hooks never write accepted state. The parent control plane alone derives event sequence, revisions, previous hashes, and event hashes under its writer lock.
- Preserve ARS semantics and the pinned role assets. Experimental design is allowed; experiment execution, hidden network work, and controlled-execution adapters remain disabled in this phase.
- Read-only worker retrieval stays limited to the five existing MCP tools and an explicit parent-supplied root capability. Crawl, sync, rebuild, and repair remain parent-controlled.
- Hooks are a defense-in-depth convenience layer only. They may be disabled, untrusted, concurrent, skipped, or failed; they cannot be an authorization, provenance, filesystem-confinement, or gate boundary.
- Outputs, logs, and staged evidence must be bounded, redacted, and free of private source text, credentials, absolute private paths, and transcripts unless retained in the restricted per-attempt evidence area.
- Stage/install tests must execute exact staged plugin bytes from isolated homes and must not import the source checkout or inherit <code>PYTHONPATH</code>.
- Test coverage must include strict/schema checks, pure transition/reducer tests, duplicate/stale/unauthorized rejection without partial mutation, replay/crash recovery, hook stdin/stdout and trust modes, worker handoff, blind review, stop/resume, and staged host qualification.
- Do not introduce LangGraph, CrewAI, a generic task queue, a second canonical database, transcript parsing, hook-only enforcement, or plugin-local custom-agent registration as an assumed host capability.
- Use the GSD workflow for repository changes. This artifact is documentation-only; no application or other planning file is changed. [CITED: AGENTS.md; user objective]

## Summary

[CITED: src/arw/runtime.py; src/arw/reducer.py; src/arw/manifests.py; src/arw/status.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Phase 2 already provides the right authority kernel: <code>RuntimeCommandService</code> validates/replays under one lock, the reducer produces a pure projection, and accepted artifacts/passports are content-addressed and ledger-bound. Phase 4 should extend that kernel rather than replace it. The missing layer is a repository-owned assignment/proposal protocol, a frozen scheduler, a narrow execution adapter, formal panel/gate models, and hook observations that cannot become authority.

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; https://learn.chatgpt.com/docs/agent-configuration/subagents.md; https://learn.chatgpt.com/docs/hooks.md] Native Codex behavior must be treated as an external transport capability, not as workflow truth. The Python runtime can deterministically test schemas, retries, ordering, replay, blind assignment construction, hook parity, and gate scope with a fake adapter. A real host tuple can earn formal independent-review credit only after staged canaries prove direct-child identity, result isolation, hook trust behavior, continuation behavior, and cancellation mapping for the exact Codex/plugin/adapter/profile/permission configuration.

**Primary recommendation:** Build a parent-owned immutable assignment/proposal ledger protocol around the existing runtime, use a thin <code>CodexNativeExecutionAdapter</code> only as a qualified transport, and make the 48-case deterministic corpus plus host qualification gates precede any claim of native independent orchestration. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

## Research Scope Notes

[CITED: repository filesystem inventory on 2026-07-14] The supplied working directory was an unrelated Examination worktree. Research was performed in the discovered Academic Research Workbench repository at <code>/home/zhangyangrui/my_programes/academic-research-workbench</code>, and this is the only repository file written.

[CITED: .planning/phases directory inventory on 2026-07-14] The requested Phase 3 directory named <code>03-durable-canonical-runtime-and-recovery</code> does not exist. Its inherited concerns are implemented by completed Phase 2 <code>02-durable-provenance-runtime</code>; the actual Phase 3 is <code>03-secure-files-first-data-plane</code>. Both contexts and summaries were used as the prior-runtime and bounded-retrieval references.

[CITED: .planning/graphs/graph.json absent on 2026-07-14] No project knowledge graph is present, so no graph-derived dependencies were injected into this research.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Assignment preparation, lifecycle decisions, retries, gates, and finalization legality | API / Backend — Python parent runtime | Database / Storage — journal and manifests | Only <code>RuntimeCommandService</code> may append canonical events; the reducer and journal reconstruct legal state without a host session. [CITED: src/arw/runtime.py; src/arw/reducer.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Child dispatch, cooperative cancellation request, and host observations | API / Backend — adapter boundary | Codex host / execution environment | The adapter asks an external host to do work, but returns only observational metadata and an inbox path; it cannot accept proposals or mutate state. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Worker context retrieval | Database / Storage — bounded files MCP | Codex host child | Assignments grant root capability IDs and existing read-only MCP capabilities, not unrestricted paths or admin tools. [CITED: src/arw/files_mcp.py; skills/academic-research-workbench/SKILL.md; .planning/phases/03-secure-files-first-data-plane/03-CONTEXT.md] |
| Immutable proposal/report evidence | Database / Storage — per-attempt evidence plus manifest store | API / Backend — validator | Raw worker bytes are retained as evidence, while only parent-validated manifest references enter canonical history. [CITED: src/arw/manifests.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Independent review and synthesis | API / Backend — panel planner and acceptance cursor | Codex host children | The parent freezes shared subject/rubric digests and separate identities/paths before dispatch; the synthesizer receives accepted reports only after the first round completes. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Hook hydration, preflight, warning, and continuation request | Codex host hook process | API / Backend — observation ingestion | Hooks emit bounded non-authoritative observations; paired runtime results must remain equivalent whether hooks ran or did not run. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; https://learn.chatgpt.com/docs/hooks.md] |
| Human waiver, correction, access, replacement, and approval | API / Backend — parent/operator command | Database / Storage — immutable decision events | Human decisions bind exact evidence and one next transition without editing an earlier verdict. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; src/arw/runtime.py] |

## Standard Stack

### Core

| Library / Component | Version | Purpose | Why Standard |
|---|---:|---|---|
| Python | <code>>=3.13,&lt;3.15</code> | Parent control plane, schemas, reducer, adapter, hooks, and tests | It is the declared ARW runtime and already owns canonical state. [CITED: pyproject.toml; AGENTS.md] |
| ARW <code>RuntimeCommandService</code>, reducer, journal, manifests | Repository-owned | Sole-writer canonical state and replay | Reuse the implemented authority kernel instead of introducing a second workflow engine. [CITED: src/arw/runtime.py; src/arw/reducer.py; src/arw/journal.py; src/arw/manifests.py] |
| <code>pydantic</code> | 2.13.4 | Strict frozen Python contracts and schema generation | Existing <code>StrictModel</code> enforces strict, frozen, extra-forbid contracts at canonical boundaries. [CITED: pyproject.toml; src/arw/models.py] |
| <code>jsonschema</code> | 4.26.0 | Independent Draft 2020-12 validation | Existing schema tests independently validate generated documents and native-shaped fixtures. [CITED: pyproject.toml; tests/schema/test_cross_language.py] |
| Repository-owned <code>CodexNativeExecutionAdapter</code> | New in Phase 4; host tuple qualified | Transport from a prepared attempt to a native Codex child | It keeps host-specific behavior outside the kernel and supports deterministic fake implementations. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

### Supporting

| Library / Component | Version | Purpose | When to Use |
|---|---:|---|---|
| <code>portalocker</code> | 3.2.0 | Existing cross-platform writer lock | Continue serializing parent canonical transactions; do not add a second scheduler lock. [CITED: pyproject.toml; src/arw/journal.py] |
| Standard-library <code>asyncio.TaskGroup</code> and finite semaphore | Python runtime | Concurrent dispatch with deterministic collection | Use for transport concurrency only; buffer results and commit in frozen order. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>pytest</code> | 9.1.1 | Unit, schema, integration, replay, staged, and corpus tests | It is already configured with a <code>codex_host</code> marker. [CITED: pyproject.toml] |
| Existing bounded files MCP | Repository-owned | Worker reading under explicit root capability | Use the five read-only tools only; do not give workers filesystem administration. [CITED: src/arw/files_mcp.py; tests/integration/test_files_mcp.py] |
| Codex CLI | local candidate 0.144.3; recorded floor 0.144.1 | Optional native dispatch/hook qualification | Use only through the adapter and staged test harness; a local binary is not a protocol admission. [CITED: local environment probe 2026-07-14; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| ARW kernel plus thin adapter | LangGraph, CrewAI, Temporal, Celery, or another agent workflow engine | Reject for Phase 4: each introduces a competing scheduler/state authority and conflicts with the locked sole-writer/replay model. [CITED: AGENTS.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Immutable proposal bytes | Transcript parsing or final-chat-message parsing | Reject: transcript format is explicitly unstable, and unstructured text cannot bind assignment/attempt/hash fields. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Assignment-injected native child fallback | Plugin-native custom-agent distribution | Reject as a correctness dependency: custom profiles are project/user configuration, while plugin distribution is unproven. [CITED: skills/academic-research-workbench/SKILL.md; https://learn.chatgpt.com/docs/agent-configuration/subagents.md] |
| Runtime/MCP enforcement | Hook-only policy enforcement | Reject: hooks can be disabled, untrusted, skipped, or concurrent. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |

**Installation:**

~~~bash
uv sync --frozen
~~~

[CITED: pyproject.toml; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Phase 4 needs no new external package. It uses the committed Python stack and repository-owned modules, so a Package Legitimacy Audit is not applicable.

## Architecture Patterns

### System Architecture Diagram

~~~mermaid
flowchart TD
    U[Operator / parent CLI request] --> R[RuntimeCommandService<br/>sole canonical writer]
    R --> A[Immutable assignment manifest<br/>frozen policy, DAG key, inputs, roots, output contract]
    R --> T[Attempt.started canonical event]
    A --> E[ExecutionAdapter boundary]
    T --> E
    E --> H[Qualified Codex direct child<br/>or deterministic fake]
    H --> I[Attempt inbox<br/>raw proposal bytes only]
    I --> V[Parent proposal validator<br/>canonical bytes + schema + bindings + paths]
    V -->|valid and cursor-ready| R
    V -->|invalid / stale / late| N[Immutable negative evidence<br/>rejected or retry decision]
    R --> J[Append-only journal + immutable manifests]
    J --> S[Pure reducer/status/replay]

    A --> P[Four isolated reviewer assignments]
    P --> Q[Four immutable reviewer reports]
    Q --> X[Separate synthesizer assignment only after all required reports]
    X --> F[Finding matrix + review gate]
    F --> R

    K[Codex lifecycle hook] --> O[Bounded observation / one continuation request]
    O --> R
    O -. never writes .-> J

    G[Human gate authority] --> D[Scoped decision request/resolution]
    D --> R
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] The diagram separates host execution, worker evidence, and human/hook inputs from the sole canonical writer; every arrow returning to canonical state passes through the parent validator and runtime transaction.

### Component Responsibilities and Exact File Plan

| Surface | Action | Responsibility / invariant |
|---|---|---|
| <code>src/arw/orchestration_models.py</code> | Create | Strict role catalog, conflict matrix, execution provenance, assignment, attempt envelope, proposal, review finding, gate, waiver/correction/approval, and hook-observation models. This module must not import Codex host code. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>src/arw/scheduler.py</code> | Create | Freeze/validate DAG, derive unique <code>(layer, ordinal)</code> keys, hold the acceptance cursor, classify retryability, and expose deterministic scheduling primitives. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>src/arw/orchestration.py</code> | Create | Parent coordinator that prepares assignments, creates attempts, invokes the adapter, buffers results, and submits only parent commands in frozen order. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>src/arw/execution.py</code> | Create | <code>ExecutionAdapter</code> protocol, deterministic fake, and thin <code>CodexNativeExecutionAdapter</code>; adapter returns observations and proposal path only. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>src/arw/review.py</code> | Create | Formal-panel construction, blind capability filtering, conflict checks, all-report prerequisite, separate synthesis input, finding-matrix/gate evaluation. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>src/arw/hook_contracts.py</code> | Create | Strict stdin/output models, bounded observation records, continuation idempotency keys, allowed hook status values, and redaction limits. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>hooks/arw_hook.py</code> | Create | Synchronous, bounded command hook that reads immutable context and emits a strict observation; it never imports runtime mutation commands. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>src/arw/models.py</code> | Extend compatibly | Add Phase 4 event payload discriminators and parent/operator request envelopes. Preserve all Phase 2 schema/event behavior. [CITED: src/arw/models.py; .planning/phases/02-durable-provenance-runtime/02-CONTEXT.md] |
| <code>src/arw/schema_registry.py</code> and <code>schemas/v1/</code> | Extend | Register and byte-stably generate checked-in Phase 4 schemas; validate every worker-visible/proposed document independently. [CITED: src/arw/schema_registry.py; tests/schema/test_schema_drift.py] |
| <code>src/arw/workflows.py</code> | Extend | Add event categories/authority map and legal transitions for assignment, proposal, review, gate, and decision outcomes; worker/hook roles remain unauthorized. [CITED: src/arw/workflows.py; src/arw/models.py] |
| <code>src/arw/reducer.py</code> | Extend | Project immutable assignments, attempt state/outcomes, schedule cursor, panel/report state, gate blockers, and scoped decision state from events only. [CITED: src/arw/reducer.py] |
| <code>src/arw/runtime.py</code> | Extend | Add parent-only prepare/seal/accept/reject/retry/cancel/supersede/gate commands inside existing replay-lock-validate-append-replay transaction flow. [CITED: src/arw/runtime.py] |
| <code>src/arw/manifests.py</code> and <code>src/arw/journal.py</code> | Extend | Install/load immutable assignment/proposal/report/gate manifests and fail closed on bad path/hash/event-manifest semantics during replay. [CITED: src/arw/manifests.py; src/arw/journal.py] |
| <code>src/arw/status.py</code> and <code>src/arw/cli.py</code> | Extend | Surface active schedule, blocked gates, hook observation status, panel completeness, and legal next action through parent-only commands. [CITED: src/arw/status.py; src/arw/cli.py] |
| <code>hooks/hooks.json</code> and <code>.codex-plugin/plugin.json</code> | Extend | Replace the baseline SessionStart-only hook with explicit bounded lifecycle commands and pin the plugin hook path as <code>./hooks/hooks.json</code>; package containment and trust remain staged-tested. [CITED: hooks/hooks.json; .codex-plugin/plugin.json; https://learn.chatgpt.com/docs/build-plugins.md; https://learn.chatgpt.com/docs/hooks.md] |
| <code>tests/evals/phase4/corpus/v1/</code> and Phase 4 test files | Create | Establish the corpus and red tests before adapter implementation or host admission. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

### Recommended Project Structure

~~~text
src/arw/
├── orchestration_models.py  # strict Phase 4 contracts; no host import
├── scheduler.py             # frozen DAG and canonical acceptance cursor
├── orchestration.py         # parent coordinator only
├── execution.py             # protocol, fake, qualified Codex adapter
├── review.py                # panel/blinding/synthesis/finding matrix
└── hook_contracts.py        # hook wire contracts and idempotency
hooks/
├── hooks.json               # explicit lifecycle registration
└── arw_hook.py              # synchronous observation-only hook
schemas/v1/
├── assignment.schema.json
├── worker-proposal.schema.json
├── role-catalog.schema.json
├── review-finding-matrix.schema.json
├── gate-decision.schema.json
└── hook-observation.schema.json
tests/
├── unit/test_orchestration_models.py
├── unit/test_scheduler.py
├── unit/test_review.py
├── unit/test_hook_contracts.py
├── schema/test_phase4_contracts.py
├── integration/test_orchestration_lifecycle.py
├── integration/test_orchestration_replay.py
├── integration/test_orchestration_panels.py
├── integration/test_orchestration_hook_parity.py
├── integration/test_human_gates.py
├── evals/test_phase4_corpus.py
└── staged/test_phase4_host_qualification.py
tests/evals/phase4/corpus/v1/
├── manifest.json
├── development/
└── sealed-parent-only/
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Optional native custom-agent TOML files belong in user or project <code>.codex/agents/</code>, not as an assumed plugin-distributed agent facility. Keep assignment-injected direct children as the correctness baseline.

### Data Model and Invariant Boundaries

| Model / state | Minimum immutable bindings | Parent-only invariant |
|---|---|---|
| Role catalog and conflict matrix | Catalog/matrix version and digest; role ID; capability class; independence eligibility; prohibited pair list | A workflow freezes the selected catalog/matrix digest before dispatch; no later catalog edit reinterprets an active run. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Assignment manifest | Run/stage/task IDs; role; worker identity; execution mode; base revision; ordered input/policy/context hashes; root/capability IDs; direct scratch/result paths; output schema/size; blind constraints; deadline; completion contract; frozen DAG key; supersedes assignment | The parent creates and seals one assignment before attempt start. A content change produces a new assignment with an explicit supersession relation. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Attempt state | Assignment ID; new attempt ID/number; host observation identity; start/cancel/termination timestamps; continuation count; terminal disposition | A retry retains the assignment ID but creates a fresh attempt. Attempt number never exceeds two, and a cancelled/superseded attempt cannot reopen. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Worker proposal bytes | Exact canonical JSON bytes/digest; assignment/attempt/role/worker/host IDs; nonce; base revision; ordered consumed hashes; output paths/sizes/digests; proposed disposition | Seal raw bytes before validation; parent cross-validates every echoed field against the assignment and adapter observation; raw output does not itself mutate state. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Scheduler state | Frozen DAG digest; topological layer; task ordinal; acceptance cursor; required/optional flag; predecessor terminal outcomes | Completion timing is observational. The reducer advances only when every earlier key has a terminal outcome, then records acceptance/rejection/retry decision in cursor order. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Formal review round | Shared subject/rubric/context hashes; four parent-created worker identities; distinct host identities; separate attempts/nonces/results; no peer capability/path | Synthesis is illegal until every required first-round report is accepted. <code>degraded_inline</code> has independence eligibility false. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Finding matrix and gate | Source report hashes; evidence hashes; severity/confidence; consensus class; limitation/absence record; PASS/FAIL/BLOCKED verdict | Majority cannot delete dissent; unresolved critical/DA-critical findings keep the gate blocked. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Human decision | Decision kind/choice; accountable actor/role; exact gate/subject/evidence hashes; allowed transition; scope; rationale; conflict declaration; timestamp | Waiver, correction, release, access escalation, replacement, and approval append a new event. They never rewrite a prior verdict and permit one next legal transition only. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Hook observation | Hook definition digest; event/attempt/deliverable ID; trust status; bounded output digest; redacted taxonomy; idempotency key; continuation count | A hook process emits observation only. The parent may record an idempotent observation but continues to enforce the same runtime/MCP/gate rules without it. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; https://learn.chatgpt.com/docs/hooks.md] |

### Pattern 1: Immutable Assignment, New Attempt

**What:** Create a content-addressed assignment first, start a fresh attempt that references it, and give the adapter only an attempt-local result inbox. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

**When to use:** Every specialized worker, panel reviewer, synthesizer, hook continuation, retry, cancellation recovery, and supersession path. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Required rule:** A retry changes only attempt-scoped fields; any changed role/input/capability/root/schema/policy/deadline creates a superseding assignment. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

### Pattern 2: Concurrent Execution, Frozen Acceptance

**What:** Dispatch a frozen layer through a finite semaphore and <code>TaskGroup</code>, buffer all host outcomes, then process the smallest unresolved <code>(topological_layer, task_ordinal)</code> key. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

**When to use:** Any layer with more than one independent worker, including the four-reviewer panel. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Anti-pattern:** Do not accept with <code>asyncio.as_completed()</code>; its completion order is nondeterministic and would make canonical history timing-dependent. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pattern 3: Raw Evidence Before Parent Validation

**What:** Read the one admissible direct, non-symlink proposal file under the attempt result root; seal its raw bytes/digest in restricted evidence; validate canonical JSON, strict model, independent schema, echo bindings, path/size constraints, cancellation/supersession state, and frozen cursor before accepting anything. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

**When to use:** Every host result, including malformed, stale, cancelled, late, or duplicate proposals. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Anti-pattern:** Do not use a transcript path, final message, host session ID, or an adapter callback as a proposal/gate authority. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pattern 4: Formal Blind Panel Before Synthesis

**What:** Freeze one subject/rubric/context snapshot, construct four isolated assignments with distinct identities/nonces/results, accept all required reports, then create a fifth separate synthesizer assignment that reads only accepted reports. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**When to use:** Only for workflows claiming formal independent review. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Anti-pattern:** Do not treat four role labels in one inline prompt, one reused host identity, or an early synthesizer as independent review. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pattern 5: Hooks as Observations With Parity

**What:** Let synchronous hooks output a bounded strict observation and at most one continuation request keyed to an attempt/deliverable. The parent independently verifies envelope validity and records any accepted observation through the normal writer. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; https://learn.chatgpt.com/docs/hooks.md]

**When to use:** Session hydration, SubagentStart context, SubagentStop malformed-envelope hints, policy warnings, and Stop reminders only. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Anti-pattern:** Do not set hook <code>async</code>, rely on matching-hook order, make a hook write a journal/manifests pointer, or let it release a gate. Current Codex documentation says asynchronous command hooks are skipped and matching command hooks may start concurrently. [CITED: https://learn.chatgpt.com/docs/hooks.md]

### Pattern 6: Append-Only Gate Evolution

**What:** Model gate evaluation, human decision request, human resolution, waiver, correction, access decision, and approval as append-only records with exact hashes/scopes and reducer-derived legality. [CITED: src/arw/runtime.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**When to use:** Every PASS/FAIL/BLOCKED change, critical dissent, stale evidence, restricted access, escalation, retry replacement, and final completion. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

**Anti-pattern:** Do not mutate a verdict file in place or define a blanket approval that covers future evidence or several transitions. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

## Proposed Canonical Lifecycle

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Event names are a discretion area; use the following explicit event families so replay and status have one finite state machine.

| State change | Parent command / canonical event family | Required outcome |
|---|---|---|
| Freeze catalog/policy/DAG and prepare work | <code>assignment.prepared</code> | Assignment manifest exists, is content-addressed, and binds the frozen acceptance key. |
| Begin a transport try | <code>attempt.started</code> | New attempt ID and number reference an existing assignment; the worker has no canonical credentials. |
| Observe host dispatch/result | <code>attempt.dispatched</code> / <code>proposal.sealed</code> | Record redacted host observation and raw proposal digest without accepting the proposal. |
| Accept a valid proposal | <code>proposal.accepted</code> plus accepted artifact/report manifest event | Only cursor-ready, current, schema-valid, fully bound proposal bytes can produce accepted state. |
| Reject a proposal | <code>proposal.rejected</code> | Preserve reason and raw digest; distinguish invalid, stale, cancelled, superseded, late, permission, or policy outcomes. |
| Retry an eligible failure | <code>attempt.closed</code> followed by fresh <code>attempt.started</code> | Same assignment, new attempt, maximum attempt number two. |
| Request/force cancellation | <code>attempt.cancel_requested</code>, then <code>attempt.termination_recorded</code> or <code>attempt.interrupted</code> | Record cooperative deadline first; preserve later output as <code>rejected_stale</code>; force mapping is host-qualified. |
| Supersede changed work | <code>assignment.superseded</code> then new <code>assignment.prepared</code> | Old assignment/attempt output remains evidence and cannot be accepted. |
| Complete panel/synthesis | <code>review.report_accepted</code>, <code>review.synthesis_accepted</code>, <code>gate.evaluated</code> | Synthesis is blocked until all required reports are accepted; finding matrix preserves dissent. |
| Resolve a consequential gate | <code>human_decision.requested</code> / <code>human_decision.resolved</code> with a typed decision kind | A scoped, rationale-bearing event releases only the exact blocker or one next transition. |
| Recover after parent crash | <code>attempt.interrupted</code>, then retry/replacement/block decision | Every recovered active attempt has a terminal/requeue decision within its remaining retry budget. |

## Host-Qualified-Only Behavior

| Host-facing behavior | Deterministic fake must prove | Exact staged host test must prove | Admission rule |
|---|---|---|---|
| Direct-child native dispatch | Adapter receives frozen <code>DispatchSpec</code>, writes only to configured inbox, and returns a trusted-shaped observation. | The exact Codex version starts a fresh direct child from staged plugin bytes and binds observed <code>agent_id</code> to the assignment/attempt. [CITED: https://learn.chatgpt.com/docs/agent-configuration/subagents.md] | Formal independent work is BLOCKED until PASS. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Native/custom role profile availability | Fallback selection records <code>assignment_injected</code> or <code>degraded_inline</code> accurately. | Project/user profile discovery and effective role instructions are observed without assuming plugin profile distribution. [CITED: https://learn.chatgpt.com/docs/agent-configuration/subagents.md] | Use assignment-injected child as the normal fallback; never silently count inline work as independent. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Parent permission/sandbox inheritance and root confinement | Assignment contains only declared capability/root IDs and result paths. | Child receives no peer/result/admin access and cannot exploit inherited host permissions to alter canonical state. Codex documents parent live override inheritance, but the effective tuple still needs canary evidence. [CITED: https://learn.chatgpt.com/docs/agent-configuration/subagents.md] | Host failure blocks the affected native route. |
| Result handoff and host identity | Parent accepts only a path under the direct attempt result root and a non-empty adapter-observed ID. | Host-produced proposal is isolated to the assigned path; a distinct host ID exists for every formal seat. | No transcript/session ID substitute is accepted. [CITED: https://learn.chatgpt.com/docs/hooks.md] |
| Cooperative cancellation / force termination | State machine records deadline, retry budget, and a late proposal as stale. | The adapter's request-cancel and force/interruption mapping works, or the host reports an honest unsupported result. [ASSUMED] | If force termination is not proven, mark interrupted/BLOCKED after the cooperative deadline; do not invent an API. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Hook trust, disabled/bypass behavior, and concurrency | Strict hook wire model, idempotency key, one-continuation cap, and authority-normalized parity. | Trusted, disabled, changed/untrusted, timeout, and failure modes behave as documented; concurrent matching hook invocations cannot exceed one continuation. [CITED: https://learn.chatgpt.com/docs/hooks.md] | No mode may change canonical authorization/MCP/gate result. |
| SubagentStop/Stop continuation effect | Parent records no more than one continuation intent and still validates final proposal. | The exact client honors the desired continuation path sufficiently for the adapter contract. [ASSUMED] | Treat host continuation as convenience only; a failure never changes parent lifecycle legality. |
| Effective direct-child limits | Scheduler stays within configured finite width and depth one. | <code>agents.max_depth=1</code> and policy <code>agents.max_threads=4</code> are observed on the staged host. Codex documents configurable depth/thread limits and defaults, but no plugin manifest owns this configuration. [CITED: https://learn.chatgpt.com/docs/agent-configuration/subagents.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] | Fail qualification if effective limits do not support the frozen plan safely. |

[ASSUMED] The current local Codex CLI can be authenticated and exposed to a safe staged qualification environment. This was deliberately not inferred from the presence of the binary; planning must retain a human/CI qualification checkpoint.

## Don't Hand-Roll

| Problem | Do Not Build | Use Instead | Why |
|---|---|---|---|
| Canonical event serialization and hash chain | A separate orchestration journal or mutable scheduler checkpoint | Existing canonical JSON/seal/journal/reducer transaction path | A second source of truth would break replay and sole-writer authority. [CITED: src/arw/canonical.py; src/arw/journal.py; src/arw/runtime.py] |
| Contract validation | Ad hoc <code>dict</code> checks or model-only validation | Existing strict Pydantic models plus checked-in Draft 2020-12 schemas and independent <code>jsonschema</code> tests | Worker bytes are untrusted; independent validation catches schema-generation drift. [CITED: src/arw/models.py; tests/schema/test_cross_language.py] |
| Locking | A custom asyncio/file lock around writes | Existing journal/portalocker write lock | Canonical writes are already serialized and replay-verified under the runtime lock. [CITED: src/arw/journal.py; pyproject.toml] |
| Filesystem confinement | New worker file utilities or path strings in prompts | Existing one-root, read-only files MCP and assignment capability IDs | Phase 3 already exercises traversal, symlink, output-cap, and no-write protections. [CITED: src/arw/files_mcp.py; tests/integration/test_files_security.py] |
| Agent workflow framework | LangGraph/CrewAI graph/checkpoint/retry abstraction | Repository-owned frozen scheduler and thin adapter | The phase requires deterministic historical ordering and immutable artifacts, not framework-owned state. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Native host API | Unverified subprocess/thread/session control assumptions | <code>ExecutionAdapter</code> protocol, deterministic fake, and staged canaries | Public host behavior changes independently of ARW and must be qualified. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Human gate editing | In-place verdict files or a generic “approved” flag | Typed append-only decisions with exact hashes/scope and reducer legality | Original evidence must remain immutable and a decision may authorize one exact next transition. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |

**Key insight:** Phase 4 is not an “agent framework” feature. It is an extension of the existing durable authority protocol in which a host is only a transport, a worker is only a proposal producer, a hook is only an observation source, and a human decision is only a precisely scoped new event. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

## Delivery Dependency Order

| Order | Deliverable | Why it precedes the next step |
|---|---|---|
| 0 | Freeze the Phase 4 schema/corpus manifest, 32 development cases, 16 sealed parent-only cases, and deterministic fake-adapter test fixtures. | The AI contract requires corpus v1 and red tests before adapter implementation or host admission; it gives later code a fixed oracle. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| 1 | Add strict models, generated schemas, schema registry entries, event categories, reducer state, workflow legality, and status fields. | Runtime commands cannot safely persist or replay a concept whose bytes/schema/state are not defined first. [CITED: src/arw/schema_registry.py; src/arw/reducer.py; src/arw/workflows.py] |
| 2 | Implement immutable assignment/proposal/report/gate manifests and parent-only runtime commands with rejection-without-authoritative-write tests. | Scheduler/adapter behavior must enter the existing transaction path, not create side stores. [CITED: src/arw/runtime.py; src/arw/manifests.py] |
| 3 | Implement frozen scheduler and deterministic fake adapter lifecycle/recovery paths. | Deterministic ordering, retry/cancel/supersede, and cold replay must work without Codex before adding host uncertainty. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| 4 | Implement review isolation/finding matrix, gates, human decisions, hook contracts, and hook-parity suite. | These features depend on stable assignment/attempt/proposal state and must prove the same authority behavior in every hook mode. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| 5 | Implement <code>CodexNativeExecutionAdapter</code>, stage exact plugin bytes, and run host-qualified canaries in fresh homes. | Native behavior is an admission test after deterministic protocol proof, not a design assumption. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

## Common Pitfalls

### Pitfall 1: Treating Host Completion Order as Canonical Order

**What goes wrong:** A later task becomes part of accepted history because it finishes first.  
**Why it happens:** Collection code uses <code>asyncio.as_completed()</code> or dispatch-time callbacks as acceptance authority.  
**How to avoid:** Buffer all outcomes, resolve only the frozen cursor key, and test every permutation for layers of two through five workers.  
**Warning signs:** Journal/status/artifact hashes differ solely because completion ordering changes. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 2: Mutating an Assignment on Retry

**What goes wrong:** A retry subtly receives new inputs, a new deadline, or a broader capability while retaining its original assignment ID.  
**Why it happens:** Attempt and assignment state are stored in one mutable record.  
**How to avoid:** Make assignment bytes a manifest; create a new attempt for a retry and an explicit superseding assignment for every changed assignment binding.  
**Warning signs:** An accepted proposal cannot be reconstructed from the original assignment digest. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

### Pitfall 3: Giving a Worker a Canonical Write Surface

**What goes wrong:** A worker, hook, adapter, or MCP caller can append an event, move a manifest pointer, or mark a gate passed.  
**Why it happens:** Canonical CLI/runtime calls are exposed in child tools, or parent authority is inferred from a caller-supplied actor field.  
**How to avoid:** Keep the command surface parent/operator-only; run byte-identical authoritative-tree rejection tests for worker/hook/adapter/direct-file attacks.  
**Warning signs:** A worker identity appears as an accepted event actor or a rejected request changes a journal/manifest pointer. [CITED: src/arw/workflows.py; tests/integration/test_runtime_transitions.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 4: Confusing Codex Session ID With Worker Identity

**What goes wrong:** A panel appears to have distinct workers because IDs from hook context or a parent session differ, while actual children are reused or undisclosed.  
**Why it happens:** Codex hook documentation states subagent hooks use the parent session ID; session metadata is not a proof of a distinct child.  
**How to avoid:** Bind each formal seat to a parent-created worker ID and a separately adapter-observed host <code>agent_id</code>; staged host tests must prove both.  
**Warning signs:** The four panel assignments share a session ID, scratch directory, nonce, or host identity. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 5: Blindness Theater

**What goes wrong:** Reviewers can read peer reports, attempt metadata, expected labels, or an early synthesis despite “blind” role names.  
**Why it happens:** The same context tree or root capability is reused for all panel seats.  
**How to avoid:** Test visibility as a matrix: identical subject/rubric digest, distinct attempts/nonces/paths, no peer report paths/capabilities, labels outside allowed roots, fifth synthesizer after acceptance.  
**Warning signs:** A first-round assignment contains any peer ID/report hash/path or the sealed-corpus path. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 6: Hook-Only Enforcement

**What goes wrong:** Disabling, declining trust for, timing out, or bypassing a hook makes an otherwise forbidden action succeed.  
**Why it happens:** PreToolUse/Stop output is treated as the security or workflow boundary.  
**How to avoid:** Put authorization in runtime/MCP/gate checks and compare trusted/disabled/untrusted/timeout/failed runs after removing allowlisted observation-only differences.  
**Warning signs:** Different hook modes produce different accepted event sequence, gate verdict, MCP denial, or legal transition. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

### Pitfall 7: Depending on Hook Order or Async Hooks

**What goes wrong:** One hook is assumed to prepare state before another, or a configured async hook never runs.  
**Why it happens:** Matching command hooks may launch concurrently, and documented async command hooks are skipped.  
**How to avoid:** Make each observation idempotent and self-contained, serialize only through the parent transaction, use synchronous commands with finite timeouts, and test duplicate/concurrent delivery.  
**Warning signs:** Flaky continuation counts or a hook status that differs by invocation order. [CITED: https://learn.chatgpt.com/docs/hooks.md]

### Pitfall 8: Rewriting a Gate Verdict

**What goes wrong:** A waiver flips a failed result to pass, or an approval silently releases several blockers.  
**Why it happens:** The model represents a gate as a mutable current-status row rather than immutable verdict and decision events.  
**How to avoid:** Preserve the original verdict bytes; append a scoped typed decision with exact hashes and one legal transition, then invalidate dependent evidence for corrections.  
**Warning signs:** Before/after canonical event bytes change or a decision lacks a subject/evidence hash/rationale/actor/scope. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

### Pitfall 9: “No Side Effect” Tests That Snapshot the Wrong Tree

**What goes wrong:** Tests fail because rejected proposal raw evidence is correctly retained, or pass while an accepted pointer changed outside the snapshot.  
**Why it happens:** The same filesystem snapshot is used for authoritative state and restricted raw evidence.  
**How to avoid:** Define <code>authoritative_tree()</code> for journal, accepted manifests/pointers, and canonical projections; separately assert allowed raw-evidence append-only retention and no new accepted reference.  
**Warning signs:** A rejection test either forbids required forensic retention or cannot detect an accepted-manifest pointer write. [CITED: src/arw/manifests.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 10: Fake-Only Native Claims

**What goes wrong:** Unit tests prove the fake adapter but the product claims native child isolation, cancellation, profiles, hook trust, or identity without a real host.  
**Why it happens:** A local Codex binary is mistaken for qualified host behavior.  
**How to avoid:** Mark host-dependent tests <code>codex_host</code>, run them from exact staged bytes in three fresh homes, and block formal-panel admission until the tuple passes.  
**Warning signs:** A test report contains no exact stage/adapter/Codex/profile/permission/hook digest evidence. [CITED: pyproject.toml; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Pitfall 11: Cold Replay That Secretly Needs Host State

**What goes wrong:** Recovery reads a transcript, cache, status file, or live host context to decide which proposal/gate result existed.  
**Why it happens:** Observational host state is allowed to become de facto authority.  
**How to avoid:** Delete transcripts, host cache/context, status output, projections, and hook logs before fresh-process replay; reconstruct only from canonical events/manifests/artifacts/decision records.  
**Warning signs:** Replaying an identical canonical tree gives a different cursor, gate, or next legal transition after those files are removed. [CITED: .planning/STATE.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

## Code Examples

Verified patterns are shown as implementation-oriented pseudocode. They define boundaries for the planner; they are not a request to paste an unqualified host API into the kernel.

### Narrow Execution Adapter

~~~python
# Source: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md
from pathlib import Path
from typing import Protocol

class ExecutionAdapter(Protocol):
    async def dispatch(self, spec: DispatchSpec) -> HostResult: ...
    async def request_cancel(self, spec: DispatchSpec) -> None: ...
    async def force_terminate(self, spec: DispatchSpec) -> None: ...

class HostResult(StrictModel):
    attempt_id: StableId
    host_agent_id: str
    proposal_path: str
    # transcript/reference fields, if observed, are non-authoritative metadata only
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] The adapter has exactly the host actions the parent needs. It must not expose append-event, accept-proposal, resolve-gate, or direct manifest mutation methods.

### Proposal Admission Boundary

~~~python
# Source: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md
async def admit_result(spec: DispatchSpec, result: HostResult) -> ProposalDisposition:
    proposal_path = require_direct_regular_file(
        root=spec.result_root,
        candidate=result.proposal_path,
        required_name=spec.result_name,
    )
    raw = proposal_path.read_bytes()
    raw_receipt = runtime.seal_raw_proposal(spec, result, raw)
    proposal, proposal_sha256 = validate_canonical_proposal_bytes(raw)
    validate_echo_bindings(
        proposal=proposal,
        assignment=runtime.load_assignment(spec.assignment_id),
        attempt=spec.attempt_id,
        observed_host_agent_id=result.host_agent_id,
        raw_sha256=proposal_sha256,
    )
    return runtime.accept_or_reject_at_frozen_cursor(spec, proposal, raw_receipt)
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] The acceptance command uses the current runtime CAS/revision but validates the proposal against its frozen assignment/base/input/cursor bindings. A proposal does not become valid by rewriting it to the current revision.

### Deterministic Concurrent Collection

~~~python
# Source: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md
async def collect_layer(specs: tuple[DispatchSpec, ...]) -> dict[StableId, HostResult]:
    semaphore = asyncio.Semaphore(4)
    completed: dict[StableId, HostResult] = {}

    async def one(spec: DispatchSpec) -> None:
        async with semaphore:
            completed[spec.assignment_id] = await adapter.dispatch(spec)

    async with asyncio.TaskGroup() as group:
        for spec in specs:
            group.create_task(one(spec))
    return completed

for key in frozen_schedule.keys_in_order():
    resolve_terminal_outcome(key, completed.get(key.assignment_id))
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Dispatch may be concurrent; <code>keys_in_order()</code>, not completion arrival, decides canonical acceptance.

### Hook Observation Contract

~~~json
{
  "schema_version": "arw.hook-observation.v1",
  "hook_event": "SubagentStop",
  "attempt_id": "attempt.example",
  "hook_definition_sha256": "…",
  "status": "trusted_enabled",
  "observation_kind": "proposal_incomplete",
  "continuation_request": {
    "idempotency_key": "attempt.example:subagent-stop:v1",
    "requested": true
  }
}
~~~

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; https://learn.chatgpt.com/docs/hooks.md] The hook writes this bounded value to stdout only; the parent checks the persisted continuation counter and independently decides whether to continue.

## State of the Art

| Old Approach | Current Phase 4 Approach | When / Why | Impact |
|---|---|---|---|
| Treat transcript/final chat text as worker output | Canonical, schema-valid proposal bytes tied to an immutable assignment and external observation | Codex documents transcript paths as unstable; the phase contract requires byte-level bindings. [CITED: https://learn.chatgpt.com/docs/hooks.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] | Replay and acceptance no longer depend on model conversation storage. |
| Accept whichever worker finishes first | Freeze DAG/layer/ordinal and buffer concurrent outcomes | The phase contract makes timing unable to change canonical history. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] | Completion permutations can be exhaustively tested. |
| Agent framework owns retries/checkpoints | Existing ARW writer/reducer owns lifecycle; adapter is transport-only | Locked sole-writer and immutable-manifest architecture rejects competing state machines. [CITED: AGENTS.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] | Cold replay remains local and host-independent. |
| Hook blocks/authorizes a workflow | Runtime/MCP/gate constraints operate identically with hook observations absent | Hooks can be untrusted, disabled, skipped, and concurrent. [CITED: https://learn.chatgpt.com/docs/hooks.md] | Hook parity becomes a testable safety property. |
| “Human approved” edits a mutable status | Scoped append-only waiver/correction/access/approval event | D-15/D-16 require immutable verdict evidence and exact scope. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] | Accountability and supersession are replayable. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | [ASSUMED] A future staged host can expose a direct-child dispatch/cancellation mapping that the thin adapter can qualify. | Host-Qualified-Only Behavior | The native path stays unavailable; deterministic fake coverage still works and formal independent work remains BLOCKED. |
| A2 | [ASSUMED] The exact host can provide an adapter-observed child identity that is stable enough to bind a formal panel seat. | Host-Qualified-Only Behavior | A native panel cannot claim distinct identities and must be BLOCKED. |
| A3 | [ASSUMED] The exact host's <code>SubagentStop</code>/<code>Stop</code> behavior can support the desired one-continuation convenience path. | Host-Qualified-Only Behavior | Continuation is disabled or recorded as unsupported; parent lifecycle correctness remains unaffected. |
| A4 | [ASSUMED] A safe authenticated, fresh-home staged test environment will be supplied before native-host admission. | Environment Availability / Validation Architecture | Host canaries cannot run; do not infer a PASS from unit/fake-adapter tests. |

## Open Questions

1. **Which exact native dispatch/cancellation interface will the adapter use for Codex CLI 0.144.3?**
   - What we know: Codex documents subagents, configuration limits, custom-agent locations, and hook behavior, but the Phase 4 AI contract explicitly says plugin-callable spawn/cancel/force-kill mappings are not locally proven. [CITED: https://learn.chatgpt.com/docs/agent-configuration/subagents.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
   - What is unclear: The exact implementation path, force termination behavior, and observed identity/result isolation under this installed host.
   - Recommendation: Isolate it in <code>CodexNativeExecutionAdapter</code>, ship deterministic fakes first, and make the exact tuple a staged <code>codex_host</code> admission gate.

2. **How is a human gate actor authenticated and conflict declaration supplied at the CLI boundary?**
   - What we know: Existing Phase 2 decisions already carry actor/choice/rationale, while D-15/D-16 require richer accountable actor/role/scope/conflict/evidence bindings. [CITED: src/arw/models.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]
   - What is unclear: Whether Phase 4’s local single-user CLI needs a configured operator identity file or an explicit request field plus a visible “unverified identity” classification.
   - Recommendation: Plan a strict local operator identity configuration/validation checkpoint before final-approval commands; do not claim stronger authentication than the host actually provides. [ASSUMED]

3. **Which pinned ARS role assets map to optional support roles beyond the locked five-role minimum?**
   - What we know: The mandatory four reviewers, separate synthesizer, and experiment designer are fixed; role combinations are a discretion area. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]
   - What is unclear: The initial catalog’s optional specialist set.
   - Recommendation: Begin with only required roles plus <code>experiment_designer</code>; add optional roles only with a catalog/matrix version and corpus cases. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---:|---|---|
| Python | Parent runtime and tests | ✓ | 3.14.6 | Project supports 3.13 through 3.14; do not add a runtime. [CITED: local environment probe 2026-07-14; pyproject.toml] |
| uv | Locked environment and test commands | ✓ | 0.11.28 | — [CITED: local environment probe 2026-07-14] |
| pytest | Deterministic suites | ✓ | 9.1.1 | — [CITED: local environment probe 2026-07-14; pyproject.toml] |
| Codex CLI | Optional native adapter/host qualification | ✓ | 0.144.3 candidate | Deterministic fake adapter; formal native independence remains BLOCKED until qualification. [CITED: local environment probe 2026-07-14; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| bubblewrap | Existing isolated staged launcher patterns | ✓ | 0.11.0 | Existing no-network/staged harness may choose its documented fallback if platform support differs. [CITED: local environment probe 2026-07-14; tests/staged/test_mcp_launcher.py] |
| Node.js | Existing staging/smoke helper ecosystem | ✓ | v24.13.0 | Python tests do not depend on it for deterministic orchestration logic. [CITED: local environment probe 2026-07-14] |
| Authenticated fresh Codex host tuple | Exact staged native dispatch/hook/cancellation canaries | Not qualified | — | Deterministic fakes cover kernel behavior only. [ASSUMED] |

**Missing dependencies with no fallback:**

- [ASSUMED] A qualified authenticated Codex host tuple is required before a formal native independent-review capability can be admitted; it is not required to implement or test the deterministic Phase 4 kernel.

**Missing dependencies with fallback:**

- [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Native dispatch/cancellation/profile behavior can be represented by deterministic fakes while the adapter and staged qualification suite are built; do not use that fallback to make a formal independence claim.

## Validation Architecture

[CITED: .planning/config.json] Nyquist validation is enabled. Phase 4 therefore requires test-first delivery, an explicit requirement map, Wave 0 fixtures, and a phase gate rather than a single end-to-end smoke test.

### Test Framework

| Property | Value |
|---|---|
| Framework | <code>pytest 9.1.1</code> with strict markers. [CITED: pyproject.toml; local environment probe 2026-07-14] |
| Schema validator | <code>jsonschema 4.26.0</code> independently validates generated Draft 2020-12 contracts. [CITED: pyproject.toml; tests/schema/test_cross_language.py] |
| Test configuration | <code>pyproject.toml</code>; existing marker <code>codex_host</code> is reserved for authenticated fresh-host plugin tests. [CITED: pyproject.toml] |
| Quick deterministic run | <code>uv run pytest -q tests/unit/test_orchestration_models.py tests/unit/test_scheduler.py tests/schema/test_phase4_contracts.py</code> after these files are added. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Full deterministic run | <code>uv run pytest -q -m "not codex_host" tests/unit tests/schema tests/integration tests/staged tests/evals</code>. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Host qualification run | <code>ARW_EXPECT_CODEX_VERSION=&lt;exact-version&gt; uv run pytest -q -m codex_host tests/staged/test_phase4_host_qualification.py</code>, repeated in three independent fresh homes for the exact host tuple. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

### Existing Analogs to Extend

| Existing file / pattern | What it proves today | Phase 4 reuse |
|---|---|---|
| <code>tests/integration/test_runtime_attempts.py</code> | Parent starts/closes attempts and rejection paths remain side-effect free. | Extend its authoritative-tree oracle into assignment/proposal/retry/cancel/supersede scenarios. [CITED: tests/integration/test_runtime_attempts.py] |
| <code>tests/integration/test_runtime_transitions.py</code> | Runtime/CLI reject unauthorized worker actor and stale/out-of-order commands. | Add worker/hook/adapter direct-write and gate-bypass attacks. [CITED: tests/integration/test_runtime_transitions.py] |
| <code>tests/unit/test_reducer.py</code> | Pure reducer validation and deterministic state projection. | Add schedule cursor, assignment/attempt disposition, panel, gate, and scoped-decision event-sequence fixtures. [CITED: tests/unit/test_reducer.py] |
| <code>tests/schema/test_cross_language.py</code> and <code>test_schema_drift.py</code> | Independent schema validation and byte-stable regeneration. | Add all worker-visible assignment/proposal/review/gate/hook contracts and hostile fixture mutations. [CITED: tests/schema/test_cross_language.py; tests/schema/test_schema_drift.py] |
| <code>tests/integration/test_recovery.py</code> and <code>test_recovery_crash.py</code> | Tail recovery, exact quarantine evidence, crash/retry behavior. | Add active-orphan interruption, retry-budget preservation, late proposal retention, and cold replay after host/cache deletion. [CITED: tests/integration/test_recovery.py; tests/integration/test_recovery_crash.py] |
| <code>tests/integration/test_passport_lifecycle.py</code> | Immutable manifest install and pointer/event authority separation. | Reuse for assignment/proposal/report/gate manifest installation and no-pointer-on-rejection assertions. [CITED: tests/integration/test_passport_lifecycle.py] |
| <code>tests/integration/test_files_security.py</code> and <code>test_files_mcp.py</code> | Five bounded read-only MCP tools, root confinement, and no writes. | Test that every worker assignment exposes only declared capability IDs and hook modes cannot affect MCP denials. [CITED: tests/integration/test_files_security.py; tests/integration/test_files_mcp.py] |
| <code>tests/integration/test_phase2_durable_runtime.py</code> | Staged harness records command/evidence/tree snapshots from an isolated install. | Reuse the fresh-home, exact-stage, no-source-import evidence pattern for Phase 4 staged fixtures. [CITED: tests/integration/test_phase2_durable_runtime.py] |
| <code>tests/staged/test_skill_route.py</code>, <code>test_compatibility_probes.py</code>, and <code>test_mcp_launcher.py</code> | Exact staged bytes, fresh homes, host marker, plugin identity, hook boundary, and no absolute private paths. | Add native subagent/hook canaries without weakening existing installed-plugin isolation. [CITED: tests/staged/test_skill_route.py; tests/staged/test_compatibility_probes.py; tests/staged/test_mcp_launcher.py] |

### Test Surface to Create

| New test file | Primary coverage | Required oracle |
|---|---|---|
| <code>tests/unit/test_orchestration_models.py</code> | Strictness, canonical bytes, immutable binding, execution mode, conflict matrix, proposal echo validation, gate scope. | Every one-field mutation is rejected; unknown/coerced fields fail. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>tests/unit/test_scheduler.py</code> | DAG acyclicity, unique keys, retry taxonomy/budget, cursor advancement, completion permutations. | Identical authoritative digest for all <code>n!</code> schedules with <code>2 &lt;= n &lt;= 5</code>, including all 24 four-panel orders. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>tests/unit/test_review.py</code> | Role conflict, isolated visibility, first-round completeness, synthesis prereq, dissent matrix. | Missing/reused/conflicted/inline identity blocks formal review. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>tests/unit/test_hook_contracts.py</code> | Hook stdin/stdout schema, status enum, redaction, idempotency, continuation caps. | Repeated/concurrent signals never exceed one per target. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>tests/schema/test_phase4_contracts.py</code> | Pydantic and independent <code>jsonschema</code> validation for all Phase 4 documents. | Native/fake fixtures validate independently; extra/coerced documents fail. [CITED: tests/schema/test_cross_language.py] |
| <code>tests/integration/test_orchestration_lifecycle.py</code> | Parent-only command path for prepare/start/seal/accept/reject/retry/cancel/supersede. | Canonical events, manifest bindings, rejection tree, and attempt count match the finite matrix. [CITED: src/arw/runtime.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>tests/integration/test_orchestration_replay.py</code> | Crash/restart/orphan recovery/cold replay. | Delete host/transcript/cache/status/projection state and reconstruct exact cursor/gates/outcomes from canonical files. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>tests/integration/test_orchestration_panels.py</code> | Four-seat blind panel and separate synthesis. | Visibility matrix, identities, nonces, paths, report retention, dissent, early-synthesis denial, and final BLOCKED cases. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>tests/integration/test_orchestration_hook_parity.py</code> | Trusted/disabled/untrusted/timeout/failed hook comparison. | Authority-normalized replay digests match; only allowlisted observation records differ. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>tests/integration/test_human_gates.py</code> | PASS/FAIL/BLOCKED, fresh evidence, waiver/correction/access/escalation/replacement/final approval. | Original verdict bytes unchanged; stale/blanket/overbroad decision rejects; completion remains illegal when required evidence is unresolved. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| <code>tests/evals/test_phase4_corpus.py</code> | 48 corpus manifest/digests, expected event sequence, redactions, replay digest, and parent-only sealed label isolation. | All development cases always run; sealed cases execute only in the parent harness and never enter worker roots/prompts/stage. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| <code>tests/staged/test_phase4_host_qualification.py</code> | Exact staged native host tuple. | Fresh-child dispatch, identity, result isolation, limits, cancellation mapping, hook trust modes, continuation, and no source import/private path leakage. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

### Phase Requirements → Test Map

| Req ID | Unit / schema test | Integration / replay test | Hook-parity test | Staged-host test |
|---|---|---|---|---|
| PKG-05 | <code>test_orchestration_models.py::test_execution_mode_is_required_and_inline_is_not_independence_eligible</code> | <code>test_orchestration_panels.py::test_run_status_records_native_assignment_injected_or_degraded_inline</code> | — | <code>test_phase4_host_qualification.py::test_observed_native_profile_or_assignment_injected_mode_matches_manifest</code>. [CITED: .planning/REQUIREMENTS.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| AGT-01 | <code>test_orchestration_models.py::test_assignment_binds_all_locked_fields_and_canonical_bytes</code> | <code>test_orchestration_lifecycle.py::test_parent_prepares_manifest_before_attempt_and_dispatch</code> | — | <code>test_phase4_host_qualification.py::test_staged_child_receives_only_assignment_declared_context</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-02 | <code>test_orchestration_models.py::test_every_proposal_binding_mutation_rejects</code> and independent schema fixture | <code>test_orchestration_lifecycle.py::test_worker_hook_adapter_and_direct_file_mutations_leave_authoritative_tree_unchanged</code> | <code>test_orchestration_hook_parity.py::test_hook_cannot_accept_or_write_proposal</code> | <code>test_phase4_host_qualification.py::test_host_result_is_only_direct_attempt_proposal_path</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-03 | <code>test_scheduler.py::test_frozen_cursor_is_permutation_invariant</code> and <code>test_scheduler.py::test_supersession_requires_new_assignment</code> | <code>test_orchestration_lifecycle.py::test_accept_reject_retry_cancel_and_late_stale_matrix</code>; <code>test_orchestration_replay.py::test_replay_matches_lifecycle_sequence</code> | — | <code>test_phase4_host_qualification.py::test_native_outcomes_are_buffered_then_committed_by_frozen_key</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-04 | <code>test_review.py::test_conflict_matrix_and_four_distinct_panel_seats</code> | <code>test_orchestration_panels.py::test_blind_panel_preserves_reports_dissent_and_separate_synthesis</code> | — | <code>test_phase4_host_qualification.py::test_four_fresh_host_ids_and_no_peer_or_label_access</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-05 | <code>test_scheduler.py::test_retry_taxonomy_attempt_cap_and_orphan_state</code> | <code>test_orchestration_replay.py::test_crash_marks_active_attempt_interrupted_and_requeues_once_or_blocks</code> | — | <code>test_phase4_host_qualification.py::test_timeout_cooperative_cancel_and_qualified_force_or_interrupted_outcome</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-06 | <code>test_hook_contracts.py::test_strict_observation_and_one_continuation_per_key</code> | <code>test_orchestration_lifecycle.py::test_parent_revalidates_hook_flagged_proposal</code> | <code>test_orchestration_hook_parity.py::test_all_hook_statuses_preserve_authority</code> | <code>test_phase4_host_qualification.py::test_trusted_hook_context_and_stop_request_are_observational</code>. [CITED: .planning/REQUIREMENTS.md] |
| AGT-07 | <code>test_hook_contracts.py::test_hook_status_cannot_be_used_as_authority_input</code> | <code>test_orchestration_hook_parity.py::test_disabled_and_bypassed_hooks_keep_runtime_mcp_gate_and_provenance_results</code> | Same paired test across trusted, disabled, untrusted, timeout, and failed modes. | <code>test_phase4_host_qualification.py::test_exact_host_hook_modes_match_authority_normalized_digest</code>. [CITED: .planning/REQUIREMENTS.md] |
| SCI-02 | <code>test_orchestration_models.py::test_gate_verdict_and_fresh_evidence_constraints</code> | <code>test_human_gates.py::test_fail_or_blocked_required_gate_prevents_complete</code>; replay asserts blocker legality. | Hook-enabled/disabled finalization parity case. | <code>test_phase4_host_qualification.py::test_host_cannot_complete_run_with_missing_required_gate_evidence</code>. [CITED: .planning/REQUIREMENTS.md] |
| SCI-03 | <code>test_orchestration_models.py::test_scoped_decision_requires_actor_hashes_scope_rationale_and_one_transition</code> | <code>test_human_gates.py::test_waiver_correction_access_and_approval_append_without_rewrite</code>; cold replay checks invalidation. | Hook request cannot substitute a human decision. | Human/host fixture confirms operator-visible decision request and no host-derived authorization. [CITED: .planning/REQUIREMENTS.md] |

### Roadmap Success Criteria → Test Map

| Success Criterion | Concrete evidence and tests |
|---|---|
| 1. Immutable assignment and schema-valid proposal; no direct mutation | <code>test_orchestration_models.py</code> mutation matrix; <code>test_phase4_contracts.py</code> independent schemas; <code>test_orchestration_lifecycle.py::test_worker_hook_adapter_and_direct_file_mutations_leave_authoritative_tree_unchanged</code>; staged proposal-inbox canary. [CITED: .planning/ROADMAP.md] |
| 2. Deterministic lifecycle and bounded recovery | Exhaustive scheduler permutations; integration failure matrix for accept/reject/retry/cancel/supersede; crash/orphan/cold-replay tests; host timeout/cancellation mapping canary. [CITED: .planning/ROADMAP.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| 3. Genuine independent review and honest execution provenance | Role/conflict/visibility unit matrix; blind-panel integration fixture with report/dissent/finding matrix; <code>PKG-05</code> status assertions; exact-host four-identity and isolation canary; formal review remains BLOCKED if canary fails. [CITED: .planning/ROADMAP.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| 4. Hooks useful but non-bypassable | Hook stdin/stdout unit golden tests; paired trusted/disabled/untrusted/timeout/failed integration runs; authority-normalized digest equality; exact staged hook trust/concurrency/continuation test. [CITED: .planning/ROADMAP.md; https://learn.chatgpt.com/docs/hooks.md] |
| 5. PASS/FAIL/BLOCKED and immutable accountable human decisions | Gate and scope schemas; integration finalization denial; waiver/correction/access/approval before/after ledger checks; replay invalidation check; staged UI/CLI visibility smoke plus human review of consequential decisions. [CITED: .planning/ROADMAP.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |

### Corpus and Replay Requirements

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Create immutable <code>tests/evals/phase4/corpus/v1/manifest.json</code> before adapter implementation. The declared corpus is 48 cases: 32 development cases and 16 sealed qualification cases.

| Case family | Count | Required coverage |
|---|---:|---|
| End-to-end routing | 6 | Experimental/non-experimental role activation and experiment execution disabled. |
| Sole-writer attacks | 6 | Worker/reviewer/synthesizer/hook/adapter/MCP/direct-file canonical-write attempts. |
| Assignment/proposal mutations | 6 | Schema/coercion/extra field; canonical bytes; digest/nonce/base/input/policy/identity mismatch; size; duplicate; traversal/symlink. |
| DAG ordering | 6 | Cycles, duplicate keys, missing required task, completion permutations, stable acceptance. |
| Lifecycle/recovery | 6 | Timeout, process failure, repairable/non-repairable failures, cancellation, late result, supersession, orphan restart. |
| Role conflicts/blind panel | 6 | Forbidden identity pairs, missing/reused role, peer/label access, early synthesis, degraded inline. |
| Synthesis/gate | 5 | Dissent, missing report, unresolved critical, waiver/correction/access/final approval, stale/over-broad decision. |
| Hook parity | 4 | Trusted/disabled/untrusted/timeout/failed behavior, duplicate/concurrent continuation, authority attack. |
| Restricted safety | 3 | Restricted/licensed/private/root/tool/network/experiment-execution denial. |

[CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Each case must freeze input bytes, role/policy/schema/protocol digests, initial ledger, fake/host observations, expected events, expected accepted hashes, terminal gate/status, authority-normalized replay digest, redaction expectations, and expert-review flag. The 16 sealed expected outcomes and contamination canaries must remain in a parent-only path outside worker roots, context manifests, prompts, staged plugin bytes, and role examples.

### Data/Invariant Test Boundaries

- [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Define <code>authoritative_tree()</code> as journal segments, immutable accepted manifests and pointers, canonical state/passport artifacts, and status projection inputs. Every rejected command must leave this tree byte-identical.
- [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Define <code>attempt_evidence_tree()</code> separately. It may gain an immutable raw proposal/observation receipt on rejection, but no accepted artifact/report/gate reference may point to it.
- [CITED: tests/integration/test_recovery_crash.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Inject IDs, clock, and failpoints; do not use wall-clock arrival times or random host output to decide an expected canonical result.
- [CITED: tests/integration/test_segmented_journal.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Replay tests must use a fresh process after deleting transcript, host cache/context, status output, graph/projection files, and hook logs. Retain only canonical files and restricted evidence referenced by canonical digest.
- [CITED: tests/integration/test_files_security.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Proposal-path tests must cover direct file, missing file, absolute path, parent traversal, outside-root path, symlink, nested redirection, duplicate path, and oversized result; resolving a path alone is insufficient.

### Sampling Rate

- **Per task commit:** Run the directly affected unit/schema tests plus the nearest integration test. [CITED: .planning/config.json]
- **Per wave merge:** Run <code>uv run pytest -q -m "not codex_host" tests/unit tests/schema tests/integration tests/staged tests/evals</code>. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- **Phase gate:** Full deterministic suite, all 48 corpus cases, no unexpected skips/xpasses, byte-stable schema regeneration, clean cold replay, and retained staged evidence. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- **Host admission gate:** Twelve host-dependent corpus canaries in three fresh homes for each exact tuple of Codex version, plugin stage digest, adapter digest, model/profile/permission metadata, and hook digest; any Critical failure keeps native formal-panel behavior BLOCKED. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- **Human release gate:** Two named domain experts review all 16 sealed qualification cases and human-review-required staged cases; a third preserves/adjudicates disagreement. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

### Wave 0 Gaps

- [ ] <code>tests/evals/phase4/corpus/v1/manifest.json</code> and 48 immutable case fixtures — contract/oracle before implementation. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- [ ] <code>tests/unit/test_orchestration_models.py</code>, <code>test_scheduler.py</code>, <code>test_review.py</code>, and <code>test_hook_contracts.py</code> — pure invariant coverage. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- [ ] <code>tests/schema/test_phase4_contracts.py</code> — independent validation before host integration. [CITED: tests/schema/test_cross_language.py] 
- [ ] <code>tests/integration/test_orchestration_lifecycle.py</code>, <code>test_orchestration_replay.py</code>, <code>test_orchestration_panels.py</code>, <code>test_orchestration_hook_parity.py</code>, and <code>test_human_gates.py</code>. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- [ ] <code>tests/staged/test_phase4_host_qualification.py</code> plus explicit environment guard that skips only when the human/CI host credential is deliberately absent; a skipped host test is never a qualification PASS. [ASSUMED]
- [ ] No new test framework install is needed; use existing <code>pytest</code>, <code>pydantic</code>, <code>jsonschema</code>, <code>itertools.permutations</code>, and ARW evidence/replay utilities. [CITED: pyproject.toml; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]

## Security Domain

[CITED: https://owasp.org/www-project-application-security-verification-standard/] OWASP ASVS is a verification framework whose category identifiers can change by version. The table applies relevant control areas to this local, single-writer orchestration phase; it is not a claim of complete ASVS certification.

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---|---|---|
| V1 Architecture, Design, and Threat Modeling | Yes | Explicit trust boundaries: parent writer, adapter transport, untrusted worker bytes, bounded MCP, observational hooks, and scoped human decisions. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; https://devguide.owasp.org/en/06-verification/01-guides/03-asvs/] |
| V2 Authentication | Conditional | Bind local operator identity/role to consequential human decisions; do not overstate authentication strength until the local configuration is defined and tested. [ASSUMED] |
| V3 Session Management | Conditional | Treat Codex session and transcript fields as observational; never use them as worker identity or authority. [CITED: https://learn.chatgpt.com/docs/hooks.md] |
| V4 Access Control | Yes | Parent-only canonical commands, role conflict matrix, per-assignment root/capability IDs, direct attempt paths, and no peer panel access. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| V5 Validation, Sanitization, and Encoding | Yes | Strict Pydantic, independently validated JSON Schema, canonical bytes, digest/size/path checks, and redacted bounded outputs. [CITED: src/arw/models.py; tests/schema/test_cross_language.py; https://devguide.owasp.org/en/06-verification/01-guides/03-asvs/] |
| V6 Stored Cryptography | Yes, for integrity not authentication | Use existing SHA-256/canonical event sealing and never invent cryptography or use an unverified hash as an identity/authentication claim. [CITED: src/arw/canonical.py; https://owasp.org/www-project-application-security-verification-standard/] |
| V7 Error Handling and Logging | Yes | Store content-free/redacted status telemetry and restricted raw attempt evidence by digest; deny with auditable taxonomy without exposing private corpus bytes. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| V12 Files and Resources | Yes | Reuse Phase 3 bounded read-only MCP and reject absolute/traversal/symlink/out-of-root proposal paths. [CITED: src/arw/files_mcp.py; tests/integration/test_files_security.py] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Worker/hook/adapter directly mutates canonical state | Elevation of privilege / Tampering | Actor-category authority, parent-only commands, journal/reducer replay checks, and authoritative-tree rejection tests. [CITED: src/arw/workflows.py; src/arw/runtime.py] |
| Malformed, stale, or substituted proposal enters accepted state | Tampering | Seal raw bytes, strict+independent schema validation, bind every echo field/digest/nonce/host ID/path, accept once at frozen cursor. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Reviewer accesses peer report or sealed answer label | Information disclosure | Isolated roots/capabilities/attempts/nonces, parent-only sealed corpus labels, and staged capability-access canaries. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Hook bypass or trust state changes enforcement | Elevation of privilege / Tampering | Runtime/MCP/gate enforcement independent of hook state; five-mode parity test. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; https://learn.chatgpt.com/docs/hooks.md] |
| Symlink/traversal/oversized result attacks | Tampering / Denial of service | Existing confinement pattern plus direct regular-file, one result root, byte cap, no-follow/symlink tests. [CITED: tests/integration/test_segmented_journal.py; tests/integration/test_files_security.py] |
| Retry/cancel/continuation loop consumes unbounded work | Denial of service | Finite concurrency, deadline, two attempts, 10-second cancellation grace policy, and one persisted continuation per target. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |
| Broad human decision launders a FAIL/BLOCKED result | Repudiation / Tampering | Exact evidence hashes, accountable actor/role, rationale/scope/conflict, one transition, immutable original verdict, human audit. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] |
| Untrusted source/manuscript text leaks through logs or external host | Information disclosure | Root/capability restriction, no transcript authority, redacted observation receipts, and staged evidence scans for private paths/content. [CITED: AGENTS.md; tests/staged/test_mcp_launcher.py; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] |

## Sources

### Primary (HIGH confidence)

- [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md] Locked Phase 4 semantics, scope, roles, lifecycle rules, hooks, gates, discretion, and deferrals.
- [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md] Selected adapter architecture, required modules, concurrency/lifecycle details, corpus/evaluation strategy, and host qualification gates.
- [CITED: src/arw/models.py; src/arw/runtime.py; src/arw/reducer.py; src/arw/manifests.py; src/arw/journal.py; src/arw/workflows.py; src/arw/status.py; src/arw/schema_registry.py; src/arw/cli.py] Existing authority, schema, manifest, replay, and command seams.
- [CITED: tests/unit/test_reducer.py; tests/integration/test_runtime_attempts.py; tests/integration/test_runtime_transitions.py; tests/integration/test_recovery.py; tests/integration/test_recovery_crash.py; tests/integration/test_files_security.py; tests/staged/test_skill_route.py; tests/staged/test_compatibility_probes.py] Existing test analogs and staged isolation conventions.
- [CITED: pyproject.toml; .codex-plugin/plugin.json; hooks/hooks.json; .mcp.json; skills/academic-research-workbench/SKILL.md] Installed runtime, package versions, plugin/hook/MCP baseline, and current assignment-injected fallback.
- [Official Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md) — direct-child depth/thread configuration, parent inheritance, and custom-agent locations.
- [Official Codex Hooks](https://learn.chatgpt.com/docs/hooks.md) — hook trust, concurrent matching command hooks, supported handlers, unstable transcript boundary, plugin hook packaging, and subagent hook fields.
- [Official Codex Build Plugins](https://learn.chatgpt.com/docs/build-plugins.md) — plugin hook path behavior.

### Secondary (MEDIUM confidence)

- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) and [OWASP Developer Guide overview](https://devguide.owasp.org/en/06-verification/01-guides/03-asvs/) — security verification categories used to frame the relevant controls.

### Tertiary (LOW confidence)

- None. Host-specific capabilities that are not locally proven are explicitly listed as [ASSUMED] and gated by staged qualification rather than treated as source-backed facts.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — existing locked Python dependencies and sole-writer architecture were inspected; no new package is proposed. [CITED: pyproject.toml; src/arw/runtime.py]
- Architecture: HIGH for kernel/manifest/reducer boundaries; MEDIUM for the proposed event decomposition because names are a discretion area; LOW only for native host API mapping until canaries pass. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
- Pitfalls: HIGH — they derive from locked failure cases, existing adversarial/recovery tests, and current official Codex hook/subagent documentation. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md; .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md; https://learn.chatgpt.com/docs/hooks.md]

**Research date:** 2026-07-14  
**Valid until:** 2026-08-13 for repository architecture; requalify native-host claims whenever the Codex CLI version, plugin stage digest, adapter digest, profile/model/permission configuration, or hook definition digest changes. [CITED: .planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-AI-SPEC.md]
