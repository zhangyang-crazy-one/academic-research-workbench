## Why

The experiment acceptance evaluator can round away a small term between large canceling terms and pass a false zero-tolerance claim. Short scientific notation can also overflow its fixed-point result field or raise an uncaught decimal exception.

## What Changes

- Evaluate numeric checks using exact rational arithmetic in evaluator 1.1.0, including comparisons and tolerance boundaries.
- Bound input coefficients and exponents before costly conversion; return typed blocking results outside the supported domain.
- Serialize observations in bounded decimal/scientific notation and preserve the old 1.0.0 algorithm for offline replay of old receipts.
- Verify cancellation, ordering, scientific notation, comparison boundaries, result digest, and replay.

## Capabilities

### New Capabilities

- `experiment-exact-arithmetic`: Bounded exact numeric acceptance and version-specific replay.

### Modified Capabilities

None.

## Impact

The experiment acceptance evaluator, result schema, focused tests, and runtime documentation change. No new dependency or execution capability is added.
