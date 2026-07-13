---
phase: 01-contract-license-and-executable-baseline
plan: 04
subsystem: supply-chain
tags: [licensing, cyclonedx, privacy, allowlist, release-gate]
requires:
  - phase: 01-contract-license-and-executable-baseline
    plan: 03
    provides: receipt-bound materialized sources, preserved native legal tooling, and digest-closed manifests
provides:
  - distinct CC BY-NC 4.0 and MIT component license identities
  - post-materialization native and extended legal inventory with retained raw evidence
  - CycloneDX 1.5 coverage for sources, patches, C legal inputs, Python wheels, and build artifacts
  - independent technical PASS and release BLOCKED classification
  - positive-allowlist stage with exact coverage, no-symlink validation, and private-canary evidence
affects: [01-06, 01-07, release-qualification, installed-package-verification]
tech-stack:
  added: [CycloneDX 1.5 SBOM]
  patterns: [preserved-native-gate wrapper, two-dimensional qualification, positive stage allowlist, canary-based privacy evidence]
key-files:
  created:
    - scripts/license-gate
    - LICENSES/academic-research-skills-CC-BY-NC-4.0.txt
    - LICENSES/experiment-agent-CC-BY-NC-4.0.txt
    - LICENSES/file-base-MIT.txt
    - THIRD_PARTY_NOTICES.md
    - MODIFICATIONS.md
    - SBOM.cdx.json
    - supply-chain/use-distribution.json
    - supply-chain/license-verdict.json
    - tests/integration/test_license_gate.py
    - tests/staged/test_supply_chain_inventory.py
    - tests/staged/test_private_exclusions.py
  modified:
    - scripts/stage-plugin
key-decisions:
  - "Post-materialization qualification executes the preserved file-base gate, policy, both checkers, and notice generator before extending their inventory."
  - "Technical provenance hashes do not satisfy intended-use, distribution, approval, or permission evidence; release remains BLOCKED."
  - "The distributable stage is built and revalidated from an exact positive allowlist whose files are individually digest-covered."
patterns-established:
  - "Two-stage legal chain: the source manifest links immutable pre-vendor evidence to a repeatable post-materialization native gate."
  - "Qualification split: technical_qualification and release_qualification are evaluated independently."
  - "Private-safe stage: allowlist assembly, exact inventory comparison, no symlinks, and unique canary scans all retain raw evidence."
requirements-completed: [SUP-03, SUP-04, SUP-05]
metrics:
  duration: 30m
  completed: 2026-07-13
  tasks: 3
  files: 22
---

# Phase 1 Plan 4: Extended Legal Inventory and Private-Safe Stage Summary

**The exact materialized build now passes the preserved and extended legal toolchain, carries complete mixed-license/SBOM evidence, excludes private material by construction, and remains honestly blocked for release pending authentic use/distribution permission evidence.**

## Performance

- **Duration:** 30 minutes
- **Started:** 2026-07-13T03:29:16Z
- **Completed:** 2026-07-13T03:59:14Z
- **Tasks:** 3
- **Files modified:** 22

## Accomplishments

- Preserved separate ARS and experiment-agent CC BY-NC 4.0 identities alongside file-base MIT, exact license bytes, modification markings, and generated upstream notices.
- Executed the preserved file-base self-test, policy, Python checker, npm checker, and notice generator over the current materialized source, retaining commands, streams, statuses, invocation logs, and the pre-vendor receipt link.
- Generated normalized CycloneDX 1.5 evidence covering all three source components, the ordered patch, 23 frozen Python wheels, 181 file-base legal inputs, the deterministic first-party wheel, and four declared native/build artifacts.
- Classified the exact build as technical `PASS` and release `BLOCKED` because intended use, distribution class, accountable approval, and CC BY-NC permission remain unresolved; private repository status is explicitly not treated as noncommercial evidence.
- Extended stage assembly with legal/native/source artifacts, per-file coverage hashes, exact allowlist revalidation, symlink rejection, and raw scans proving all eight private canary classes absent.

