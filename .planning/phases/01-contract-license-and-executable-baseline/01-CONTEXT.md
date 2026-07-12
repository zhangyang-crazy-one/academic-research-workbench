# Phase 1: Contract, License, and Executable Baseline - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning
**Source:** PRD Express Path (`.planning/REQUIREMENTS.md`) plus confirmed project decisions

<domain>
## Phase Boundary

Phase 1 proves that the repository can produce a cleanly installed, headless Codex plugin walking skeleton from pinned and legally classified inputs. The vertical slice must install the plugin, route one ARS task, initialize and append one canonical event through a sole-writer runtime, invoke the bundled root-confined MCP against a fixture, replay the event, and preserve machine-readable evidence.

This phase freezes only the contracts required by downstream work. It does not implement the full runtime state machine, production retrieval/indexing, complete subagent orchestration, semantic graph, or scientific audit dossier.

</domain>

<decisions>
## Implementation Decisions

### D-01 Plugin identity and installability
- The product name is `Academic Research Workbench`; the plugin/repository slug is `academic-research-workbench`.
- The repository must contain a valid `.codex-plugin/plugin.json`, one routable skill, MCP configuration, hook declarations or stubs that match supported plugin contracts, and stable launcher entrypoints.
- Validation must exercise a staged or installed plugin path, not only the source checkout.

### D-02 Headless walking skeleton
- The first executable slice is install -> skill route -> runtime init/append/replay -> bounded MCP fixture read -> evidence output.
- No desktop, browser, or synthetic UI is required. CLI output and versioned JSON/Markdown artifacts are the user interaction for Phase 1.
- A successful demo must be repeatable from a clean checkout and must not depend on absolute paths into Paper4Master, Examination, or the developer's home directory.

### D-03 Canonical authority
- A short-lived Python control-plane CLI is the only canonical writer.
- Canonical events are deterministic, sequence ordered, and hash chained from the first Phase 1 fixture.
- SQLite, FTS, graph data, hook logs, transcripts, and generated state are projections or observations, never authority.
- Hooks and workers cannot write accepted state directly.

### D-04 Source pinning and bundling
- Pin file-base to upstream commit `ee68144af5453addda995a27cce8142999f318fb` and preserve the existing Paper4Master patch as an ordered, hashed patch input.
- Pin the selected ARS 0.1.19 source snapshot and record its exact tree digest and upstream provenance before adapting it.
- Materialize reproducible source snapshots and patch series; do not depend on mutable submodules, upstream branches, ignored local checkouts, or runtime network clones.
- Preserve upstream license texts, modification markings, third-party notices, source manifests, dependency locks, and SBOM inputs.

### D-05 Licensing gate
- ARS/experiment-agent CC BY-NC 4.0 content and file-base MIT content must remain separately identified; the collective plugin must not be labeled simply MIT.
- Private repository status is not treated as proof of noncommercial use.
- Development may proceed, but release qualification must fail until intended use/distribution classification and any required owner permission are recorded.
- The staged package must exclude private papers, extracted full text, run data, credentials, and indexes by default.

### D-06 MCP confinement probe
- The MCP process receives explicit allowed roots and enforces path, symlink/junction, sensitive-file, and output-budget restrictions internally.
- Hooks may warn or hydrate context but are not accepted as the filesystem security boundary.
- Phase 1 may use a thin fixture-level MCP command surface, but traversal, escape, disallowed-root, sensitive-path, and over-budget probes must be executable and preserve evidence.

### D-07 Version and schema identity
- One command must report plugin, runtime, ARS snapshot, file-base snapshot, patch set, and schema versions.
- Cross-language contracts use checked-in JSON Schema with independent validation at the runtime/MCP boundary.
- Source, patch, schema, and staged-artifact digest drift is a build failure.

