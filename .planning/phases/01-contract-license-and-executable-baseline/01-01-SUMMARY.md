---
phase: 01-contract-license-and-executable-baseline
plan: 01
subsystem: packaging
tags: [python, uv, hatchling, pytest, codex-plugin, offline-wheelhouse]

requires: []
provides:
  - Valid mixed-license Codex plugin shell with a thin routable skill
  - Hash-locked offline Python wheelhouse for Linux x86_64 on Python 3.13 and 3.14
  - Positive-allowlist stage builder and isolated installed-plugin smoke runner
  - Executable PKG-01 acceptance tests and sanitized raw install evidence
affects: [01-02-routing, 01-03-supply-chain, 01-06-mcp-launcher, 01-07-build-identity]

tech-stack:
  added: [Python 3.14.6, uv 0.11.28, hatchling 1.31.0, pytest 9.1.1, pydantic 2.13.4, jsonschema 4.26.0, portalocker 3.2.0]
  patterns: [positive-allowlist staging, installed-path testing, hash-locked offline bootstrap, isolated local marketplace]

key-files:
  created:
    - pyproject.toml
    - .codex-plugin/plugin.json
    - bin/arw
    - scripts/stage-plugin
    - scripts/smoke-staged-plugin
    - tests/staged/test_manifest_install.py
    - tests/staged/test_cli_launcher.py
    - vendor/python/wheelhouse.lock.json
  modified: []

key-decisions:
  - "Runtime identity is the SHA-256 of the staged wheelhouse lock; cache-local environments live only under CODEX_HOME."
  - "The installed package is qualified through an isolated repo-owned marketplace and execution with the source checkout hidden and networking disabled."
  - "The collective plugin uses LicenseRef-Academic-Research-Workbench-Mixed rather than collapsing component licenses into MIT."

patterns-established:
  - "Installed bytes only: launchers resolve the plugin root from their own installed path and never import repository source."
  - "Exact stage: a positive allowlist is copied into a temporary stage, verified, and atomically promoted."
  - "Evidence hygiene: commands, streams, statuses, digests, and verdicts are retained with absolute source/home prefixes replaced by stable tokens."

requirements-completed: [PKG-01]

duration: 24 min
completed: 2026-07-13
---

# Phase 1 Plan 1: Python Package and Installed-Plugin Bootstrap Summary

**A mixed-license Codex plugin installs from an exact allowlisted stage and runs a hash-locked Python package offline from cached installed bytes.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-07-13T01:34:02Z
- **Completed:** 2026-07-13T01:58:24Z
- **Tasks:** 3
- **Files modified:** 36

## Accomplishments

- Froze Python 3.14.6 development with support for Python 3.13 through 3.14, an exact uv lock, and 23 hash-inventoried Linux wheels covering both CPython ABIs.
- Created a validator-clean plugin manifest, thin model-invocable skill, and stage-relative launcher that bootstraps only from verified installed wheels under a lock and atomic completion marker.
- Built and installed the exact allowlisted stage through an isolated Codex marketplace, then ran its cached CLI outside the checkout with the repository hidden, networking disabled, and inherited Python state removed.
- Preserved stage inventory, per-file digests, validator/install/launcher commands, streams, statuses, redaction policy, and machine verdicts.

## Task Commits

Each task was committed atomically:

1. **Task 1: Freeze package inputs and execute RED installed-path tests** - `1f8ceba` (test)
2. **Task 2: Implement valid plugin shell and offline installed launcher** - `f9a5cd1` (feat)
3. **Task 3: Build and install the exact allowlisted stage** - `b59c65a` (feat)

## Files Created/Modified

- `.python-version`, `pyproject.toml`, `uv.lock` - Frozen Python, build, dependency, and test contract.
- `vendor/python/wheelhouse/**`, `vendor/python/wheelhouse.lock.json` - Offline Python 3.13/3.14 wheels with registry, version, uv-lock relationship, and SHA-256 inventory.
- `.codex-plugin/plugin.json` - Valid plugin identity with mixed-license LicenseRef and complete interface fields.
- `skills/academic-research-workbench/SKILL.md` - Thin route declaration targeting `bin/arw route --json`.
- `bin/arw` - Installed-path interpreter selection, wheel verification, locked cache-local bootstrap, and package health command.
- `scripts/stage-plugin` - First-party wheel build plus strict positive-allowlist stage assembly.
- `scripts/smoke-staged-plugin` - Isolated marketplace install, exact-byte comparison, network-denied launch, and evidence capture.
- `tests/staged/test_manifest_install.py`, `tests/staged/test_cli_launcher.py` - Clean stage/install and outside-checkout runtime acceptance tests.
- `.gitignore` - Prevents virtual environments, generated stages, evidence, and bytecode from entering commits.

