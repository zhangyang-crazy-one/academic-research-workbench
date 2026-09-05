# Historical PR review closure

This audit compares historical review findings with the current source, rather
than treating a closed PR or resolved thread as proof of a fix. PR #16 remains
subject to latest-head Codex review and CI before merge.

## Coverage

| PR | Historical findings inspected | Disposition |
| --- | --- | --- |
| 1, 2 | No review threads | No findings to reconcile |
| 3 | 2 P2 | Fixed in `052b3d8`; GitHub threads remain outdated/unresolved |
| 4 | 75 original findings: 35 P1, 40 P2 | Current source fixes present; all reply-named fixing commits reachable |
| 5 | 4: 2 P1, 2 P2 | Current source fixes present |
| 7 | 6: 2 P1, 4 P2 | Current source fixes present |
| 10 | 1 P1 | Current source fix present |
| 12 | 2 P2 | Root-ID parameterization fixed; local OpenSpec now distinguishes the frozen five-tool surface from the future seven-tool target |
| 13 | 6: 4 P1, 2 P2 | Fixed, including projection data/head propagation, transactional migrations, deletion sweep, and fault persistence |
| 14 | 2: 1 P1, 1 P2 | Provider registration and capability-name mapping fixed in PR #15 |
| 15 | 16 P2 | Eleven already fixed; five transport/installation gaps addressed in this follow-up |

The audit retrieved all review-thread pages for these PRs. PR #4 has 150 inline
comments (75 original findings and 75 replies), not 150 independent defects.
Source inspection is distinct from execution evidence. Concurrent runs initially
invalidated shared temporary staging directories; final verification was rerun
serially after all write/test workers settled (results below).

## PR #15 follow-up scope

- Match the existing five-tool transport's non-error `degraded` / `no_structure`
  outline/context envelopes and `invalid_request` validation errors.
- Bind live file access to the explicitly selected registered root and root ID;
  mutable SQLite metadata cannot grant filesystem authority.
- Connect the installed file shim to the store reader, with no unanchored direct
  entry path and no legacy fallback on root, capability, or corruption failures.
- Bind installed graph and store-file MCP activation to the bundled plugin
  manifest; a missing installed manifest must not silently disable filtering.

A callable `_files-store-mcp` command alone does **not** establish that the
installed shim routes through it. The route must be exercised separately.

## Contract and test corrections

The shipped MCP/provider compatibility surface remains five read-only operations:
`list_files`, `read_file`, `search_files`, `get_outline`, and `get_context`.
The seven-tool research surface is a future target, not an implemented contract.
See [v2 invariants](../v2-invariants.md). The ignored local OpenSpec baseline is
reconciled separately; no research-ingest methods are added speculatively.

Four research-integrity tests incorrectly relied on jsonschema's optional default
`date-time` checker, which was absent in the locked environment. The test schema
validators now use the project's registered RFC 3339 checker. The bridge's
independent field-validator rejection remains tested with schema format checking
disabled. No production date validation, schemas, or negative cases were removed.

## Evidence collected before final integration

- PR #3: direct malformed schedule/source-ID reproductions reject correctly.
- PR #4: 28 folder-scan tests and 25 targeted integration-lock tamper tests pass.
- Current five-tool compatibility: 12 MCP/port/local-store contract tests pass.
- Graph manifest follow-up: 27 graph/capability tests pass in the locked uv env.
- Research-integrity correction: 103 tests pass; complete unit suite: 540 pass.
- PR #16 suffix and audit-entry follow-up: 14 focused tests pass.
- Store transport/root/shim follow-up: 21 tests pass, using isolated temporary
  plugin fixtures rather than mutating the repository's wheelhouse or lockfile.
- Final serial integration: 674 tests pass across the complete unit suite and
  selected CLI/MCP/provider/local-store/provenance regression suites.
- Final serial schema/staged checks: 33 tests pass (schema drift, supply-chain
  inventory, and graph installation). License gate: technical PASS; release BLOCKED.

These are scoped test results, not a claim that latest-head CI or the complete
staged release qualification has passed. License technical validation and legal
release permission remain separate gates.

## Historical references

- [PR #3](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/3):
  discussions `3742961527`, `3742961531` (fixed but not marked resolved).
- [PR #4](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/4):
  source/integrity/supply-chain gates; historical fixes retained, not relaxed.
- [PR #12 discussion 3903137928](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/12#discussion_r3903137928):
  five-tool baseline versus seven-tool target.
- [PR #15](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/15):
  store transport, allowed roots, installed routing, and graph manifest binding.
