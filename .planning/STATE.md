---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: ready_to_plan
stopped_at: Phase 2 complete (5/5) — ready to plan Phase 3
last_updated: 2026-07-13T22:41:20+08:00
last_activity: 2026-07-13
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 12
  completed_plans: 12
  percent: 29
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-12)

**Core value:** Every research run must be reproducible, resumable, and auditable from source files through claims, experiments, review gates, and final artifacts.
**Current focus:** Phase 3 — secure files first data plane

## Current Position

Phase: 3 of 7 (Secure Files-First Data Plane)
Plan: Not started
Status: Ready to plan
Last activity: 2026-07-13

Progress: [███░░░░░░░] 29%

## Performance Metrics

**Velocity:**

- Total plans completed: 12
- Average duration: 38 min
- Total execution time: 7.6 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 7 | 347 min | 50 min |
| 02 | 5 | 107 min | 21 min |

**Recent Trend:**

- Last 5 plans: 12 min, 9 min, 14 min, 16 min, 56 min
- Trend: Runtime plans remained compact; final staged qualification included full review closure

*Updated after each plan completion*
| Phase 01 P06 | 188m | 3 tasks | 26 files |
| Phase 01 P07 | 10m | 3 tasks | 15 files |
| Phase 02 P01 | 12 min | 3 tasks | 19 files |
| Phase 02 P02 | 9 min | 3 tasks | 15 files |
| Phase 02 P03 | 14 min | 3 tasks | 19 files |
| Phase 02 P04 | 16 min | 3 tasks | 19 files |
| Phase 02 P05 | 56 min | 3 tasks | 22 files |

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
- [Phase 02]: New manifests bind a registered workflow ID and digest; legacy manifests select one frozen compatibility identity. — This prevents mutable workflow definitions from rewriting historical transition legality while preserving Phase 1 bytes.
- [Phase 02]: Status is a pure projection and opens only an existing read-only lock. — Every status path must remain side-effect-free, including damaged runs without a lock file.
- [Phase 02]: Phase 2 runtime commands require segmented-v1 and legacy events.jsonl remains read-only. — This preserves frozen Phase 1 semantics and prevents append-then-reject partial mutation.
- [Phase 02]: Installed artifact or Passport files are non-authoritative until a hash-binding event accepts them. — Store presence cannot replace canonical ledger authority.
- [Phase 02]: Passport lineage is exact and linear: based-on revision, parent, and superseded hash must match the pre-event reducer state. — Exact lineage prevents implicit branches and stale resume.
- [Phase 02]: Freshness is evaluated from an injected clock and blocks lifecycle/resume without changing historical Passport bytes. — Historical evidence remains immutable while current legality is projected dynamically.
- [Phase 02]: Recovery eligibility is limited to a final malformed, incomplete, or truncated-UTF-8 record after at least one fully validated event. — Accepted-event, middle-chain, manifest, and recovery-binding damage must remain blocked for forensics.
- [Phase 02]: A recovered chain is healthy only when the next segment begins with recovery.completed and its event, original segment, raw copy, and canonical receipt all cross-validate. — Recovery authority must be independently reconstructible from unchanged canonical and forensic bytes.
- [Phase 02]: Status and replay return the last trustworthy prefix for recoverable or blocked damage; only explicit operator recovery writes quarantine or continuation bytes. — Observation and repair remain separate authority boundaries.

### Pending Todos

None yet.

### Blockers/Concerns

- [Release]: SUP-04 remains blocked until intended-use, distribution, accountable approval, and compatible permission evidence exists.
- [Phase 3]: VER-03 must cover race-sensitive file replacement beyond Phase 2 deterministic symlink rejection.
- [Trust]: Unkeyed hashes prove byte consistency, not authenticity if an attacker can rewrite every root of trust.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | Desktop UI, domain packs, team coordination, and telemetry | Deferred | v1.0 roadmap |
| v1.x/v2 | Publication AST/export and additional ingestion/connectors | Deferred | v1.0 roadmap |

## Session Continuity

Last session: 2026-07-13T22:41:20+08:00
Stopped at: Phase 2 complete and independently verified; Phase 3 is ready to plan
Resume file: None