### D-08 Compatibility probes
- Installed MCP launcher resolution, custom-agent distribution, Codex hook behavior, experiment ownership, operating-system support, and exact retrieval budgets are empirical probes rather than assumed product capabilities.
- Native Codex subagents plus immutable assignment-injected ARS roles are the required fallback; plugin-native custom-agent registration is optional unless proven by the supported contract.
- Controlled experiment execution remains disabled; Phase 1 only records the decision/probe contract for later phases.

### D-09 Verification evidence
- Every Phase 1 smoke, schema, digest, install, launcher, confinement, and recovery probe writes inspectable raw output plus a concise verdict.
- The seed recovery case includes init, append, forced stop, replay, and last-valid-revision evidence.
- Tests must assert behavior from a clean staged package and use repository-owned fixtures.

### the agent's Discretion
- Exact Python package layout, CLI framework or standard-library argument parsing, build tool details, and test runner organization.
- Whether the append-only Phase 1 journal uses one file or sealed segments, provided later crash/fault testing can evolve without rewriting accepted evidence.
- Initial supported OS matrix; Linux x86_64 may be the first proven target if other platforms remain explicitly unclaimed.
- Exact byte, row, page, and timeout defaults for Phase 1 fixtures, provided limits are explicit, small, and reported in tool results.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and scope
- `.planning/PROJECT.md` - Core value, hard constraints, source-of-truth rule, and explicit exclusions.
- `.planning/REQUIREMENTS.md` - Atomic v1 requirements and release acceptance criteria.
- `.planning/ROADMAP.md` - Phase 1 goal, mapped requirements, and success criteria.
- `.planning/research/SUMMARY.md` - Resolved research decisions, probes, licensing gates, and dependency order.

### Integration architecture
- `docs/architecture/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md` - Prior ARS/Open Science/file-base integration design and phased exit gates.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md` - Current ARS 0.1.19 router and Codex adapter behavior.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/LICENSE` - Actual ARS license text to verify before bundling.

### Plugin conventions
- `/home/zhangyangrui/.codex/skills/.system/plugin-creator/SKILL.md` - Required Codex plugin manifest and scaffold workflow.
- `/home/zhangyangrui/.codex/skills/.system/skill-creator/SKILL.md` - Skill packaging and instruction-quality rules.

### File-base baseline
- `/home/zhangyangrui/orca/projects/Paper4Master/scripts/build-file-base-mcp` - Existing reproducible-build wrapper baseline.
- `/home/zhangyangrui/orca/projects/Paper4Master/scripts/file-base-mcp` - Existing allowed-root launcher baseline.
- `/home/zhangyangrui/orca/projects/Paper4Master/patches/file-base-server-name.patch` - Existing local patch to preserve and hash.
- `/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/LICENSE` - Upstream file-base license.
- `/home/zhangyangrui/orca/projects/Paper4Master/codebase-memory-mcp-file-code-analysis.md` - Empirical capability and gap analysis.

</canonical_refs>

<specifics>
## Specific Ideas

- Keep fixture content multilingual and domain-neutral: include CJK and LaTeX text without embedding Chinese-military ontology assumptions.
- Emit a single `doctor` or `version --json` surface that can be used by users, tests, and audit bundles.
- Preserve command stdout/stderr, exit status, hashes, environment identity, and staged package inventory under a deterministic evidence directory.
- Treat an unresolved license classification as a successful technical probe with a BLOCKED release verdict, not as a reason to falsify or omit the gate.

</specifics>

<deferred>
## Deferred Ideas

- Full runtime lifecycle, Passport checkpointing, stale worker rejection, and comprehensive fault recovery belong to Phase 2.
- Production files-first indexing and research-format retrieval belong to Phase 3.
- Full subagent execution, independent reviewer panels, and human gate UX belong to Phase 4.
- Semantic graph projection and evidence-chain queries belong to Phase 5.
- Complete integrity receipts and audit dossier belong to Phase 6.
- Cross-matrix installed-package release qualification belongs to Phase 7.
- Desktop UI, domain packs, remote collaboration, and telemetry remain v2 or later.

</deferred>

---

*Phase: 01-contract-license-and-executable-baseline*
*Context gathered: 2026-07-12 via PRD Express Path*
