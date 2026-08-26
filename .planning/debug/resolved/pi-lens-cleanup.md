---
status: resolved
trigger: "修复这些问题，并push 一个PR"
created: 2026-08-26
updated: 2026-08-26
---

# Debug Session: pi-lens-cleanup

## Symptoms

- expected_behavior: `lens_diagnostics mode=all` reports zero blocking errors and zero warnings for the ARS 0.1.27 PR.
- actual_behavior: pi-lens reported 15 blocking errors and 23 Markdown warnings.
- error_messages: 13 Pyright findings in `src/arw/cli.py`, 2 Marksman broken-link findings, and Markdown warnings in ARS workflow/reference/router docs plus `.planning/STATE.md`.
- timeline: Findings were visible after the bundled ARS 0.1.27 sync and final qualification.
- reproduction: Run `lens_diagnostics` with `mode=all`, `severity=all`.

## Current Focus

- hypothesis: confirmed and fixed
- test: active pi-lens scan, primary Python LSP, root/ARS tests, installed smokes, and Phase-7 qualification
- expecting: zero unresolved pi-lens errors/warnings without weakening validation
- next_action: open PR
- reasoning_checkpoint: All fixes are semantic-preserving; the exact layout-export table markers remain machine-checked.
- tdd_checkpoint: Existing diagnostics and regression suites were used as the oracle.

## Evidence

- timestamp: 2026-08-26
  observation: `lens_diagnostics mode=all` reports no issues across 24 diagnosed files.
- timestamp: 2026-08-26
  observation: Primary Python LSP confirms `src/arw/cli.py` clean.
- timestamp: 2026-08-26
  observation: Targeted CLI/STORM/orchestration/stage tests: 23 passed.
- timestamp: 2026-08-26
  observation: ARW root suite: 524 passed.
- timestamp: 2026-08-26
  observation: Bundled ARS suite: 9187 passed plus 261 subtests.
- timestamp: 2026-08-26
  observation: Reviewer verdict ACCEPT with no confirmed defects.
- timestamp: 2026-08-26
  observation: Codex host qualification and all four installed-stage smokes PASS.
- timestamp: 2026-08-26
  observation: Final Phase-7 technical qualification PASS; release remains blocked only by the existing legal evidence gate.

## Eliminated

- hypothesis: The findings were harmless cache-only artifacts.
  reason: Active scans reproduced real type-narrowing and Markdown defects.
- hypothesis: Table whitespace could be normalized without considering runtime contracts.
  reason: The ARS layout-export test proved two exact table markers are machine-readable contract inputs; localized MD060 suppression preserves them.

## Resolution

- root_cause: Dynamic dictionaries were not narrowed for Pyright; Markdown contained malformed table/list/fence syntax and unresolved maintainer-local wikilinks; one table's exact audit markers conflicted with MD060 alignment style.
- fix: Added explicit local narrowing in `src/arw/cli.py`; normalized Markdown syntax; converted non-distributed note links to documented plain identifiers; escaped a literal table pipe; preserved exact layout markers with a local MD060 directive; regenerated SBOM/license projections.
- verification: pi-lens 0 errors/0 warnings, primary LSP clean, 23 targeted + 524 ARW + 9187 ARS tests, 261 subtests, host canary/smokes PASS, Phase-7 technical PASS.
- files_changed: `.planning/STATE.md`, `MODIFICATIONS.md`, `SBOM.cdx.json`, `src/arw/cli.py`, `supply-chain/use-distribution.json`, and four ARS Markdown files.
