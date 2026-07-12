# Architecture Research

**Domain:** Codex-native, files-first, auditable academic research workbench plugin
**Researched:** 2026-07-12
**Confidence:** HIGH for local runtime/file-base boundaries; MEDIUM-HIGH for Codex packaging and subagent integration because the official plugin surface is current but still evolving

## Executive Recommendation

Build the v1.0 workbench as a **local modular monolith with two processes and one authority**:

1. A short-lived `workbench` runtime CLI is the only writer of canonical run state.
2. A long-lived `file-base` stdio MCP server owns bounded file retrieval and disposable query projections.
3. Codex owns conversation flow and subagent spawning; the parent Codex thread is the only actor allowed to ask the runtime to accept worker output.
4. Hooks observe, inject context, and block obvious misuse, but never define provenance or scientific truth.
5. Every graph node, verification verdict, and resumable state must be reproducible from authoritative files after deleting all caches.

Do not make the runtime a daemon, do not put canonical state in SQLite, and do not let subagents, hooks, or MCP tools edit run ledgers directly. The filesystem is the durable integration bus; JSON Schemas, hashes, locks, and deterministic reducers make it safe.

## Standard Architecture

### System Overview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Codex host                                                                  │
│                                                                              │
│  Plugin skill/router ──► Parent orchestrator ──► Codex subagent threads     │
│         │                    │       ▲                │                      │
│         │                    │       │ result ref     │ immutable assignment │
│         │                    ▼       │                ▼                      │
│         │              workbench runtime CLI   results/<attempt>.json       │
│         │                 (SOLE WRITER)                                     │
│         │                    │                                               │
│         └── lifecycle hooks ─┤ context / guard / continuation only           │
├──────────────────────────────┼───────────────────────────────────────────────┤
│ Authoritative run store      ▼                                               │
│                                                                              │
│  run_manifest.json   ledger/events.jsonl   manifests/artifacts/*.json        │
│  assignments/*.json  results/*.json        passports/*.json                 │
│  evidence/<gate-run>/...     paper/ experiment/ reviews/ exports/           │
│                                                                              │
│  state.json = atomic, rebuildable snapshot; never independent authority      │
├─────────────────────────────────────┬────────────────────────────────────────┤
│ Projection boundary                 │ Query boundary                         │
│                                     │                                        │
│  runtime `sync-index`               │ file-base MCP (read-only to agents)     │
│      │                              │  list/read/search/outline/context       │
│      ▼                              │  graph relationship queries             │
│  manifest projector                 │                                        │
│      ├── files.sqlite               │ bounded results + source hashes         │
│      └── research-graph.sqlite      │                                        │
│            disposable caches under plugin data / configured cache root       │
└──────────────────────────────────────────────────────────────────────────────┘
```

The process split is deliberate:

- The runtime is short-lived and side-effect controlled. A crash cannot leave an in-memory orchestrator as the only holder of state.
- The MCP server is long-lived because indexes and query connections benefit from reuse.
- The filesystem boundary makes both independently testable and prevents the query service from becoming a second workflow engine.

### Component Responsibilities

| Component | Owns | Must Not Own | Typical Implementation |
|-----------|------|--------------|------------------------|
| Codex plugin bundle | Installation metadata, root skill, MCP wiring, trusted hook definitions, launchers, notices | Run state, caches, user research artifacts | `.codex-plugin/plugin.json`, `skills/`, `.mcp.json`, `hooks/`, packaged launchers |
| ARS skill/router | Workflow semantics, stage rules, role prompts, gate policy, handoff vocabulary | Durable execution, direct state mutation | Materialized/pinned ARS source behind one root `SKILL.md` |
| Parent orchestrator | User interaction, branch decisions, subagent dispatch, deterministic merge order | Direct edits to ledger/manifests; hidden state required for resume | Codex parent thread calling runtime commands |
| Runtime kernel | Run identity, state machine, locks, command idempotency, ledger append, artifact acceptance, checkpoints, resume, gate/finalize policy | File search UI, semantic graph query, LLM reasoning | Python CLI with pure reducer + filesystem transaction adapter |
| Schema registry | Wire contracts and compatibility rules | Business decisions hidden in code | JSON Schema Draft 2020-12 plus cross-record validators |
| Assignment manager | Immutable worker input snapshots and attempt lifecycle | Agent spawning | Runtime submodule; one assignment, many attempts |
| Codex subagents | Scoped research, experiment, writing, or review work | Canonical state writes, accepting their own output, seeing blind peers before synthesis | Built-in or custom agents receiving an assignment ID/path |
| Hook pack | Context hydration, obvious tool denial, telemetry proposals, incomplete-work continuation | Provenance, sole security enforcement, canonical acceptance | Trusted command hooks that invoke read-only/runtime-safe commands |
| Files-first indexer | Allowed-root crawl, file metadata, text extraction cache, FTS, outline cache | Scientific provenance and workflow transitions | Patched pinned C file-base binary; `files.sqlite` projection |
| Research graph projector | Deterministic manifest-to-node/edge mapping, projection cursor, rebuild receipt | Inference from prose, graph-authored provenance | Runtime-invoked projector writing `research-graph.sqlite` |
| Read-only MCP query facade | Bounded file and graph queries | Canonical mutations, arbitrary filesystem access | JSON-RPC 2.0 over stdio; only query tools advertised |
| Verification runner | Executes validators, captures command/effect evidence, validates verdicts | Silent waivers, reusing stale verdicts | Runtime submodule writing immutable evidence bundles |

## Authority and Source-of-Truth Rules

### Authority Hierarchy

Use this order whenever records disagree:

1. **Pinned input bytes and immutable accepted artifacts**, identified by SHA-256.
2. **Validated artifact manifests**, which state what those bytes mean and how they were produced.
3. **Append-only ledger events**, which record accepted transitions, decisions, waivers, and manifest references.
4. **Immutable Material Passport checkpoint versions**, which summarize a coherent handoff boundary and retain existing ARS append-only fields.
5. **Derived snapshots and projections** such as `state.json`, file indexes, graph databases, dashboards, and MCP responses.
6. **Observational data** such as hooks, transcripts, notifications, and logs not accepted into an evidence manifest.

An artifact existing on disk is not enough to make it canonical. It becomes canonical only when a valid immutable manifest is referenced by a committed ledger event.

### Record Classification

| Record | Authority | Mutation Rule | Recovery Rule |
|--------|-----------|---------------|---------------|
| `run_manifest.json` | Canonical run identity and creation configuration | Create once; never rewrite | Missing/invalid means the run is invalid, not guessed |
| `ledger/events.jsonl` | Canonical workflow history | Append under exclusive run lock; sequence and hash chained | Validate prefix; quarantine a partial/corrupt tail before repair |
| `manifests/artifacts/<id>.json` | Canonical artifact provenance | Immutable, content-addressed, schema-valid | Re-hash referenced bytes; mismatch marks tampering/staleness |
| `passports/passport.<revision>.json` | Canonical checkpoint handoff | New immutable version per checkpoint; retain ARS append-only ledgers | Resume only from a validated checkpoint hash |
| `passport.json` | Convenience pointer/copy to latest passport | Atomic replacement | Rebuild by selecting latest accepted passport event |
| `assignments/<assignment_id>.json` | Canonical worker contract | Immutable | Retry creates a new attempt, not a rewritten assignment |
| `results/<attempt_id>.json` | Immutable worker proposal | Worker may create once in its result inbox | Not canonical until `accept-result` commits its manifest |
| `state.json` | Derived current-state snapshot and CAS hint | Atomic replacement after ledger commit | Delete and replay ledger + manifests |
| `evidence/<gate_run_id>/` | Canonical only when its receipt manifest is accepted | Immutable bundle | Re-run gate if subject or verifier hash changed |
| `files.sqlite` | Disposable file catalog/search projection | Projector-owned | Delete and re-index allowed roots |
| `research-graph.sqlite` | Disposable semantic projection | Projector-owned | Delete and rebuild from accepted manifests/ledger |
| Hook output / transcript | Observational | Append externally as supplied | Never sufficient to pass a gate |

### Required Event Envelope

Every ledger event should carry at least:

```json
{
  "schema_version": "workbench.event.v1",
  "run_id": "run_...",
  "seq": 42,
  "event_id": "evt_...",
  "command_id": "cmd_...",
  "expected_revision": 41,
  "event_type": "artifact.accepted",
  "occurred_at": "2026-07-12T12:34:56.789Z",
  "actor": {"kind": "parent_orchestrator", "id": "..."},
  "payload": {"artifact_manifest": "manifests/artifacts/art_....json"},
  "prev_event_sha256": "...",
  "event_sha256": "..."
}
```

The reducer must be a pure function from `(run_manifest, valid events, valid referenced manifests)` to `state.json`. A state-machine rule that cannot be reproduced by this reducer is hidden state and should not ship.

## Command and Tool Boundaries

### Runtime CLI: Canonical Mutation API

Only the parent orchestrator invokes canonical mutation commands. Commands return machine-readable JSON and require `run_id`, `command_id`, and `expected_revision` for mutations.

| Command | Purpose | Canonical Write |
|---------|---------|-----------------|
| `init` | Create run identity, initial ledger, allowed roots, and policy snapshot | Yes |
| `status` | Replay/validate and report current state and next legal actions | No, except optional snapshot refresh |
| `transition` | Commit one legal state-machine transition | Yes |
| `checkpoint` | Seal current artifacts and emit immutable passport version | Yes |
| `resume` | Lock, verify, and consume one checkpoint/boundary hash | Yes |
| `assign` | Create immutable assignment and first attempt record | Yes |
| `accept-result` | Validate result envelope, input hash, attempt freshness, and artifact hashes; then accept | Yes |
| `record-artifact` | Register a parent-produced immutable artifact | Yes |
| `record-experiment` | Register command, environment, dataset, logs, outputs, and result manifests | Yes |
| `run-gate` | Execute verifier and produce an evidence receipt + verdict | Yes |
| `waive-gate` | Record explicit human waiver, scope, reason, and subject hash | Yes |
| `finalize` | Refuse unless all mandatory gates and deliverables are fresh and resolved | Yes |
| `verify-ledger` | Validate sequence, hash chain, schemas, and referenced bytes | No |
| `rebuild-state` | Replay canonical records into a fresh `state.json` | Derived only |
| `sync-index` | Ask projector to catch up to a specific ledger tip | Projection only |

Do not expose these commands as general MCP tools. They are local capability boundaries under parent control, and their narrow CLI makes tests, permissions, and recovery behavior explicit.

### Files-First MCP: Read API

The agent-facing MCP advertises only bounded read/query tools:

| Tool | Contract |
|------|----------|
| `list_files` | Page through allowed-root-relative metadata; filters are declarative and bounded |
| `read_file` | Read a byte or line window, never an unbounded whole corpus; return current SHA and indexed SHA |
| `search_files` | Search indexed content with path/type filters, pagination, snippets, and total/truncation metadata |
| `get_file_outline` | Return cached headings/sections/entries with source and extractor hashes |
| `get_file_context` | Return a bounded neighborhood around a match or outline node |
| `query_research_graph` | Execute allowlisted query shapes or a constrained graph DSL with row/depth/time caps |
| `trace_evidence` | Follow claim/number/figure/review/gate relationships to canonical paths and hashes |
| `projection_status` | Report schema version, indexed ledger tip, staleness, and last rebuild receipt |

Projector mutations (`crawl`, `extract`, `sync-manifests`, `rebuild-graph`) should be file-base administrative CLI commands invoked by `workbench sync-index`, not tools visible to research subagents. If an implementation temporarily exposes them over MCP, enable them only for the parent profile and disable them for all worker profiles.

### Why the Existing MCP Must Be Extended, Not Merely Renamed

The pinned `codebase-memory-mcp` implementation is a single-threaded JSON-RPC dispatcher around a C pipeline and SQLite store. Its current durable schema contains `projects`, `file_hashes`, generic `nodes`, `edges`, and node FTS. It does **not** have a first-class file-content table or the required files-first tools. Existing source reads occur as helpers inside graph-oriented `get_code_snippet` and `search_code` handlers.

The Paper4Master patch usefully admits generic text and directly text-bearing PDFs as structure-only `File` nodes, skips AST passes for those files, and renames the server. That is an ingestion foothold, not a files-first architecture. Add separate file catalog/content/outline storage and explicit read tools. Treat the patch's direct-PDF-text heuristic as an admission signal only; extracted text must record extractor name/version, source PDF hash, and extraction status.

## Recommended Project Structure

```text
academic-research-workbench/
├── .codex-plugin/
│   └── plugin.json                 # Required package entry point only
├── .mcp.json                       # file-base stdio server wiring
├── skills/
│   └── academic-research-workbench/
│       ├── SKILL.md                # Single Codex-visible router
│       ├── references/             # Runtime/operator guidance
│       └── agents/                 # Role prompts; not assumed auto-discovered
├── hooks/
│   ├── hooks.json                  # Trusted lifecycle declarations
│   └── *.py                        # Thin adapters; no direct canonical writes
├── agent-profiles/
│   └── *.toml                      # Source templates for optional .codex/agents install
├── bin/
│   ├── workbench                   # Stable runtime launcher
│   └── file-base-mcp               # Stable MCP launcher
├── src/workbench/
│   ├── cli.py
│   ├── kernel/                     # Commands, reducer, legal transitions
│   ├── ledger/                     # Locking, append, hash chain, replay
│   ├── artifacts/                  # Hashing, immutable manifests, passports
│   ├── assignments/                # Assignment/attempt/result acceptance
│   ├── gates/                      # Verifier execution and evidence receipts
│   ├── projector/                  # Canonical files -> graph records
│   └── security/                   # Root capabilities, path/open policy
├── schemas/
│   ├── runtime/                    # run, event, state, assignment, result
│   ├── research/                   # source, claim, dataset, experiment, review
│   └── evidence/                   # command, receipt, verdict, waiver
├── native/file-base/
│   ├── upstream.lock.json          # Exact commit, tree hash, license
│   ├── patches/                    # Ordered, hashed local patches
│   ├── build.py                    # Clean-tree reproducible build
│   └── NOTICE.md
├── vendor/academic-research-suite/
│   ├── upstream.lock.json
│   ├── manifest.json
│   └── ...                         # Materialized, pinned ARS source
├── tests/
│   ├── contracts/
│   ├── recovery/
│   ├── security/
│   ├── projection/
│   └── e2e/evidence/               # Inspectable fixture run outputs
└── THIRD_PARTY_NOTICES.md
```

### Structure Rationale

- **Plugin root:** Mirrors the official Codex plugin layout: only `plugin.json` lives in `.codex-plugin`; skills, hooks, `.mcp.json`, and assets stay at root.
- **`agent-profiles/`:** Official Codex custom agents are discovered from `~/.codex/agents/` or project `.codex/agents/`, not listed as a native plugin component. Keep canonical role behavior in assignment contracts and treat custom TOML profiles as an optional installation adapter.
- **`src/workbench/kernel/`:** Keeps state-machine decisions independent from filesystem and Codex APIs, enabling deterministic replay tests.
- **`native/file-base/`:** Makes the pinned upstream, ordered patches, clean build, and notices reviewable. Do not mutate an ignored upstream checkout in place as the current Paper4Master build script does.
- **`schemas/`:** Workbench runtime schemas are separate from vendored ARS schemas. Adapt them explicitly; never silently edit vendored contracts.
- **`tests/e2e/evidence/`:** The product promise is auditable execution, so verification fixtures must include ledger, manifests, failure artifacts, and rebuild receipts, not just pass/fail output.

## Architectural Patterns

### Pattern 1: Command Journal + Pure Reducer

**What:** Every state-changing command validates against the current revision, stages immutable files, appends one committed event, and regenerates the snapshot by reduction.

**When to use:** All run lifecycle changes.

**Trade-offs:** More explicit records and validation work than a mutable database; dramatically better crash recovery, auditability, and testability.

```python
def execute(command, run):
    with exclusive_run_lock(run):
        history = verify_and_read_ledger(run)
        state = reduce_run(run.manifest, history)
        prior = find_by_command_id(history, command.command_id)
        if prior:
            return prior.outcome                 # idempotent retry
        require(command.expected_revision == state.revision)
        decision = validate_command(state, command)
        manifests = stage_immutable_outputs(decision)
        event = append_and_fsync_event(history.tip, command, manifests)
        atomic_write_state(reduce_run(run.manifest, history + [event]))
        return event.outcome
```

The safe commit order is: write artifact bytes to a temporary file, fsync, rename; write and fsync immutable manifests; append and fsync the referencing event; atomically replace `state.json`. A crash before event append leaves an unreferenced orphan that recovery can quarantine. A crash after event append can always rebuild `state.json`.

### Pattern 2: Parent-Writer / Worker-Proposal

**What:** Workers receive immutable assignments and can only emit result proposals into a result inbox. The parent validates and accepts them in deterministic task order.

**When to use:** Every delegated research, experiment, writing, and review task.

**Trade-offs:** Requires an explicit accept step; prevents concurrent workers from corrupting canonical files or silently overwriting one another.

Minimum assignment fields:

- assignment and attempt IDs;
- run/stage/task type;
- immutable input artifact references and hashes;
- allowed read roots and writable scratch/result path;
- required output schema and maximum size;
- policy snapshot and mandatory evidence requirements;
- blind-review group and unavailable peer outputs;
- deadline/cancellation metadata.

Minimum result fields:

- assignment/attempt IDs and exact input hash;
- status: `completed`, `partial`, `blocked`, or `failed`;
- produced artifact paths, hashes, media types, and schema versions;
- claims/evidence references introduced;
- tool/experiment evidence references where required;
- unresolved issues and requested next action;
- provenance mode (`executed`, `reported`, `simulated`) in one unambiguous location.

Never accept a transcript, final chat message, or hook output as the result envelope.

### Pattern 3: Rebuildable Projection with a Watermark

**What:** The projector consumes only validated canonical records up to a ledger tip hash and writes disposable indexes plus a projection receipt.

**When to use:** File catalog, FTS, outlines, and research semantic graph.

**Trade-offs:** Queries may temporarily be stale; staleness is visible and recovery is deletion + rebuild rather than forensic database repair.

Each projection receipt should record:

- projector and schema versions;
- allowed-root identity;
- run ID and indexed ledger sequence/tip hash;
- source manifest count and aggregate hash;
- row/node/edge counts;
- skipped records with reasons;
- start/end timestamps and result status.

Stable graph IDs should be derived from canonical identity, not SQLite row IDs. Use a namespaced key such as `(run_id, entity_type, canonical_artifact_path, content_sha256, local_entity_key)`. Supersession creates a new node and a `SUPERSEDES` edge; it does not rewrite history.

### Pattern 4: Evidence Receipt, Not Boolean Verification

**What:** A gate verdict points to a complete immutable evidence bundle and the exact subject/verifier hashes.

**When to use:** Citation, claim, temporal, statistical, experiment, figure, review, format, and finalization gates.

**Trade-offs:** More disk usage; makes PASS independently inspectable and automatically stale when inputs change.

```text
evidence/<gate_run_id>/
├── request.json             # gate, subject manifests, policy
├── command.json             # executable, args, cwd, timeout
├── environment.json         # redacted environment + lock/tool versions
├── stdout.log
├── stderr.log
├── result.json              # machine-readable findings
├── artifacts.json           # all produced files and hashes
├── verdict.json             # PASS/FAIL/BLOCKED + counts
└── receipt.json             # hashes the complete bundle
```

A verdict is fresh only if the receipt validates, every subject hash still matches, the policy version matches, and the verifier version is allowed. A waiver is a separate ledger event; it never edits the verdict.

### Pattern 5: Capability-Based File Access

**What:** `init` resolves a small set of allowed roots into immutable root capabilities. MCP and runtime operations receive `(root_id, relative_path)`, not arbitrary absolute paths.

**When to use:** Every read, extraction, search, and artifact write.

**Trade-offs:** Callers must select a root explicitly; eliminates ambient filesystem authority and makes audit logs meaningful.

The existing `realpath` containment check is a useful baseline but leaves a check/open race. Prefer descriptor-relative traversal with no-follow semantics (`openat2` with `RESOLVE_BENEATH`/`NO_MAGICLINKS` where available; conservative `openat` segment traversal otherwise). After opening, verify file type and limits with `fstat` before reading.

## Data Flow

### Run and Delegation Flow

```text
User request
  ↓
Plugin skill/router ── chooses ARS workflow/mode
  ↓
Parent: `workbench init|status`
  ↓
Runtime validates schemas/state and returns legal next actions
  ↓
Parent: `workbench assign`
  ↓
Immutable assignment + input hashes
  ↓
Codex spawns narrow read-only subagent
  ↓
Worker writes result proposal + artifacts to assigned inbox/scratch
  ↓
Parent: `workbench accept-result`
  ↓
Runtime validates freshness/schema/hashes/policy
  ↓
Artifact manifests + ledger event + rebuilt state snapshot
  ↓
`workbench sync-index` ──► disposable files/graph projections
```

### Files-First Query Flow

```text
Agent MCP query
  ↓
Tool schema validation and per-tool limits
  ↓
Root capability + relative path resolution
  ↓
files.sqlite metadata/FTS/outline lookup
  ↓
Optional descriptor-safe bounded source read
  ↓
Response: rows/snippets + current SHA + indexed SHA + truncation/staleness
```

Full-text search must preserve a non-FTS exact/substring path for identifiers, citation keys, LaTeX commands, and CJK validation. FTS tokenization is an optimization, not the only discovery mechanism.

### Gate and Finalization Flow

```text
Requested transition
  ↓
Runtime computes required gates from state + policy
  ↓
Verification runner executes each gate and captures evidence bundle
  ↓
Runtime validates receipt/verdict/subject hashes
  ├── PASS and fresh ──► append gate.passed ──► transition eligible
  ├── FAIL ────────────► append gate.failed ──► transition blocked
  ├── inaccessible ────► human-review item ──► blocked_human_review
  └── explicit waiver ─► append gate.waived with scoped rationale
```

### Graph Rebuild Flow

```text
Delete projection databases
  ↓
Validate run manifest + ledger hash chain
  ↓
Replay accepted artifact/passport/evidence manifests
  ↓
Build file catalog/extractions
  ↓
Project deterministic research nodes/edges
  ↓
Write projection receipt at ledger tip H
  ↓
Run fixed equivalence queries against golden answers
```

The graph projector parses validated JSON/YAML manifests and structured paper artifacts. It must not infer canonical claims, gates, or stage state from prose. Prose may be indexed for retrieval, but only manifest-declared entities receive authoritative research relationships.

## Failure and Recovery Semantics

| Failure | Required Behavior | Recovery Evidence |
|---------|-------------------|-------------------|
| Duplicate command after timeout | Return prior outcome by `command_id`; do not append twice | Original event ID and revision |
| Stale parent revision | Reject with current revision and legal next actions | No mutation |
| Lock contention | Fail fast/retry with bounded backoff; never write unlocked | Contention diagnostic only |
| Crash while writing artifact | Temporary/orphan file is not canonical | Recovery scan quarantines unreferenced file |
| Crash after ledger append, before snapshot | Ledger remains authoritative | `rebuild-state` reproduces snapshot |
| Partial/corrupt ledger tail | Stop at last valid hash-chained event; preserve bad bytes; require repair command | Archived corrupt tail + recovery event |
| Manual mutation of accepted artifact | Mark dependent manifests/gates/projections stale; never update expected hash silently | Integrity finding and new artifact version if accepted |
| Missing/invalid worker result | Attempt remains incomplete or failed | Retry with new attempt ID and same assignment hash |
| Late result from superseded attempt | Store as historical proposal; refuse canonical acceptance | `result.rejected_stale` event if parent records it |
| Subagent or parent interruption | No transition without accepted result; resume from state reducer | Open assignment and next action in `status` |
| Hook missing, untrusted, timeout, or skipped | Core runtime and MCP enforcement still hold | Hook degradation reported, not a gate bypass |
| MCP/index crash | Restart server; queries report unavailable/stale | Re-index/rebuild receipt |
| Graph schema migration failure | Keep canonical run untouched; delete/rebuild new projection | Failed migration log + successful rebuild receipt |
| Gate verifier crash/timeout | Verdict is `BLOCKED`, never PASS | stdout/stderr/timeout metadata |
| Paid or inaccessible source | Create human-review item; never claim semantic verification | Access-state evidence and pending decision |
| Concurrent checkpoint resume | Exclusive passport/run lock covers read-check-append; second consumer rejected | Existing consume event/hash |

Resume must not depend on conversation memory. It should verify the requested boundary/passport hash, acquire the run lock, ensure no later consumption event exists, append a consume/resume event, and return the recovered stage, exact inputs, unresolved gates, and next legal actions.

## Security Boundaries

### Trust Zones

| Zone | Trust Level | Rules |
|------|-------------|-------|
| Plugin install root | Trusted code, read-only at runtime | Hash/version inventory; no user artifacts or mutable cache |
| `PLUGIN_DATA` / configured cache root | Mutable but non-authoritative | Projections and operational cache only; safe to delete |
| Canonical run directory | High-integrity user data | Runtime-only canonical writes; locks, schemas, hashes, immutable versions |
| Worker scratch/result inbox | Untrusted proposal zone | Scoped writes; size/type/path limits; validate before acceptance |
| Research corpus/manuscripts/PDF text | Untrusted content | Never interpret embedded instructions as policy or tool authorization |
| Network and external APIs | Separate capability | Explicit configuration/consent; record provider and content class sent |

### Mandatory Controls

- Default subagents to read-only sandbox. Experiment workers write only to assigned scratch and never to canonical directories.
- Preserve Codex parent permission mode: official behavior says subagents inherit the parent turn's live permission choices. Runtime authorization must therefore remain stricter than agent profile text.
- Enforce allowed roots inside the MCP/runtime, not only with `PreToolUse`. Official Codex documentation explicitly notes that `PreToolUse` does not intercept every equivalent tool path.
- Bound bytes, lines, result rows, graph depth, query complexity, extraction time, PDF pages, and total response size.
- Deny device files, sockets, FIFOs, escaping symlinks/junctions, credentials, private keys, browser/session databases, and configured ignore patterns.
- Keep local indexing network-free. Update checks and source connectors are separately enabled and visible.
- Redact secrets from environment evidence while recording an allowlisted environment fingerprint and dependency-lock hashes.
- Make plugin hooks opt-in/trusted. Codex hashes non-managed hook definitions and skips changed/untrusted hooks until reviewed.
- Do not treat `PostToolUse` as rollback: the tool has already executed. Use it for feedback/telemetry; use runtime-controlled executors where evidence and containment are mandatory.
- Set hook timeouts narrowly. Codex's default is 600 seconds, which is too high for policy hooks; use approximately 5–30 seconds depending on event.

## Codex Integration Decisions

### Plugin Bundle

Follow the documented plugin root shape. `.codex-plugin/plugin.json` identifies the plugin and points to `./skills/`, `./.mcp.json`, and `./hooks/hooks.json`. Keep only the manifest inside `.codex-plugin/`. Mutable data belongs under the run root or `PLUGIN_DATA`, never beside installed plugin code.

The official docs explicitly define `PLUGIN_ROOT`/`PLUGIN_DATA` for hook commands but do not equally establish variable interpolation inside `.mcp.json` command fields. Make MCP launcher resolution a Phase 0 install test. Prefer a stable installed executable name; do not assume an undocumented relative working directory.

### Subagents

Use direct children only (`max_depth = 1`) and cap parallelism. The parent owns the DAG; workers cannot spawn research descendants in v1. Independent reviewers receive the same manuscript/rubric snapshot but not one another's outputs. The synthesizer starts only after all required independent result envelopes are accepted.

Because current Codex docs discover custom agents from user/project `.codex/agents/`, keep the workflow correct with built-in subagents plus assignment-injected role instructions. Offer an explicit `configure-codex-agents` adapter that materializes reviewed TOML profiles into project scope; do not make canonical execution depend on that installation succeeding.

### Hooks

| Event | Recommended Use | Explicit Non-Responsibility |
|-------|-----------------|-----------------------------|
| `SessionStart` | Read `status`, verify selected run, inject run/passport summary | No implicit resume or state write |
| `SubagentStart` | Inject assignment ID, input hash, output path/schema, policy reminder | Cannot prevent start via `continue: false`; sandbox/runtime still enforce |
| `PreToolUse` | Deny obvious forbidden paths/commands/MCP mutations | Not complete mediation |
| `PostToolUse` | Submit lightweight observation proposal and flag suspicious output | Cannot undo the completed tool call |
| `SubagentStop` | Require one more pass if envelope is missing/malformed | Does not accept the result |
| `Stop` | Continue when explicitly requested deliverables or mandatory gates remain | Does not replace `finalize` refusal |

Matching hooks can run concurrently, so hook ordering must never be semantically required. Any hook that records an observation does so through an idempotent runtime command protected by the run lock.

## Scaling Considerations

The v1 target is a local headless workbench, so scale by run/artifact volume rather than user count.

| Scale | Architecture Adjustment |
|-------|-------------------------|
| 1–100 runs / <100k files | One local runtime CLI, one stdio MCP process, SQLite projections, per-run lock |
| 100–10k runs or multi-million-file corpora | Shard caches by workspace/root ID, incremental extraction, sealed ledger segments, background projector with explicit watermark |
| Team-shared or remote execution | Keep the same contracts; add an authenticated command service and object store, lease-based single writer, tenant-isolated indexes. Do not promote current SQLite caches to authority |

### Scaling Priorities

1. **First bottleneck:** extraction and full-text indexing, especially PDF/CJK/LaTeX content. Fix with content-hash reuse, incremental indexing, extraction workers, and bounded result APIs.
2. **Second bottleneck:** ledger replay across very long runs. Fix with verified checkpoint snapshots and sealed segments while preserving replay from genesis.
3. **Third bottleneck:** graph fan-out and broad queries. Fix with allowlisted query templates, depth/row/time budgets, and projection-specific indexes.

## Anti-Patterns

### Graph as Workflow Database

**What people do:** Update stage/gate/provenance nodes directly and then export manifests.

**Why it's wrong:** Graph mutation order, migration, or cache loss changes scientific history.

**Do this instead:** Project graph state from accepted ledger/manifests and prove delete/rebuild equivalence.

### Shared Writable Run Directory for Agents

**What people do:** Let every specialist edit `paper/`, `passport.json`, and `state.json` directly.

**Why it's wrong:** Races, accidental overwrites, non-deterministic synthesis, and unverifiable authorship.

**Do this instead:** Immutable assignments, per-attempt scratch/inbox, parent-mediated acceptance.

### Hooks as Security or Provenance Core

**What people do:** Assume `PreToolUse` sees every side effect and `PostToolUse` proves what happened.

**Why it's wrong:** Codex documents incomplete interception; matching hooks are concurrent; post hooks run after effects.

**Do this instead:** Enforce in runtime/MCP and use hooks as defense in depth.

### Mutable Passport Singleton

**What people do:** Repeatedly rewrite one large Material Passport file in place.

**Why it's wrong:** Crash windows and concurrent resume make historical boundaries ambiguous.

**Do this instead:** Immutable passport revisions plus an atomic latest pointer and append-only boundary/consume events.

### Auto-Accepting Worker Chat Output

**What people do:** Parse the last assistant message and infer completion.

**Why it's wrong:** Missing hashes, stale inputs, malformed handoffs, and prompt text can masquerade as results.

**Do this instead:** Require a schema-valid result envelope and explicit `accept-result`.

### In-Place Upstream Patching

**What people do:** Detect patch markers in an ignored checkout, apply if absent, then copy a binary.

**Why it's wrong:** The build depends on unknown dirty state and cannot prove exact source/patch provenance.

**Do this instead:** Verify pinned commit/tree hash, copy/export to a clean temporary tree, apply ordered hashed patches with `--check`, build, and emit an SBOM/build manifest.

### One SQLite File for Every Concern

**What people do:** Add file content, graph, workflow state, and evidence verdicts to the existing graph DB.

**Why it's wrong:** A projection migration or corruption now threatens retrieval availability and tempts code to query mutable state as authority.

**Do this instead:** Keep canonical state as files and prefer separate `files.sqlite` and `research-graph.sqlite` projections, even if one MCP process serves both.

## Build Order and Dependency Gates

1. **Contract and reproducible package baseline**
   - Materialize/pin ARS and file-base source, patches, licenses, and notices.
   - Define run/event/state/assignment/result/artifact/evidence schemas and compatibility policy.
   - Scaffold valid plugin, stable launchers, and one install/start smoke test.
   - Exit gate: a fixture can initialize, append, stop, replay, and resume without conversation memory.

2. **Durable runtime kernel**
   - Implement locks, idempotent commands, journal append, reducer, immutable manifests, passport revisions, and recovery tooling.
   - Exit gate: crash points, duplicate command, stale revision, double resume, and lock contention are proven by tests with evidence artifacts.

3. **Files-first MCP foundation** — may run in parallel with step 2 after schemas/root capabilities freeze
   - Add first-class files/extractions/outlines and bounded read/search tools.
   - Implement descriptor-safe path access, ignore policy, incremental rename/delete handling, CJK/LaTeX/PDF fixtures, and staleness reporting.
   - Exit gate: no advertised query can escape allowed roots or return unbounded content.

4. **Parent/worker orchestration**
   - Add assignment/attempt/result acceptance, narrow agent role adapters, deterministic review fan-out/synthesis, and cancellation/retry semantics.
   - Exit gate: malformed, stale, late, or peer-contaminated results cannot mutate canonical state.

5. **Lifecycle hooks as adapters**
   - Add SessionStart/SubagentStart/SubagentStop/Pre/Post/Stop behavior only after equivalent runtime checks exist.
   - Exit gate: disabling or refusing hook trust degrades convenience, not correctness or security.

6. **Research graph projection**
   - Add manifest-only entity projection, stable IDs, supersession, projection receipts, bounded evidence-chain queries, and full rebuild.
   - Exit gate: delete both projection databases, rebuild, and obtain equivalent fixed-query answers at the same ledger tip.

7. **Verification/evidence hardening**
   - Wire citation, semantic-claim, temporal, statistical, experiment, figure, review, and format gates to captured evidence receipts.
   - Exit gate: `finalize` refuses unresolved, stale, missing, inaccessible, or unverifiable required evidence; waivers remain explicit and scoped.

The critical dependency is the canonical schema/reducer contract. Agent behavior, hooks, and graph projection all consume it; none should independently define run, result, claim, or gate semantics.

## Integration Points

### External/Host Interfaces

| Interface | Integration Pattern | Notes |
|-----------|---------------------|-------|
| Codex plugin loader | Required manifest with relative component paths | Plugin hooks require review/trust; only package metadata belongs in `.codex-plugin/` |
| Codex subagents | Parent-spawned direct children with immutable assignment snapshot | Custom profiles are user/project scoped; built-in fallback must remain valid |
| Codex hooks | JSON/stdin command hooks with narrow timeouts | Concurrent, optional, defense in depth |
| MCP | JSON-RPC 2.0 over stdio | Query-only advertised surface; structured, bounded responses |
| ARS | Pinned workflow prompts and existing shared contracts | Preserve semantics; add explicit adapters instead of editing vendored source |
| file-base upstream | Pinned source + ordered local patches | Reuse parser/index pipeline, replace code-centric file API gap |
| External literature APIs | Runtime connector adapters producing source manifests | Network/credentials/paid access are explicit capabilities and human-gated |

### Internal Boundaries

| Boundary | Communication | Invariant |
|----------|---------------|-----------|
| Parent ↔ runtime | JSON CLI request/response | Only runtime writes canonical records |
| Parent ↔ worker | Assignment path/ID and result envelope | Worker cannot accept or merge its own result |
| Runtime ↔ canonical store | Locked filesystem transaction | Event references only durable immutable manifests |
| Runtime ↔ projector | Explicit ledger tip + manifest set | Projection cannot advance past verified authority |
| Agent ↔ MCP | Read-only tool calls | Every response is bounded and names source/hash/staleness |
| Hook ↔ runtime | Idempotent observe/status commands | Hook ordering/failure cannot affect core correctness |
| Graph ↔ authoritative files | One-way projection | No reverse sync from graph to provenance |

## Confidence and Open Architecture Risks

| Area | Confidence | Reason / Required Validation |
|------|------------|------------------------------|
| Ledger/manifests as authority | HIGH | Explicit project invariant and ARS passport/audit patterns |
| Existing file-base gaps and extension points | HIGH | Verified against pinned C entrypoints, schema, path guard, patch, and launch scripts |
| Plugin skills/MCP/hooks layout | HIGH | Current official Codex plugin documentation |
| Hook limitations and event behavior | HIGH | Current official Codex hooks documentation |
| Custom agent packaging inside a plugin | MEDIUM | Official docs define user/project `.codex/agents`, not a native plugin `agents` component; keep adapter/fallback |
| MCP launcher path resolution from installed plugin | MEDIUM | Official plugin docs show MCP maps but do not clearly establish the same `PLUGIN_ROOT` substitution documented for hooks; prove in Phase 0 |
| Portable race-free path opening | MEDIUM-HIGH | Strong OS patterns exist, but Windows junction/reparse-point parity needs dedicated tests |
| CJK/LaTeX/PDF retrieval quality | MEDIUM | Requires corpus benchmarks; current patch only admits structure-only file nodes |

## Sources

### Local primary sources

- [`PROJECT.md`](/home/zhangyangrui/my_programes/academic-research-workbench/.planning/PROJECT.md) — milestone scope, authority, security, and v1 headless constraints.
- [`ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`](/home/zhangyangrui/orca/workspaces/Examination/审查/experiments/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md) — prior target architecture, run layout, phases, and graph semantics.
- [`academic-research-suite/SKILL.md`](/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md) and [`science_workbench_mvp.md`](/home/zhangyangrui/.codex/skills/academic-research-suite/codex/references/science_workbench_mvp.md) — ARS routing, security, optional runtime profile, run/evidence requirements.
- [`full-runtime-manifest.json`](/home/zhangyangrui/.codex/skills/academic-research-suite/codex/full-runtime-manifest.json) and [`ars_codex_full_runtime.py`](/home/zhangyangrui/.codex/skills/academic-research-suite/codex/scripts/ars_codex_full_runtime.py) — current planner-only baseline and declared degradations.
- [`handoff_schemas.md`](/home/zhangyangrui/.codex/skills/academic-research-suite/ars/shared/handoff_schemas.md) and [`reset_ledger_entry.schema.json`](/home/zhangyangrui/.codex/skills/academic-research-suite/ars/shared/contracts/passport/reset_ledger_entry.schema.json) — existing handoff and append-only resume contracts.
- [`codebase-memory-mcp/src/main.c`](/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/src/main.c), [`src/mcp/mcp.c`](/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/src/mcp/mcp.c), and [`src/store/store.c`](/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/src/store/store.c) — pinned MCP process, tool dispatch, containment guard, and SQLite schema.
- [`file-base-mcp`](/home/zhangyangrui/orca/projects/Paper4Master/scripts/file-base-mcp), [`build-file-base-mcp`](/home/zhangyangrui/orca/projects/Paper4Master/scripts/build-file-base-mcp), and [`file-base-server-name.patch`](/home/zhangyangrui/orca/projects/Paper4Master/patches/file-base-server-name.patch) — current wrapper, non-clean build behavior, text/PDF admission patch, and server rename.

### Current official Codex documentation

- [Build plugins](https://developers.openai.com/codex/plugins/build) — required manifest, root layout, bundled MCP maps, hook trust, and plugin data variables.
- [Hooks](https://developers.openai.com/codex/hooks) — events, concurrency, trust, output semantics, `PreToolUse` limitations, and stop/subagent-stop behavior.
- [Subagents](https://developers.openai.com/codex/subagents) — custom agent discovery, inherited permissions, concurrency/depth controls, and narrow-role guidance.
- [Model Context Protocol](https://developers.openai.com/codex/mcp) — stdio server configuration and MCP host/client/server boundary.
- [Customization](https://developers.openai.com/codex/concepts/customization) — complementary roles of skills, MCP, and subagents.

---
*Architecture research for: Academic Research Workbench v1.0 headless core*
*Researched: 2026-07-12*
