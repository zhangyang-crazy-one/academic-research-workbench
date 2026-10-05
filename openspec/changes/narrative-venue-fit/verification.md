# Verification

The issue 55 implementation was checked in an isolated export of the staged
Git index. `tests/unit/test_narrative_fit.py` covers bundled minimal CLI,
accepted draft and source binding, graph failure, frozen byte repeat and
tamper, no ledger/narrative mutation, current-state freshness, profile review
expiry, accepted PDF page count and recount, promoted heuristic evidence and
run scope, and optional judgment provenance.

- Staged index export: 95 writing, narrative and fit tests passed (including 9
  focused fit tests).
- Checked schema registry: 95 checked documents, including all four fit schemas.
- Ruff on changed Python modules and fit test: passed.
- Pyright on fit model, extension and CLI: 0 errors.
- `git diff --cached --check`: passed.
- `openspec validate narrative-venue-fit --type change --strict
  --no-interactive`: passed.

The bundled annual venue profile does not assign a unique official source URL
to each hard-gate sentence. The generated profile therefore retains exact
bundle SHA-256 and JSON locator and leaves each natural-language requirement
unknown. Submission compliance, semantic scientific support, comprehensive
anonymity, and acceptance probability are outside this deterministic check.
The frozen snapshot contains manuscript and evidence bytes and should remain
private to the project.

Explicit public mode extension (2026-10-03): fourteen focused fit tests passed,
including all nine existing selected-narrative cases, capsule byte distinction,
CLI offline replay, read-only capture, actual accepted PDF count, forged cross-run
manifest rejection, missing-root freshness, unknown official requirements and explicit bound-run rejection.
Targeted Ruff checks and Pyright passed. Checked schema validation passed; the
existing selected snapshot/profile/report schemas remain unchanged. The new
public snapshot has its own schema. These synthetic integrity tests do not
establish scientific findings or venue-rule compliance.
