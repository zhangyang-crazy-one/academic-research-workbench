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

The bundled adapter is version `0.1.27`. It tracks
`academic-research-skills@127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb`
(ARS v3.21.1, released 2026-08-24) and
`experiment-agent@e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651` (v1.1.0).
The ARW core requires Codex CLI `>=0.144.4`; the optional contained
subscription citation transport is capability-gated and requires Codex CLI
`>=0.147.0`.
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
profile. The plugin does not register this MCP by default. File access remains
disabled until a project explicitly opts in.

## Qualification status

The retained Phase 7 verifier records technical qualification separately from
release permission. Technical evidence may be `PASS` while release remains
`BLOCKED` until accountable intended-use, distribution, approval, and
CC-BY-NC permission evidence is supplied. See
`build/evidence/phase-07-final-13/phase-7-verification.json` for the latest
serial qualification receipt when present.

## Grok Bot consumption

This repository is Codex-native. A thin, fail-closed adaptation for the
Grok Bot named `arw` lives in `grok-bot/` and is **not** a second plugin
install, a Codex marketplace path, or a qualified-stage unlock. See
`grok-bot/GROK_BOT.md`.

## Installation

### Enable the files-first MCP for one project

After installing a qualified plugin with its native `libexec/file-base-mcp`
binary, create an existing research root and an existing cache directory outside
that root. Point `--target` at the **project** configuration file. The command
checks Python, the native provider, allowed root, cache, target and binary before
writing; it never edits user or global host configuration.

```bash
mkdir -p /path/to/project/.codex /path/to/file-base-cache
/installed/plugin/bin/arw files enable --provider native --host codex \
  --target /path/to/project/.codex/config.toml \
  --root /path/to/research --root-id research --cache-dir /path/to/file-base-cache

# For Claude Code, use the project's .mcp.json instead:
/installed/plugin/bin/arw files enable --provider native --host claude \
  --target /path/to/project/.mcp.json \
  --root /path/to/research --root-id research --cache-dir /path/to/file-base-cache

/installed/plugin/bin/arw health --json
```

Run one host command for each project that needs files-first access. The
generated entry binds that root and cache explicitly; inspect the generated
project config before starting a new host session. Codex loads project config
only for trusted projects. A plain source checkout lacks the qualified native
binary, so `files enable` returns a structured `native_binary_missing` result
without creating a config. Run `health --json` from the target project to see
its Codex and Claude project-config states plus native binary readiness.
Bounded source retrieval supports citation checks and manuscript drafting;
source files and the parent-owned journal remain authoritative.
Existing `ARW_FILES_*` launcher deployments retain
their startup-only `STORE_ABSENT=69` fallback.

### Development checkout

Requirements are Python `>=3.13`, `uv>=0.11.28`, and (for the host
qualification path) Codex CLI `>=0.144.4`. Python dependency versions are
intentionally flexible and resolved when installing; this project does not
include or require a `uv.lock` dependency lockfile. The uv project integration
is unmanaged to prevent automatic lock creation; setup uses `uv pip` to resolve
the declared ranges. Source commits, artifact digests, schemas, and actual host
observations remain evidence about the inputs used, not compatibility pins.
The launcher accepts newer Python versions that satisfy the minimum; each host
still needs to pass its runtime and dependency qualification checks.

### Platform support

| Platform | Support | CI coverage and limits |
| --- | --- | --- |
| Linux | Tier 1 | Full non-host Python tree and a separate native confinement/admin job on each PR; ASan/UBSan native suite nightly. |
| macOS | Tier 2 | Canonical state, manifest, recovery, and platform-report unit tests on each PR. The Linux network-denied native builder is unavailable. |
| Windows | Unsupported | No Windows CI job or native file-base qualification; POSIX descriptor-relative file access and the Bash launcher are unavailable. |

