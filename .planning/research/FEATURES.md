# Feature Research

**Domain:** Codex-native, headless academic research workbench plugin
**Researched:** 2026-07-12
**Confidence:** MEDIUM

## Scope And Classification

This inventory distinguishes two observable surfaces:

- **User-observable:** what a researcher can invoke, inspect, approve, resume, or receive as a research artifact.
- **Operator-observable:** what a maintainer or auditor can inspect to diagnose packaging, runtime state, permissions, agents, indexes, gates, recovery, and provenance.

“Differentiator” describes product positioning, not roadmap optionality. Several differentiators below are P1 launch requirements because they implement the project's core promise: every run is reproducible, resumable, and auditable from source files through claims, experiments, reviews, and final artifacts.

Complexity is relative to this greenfield v1.0 headless core. Dependencies use the feature IDs defined below.

## Feature Landscape

### Table Stakes (Users Expect These)

Missing any P1 item below makes the plugin feel like a prompt collection or an unsafe local tool rather than an executable research workbench.

| ID | Feature | Surface | Why Expected | Complexity | Dependencies | Notes |
|----|---------|---------|--------------|------------|--------------|-------|
| TS-1 | Installable, discoverable Codex plugin | Both | A plugin must install, enable/disable, expose its skill, MCP server, and trusted hook pack, and report its identity/version. | MEDIUM | None | Ship `.codex-plugin/plugin.json`, stable name/version, skill routing, `.mcp.json`, hook paths, install metadata, and a smoke test from a clean install. Do not require a desktop shell. |
| TS-2 | Pinned source, patches, notices, and license inventory | Operator | Operators must be able to reproduce the package and determine exactly which ARS and file-base sources were shipped. | MEDIUM | TS-1 | Machine-readable source locks, commit verification, patch hashes, third-party notices, and license inventory are release gates. Runtime fetching from moving branches is prohibited. |
| TS-3 | Existing ARS workflow and mode routing | User | Researchers expect literature review, research scoping, paper production, experiment planning/validation, review, revision, and integrity workflows already present in ARS to remain available. | MEDIUM | TS-1, TS-2 | Preserve ARS semantics and aliases through the root skill. Route vague paper topics to Socratic scoping. Expose known degradations instead of claiming perfect Claude/Codex parity. |
| TS-4 | Explicit run lifecycle, status, checkpoint, and resume | Both | Long research runs must survive interruption and show the current stage, completed work, blockers, and next legal action. | HIGH | TS-1, TS-5 | Provide at least `init`, `status`, `transition`, `checkpoint`, `resume`, and `finalize`; resume must work without conversation memory. User checkpoints distinguish advisory, mandatory, and human-review states. |
| TS-5 | Append-only ledger, state machine, immutable artifacts, and Material Passport | Both | Research outputs need durable provenance, versioning, staleness detection, and an inspectable chain of custody. | HIGH | TS-2 | `events.jsonl` is append-only; `state.json` uses atomic replacement and revision/CAS checks; artifacts carry path, SHA-256, origin, mode, version, dependencies, and verification state. Never overwrite prior artifact versions. |
| TS-6 | Bounded files-first MCP | Both | A research workbench must list, read, search, outline, and contextualize manuscripts, notes, bibliographies, data files, reports, and scripts—not only code symbols. | HIGH | TS-1, TS-2, TS-7 | Launch tools: `list_files`, `read_file`, `search_files`, `get_file_outline`, `get_file_context`. Cover Markdown, LaTeX, BibTeX, text, JSON/YAML/TOML, CSV, and extracted/direct-text PDF content with explicit format coverage and truncation metadata. |
| TS-7 | Safe local-access and permission boundaries | Both | Researchers may handle unpublished papers, private notes, credentials, and paid sources; the plugin must make access boundaries visible and fail closed. | HIGH | TS-1, TS-2 | Canonicalize paths, enforce allowed roots, reject symlink/`..` escapes, bound bytes/rows/context/depth/time, default MCP tools and initial workers to read-only, and expose ignore decisions. Use MCP allowlists/approval modes; hooks are defense in depth only. |
| TS-8 | Specialized subagent execution with deterministic handoffs | Both | A workbench that advertises delegated research must actually run scoped source, evidence, experiment, drafting, review, and synthesis roles and show their outcomes. | HIGH | TS-4, TS-5, TS-7 | Each worker receives an immutable assignment ID, input hash, allowed roots/tools, output schema, and completion contract; it returns a schema-validated result envelope. The parent orchestrator alone merges canonical state in deterministic order. |
| TS-9 | Trusted lifecycle hooks with visible decisions | Operator | Hooks are needed to hydrate runs, validate agents, capture tool evidence, and continue unfinished gated work, but operators must be able to review and trust them. | HIGH | TS-4, TS-5, TS-7, TS-8 | Cover `SessionStart`, `SubagentStart`, `SubagentStop`, `PreToolUse`, `PostToolUse`, and `Stop`. Record matched event, policy decision, reason, duration, and failure. Make disabled/untrusted/partial-interception states explicit. |
| TS-10 | Integrity gates, waivers, and human-review queue | Both | Academic workflows require more than successful command execution: claims, citations, data, figures, reviews, and final readiness need explicit verdicts. | HIGH | TS-5, TS-8 | Gates emit machine-readable PASS/FAIL/BLOCKED results and actionable summaries. Waivers record actor, reason, time, and scope. Paid/inaccessible or unauthorized evidence becomes `blocked_human_review`, never “verified.” |
| TS-11 | Unified status and diagnostics | Both | Users need a concise “where am I?” view; operators need enough detail to diagnose a stuck or stale run without reading raw transcripts. | MEDIUM | TS-4, TS-5, TS-8, TS-9, TS-10 | Status reports run/stage, revision, last checkpoint, active/finished agents, failing gates, pending human actions, graph/index freshness, and next resumable task. Link to canonical files rather than duplicating their contents. |
| TS-12 | Executable end-to-end, recovery, and audit evidence | Operator | Static schemas and unit tests do not prove that a real run installs, advances, crashes, resumes, rejects stale work, and produces inspectable evidence. | HIGH | TS-1 through TS-11 | Release fixtures must cover clean install, init/advance/stop/resume, duplicate command, stale result, failed gate, lock contention, bounded reads, path escape, and evidence-chain inspection. Preserve raw fixture artifacts for audit. |

