# Phase 7: Installed E2E Recovery and Release Qualification — Research

**Researched:** 2026-07-16
**Domain:** installed Codex plugin qualification, deterministic crash/recovery,
representative research audit, and fail-closed release evidence
**Confidence:** HIGH for the existing ARW/runtime/stage contracts; MEDIUM for
the new representative installed E2E until its first retained run is produced

## Planning basis

Phase 7 is downstream of the technically qualified Phase 6 dossier and the
Phase 04.1 exact host/install lock. The phase must qualify installed bytes and
replayable evidence, not source-checkout imports or conversation state. The
release verdict remains independent from technical qualification and must stay
BLOCKED while SUP-04/P04-09 and CC BY-NC intended-use, distribution,
accountable-approval, and permission evidence are unresolved.

The user's locked discussion decisions are:

- Extend `tests/fixtures/phase6/representative-run/` into one installed
  source → claim → experiment → figure/result → independent-review → failed
  gate → human-resolution → crash/resume → dossier journey.
- Run a real, deterministic ARS adapter smoke using the current local Codex
  adapter tree at `/home/zhangyangrui/.codex/skills/academic-research-suite`,
  with networking disabled. ARS remains external and is not copied into the
  ARW stage.
- Preserve local ARS reshaping and adapter-side enhancements, but bind the
  exact observed `manifest.json`, `VERSION`, router `SKILL.md`, adapter tree,
  ARS content tree, and upstream source commits/trees. Do not resolve moving
  latest revisions at runtime.
- Use bounded canonical/sidecar evidence and deterministic serial execution
  with repository-owned `TMPDIR` to avoid the prior memory-heavy install
  incident.

## Local ARS adapter inspection

The local adapter is `0.1.20` and its manifest binds
`academic-research-skills@c22c17eed8a5753aa60681be9734919f2e2f5b42` and
`experiment-agent@9b063fa895eaf1f63ac99ac03f924f8d31aa8d26`. It advertises the
Codex router in `SKILL.md`, the pipeline entry in
`ars/academic-pipeline/WORKFLOW.md`, and a Codex-specific adapter profile.

A normalized inventory comparison on 2026-07-16 found 1,034 files in the
local `ars/` tree versus 1,027 mapped files in the repository's materialized
upstream source. There were 24 local-only paths and 24 content-different paths
after mapping local `WORKFLOW.md` names to upstream `SKILL.md` names. Examples
include local paper/research references, experiment-agent material, shared
manuscript boundary content, and Codex validator/adaptation files. This means
the upstream commit alone is not the runtime identity. `manifest.json`, the
adapter version files, full adapter tree digest, and ARS content tree digest
must be observed from the actual local root.

`src/arw/integration_lock.py::_validate_external_ars` already checks:

- external root safety and direct files for `manifest.json`, `VERSION`, and
  `SKILL.md`;
- adapter name/version agreement at all three locations;
- external manifest source commits against `vendor/source-manifest.json`;
- full adapter and `ars/` content tree digests;
- `bundled: false` and the stage rejection of `skills/academic-research-suite`.

Phase 7 should test this existing contract against the real local adapter and
exercise the installed CLI's explicit `ARW_ARS_ROOT` path. It should not add a
second unpinned dependency resolver or claim that the local tree is a public
fork without an independently pinned repository and permission record.

## Existing implementation patterns

### Installed stage and host

- `scripts/stage-plugin` builds the first-party wheel, applies a positive
  allowlist, writes `stage-inventory.json`, SBOM/build identity, and validates a
  supplied integration lock. It rejects symlinks and private/generated paths.
- `scripts/qualify-codex-host` installs exact stage bytes through a local
  marketplace into three fresh homes, proves default hook trust behavior,
  exercises the controlled `/work/result` channel, and retains redacted canary
  receipts without credentials or absolute paths.
- `build/evidence/phase-04.1-host-canary-20260715i/` is the latest retained
  host baseline; its integration lock binds Codex `0.144.4`, ARS `0.1.20`,
  hook/stage digests, file-base patch identity, and the blocked legal verdict.
- `scripts/verify-phase-6` is a reusable serial verifier: it owns an evidence
  root, runs source/phase/prior regression commands, builds and validates a
  locked stage, records identities and stage inventory, and emits separate
  technical/release verdicts.

### Canonical runtime and recovery

- `src/arw/runtime.py`, `journal.py`, `reducer.py`, and `recovery.py` are the
  authority boundary. Recovery eligibility is derived from canonical
  `run-manifest.json` plus events/segments, not projections or transcripts.
- Existing fixtures and tests cover recoverable final tails, malformed or
  truncated records, middle-chain damage, duplicate events, stale revisions,
  lock contention, and recovery receipts. Phase 7 should extend these with
  deterministic process-kill/I/O/space/lock-death injection at named write and
  host-dispatch boundaries.
- Fault evidence should be a parent-owned sidecar bundle. It must retain a
  stable fault ID, injected boundary, bounded raw streams, file/hash snapshots,
  process status, replayed state, and the final reason code. Only a validated
  recovery operation may append a canonical recovery event.

### Scientific audit journey

- `src/arw/audit_dossier.py` assembles a canonical replay-first dossier and
  refuses forged or empty technical PASS inputs. The Phase 6 fixture already
  contains integrity receipt, experiment provenance, access decision, claim
  capabilities, and dossier material suitable for extension.
- `src/arw/review.py` and the Phase 4 panel contracts retain independent report
  hashes, minority/dissent findings, and synthesizer separation. The installed
  E2E must demonstrate these records survive crash/resume and appear in the
  final dossier without promoting a transcript or graph projection.
- Phase 5 graph outputs are disposable. A graph/index loss or stale projection
  must not alter the canonical gate, recovery outcome, or dossier verdict.

