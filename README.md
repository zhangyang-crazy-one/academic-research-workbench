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

The ARS-derived material follows the upstream CC BY-NC 4.0 terms. ARW does
not convert that material to MIT. The file-base component remains MIT, and the
complete component inventory is in `LICENSE`, `LICENSES/`, `MODIFICATIONS.md`,
`THIRD_PARTY_NOTICES.md`, and `vendor/source-manifest.json`.

The Science Workbench paper AST/export remains a v2/deferred boundary; ARW
does not claim to replace a complete research-to-paper workflow.

## Qualification status

The retained Phase 7 verifier records technical qualification separately from
release permission. Technical evidence may be `PASS` while release remains
`BLOCKED` until accountable intended-use, distribution, approval, and
CC-BY-NC permission evidence is supplied. See
`build/evidence/phase-07-final-13/phase-7-verification.json` for the latest
serial qualification receipt when present.

## Installation

### Development checkout

Requirements are Python `>=3.13,<3.15`, `uv==0.11.28`, and (for the exact
host qualification path) Codex CLI `0.144.4`.

```bash
git clone <repository-url> academic-research-workbench
cd academic-research-workbench
uv sync --frozen --all-groups
./bin/arw help
```

Source verification is an explicit online preparation step and materializes
ignored snapshots under `vendor/sources/`:

```bash
./scripts/materialize-sources --clean
./scripts/verify-sources --inputs-only
```

Set `ARW_ARS_ROOT` to the separately installed, exact ARS adapter before using
the integration route. An absent or drifting external adapter is intentionally
reported as blocked; ARW does not silently clone or substitute ARS.

### Staged Codex plugin

Use a qualified staged package produced by the staging workflow for
installation. A source checkout does not contain a prebuilt `marketplace/`
directory; create one from the immutable stage explicitly:

```bash
./scripts/stage-plugin --clean
./scripts/create-marketplace
codex plugin marketplace add ./build/marketplace --json
codex plugin add academic-research-workbench@arw-local --json
```

`create-marketplace` copies the exact staged tree and writes the local
marketplace manifest. For host qualification, use
`./scripts/smoke-staged-plugin` so the marketplace, fresh homes, hook trust,
and installed inventory are isolated and recorded together.

The staging and smoke scripts record the exact stage identity, installed
inventory, hook definition, MCP launcher, and version tuple. Do not install
from a dirty source checkout when making a qualification claim.

## Release boundary

CI builds and tests every change, but CD is fail-closed: a release job stops
unless the retained license verdict is `PASS`, accountable intended-use and
distribution evidence is present, and the P04-09 human gate is complete.
Planning files, local evidence, build directories, credentials, and materialized
third-party sources are excluded from source archives and staged payloads.