### Differentiators (Competitive Advantage)

| ID | Feature | Surface | Value Proposition | Complexity | Dependencies | Notes |
|----|---------|---------|-------------------|------------|--------------|-------|
| DF-1 | Canonical truth versus rebuildable projection | Both | The ledger, manifests, and source files remain authoritative while the file/research graph can be deleted, migrated, or rebuilt without provenance loss. | HIGH | TS-5, TS-6 | Every projected record carries canonical path and SHA-256. Rebuild equivalence is a release gate. This is a P1 differentiator, not optional architecture polish. |
| DF-2 | Research-semantic evidence-chain queries | Both | A researcher can move from claim to supporting/contradicting source, result, dataset, figure, review finding, gate, and required human action. | HIGH | DF-1, TS-10 | Use stable IDs and bounded queries over validated manifests; support `SUPPORTS`, `CONTRADICTS`, `DERIVED_FROM`, `REPORTS_RESULT`, `FLAGS`, `BLOCKS`, and `RESOLVES` relationships. |
| DF-3 | Proven crash recovery and stale-work rejection | Both | Resume is scientifically safer than “continue from chat”: duplicate commands are idempotent, stale agent results cannot mutate state, and consumed checkpoints remain auditable. | HIGH | TS-4, TS-5, TS-8, TS-12 | Use atomic checkpoints, revision CAS, lock diagnostics, assignment/input hashes, append-only boundary/resume entries, and immutable result versions. Do not market a configuration lock as bit-for-bit replay. |
| DF-4 | Research-aware, multilingual file retrieval | User | Bounded contextual retrieval works across prose, CJK text, LaTeX structure, BibTeX, tabular files, and extracted PDF text rather than treating a paper workspace as a code repository. | HIGH | TS-6, TS-7 | Test CJK and LaTeX tokenization, heading/citation/ref extraction, rename/delete/incremental indexing, and stale-cache behavior. CJK support is language-general and must not encode Chinese military assumptions. |
| DF-5 | Independent reviewer panel with dissent preservation | Both | Methodology, domain, perspective, and devil's-advocate findings are produced independently before synthesis; minority concerns cannot disappear by majority vote. | MEDIUM | TS-8, TS-10 | Blind reviewers from one another until synthesis. Persist individual reports and a finding matrix; the synthesizer may prioritize but must explicitly resolve or preserve dissent. |
| DF-6 | End-to-end audit evidence bundle | Both | Each completed run yields a compact, inspectable dossier linking source hashes, agent assignments/results, tool evidence, gates, waivers, experiments, reviews, outputs, and next actions. | HIGH | TS-5, TS-9, TS-10, TS-12, DF-2 | Provide machine-readable artifacts plus a concise Markdown audit summary. Evidence should be sufficient for a third party to reconstruct why a run reached `ready` or remained blocked. |
| DF-7 | Evidence-access semantics and honest human handoff | User | The plugin distinguishes metadata, abstract, open full text, local private file, and inaccessible/paid evidence, preventing false claims of verification. | MEDIUM | TS-6, TS-7, TS-10 | Default to public metadata/abstract verification. Require explicit authorization for private/local/paid material and enqueue unresolved access judgments for human review. |
| DF-8 | Gate-aware “next resumable task” computation | Both | Instead of showing logs alone, status explains the exact legal next action and why other transitions are blocked. | MEDIUM | TS-4, TS-10, DF-1 | Compute from validated state and gates, not from conversational inference or graph state. Project this into the graph only as a query accelerator. |

