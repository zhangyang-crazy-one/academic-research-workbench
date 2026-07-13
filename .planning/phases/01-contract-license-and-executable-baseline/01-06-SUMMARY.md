---
phase: 01-contract-license-and-executable-baseline
plan: 06
subsystem: confined-native-mcp
tags: [c, mcp, openat, nofollow, asan, ubsan, tsan, bwrap, codex-plugin]

requires:
  - phase: 01-contract-license-and-executable-baseline
    provides: Digest-verified vendored sources and private-safe legal inventory from Plans 03 and 04
provides:
  - Strict bounded-read request/result schemas and direct-native denial matrix
  - Descriptor-relative Linux confinement implemented by ordered file-base patch 0002
  - Unchanged upstream, ASan+UBSan, and separate TSan PASS evidence under network denial
  - Self-locating installed MCP launcher and fresh-installed bounded-read qualification
affects: [phase-02-runtime-lifecycle, phase-03-files-data-plane, installed-qualification, release-audit]

tech-stack:
  added: []
  patterns:
    - Descriptor-relative component traversal with no-follow opens and regular-file final checks
    - Explicit allowed-root capability plus byte and line ceilings before content release
    - Separate normal, ASan+UBSan, and TSan evidence runs in denied network namespaces
    - Plugin-root-relative MCP launcher with explicit root and cache configuration

key-files:
  created:
    - schemas/v1/mcp-read-request.schema.json
    - schemas/v1/mcp-read-result.schema.json
    - vendor/patches/file-base/0002-phase1-confined-read.patch
    - .mcp.json
    - scripts/file-base-mcp
    - tests/staged/test_mcp_launcher.py
  modified:
    - scripts/build-file-base
    - scripts/offline-exec
    - scripts/stage-plugin
    - scripts/smoke-staged-plugin
    - vendor/source-manifest.json
    - supply-chain/use-distribution.json

key-decisions:
  - "Filesystem confinement is enforced inside the native MCP; launcher and host configuration are not trusted as the security boundary."
  - "Phase 1 claims the Linux baseline only and opens allowed paths component by component relative to a pre-opened root descriptor."
  - "Sanitizer suites use separate clean builds; TSan is never combined with ASan."
  - "The installed launcher accepts no implicit root or cache and resolves only the staged libexec binary from its own plugin root."

patterns-established:
  - "Denied reads return typed no-content results, and the outside canary is scanned out of streams and retained evidence."
  - "Native evidence binds compiler, flags, sanitizer runtime, patch order, unchanged test-tree hash, streams, status, and network audit."

requirements-completed: [PKG-03, FILE-05]

duration: 3h 08m
completed: 2026-07-13
---

# Phase 1 Plan 6: Confined Native MCP and Installed Launcher Summary

**The installed plugin now launches a digest-bound native file-base MCP that performs one explicitly rooted bounded read while rejecting traversal, symlink escape, sensitive paths, unknown roots, and excessive budgets before content release.**

## Performance

- **Duration:** 3h 08m
- **Started:** 2026-07-13T04:44:07Z
- **Completed:** 2026-07-13T07:51:55Z
- **Tasks:** 3
- **Files modified:** 26
- **Full regression:** 47 passed

## Accomplishments

- Added strict Draft 2020-12 MCP read contracts and eight direct-native success/denial cases covering CJK/LaTeX, traversal, absolute paths, symlink escape, unknown roots, `.env`, and byte/line ceilings.
- Appended digest-bound patch 0002 after patch 0001, implementing descriptor-relative no-follow traversal, regular-file checks, sensitive-name policy, strict UTF-8 output, and typed no-content denials.
- Preserved the upstream C test tree byte-for-byte at SHA-256 `4ace6a4c832b8d3e04d9366f5d7684833eadf338fd4be367e03fb7f8d274da2a`.
- Passed the unchanged upstream suite in clean normal, ASan+UBSan, and separate TSan builds under denied network namespaces. Each run recorded `5,784 passed, 1 skipped`; the skip is the upstream incremental clone probe under intentional network denial.
- Added a plugin-root-relative `.mcp.json`, self-locating launcher, exact-stage native binary, and fresh-installed Codex MCP-list plus bounded-read smoke proof outside the repository.
- Re-ran the legal classifier and closed the current source-manifest, SBOM, and notices digests while preserving technical `PASS` and release `BLOCKED`.

## Task Commits

1. **Task 1: Execute RED direct-native confinement contracts** - `9d63e87` (test)
2. **Task 2: Implement patch 0002 and pass native safety gates** - `a43afbd` (feat)
3. **Task 3 RED: Define installed MCP launcher contract** - `eb82721` (test)
4. **Task 3 GREEN: Qualify installed MCP launcher and bounded read** - `2a18d07` (feat)

Additional provenance closure:

- **Current native/legal evidence digest closure** - `2e316e5` (fix)

## Files Created/Modified

- `schemas/v1/mcp-read-request.schema.json`, `schemas/v1/mcp-read-result.schema.json` - Strict capability, path, ceiling, success, and denial wire contracts.
- `tests/integration/test_mcp_confinement.py` - Direct-native denial matrix, outside-canary checks, and sanitizer evidence validation.
- `vendor/patches/file-base/0002-phase1-confined-read.patch` - Native confined-read capability plus UBSan-diagnosed zero-length null argument fixes.
- `scripts/build-file-base`, `scripts/offline-exec` - Reproducible patching, unchanged-test verification, sanitizer runtime binding, network denial, and retained verdicts.
- `.mcp.json`, `scripts/file-base-mcp` - Installed host registration and self-locating explicit-configuration launcher.
- `scripts/stage-plugin`, `scripts/smoke-staged-plugin` - Exact native staging, isolated install, host listing, JSON-RPC stdio read, path redaction, and source/canary exclusion.
- `vendor/source-manifest.json`, `MODIFICATIONS.md`, `SBOM.cdx.json`, `THIRD_PARTY_NOTICES.md`, `supply-chain/use-distribution.json` - Ordered source, patch, artifact, dependency, and license evidence closure.

