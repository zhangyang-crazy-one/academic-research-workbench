---
phase: 1
slug: contract-license-and-executable-baseline
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
---

# Phase 1 - Validation Strategy

> Per-phase validation contract for the installed plugin walking skeleton, source and license gates, canonical event baseline, and confined MCP probe.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with independent `jsonschema` validation |
| **Config file** | `pyproject.toml` - Wave 0 creates it |
| **Quick run command** | `uv run pytest -q tests/unit tests/schema` |
| **Full suite command** | `uv run pytest -q tests/unit tests/schema tests/integration tests/staged` |
| **Phase gate** | `./scripts/verify-phase-1 --clean --evidence-root build/evidence/phase-01` |
| **Estimated runtime** | Quick <30 seconds; full local <180 seconds; authenticated Codex host canary excluded from quick runs |

## Sampling Rate

- **After every task commit:** Run the narrow affected test file plus `uv run pytest -q tests/schema`.
- **After every plan wave:** Run `uv run pytest -q tests/unit tests/schema tests/integration`; add `tests/staged` whenever plugin, launcher, vendor, build, or stage files changed.
- **Before `$gsd-verify-work`:** Run `./scripts/verify-phase-1 --clean --evidence-root build/evidence/phase-01`, including the authenticated fresh-thread Codex route canary.
- **Max feedback latency:** 30 seconds for unit/schema tasks, 180 seconds for local integration/staged tasks.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 0 | PKG-01 | T-01 | Stage validates and installs from an allowlisted tree | staged | `uv run pytest -q tests/staged/test_manifest_install.py` | No - W0 | pending |
| 01-01-02 | 01 | 0 | PKG-02 | T-02 | Fresh installed skill returns a declared ARS family and mode | staged host | `uv run pytest -q -m codex_host tests/staged/test_skill_route.py` | No - W0 | pending |
| 01-01-03 | 01 | 0 | PKG-03 | T-03 | Installed-cache MCP launches without source-checkout paths | staged host | `uv run pytest -q tests/staged/test_mcp_launcher.py` | No - W0 | pending |
| 01-01-04 | 01 | 0 | PKG-04 | T-04 | Version JSON reports plugin, runtime, source, schema, and patch identities | integration | `uv run pytest -q tests/integration/test_version_report.py` | No - W0 | pending |
| 01-02-01 | 02 | 1 | SUP-01 | T-05 | Clean materialization reproduces pinned trees and ordered patches | integration/build | `uv run pytest -q tests/integration/test_source_materialization.py` | No - W0 | pending |
| 01-02-02 | 02 | 1 | SUP-02 | T-05 | Mutated source, patch, lock, or artifact digest blocks the build | integration/build | `uv run pytest -q tests/integration/test_digest_drift.py` | No - W0 | pending |
| 01-02-03 | 02 | 1 | SUP-03 | T-06 | Stage contains component licenses, notices, SBOM, and source manifest | staged | `uv run pytest -q tests/staged/test_supply_chain_inventory.py` | No - W0 | pending |
| 01-02-04 | 02 | 1 | SUP-04 | T-06 | Unknown or incompatible use classification returns release BLOCKED | integration | `uv run pytest -q tests/integration/test_license_gate.py` | No - W0 | pending |
| 01-02-05 | 02 | 1 | SUP-05 | T-07 | Private canaries and denylisted classes never enter the stage | staged/security | `uv run pytest -q tests/staged/test_private_exclusions.py` | No - W0 | pending |
| 01-03-01 | 03 | 1 | RUN-01 | T-08 | Init writes a strict run manifest and `run.initialized` event | integration | `uv run pytest -q tests/integration/test_run_init.py` | No - W0 | pending |
| 01-03-02 | 03 | 1 | RUN-02 | T-08 | One locked writer emits deterministic sequence and hash-chain bytes | unit/integration | `uv run pytest -q tests/unit/test_canonical.py tests/integration/test_journal_replay.py` | No - W0 | pending |
| 01-03-03 | 03 | 1 | FILE-05 | T-09 | Traversal, root, symlink, sensitive-path, and budget denials return no content | security integration | `uv run pytest -q tests/integration/test_mcp_confinement.py` | No - W0 | pending |
| 01-04-01 | 04 | 2 | VER-01 | T-10 | Checked-in schemas match generated models and independently validate MCP fixtures | schema | `uv run pytest -q tests/schema/test_schema_drift.py tests/schema/test_cross_language.py` | No - W0 | pending |

*Status: pending -> green / red / flaky. Planner may rename plan/task IDs, but every requirement row must remain represented.*

