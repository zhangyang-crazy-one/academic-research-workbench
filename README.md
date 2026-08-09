# Academic Research Workbench

Academic Research Workbench (ARW) is a headless, Codex-native control plane
for reproducible and auditable research runs. Canonical run state is kept in
the append-only ledger; file-base and research-graph indexes are disposable
projections.

## ARS integration boundary

ARW uses the current locally maintained and reshaped Academic Research Suite
(ARS) adapter as a bundled plugin skill at
`skills/academic-research-suite/`. The staged package carries the exact
modified router, workflows, references, Codex profile metadata, and adapter
manifest. The integration lock binds the bundled adapter version, upstream
source identities, and content digests; missing or drifting bundled content is
blocked. This repository's wording does not assert public fork ownership,
redistribution permission, or a license grant for ARS content.

The ARS-derived material follows the upstream CC BY-NC 4.0 terms. ARW does
not convert that material to MIT. The file-base component remains MIT, and the
complete component inventory is in `LICENSE`, `LICENSES/`, `MODIFICATIONS.md`,
`THIRD_PARTY_NOTICES.md`, and `vendor/source-manifest.json`.

The bundled adapter is version `0.1.26`. It tracks
`academic-research-skills@8cc7f8f4cccda721646d9df590b42721c93cba31`
(ARS v3.19.0 plus post-tag `main` updates through 2026-08-09) and
`experiment-agent@e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651` (v1.1.0).
The Codex overlay also provides a source-audited annual venue registry for the
October 2026 ARR cycle, COLING 2027, NAACL 2027, and ECIR 2027 under
`skills/academic-research-suite/codex/references/annual_venue_profiles.*`.
Current venue facts must still be rechecked against official pages at use time;
accepted-paper patterns in that registry are editorial evidence, not template
requirements.

### Personal non-commercial research use

