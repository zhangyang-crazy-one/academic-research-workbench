# Experiment claim acceptance

Tracking: issue #57. This is an offline MVP that checks whether stored
experiment outputs support a numeric claim, as defined by one versioned
contract. It builds on the external-only experiment provenance
(`arw.experiment-provenance.v1`) and the claim identities in the
claim–evidence links.

## What it does

`src/arw/kernel/artifacts/experiment_acceptance.py` evaluates an
`ExperimentContract` (`arw.experiment-contract.v1`) against sealed
`ExperimentProvenance` and the raw CSV outputs that provenance names. The
result is an `ExperimentAcceptanceResult` (`arw.experiment-acceptance.v1`).

Supported checks:

| Kind | Meaning |
| --- | --- |
| `numeric_reproduction` | Recompute one whitelisted operator (`mean@1`, `sum@1`, `min@1`, `max@1`, `median@1`, `count@1`) over one CSV column and compare it with the reported metric. The pass condition is `abs(computed - reported) <= absolute + relative * abs(reported)`, and both boundaries are inclusive. |
| `baseline_comparison` | Compare two reported metrics whose metric definition, unit, dataset, split and evaluation condition are all identical. The direction is `higher_is_better` or `lower_is_better`. The threshold is absolute or relative to the absolute value of the baseline, and it is inclusive. |
| `statistical_significance`, `conditional_effect`, `interaction_effect`, `causal_effect`, `leaderboard_rank` | Always `unsupported`. These never become a weaker pass. |

Evaluator `1.1.0` reads reported floats from their shortest round-trip text and
uses exact rational arithmetic for operators, ranges, tolerances, thresholds,
and budget comparisons. A zero-tolerance check therefore retains small terms
between large canceling values. `observed` and `expected` are deterministic
display fields: up to 56 significant digits with half-even rounding, using scientific notation when
fixed notation would exceed the 64-character result limit. A repeating
fraction or a longer result can be rounded for display; the pass/fail decision
always uses the full exact value.

The supported `1.1.0` numeric input domain is at most 128 characters and 64
coefficient digits per value, with a written base-10 exponent from `-1000` to
`1000` (at most four exponent digits). This applies to CSV cells, reported
metrics, and contract limits. Values outside the domain block with
`value_out_of_supported_range`: `invalid_artifact` for CSV or reported values,
`invalid_contract` for contract check values. An out-of-domain budget usage
metric is `unverifiable`; an out-of-domain budget limit is `invalid_contract`.
Data remains subject to the existing
8 MiB and 200,000-row bounds. No numeric expansion occurs before the exponent
and coefficient bounds are checked.

For a nonzero accepted token, these bounds put its adjusted decimal exponent
between `-1064` and `1063`: up to 64 coefficient digits combined with a
written exponent of magnitude 1000. A sum of at most 200,000 rows has magnitude
below `1e1070`; a baseline relative improvement and a tolerance product have
magnitude below `1e2129`. The rational numerator and denominator therefore
stay finite under the same input and row limits. Conversion for display uses a
decimal context with exponent range `-10000` to `10000`; it chooses scientific
notation directly when the adjusted exponent makes fixed notation long.

## Statuses

Each check has exactly one status:

- `passed`: the contract is satisfied.
- `failed`: the evidence is complete and valid, but the threshold or
  tolerance is not met.
- `evidence_missing`: there is no raw output, no file supplied, or no
  reported metric. A missing output is not an experiment failure.
- `invalid_contract`: the contract cannot be evaluated as written. Causes
  include an unknown artifact, a unit mismatch (units are never converted),
  incomparable contexts, or a relative threshold against a zero baseline.
- `invalid_artifact`: the output data is unusable. Causes include a digest
  mismatch, an unsafe or symlinked path, a value that is NaN, ±Infinity,
  non-numeric, missing (when `missing_values` is `reject`) or out of range,
  duplicate or missing sample IDs, malformed CSV, an oversized file, or no
  samples.
- `unsupported`: the claim type is outside the MVP.

`overall_status` is `passed` only when every check passes. Otherwise it is
the most severe status present, in this order: `invalid_contract`,
`invalid_artifact`, `evidence_missing`, `failed`, `unsupported`.

`budget_status` is reported separately and never changes an effect check:

- `not_declared`: the contract declares no budget.
- `within_budget` or `exceeded`: the budget was checked against the
  provenance usage metric.
- `unverifiable`: the provenance has no usage metric.
- `invalid_contract`: the usage metric's unit conflicts with the contract.

## Pre-declaration and versions

Contracts are immutable. A changed threshold, tolerance or analysis needs a
new `contract_version` that names the contract it supersedes through
`supersedes_contract_sha256`. Results are content-addressed and contain no
timestamps, so an earlier failed result still replays byte-for-byte.
New results record evaluator `1.1.0`. Offline replay dispatches by the stored
`evaluator_version`; existing `1.0.0` receipts retain their original decimal
arithmetic, output bytes, and digest.

A contract's `declared_timing: predeclared` is only a claim. The result
reports it as:

- `verified_predeclared` when parent-ledger `TimingEvidence` shows the
  contract was accepted before the provenance.
- `predeclaration_contradicted` when the ledger shows the opposite order.
- `predeclaration_unverified` when there is no ledger order. This is always
  the case from the CLI today.

Self-reported runner timestamps are never used.

## Boundaries

- The evaluator never executes the artifacts, scripts or expressions it reads,
  never starts a process or opens a network connection, and needs no model,
  credentials or host qualification.
- It reads only regular files under the run root that provenance names and
  whose SHA-256 digests match.
- A result's `scope` is always `contract_conformance_only`. A pass does not
  establish statistical significance, scientific validity or causality, does
  not unlock the `experiment_reproduced` claim capability (which stays
  BLOCKED), and must not be used to promote a heuristic automatically.

## CLI

```bash
arw experiment accept --run-root RUN --contract contract.json \
  --provenance-sha256 SHA [--publish]
arw experiment replay --run-root RUN --result-sha256 SHA
```

`--publish` writes the contract and the result write-once to
`experiment/contracts/sha256/` and `experiment/acceptance/sha256/`.
`replay` re-evaluates a published result and fails with `replay_mismatch`
if any byte differs.

## Follow-up

Verified pre-declaration needs a parent-ledger event that accepts a contract
digest, so that `TimingEvidence` can be read from the journal rather than
supplied by a caller. Paired per-sample comparisons, JSON Lines inputs and
further operators are also outside this MVP.