## Task Commits

Each task was committed atomically:

1. **Task 1: Execute red legal inventory, classifier, and private-stage tests** — `3c89e04` (`test`)
2. **Task 2: Extend and execute the complete post-materialization license gate** — `1442630` (`feat`)
3. **Task 3: Enforce private-safe staging and release BLOCKED semantics** — `8152893` (`feat`)

## Files Created/Modified

- `scripts/license-gate` — Verifies the source/pre-vendor chain, executes preserved native tooling, extends complete inventory, emits SBOM/notices, and classifies release.
- `LICENSES/` — Exact canonical CC BY-NC 4.0 and MIT component license copies without collective-license collapse.
- `THIRD_PARTY_NOTICES.md` — Source, patch, Python wheel, and preserved file-base generated notices.
- `MODIFICATIONS.md` — Upstream revisions, unchanged source partitions, ordered patch identity, and modification duties.
- `SBOM.cdx.json` — Normalized CycloneDX 1.5 source/build inventory bound to the frozen lock and current manifest.
- `supply-chain/use-distribution.json` — Explicitly unresolved intended-use/distribution/approval/permission record with technical provenance hashes.
- `supply-chain/license-verdict.json` — Independent technical and release qualification with component-level status and evidence-needed fields.
- `scripts/stage-plugin` — Positive legal/native/runtime allowlist, exact coverage inventory, validation mode, and raw privacy evidence.
- `tests/fixtures/private-canaries/` — Unique paper, extracted-text, run, credential, index, VCS, cache, and undeclared canaries.
- `tests/integration/test_license_gate.py` — Native-tool execution, receipt linkage, license mapping, and classifier proof.
- `tests/staged/test_supply_chain_inventory.py` — SBOM completeness and exact stage coverage proof.
- `tests/staged/test_private_exclusions.py` — Private-class exclusion plus undeclared-file and absolute-symlink rejection proof.

## Decisions Made

- Kept the upstream legal gate authoritative for its native policy instead of translating or replacing it; the workbench wrapper adds manifest, patch, Python, artifact, and qualification closure around actual executions.
- Normalized the uv-produced CycloneDX timestamp to the immutable pre-vendor receipt time so repeated frozen-lock exports remain stable while retaining uv 0.11.28 as the producing tool.
- Recorded technical provenance hashes in `use-distribution.json` with purpose `technical-provenance-only`; these records cannot unlock the release classifier.
- Required stage validation to compare every regular file to a committed-at-build inventory and reject every symlink before reading coverage metadata.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reused the verified cached ScanCode executable**
- **Found during:** Task 2 native gate execution
- **Issue:** ScanCode 32.5.0 had been provisioned by Plan 03 under ignored `build/tools/scancode`, but was not on the executor `PATH`.
- **Fix:** Resolve the existing verified executable deterministically before reporting the tool unavailable; no package installation or substitution occurred.
- **Files modified:** `scripts/license-gate`
- **Verification:** Native self-test and real gate both returned status 0 and retained invocation evidence.
- **Committed in:** `1442630`

**2. [Rule 3 - Blocking] Bypassed a looping pyenv shim for native checkers**
- **Found during:** Task 2 native gate execution
- **Issue:** Resolving `python3` through a pyenv shim looped in `pyenv-hooks` inside the vendored source tree before the preserved checker started.
- **Fix:** Bound preserved checker invocations to the executor's concrete system Python while leaving npm and ScanCode independently resolved.
- **Files modified:** `scripts/license-gate`
- **Verification:** Both preserved Python and npm checkers executed and the native gate completed successfully.
- **Committed in:** `1442630`

**3. [Rule 3 - Blocking] Used the frozen project environment for the first-party wheel build**
- **Found during:** Task 2 extended inventory generation
- **Issue:** The system Python correctly used by native checkers does not contain the pinned Hatchling build backend.
- **Fix:** Restricted first-party wheel construction to `.venv/bin/python`, the environment created from the frozen project lock.
- **Files modified:** `scripts/license-gate`
- **Verification:** Repeated builds produced the same wheel SHA-256 and the wheel appears in the SBOM.
- **Committed in:** `1442630`

