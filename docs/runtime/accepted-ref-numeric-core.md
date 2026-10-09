# Accepted references and independent numeric core

These additive Python APIs preserve existing accepted bytes and original validators. They do not write authority records or migrate old receipts.

## Reference API

Import `ParentArtifactRef`, `JournalEventRef`, and the scope-discriminated `AcceptedRef` from `arw.kernel.state.accepted_ref`. Parent references bind project/run identity, run-manifest digest, artifact ID, accepting event ID/digest, and content digest. A JSON Pointer `selector` and optional canonical selected-value digest narrow a JSON selection. Source locators additionally retain the complete `source_locator`, its quote digest as `selected_sha256`, and `producing_activity_id`.

Import `ResolutionContext`, `RunPrefix`, `to_accepted_ref`, `resolve_ref`, and `verify_ref` from `arw.kernel.ledger.accepted_refs`:

```python
context = ResolutionContext(
    project_id="project.example",
    run_roots=(run_root,),
    project_root=project_root,
    run_prefixes=(RunPrefix(run_id, revision, head_sha256, run_manifest_sha256),),
    journal_sequence=journal_sequence,
    journal_head_sha256=journal_head_sha256,
)
result = to_accepted_ref(original, context, adapter_kind="ResearchBinding")
```

Omit prefix fields for a current read. Fixed prefixes use the original run/project journal validators and ignore unrelated later tails. Accepted events outside the selected prefix remain unresolved. `RefResolution` preserves `original` and reports `status`, `ref`, `proven_scope`, `reason`, whole-artifact `raw_bytes`, and `selected_value`. A selected JSON string is a Python string; SourceLocator selections are the original located bytes. General JSON `selected_value` follows existing selector semantics; exact arithmetic parses the retained raw literal separately.

`held_lock_roots` is an internal service-only context field. The parent service sets it only for exact roots whose writer lock it already owns. It is absent from JSON schemas and CLI input contracts. Such reads call `replay_run_under_held_lock` and revalidate real journal/manifests rather than accepting cached events or a caller validation flag.

| Adapter | Conditions and proof | Failure boundary |
|---|---|---|
| SourceLocator v1/v2 | Full original source/PDF/extraction/location/quote validator; activity and selected digest retained | Digest, location, unsafe path and missing PDF failures remain unresolved |
| EvidenceSpan | Source manifest has a selected-prefix acceptance and original integrity chain validates | Missing acceptance stays `no_accepting_event`; proof remains `metadata_only`, without claiming extraction text was retained |
| ClaimEvidenceLink | Preserved as a relation edge | `unsupported: edge_not_ref` |
| ResearchBinding | Acceptance/event/content and original JSON Pointer requirements | Cross-run names are `ambiguous_run`; non-JSON evidence is rejected even for empty pointer |
| SubmissionArtifactReference | Original manifest/content/acceptance binding | Cross-run names are `ambiguous_run`; manifest substitutions are rejected |
| MemoryLink | Artifact kind with both digest and event ID | Hashless/file/issue links never become accepted evidence |
| VenueSourceCapsule | Accepted canonical capsule digest and original capsule structure | `structural_capsule` proves retained capsule only, never the absent original PDF |

Models can be passed directly. Dictionaries with `scope` or known `schema_version` dispatch automatically. The three untagged legacy dictionaries require `adapter_kind="ResearchBinding"`, `"SubmissionArtifactReference"`, or `"MemoryLink"`. Explicit adapter names are also available for all seven types. No original object is rewritten.

## Exact numeric API

Models live in `arw.kernel.state.numeric_core`; evaluation functions live in `arw.kernel.policy.numeric_core`. `ComparisonContext` is shared from `arw.kernel.state.experiment_context`. The old `arw.kernel.artifacts.experiment_acceptance.ComparisonContext` import remains an alias to the same class with unchanged schema fields and constraints.

`RationalExact` has reduced numerator/positive denominator, each bounded to 128 decimal digits. JSON scalar decimals are parsed from hash-verified raw UTF-8 JSON using `Decimal`, preserving `0.10000000000000000001` separately from `0.1`. Duplicate keys and nonfinite constants are rejected. Decimal strings are supported; fraction notation such as `"1/3"` is outside the scalar domain. An exact 1/3 is represented as numerator 1, denominator 3 after arithmetic.

