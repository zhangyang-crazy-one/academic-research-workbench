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
| 10 | 1 P1 | Original source fix present; the September 8 audit found a new built-wheel/SBOM mismatch, addressed by the packaging follow-up below |
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

## Latest-head follow-up (`f744460` review)

- P1 `3939364471`: installed store reads now also bind the canonical selected
  generation ID; a stale ingestion cache raises `stale_ingested_cache` (exit 78),
  rather than silently serving an older inventory.
- P2 `3939364472`: exit 69 is reserved for genuinely missing store paths.
  Non-regular entries, broken-symlink/non-directory ancestors, and I/O errors
  fail closed (78). Genuinely uncreated nested cache directories still allow
  the documented fallback. Thirteen regression cases were added.
- Final serial regression selection: 687 passed. Clean-index snapshot schema,
  supply-chain inventory, and graph-install tests: 33 passed. The first snapshot
  staging attempt lacked the existing pinned legal verdict fixture; rerunning
  with that unchanged evidence restored passed without relaxing any gate.
- Clean-index license gate: technical PASS / release BLOCKED. SBOM wheel hashes
  come from task-only staged source, not unrelated dirty working-tree changes.
- Latest-head Codex review and CI must pass again before merge.

## Long-lived readers (`0249df5` review)

- P1 `3939599512`: all five file operations use a dedicated read-only SQLite
  transaction and validate canonical selection before and after assembling the
  result. Drift returns `stale_query_generation`; callers restart the reader.
- Per-adapter serialization prevents concurrent native callers sharing a request
  connection. Success and failure both release the connection and request lock.
- Canonical selection reads are capped at 64 KiB, descriptor-relative, no-follow,
  and nonblocking. Unsupported secure primitives fail closed rather than silently
  downgrading. Post-start FIFO, symlink, ancestor-symlink, and oversized-file
  substitutions are covered alongside real second-connection WAL commits.
- The compatibility fixture explicitly commits its seeded projection before
  testing the independent read snapshot; runtime isolation is not weakened.
- Serial regression selection: 706 passed; subsequent type-only correction
  rechecked with 58 focused tests. Clean-index license technical PASS / release
  BLOCKED. Latest-head Codex review and CI remain required before merge.

## Complete bindings and conflict-policy follow-up (`1fdbc1f` review)

- P1 `3939835815`: unsupported secure-reader primitives are rejected at startup
  (exit 78), before stdin/initialize; the error points to explicit legacy-reader
  configuration. This is capability rejection, not a claim of a Windows-native
  secure reader. Unsupported-platform behavior is simulated in a subprocess.
- P1 `3939835826`: strict, duplicate-key-rejecting selection validation now binds
  root ID, generation ID, and manifest digest to the loader-validated startup
  selection. Canonical-root callers cannot omit the trusted digest.
- P2 `3939835833`: incompatible unique/conflict policies are rejected; bounded
  inventory counts inside the write transaction detect silent replacement and
  roll back. Legitimate distinct records sharing an entity remain supported.
- `provenance record` no longer discards verification faults. Both record and
  verify return exit 65 on faults; verify retains structured fault JSON.
- Serial regression selection: 731 passed. Seven touched Python files confirmed
  primary-LSP clean. No expected-failure markers hide the CLI regression.

## Inventory, receipt budgets and reproducible packaging

The follow-up to review comments `3940050812` and `3940050813` binds cached
file rows to the loader-verified canonical generation and bounds aggregate
audit receipt input and output. Cache metadata alone does not establish that
the rows or search index represent the selected generation.

Each canonical file request validates a typed inventory fingerprint in its
read-only transaction. Search also checks FTS recall against the verified
folded body text: replacing shadow postings with an empty index must produce
an integrity error rather than a successful empty result. Inventory checks
and query execution share the five-second request deadline. Oversized
inventories return a typed budget failure; this does not invalidate canonical
evidence or authorize a read-path index repair.

Audit loading defaults to at most 4 MiB of receipt input and 256 KiB of
canonical fault output, with explicit truncation faults. The output limit
includes retained receipt identifiers and generated fault messages.

Wheel construction pins Hatchling 1.31.0 and stores sorted ZIP members without
compression, preserving payload bytes and RECORD while eliminating differences
between host compression libraries. CI compares the actual first-party wheel
SHA-256 with the checked-in SBOM. The dependent technical-evidence hash is
refreshed from that SBOM; no legal-use declaration or release authorization is
changed.

The completed FileProvider interface is the existing five-operation contract
listed above and in `v2-invariants.md`. Future research-manifest ingestion and
sync operations require their own qualification.

### Canonical database snapshot binding

The canonical inventory anchor must query the exact database bytes whose
SHA-256 matches the selected generation manifest. A loader check followed by
reopening the original pathname leaves a substitution window: changed database
rows can become the expected fingerprint even though the manifest and selection
have not changed.

Canonical fingerprint construction therefore reads through one safely opened
descriptor, enforces a separate 256 MiB raw-database limit, checks the manifest
digest, and queries a private SQLite byte snapshot with writes disabled. It does
not reopen the canonical pathname for SQL or consult sibling WAL files. This is
a startup query limit; the existing per-request row, aggregate, FTS and deadline
limits remain in effect. Missing safe-descriptor or SQLite deserialization
capabilities produce an explicit startup failure.

The regression boundary includes both pathname replacement and in-place edits
after loader validation, plus replacement after the private bytes are captured.
The latter cannot change the fingerprint derived from the verified snapshot.
