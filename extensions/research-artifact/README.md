# Research artifact compilation

The MVP compiles `methodology_figure` and `evidence_graph_view` IRs to deterministic
SVG source. It is not a paper AST, numerical plotting library or complete visual
quality assessor. The default renderer and validators require no model or graph
server. The source index reuses the local-store SQLite schema and is rebuilt in
memory from accepted artifact manifests; SQLite is never an authority.

`ArtifactIRBuilder.build`, `ArtifactRenderer.render` and
`ArtifactValidator.validate` are the replaceable ports. Receipt admission is an
internal parent journal delegate, not a provider port. Public capabilities are
`research.artifact.compile`, `research.artifact.inspect` and
`research.artifact.reproduce`. Missing extension imports return
`CapabilityUnavailable`.

Each node, edge and annotation binds an accepted artifact/event, source digest
and JSON pointer. A node must match the accepted kind/label and cannot increase
confidence. Edges preserve accepted endpoints/relation/label. Caption and
manuscript annotations preserve their accepted text, including numbers, units,
uncertainty and citations. This is a scoped exact-evidence check, not a general
natural-language entailment model.

IR presentation contains only declared style preferences. Pixel geometry is
computed by the SVG renderer. Renderer code bytes determine its identity digest;
SVG is UTF-8/LF with deterministic element order and integer geometry. Font names
are recorded; cross-host pixel-identical rasterization is not promised.

All five validation levels retain separate applicability and outcome. Exploratory
figures may skip visual review explicitly. Publication-critical figures require
semantic and visual PASS plus bound captions and manuscript references. The MVP
has no autonomous vision reviewer. It can consume an already accepted
`arw.visual-review.v1` artifact bound to the exact IR/output hashes, with reviewer
tool/version/identity. Such a review cannot replace source validation. Unavailable
required review yields FAIL; fixtures labeled simulated are not live reviews.

## CLI

```sh
arw artifact ir --run-root RUN --input specification.json
arw artifact render --run-root RUN --input frozen-ir.json
arw artifact qualify --run-root RUN --input frozen-ir.json --request command.json
arw artifact inspect FIGURE_ID --run-root RUN
arw artifact reproduce FIGURE_ID --run-root RUN
arw artifact doctor --run-root RUN
```

`command.json` is a normal parent `RuntimeCommandRequest`. A complete operation
records freeze/render/validate/accept, and optional supersede events. Repeating
its identity is idempotent; different content using an accepted ID is rejected.
Readers use accepted events, not directory presence. Missing post-freeze binding
is reported by doctor and can be repaired by an exact qualification retry.

## Retention

An accepted authorization artifact containing
`{"action":"purge_research_artifact","artifact_id":"..."}` plus the explicit
`--authorize-purge` flag authorizes the purge command. The accepted authorization
is bound into a tombstone before body removal. Original event and manifest hashes
remain intact, while body reads and reproduction return `BodyUnavailable`.
A purged body is never advertised as rebuildable. Retention does not purge source
research evidence or represent scientific approval.

```sh
arw artifact purge FIGURE_ID --run-root RUN \
  --authorization-artifact-id AUTHORIZATION_ID --authorize-purge
```
