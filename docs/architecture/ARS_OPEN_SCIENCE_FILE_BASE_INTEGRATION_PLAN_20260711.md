# ARS Codex Runtime and file-base Integration Plan

Date: 2026-07-11

## 1. Objective

Turn `academic-research-suite` from a prompt-and-contract package into a
restartable, auditable Codex research runtime, while integrating Paper4Master's
`file-base` MCP as the file and relationship query layer.

The integration follows one non-negotiable boundary:

- The ARS append-only run ledger and immutable artifact manifests are the source
  of truth.
- `file-base` is a rebuildable graph/read projection over those files and
  manifests.
- Hooks coordinate and validate lifecycle events; they are not the provenance
  store.
- Subagents produce scoped result envelopes; the parent orchestrator is the only
  writer of canonical state.

## 2. Current Baseline

### ARS

- Strong research-question, evidence, integrity, review, and manuscript
  contracts already exist.
- The Codex planner emits route and agent-team JSON but does not dispatch agents,
  execute gates, advance pipeline state, or resume a run.
- The current Codex hook only announces aliases.
- The Science Workbench reference defines run directories, paper AST, audit
  artifacts, and human-review states, but these are not implemented.

### file-base

- Derived from `DeusData/codebase-memory-mcp` revision
  `ee68144af5453addda995a27cce8142999f318fb` under the MIT License.
- The local patch admits generic text, LaTeX, shell scripts, patches, and
  directly text-bearing PDFs as structure-only `File` nodes.
- Paper4Master currently indexes 7 files into 57 nodes and 56 edges.
- The existing global cache has already indexed ARS into 7,465 nodes and 7,510
  edges, demonstrating immediate structural-query value.
- Missing capabilities remain: first-class `files` storage, bounded file reads,
  content FTS, extracted PDF text, research-semantic nodes, and stable ingestion
  of ARS manifests.

## 3. Target Architecture

```text
Codex parent orchestrator
  |-- ARS runtime CLI --------> events.jsonl + state.json + manifests
  |-- read-only subagents ----> assignments/<id>.json + results/<id>.json
  |-- lifecycle hooks --------> policy checks + lightweight event capture
  `-- file-base MCP ----------> rebuildable file/research graph projection

Open Science Desktop or another UI may consume the same run artifacts later.
```

### Canonical run layout

```text
experiments/runs/<task>__<timestamp>__<hash8>/
  run_manifest.json
  state.json
  passport.json
  events.jsonl
  assignments/
  results/
  input/
  evidence/
    sources.json
    claims.json
  experiment/
    data_contract.json
    runs.jsonl
    results.json
  paper/
    paper.ast.json
    drafts/
  reviews/
  audit/
  exports/
