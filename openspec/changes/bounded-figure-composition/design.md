## Context
Issue #152 composes paper evidence without relaxing the two v1 IR schemas or changing their pinned renderers. Canonical journal and retained files remain authoritative.

## Goals / Non-Goals
**Goals:** 2–4 independently sourced panels, explicit bounded layout, stable shared object encoding, safe SVG and the existing four-stage parent admission protocol.
**Non-Goals:** arbitrary SVG import, scientific recomputation, custom recoloring of accepted children, shared axes, image generation, global layout optimization or automatic visual acceptance.

## Decisions
- Separate strict core contracts and additive schemas. Source documents describe sequence segments or typed entity graphs; a ResearchBinding selects the exact accepted JSON object. Whole source, selected digest, event digest and historical prefix all remain checked through the existing AcceptedRef adapter.
- Keep existing v1 children immutable: resolve their accepted receipt, inspect all retained output digests and pin identities. Only translate/uniform-scale a controlled parsed SVG subtree. Incompatible shared encoding requires a newly validated child candidate; composition refuses it.
- New object SVG uses an explicit encoding table keyed by identity, never panel ordering. Relations have labels and typed source content. A repeated object ID does not create a transformation edge.
- Explicit row/column/grid cell placement with ratios and bounded spans. Independent axes only. Layout does not crop children. Font-size report measures composed point sizes, with host-dependent glyph coverage and legibility remaining visual-review obligations.
- Reuse commit_artifact_pipeline with a new receipt model, immutable candidate/accepted paths and exact composition visual reviews. Existing event envelopes carry the additive artifact kind without schema mutation. Read-only rendering cannot admit evidence.

## Risks / Trade-offs
- Small panels shrink text → report actual minimum point size; never infer visual PASS.
- Host fonts differ → record requested family; #153 records actual rasterizer/fonts and pixel review.
- Accepted child may be unsafe or historically unavailable → reject unsafe grammar, digest mismatch or unsupported renderer, without rewriting it.
- New schemas add package inventory → validate schema drift, compatibility, CLI and supply-chain tests; v1 model projections stay unchanged.
