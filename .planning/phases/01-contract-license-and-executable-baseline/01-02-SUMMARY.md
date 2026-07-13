---
phase: 01-contract-license-and-executable-baseline
plan: 02
subsystem: packaging
tags: [codex-plugin, skills, hooks, pydantic, json-schema, installed-host]

requires:
  - phase: 01-contract-license-and-executable-baseline/01-01
    provides: Exact allowlisted stage, isolated marketplace install, and offline installed launcher
provides:
  - Strict ARS 0.1.19 installed route contract and checked-in Draft 2020-12 schema
  - Model-invocable installed skill with observational hook and honest compatibility fallbacks
  - Cachebusted fresh-host convergence with exact installed identity and retained raw evidence
  - Technical PASS for PKG-02 from fresh Codex host attempt 008
affects: [01-03-supply-chain, 01-04-licensing, 01-07-build-identity, phase-4-subagents]

tech-stack:
  added: []
  patterns: [strict route model, observational hooks, cachebusted reinstall, evidence-backed host classification]

key-files:
  created:
    - hooks/hooks.json
    - schemas/v1/route-result.schema.json
    - src/arw/__init__.py
    - src/arw/cli.py
    - src/arw/contracts.py
    - tests/staged/test_skill_route.py
    - tests/staged/test_compatibility_probes.py
  modified:
    - bin/arw
    - pyproject.toml
    - scripts/stage-plugin
    - scripts/smoke-staged-plugin
    - skills/academic-research-workbench/SKILL.md

key-decisions:
  - "The Phase 1 installed canary routes to academic-pipeline in inline-role-prompts mode with ARS adapter 0.1.19 and experiment execution disabled."
  - "Plugin-native custom-agent distribution remains unproven; native Codex subagents with immutable assignment-injected ARS roles are the required fallback."
  - "Plugin hooks use the default hooks/hooks.json contract, remain observational and read-only, and are not an authorization or canonical-state boundary."
  - "Host qualification requires a command_execution event from installed bin/arw; schema-shaped model output alone is rejected."

patterns-established:
  - "Installed route proof: direct offline output, host output, and checked-in schema must agree exactly."
  - "Convergence evidence: every attempt retains commands, streams, status, classification, and installed identity; only a final fresh-process PASS closes the gate."
  - "Credential hygiene: authentication may be copied into an isolated host only for the canary and is deleted immediately after every outcome."

requirements-completed: [PKG-02]

duration: 31 min
completed: 2026-07-13
---

# Phase 1 Plan 2: Installed Skill Route and Fresh-Host Compatibility Summary

**A fresh Codex process invokes exact installed bytes to return a strict ARS 0.1.19 route, while hooks stay observational, custom-agent support stays unclaimed, and experiment execution stays disabled.**

## Performance

- **Duration:** 31 min
- **Started:** 2026-07-13T02:07:50Z
- **Completed:** 2026-07-13T02:39:16Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Added a strict Pydantic route contract and matching Draft 2020-12 schema for `academic-pipeline` / `inline-role-prompts`, ARS adapter `0.1.19`, and disabled experiments.
- Connected the installed skill and `bin/arw` launcher to the packaged CLI without source, user-site, `PYTHONPATH`, or network fallback.
- Added a default plugin hook companion that only emits routing context and cannot mutate canonical state.
- Converged the installed host to technical PASS on attempt `008`, with raw JSONL proving a successful installed `bin/arw route --json` command event and exact stage/installed SHA-256 equality.
- Preserved honest compatibility evidence: plugin custom-agent distribution is unproven, native subagents plus immutable assignment roles are the fallback, and untrusted hooks are skipped without affecting route correctness.

## Task Commits

Each task was committed atomically:

1. **Task 1: Execute RED route and compatibility behavior tests** - `b25a0c1` (test)
2. **Task 2: Implement strict route, skill, and observational hook contracts** - `ab95597` (feat)
3. **Task 3: Converge the fresh installed host canary to success** - `4b5c7df` (feat)

Additional correctness commit:

- **Credential-retention security fix** - `9863c6d` (fix)

## Files Created/Modified

