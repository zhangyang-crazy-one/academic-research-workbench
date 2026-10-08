# Single-panel result plots

`ResultPlotIR` (`arw.result-plot-ir.v1`) is independent of the schematic
`ResearchArtifactIR`. Its additive receipt is `arw.result-plot-receipt.v1`.
Existing schematic models, schema bytes and `SvgRenderer` are unchanged.

The grammar supports observation `point`, `line`, `strip`; aggregate `point`,
`line`, `bar`; and interval `rule`. All layers share one panel and scales.
The y scale is linear or log; x is linear, log or band. Facets, box marks,
TeX/PGFPlots, arbitrary plotting code and SD/SE recomputation are unsupported.
Log bars have no defined zero baseline and are rejected. Explicit domains
must contain all exact values; clipping cannot silently hide data.

Observation sources are accepted `CsvSelection` objects with globally unique
stable row IDs, an explicit missing policy and `ComparisonContext`. The core
retains full row fields for series/order/pair metadata. Continuous x/y axes can
use a separate typed `x_source` selection (for example elapsed seconds versus
accuracy ratio). Both selections must have identical row identity, row-set,
grouping and missing-policy contracts and exactly the same selected row IDs
and groups. Dataset, split and evaluation condition must match; axis metric
and unit can differ. Missing, duplicate or mismatched rows fail rather than
silently joining a subset. Band axes do not accept numeric x selections.
Lines require series
and order and are connected within each series, and within each pair when
paired. Pair completeness is checked by actual exact x/category positions,
while connections still use the explicit order; a paired line cannot span
multiple series. Missing pair IDs, repeated pair positions, missing pair members and
excluded paired numeric rows fail explicitly. Strip jitter is a hash of the
stable row ID, confined to the x band display axis; y remains exact.

Each aggregate/interval datum carries shared `DerivationRequest` objects.
A multi-group or multi-value request is not an implicit scalar: choose the
specific row set/group before plotting. The compiler re-evaluates accepted
sources through `numeric_core`; no legacy `observed` display string is used
as an exact number. Every emitted `PlotValue` records `plot_value_id`,
`derivation_id`, exact rational, layer, series, category, channel, statistic,
expression, unit, display scale/rounding and IR revision. Coordinate arithmetic
uses normalized exact values. Operand normalization scales remain in the
expression; presentation `scale` and suffix never change derivation identity
or coordinates. Log layout uses fixed 400-digit Decimal transforms; emitted
layout coordinates are rounded to six decimal places only after calculation.

Intervals require lower/upper endpoint derivations, sampling unit, accepted
effective-n derivation, missing policy, method, assumptions and accepted
calculation source. CI requires confidence level; SD requires ddof. Inverted
endpoints fail. `precomputed_interval_source_resolved` records source integrity;
`precomputed_statistics_not_recomputed` remains `unsupported`. It never becomes
statistical PASS merely because the source hash matches.

The `arw.plot-heuristics.v1` profile records a configurable small-sample
threshold (default 20). Summary-only continuous independent data with available
raw observations yields advisory. Counts are exempt. `raw_unavailable` is
explicit, and cannot coexist with invented observation layers.

Caption numeric bindings use UTF-8 byte occurrence spans. Result bindings name
one plot value and its series/category, statistic/expression, unit/scale and
revision. Sample size, confidence level and figure number use separately typed
metadata slots. A binding must cover an entire numeric occurrence, so selecting
the final `3` of `13` cannot satisfy a figure-number or sample-size check. Metadata scaling can express a confidence level as percent.
Unbound text is unknown. Mismatched declared bindings are advisory, including
A/B swaps and swapped same-rounded values. The `confirmation` field is a
statement, never authorization.

`caption_checks(..., hard_caption_checks=True, attestation_verifier=...)`
accepts the `CaptionAttestationVerifier` protocol. Its adapter must prove the
journal confirmation plus parent-ledger anchor against the fixed N-1 prefix,
time, role, gate, scope, exact IR hash and revision, and return a
`VerifiedCaptionAttestation`. Without that adapter, hard checks fail closed
with `caption_auth_missing`/unsupported. The hard path is explicitly opted in;
this module does not invent or sign authority evidence.

