# Offline candidate selection audit

`arw selection-audit export` emits a JSON receipt to stdout from one already retained, parent-accepted run. It accepts no network or model calls and writes nothing. ARS consent must authorize an explicit local export. Example:

```sh
arw selection-audit export --run-root RUN --expected-head EVENT_SHA256 \
  --plan-artifact artifact.plan --retrieval-artifact artifact.retrieval \
  --ledger-artifact artifact.ledger --reading-artifact artifact.reading
```

Omit `--reading-artifact` when no complete author reading log exists. The receipt then reports `reading_status: unknown`, `coverage_status: unknown`, and null round/stop. Selected work families and final citations do not prove reading. A trace is `arw.selection-reading-trace.v1`: it binds the plan and ledger digests, selected family/member raw-hit IDs, ordered `(round, order)` positions, `stance` with `human_assertion` or `unknown` basis, optional reached rounds and stop reason, and a `complete_log` flag. An incomplete log retains partial rows but does not establish full coverage.

Save the stdout JSON explicitly if desired, then verify it against the same canonical run:

```sh
arw selection-audit replay --receipt receipt.json --run-root RUN
```

Replay checks the receipt digest, current journal head, ARS normative derivation, each accepted artifact event/manifest/content, and exact result bytes. A stale or tampered receipt fails. Source paths are confined by the existing bounded retained-file reader. The command never changes a manuscript, run journal, or ARS upstream implementation.

The repository's self-authored teaching pool can be replayed offline:

```sh
arw selection-audit replay --fixture tests/fixtures/selection-audit/self-authored-pool.json
```

Its labels are explicitly synthetic assumptions, not scientific assessments. Its original supportive citation points to an exact synthetic source byte span with a checked SHA-256, yet two opposing families remain unread. It compares original, support-first and oppose-first orders under the same two-read early-stop budget, preserving each read set and direction. The separate four-item SRS example enumerates all six two-item draws and recomputes inclusion probability 1/2. The production receipt remains `descriptive_only`: actual search/reading logs do not prove randomized inclusion, selection, or round reach. Zero complete-log reads have zero observed coverage but an unknown conclusion; unlogged reads remain unknown. This does not estimate the bias of an actual literature review. An empirical public pilot has not been measured.