The maintainer's intended use of this repository is personal, non-commercial
academic research. In the CC BY-NC 4.0 license, “NonCommercial” means a use
that is not primarily intended for or directed toward commercial advantage or
monetary compensation ([license text](https://creativecommons.org/licenses/by-nc/4.0/legalcode),
[Creative Commons FAQ](https://creativecommons.org/faq/)). This project-use
statement is not a relicensing of the ARS-derived material and is not legal
advice. It does not authorize commercial use, imply endorsement, or remove the
obligation to preserve attribution, license notices, and modification notices
when sharing ARS-derived material. Commercial use or a materially different
distribution context requires separate permission from the applicable rights
holder.

The source repository is public for this declared personal research purpose.
The qualified-plugin and tagged-release workflows remain fail-closed and
continue to require their machine-verifiable evidence; a README statement
alone does not turn an unqualified stage into a release artifact.

The Science Workbench paper AST/export remains a v2/deferred boundary; ARW
does not claim to replace a complete research-to-paper workflow.

The files-first MCP is ARW's modified `DeusData/codebase-memory-mcp` adapter.
The installed launcher retains the upstream-compatible `file-base` command
name; `vendor/mcp-manifest.json` records its exact source commit, ordered ARW
patches, patched-tree digest, binary digest, protocol, and bounded capability
profile.

## Qualification status

The retained Phase 7 verifier records technical qualification separately from
release permission. Technical evidence may be `PASS` while release remains
`BLOCKED` until accountable intended-use, distribution, approval, and
CC-BY-NC permission evidence is supplied. See
`build/evidence/phase-07-final-13/phase-7-verification.json` for the latest
serial qualification receipt when present.

## Installation

### Development checkout

Requirements are Python `>=3.13,<3.15`, `uv>=0.11.28`, and (for the exact
host qualification path) Codex CLI `0.144.4`. The `uv` declaration is a
minimum compatible tool version; resolved Python dependencies remain pinned
by `uv.lock`, while source commits, artifact digests, schemas, and qualified
host identities remain exact reproducibility locks.

```bash
git clone <repository-url> academic-research-workbench
cd academic-research-workbench
uv sync --frozen --all-groups
./bin/arw help
```

`--all-groups` also installs the dependencies required by the bundled ARS
self-tests. Verify the complete vendored skill suite from the checkout root:

```bash
(cd skills/academic-research-suite/ars && \
  uv run --frozen --all-groups --project ../../.. python -m pytest -q \
    --ignore scripts/test_check_calibration_tiers.py)
```

The ignored calibration-tier test is an upstream maintainer check that requires
the deliberately non-vendored `.claude/CLAUDE.md`; the runtime manifest records
that boundary. Its executable Codex equivalents remain covered by the adapter
quality gates.

Source verification is an explicit online preparation step and materializes
ignored snapshots under `vendor/sources/`:

```bash
./scripts/materialize-sources --clean
./scripts/verify-sources --inputs-only
```

The native `file-base` binary is a separately qualified, modified
`codebase-memory-mcp` data-plane artifact. A clean checkout cannot skip the
pre-vendor license receipt: if the retained receipt or its source archives are
absent, `verify-sources` must fail closed. When those local qualification
inputs are present, build it through the denied-network evidence boundary:

```bash
mkdir -p build/evidence/local-native
./scripts/offline-exec \
  --evidence-root build/evidence/local-native \
  ./scripts/build-file-base --clean --run-upstream-tests
```

The ARS skill is staged with ARW; no silent clone or second installation is
used. A clean stage/install verification is required before the route can pass.

### Staged Codex plugin

Use a qualified staged package produced by the staging workflow for
installation. A source checkout does not contain a prebuilt `marketplace/`
directory; create one from the immutable stage explicitly. The stage must
carry `supply-chain/integration-lock.json`; an unlocked stage is diagnostic
only and cannot qualify the route:

```bash
./scripts/stage-plugin --clean --stage-root build/stage/bootstrap
```

This bootstrap stage is only the deterministic input for host qualification;
do not install it. For host qualification, use
`./scripts/smoke-staged-plugin` so the marketplace, fresh homes, hook trust,
and installed inventory are isolated and recorded together.

The staging and smoke scripts record the exact stage identity, installed
inventory, hook definition, MCP launcher, and version tuple. Do not install
from a dirty source checkout when making a qualification claim.

For a repeatable final stage, first run
`scripts/qualify-codex-host` against the deterministic bootstrap stage and
retain its redacted `canary.json`. Then bind that exact evidence to the stage
with the fail-closed helper (the launcher/native paths are part of the lock):

```bash
./scripts/qualify-codex-host \
  --stage-root build/stage/bootstrap \
  --evidence-root build/evidence/host-canary \
  --work-root build/qualification-work \
  --credential-source "$CODEX_HOME" \
  --codex-launcher "$(command -v codex)"
./scripts/prepare-qualified-stage \
  --host-canary-evidence build/evidence/host-canary/canary.json \
  --codex-launcher /usr/local/sbin/codex \
  --codex-native-binary /path/to/exact/native/codex \
  --stage-root build/stage/qualified \
  --evidence-root build/evidence/qualified
```

Only after that command succeeds, create and install the qualified marketplace
copy:

```bash
./scripts/create-marketplace --stage-root build/stage/qualified
codex plugin marketplace add ./build/marketplace --json
codex plugin add academic-research-workbench@arw-local --json
```

`create-marketplace` copies the exact staged tree and writes the local
marketplace manifest. Do not install an unlocked bootstrap stage.

The helper never fabricates a canary or silently upgrades a missing lock. A
qualified stage still reports `release_qualification: BLOCKED` until the
retained CC BY-NC intended-use, distribution, accountable-approval, and
permission evidence is resolved. If host canary evidence is not supplied,
`bin/arw route --json` remains blocked with
`integration_inputs_incomplete` by design; supplying the exact retained
`ARW_HOST_CANARY_EVIDENCE` makes the verifier recompute the lock and can return
`integration_status: PASS` on the same host.

## Release boundary

CI builds and tests every change, but CD is fail-closed: a release job stops
unless the retained license verdict is `PASS`, accountable intended-use and
distribution evidence is present, and the P04-09 human gate is complete.
Planning files, local evidence, build directories, credentials, and materialized
third-party sources are excluded from source archives and staged payloads.