### Anti-Features (Commonly Requested, Often Problematic)

| ID | Anti-Feature | Surface | Why Requested | Why Problematic | Complexity Avoided | Conflicts With | Alternative |
|----|--------------|---------|---------------|-----------------|--------------------|----------------|-------------|
| AF-1 | Desktop UI or Open Science Desktop shell in v1 | User | A visual run browser appears easier to use. | It duplicates unstable runtime contracts and diverts effort from recovery, provenance, and evidence gates. v1 is explicitly headless. | HIGH | TS-4, TS-12 | Provide CLI/status commands and linked Markdown/JSON artifacts; add a read-only UI adapter only after contracts stabilize. |
| AF-2 | Chinese-military-specific ontology, sources, labels, or defaults in core | User | The motivating project may benefit from domain shortcuts. | It contaminates general abstractions, harms reuse, and violates confirmed v1 scope. | MEDIUM | DF-2, DF-4 | Keep core ontology domain-neutral; add separately versioned, optional domain packs after v1 if justified. |
| AF-3 | Semantic graph as authoritative storage | Both | A single graph database looks simpler and enables rich queries. | Index deletion, migration, partial ingestion, or schema bugs would rewrite scientific truth and create conflicts with ledgers/manifests. | HIGH | TS-5, DF-1 | Keep graph state disposable and rebuildable from canonical artifacts; compare rebuild results. |
| AF-4 | Canonical writes by subagents | Operator | Letting workers update state directly seems faster. | Parallel writes create races, nondeterministic merges, provenance ambiguity, and reviewer leakage. | HIGH | TS-5, TS-8, DF-5 | Workers are read-only by default and emit result envelopes; only the parent performs deterministic canonical writes. |
| AF-5 | Unbounded general filesystem bridge | Both | “Read any local file” reduces setup friction. | It risks credential leakage, path escape, oversized outputs, prompt injection exposure, and accidental indexing of private corpora. | HIGH | TS-6, TS-7 | Require allowed roots, ignore rules, symlink-safe path checks, bounded outputs, and explicit authorization. |
| AF-6 | Silent credentials, paid-database access, paywall bypass, or hidden network calls | User | Automatic full-text access appears to improve verification coverage. | It creates privacy, legal, licensing, cost, and consent failures and may falsely label inaccessible evidence as verified. | HIGH | TS-7, TS-10, DF-7 | Keep network behavior visible and separately configurable; use public metadata by default and human-gate inaccessible evidence. |
| AF-7 | Unpinned remote dependencies or build-time mutation of an ignored checkout | Operator | Tracking upstream `main` minimizes vendoring work. | Builds drift, patches become non-reviewable, licenses become uncertain, and regressions cannot be reproduced. | MEDIUM | TS-2, TS-12 | Verify pinned commits, apply recorded patches in clean/temp trees, and ship notices and source locks. |
| AF-8 | Mutable history, overwritten artifacts, or destructive “cleanup” | Both | Keeping only the latest state seems tidy. | It erases failed attempts, waivers, superseded claims, and recovery evidence needed for audit. | MEDIUM | TS-5, DF-3, DF-6 | Append events, create immutable versions, represent supersession explicitly, and archive without rewriting history. |
| AF-9 | Treating hooks as a complete security boundary | Operator | Central pre-tool hooks look like one place to enforce every policy. | Current Codex interception is incomplete; equivalent side effects can use unsupported paths, and plugin hooks require user trust. | HIGH | TS-7, TS-9 | Enforce invariants in the runtime/MCP/state writer, use sandbox and approvals, and treat hooks as visible defense in depth. |
| AF-10 | Fully autonomous progression through mandatory gates | User | “Run everything without stopping” reduces interaction. | It can publish unsupported claims, waive access issues implicitly, or erase the user's responsibility for scientific decisions. | MEDIUM | TS-10, DF-7, DF-8 | Automate non-critical stages, but require explicit decisions for blocking integrity failures, waivers, paid/private evidence, and final readiness. |
| AF-11 | Universal binary ingestion and OCR in v1 | User | Supporting every PDF, DOCX, spreadsheet, slide, image, and scan sounds complete. | Parser/OCR quality, licensing, resource limits, and false extraction confidence would overwhelm the headless core milestone. | HIGH | TS-6, TS-12 | Launch with declared text formats and bounded extracted/direct-text PDF support; add optional format adapters with provenance and quality flags later. |
| AF-12 | Hidden cloud sync, analytics, or telemetry | Operator | Central dashboards and usage analytics help operations. | Unpublished research and private sources make undisclosed data movement unacceptable, and it is unrelated to validating the local core. | HIGH | TS-7, DF-6, DF-7 | Keep v1 local-first; if telemetry is later needed, make it opt-in, documented, redacted, and auditable. |

