---
phase: 03-secure-files-first-data-plane
plan: 05
subsystem: security-qualification
tags: [security, race, staged-package, evidence, build-identity, supply-chain]

requires:
  - phase: 03-secure-files-first-data-plane
    plan: 04
    provides: Complete five-tool retrieval behavior, generated contracts, and native publication identity
provides:
  - Deterministic VER-03 adversarial coverage for confinement, replacement races, malformed inputs, sensitive paths, and output budgets
  - Descriptor-pinned SQLite query access that detects database replacement before returning derived content
  - Staged payload identity covering the first-party wheel, native tree and binary, generated contracts, compile profile, and retrieval algorithm versions
  - Raw-evidence Phase 3 verifier with per-requirement, per-decision, and ROADMAP success-criterion verdicts
  - Installed one-root end-to-end qualification and explicit separation of technical PASS from legal release BLOCKED
affects: [phase-04-subagent-orchestration, phase-05-evidence-queries, phase-07-release-qualification]

tech-stack:
  added: []
  patterns:
    - SQLite is opened through a verified O_NOFOLLOW descriptor and /proc/self/fd rather than a mutable pathname
    - Staging verifies every identity-bearing payload before publishing the installable package
    - Phase verification retains raw commands, logs, hashes, staged-runtime transcripts, and machine-readable verdicts
    - Verifier temporary trees live outside the Git worktree and are removed after execution

key-files:
  created:
    - scripts/phase3-runtime-evidence
    - scripts/verify-phase-3
    - tests/integration/test_files_security.py
    - docs/runtime/files-first-data-plane.md
  modified:
    - src/arw/files.py
    - src/arw/files_mcp.py
    - src/arw/build_identity.py
    - scripts/stage-plugin
    - scripts/license-gate
    - schemas/v1/build-identity.schema.json
    - supply-chain/use-distribution.json

key-decisions:
  - "Race qualification uses deterministic parent-controlled descriptor schedules against the active Python MCP; no release binary exposes test barriers."
  - "Generation databases are SHA-validated on an O_NOFOLLOW descriptor and queried through that same descriptor, so path substitution cannot change query bytes."
  - "The top verdict distinguishes technical qualification from SUP-04 legal release qualification; Phase 3 may pass while release remains blocked."
  - "Final evidence is retained under ignored build/evidence while verifier scratch data is created outside the repository and deleted."

requirements-completed: [FILE-01, FILE-02, FILE-03, FILE-04, FILE-06, FILE-07, FILE-08, VER-03]

duration: 35 min
completed: 2026-07-14
---

# Phase 3 Plan 5: Secure Files-First Qualification Summary

**The exact staged plugin now proves bounded, read-only multilingual retrieval under adversarial replacement and malformed-input schedules, with raw evidence for every Phase 3 requirement and design decision.**

## Accomplishments

- Added the VER-03 matrix for traversal and link escape, sensitive paths, malformed requests, client limit escalation, output exhaustion, pointer/generation/database replacement, no-write behavior, and canary leakage.
- Closed a live database substitution gap by opening SQLite with `O_NOFOLLOW`, verifying digest and descriptor/path identity, and querying through `/proc/self/fd/<fd>`; integrity changes return `generation_integrity_changed` without body-derived output.
- Extended build identity and staged validation to bind the native source tree and binary, build evidence and compile profile, generated file contract, tokenizer/ranking/outline versions, and hash-locked first-party wheel.
- Added a clean Phase 3 verifier that stages exact tracked bytes, runs source and Phase 1/2 regressions, exercises the installed runtime, retains raw evidence, and emits one requirement/decision/success-criterion verdict.
- Documented root registration, extraction registration, explicit synchronization, one-root launch, freshness behavior, ceilings, rebuild, repair, and the raw-PDF exclusion boundary.
- Refreshed SBOM, notices, and technical provenance hashes while retaining the independent SUP-04 release blocker.

## Task Commits

1. **Task 1: Define and close the adversarial security matrix** - `2929824`, `8aa9235`
2. **Task 2: Bind staged files-plane identity and package inventory** - `39e3cb2`
3. **Task 3: Add raw-evidence qualification and close verifier defects** - `efdda4e`, `b540577`, `d6de238`

## Deviations from Plan

### Architecture Deviation

**No native patches `0005` or `0006`, native MCP retrieval profile, or release-mode test barrier was added.**
- Plan 03 established the dedicated five-tool server in the hash-locked first-party Python wheel because the generic upstream native MCP exposes a broader write-capable dispatch surface.
- The security suite therefore schedules deterministic descriptor and path replacements against the active server from the parent test process. This exercises the shipped implementation without adding test controls to release bytes.
- The native binary remains the Phase 1 compatibility server and Phase 3 generation publication gate; its source tree, build evidence, compile profile, generated contract, and binary digest remain staged-identity inputs.

### Auto-fixed Issues

**1. [Security] Pinned SQLite queries to verified bytes**
- Opening SQLite by pathname after an integrity check left a substitution interval.
- Queries now use the same verified no-follow descriptor, and pointer/path/inode changes fail closed before content is returned.

**2. [Packaging] Bound all active files-plane components into build identity**
- The staged identity did not cover the first-party wheel, generated header, algorithm versions, or full native provenance.
- Stage construction now verifies these payloads and includes the operator contract header path in installed administration.

**3. [Verification] Kept temporary source trees outside Git and refreshed provenance after generated legal artifacts**
- Clean verification initially dirtied or expanded the source worktree and SBOM regeneration made technical provenance hashes stale.
- The verifier now uses an external owned temporary root, and `license-gate` refreshes technical digest references after generating notices and SBOM data.

## Verification

- Phase 3 specialized suite - `65 passed in 47.38s`.
- Frozen full suite - `184 passed in 258.06s`.
- `UV_OFFLINE=1 ./scripts/verify-phase-3 --clean --evidence-root build/evidence/phase-03` - technical `PASS`.
- Source verification, Phase 1 regression, Phase 2 regression, staging, and installed-runtime commands - all exited `0`.
- Requirements `FILE-01`, `FILE-02`, `FILE-03`, `FILE-04`, `FILE-06`, `FILE-07`, `FILE-08`, and `VER-03` - all `true` in the top verdict.
- Decisions `D-01` through `D-16` and ROADMAP criteria `SC-1` through `SC-4` - all `true`.
- Build identity SHA-256 - `69b0d6edeb7288fe4f21efbe8354a8487fd266b2c776d5b2300e74d174ad8b45`.
- Generated contract header SHA-256 - `3cdc203ec0c762744995eb9f5b7d4652ca92eabfe7f824f32a98dbe0d091e7b1`.
- Release qualification - `BLOCKED` solely by the separately tracked SUP-04 legal authorization evidence.

## Phase Completion

- All four Phase 3 ROADMAP success criteria are proven from exact staged bytes.
- Agent-facing MCP surface is exactly five bounded read-only tools; administration remains parent-controlled.
- Projection deletion/rebuild, selected-generation freshness, query no-write manifests, and private-canary scans passed.
- Phase 4 can consume the one-root files capability through immutable worker assignments without receiving filesystem or administration authority.

## Self-Check: PASSED

- Summary, verifier, documentation, schemas, implementation, tests, and retained verdict agree on the active Python MCP architecture.
- No generated evidence, database, extraction text, cache, temporary source tree, or private canary is tracked or staged.
- Technical completion does not misrepresent unresolved release authorization as satisfied.

---
*Phase: 03-secure-files-first-data-plane*
*Completed: 2026-07-14*
