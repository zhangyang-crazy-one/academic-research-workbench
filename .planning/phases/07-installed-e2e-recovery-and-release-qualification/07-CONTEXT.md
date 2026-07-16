# Phase 7: Installed E2E Recovery and Release Qualification - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 7 qualifies the exact installed ARW stage through a representative
research audit, deterministic crash/recovery and fault-injection scenarios,
installed compatibility/MCP/hook/version checks, and a fail-closed technical
and release verdict. It extends the Phase 6 representative fixture and uses
the current local Codex ARS adapter as an external exact dependency. It does
not bundle ARS workflows, silently track a moving latest ARS revision, or turn
technical qualification into publication permission.

</domain>

<decisions>
## Implementation Decisions

### Representative E2E journey and ARS integration

- **D-07-01:** Extend the existing Phase 6 representative fixture rather than
  creating a disconnected test corpus. The installed journey must cover local
  sources and claims, an experiment and figure/result, independent review,
  failed gate, human resolution, crash/resume, and final audit dossier.
- **D-07-02:** Execute a real external ARS adapter smoke using deterministic
  local fixtures with networking disabled. ARW accepts only validated
  route/handoff/result envelopes and remains the canonical evidence writer.
- **D-07-03:** The exact external ARS input is the current local Codex adapter
  tree at `/home/zhangyangrui/.codex/skills/academic-research-suite`, including
  its local reshaping and adapter-side enhancements. The lock must bind its
  `manifest.json`, `VERSION`, router `SKILL.md`, full adapter tree digest,
  upstream source commits/trees, and ARS content tree digest. Phase 7 must not
  auto-track a moving latest revision and must not copy the ARS tree into the
  ARW stage.
- **D-07-04:** Retain only bounded canonical ARS route/handoff/result evidence,
  input/output digests, workflow and adapter identity, error/blocker reasons,
  and redacted command summaries. Full transcripts, private full text,
  credentials, and uncontrolled intermediate payloads are excluded.

### Recovery fault-injection matrix

- **D-07-05:** Use a deterministic fault matrix with stable fault IDs at
  canonical write, fsync, lock, and host-dispatch boundaries. Each scenario is
  an independent subprocess/run root with retained raw evidence, replay input,
  and final verdict.
- **D-07-06:** Parent replay classifies injected failures. A provable final
  tail damage case enters explicit recovery/quarantine; middle-chain damage,
  hash mismatch, manifest mismatch, and lock death remain `BLOCKED`; host or
  process failures follow bounded retry policy rather than being laundered as
  `CANCELLED`.
- **D-07-07:** Fault evidence is parent-owned sidecar evidence containing the
  fault ID, injection boundary, bounded stdout/stderr, file snapshots and
  hashes, process state, and replay verdict. A canonical recovery event is
  appended only after validation.
- **D-07-08:** Run all fault scenarios serially with one independent subprocess
  and run root per case, using the same fixture for source and installed stage
  and a repository-owned bounded `TMPDIR`. Parallel stage/install operations
  are out of scope because they risk memory exhaustion and weaken evidence
  isolation.

### Installed compatibility and provisioning

- **D-07-09:** Codex CLI `0.144.4` and its retained exact host tuple are the
  sole technical qualification baseline. Other versions are explicit
  unsupported/drift observations and fail closed rather than receiving a
  best-effort PASS.
- **D-07-10:** Exercise the package through a local marketplace with the
  source checkout hidden, networking disabled, fresh `HOME`/`CODEX_HOME`, and
  an explicit external ARS root.
- **D-07-11:** Verify manifest discovery, route/version reporting, MCP
  negotiation, CLI lifecycle, official hook observations, stage identity,
  positive allowlist, inventory, SBOM, and build identity as separate gates.
- **D-07-12:** Require `ARW_ARS_ROOT` (or an equivalent controlled path) to
  resolve the external ARS tree and validate it against the integration lock.
  Implicit user paths, missing roots, symlinked roots, and digest drift are
  blocked.

### Evidence, resource, and release boundaries

- **D-07-13:** Retain bounded canonical/sidecar records, raw stream summaries,
  and hashes while excluding secrets, private full text, credentials, and
  absolute-path material from retained evidence.
- **D-07-14:** Run installation, recovery, host qualification, and full
  regression serially with repository-owned temporary roots and explicit
  cleanup/ownership markers. Do not repeat memory-heavy parallel installs.
- **D-07-15:** Keep stage, host, recovery, and dossier evidence in separate
  marked roots with canonical hashes and cold-replay inputs. Hooks, transcripts,
  projections, and graphs remain observations, never authority.
- **D-07-16:** Technical qualification and release qualification remain
  independent. SUP-04/P04-09 and CC BY-NC intended-use, distribution,
  accountable-approval, and permission blockers require accountable human/legal
  evidence and cannot be auto-overridden by a technical PASS.

### the agent's Discretion

- Exact fixture IDs, fault ID names, subprocess wrapper implementation, and
  evidence directory layout, provided all identities and boundaries above are
  explicit and hash-bound.
- Exact unsupported-version reporting format and compatibility matrix file,
  provided the retained `0.144.4` tuple is the only PASS baseline.
- Exact ARS adapter compatibility shim locations, provided local ARS content
  is not silently copied into the ARW stage and the lock observes the current
  external tree.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements

- `.planning/ROADMAP.md` — Phase 7 goal, success criteria, dependencies, and
  requirements VER-02/VER-04/VER-06/VER-08.
- `.planning/REQUIREMENTS.md` — installed compatibility, recovery, E2E, and
  release-fail-closed acceptance obligations.
