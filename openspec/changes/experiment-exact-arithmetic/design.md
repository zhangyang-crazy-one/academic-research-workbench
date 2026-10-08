## Context

Evaluator 1.0.0 uses a 50-digit Decimal context and fixed-point output. Its receipt bytes are immutable and must still replay under that algorithm.

## Goals / Non-Goals

**Goals:** Exact pass/fail arithmetic, bounded conversion and output, typed failures, and version-specific offline replay.

**Non-Goals:** Changing provenance's numeric representation, adding operators, or reinterpreting old receipts.

## Decisions

- Preserve 1.0.0 helpers and dispatch replay by recorded evaluator version. New evaluations use 1.1.0; the result schema accepts both versions.
- Parse decimal tokens only after checking token length, coefficient digit count, and exponent text/value. 1.1.0 accepts at most 64 coefficient digits, a 128-character token, and exponent magnitude at most 1000. Out-of-domain artifact and reported values block as `invalid_artifact`; contract numeric limits block as `invalid_contract`.
- A nonzero input has adjusted exponent from -1064 through 1063. With 200,000 CSV rows, sum/mean magnitude is below 1e1070; relative improvements and tolerance products stay below 1e2129. Display's decimal exponent range of ±10000 is therefore wider than any accepted intermediate result.
- Convert accepted decimals to `Fraction` for all 1.1.0 operators and comparisons. This makes cancellation and inclusive boundaries independent of row order and decimal context. At most 200,000 rows and 8 MiB of CSV are already allowed; bounded exponents keep each fraction finite in size.
- Round display to at most 56 significant digits with half-even ties, using fixed notation where it fits 64 characters and scientific notation otherwise. Display rounding never decides pass/fail.

## Risks / Trade-offs

- [A displayed repeating mean can be rounded] → Comparison uses the exact fraction, and documentation calls the field a bounded display.
- [Old receipts encode the prior arithmetic] → Replay selects their stored evaluator version and retains their canonical bytes.

## Migration Plan

New evaluations issue 1.1.0 receipts. Existing 1.0.0 receipts stay loadable, publishable, and replayable without migration.