`ScalarJson(ref, json_pointer, unit, scale, context)` selects one scalar from accepted JSON. `CsvSelection(ref, columns, row_id_column, row_set, group_by, missing_policy, context, unit, scale)` selects accepted CSV values. Row sets are `AllRows`, sorted unique `RowIds`, or a closed `RowPredicate` (`eq/ne` string comparison; `lt/le/gt/ge` exact decimal comparison). There is no eval. CSV IDs must be globally unique and nonempty even outside the selected row set. Missing values either reject or exclude the entire selected row; excluded IDs remain observable in `ResolvedOperand`.

`resolve_operand` returns canonical row-ID order plus each row's full string `fields`, exact per-column `values`, and `group_key`. Rendering consumers use their explicitly declared series/order/pair fields instead of physical CSV order. Multi-column observations are supported; aggregations require one explicitly selected numeric column. `csv_selection_from_data_selector` maps the original selector's all-rows, column, row ID and missing policy without changing semantics. Selectors that omitted row identity keep their original evaluator and cannot acquire fabricated line IDs.

```python
request = DerivationRequest(
    expr=NumericExpression(op="mean", args=(selection,)),
    context=comparison_context,
)
result = evaluate_derivation(request, resolution_context)
```

The sealed `arw.numeric-expression.v1` vocabulary is `value`, `diff`, `ratio`, `pct_point_diff`, `relative_change`, `count`, `sum`, `mean`, `median`, `min`, and `max`; evaluator identity is `arw.rational.v1`. Binary operands are `(current, baseline)`: difference is current minus baseline, ratio is current divided by baseline, and relative change is their difference divided by baseline. Percentage-point difference requires normalized ratio/proportion values in [0, 1]. Relative change accepts same-context nonnegative quantities such as latency and throughput, requires a nonzero baseline, and returns a dimensionless ratio; negative inputs are out of domain. This corrects the unreleased v1 domain before its first merge. From 0.80 to 0.831, percentage-point difference is exactly 31/1000 and relative change is exactly 31/800.

Results distinguish `exact`, `undefined`, `context_mismatch`, `out_of_domain`, and `unsupported`. Single results use `exact`; grouped aggregates use `groups` with keys/row IDs; multiple observed values use `values`. Empty reductions and zero denominators are undefined. Missing accepted inputs and unsupported evaluator versions are unsupported. The expression model rejects operations outside the sealed vocabulary; SD/SE and other irrational calculations are outside v1.

`derivation_id(request)` hashes canonical expression, accepted reference/digest/selection, comparison context and evaluator version. `DerivationRef(kind="derivation_ref", derivation_id=...)` resolves through a supplied derivation mapping; every referenced request is re-evaluated against accepted input files. Stored `exact` and status fields do not become authority. A derivation record's ID must match its request. Evaluation is memoized with bounds of 128 derivation nodes, depth 32, 10,000 CSV rows, 32 numeric columns/arguments, and 320,000 resolved values.

`NumericPresentation(derivation_id, decimals, rounding_mode, unit_suffix, scale)` formats an exact result through `format_exact`. Presentation changes never enter derivation identity. Rounding modes are explicit (`ROUND_HALF_EVEN`, `ROUND_HALF_UP`, `ROUND_DOWN`). A scale of 100 displays 31/1000 as 3.1 percentage points and 31/800 as 3.88% at two decimals with half-even rounding. Point coordinates can continue using the exact rational regardless of rounded labels.

Legacy `arw.experiment-acceptance.v1` observed fields are display-only and cannot be consumed as scalar exact operands. Their bytes, old evaluator, schema and replay remain unchanged.

## Validation and dependency boundary

The four new checked-in schemas participate in `schema_registry` generation, drift detection and semantic validation (including rational reduction and derivation ID coherence). Tests use real parent acceptance and project journal bytes, including SourceLocator v2 extraction/PDF failures, fixed prefixes after torn tails, cross-run ambiguity, writer-lock reads, exact lexical JSON, repeated derivation DAGs and legacy golden replay.

The comparison context extraction avoids a state-to-evaluator dependency. The ledger adapter's necessary `ledger -> policy` edge delegates the original integrity validator lazily; the pinned dependency baseline records this one reviewed edge. Existing static cycles remain documented, and fresh interpreter tests cover both import orders.