**4. [Rule 3 - Blocking] Added stage legal outputs during Task 2**
- **Found during:** Task 2 acceptance verification
- **Issue:** The plan's Task 2 command runs the complete staged supply-chain test, which requires legal/SBOM/source artifacts before Task 3's privacy hardening begins.
- **Fix:** Added only the positive legal/native/source copies and initial per-file coverage inventory in Task 2; Task 3 then added validation mode, canary scans, raw privacy evidence, and evidence hashes.
- **Files modified:** `scripts/stage-plugin`, `supply-chain/use-distribution.json`, `supply-chain/license-verdict.json`
- **Verification:** Task 2's four legal/inventory tests passed before Task 3, then the full seven-test plan gate passed.
- **Committed in:** `1442630`, `8152893`

**5. [Rule 1 - Bug] Corrected STATE metric placement and frontmatter progress**
- **Found during:** Plan metadata close-out
- **Issue:** The installed SDK's metric handler appended a row below the narrative instead of updating the legacy velocity table, and left frontmatter progress at 0 despite four of seven summaries.
- **Fix:** Reconciled frontmatter to 57% and updated the existing velocity, phase-total, and recent-trend fields to include this 30-minute plan.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `state.validate` reports valid/no drift and the file now agrees with 4/7 summaries on disk.
- **Committed in:** plan metadata commit

---

**Total deviations:** 5 auto-fixed issues (4 Rule 3 blocking issues, 1 Rule 1 metadata bug).
**Impact on plan:** All fixes were required to execute the pinned toolchain or satisfy the plan's own acceptance order. No dependency, license identity, legal permission, or product scope was substituted.

## Issues Encountered

- The first native execution attempt correctly stopped because the verified ScanCode cache was not on `PATH`.
- A second attempt exposed the pyenv shim loop; it was interrupted before evidence was accepted and replaced by a concrete system-Python binding.
- A third attempt completed the native gate but found Hatchling absent from system Python; the final path used the frozen project environment only for the deterministic first-party build.

## Authentication Gates

None.

## Known Stubs

None. Empty permission references and unresolved use/distribution fields are intentional external legal-evidence states that enforce release `BLOCKED`; they do not prevent the technical objective from being achieved.

## User Setup Required

None for technical use. Only accountable review plus authentic intended-use, distribution, approval, and any required owner-permission evidence may change release qualification from `BLOCKED`.

## Verification

- Executed extended gate: technical `PASS`, release `BLOCKED`.
- Preserved native tool statuses: self-test `0`, gate `0`, notice generator `0`; both policy checkers appear in the raw invocation log.
- Plan suite: `7 passed in 63.93s`.
- Broader non-host integration/staged regression: `15 passed, 2 deselected in 82.85s`.
- Stage evidence: exact inventory diff empty, 8/8 private canaries absent, no symlinks.
- Inventory closure: 3 component licenses, 1 ordered patch, 23 Python wheels, 181 file-base legal inputs, 4 declared artifacts, plus deterministic first-party wheel.

## Next Phase Readiness

- SUP-03, SUP-04, and SUP-05 are technically complete with release honestly blocked.
- Plan 06 can append patch 0002/native changes and rerun the same manifest-driven gate without changing classifier semantics.
- Plan 07 can aggregate the independent technical/release fields and retained raw evidence into final Phase 1 qualification.

## Self-Check: PASSED

- All declared key files exist.
- Task commits `3c89e04`, `1442630`, and `8152893` exist in repository history.
- Retained native invocation logs prove both preserved checkers executed.
- Retained legal and stage verdicts confirm technical `PASS`, release `BLOCKED`, and zero private-canary hits.

---
*Phase: 01-contract-license-and-executable-baseline*
*Completed: 2026-07-13*
