# Qualified research artifact pipeline

The two-kind MVP provides deterministic SVG compilation from a typed IR, accepted
source bindings, five independent validation levels, immutable qualification
receipts, parent-owned acceptance and supersession events, exact reproduction,
and authorized body tombstones. It adds no graph server, model or rasterization
dependency.

The complete contract and executable example are in
`extensions/research-artifact/README.md`, `CONTRACT-INVENTORY.md`, and
`examples/compile_workflow.py`. Run the example with a fresh output directory:

```sh
.venv/bin/python extensions/research-artifact/examples/compile_workflow.py build/artifact-example
```

The example is explicitly exploratory: source, semantic and render checks pass;
visual review is OPTIONAL_SKIPPED. A publication-critical figure requires a
separately accepted, exact-output-bound review and cannot use this example as
publication approval. The bilingual example was exported and visually inspected
locally; deterministic SVG reproduction passed. That observation is separate
from the example's recorded qualification policy.

## Acceptance evidence

- `tests/integration/test_research_artifacts.py`: both supported IR kinds;
  parent acceptance, CLI inspect/reproduce, deterministic source rendering,
  missing/malformed bindings, stronger confidence and causal wording, caption
  and manuscript/value drift, publication-required missing review, simulated
  review identity binding, renderer substitution, secret rejection, immutable
  supersession, concurrent retries, actual SIGKILL at three durability points,
  missing binding diagnosis/repair, and explicit tombstone retention.
- `tests/compat/test_research_artifact_events.py`: byte-stable old/new event
  replay including supersession, reader migration, and generated schema drift.
- `tests/compat/test_kernel_dependency_direction.py`: no renderer dependency in
  the kernel; existing subpackage dependency ratchet remains unchanged.
- Unit + artifact + local-store knowledge regression: 629 passed.
- Frozen-environment compatibility + artifact regression: 90 passed after the
  final renderer table pin; the external-table fixture and final lifecycle guard
  passed in the final focused rerun: 35 tests passed.

## Reader migration

Migration 0001 registers new artifact event families at envelope version 1.1.0.
Version 1.0.0 events retain their exact bytes and hashes. The reader registry is
core code and remains available when the optional renderer extension is disabled.
There is no historical JSON journal rewrite. The existing numbered SQLite
migration helper is reused only for the disposable source projection, not to
mutate canonical history.

## Result-plot numeric labels and grouped bars

SVG coordinates retain the fixed six-decimal layout format. Numeric tick labels use independent significant figures and scientific notation; near-neighbour ranges use an explicitly stated common axis offset when full labels would wrap. Nonzero small domains remain visibly nonzero, and tick labels remain distinct and deterministic.

Multi-series grouped bars require a band x axis. A continuous x axis with multiple bar series reports `continuous_grouped_bar_unsupported` during compilation. Single-series continuous bars and band-axis grouped bars remain supported.

## Concurrent qualification

Research-artifact qualification waits up to five seconds for the canonical writer lock before preparing, rendering or committing. This operation-specific wait covers concurrent identical requests whose predecessor is still rendering or publishing. Once admitted, the ordinary immutable command identity and revision checks apply: identical retries return the accepted record; distinct stale requests fail. A timeout returns the existing canonical-writer-lock error without preparing or committing the waiting request. Internal callers may select a finite wait between zero and thirty seconds. General journal operations retain their existing timeout; no automatic retry or second writer is introduced.

## Optional PGFPlots source export

```bash
arw artifact export-pgfplots --run-root RUN --input input/result-plot.json
```

This explicit operation uses the same original `compile_plot` result as SVG.
Its immutable candidate contains `figure.tex` and `export.json`, with original
`plot_value_id` values, exact rational coordinates, source/IR digests and a
versioned exporter identity. Coordinates come from the compiled exact values,
never rounded display strings or a separate statistical calculation. Category,
series and stable-row jitter positions are layout only. Point, line, bar,
strip and interval layers are exported. All user titles, captions, units,
categories and series labels are escaped as plain TeX text; no arbitrary PGF
keys, macros or external input files are accepted.

No package is installed and no TeX executable runs. Source export is byte
deterministic; fixed-environment rendering and publication quality remain
`not_verified`. It does not modify the SVG receipt, accepted ledger or qualify
result. Caller-side compilation requires an existing `pgfplots` package
(`\usepackage{pgfplots}` / `\pgfplotsset{compat=1.18}`), an appropriate engine
and fonts, followed by independent qualification. That optional environment
qualification is not implemented by this source-only exporter. Large exact
fractions and CJK text may exceed a chosen TeX environment's capabilities;
source correctness does not establish successful visual rendering.

