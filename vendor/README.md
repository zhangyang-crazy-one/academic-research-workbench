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
The ARS manifest's `3.22.2` is the **Codex adapter version**; the source at
`7de1c9dfb7af9c02a9b57750761323f35a743aa2` is ARS **v3.22.2** (see
`skills/academic-research-suite/manifest.json` and the materialized upstream
`.claude-plugin/plugin.json`). From 3.22.0 the ARS-Codex package numbers its
releases after the suite, so the two values coincide here; the watcher still
compares commits, not version strings. Neither source identity is a Python
package compatibility pin. Python dependency declarations remain open lower
bounds. Missing API metadata and histories beyond the scan cap are reported as
unknown, not as proof that the vendor is current. A release tag is an
approved source revision. The job never downloads or executes upstream code,
and it does not edit source manifests, snapshots, patches, or binaries.

ARS was synced from v3.21.1 to
[v3.22.2](https://github.com/Imbad0202/academic-research-skills/releases/tag/v3.22.2)
on 2026-10-05 (issue #47). The license and NOTICE bytes are unchanged
(CC BY-NC 4.0). The adapter, integration lock, manifests, notices, and
pre-vendor receipt were regenerated for the new commit; `MODIFICATIONS.md`
records the merge method and the ARW-owned overlays. The CC BY-NC permission,
intended-use, distribution-class and accountable-approval blockers are
unchanged by a source sync.

file-base was upgraded from `ee68144` (`v0.9.0-2-gee68144`) to
[v0.11.0](https://github.com/DeusData/codebase-memory-mcp/releases/tag/v0.11.0)
(`8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798`) on 2026-10-06 (issue #47). The
four local patches in `mcp-manifest.json` were rebased onto the new source:
server naming (`0001`), confined reads (`0002`), generation builder (`0003`),
and research graph (`0004`). Upstream v0.11 has no native `read_file` MCP
tool, so `0002` is retained. `0003` also registers `files-build` as a stateless
command, because v0.11 otherwise runs every non-listed command as a client of
the new mandatory daemon. The pre-vendor dependency license gate was rerun on
the v0.11 inventory with the canonical producer toolchain, and it added three
grammar licenses (ArkTS, Chialisp, PL/SQL). The source, patch, legal-input,
binary, notice and SBOM digests and the normal, ASan+UBSan and TSan native
qualification evidence were all regenerated. The MCP tool list grows from 8
to 18 tools because v0.11 removed `tools/list` pagination; the capability
profile and ARW's confinement contract are unchanged. Existing indexes must be
rebuilt after the upgrade.

v0.11's upstream suite is kept byte-identical and passes on all three native
surfaces. To achieve that, the ARW patches changed how they extend upstream
(`MODIFICATIONS.md` has the details):

- The Text and PDF file kinds sit outside the language enum.
- Text is indexed only through explicit extensions.
- `read_file` is listed only when an allowed root is configured.

The upstream suite is qualified by running `scripts/offline-exec` through
sudo. Root creates the network and PID namespaces without a user namespace,
the suite runs as the invoking user, and the strace network audit uses
`--seccomp-bpf`. The three native evidence runs built a byte-identical binary,
and a local `build-file-base` reproduces it.

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
remain separate source-admission work; the ARS v3.22.2 sync ran the bundled
ARS self-tests separately.
