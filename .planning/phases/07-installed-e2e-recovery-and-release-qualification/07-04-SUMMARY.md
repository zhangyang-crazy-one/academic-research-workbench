---
phase: 07-installed-e2e-recovery-and-release-qualification
plan: 04
status: complete
requirements:
  - VER-02
  - VER-04
  - VER-06
  - VER-08
commits:
  - a6bd8c7
  - f8583e7
---

# Phase 7 Plan 04 Summary

## Outcome

Phase 7 now has a serial, evidence-bound aggregate verifier. It validates the
installed stage, exact external ARS lock, host/hook canary, recovery matrix,
representative dossier and cold replay, Phase 5 graph-equivalence receipts,
and Phase 4.1 subagent/panel independence receipts before producing a single
canonical verdict. Technical qualification is `PASS`; release qualification
remains `BLOCKED` for SUP-04/P04-09 and the unresolved CC-BY-NC intended-use,
distribution, accountable-approval, and permission evidence.

## Completed Tasks

### 07-04-T1 — Serial evidence-bound verifier

- Added `scripts/verify-phase-7` with an owned evidence-root marker,
  canonical JSON receipts, bounded/redacted command streams, serial execution,
  stage/lock/canary validation, and per-requirement status for VER-02/04/06/08.
- Validated the exact Phase 5 graph-equivalence receipt, including the
  generated file-base evidence at
  `build/stage/phase-05/.file-base/build-evidence.json`; a missing or digest
  mismatched path fails closed.
- Validated Phase 4.1 host/panel corpus, 48 case results, and P04-05-T01/T02
  exit receipts without treating the graph or review packet as canonical
  authority.
- Added aggregation/tamper probes for stale stage identity, missing file-base
  evidence, failed independence command, and release-boundary separation.

### 07-04-T2 — Release-boundary and documentation probes

- Added conservative root `README.md` wording: the current reshaped ARS
  adapter is an explicit external input, not a claimed public fork or
  redistribution grant; Science Workbench paper AST/export remains v2.
- Updated the Phase 7 validation contract with Nyquist-compliant commands,
  retained evidence paths, and the technical PASS/legal BLOCKED distinction.

### 07-04-T3 — Final serial qualification

- Focused Phase 7 suite: `13 passed`.
- Full non-host regression: `481 passed, 3 deselected` (the exact host-marked
  tests were run separately; no tests were deleted or xfailed).
- Exact stage validation: `stage valid`.
- Exact live Codex host canary: `Codex host technical qualification PASS` with
  three fresh HOME/CODEX_HOME roots, observed official hook execution,
  credential hygiene, and controlled result channel.
- Final aggregate: `build/evidence/phase-07-final-2/phase-7-verification.json`.
- Live canary receipt: `build/evidence/phase-07-host-canary-final/canary.json`.

## Deviations from Plan

**[Rule 1 - Compatibility] Existing staged test fixture used the retired
0.144.3 tuple** — Found during: first full non-host regression | Eight stage
inventory tests failed before reaching their intended lock/tamper assertions.
The fixture's locally generated lock was updated to the retained exact
`codex-cli 0.144.4` baseline; the negative 0.144.3 unsupported-host probe was
preserved. Verification: `tests/staged/test_supply_chain_inventory.py` 11
passed, then full non-host regression 481 passed. The shared file already
contained user Phase 4 edits, so the one-line compatibility change remains
unstaged for the parent to include selectively.

**[Rule 1 - Safety] Prior Phase 7 evidence root was unowned** — The existing
`build/evidence/phase-07` contained Wave 1–3 receipts without a Phase 7
ownership marker. The verifier refused to delete it under `--clean`; final
evidence was written to the fresh owned root `build/evidence/phase-07-final-2`.
No prior receipts were overwritten.

**Total deviations:** 2 auto-fixed/safety-preserving. **Impact:** no
qualification gate was weakened; all retained evidence is hash-bound and the
legal release blocker remains explicit.

## Authentication Gates

None. The exact host canary used the preconfigured credential source while
stripping API-key environment variables and retaining no secret bytes.

## Self-Check: PASSED

- `git diff --check` passed.
- `tests/integration/test_phase7_verifier.py` and staged Phase 7 probes: 8
  passed.
- Full non-host and exact host evidence are retained under repository-local
  `build/evidence`/`build/tmp` roots.
- Technical qualification and legal release qualification remain separate.
- No push, PR, or publication action was performed.

## Residual Remediation and Final Requalification

The independent verifier review initially found fail-closed gaps in command
identity, prior-phase parent evidence, graph-control binding, fault sidecar
replay binding, dirty-worktree provenance, and verifier subprocess credential
hygiene. These were closed in the follow-up commits through `ef3974e` and the
review closeout `e8169fe`:

- prior Phase 5/4.1 receipts and graph-control are pinned to the qualified
  canonical digests and revalidated at aggregation;
- command receipts are verifier-owned, exact-argv, output-hash bound, and
  tied to the current dirty worktree digest;
- fault sidecars require canonical sealed event sequences and replay-root
  validation; detached fixtures require explicit opt-in;
- verifier subprocesses use empty repo-local HOME/CODEX_HOME directories and
  do not inherit credential variables.

Final serial evidence is retained at
`build/evidence/phase-07-final-13/phase-7-verification.json` with technical
qualification `PASS`, all VER-02/04/06/08 requirements `PASS`, and release
qualification `BLOCKED` only for the named legal/permission/accountable-human
gates. The final non-host command recorded 490 passed and 3 deselected; the
focused Phase 7 suite recorded 76 passed in the current working tree.

---
*Phase: 07-installed-e2e-recovery-and-release-qualification*
*Plan: 04*
*Completed: 2026-07-16*