## Decisions Made

- Used the staged wheelhouse-lock digest as runtime identity so any package, hash, requirements, or first-party-wheel change creates a distinct cache environment.
- Required `CODEX_HOME` for runtime mutation; `--help` remains bootstrap-free, while installed commands never fall back to source or user-site packages.
- Qualified Linux x86_64 first and checked in both CPython 3.13 and 3.14 compiled wheels; macOS and Windows remain unclaimed.
- Treated Codex host installation as the exact-stage validation boundary and retained official plugin-creator validation for both source and generated stage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added the canonical validator's missing PyYAML dependency**
- **Found during:** Task 2
- **Issue:** The required `validate_plugin.py` imports `yaml`, but the initial audited project lock omitted PyYAML, so the exact verification command could not start.
- **Fix:** Verified PyYAML with local slopcheck (`OK`), pinned validator-only PyYAML 6.0.3, and added hash-inventoried Python 3.13/3.14 wheels.
- **Files modified:** `pyproject.toml`, `uv.lock`, `vendor/python/wheelhouse.lock.json`, `vendor/python/wheelhouse/pyyaml-*.whl`
- **Verification:** The exact `uv run python .../validate_plugin.py .` command passes.
- **Committed in:** `f9a5cd1`

**2. [Rule 1 - Bug] Made stage inventory ordering path-deterministic**
- **Found during:** Task 3 final staged tests
- **Issue:** `Path` ordering emitted directory children before a sibling `wheelhouse.lock.json`, violating the sorted inventory contract.
- **Fix:** Sort `(relative_path, digest)` records explicitly before writing inventory and aggregate digest bytes.
- **Files modified:** `scripts/smoke-staged-plugin`
- **Verification:** Both staged tests pass and inventory equals its lexical sort.
- **Committed in:** `b59c65a`

**3. [Rule 2 - Missing Critical] Excluded generated runtime and evidence output from version control**
- **Found during:** Task 3
- **Issue:** Virtual environments, generated stages/evidence, and Python bytecode had no repository ignore contract and could be accidentally staged.
- **Fix:** Added focused ignores for `.venv/`, `build/`, `__pycache__/`, and Python bytecode.
- **Files modified:** `.gitignore`
- **Verification:** The full clean stage/install/test gate leaves `git status --porcelain` empty.
- **Committed in:** `b59c65a`

---

**Total deviations:** 3 auto-fixed (1 blocking issue, 1 bug, 1 missing critical control).
**Impact on plan:** All fixes were required for validator execution, deterministic evidence, or safe generated-output handling; PKG-01 scope remained unchanged.

## Issues Encountered

- The project-local `.python-version` causes pyenv to expose the system `uv 0.11.26`; verification selected the already-installed pinned `uv 0.11.28` via `PYENV_VERSION=3.11.10`. The lock still enforces uv 0.11.28.
- The empirical Codex probe required a repo-style `.agents/plugins/marketplace.json` beneath the isolated marketplace root. Installation then resolved to the expected isolated cache path.

## Authentication Gates

None.

## Known Stubs

- `bin/arw:212` returns typed `route-not-implemented`; this is intentional because Plan 01-02 owns PKG-02 route execution. It does not block the PKG-01 install/package goal.

## User Setup Required

None - no external service configuration required.

## Verification

- `uv sync --frozen` with pinned uv 0.11.28: PASS.
- Source and exact generated stage validation with plugin-creator: PASS.
- Exact allowlisted stage plus isolated Codex marketplace install: PASS.
- Cached launcher under hidden-source/network namespace: PASS.
- `pytest -q tests/staged/test_manifest_install.py tests/staged/test_cli_launcher.py`: 2 passed.
- Evidence forbidden-prefix scan and absent `vendor/sources/**` gate: PASS.

## Next Phase Readiness

- PKG-01 is complete and Plan 01-02 can implement the declared `route --json` contract on top of the installed runtime.
- `vendor/sources/**` remains untouched for Plan 01-03's mandatory pre-vendoring license gate.
- Release qualification remains subject to the later mixed-license use/distribution decision; this plan establishes technical installability only.

## Self-Check: PASSED

- All key created files exist.
- Task commits `1f8ceba`, `f9a5cd1`, and `b59c65a` exist.
- PKG-01 verification and requirement metadata are present.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
