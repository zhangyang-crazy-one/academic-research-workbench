# Phase 7 Pattern Map

## Installed stage and external ARS

| Planned role | Closest existing analog | Reuse pattern |
|---|---|---|
| Lock-bound local ARS smoke | `src/arw/integration_lock.py::_validate_external_ars`, `build_integration_lock`, `tests/unit/test_integration_lock.py` | Validate explicit `ARW_ARS_ROOT` with direct `manifest.json`, `VERSION`, `SKILL.md`, source commits, adapter tree digest, and `ars/` content digest; never infer identity from route fields alone. |
| Installed stage command | `scripts/stage-plugin`, `tests/staged/test_manifest_install.py`, `tests/staged/test_mcp_launcher.py` | Build from positive allowlist, hide source checkout, validate stage inventory/coverage/build identity, and reject bundled `skills/academic-research-suite`. |
| Exact host evidence | `scripts/qualify-codex-host`, `tests/staged/test_phase4_host_qualification.py` | Reuse three fresh-home receipts, explicit result channel, default trust probe, hook observations, redacted evidence, and exact Codex tuple. |
| Phase verifier | `scripts/verify-phase-6`, `scripts/verify-phase-4` | Own a marked evidence root, run commands serially, retain bounded logs/result hashes, compare lock/stage identities, and emit separate technical/release verdicts. |

## Canonical recovery and fault injection

| Planned role | Closest existing analog | Reuse pattern |
|---|---|---|
| Replay/recovery policy | `src/arw/recovery.py`, `src/arw/runtime.py`, `src/arw/journal.py`, `src/arw/reducer.py` | Replay canonical segments/manifests only; distinguish final recoverable tail from middle-chain/hash/manifest damage; append recovery events only through parent writer. |
| Tail/middle-chain tests | `tests/unit/test_recovery_scan.py`, `tests/integration/test_recovery.py`, `tests/integration/test_recovery_crash.py` | Use `tmp_path`, deterministic segment fixtures, injected clocks/status, exact reason codes, and immutable quarantine/evidence. |
| Process/crash boundary | `tests/fixtures/recovery/`, `scripts/verify-phase-4` forced-stop and recovery commands | Preserve raw streams, byte snapshots, status, replay and verdict in sidecar evidence; do not let test control metadata become canonical state. |
| Retry/stale completion | `src/arw/orchestration.py`, `src/arw/scheduler.py`, `tests/integration/test_orchestration_replay.py`, `tests/integration/test_runtime_attempts.py` | Parent materializes prepared/retry/cancel/deadline events before host action; reject duplicate/stale assignment keys; cap fresh attempts at two. |

## Representative scientific audit

| Planned role | Closest existing analog | Reuse pattern |
|---|---|---|
| Fixture/run root | `tests/fixtures/phase6/representative-run/` | Extend immutable integrity, provenance, access, claim, review, and dossier records rather than create a parallel authority format. |
| Dossier cold replay | `src/arw/audit_dossier.py`, `tests/unit/test_audit_dossier.py`, `tests/integration/test_audit_dossier_replay.py`, `tests/property/test_audit_dossier_replay.py` | Rebuild from ledger/manifests/typed evidence, derive canonical hashes, reject forged PASS, preserve blockers and projection-loss state. |
| Review/gate/human evidence | `src/arw/review.py`, `tests/integration/test_human_gates.py`, `tests/integration/test_orchestration_panels.py` | Preserve exact report hashes, minority/dissent, accountable role, prior verdict hash, append-only waiver/correction, and synthesizer separation. |
| Graph/projection loss | `src/arw/graph_projection.py`, `tests/integration/test_graph_authority.py`, `tests/integration/test_graph_rebuild.py` | Delete or corrupt projections and prove canonical state/gate/dossier replay is unchanged; return typed unavailable/corrupt rather than fallback authority. |

## Evidence and resource controls

- Use `build/evidence/phase-07-*` marked roots and `build/tmp/phase-07-*`
  absolute temporary roots; do not use global `/tmp` or parallel stage builds.
- Reuse `canonical_json_bytes`, `FileBinding`, write-once manifests, and
  bounded command capture rather than inventing a second digest format.
- Scan retained evidence and stage for secrets, private full text, credentials,
  symlinks, and absolute workspace paths using the Phase 4–6 private exclusion
  patterns.
- Keep local ARS outside the stage. The stage carries only lock metadata and
  ARW runtime; the external root is supplied explicitly and independently
  verified.

## Likely Phase 7 files

### New

- `scripts/verify-phase-7`
- `tests/integration/test_phase7_installed_e2e.py`
- `tests/integration/test_phase7_fault_matrix.py`
- `tests/staged/test_phase7_qualification.py`
- bounded Phase 7 fixture additions under `tests/fixtures/phase6/representative-run/`

### Extend

- `src/arw/integration_lock.py` only if current local-tree/ARS evidence needs a
  narrowly scoped contract correction
- `src/arw/recovery.py`/`runtime.py`/`orchestration.py` only for tested fault
  injection seams or missing canonical evidence, never for a second writer
- `scripts/stage-plugin`, `scripts/qualify-codex-host`, and existing verifier
  helpers only through backward-compatible bounded options
- staged/schema registries and docs only when new Phase 7 evidence contracts
  require them

No Phase 7 change should modify or stage the external local ARS tree itself.
