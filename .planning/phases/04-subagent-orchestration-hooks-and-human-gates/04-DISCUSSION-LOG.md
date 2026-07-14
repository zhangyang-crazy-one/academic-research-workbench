# Phase 4: Subagent Orchestration, Hooks, and Human Gates - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 04-subagent-orchestration-hooks-and-human-gates
**Areas discussed:** Role catalog and execution modes; assignment lifecycle, concurrency, retry, and cancellation; independent review and dissent synthesis; hooks and human gates

---

## Role Catalog and Execution Modes

### Role catalog organization

| Option | Description | Selected |
|--------|-------------|----------|
| Stable catalog with workflow-selected activation | Stable role IDs; activate only roles required by the workflow; experimental research requires an experiment designer. | Yes |
| Full role set for every run | Dispatch every research and review role for every task. | |
| Fully dynamic ad hoc roles | Let the parent invent roles per request. | |

**User's choice:** Stable catalog with workflow-selected activation.

### Execution-mode degradation

| Option | Description | Selected |
|--------|-------------|----------|
| Tiered degradation with independence fail-closed | Native profile, then assignment-injected subagent; inline only for non-independent support work. | Yes |
| Allow every role inline | Permit advisory inline review without independence claims. | |
| Block on any missing native role | No inline fallback for any work. | |

**User's choice:** Tiered degradation; a missing independent role blocks the run.

### Experiment design versus methodology review

| Option | Description | Selected |
|--------|-------------|----------|
| Separate first-class roles | Distinct experiment designer and methodology reviewer identities. | Yes |
| One methodology expert | One role designs and reviews methodology. | |
| Separate only for complex studies | Permit role merging for simple benchmarks. | |

**User's choice:** Always separate experiment design from methodology review.

### Worker role reuse

| Option | Description | Selected |
|--------|-------------|----------|
| Conflict-matrix constrained reuse | Share only non-conflicting support roles; prohibit producer/reviewer and other independence conflicts. | Yes |
| One worker per role | Never reuse a worker identity. | |
| Free reuse outside reviewer panel | Restrict only reviewer identities. | |

**User's choice:** Use a declared role-conflict matrix.

---

## Assignment Lifecycle, Concurrency, Retry, and Cancellation

### Assignment and retry identity

| Option | Description | Selected |
|--------|-------------|----------|
| Immutable assignment with multiple attempts | Retry with a new attempt ID; assignment changes require explicit supersession. | Yes |
| New assignment for every retry | Do not preserve retry lineage. | |
| Mutable assignment | Update task definition in place. | |

**User's choice:** Immutable assignment with attempt lineage.

### Concurrent acceptance order

| Option | Description | Selected |
|--------|-------------|----------|
| Parallel execution, deterministic acceptance | Freeze DAG/order; accept by topology and ordinal. | Yes |
| Completion-order acceptance | Accept whichever worker returns first. | |
| Fully serial execution | Do not run workers concurrently. | |

**User's choice:** Parallel work with deterministic parent acceptance.

### Retry policy

| Option | Description | Selected |
|--------|-------------|----------|
| Failure-classified bounded retry | One retry for transient or repairable envelope failures; other classes block or reject. | Yes |
| Human decision after every failure | Never retry automatically. | |
| Three retries for every failure | Retry all failures uniformly. | |

**User's choice:** At most two attempts and no automatic retry for policy, stale, superseded, cancelled, or scientific-disagreement outcomes.

### Cancellation and late results

| Option | Description | Selected |
|--------|-------------|----------|
| Two-stage cancellation with retained evidence | Cooperative deadline, forced termination, preserve late proposals as rejected stale. | Yes |
| Immediate kill and delete | Discard all terminated output. | |
| Ignore without termination | Let the worker continue but ignore its result. | |

**User's choice:** Two-stage cancellation and explicit interrupted-attempt recovery.

---

## Independent Review and Dissent Synthesis

### Base review panel