## Threat References

| Ref | Threat | Required Control |
|-----|--------|------------------|
| T-01 | Source-only validator pass is mistaken for installed plugin success | Isolated staged marketplace install and fresh host process |
| T-02 | Static skill text is mistaken for executable routing | Authenticated Codex host canary with declared route result |
| T-03 | Launcher depends on developer absolute paths | Installed-cache probe and forbidden-prefix scan |
| T-04 | Version drift is hidden | One machine-readable version report backed by checked-in manifests |
| T-05 | Source, patch, lock, or artifact substitution | Exact digests, clean materialization, ordered patches, negative mutation fixtures |
| T-06 | Mixed licenses are collapsed into an inaccurate project license | Component-specific licenses and explicit PASS/BLOCKED release classifier |
| T-07 | Private research material enters the package | Allowlist staging and forbidden-canary scan |
| T-08 | Concurrent or non-deterministic canonical mutation | Inter-process lock, expected revision, canonical JSON, hash chain, fsync |
| T-09 | MCP leaks files or exhausts output budget | Root-relative safe open, sensitive policy, hard caps, no-content denials |
| T-10 | Python and MCP contracts drift | Checked-in Draft 2020-12 schemas plus independent validators |

## Wave 0 Requirements

- [ ] `pyproject.toml`, `.python-version`, `uv.lock`, and pytest configuration.
- [ ] `tests/unit/test_canonical.py` for deterministic canonical bytes and event hashes.
- [ ] `tests/schema/test_schema_drift.py` and `tests/schema/test_cross_language.py`.
- [ ] `tests/integration/test_run_init.py` and `tests/integration/test_journal_replay.py`.
- [ ] `tests/integration/test_mcp_confinement.py` and repository-owned confinement fixtures.
- [ ] `tests/staged/test_manifest_install.py`, `test_skill_route.py`, `test_mcp_launcher.py`, `test_supply_chain_inventory.py`, and `test_private_exclusions.py`.
- [ ] `scripts/verify-phase-1` evidence orchestrator.

## Recovery Fixture

`tests/fixtures/recovery/seed/` contains fixed run, command and event IDs, fixed UTC timestamps, an immutable input file, declared workflow family/mode, and capability list. The test initializes the run, appends `baseline.probe_recorded`, triggers `SIGKILL` after journal `fsync` and before derived output, then starts a fresh process that replays only the run manifest and JSONL. It must report the last valid revision/hash and prove no duplicate event was appended.

Evidence is preserved under `build/evidence/phase-01/<build-manifest-sha256>/runtime/{init,append,forced-stop,replay}/` with command metadata, stdout, stderr, exit/signal status, journal bytes, replay result, and verdict.

## Confinement Fixture

`tests/fixtures/confinement/` contains an allowed CJK/LaTeX file, an oversized file, a sensitive `.env` canary, a symlink to an outside secret, an unconfigured second root, and a unique outside secret. Parameterized cases cover traversal, absolute outside path, symlink escape, root denial, sensitive path, over-budget request, and valid bounded read.

Every denial must return a typed error, contain no content, omit the outside canary from all captured streams, and write evidence under `build/evidence/phase-01/<build-manifest-sha256>/confinement/<case-id>/`.

## Evidence Contract

- `environment.json` records allowlisted tool and OS versions without dumping secrets.
- `stage/` records inventory, digests, and forbidden-file scan.
- `source/` records materialization, digest checks, license verdict, and SBOM check.
- `plugin/` records validation, install, route, version, and launcher commands and verdicts.
- `schema/` records generated-schema diff and independent Python/MCP validation.
- `runtime/` records init, append, forced-stop, and replay.
- `confinement/` records each request, response, and no-content verdict.
- `summary.json` and `SUMMARY.md` report technical qualification separately from release qualification.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Intended use/distribution classification and any owner permission are substantively valid | SUP-04 | Legal intent and permission authenticity cannot be inferred by an automated test | Review `supply-chain/use-distribution.json`, component licenses, and attached permission evidence; record accountable approval. Automated tests still require missing/unknown data to return BLOCKED. |

## Validation Sign-Off

- [x] All planned requirement rows have automated commands or Wave 0 dependencies.
- [x] Sampling continuity permits no three consecutive tasks without automated verification.
- [x] Wave 0 names every missing test and fixture.
- [x] No watch-mode flags are used.
- [x] Quick feedback target is below 30 seconds; local full-suite target is below 180 seconds.
- [x] `nyquist_compliant: true` is set in frontmatter.

**Approval:** strategy approved for planning on 2026-07-13; implementation evidence pending.