## Decisions Made

- The launcher fails with status 64 unless `CBM_ALLOWED_ROOT`, `CBM_ALLOWED_ROOT_ID`, and `CBM_CACHE_DIR` are explicit. `.mcp.json` contains no operator-specific or source-tree path.
- Patch 0002 evaluates policy before opening or reading content. Denials omit `content` entirely and expose only typed policy metadata.
- The build accepts a verified user-space sanitizer runtime directory because the host image does not provide usable system ASan/UBSan/TSan linker runtimes.
- The installed smoke copies only the allowed fixture into an isolated root, hides the source repository with bubblewrap, denies network access, and invokes the staged launcher from an unrelated working directory.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Supplied verified user-space sanitizer runtimes**
- **Found during:** Task 2 sanitizer builds
- **Issue:** The host lacked usable system `libasan`, `libubsan`, and `libtsan` linker runtimes, and privilege escalation was unavailable.
- **Fix:** Downloaded Fedora runtime RPMs without installation, extracted them under `build/tools`, verified the runtime tree and library digests, and taught the build to consume only an explicit `ARW_SANITIZER_RUNTIME_DIR`.
- **Verification:** Separate ASan+UBSan and TSan suites both passed with fatal diagnostic patterns absent and network syscall attempts empty.
- **Committed in:** `a43afbd`

**2. [Rule 1 - Bug] Fixed sanitizer-reported zero-length null library calls**
- **Found during:** Task 2 ASan+UBSan convergence
- **Issue:** UBSan identified null array/buffer arguments reaching `qsort` and `memcpy` for zero-length operations in the pinned native source.
- **Fix:** Added guarded zero-length handling to ordered patch 0002 without changing the upstream test tree.
- **Verification:** ASan+UBSan and TSan suites each passed 5,784 upstream tests with no fatal sanitizer diagnostics.
- **Committed in:** `a43afbd`

**3. [Rule 2 - Missing Critical] Rebound technical provenance hashes after native and launcher changes**
- **Found during:** Full repository regression
- **Issue:** `use-distribution.json` retained pre-0002 digests for the source manifest, SBOM, and generated notices.
- **Fix:** Re-ran the legal gate and updated only the three `technical-provenance-only` digests; intended-use and permission fields remain unresolved.
- **Verification:** Seven license/inventory/private-stage tests and the full 47-test suite pass; release qualification remains `BLOCKED`.
- **Committed in:** `2e316e5`

---

**Total deviations:** 3 auto-fixed (1 environment blocker, 1 sanitizer-reported native defect, 1 provenance closure).
**Impact on plan:** All fixes were necessary to execute the specified native safety and installed-byte gates; no new runtime authority or release permission was introduced.

## Issues Encountered

- A continuation subagent stopped returning status after Task 2 despite having committed its work. The orchestrator retained those commits, confirmed Task 3 RED, and completed the launcher inline.
- One full-regression attempt exhausted the `/tmp` user quota because pytest retained 7.4 GiB of prior exact-stage copies. Removing only generated pytest temporary directories and rerunning in a dedicated base temp produced `47 passed`.

## Authentication Gates

None. The MCP install/list/read qualification does not require an authenticated model invocation.

## Known Stubs

None for PKG-03/FILE-05. General file-plane lifecycle, multiple allowed roots, indexing, graph projection, and research workflow orchestration remain scoped to later phases.

## Verification

- Direct-native plus installed MCP suite: `13 passed`.
- Normal unchanged upstream suite: `5,784 passed, 1 skipped`, technical `PASS`, denied network namespace, zero external network attempts.
- ASan+UBSan unchanged upstream suite: `5,784 passed, 1 skipped`, fatal diagnostics absent, technical `PASS`.
- Separate TSan unchanged upstream suite: `5,784 passed, 1 skipped`, fatal diagnostics absent, technical `PASS`.
- License/inventory/private-stage regression: `7 passed`; technical `PASS`, release `BLOCKED`.
- Full repository regression: `47 passed in 101.04s`.
- Installed MCP evidence: `build/evidence/phase-01/mcp-launcher/summary.json` records exact-stage install, explicit root/cache, source-independent JSON-RPC stdio, Linux network isolation, and technical `PASS`.

## Next Phase Readiness

- PKG-03 and FILE-05 are complete with direct-native, installed-host, sanitizer, unchanged-upstream, legal, and no-content denial evidence.
- Plan 01-07 can bind build identity and final evidence schemas to the exact wheel/native/plugin bytes already qualified here.
- Release remains intentionally `BLOCKED` until intended use, distribution class, accountable approval, and compatible CC BY-NC permission evidence are supplied.

## Self-Check: PASSED

- All declared schemas, patch, launchers, native binary, manifests, tests, and retained evidence paths exist.
- RED/GREEN task commits and the provenance-fix commit are present in git history.
- Direct-native, sanitizer, installed MCP, license, and full regression claims match checked verdicts and test output.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