## Service API and Figure contract

`ResearchArtifactService.build` dispatches result specifications and adds the
actual renderer pin if omitted. `render` publishes candidate IR/SVG bytes.
`capture_result_plot(ir, run_root=..., resolution_context=...)` is read-only and
returns `(ResultPlotReceipt, ir_bytes, svg_bytes)`. A receipt PASS describes the
checks; it is not parent acceptance. A supplied `ResolutionContext` can include
multiple runs, preserving fully scoped identities even for same-name artifacts.
`qualify` uses the original parent-only immutable lifecycle for same-run inputs.
Cross-run or journal-backed parent qualification requires an explicitly
accepted source bridge; without it, `plot_source_bridge_required` fails closed.
The bridge preserves the original lifecycle source-event rule and never replaces
original source resolution. `inspect` and `reproduce(..., resolution_context=...)` handle accepted
result plots, and source tampering prevents reproduction.

`source_bridge(ir, run_root=..., resolution_context=...)` returns a read-only
`arw.plot-source-bridge.v1` proposal. Save the proposed JSON under the target run,
then explicitly accept it with the existing parent `accept-artifact` command,
kind `plot-source-bridge` and media type `application/json`. Add its whole-object
`ResearchBinding` (artifact, accepted event and content digests) to the IR's
single `acceptance_bindings` slot. The capsule binds the complete canonically
sorted source ref objects and their digest to the figure identity/revision.
Compiler, qualification and reproduction verify the capsule's real target-run
acceptance and every original accepted source. Unaccepted/wrong-kind capsules,
wrong revisions, missing refs, digest changes and source tampering fail. The
bridge event must be inside any supplied historical target prefix.

`caption_targets(ir, run_root=..., resolution_context=...)` returns read-only
binding IDs, target hashes and `caption:<sha256>` authority scopes. These are
proposals, not signatures. The target freezes complete caption bytes, numeric
occurrence, binding context, accepted derivation/exact value and source refs,
excluding its own confirmation refs/declaration and bridge to avoid a digest
self-reference. The trusted authority adapter verifies the semantic target and
returns the current complete IR hash as a response integrity check.

`verify_plot_receipt(run_root, events, artifact_id, resolution_context=...)`
replays the supplied event prefix through the original on-disk hash-chain
validator, independently of later tails, then verifies acceptance, retained receipt/output and
post-freeze binding hashes, source references, every exact plot value, metadata,
`rendered_from` and reproduced SVG bytes. It returns the typed receipt. It
proves integrity only; no Figure-to-claim support relationship is inferred.

Parent manifests retain kind `research-artifact`. Their content is the plot
receipt; its own `artifact_kind` is `result_plot`. Figure adapters inspect the
receipt discriminator, `/plot_values/<index>` and `/rendered_from`. The latter
holds the fully scoped accepted source refs, IR hash and renderer identity.
Prose own-result references must use the same shared derivation IDs.

## Determinism, safety and actual review

SVG uses only inert XML text and closed geometry, a fixed Okabe–Ito palette or
monochrome, no images/scripts/event handlers/hrefs/style URLs/imports. XML and
TeX metacharacters in labels remain text. The source IR budget is 1 MiB, each
observation layer is at most 1000 rows, total plot values at most 5000, series
at most eight, and SVG at most 2 MiB. Safety/integrity errors fail; advisory
heuristics do not impose a universal statistical rule.

The receipt promises SVG byte determinism under the pinned renderer. It records
fixed-environment rendering as `not_verified`; identical source bytes do not
prove cross-host font equivalence, correct glyphs, overlap-free labels, final
size or publication quality. Publication-critical figures require caption,
manuscript reference and accepted `arw.visual-review.v1` evidence bound to exact
IR/output hashes. The original `EvidenceValidator` verifies that evidence and
reviewer identity; this module never fabricates visual review. Tests can use
explicitly simulated evidence fixtures but those are not production reviews.