## Feature Dependencies

```text
TS-1 Installable plugin
├──requires──> TS-2 Pinned source and licenses
├──enables───> TS-3 ARS workflow routing
└──enables───> TS-6 Files-first MCP ──requires──> TS-7 Access boundaries

TS-5 Ledger + state + passports
├──enables───> TS-4 Lifecycle/status/resume
├──enables───> TS-8 Subagent handoffs ──requires──> TS-7 Access boundaries
├──enables───> TS-9 Lifecycle hooks
└──enables───> TS-10 Gates/waivers/human review

TS-4 + TS-8 + TS-9 + TS-10 ──compose──> TS-11 Unified diagnostics
TS-1..TS-11 ──verified-by──> TS-12 End-to-end/recovery/audit evidence

TS-5 + TS-6 ──enable──> DF-1 Rebuildable projections
DF-1 + TS-10 ──enable──> DF-2 Evidence-chain queries
TS-4 + TS-5 + TS-8 + TS-12 ──enable──> DF-3 Proven recovery
TS-8 + TS-10 ──enable──> DF-5 Independent review
TS-5 + TS-9 + TS-10 + TS-12 + DF-2 ──compose──> DF-6 Audit bundle
TS-4 + TS-10 + DF-1 ──enable──> DF-8 Next resumable task

AF-3 Graph authority ──conflicts-with──> TS-5 and DF-1
AF-4 Worker canonical writes ──conflicts-with──> TS-8 and DF-5
AF-9 Hook-only enforcement ──conflicts-with──> TS-7
AF-10 Autonomous gate skipping ──conflicts-with──> TS-10 and DF-7
```

