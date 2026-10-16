## Context
The existing compositor and numeric engine are retained. #162 explicitly proposes staged delivery; this change implements milestone 1 and automatable semantic checks for its three public examples.

## Goals / Non-Goals
Goals: explicit sourced question/claim, typed ports, operation expansion, token mapping, state changes and conditional feedback; deterministic editable SVG and parent acceptance. Non-goals: auto-inferred scientific mechanisms, arbitrary graphics, layout search, draw.io, general tensor/attention visualization, independent human authorization.

## Decisions
Use a standalone MechanismFigureIR and accepted MechanismFacts document, rather than widening earlier v1 object schemas. Whole selected facts are bound through AcceptedRef/digest, with strict typed models and small bounded cardinalities. Source facts carry object identity/state, tokens/axes, operation steps, candidate states and relations. Caller supplies manual geometry with input/output ports and explicit edge waypoints; geometry is never scientific truth. A separately invoked checker compares the frozen answer document with visible SVG text, component/port sets and actual arrow endpoints. It does not compare to another generated image. Its results are structural checks, not pixel comprehension.

Reuse the parent append-only artifact commit path and exact-output visual review. Missing review blocks publication; exploratory acceptance does not establish visual quality. Optional system rasterization is measured and retained only as evidence. No external services or additional dependencies are introduced.

## Risks / Trade-offs
Complex methods exceed the small component budget → reject unsupported input. Text may fit geometrically yet be unclear → require actual pixels and independent review; report pending. Generic component names can conceal mechanism → require sourced expansion for the innovation and explicit typed port connections. A source document can itself be scientifically wrong → accepted source remains parent-owned; rendering validates consistency, not scientific correctness.


## Independent review amendment
The owner's 2026-10-16 comment requires a separate read-only figure-reviewer with actual pixels, frozen answers, reference/version comparisons and concrete findings. Two native Codex reviewer rounds were run without producer scores. Source revision 2 explicitly corrects synthetic counter facts while retaining v1 and its original output. Partial/new findings remain open after the fixed two-round budget. A historical control changed only a stop role prefix; it is classified as such, not as full stop-condition omission. The latter has a separate actual raster/structural supplement without independent third-round pixel review. No source or visual status is promoted by the advisory record.
