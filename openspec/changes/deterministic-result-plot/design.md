## Context
Issue #95 v3 consumes #94 AcceptedRef and RationalExact. The existing parent pipeline persists immutable IR/output/receipt bytes before recording four lifecycle events. Legacy schematic receipts are hash-bearing and must remain byte compatible.

## Goals / Non-Goals
Goals: accepted-source single-panel plots, exact-coordinate rendering, structured value bindings, explicit uncertainty, reproducibility and actual visual evidence.
Non-goals: statistical SD/SE recomputation, arbitrary code, TeX, facets, box plots, scientific claim certification or cross-host font equivalence.

## Decisions
Use an independent strict ResultPlotIR and additive ResultPlotReceipt. Observation sources are CsvSelection, aggregate and interval points carry shared DerivationRequest. The compiler resolves immutable source refs and asks numeric_core to evaluate each value; it never imports observed display text as exact. PlotValue captures identity, location, expression, scale, display and revision. Presentation is excluded from shared derivation IDs. Line segments partition by explicit series and order; pairing is checked before drawing. Stable ID hash jitter affects only a band display axis. Intervals accept lower/upper endpoints only and disclose imported statistical verification as unsupported.

Use the existing pipeline via a computed ResearchBinding provenance bridge for parent refs; retain the canonical AcceptedRef structures in the plot receipt. The existing EvidenceValidator performs visual evidence checks through a proxy with required exact IR/output digest binding. The plot policy separately checks numeric/source integrity, SVG output safety and caption structure. The closed SVG grammar has no scripts, external resources, images, style URLs or raw markup. Coordinates use Fraction until fixed decimal emission; log transforms use documented fixed Decimal arithmetic.

## Risks / Trade-offs
Host fonts can differ → receipt only promises source byte determinism; publication-critical qualification requires existing accepted visual evidence. Precomputed statistical estimates may be wrong → mark source integrity and statistical verification separately. Broad layer grammar can hide ambiguous ordering → reject missing/duplicate order or pair identities. Caption numbers without confirmed bindings → advisory/unknown, never claim verified.

## Migration Plan
Additive schemas and dispatch; existing research-artifact models and SvgRenderer are unchanged. Rollback can omit the new extension paths while legacy artifacts remain replayable.
