---
phase: 1
slug: contract-license-and-executable-baseline
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
revised: 2026-07-13
---

# Phase 1 - Validation Strategy

> Validation contract for the installed plugin, license-before-vendoring chain, canonical writer, confined/sanitized native MCP, final build identity, and clean evidence run.

## Test Infrastructure

| Property | Value |
|---|---|
| **Framework** | pytest 9.x plus independent `jsonschema` Draft 2020-12 validation |
| **Config file** | `pyproject.toml` — Plan 01 creates it |
| **Quick command (<30s target)** | `uv run pytest -q tests/unit/test_canonical.py tests/schema/test_schema_drift.py` |
| **Local suite** | `uv run pytest -q tests/unit tests/schema tests/integration tests/staged -m 'not codex_host'` |
| **Host canaries** | `uv run pytest -q -m codex_host tests/staged/test_skill_route.py tests/staged/test_compatibility_probes.py tests/staged/test_mcp_launcher.py` |
| **Clean completion gate** | `./scripts/verify-phase-1 --clean --evidence-root build/evidence/phase-01` |

The quick command alone targets 30 seconds. The clean gate executes pre-vendor legal preflight, network-denied reconstruction, unchanged upstream C tests, ASan+UBSan, separate TSan, legal/SBOM generation, installed canaries, forced-stop replay, confinement, and evidence aggregation.

## Sampling Rate

- After each implementation task: run its narrow command and, once present, schema drift.
- After Wave 1: run Plan 01 package/install/CLI tests.
- After Wave 2: run Plan 02 installed route/compatibility and Plan 03 pre-vendor/source/drift tests; same-wave plans have no overlapping files.
- After Wave 3: run Plan 04 legal/private-stage and Plan 05 canonical/replay tests; same-wave plans have no overlapping files.
- After Wave 4: run direct-native confinement, unchanged upstream C, ASan+UBSan, separate TSan, extended legal, and installed MCP tests.
- After Wave 5: run schema/version tests and the clean completion gate including authenticated host canaries and all native evidence domains.

## Requirement Verification Map

| Task ID | Plan | Wave | Requirement | Automated command | Status |
|---|---:|---:|---|---|---|
| 01-01-03 | 01 | 1 | PKG-01 | `uv run pytest -q tests/staged/test_manifest_install.py tests/staged/test_cli_launcher.py` | pending |
| 01-02-03 | 02 | 2 | PKG-02 | `./scripts/smoke-staged-plugin --route --fresh-home build/isolated/route-home --evidence-root build/evidence/phase-01/route && uv run pytest -q -m codex_host tests/staged/test_skill_route.py tests/staged/test_compatibility_probes.py` | pending |
| 01-03-03 | 03 | 2 | SUP-01 | `./scripts/offline-exec --evidence-root build/evidence/phase-01/source ./scripts/verify-sources && uv run pytest -q tests/integration/test_pre_vendor_license_gate.py tests/integration/test_source_materialization.py` | pending |
| 01-03-03 | 03 | 2 | SUP-02 | `uv run pytest -q tests/integration/test_digest_drift.py` | pending |
| 01-04-02 | 04 | 3 | SUP-03 | `./scripts/license-gate --source-manifest vendor/source-manifest.json --pre-vendor-evidence build/evidence/phase-01/pre-vendor-license --evidence-root build/evidence/phase-01/license && uv run pytest -q tests/staged/test_supply_chain_inventory.py` | pending |
| 01-04-03 | 04 | 3 | SUP-04 | `uv run pytest -q tests/integration/test_license_gate.py` | pending |
| 01-04-03 | 04 | 3 | SUP-05 | `uv run pytest -q tests/staged/test_private_exclusions.py` | pending |
| 01-05-02 | 05 | 3 | RUN-01 | `uv run pytest -q tests/integration/test_run_init.py` | pending |
| 01-05-03 | 05 | 3 | RUN-02 | `uv run pytest -q tests/unit/test_canonical.py tests/integration/test_journal_replay.py` | pending |
| 01-06-03 | 06 | 4 | PKG-03 | `./scripts/smoke-staged-plugin --mcp --fresh-home build/isolated/mcp-home --evidence-root build/evidence/phase-01/mcp-launcher && uv run pytest -q tests/staged/test_mcp_launcher.py` | pending |
| 01-06-02 | 06 | 4 | FILE-05 | `uv run pytest -q tests/integration/test_mcp_confinement.py` | pending |
| 01-07-02 | 07 | 5 | PKG-04 | `uv run pytest -q tests/integration/test_version_report.py` | pending |
| 01-07-01 | 07 | 5 | VER-01 | `uv run pytest -q tests/schema/test_schema_drift.py tests/schema/test_cross_language.py` | pending |

Every Phase 1 requirement appears exactly once in this map and exactly once across PLAN frontmatter.

## Wave 0 / Executed RED Order

- Plan 01 collects and executes package/install/CLI behavior tests, explicitly expecting nonzero before plugin/launcher/stage implementation.
- Plan 02 collects and executes route/compatibility behavior tests before route/host implementation.
- Plan 03 collects and executes pre-vendor/source/drift tests before the preflight script or any `vendor/sources/**` copy.
- Plan 04 collects and executes legal/inventory/private tests before post-materialization legal/stage changes.
- Plan 05 collects and executes run/event/canonical tests before writer implementation; replay is red before failpoint wiring.
- Plan 06 collects and executes direct-native confinement tests against the 0001-only binary before patch 0002.
- Plan 07 writes schema/version tests before schema registry and build-identity wiring.