`arw health --json` reports the running platform's tier and capabilities that
are unavailable for platform reasons. A successful health response observes the
environment; it does not grant release qualification. Linux native jobs build
from pinned source snapshots in ignored work areas and do not rewrite
`vendor/source-manifest.json`.
Initial setup or a later dependency install needs access to the configured
package index unless compatible packages are already cached; offline dependency
resolution is not guaranteed. Once installed, research operations retain their
existing local/offline behavior where each capability supports it.

```bash
git clone <repository-url> academic-research-workbench
cd academic-research-workbench
uv venv
.venv/bin/python scripts/install-unmanaged-deps.py --all-extras dev ars-test storm
./bin/arw help
```

The selected groups also install the dependencies required by the bundled ARS
self-tests. Verify the complete vendored skill suite from the checkout root:

```bash
(cd skills/academic-research-suite/ars && \
  ../../../.venv/bin/python -m pytest -q \
    --ignore scripts/test_check_calibration_tiers.py \
    --ignore scripts/test_check_distribution_surface_claims.py)
```

The ignored calibration-tier and distribution-surface tests are upstream
maintainer checks that require deliberately non-vendored `.claude/CLAUDE.md`
and `.claude-plugin` inputs. The runtime manifest records both boundaries;
their executable Codex equivalents remain covered by the adapter quality gates.

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
CANDIDATE_WHEEL="$(./scripts/build-candidate --output-root build/candidates/local-001)"
./scripts/license-gate \
  --wheel "$CANDIDATE_WHEEL" \
  --build-evidence build/candidates/local-001/build-evidence.json \
  --output-root build/evidence/candidates/local-001
./scripts/stage-plugin --clean \
  --candidate-wheel "$CANDIDATE_WHEEL" \
  --build-evidence build/candidates/local-001/build-evidence.json \
  --candidate-evidence-root build/evidence/candidates/local-001 \
  --stage-root build/stage/bootstrap
```

Use fresh candidate and gate roots for each attempt. The build records the
actual Python, uv, backend, resolved build packages, wheel and sdist digests.
The license gate records its own validation environment; installation smoke
records a separate resolved installation inventory. These observations do not
constrain later dependency resolution. Package installation needs the configured
package index when compatible dependencies are absent from the local cache.
The gate requires the pinned pre-vendor legal receipt and verified source
snapshots; it never rebuilds or replaces the supplied wheel.
Its source preflight checks manifest-bound inputs; the native binary and its
build evidence are checked when the plugin is staged.

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
  --candidate-wheel "$CANDIDATE_WHEEL" \
  --build-evidence build/candidates/local-001/build-evidence.json \
  --candidate-evidence-root build/evidence/candidates/local-001 \
  --host-canary-evidence build/evidence/host-canary/canary.json \
  --codex-launcher /usr/local/sbin/codex \
  --codex-native-binary /path/to/exact/native/codex \
  --stage-root build/stage/qualified \
  --evidence-root build/evidence/qualified
```

`prepare-qualified-stage` passes that same wheel through bootstrap and final
staging. Rebuilding after the gate creates a new candidate and requires new
evidence. For transfer, `scripts/candidate-bundle create` records the explicit
wheel and source artifacts with their digests. `scripts/candidate-bundle archive`
packs the verified manifest files into a tar archive, preserving hidden stage
files and executable modes; `scripts/candidate-bundle extract` rejects unsafe
members and rechecks every digest after download. The release workflow selects
only the verified wheel and sdist for publication. The current approval and
permission fields have no independently verifiable authority contract, so
`check-release-candidate` keeps release qualification blocked even if
transferred records self-report `PASS`.

To prepare a transfer:

```bash
./scripts/candidate-bundle create \
  --wheel "$CANDIDATE_WHEEL" \
  --build-evidence build/candidates/local-001/build-evidence.json \
  --candidate-evidence-root build/evidence/candidates/local-001 \
  --output-root build/candidate-bundles/local-001
```