## Requirement coverage and gaps

| Requirement | Phase 7 truth | Current gap / planned proof |
|---|---|---|
| VER-02 | Installed tests exercise manifest, route, launcher, MCP, hooks, version | Existing staged tests and host canary are separate; add one installed E2E command that binds all receipts to the current stage/lock. |
| VER-04 | Hard termination, torn writes, I/O failure, disk exhaustion, lock death, duplicate delivery, stale completion preserve evidence and block stale authority | Unit/integration recovery exists, but a Phase 7 deterministic fault matrix and installed-process crash bundle are not yet retained. |
| VER-06 | One representative E2E fixture covers sources, claim, experiment, figure/result, review, failed gate, human resolution, crash/resume, final dossier | Phase 6 fixture is canonical but not yet run end-to-end from installed stage with ARS smoke and recovery. |
| VER-08 | Release qualification fails on missing/stale/unresolved licensing, integrity, recovery, security, compatibility, or stage evidence | Phase 6 provides technical/release separation and legal blockers; Phase 7 must aggregate all gates and prove each missing/tampered evidence case fails closed. |

## Threat model

| Threat | Required mitigation/evidence |
|---|---|
| Installed test accidentally imports source checkout | Hide the checkout, use a local marketplace, verify installed tree identity against stage, and reject source paths in retained evidence. |
| ARS local tree changes without lock refresh | Require explicit `ARW_ARS_ROOT`; compare manifest/version/router/adapter/content digests and upstream commits; fail closed on any mismatch. |
| Crash leaves a stale proposal or partial event canonical | Inject faults before/after each write boundary, kill the child, replay only canonical bytes, and require parent recovery admission before continuation. |
| Disk/IO/lock fault is mislabeled cancelled | Bind fault class to policy and assert bounded retry/recovery/block reason codes in event sequence tests. |
| Duplicate or stale worker result is accepted after resume | Preserve assignment/attempt keys and replay cursor; reject duplicate/stale result envelopes before acceptance. |
| Full-text, credential, or absolute path leaks into evidence/stage | Redact streams, enforce byte/path ceilings, scan evidence and stage, and require positive inventory coverage. |
| Graph, hook, or transcript becomes release authority | Rebuild dossier/gate from canonical ledger/manifests and compare before/after projection/hook failure snapshots. |
| Technical PASS is mistaken for distribution permission | Emit separate technical/release verdicts with retained SUP-04/P04-09/permission blockers and no auto-waiver. |
| Parallel install exhausts memory or mixes evidence roots | Run all heavy commands serially with repo-local bounded `TMPDIR`, unique markers, and cleanup ownership. |

## Recommended plan slices

1. **Installed ARS/stage qualification** — add a lock-bound local ARS smoke,
   installed E2E launcher, stage/source-hidden checks, MCP/CLI/version/hook
   receipts, and local adapter identity tests.
2. **Deterministic recovery matrix** — add fault injection controls and tests
   for all required failure classes, process kill/replay, sidecar evidence,
   retry budget, stale/duplicate results, and crash-safe canonical sequences.
3. **Representative installed research audit** — extend the Phase 6 fixture to
   run from installed bytes, consume bounded ARS route evidence, preserve
   independent review/dissent/human gate evidence, and cold-replay the dossier
   after projection loss.
4. **Release aggregation and qualification** — aggregate VER-02/04/06/08,
   inventory/SBOM/build identity, host canary, recovery bundle, and legal
   verdicts; add tamper/missing-evidence fail-closed probes and a serial full
   regression/staged verifier.

## Validation Architecture

No network or package installation is required. All commands use the frozen
`.venv`, `UV_OFFLINE=1`, `PYTHONNOUSERSITE=1`, and a repository-owned absolute
`TMPDIR`.

| Gate | Command / evidence | Purpose |
|---|---|---|
| Quick | Focused installed, recovery, ARS lock, dossier, and replay pytest subsets | Fast contract feedback after each slice. |
| ARS/stage | `./scripts/stage-plugin --clean --integration-lock ...` plus local `ARW_ARS_ROOT` smoke and `scripts/qualify-codex-host` | Exact stage, external local ARS, host, hook, and result-channel proof. |
| Recovery | Deterministic fault matrix command with one scenario/run root per case | Retain raw sidecar evidence, replay sequence, and reason codes. |
| E2E | Installed representative fixture command with source checkout hidden | Prove VER-06 from installed bytes and final dossier. |
| Aggregation | New Phase 7 verifier, serial and fail-closed | Produce technical/release verdicts and named blockers. |
| Full | Serial non-host regression plus staged/host suites | Cross-phase regression without memory-heavy parallel install. |

Every required check must retain raw status and canonical digest evidence. No
test may be deleted or xfailed to obtain a green technical verdict. A technical
PASS remains compatible with a release BLOCKED result.

## Official/local references

- Local ARS Codex adapter:
  `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md`
- Local ARS manifest:
  `/home/zhangyangrui/.codex/skills/academic-research-suite/manifest.json`
- Project integration lock implementation: `src/arw/integration_lock.py`
- Installed stage and host scripts: `scripts/stage-plugin`,
  `scripts/qualify-codex-host`, `scripts/verify-phase-6`
- Canonical recovery: `src/arw/runtime.py`, `src/arw/journal.py`,
  `src/arw/reducer.py`, `src/arw/recovery.py`
- Prior exact host evidence:
  `build/evidence/phase-04.1-host-canary-20260715i/integration-lock.json`
- Prior Phase 6 verifier:
  `build/evidence/phase-06-final-verifier/verdict.json`

The local adapter tree is the phase's external exact input; the pinned
upstream repository commits remain provenance fields, not a substitute for the
actual local adapter bytes used by the host.