### Dependency Notes

- **Stabilize schemas before graph semantics:** run, state, assignment, result, source, claim, experiment, review, and gate schemas define the truth the graph projects. Building semantic ingestion first would create competing definitions.
- **Build TS-5 before TS-4:** resume is a consequence of durable events, atomic state, immutable artifacts, and checkpoint identity; it cannot be safely added as a conversational shortcut.
- **Build TS-6 and TS-7 together:** file value without root enforcement and bounds is unsafe; security retrofits would change every tool contract.
- **Build TS-8 before TS-9 orchestration logic:** hooks should validate and observe a stable assignment/result contract, not become the contract themselves.
- **Build TS-10 before DF-2 and DF-8:** evidence-chain and “next action” queries require stable gate verdicts and human-action states.
- **TS-12 is continuous, not a final test phase:** each substrate feature needs an executable failure/recovery fixture before downstream features depend on it.

## MVP Definition

### Launch With (v1.0 Headless Core)

- [ ] **TS-1 + TS-2:** clean install, stable manifest, pinned ARS/file-base sources, patch verification, notices, and license inventory.
- [ ] **TS-3:** executable routing for the existing ARS workflow families with explicit Codex parity/degradation reporting.
- [ ] **TS-5 + TS-4:** append-only run ledger, schema-validated state, Material Passport, atomic checkpoints, status, and crash-safe resume without chat memory.
- [ ] **TS-6 + TS-7:** bounded read-only files-first MCP with first-class file metadata, content search, allowed-root enforcement, ignore defaults, and CJK/LaTeX tests.
- [ ] **TS-8 + TS-9:** scoped specialized workers, parent-only canonical writes, deterministic handoffs, trusted lifecycle hooks, and visible hook limitations.
- [ ] **TS-10 + TS-11:** mandatory integrity/human-review states, recorded waivers, concise status, blockers, and next legal action.
- [ ] **DF-1:** idempotent research-graph projection that can be deleted and rebuilt to equivalent query results.
- [ ] **DF-2 + DF-8:** a bounded minimum query set for claim evidence, figures/results, review resolution, failing gates, and next resumable task.
- [ ] **DF-3 + DF-5 + DF-6 + TS-12:** one representative end-to-end research-to-review fixture proving independent review, stale-result rejection, crash/restart, and a complete audit evidence bundle.

### Add After Validation (v1.x)

- [ ] **Hardened structured paper/export pipeline** — normalize Markdown into a paper AST, validate references/layout, and produce strict publication outputs once the runtime and gate contracts are stable.
- [ ] **Additional source adapters and cache invalidation controls** — add only when a source's licensing, credentials, access state, and rate limits can be represented honestly.
- [ ] **Optional OCR/DOCX/spreadsheet adapters** — require extraction provenance, confidence/quality flags, bounded resources, and adversarial fixtures.
- [ ] **Expanded benchmark suite** — add fixed literature, experiment, review, recovery, and evidence-chain corpora after the v1 schemas stop moving.
- [ ] **Operator repair commands** — add validated index repair, checkpoint reconciliation, and migration dry-runs after real failure patterns are observed.

### Future Consideration (v2+)