A candidate with independently produced Phase 7 evidence uses the five explicit
inputs below. `candidate-bundle` verifies that the Phase 7 source commit,
stage digest, integration lock and host canary refer to the supplied wheel,
then copies only the canary's path-bound evidence files from its evidence root.
The equivalent `--qualification-root` form must contain
`phase-7-verification.json`, `stage/`, `integration-lock.json`,
`host-canary.json`, and the canary's referenced evidence files with the same
relative paths and hashes.

```bash
./scripts/candidate-bundle create \
  --wheel "$CANDIDATE_WHEEL" \
  --build-evidence build/candidates/local-001/build-evidence.json \
  --candidate-evidence-root build/evidence/candidates/local-001 \
  --phase7-verification build/evidence/phase-07/phase-7-verification.json \
  --qualified-stage build/stage/phase-07-qualified \
  --integration-lock build/evidence/phase-07/integration-lock.json \
  --host-canary build/evidence/phase-07/host-canary/canary.json \
  --canary-evidence-root build/evidence/phase-07/host-canary \
  --output-root build/candidate-bundles/qualified-local-001
./scripts/candidate-bundle verify --bundle-root build/candidate-bundles/qualified-local-001
./scripts/candidate-bundle archive \
  --bundle-root build/candidate-bundles/qualified-local-001 \
  --output build/candidate-bundles/qualified-local-001.tar.gz
```

`verify-phase-7` currently records `release_qualification: BLOCKED` while
legal and accountable approval evidence is unresolved; packaging its technical
result does not change that status. The release
workflow takes the exact Actions run ID and artifact name, downloads and
rehashes the bundle, checks its source commit and release gates, transfers it
between jobs, then rehashes it again before publishing only the listed wheel
and sdist. Missing qualification evidence blocks publication; it cannot be
replaced by CI's technical bundle. Manual release dispatch supplies
`candidate_run_id`, `candidate_artifact_name`, and `release_tag`; tag-triggered
runs require `ARW_CANDIDATE_RUN_ID` and `ARW_CANDIDATE_ARTIFACT_NAME` repository
variables for the exact qualified transfer.

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
On a successful push to `main`, CI creates SLSA provenance for the candidate
wheel, sdist, and retained CycloneDX SBOM file after Python validation. It also
attests that CycloneDX SBOM as the predicate for the wheel and sdist. Release
qualification checks both predicates for each package artifact, the SBOM file's
provenance, and the predicate's content against the retained SBOM. Each claim
must match the `ci.yml` signer, `refs/heads/main`, and the source commit bound
to the release tag before transfer to publish.
Consumers can verify downloaded candidate files with GitHub CLI:

```bash
REPO=OWNER/REPO
TAG=vX.Y.Z
SOURCE_COMMIT="$(git rev-parse "refs/tags/$TAG^{commit}")"
for file in path/to/*.whl path/to/*.tar.gz; do
  for predicate in https://slsa.dev/provenance/v1 https://cyclonedx.org/bom; do
    gh attestation verify "$file" --repo "$REPO" \
      --signer-workflow "$REPO/.github/workflows/ci.yml" \
      --source-ref refs/heads/main --source-digest "$SOURCE_COMMIT" \
      --predicate-type "$predicate"
  done
done
gh attestation verify path/to/SBOM.cdx.json --repo "$REPO" \
  --signer-workflow "$REPO/.github/workflows/ci.yml" \
  --source-ref refs/heads/main --source-digest "$SOURCE_COMMIT" \
  --predicate-type https://slsa.dev/provenance/v1
```

The attestation establishes build identity for those bytes; it does not
establish scientific validity or human authorship. Hosted OIDC creation and
retrieval/verification still require evidence from an authorized Actions run.
The owner policy keeps reviewed Action major tags and open `>=` Python ranges
without a lockfile. Issue #32's exact-SHA and zero-high `zizmor` criteria remain
unmet under that policy; no finding is suppressed or reported as cleared.
Planning files, local evidence, build directories, credentials, and materialized
third-party sources are excluded from source archives and staged payloads.
