---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 2 context gathered
last_updated: "2026-07-13T12:25:03.374Z"
last_activity: 2026-07-13 -- Phase 02 planning complete
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 12
  completed_plans: 7
  percent: 14
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-12)

**Core value:** Every research run must be reproducible, resumable, and auditable from source files through claims, experiments, review gates, and final artifacts.
**Current focus:** Phase 2 — durable provenance runtime

## Current Position

Phase: 2
Plan: Not started
Status: Ready to execute
Last activity: 2026-07-13 -- Phase 02 planning complete

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 12
- Average duration: 30 min
- Total execution time: 2.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 7 | - | - |

**Recent Trend:**

- Last 5 plans: 24 min, 31 min, 39 min, 30 min, 25 min
- Trend: Installed baseline converging

*Updated after each plan completion*
| Phase 01 P06 | 188m | 3 tasks | 26 files |
| Phase 01 P07 | 10m | 3 tasks | 15 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: v1.0 uses seven sequential MVP phases derived from the researched dependency chain, with verification evidence growing from Phase 1 through installed-package qualification.
- [Architecture]: Canonical authority remains the sole-writer append-only ledger and immutable manifests; file and research graphs are disposable projections only.
- [Scope]: Desktop UI, Chinese-military-specific assumptions, canonical graph writes, worker or hook canonical writes, and hook-only enforcement remain outside v1.
- [Phase 01]: Runtime identity is the SHA-256 of the staged wheelhouse lock; cache-local environments live only under CODEX_HOME. — This makes dependency drift create a new environment and prevents mutable source or user-site fallback.
- [Phase 01]: Installed qualification uses an isolated repo-owned marketplace with the source checkout hidden and networking disabled. — PKG-01 must be demonstrated from exact installed bytes rather than from repository imports.
- [Phase 01]: The plugin manifest uses LicenseRef-Academic-Research-Workbench-Mixed. — The collective plugin must not collapse CC BY-NC and MIT component identities into a blanket MIT label.
- [Phase 01]: Installed route canary is academic-pipeline / inline-role-prompts with ARS 0.1.19 and experiments disabled. — This matches the current adapter without claiming deferred orchestration or experiment ownership.
- [Phase 01]: Plugin-native custom-agent distribution remains unproven; use native Codex subagents with immutable assignment-injected roles. — The supported host contract proves native subagents but not plugin-distributed custom-agent registration.
- [Phase 01]: Plugin hooks are observational and read-only, never authorization or canonical-state enforcement. — Untrusted hooks can be skipped, so route correctness and scientific authority cannot depend on them.
- [Phase 01]: PKG-02 host PASS requires installed command_execution evidence; schema-shaped model output alone is rejected. — Attempt 008 proved exact installed bytes while attempts without command evidence remained defects.
- [Phase 01]: Receipt-bound source archives are the only permitted input to materialization before vendor/sources exists.
- [Phase 01]: Offline execution requires a changed network namespace plus syscall tracing and rejects every AF_INET or AF_INET6 attempt.
- [Phase 01]: The generated file-base binary remains ignored while its exact digest and build-evidence digest are bound into the source manifest.
- [Phase 01]: Post-materialization qualification executes the preserved file-base gate, policy, both checkers, and notice generator before extending their inventory. — This preserves upstream legal semantics while adding manifest and dependency closure.
- [Phase 01]: Technical provenance hashes do not satisfy intended-use, distribution, approval, or permission evidence; release remains BLOCKED. — Private repository status and technical evidence cannot establish CC BY-NC compatibility or owner permission.
- [Phase 01]: The distributable stage is built and revalidated from an exact positive allowlist whose files are individually digest-covered. — This prevents undeclared or private material and symlinks from crossing the release boundary.
- [Phase 01]: Canonical requests never choose sequence, resulting revision, previous hash, or event hash; the locked writer derives them from fully replayed durable state.
- [Phase 01]: Fresh recovery uses only run-manifest.json and events.jsonl; hooks, transcripts, projections, and evidence remain non-authoritative.
- [Phase 01]: The test-only forced-stop boundary is SIGKILL immediately after journal fsync and before CLI output.
- [Phase 01]: Recovery evidence is parent-side and non-authoritative, retaining relative argv/cwd, allowlisted environment, raw streams, status, byte snapshots, hashes, replay, and verdict only.
- [Phase 01]: Filesystem confinement is enforced inside the native MCP; launcher and host configuration are not the security boundary. — Policy evaluation, descriptor-relative no-follow traversal, and content ceilings must remain effective for every client path.
- [Phase 01]: Native safety evidence uses separate clean normal, ASan+UBSan, and TSan builds under network denial. — TSan is incompatible with ASan, and distinct retained evidence prevents one sanitizer configuration from masking another.
- [Phase 01]: The installed MCP launcher requires explicit allowed-root, capability identifier, and cache configuration and resolves only a plugin-root-relative libexec binary. — Installed qualification must not inherit source paths, PYTHONPATH, an implicit root, or an operator-specific cache.
- [Phase 01]: Phase 1 build identity is a stage payload, not a source constant; installed version rejects absent, outside-root, symlinked, or schema-invalid identity bytes. — Installed claims must bind exact staged bytes and cannot fall back to source checkouts or hard-coded versions.
- [Phase 01]: Technical qualification requires all retained evidence gates, while release remains BLOCKED until SUP-04 human legal evidence is supplied. — Private repository status and technical provenance do not establish intended use, authorization, or CC BY-NC compatibility.

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: Intended use and distribution class must be recorded; incompatible bundled licenses require permission or replacement before release qualification.
- [Phase 1]: Installed MCP launcher behavior, native/custom-agent evidence, supported OS boundary, and root-confinement behavior are empirical gates rather than assumptions.
- [Phase 1]: Recovery fixtures must start with the executable baseline and retain raw evidence as later fault cases are added.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | Desktop UI, domain packs, team coordination, and telemetry | Deferred | v1.0 roadmap |
| v1.x/v2 | Publication AST/export and additional ingestion/connectors | Deferred | v1.0 roadmap |

## Session Continuity

Last session: 2026-07-13T11:28:05.205Z
Stopped at: Phase 2 context gathered
Resume file: .planning/phases/02-durable-provenance-runtime/02-CONTEXT.md