Collection-only never proves RED. Each RED task runs the behavior tests and explicitly expects failure for the named absent behavior; import, collection, syntax, or unrelated environment failure is rejected.

## Pre-Vendoring License Gate

`scripts/pre-vendor-license-gate` fails if `vendor/sources/**` exists, reconstructs exact clean upstream pins in temporary storage, verifies URL/revision/tree identities, and executes unmodified file-base `license-gate.sh`, policy, both checkers, and notice generator before source copy. It validates canonical ARS/experiment licenses and retains all input/output digests, commands, streams, statuses, generated notices, and the absent-vendor assertion under `build/evidence/phase-01/pre-vendor-license/`. Plan 03 may populate `vendor/sources/**` only after verifying this receipt.

## Offline Source Reproduction Gate

`scripts/offline-exec` activates Linux network denial using `bwrap --unshare-net` or `unshare --user --map-root-user --net`, audits with `strace -f -e trace=network`, and fails when denial is unavailable or AF_INET/AF_INET6 activity is attempted. SUP-01 evidence retains mechanism, syscall audit, argv, streams, and status.

## Native Safety Gate

Plan 06 and `scripts/verify-phase-1` must execute the byte-identical pinned upstream C test suite after patch 0002 in three network-denied clean builds:

1. normal build and unchanged upstream suite at `native/upstream/`;
2. combined ASan+UBSan build/run at `native/asan-ubsan/` with sanitizer findings fatal;
3. separate TSan build/run at `native/tsan/` with race findings fatal and no ASan combination.

Each domain retains compiler/linker flags, compiler identity, source/patch/binary digests, unchanged test-tree hash/inventory, argv, streams, status, sanitizer report, and network syscall audit. Missing, skipped, modified-test, unsupported-without-explicit-fail, or failing native evidence blocks technical PASS. The post-0002 legal gate reruns policy/checkers/notice generation over every patch and C/Python/new dependency.

## Installed Runtime Isolation Gate

Installed CLI/MCP tests use unrelated cwd, isolated HOME/CODEX_HOME, cleared PYTHONPATH, `PYTHONNOUSERSITE=1`, inaccessible repository source, and disabled network. Python uses only `$CODEX_HOME/arw/runtime/<identity>/venv` from the installed wheelhouse. Tests reject source, Paper4Master, Examination, or developer-home prefixes.

## Recovery Fixture

`tests/fixtures/recovery/seed/` contains fixed run/command/event IDs, timestamps, immutable input, workflow family/mode, and capabilities. The test initializes, appends `baseline.probe_recorded`, sends SIGKILL after journal fsync and before derived output, then replays only manifest+JSONL in a fresh process. Evidence records signal/status, exact bytes/hashes, last revision/hash, and no duplicate.

## Confinement Fixture

`tests/fixtures/confinement/` contains bounded CJK/LaTeX content, oversized content, `.env`, escaping symlink, unconfigured root, and unique outside secret. Cases cover traversal, absolute outside path, symlink escape, root denial, sensitive path, over-budget, and bounded success. Every denial is typed/no-content with no canary leak. A direct-native test proves enforcement is in file-base. Windows junction behavior remains unclaimed in the Linux Phase 1 baseline.

## Legal and Supply-Chain Evidence

- Preserve and execute the pre-vendor native gate before source copy.
- After materialization and after patch 0002, execute the extended gate over policy, checkers, notice generator, every patch, all C/Python/new dependencies, first-party wheel, schemas, native binary, and exact stage.
- `technical_qualification` may be PASS while `release_qualification` is BLOCKED. Missing use/distribution or permission evidence must produce BLOCKED with evidence-needed fields.

## Evidence Contract

- `environment/`: allowlisted OS/tool/host identities, no secrets.
- `pre-vendor-license/`: exact clean pins, absent-vendor assertion, native policy/checkers/generator, notices, raw streams/status.
- `source/`: network denial, syscall audit, materialization, patch/build, drift.
- `license/`: raw post-materialization/post-0002 gate, notices, SBOM, use/distribution, verdict.
- `native/{upstream,asan-ubsan,tsan}/`: unchanged suite hashes, flags, raw runs, sanitizer/network audits.
- `stage/`: exact inventory, hashes, validation/install, private scans.
- `plugin/`: route, CLI/MCP launchers, installed version; all convergence attempts.
- `schema/`: generation diff and independent Python/native validation.
- `runtime/`: init, append, forced-stop, replay.
- `confinement/`: every request/result/no-content verdict.
- `summary.json` and `SUMMARY.md`: independent technical and release qualification.

## Manual External Evidence

| Behavior | Requirement | Why external | Expected state without evidence |
|---|---|---|---|
| Intended use/distribution and permission authenticity | SUP-04 | Automation cannot determine legal intent or authenticate permission | technical PASS / release BLOCKED |
| Codex host authentication | PKG-02, PKG-03 | The CLI may require user authentication | dynamic authentication gate, then retry same probe |

## Validation Sign-Off

- [x] Seven plan waves and validation waves match.
- [x] Every requirement has exactly one owner and an automated command.
- [x] Every RED contract executes behavior tests and expects failure before implementation.
- [x] Pre-vendor native legal tooling executes before `vendor/sources/**` copy.
- [x] Post-patch gate covers patches, policy/checkers/notices, and all C/Python/new dependencies.
- [x] Unchanged upstream, ASan+UBSan, and separate TSan runs are network-denied and required by the clean gate.
- [x] Installed tests remove repository/PYTHONPATH/network access.
- [x] Raw evidence and release BLOCKED semantics are explicit.