- [ ] **Read-only desktop/Open Science Desktop adapter** — consume canonical run artifacts and graph queries without owning state.
- [ ] **Optional domain packs** — separately versioned ontologies, source presets, and gates; never bake Chinese military or another single domain into core abstractions.
- [ ] **Team/remote coordination** — only after consent, identity, conflict resolution, and private-data transport policies are designed and audited.
- [ ] **Opt-in telemetry/analytics** — only with explicit data-minimization and disclosure requirements; local-first remains the default.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| TS-1 Installable plugin | HIGH | MEDIUM | P1 |
| TS-2 Pinned source/licenses | HIGH | MEDIUM | P1 |
| TS-3 ARS workflow routing | HIGH | MEDIUM | P1 |
| TS-4 Lifecycle/status/resume | HIGH | HIGH | P1 |
| TS-5 Ledger/state/passports | HIGH | HIGH | P1 |
| TS-6 Files-first MCP | HIGH | HIGH | P1 |
| TS-7 Access boundaries | HIGH | HIGH | P1 |
| TS-8 Specialized subagents | HIGH | HIGH | P1 |
| TS-9 Trusted lifecycle hooks | MEDIUM | HIGH | P1 |
| TS-10 Gates/waivers/human review | HIGH | HIGH | P1 |
| TS-11 Unified diagnostics | HIGH | MEDIUM | P1 |
| TS-12 Executable evidence tests | HIGH | HIGH | P1 |
| DF-1 Rebuildable projections | HIGH | HIGH | P1 |
| DF-2 Evidence-chain queries | HIGH | HIGH | P1 |
| DF-3 Proven recovery/stale rejection | HIGH | HIGH | P1 |
| DF-4 Research-aware retrieval | HIGH | HIGH | P1 |
| DF-5 Independent reviewer panel | HIGH | MEDIUM | P1 |
| DF-6 End-to-end audit bundle | HIGH | HIGH | P1 |
| DF-7 Evidence-access semantics | HIGH | MEDIUM | P1 |
| DF-8 Next resumable task | HIGH | MEDIUM | P1 |
| Structured paper/export hardening | MEDIUM | HIGH | P2 |
| OCR/office format adapters | MEDIUM | HIGH | P2 |
| Desktop adapter | MEDIUM | HIGH | P3 |
| Optional domain packs | LOW for core | MEDIUM | P3 |

**Priority key:**

- P1: Must have for the v1.0 headless core.
- P2: Add after the core contracts and evidence fixtures validate.
- P3: Future surface or specialization; must not delay v1.

## Baseline And Adjacent-System Feature Analysis

This is a grounded baseline comparison, not a claim of comprehensive market coverage.

| Capability | ARS 0.1.19 Codex adapter | Current patched file-base baseline | Native Codex substrate | Workbench v1 approach |
|------------|--------------------------|------------------------------------|------------------------|-----------------------|
| Academic workflow breadth | Strong prompts, roles, schemas, integrity methods, and static validators | Not applicable | General-purpose skills/subagents | Preserve ARS; execute it through durable state and gates. |
| Durable run execution | Planner/inline role execution; no complete dispatch/state/resume runtime | Index/cache lifecycle only | Sessions and subagents, but no academic run ledger | Append-only events, state machine, checkpoints, passports, parent-only writes. |
| File retrieval | Uses tools available to the active agent; no dedicated research file layer | Structural `File` nodes and code-oriented search; no first-class files table/content FTS | MCP can expose bounded tools with allowlists and approvals | Files-first MCP for research formats with explicit bounds and coverage. |
| Semantic graph | Handoff schemas and provenance concepts, not a rebuildable run graph | Code/structure graph, limited document semantics | MCP transport, not a research ontology | Disposable projection over validated manifests with rebuild equivalence. |
| Subagents and review independence | Agent prompts and optional planner profile; current adapter records degradations | Not applicable | Native subagents, custom roles, read-only sandboxes, inspectable threads | Immutable assignments/results, blind reviewers, deterministic parent synthesis. |
| Lifecycle policy | Optional local Codex hook pack; prior adapter treats hooks cautiously | Server-side path helpers only | Plugin hooks exist but require trust; interception is incomplete | Runtime/MCP enforce invariants; hooks hydrate, validate, observe, and continue as defense in depth. |
| Audit evidence | Material Passport, integrity schemas, and static audit artifacts | File/index metadata | Tool/subagent activity is inspectable but not a scientific evidence chain | Unified run dossier linking sources, claims, experiments, reviews, gates, waivers, and artifacts. |

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Confirmed v1 scope and exclusions | HIGH | Directly stated in `PROJECT.md` and the confirmed integration plan. |
| Existing ARS workflows and audit contracts | HIGH | Verified from ARS 0.1.19 router, Science Workbench contract, pipeline workflow, full-runtime manifest, and Material Passport schema. |
| Current file-base gaps | HIGH | Grounded in a local source/behavior analysis at the pinned upstream revision and local patch. |
| Native Codex plugin, MCP, hooks, and subagent capabilities | HIGH | Verified against current official Codex documentation on 2026-07-12. |
| Table-stake versus differentiator classification | MEDIUM | Opinionated product judgment grounded in confirmed scope and adjacent baselines; no broad external market/user study was performed. |
| Cost estimates | MEDIUM | Relative complexity only; implementation spikes may change sequencing, especially hooks, PDF extraction, and graph equivalence. |

