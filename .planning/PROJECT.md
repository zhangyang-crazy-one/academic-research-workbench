# Academic Research Workbench

## What This Is

Academic Research Workbench is a private, Codex-native plugin that turns the existing Academic Research Suite (ARS) and Paper4Master file-base graph MCP into an executable, auditable research workflow. It coordinates specialized subagents, lifecycle hooks, files-first retrieval, semantic research-graph projections, integrity gates, resumable runs, and evidence artifacts for literature review, experiment planning, manuscript production, and strict peer review.

The v1.0 milestone delivers a headless core for Codex. It is not a desktop application and does not constrain research workflows to one language, domain, dataset, or paper topic.

## Core Value

Every research run must be reproducible, resumable, and auditable from source files through claims, experiments, review gates, and final artifacts.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

(None yet - ship to validate)

### Active

<!-- Current scope. Building toward these. -->

- [ ] Package a valid Codex plugin with skill instructions, specialized subagents, hooks, MCP configuration, and installable manifest metadata.
- [ ] Pin and bundle the necessary ARS and file-base source, local patches, third-party notices, and license inventory so builds are reproducible.
- [ ] Implement an append-only run ledger, explicit workflow state machine, Material Passport, atomic checkpoints, and crash-safe resume behavior.
- [ ] Implement files-first MCP capabilities for bounded file listing, reads, full-text search, outline extraction, and contextual retrieval.
- [ ] Project authoritative run artifacts into a rebuildable research graph covering runs, stages, artifacts, claims, sources, datasets, experiments, figures, reviews, and gates.
- [ ] Execute specialized research subagents under lifecycle hooks, permission boundaries, integrity checks, and deterministic handoff contracts.
- [ ] Provide end-to-end, recovery, and audit tests that produce inspectable evidence instead of relying only on static validation.
- [ ] Preserve and ingest the existing ARS/open-science/file-base integration plan as an implementation input.

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Open Science Desktop or another graphical desktop shell - v1.0 is the headless runtime and plugin foundation.
- Replacing ARS with a new academic-writing methodology - the plugin operationalizes and hardens the existing suite.
- Treating the semantic graph as authoritative storage - graph indexes are rebuildable projections of ledger, manifests, and source files.
- A single-domain or Chinese-military-news workflow - datasets and papers may have domain characteristics, but the plugin must support general ontology abstraction and broader academic workflows.
- Unpinned remote dependencies or undocumented source snapshots - reproducibility and license traceability are milestone requirements.

## Context

- ARS 0.1.19 already provides broad academic workflow instructions and static validation, but its current Codex adapter emits plans rather than executing subagents, hooks, gates, persistent runtime state, or Material Passports.
- Paper4Master contains a working local wrapper and patch for `DeusData/codebase-memory-mcp` at commit `ee68144af5453addda995a27cce8142999f318fb`. The current graph is useful for structural indexing but lacks first-class files-table APIs, bounded content reads, full-text retrieval, document extraction, and research-domain nodes.
- Existing ARS ledgers and manifests remain authoritative. The file-base and semantic research graph are query accelerators that must be reconstructable after loss or schema migration.
- The prior integration plan separates contract repair, runtime kernel, file-base foundation, subagent and hook execution, semantic projection, integrity benchmarks, and a deferred desktop adapter.
- Development will occur in this private repository without modifying or reverting unrelated work in the Examination or Paper4Master repositories.

## Constraints

- **Runtime**: Codex-native plugin conventions and MCP transport contracts - the deliverable must install and execute through Codex rather than remain a design document.
- **Architecture**: Append-only ledger and immutable artifact manifests are the system of record - mutable graph state cannot decide scientific provenance.
- **Source provenance**: Necessary upstream code must be pinned with patch and license inventory - vendoring must remain reviewable and legally attributable.
- **Compatibility**: Preserve ARS workflow semantics and expose file-base capabilities through bounded, machine-readable tools - existing research assets must remain usable.
- **Security**: File access is restricted to explicitly allowed roots and outputs are bounded - the MCP must not become an unrestricted filesystem bridge.
- **Delivery**: v1.0 is headless and testable - desktop UX is deferred until runtime contracts and evidence gates are stable.

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Create `zhangyang-crazy-one/academic-research-workbench` as a private repository | Isolate plugin development and licensed source inventory from active paper workspaces | - Pending |
| Deliver a headless core in v1.0 | Runtime correctness, auditability, and recovery must precede desktop integration | - Pending |
| Pin and bundle required source, patches, and notices | Reproducible builds cannot depend on drifting local checkouts or undocumented mirrors | - Pending |
| Keep ARS ledger and manifests authoritative | Scientific provenance must survive index deletion, corruption, and schema changes | - Pending |
| Use file-base and research graph as rebuildable projections | Graph search adds value without creating a second conflicting source of truth | - Pending |
| Exclude domain-specific assumptions from core abstractions | The plugin should generalize beyond the motivating Chinese event-ontology study | - Pending |

## Evolution

After each phase, move shipped and verified capabilities from Active to Validated, record invalidated assumptions under Out of Scope, and add consequential architectural decisions above. Reassess the Core Value and full scope at each milestone boundary.

---
*Last updated: 2026-07-12 after v1.0 project bootstrap*
