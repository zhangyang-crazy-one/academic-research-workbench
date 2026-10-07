# Upstream drift assessment: 2026-09-30

Tracking: [issue #47](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/47).
Disposition: **assessed; source admission deferred**.

Update 2026-10-05: ARS was synced to v3.22.2 (`7de1c9d`) following
checklist items 1, 2 and 5; see `MODIFICATIONS.md` and `vendor/README.md`.
The file-base upgrade and the CC BY-NC / use-distribution approvals are
tracked separately. This document does not
admit a source, accept a license, qualify an upgraded runtime, or close the
drift tracker. Keep the existing source pins until the gates below pass.

## Verified candidate identities

GitHub's `releases/latest`, tag-ref, and compare metadata were read on
2026-09-30. Both releases are non-draft, non-prerelease releases:

| Component | Current source | Observed candidate | Compare result |
| --- | --- | --- | --- |
| ARS | `127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb` (v3.21.1) | [v3.22.2](https://github.com/Imbad0202/academic-research-skills/releases/tag/v3.22.2), published 2026-09-25; commit `7de1c9dfb7af9c02a9b57750761323f35a743aa2` | 53 commits ahead |
| file-base / codebase-memory-mcp | `ee68144af5453addda995a27cce8142999f318fb` (`v0.9.0-2-gee68144`) | [v0.11.0](https://github.com/DeusData/codebase-memory-mcp/releases/tag/v0.11.0), published 2026-09-15; commit `8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798` | 1,626 commits ahead |

ARS's annotated tag object is `87c1262921d3c33d6b2524e48b8a5ccc20d83786`;
the source commit is its peeled target above. The manifest's `0.1.27` is
the Codex adapter version, not the upstream suite version.

Comparisons: [ARS](https://github.com/Imbad0202/academic-research-skills/compare/127ff85e4bbfcdd10b95040537b6c6bd7ad17aeb...7de1c9dfb7af9c02a9b57750761323f35a743aa2),
[file-base](https://github.com/DeusData/codebase-memory-mcp/compare/ee68144af5453addda995a27cce8142999f318fb...8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798).
Each API comparison returned 300 file records, a capped view, not a complete
change inventory. Do not infer unchanged licenses or patch compatibility
from a path missing from that response.

## Relevant changes and risk

### ARS

The candidate changes citation-check loading and Chinese APA 7 guidance,
adds an advisory deterministic acronym checker, broadens the prompt-level
instruction/data boundary, and repairs routing on plugin/skills-copy installs.
The v3.22.2 release also adds a passport-adjacent run ledger containing exact
user instructions and answers, receipt outcomes, and file hashes.

Review ledger retention/deletion and authority explicitly: ARW's canonical
journal and parent admission must remain authoritative. A second ledger or
an upstream prompt cannot establish user authorization or successful execution.
Check compaction/resume behavior, stale receipts, missing files, broken chains,
and routing overlays. Keep acronym findings advisory rather than silently
changing publication decisions or authorized revision scope. Review changes
to claim-audit prompt/cache identity and duplicated instruction-boundary text.
Upstream describes several prompt effects as unmeasured; synthetic checks and
release claims do not establish behavior in the installed Codex adapter.

### file-base

This is substantially larger than the release's v0.10.8-to-v0.11.0 summary:
ARW starts from a v0.9-derived commit. v0.11.0 changes File-node identities
to retain extensions and rebuilds stale-format indexes once. Default CLI/MCP
output becomes compact; diagnostics, evidence and JSON require opt-in, and
semantic pagination binds cursors to arguments, result state and generation.
Memory/spill behavior and native resolution code also change.

The returned change list includes the graph UI lockfile, new grammar licenses,
and changes to native license-gate/policy tooling. The existing MIT label does
not establish that the candidate dependency inventory passes ARW's policy.

All four local patches need an isolated rebase. Patch `0001` is named for
server naming but also modifies discovery, language and pipeline code;
`0002` modifies discovery, MCP, semantic edges and similarity; `0003` adds
the parent-only generation builder in `src/main.c`; `0004` supplies the
research-graph profile. Do not drop confinement merely because upstream has
security-related changes. Preserve allowed-root, bounded-read, parent-only
write, graph authority and replay invariants with native tests.

## Admission checklist

1. In an isolated candidate workspace, collect the complete exact-commit
   diffs and clean source archives; review license/notice/dependency changes
   before materialization into the integration. Retain content and Git-tree
   hashes, raw gate evidence and a fresh pre-vendor receipt. The current
   `scripts/pre-vendor-license-gate` and `scripts/verify-sources` also embed
   exact revisions, so editing only `vendor/source-manifest.json` is insufficient.
2. For ARS, reconcile the generated adapter with the new upstream tree while
   preserving ARW-owned overlays, manifests, exclusions and command boundaries.
   Run upstream self-tests with documented adaptation exclusions, Codex quality
   gates, citation/routing/ledger fixtures, and installed-host checks.
3. For file-base, rebase each patch separately with pre/post tree hashes.
   Compare tools/list and representative tool calls against
   `tests/compat/golden/filebase/`; exercise `test_mcp_confinement.py`,
   `test_file_generations.py`, and `test_graph_mcp_profile.py` using the actual
   rebuilt binary. Run native upstream tests, ASan/UBSan and TSan.
4. Prove migration on disposable copies: same-stem/different-extension files,
   old-index rebuild, ADR/metadata retention, interruption/retry, stale cursors,
   over-budget failure, and rollback to the separately retained old index and
   binary. Never exercise a first-run rebuild against a user's only index.
5. Regenerate source/MCP manifests, adapter identity and integration lock,
   binary digest, modification records, notices, license inventory and SBOM.
   Run `verify-sources`, the license gate, offline build/stage verification,
   full relevant tests, and fresh exact-stage host qualification. Existing
   Phase 7 locked evidence cannot be reused for changed source or binaries.

## Decisions and current evidence

An accountable maintainer must choose candidate admission after reviewing the
above evidence. Separately, `supply-chain/use-distribution.json` still records
unknown intended use/distribution and missing accountable approval;
`supply-chain/license-verdict.json` reports `CC_BY_NC_PERMISSION_UNRESOLVED`
for ARS/experiment-agent. Technical upgrade work does not resolve these
release blockers. Preserve the blocked release verdict until authentic use
or permission evidence and approval exist.

Safe work now is full read-only diff/license inventory and candidate test
design. Candidate execution, patch rebase and regenerated admission artifacts
are the next scoped engineering task after review; this assessment performed
none of those steps and changed no pins, patches, source trees or approvals.

Validation performed: `.venv/bin/python -m pytest -q
tests/unit/test_vendor_drift.py` passed **15 tests** on 2026-09-30. This verifies
the existing watcher, not either upgraded integration. Issue #47 correctly
continues to show drift; a report or passing watcher test is not completion of
source admission.