## Sources

### Project And Local Baselines

- **HIGH:** `/home/zhangyangrui/my_programes/academic-research-workbench/.planning/PROJECT.md` — confirmed product value, active requirements, constraints, and exclusions.
- **HIGH:** `/home/zhangyangrui/orca/workspaces/Examination/审查/experiments/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md` — target architecture, run layout, phases, security rules, graph query set, and exit gates.
- **HIGH:** `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md` — ARS 0.1.19 routing, security boundaries, current Codex mapping, and known runtime behavior.
- **HIGH:** `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/references/science_workbench_mvp.md` — task-scoped artifacts, paper AST, verification defaults, human-review states, and audit artifact contract.
- **HIGH:** `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md` — stage/checkpoint semantics, reviewer independence, state, recovery, gates, and anti-patterns.
- **HIGH:** `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/full-runtime-manifest.json` — current routes, agent-team rules, quality gates, and known degradations.
- **HIGH:** `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/shared/handoff_schemas.md` — Material Passport and cross-stage validation/freshness contracts.
- **HIGH:** `/home/zhangyangrui/orca/projects/Paper4Master/codebase-memory-mcp-file-code-analysis.md` — empirical file-base capabilities, local patch behavior, and files-first gaps.

### Official Codex Documentation

- **HIGH:** [Build plugins](https://developers.openai.com/codex/plugins/build) — required manifest, plugin structure, bundled skills/MCP/hooks, install metadata, plugin-scoped MCP policy, and hook trust.
- **HIGH:** [Subagents](https://developers.openai.com/codex/subagents) — skill-triggered delegation, inspectable threads, parallelization guidance, read-only custom agents, and configuration limits.
- **HIGH:** [Hooks](https://learn.chatgpt.com/codex/hooks) — supported lifecycle events, inputs/outputs, trust model, continuation behavior, and incomplete `PreToolUse` interception.
- **HIGH:** [Model Context Protocol](https://developers.openai.com/codex/mcp) — server configuration, allow/deny tool lists, approval modes, required/startup behavior, and timeouts.

## Research Gaps

- Validate how this plugin will distribute project-scoped custom agent TOML files. Official plugin manifests directly enumerate skills, MCP servers, apps, and hooks, while custom agents are documented under user/project `.codex/agents/`; v1 may need skill-driven role dispatch rather than assuming a plugin-native agent registration field.
- Reconcile experiment ownership before implementation. The confirmed integration plan calls for controlled experiment-execution subagents and `record-experiment`, while the current ARS Material Passport contract says experiments are run externally and ARS only ingests scholar-declared provenance. Preserve external ingestion either way; define whether v1 execution is a new workbench-owned capability, its sandbox/approval model, and how both paths produce the same experiment record schema.
- Spike current hook behavior for `unified_exec`, web tools, and failure propagation. Official docs explicitly say interception is incomplete, so runtime/MCP enforcement must remain primary.
- Benchmark CJK/LaTeX FTS and extracted-PDF quality before finalizing file-size, context, and timeout defaults.
- Define the exact “equivalent query results” comparator for graph rebuilds, including ordering, timestamps, and schema migrations.
- Choose one representative end-to-end v1 fixture that exercises literature, claims, an experiment/result link, independent review, a failed gate, human handoff, crash/resume, and final audit evidence without requiring the deferred desktop/export surface.

---
*Feature research for: Academic Research Workbench v1.0 headless core*
*Researched: 2026-07-12*