- `src/arw/contracts.py`, `src/arw/cli.py` - Strict route model and machine-readable CLI.
- `schemas/v1/route-result.schema.json` - Independently validated installed route schema.
- `bin/arw` - Dispatches the installed cache-local runtime to `arw.cli route`.
- `skills/academic-research-workbench/SKILL.md` - Canonical model-invocable route and explicit fallback boundaries.
- `hooks/hooks.json` - Default observational `SessionStart` companion with no canonical writes.
- `scripts/stage-plugin` - Stages route schema/hooks and applies one supported Codex cachebuster suffix.
- `scripts/smoke-staged-plugin` - Clean restage/install, offline direct route, fresh-host invocation, classifications, identity, redaction, and credential cleanup.
- `tests/staged/test_skill_route.py`, `tests/staged/test_compatibility_probes.py` - Installed-byte host route and compatibility acceptance tests.
- `pyproject.toml`, `src/arw/__init__.py` - Packages the control-plane source in the first-party wheel and registers the strict host marker.

## Decisions Made

- Chose `academic-pipeline` / `inline-role-prompts` as the Phase 1 deterministic canary route because it matches the existing Codex adapter’s inline role-prompt behavior without claiming deferred orchestration.
- Kept the route result intentionally narrow: exactly five required fields, no compatibility or mutable-state payloads.
- Used the documented default `hooks/hooks.json` discovery path without adding a manifest hook field; the host classified the untrusted hook as skipped, proving route correctness does not depend on trust.
- Required raw `command_execution` evidence from the installed cache. A response that merely satisfies known schema constants is a non-authentication defect, not a PASS.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Registered the strict Codex-host pytest marker**
- **Found during:** Task 1 RED collection
- **Issue:** `--strict-markers` rejected the planned `codex_host` marker because Plan 01 had not registered it.
- **Fix:** Added the marker definition to `pyproject.toml` before collecting the RED tests.
- **Files modified:** `pyproject.toml`
- **Verification:** Both behavior files collected and then failed only on missing route behavior.
- **Committed in:** `b25a0c1`

**2. [Rule 3 - Blocking] Packaged control-plane source into the installed wheel**
- **Found during:** Task 2 installed-wheel verification
- **Issue:** Plan 01 used Hatchling `bypass-selection`, producing metadata without the new `arw` package.
- **Fix:** Declared `packages = ["src/arw"]` and added the package initializer.
- **Files modified:** `pyproject.toml`, `src/arw/__init__.py`
- **Verification:** An unrelated-cwd installed launcher returned the route from the offline wheel.
- **Committed in:** `ab95597`

**3. [Rule 1 - Bug] Resolved caller authentication from the real Codex home**
- **Found during:** Task 3 attempt `001`
- **Issue:** The runner required an override and ignored an authenticated caller `CODEX_HOME/auth.json`, creating a false authentication classification.
- **Fix:** Resolve the explicit override first, then the caller Codex home, without recording credential bytes or paths.
- **Files modified:** `scripts/smoke-staged-plugin`
- **Verification:** Subsequent attempts authenticated without human action.
- **Committed in:** `4b5c7df`

**4. [Rule 1 - Bug] Removed schema constants as a host-route substitute**
- **Found during:** Task 3 attempts `002`-`004`
- **Issue:** `--output-schema` exposed every constant, allowing schema-shaped model output without an installed command event; the last-message target was also hidden with the repository.
- **Fix:** Removed the output-schema hint, moved host output into the isolated writable root, and required a successful installed command event plus direct-result equality.
- **Files modified:** `scripts/smoke-staged-plugin`
- **Verification:** Attempts without command evidence remained non-authentication defects.
- **Committed in:** `4b5c7df`

**5. [Rule 3 - Blocking] Made the nested Codex sandbox lock writable**
- **Found during:** Task 3 attempts `005`-`007`
- **Issue:** The outer source-hiding namespace made `/tmp` read-only, so Codex could not acquire its managed shell mount-registry lock before invoking the plugin.
- **Fix:** Added an ephemeral writable `/tmp` while keeping the repository hidden and installed roots isolated.
- **Files modified:** `scripts/smoke-staged-plugin`
- **Verification:** Attempt `008` emitted a successful installed command event and route result.
- **Committed in:** `4b5c7df`

