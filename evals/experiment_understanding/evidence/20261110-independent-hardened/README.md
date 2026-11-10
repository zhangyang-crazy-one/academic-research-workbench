# Final hardened-source trial, 2026-11-10

This fresh actual CLI trial ran final implementation commit
`213f29ab7211ee9c762bdbef475d7102b7c89a6a`, including hostile-output validation,
Python `-I -S`, and runtime-mount protected-path preflight. It did not reuse the
older trial's freeze or run directory. No permission changes or elevated retry
were attempted for this trial.

- Protocol source `independent.py` SHA-256:
  `b781fb3a107251f571ed5c2e0f6b12c8f8d23674ef89131f4692de284ca798c5`
- Fresh freeze SHA-256:
  `80fe35f1b94a30d71684d0f841f99eb29e7858945011bd9c1827df9e14d74a7b`
- Method: `examples/public_mean.py`, retained verbatim as `run/method.py`.
- Outcome: **incomplete, 0/3 delivered, CLI exit 1**. Every candidate launch
  failed before execution with:

```
bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted
```

The three failures and measured wrapper elapsed times are retained in
`run/executions.json` and `run/attempts.json`; raw logs and exact public inputs
are retained separately. Missing tokens and USD remain unavailable. There was
no cooperative fallback. **Actual enforced isolation remains blocked on this
host, not validated.**

Mandatory oracle, zero-table and missing-output scorer controls passed. Existing
numeric receipt replay passed against the retained attempt bytes. The current
source/freeze/method binding and report bindings for logs, controls, attempts and
receipt were separately verified. The frozen source identity matches the final
implementation above; adding this evidence does not change that source.

Focused tests for the final implementation: **44 passed, 1 skipped** across
`tests/evals/test_independent_cpu_pilot.py` and
`tests/unit/test_experiment_understanding.py`. The skip is the actual namespace
answer/cwd/log/resume/environment/network boundary test, with the failure above.
Ruff check and formatting passed. This is not a full repository regression run.

Reproduce numeric replay without claiming candidate execution succeeded:

```bash
scripts/arw-experiment-eval verify \
  --attempts evals/experiment_understanding/evidence/20261110-independent-hardened/run/attempts.json \
  --receipt evals/experiment_understanding/evidence/20261110-independent-hardened/run/receipt.json
```