- `.planning/STATE.md` — current Phase 7 ready-to-plan handoff and retained
  legal blocker.
- `.planning/PROJECT.md` — append-only authority, source provenance,
  compatibility, security, and headless delivery constraints.

### Prior ARW qualification and authority contracts

- `.planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md`
  — sole-writer orchestration, review, hook, and human-gate decisions.
- `.planning/phases/04.1-phase-4-qualification-closure-ars-integration-lock-and-insta/04.1-CONTEXT.md`
  — exact host, external ARS, lock, stage, hook, and release-boundary gates.
- `.planning/phases/04.1-phase-4-qualification-closure-ars-integration-lock-and-insta/04.1-VERIFICATION.md`
  — retained technical qualification evidence and unresolved release gates.
- `.planning/phases/06-scientific-integrity-and-audit-dossier/06-CONTEXT.md`
  — canonical scientific evidence, dossier, freshness, and cold-replay
  decisions.
- `.planning/phases/06-scientific-integrity-and-audit-dossier/06-VERIFICATION.md`
  — final Phase 6 technical PASS/release BLOCKED evidence and retained test
  counts.

### ARW implementation and verification surfaces

- `src/arw/runtime.py`, `src/arw/recovery.py`, `src/arw/journal.py`, and
  `src/arw/reducer.py` — canonical append/replay/recovery semantics.
- `src/arw/manifests.py`, `src/arw/evidence.py`, and
  `src/arw/audit_dossier.py` — immutable manifests, bounded evidence, and
  dossier reconstruction.
- `src/arw/integration_lock.py` — exact ARS/ARW/file-base/Codex/hook/stage
  identity binding and fail-closed validation.
- `src/arw/cli.py`, `bin/arw`, and `scripts/stage-plugin` — installed CLI,
  external ARS provisioning, stage allowlist, and lock validation.
- `scripts/qualify-codex-host`, `scripts/verify-phase-4`, and
  `scripts/verify-phase-6` — exact host canary and staged verification patterns.
- `tests/integration/test_recovery.py`,
  `tests/integration/test_recovery_crash.py`,
  `tests/staged/test_manifest_install.py`,
  `tests/staged/test_mcp_launcher.py`,
  `tests/staged/test_skill_route.py`, and
  `tests/staged/test_phase6_audit_dossier.py` — reusable installed/recovery
  test patterns.
- `tests/fixtures/phase6/representative-run/` and
  `tests/fixtures/recovery/` — deterministic fixture sources for Phase 7.

### Current local ARS adapter

- `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md` — local
  Codex router and adapter boundary.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/manifest.json` —
  adapter version, upstream source commits, excluded paths, and local runtime
  notes.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md`
  — exact local pipeline workflow used by the integration smoke.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/academic-paper/WORKFLOW.md`
  — local reshaped paper workflow; its digest differs from the materialized
  upstream source and must be covered by the external adapter tree digest.
- `vendor/source-manifest.json`, `MODIFICATIONS.md`, and
  `THIRD_PARTY_NOTICES.md` — repository-side pinned source/license inventory.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `src/arw/integration_lock.py` already validates an external exact ARS root,
  adapter version, manifest/source commits, full adapter tree digest, and ARS
  content tree digest; Phase 7 should extend tests/evidence around the current
  local adapter rather than create a second dependency model.
- `scripts/qualify-codex-host` already proves exact stage install, fresh-home
  isolation, bounded result channels, and hook observations.
- `scripts/verify-phase-6` already provides serial evidence-root ownership,
  stage inventory, lock comparison, and separate technical/release verdicts.
- Existing recovery fixtures and `src/arw/recovery.py` provide deterministic
  tail/middle-chain classification patterns.

### Established Patterns

- Parent-only canonical writes and replay-derived state are authoritative;
  hooks, host transcripts, graphs, SQLite, and sidecar evidence are not.
- All canonical bytes are strict/content-addressed; stale, mismatched, or
  unverified external evidence fails closed.
- Stage builds use a positive allowlist and reject private/generated payloads;
  source checkout and external ARS are not silently copied into the stage.
- Heavy verification runs are serial and use repository-owned temporary roots to
  keep memory use bounded and evidence reproducible.

### Integration Points

- `ARW_ARS_ROOT` supplies the current external local ARS adapter to installed
  CLI/lock verification.
- The Phase 6 dossier fixture becomes the canonical E2E run root and receives
  installed-stage, recovery, and release-verdict evidence.
- `build/evidence/phase-04.1-host-canary-*` and the latest Phase 6 integration
  lock provide the retained host/stage baseline for Phase 7.

</code_context>

<specifics>
## Specific Ideas

- The locally installed Codex ARS adapter has deliberate local reshaping beyond
  the materialized upstream tree. A normalized comparison observed local-only
  files and content differences; Phase 7 must qualify the local adapter bytes
  actually used by the host, not silently substitute the upstream snapshot.
- README/operator documentation may describe the adapter as a maintained local
  ARS integration, but must not claim a public fork or redistribution right
  without a pinned source identity and permission evidence.
- The Phase 7 evidence path must remain usable after the prior memory-heavy
  full-install incident by enforcing serial bounded execution.

</specifics>

<deferred>
## Deferred Ideas

- Publishing or redistributing a separate ARS fork with its own upstream
  repository, license/permission record, and release process.
- Automatic tracking of future ARS latest revisions without explicit lock
  refresh and requalification.
- Full ARS source bundling inside ARW stage, desktop UX, cloud coordination,
  and complete Science Workbench v2 paper AST/export.

</deferred>

---

*Phase: 07-installed-e2e-recovery-and-release-qualification*
*Context gathered: 2026-07-16*
