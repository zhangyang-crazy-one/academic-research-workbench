## Context

Existing seven reference types prove different scopes. Existing experiment checks use Fraction internally but store rounded observed text. Both remain unchanged.

## Goals / Non-Goals

Goals: strict accepted-event identity; bounded reads; truthful proof scope; independently usable rational derivations.
Non-goals: statistical roots/SD/SE, authority writes, legacy migrations, figure rendering.

## Decisions

State models use strict frozen discriminated unions. ResolutionContext supplies explicit roots and optional fixed-prefix hashes; original ledger and journal validators remain authoritative. SourceLocator delegates its full original validator, evidence spans delegate the research integrity chain, and capsules prove only retained structural bytes. Every adapter preserves the original object. Ambiguous runs never choose an arbitrary match.
Numeric requests have a sealed v1 operation vocabulary. Exact decimals become reduced Fraction values with bounded numerator/denominator and row/argument budgets. CSV row IDs are globally unique and selection/group keys are explicit and stable. Context equality is required before comparisons. Derivation identity hashes expression, accepted references, context and evaluator version, excluding presentation. Derived references are re-evaluated against accepted inputs.

## Risks / Trade-offs

- Later damaged tails could invalidate historical reads: consume the coordinated original prefix replay helper when fixed prefixes are supplied, rather than copying validators.
- Capsule provenance cannot reverify a missing PDF: report structural_capsule only.
- Legacy observed text loses exact precision: never consume receipts as exact operands.

## Migration Plan

Additive modules and schemas; existing receipts/events remain byte-identical.