Version observations checked 2026-10-12: [CTAN's package catalogue](https://ctan.org/pkg/pgfplots/?lang=en)
reports **1.18.3**. The separate, unofficial [tikz.dev HTML manual](https://tikz.dev/pgfplots/reference)
labels itself **1.18.2**. These are distinct sources, not an exact package or
engine compatibility requirement. No TeX packages, fonts or manual bodies are
redistributed.

Finite decimal coordinates are emitted as exact decimal literals to avoid
PGF math division rounding; nonterminating fractions retain numerator/denominator
expressions. Actual TeX arithmetic and coordinate rendering have finite,
engine-dependent precision; source value identity is not an exact rendered
coordinate guarantee. CJK labels require a Unicode-capable engine and suitable
fonts/packages, such as XeLaTeX with xeCJK or ctex. ARW does not install or
qualify these caller-side prerequisites.

PGFPlots emits one legend entry per named series across all layers. Unnamed plots, additional interval segments and repeated series use forget plot, preserving legend/style correspondence.

## Bounded scientific composition (FigureComposition v1)

Issue #152 adds an independent `arw.figure-composition-ir.v1` and
`arw.figure-composition-receipt.v1`. The existing artifact `ir`, `render`,
`qualify`, `inspect` and `reproduce` commands dispatch on
`artifact_kind: figure_composition`. Supply the specification to `artifact ir`
to obtain the current compositor identity before freezing the IR. Admission uses
the existing parent request and four-stage canonical artifact protocol.

A composition declares 2–4 panels, physical width/height in mm, a single visual
argument, reading order, and a row/column/grid layout with ratios, explicit cells,
bounded spans and start/center/end alignment. Axes remain independent. Sources
are same-run `ResearchBinding`s resolved through the existing AcceptedRef adapter
and optional historical-prefix context; cross-run child composition is explicitly
unsupported. Each panel pins its selected canonical content SHA-256 and renderer.
Claims also use canonical bindings. Repeated object IDs convey identity only;
they do not establish a transformation between different state IDs.

Source JSON can contain a bounded sequence (ordered, identified segments with
explicit local highlights) or entity graph (typed/identified states, labelled
control/data/support relations with explicit direction, one optional local group).
The shared encoding table maps object IDs to color, shape and line style; legends
use that same table. Graph relation styles encode relation type explicitly. The
compositor does not infer causal edges or compute data.

An `accepted_v1` panel selects the complete accepted receipt of a v1 schematic or
result plot. The compiler verifies receipt/event/output hashes, binding and pinned
backend identity, copies the controlled SVG subtree, namespaces IDs/markers/clips,
and only translates and uniformly scales it. No child crop, recoloring, numerical
recomputation or uploaded SVG import is allowed. A conflicting result-series
encoding requires a new separately validated/accepted child candidate; automatic
creation of such a candidate is unsupported. Existing child legends and axes stay
unchanged. A shared composition legend can reference an existing result series
only when its declared encoding matches the accepted child's existing encoding.

The receipt reports each child's actual minimum font size in composed points and
scale. Text stays editable. This measurement does not prove glyph coverage,
clipping freedom or final-size readability; glyph coverage remains `not_verified`.
A small font is a visible review finding, not an automatic visual PASS. Target
sizes, layout, sources, encodings and child identities are part of the composition
IR digest; output-bound visual evidence expires when any of them changes.
Publication-critical compositions require an independently accepted
`arw.visual-review.v1` binding the composition's own IR and SVG hashes. The
compositor never creates that review. #153 supplies actual rasterized benchmarks
and the independent human-review packet. Tests in
`tests/integration/test_figure_composition.py` exercise real accepted numeric
children, two layouts, original v1 reproduction, malformed sources and safe SVG.

## Bounded mechanism figure (issue #162, first milestone)

`artifact_kind: mechanism_figure` dispatches through the existing artifact
`ir/render/qualify/inspect/reproduce` commands. Its independent
`arw.mechanism-figure-ir.v1` binds an accepted `arw.mechanism-facts.v1` selected
value, its SHA-256 and renderer identity. Same-run AcceptedRef resolution,
historical prefixes, source bytes and the parent writer lock remain authoritative.
The compiler requires the declared component/route inventories, compatible typed
ports, preserved object/state identity, explicit sourced operations, a connected
object chain and a conditional feedback/exit contract. Its renderer copies source
literals and never fills in a missing scientific mechanism.

Four small component families use explicit manual point geometry: token and
representation correspondence, port operations with ordered local expansion,
conditional continue/stop, and before/after candidate states. SVG remains inert
and editable, with fixed fonts, physical units and a bounded output. Text that
does not fit fails instead of being silently shrunk. This is a consistency and
mechanism-expression foundation, not automatic scientific validation or layout
search. Quantitative computation remains in the existing numeric/plot pipeline.

`arw.mechanism-advisory-review.v1` records a separate figure-reviewer role,
actual-pixel reading, source/IR/SVG/PNG/font/environment bindings, specific findings,
reader retelling and measured review resources. A model advisory record cannot
assert human acceptance or publication visual PASS. It is intentionally a
separate schema from `arw.visual-review.v1`; passing its identity as the latter
review fails qualification. The existing parent acceptance protocol remains the
only writer of canonical qualification evidence.

See [the runnable public packet](../../examples/mechanism-figures/README.md) for
three actual source-bound examples, retained first/second-round pixels and
independent review. Missing pixels or human acceptance, unresolved findings and
unsupported draw.io/three-strategy capabilities remain explicit. Source, geometry,
font or environment changes expire the relevant advisory binding; environment
binding covers the recorded rasterizer inventory, not an attestation of the
entire host. No additional model/provider/version is a release requirement.
