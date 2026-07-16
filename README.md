# Academic Research Workbench

Academic Research Workbench (ARW) is a headless, Codex-native control plane
for reproducible and auditable research runs. Canonical run state is kept in
the append-only ledger; file-base and research-graph indexes are disposable
projections.

## ARS integration boundary

ARW uses the current locally maintained and reshaped Academic Research Suite
(ARS) adapter as an explicit external integration input. The adapter is not
bundled into the staged ARW plugin: `ARW_ARS_ROOT` must point to the exact,
lock-bound installation (adapter version, upstream identities, and content
digests). A missing, symlinked, drifting, or implicitly discovered ARS root is
blocked. This repository's wording does not assert public fork ownership,
redistribution permission, or a license grant for ARS content.

The Science Workbench paper AST/export remains a v2/deferred boundary; ARW
does not claim to replace a complete research-to-paper workflow.

## Qualification status

The retained Phase 7 verifier records technical qualification separately from
release permission. Technical evidence may be `PASS` while release remains
`BLOCKED` until accountable intended-use, distribution, approval, and
CC-BY-NC permission evidence is supplied. See
`build/evidence/phase-07-final-2/phase-7-verification.json` for the latest
serial qualification receipt when present.