```

### Research graph projection

Required node types:

- `ResearchRun`, `Stage`, `AgentTask`, `Artifact`, `Source`, `Claim`, `Dataset`
- `ExperimentRun`, `Result`, `Figure`, `ReviewFinding`, `Gate`,
  `HumanReviewItem`

Required edge types:

- `CONTAINS_STAGE`, `ASSIGNED_TO`, `PRODUCED`, `DERIVED_FROM`, `SUPERSEDES`
- `CITES`, `SUPPORTS`, `CONTRADICTS`, `UNVERIFIED_BY`
- `USES_DATASET`, `GENERATED_BY`, `REPORTS_RESULT`
- `FLAGS`, `BLOCKS`, `RESOLVES`

Every projected node must carry the canonical artifact path and SHA-256. Graph
records never replace source manifests or state transitions.

## 4. Workstreams and Phases

### Phase 0 - Contract repair and executable baseline

1. Fix stale ARS compatibility/version documentation and mode declarations.
2. Make agent selection mode-aware.
3. Unify the result provenance field on `provenance.mode`; remove ambiguous
   top-level simulated flags.
4. Add JSON Schemas for run, state, assignment, result, source, claim,
   experiment result, review, and gate records.
5. Add one end-to-end fixture that fails unless a run can initialize, advance,
   stop, and resume.

Exit gate: all existing adapter tests pass, schema tests pass, and the fixture
resumes without relying on conversation memory.

### Phase 1 - ARS durable execution kernel

Implement a side-effect-controlled runtime CLI with at least:

- `init`, `status`, `transition`, `checkpoint`, `resume`
- `assign`, `accept-result`, `record-artifact`, `record-experiment`
- `run-gate`, `waive-gate`, `finalize`

Use atomic state replacement, append-only events, SHA-256 artifact addressing,
revision compare-and-swap, and immutable manuscript/result versions.

Exit gate: crash/restart, duplicate command, stale-result, failed-gate, and lock
contention tests pass.

### Phase 1F - file-base files-first foundation

This phase can run in parallel with Phase 1.

1. Pin the upstream commit in a machine-readable manifest and verify it before
   applying the local patch.
2. Build in a temporary or clean source tree instead of mutating an ignored
   checkout in place.
3. Add read-only MCP tools:
   - `list_files`
   - `read_file`
   - `search_files`
   - `get_file_outline`
   - `get_file_context`
4. Add a first-class files table:
   `rel_path, mime, extension, language, size, sha256, mtime, line_count,
   is_binary, indexed_at`.
5. Add FTS for Markdown, LaTeX, BibTeX, text, JSON/YAML/TOML, CSV, and extracted
   PDF text. CJK and LaTeX tokenization require explicit tests.
6. Add `.cbmignore` defaults for caches, generated PDFs, downloaded corpora,
   credentials, and oversized binary outputs.

Exit gate: bounded reads, CJK/LaTeX search, symlink escape rejection,
incremental re-indexing, deletion, rename, and stale-cache tests pass.

### Phase 2 - Codex subagents and lifecycle hooks

Add narrow custom agents for source discovery, evidence verification,
experiment execution, manuscript drafting, peer review, and editorial synthesis.

Initial workers are read-only. They receive immutable assignment snapshots and
return schema-validated result envelopes. The parent alone merges canonical
files in deterministic task order.

Hook responsibilities:

- `SessionStart`: validate and hydrate the selected run/passport.
- `SubagentStart`: inject assignment ID, input hash, output schema, and policy.
- `SubagentStop`: validate the result envelope and continue incomplete work.
- `PreToolUse`: block obvious path, consent, immutable-output, and stage errors.
- `PostToolUse`: record lightweight tool/output evidence and trigger graph sync.
- `Stop`: continue when mandatory gates or requested deliverables remain open.

`PreToolUse` remains defense in depth because Codex does not intercept every
possible side-effect path.

Exit gate: independent reviewers remain blind before synthesis; stale or
malformed worker results cannot mutate canonical state.

### Phase 3 - ARS research-semantic graph projection

1. Add `ingest_research_manifest` and `sync_research_run` to `file-base`.
2. Parse only validated ARS JSON manifests; do not infer canonical state from
   prose.
3. Use stable IDs derived from run ID, artifact path, and content hash.
4. Make ingestion idempotent and support supersession without destructive
   history rewrites.
5. Expose bounded queries for:
   - claim to supporting/contradicting source
   - paper number to experiment result and run
   - figure to script, data, environment, and manuscript reference
   - review finding to revision and resolution
   - blocked stage to failing gate and required human action
   - active run to next resumable task

Exit gate: deleting the graph cache and rebuilding from run artifacts produces
equivalent query results.

### Phase 4 - Integrity, experiment, and benchmark hardening

1. Wire citation, semantic-claim, temporal, statistical, domain, figure, and
   manuscript-format gates into runtime transitions.
2. Capture command, exit status, wall time, Git SHA, environment lock, dataset
   contract, seeds, inputs, outputs, logs, and hashes for experiments.
3. Add paid/inaccessible evidence to the human-review queue instead of marking
   it verified.
4. Build a fixed benchmark set covering literature, experiment, review,
   recovery, and evidence-chain queries.
5. Run a documented ResearchClawBench subset with raw runs, model/runtime
   configuration, scorer version, and reproducible score artifacts.

Exit gate: no paper may reach `ready` with unresolved mandatory gate failures,
untraceable main-result numbers, or stale figure provenance.

### Phase 5 - Optional Open Science Desktop adapter

Expose ARS run artifacts and file-base graph queries to a desktop viewer without
moving state ownership into the UI. Reuse existing PDF, notebook, file, run, and
provenance views where practical.

This phase is optional and must not block the headless Codex workflow.

## 5. Security and Privacy Requirements

- Default file and graph operations are read-only.
- Resolve paths after symlink canonicalization and enforce the active workspace
  root.
- Cap returned bytes, rows, context, traversal depth, and query time.
- Do not index credentials, private keys, browser/session databases, or ignored
  unpublished corpora by default.
- Record whether a source is metadata-only, abstract, open full text, local
  private file, or inaccessible.
- Keep external update checks and all network behavior visible and separately
  configurable from local indexing.
- Preserve the upstream MIT notice and third-party license inventory.

## 6. Recommended Delivery Order

1. Phase 0
2. Phase 1 and Phase 1F in parallel
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5 only after the headless workflow is stable

The critical dependency is the ARS schema, not the graph implementation. The
graph projection must consume stable runtime artifacts; otherwise both projects
will encode competing definitions of run, result, claim, and provenance.