**6. [Rule 1 - Bug] Normalized direct route evidence and authentication-attempt identity assertions**
- **Found during:** Task 3 acceptance verification
- **Issue:** Direct JSON existed only in raw stdout, and the test incorrectly required an installed identity for an attempt classified before installation.
- **Fix:** Emit `direct/result.json`; require identities for every non-authentication attempt and the final PASS.
- **Files modified:** `scripts/smoke-staged-plugin`, `tests/staged/test_compatibility_probes.py`
- **Verification:** Both host tests pass against retained raw attempt `008` evidence.
- **Committed in:** `4b5c7df`

**7. [Rule 2 - Missing Critical] Purged isolated authentication copies**
- **Found during:** Post-task threat-surface scan
- **Issue:** Test-only authentication copies remained under generated isolated homes after host execution.
- **Fix:** Delete the copy after every host outcome, assert no retention in compatibility evidence, and remove generated copies from completed attempts.
- **Files modified:** `scripts/smoke-staged-plugin`, `tests/staged/test_compatibility_probes.py`
- **Verification:** No generated route-home `auth.json` remains and all installed-host tests pass.
- **Committed in:** `9863c6d`

---

**Total deviations:** 7 auto-fixed (3 bugs, 3 blocking issues, 1 missing critical security control).
**Impact on plan:** Every fix was required to prove installed execution honestly, preserve isolation, or prevent credential retention; no product scope was added.

## Issues Encountered

- Attempt `001` recorded a false authentication requirement caused by the runner lookup bug; no human authentication action was needed.
- Attempts `002`-`004` returned route-shaped model output without installed command evidence and were correctly rejected.
- Attempts `005`-`007` showed the nested sandbox mount-lock failure before plugin execution and were correctly rejected.
- Attempt `008` passed with a fresh process, installed command event, schema-valid output, exact identity, and no unresolved non-authentication result.
- A later pytest fixture attempted to start a redundant host loop and was interrupted; tests now consume retained real host evidence when available and permit at most one host attempt in a clean environment.

## Authentication Gates

No human-action gate occurred. The operator was already authenticated; attempt `001` was an owned runner bug and was resolved automatically.

## Known Stubs

None. `plugin_distribution: unproven` and `experiment_execution: disabled` are intentional compatibility boundaries, not placeholders.

## Threat Flags

| Flag | File | Description |
|---|---|---|
| `threat_flag: credential-bridge` | `scripts/smoke-staged-plugin` | The host canary copies only the selected Codex auth file into an isolated `0600` location, never records it, and deletes it immediately after every outcome. |

## User Setup Required

None - the authenticated host canary completed without external configuration.

## Verification

- Strict route command and independent JSON parsing: PASS.
- Pydantic model schema equals checked-in Draft 2020-12 schema: PASS.
- Skill quick validation and plugin validation: PASS.
- Plan 01 installed-stage regression tests: `2 passed`.
- Plan 02 installed host route/compatibility tests: `2 passed`.
- Retained fresh-host evidence: attempt `008`, `command_execution` exit `0`, technical qualification `PASS`.
- Exact identity: stage and installed SHA-256 both `2577f97dce52b969e2dc65c09b0a77d5dcbe2e3fbd25e3953aab33a1d5eedd80`.
- Source checkout hidden, inherited `PYTHONPATH` absent, direct installed command network-disabled, and generated auth copies absent: PASS.

## Next Phase Readiness

- PKG-02 is complete; Plan 01-03 can begin the mandatory pre-vendoring legal/source gate.
- Custom-agent distribution remains deliberately unclaimed; later subagent work must keep the native-subagent/immutable-assignment fallback.
- Raw host evidence remains under the ignored `build/evidence/phase-01/route/` workspace tree for Phase 1 aggregation.

## Self-Check: PASSED

- All key created files exist.
- Task commits `b25a0c1`, `ab95597`, `4b5c7df`, and security fix `9863c6d` exist.
- PKG-02 metadata and retained fresh-host PASS evidence are present.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
