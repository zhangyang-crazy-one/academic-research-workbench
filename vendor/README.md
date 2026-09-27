# Third-Party Source Materialization

`vendor/sources/` is intentionally ignored by Git. It contains complete
third-party source snapshots and generated parser assets, which exceed 1 GiB
and are not first-party plugin code.

Before a source build or legal verification, run:

```bash
./scripts/materialize-sources
```

The command fetches the exact commits recorded in `source-manifest.json`,
checks their Git-tree and content-tree hashes, and atomically creates the local
`vendor/sources/` work area. It must run online. Subsequent
`scripts/offline-exec` build and verification steps consume that local copy.

Do not add `vendor/sources/` back to Git. Commit source-manifest changes,
patches, license notices, and SBOM updates instead.

`mcp-manifest.json` is intentionally small and committed. It names the
modified upstream `DeusData/codebase-memory-mcp` integration, binds the exact
source and four-patch series to the staged `file-base` binary, and records the
MCP protocol/capability profile. The 1.3 GiB `vendor/sources/file-base`
materialization remains ignored; it is reproducible from the pinned source
manifest and patches.

## Upstream drift and upgrade assessment (2026-09-25)

The weekly `.github/workflows/vendor-drift.yml` observes stable GitHub Releases
for only `Imbad0202/academic-research-skills` and
`DeusData/codebase-memory-mcp`. It compares each release tag with the exact
source commit in `source-manifest.json` using GitHub's commit-list metadata
(capped at 3,000 commits per direction; no compare patches or source files).
The ARS manifest's `0.1.27` is the **Codex adapter version**; the source at
`127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb` is ARS **v3.21.1** (see
`skills/academic-research-suite/manifest.json` and the materialized upstream
`.claude-plugin/plugin.json`). Neither source identity is a Python package
compatibility pin. Python dependency declarations remain open lower bounds.
Missing API metadata and histories beyond the scan cap are reported as
unknown, not as proof that the vendor is current. A release tag is an
approved source revision. The job never downloads or executes upstream code,
and it does not edit source manifests, snapshots, patches, or binaries.

ARS [v3.22.1](https://github.com/Imbad0202/academic-research-skills/releases/tag/v3.22.1)
includes citation-check loading and Chinese APA 7 repairs. Those changes are
relevant to ARW's citation integrity, but this watcher change **defers source
admission**. The present source license is CC BY-NC 4.0, and the current
adapter binds the v3.21.1 source commit, integration lock, notices, and
ARW-owned overlays. Admission of v3.22.1 requires checking its license and
notices, materializing and hashing the exact source commit, rebuilding the
adapter/integration lock and manifest, reviewing overlay conflicts and plugin
eval suites, then running the ARS self-tests and ARW qualification. None of
those upgrade tests was run for v3.22.1 in this change; its release notes are
not evidence that the adapted runtime passes.

file-base is currently `ee68144af5453addda995a27cce8142999f318fb`
(`v0.9.0-2-gee68144`) with four local patches in `mcp-manifest.json`:
server naming (`0001`), confined reads (`0002`), generation builder (`0003`),
and research graph (`0004`). Upstream
[v0.11.0](https://github.com/DeusData/codebase-memory-mcp/releases/tag/v0.11.0)
declares an index rebuild and changed tool output contract. The patch series
touches MCP, discovery, and graph code, so a v0.9 to v0.11 upgrade needs an
isolated rebase and contract/migration spike before admission. Specifically,
test each patch against the new source; check whether upstream now provides
equivalent allowed-root/bounded-read behavior before retaining `0002`; compare
MCP output and index rebuild behavior; rerun the dependency license gate,
confinement/security tests and C sanitizers; then regenerate source, patch,
binary and notice/SBOM evidence. The current source license is MIT, but the
v0.11 dependency inventory has not been reviewed here. No patch application,
new-source build, index migration or security backport qualification was
performed in this watcher change. Any candidate security fix needs separate
triage and a qualified backport or explicit source upgrade.

Local report replay uses `python scripts/vendor-drift-report --fixture <json>`.
`scripts/vendor-drift-issue` defaults to no write; it requires `--write` and a
token for a remote update. The workflow's manual dispatch defaults to dry-run,
and the issue reporter neither creates labels nor closes trackers. The
source-update process remains `scripts/materialize-sources`, license/notice
review, patch review, manifest regeneration, and project qualification under
an explicit maintainer decision.

Acceptance for this watcher change is offline: the fixture unit suite checks
release classification, source-manifest byte preservation, sanitization,
idempotent issue planning, and workflow permissions/YAML. The hosted schedule,
GitHub token behavior and actual issue update were not exercised locally;
those require a future hosted run. The four-patch rebase, v0.11 index migration,
and v3.22.1 ARS self-tests remain separate source-admission work.