| Option | Description | Selected |
|--------|-------------|----------|
| Four independent perspectives plus synthesizer | Methodology, domain, perspective, and devil's advocate; separate editorial synthesis. | Yes |
| Two dynamic reviewers | Select two perspectives per task. | |
| Complete ARS role set every time | Always dispatch EIC, field analyst, and all review roles. | |

**User's choice:** Four required reviewers plus a separate synthesizer; specialists may be added.

### Post-blind reviewer interaction

| Option | Description | Selected |
|--------|-------------|----------|
| Blind first round, optional separate response round | Preserve reports; later rebuttal/cross-review uses new assignments. | Yes |
| Permanent mutual blinding | Only the synthesizer sees all reports. | |
| Share and edit original reports | Reviewers converge by modifying their first reports. | |

**User's choice:** Strict blind first reports followed by optional immutable response evidence.

### Missing reviewer policy

| Option | Description | Selected |
|--------|-------------|----------|
| Required base roles, declared optional specialists | All four base reports required; disclose every optional absence. | Yes |
| Three-of-four quorum | Synthesize after any three reports. | |
| Synthesize any available reports | Never block for missing reports. | |

**User's choice:** All four base reports are mandatory for formal independent review.

### Dissent handling

| Option | Description | Selected |
|--------|-------------|----------|
| Traceable finding matrix | Preserve consensus, majority, split, and DA-critical findings with evidence. | Yes |
| Majority vote | Relegate minority findings to an appendix. | |
| Synthesizer discretion | No mandatory item-level traceability. | |

**User's choice:** Finding matrix; unresolved critical or DA-critical findings block passage.

---

## Hooks and Human Gates

### Hook activation and status

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit trust with visible status | Report enabled, disabled, untrusted, timeout, and failure states; hooks remain optional adapters. | Yes |
| Hooks required before run | Refuse execution without trusted hooks. | |
| Silently optional hooks | Do not report whether hooks ran. | |

**User's choice:** Explicit operator trust and visible degradation without authority changes.

### Hook continuation behavior

| Option | Description | Selected |
|--------|-------------|----------|
| At most one directed continuation | SubagentStop/Stop may request one bounded completion pass. | Yes |
| Continue until valid | Permit repeated continuation requests. | |
| Warning only | Never request continuation. | |

**User's choice:** One directed continuation; parent validation remains authoritative.

### Mandatory human decisions

| Option | Description | Selected |
|--------|-------------|----------|
| Risk-based gates | Require humans for waivers, correction, blocker release, restricted access, escalation, retry exhaustion, critical dissent, and final completion. | Yes |
| Every transition | Require confirmation at every stage change. | |
| Final completion only | Defer all human interaction until finalization. | |

**User's choice:** Risk-based mandatory human gates; routine fresh intermediate PASS may auto-advance.

### Effect of waiver, correction, and approval

| Option | Description | Selected |
|--------|-------------|----------|
| Immutable verdict plus scoped decision | Append decisions without changing original PASS/FAIL/BLOCKED evidence. | Yes |
| Human overwrites verdict | Replace the machine outcome. | |
| Text-only waiver | Record a note with no transition effect. | |

**User's choice:** Append-only scoped decisions; waiver releases a precise blocker but never converts FAIL to PASS.

---

## the agent's Discretion

- Exact schema decomposition, IDs, storage paths, event names, and CLI command names.
- Bounded concurrency, timeout, and cancellation-grace defaults.
- Mapping of additional non-conflicting ARS support roles into the stable catalog.
- Hook command implementation and idempotent observation format.

## Deferred Ideas

- Controlled `code_runner` and `study_manager` experiment execution is deferred to Phase 6.
- Graph projection of assignments, reviews, findings, and gates is deferred to Phase 5.
- Complete scientific verifier methods and audit dossier generation are deferred to Phase 6.
- Full installed-host compatibility and representative release qualification are deferred to Phase 7.
