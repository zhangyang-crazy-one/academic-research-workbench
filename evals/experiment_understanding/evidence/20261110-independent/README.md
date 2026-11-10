# 2026-11-10 independent-scoring pilot evidence

This historical trial used commit `65bd0b1`. Later parser-hardening changes
intentionally change the frozen protocol identity; a new execution must create
a fresh freeze, not reuse this historical anchor. Scoring receipt replay remains
available because the underlying numeric scorer is unchanged.

The actual three-task CLI trial is retained under `run/`, including frozen
method/public inputs, all raw stdout/stderr, executions, attempts, scorer
controls, numeric receipt and report. The external freeze anchor is
`804821214dc98726b92b133ed73fa8616dc101e99abc8109d5f97d233e6bfbe3`.

Outcome: **incomplete, 0/3 delivered**, not an isolated-candidate success.
All three bubblewrap launches failed before candidate execution:

```
bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted
```

The same minimal namespace probe failed in the normal command context and an
approved elevated command context. No weaker fallback was attempted. Each
failed launch remains in the denominator with its measured elapsed time;
tokens and USD are unavailable. Oracle, zero-table and missing-output scorer
controls passed; the numeric receipt replays against the retained attempts.

Focused validation: 31 passed, 1 skipped across
`tests/evals/test_independent_cpu_pilot.py` and
`tests/unit/test_experiment_understanding.py`. The skipped test is explicitly
the real namespace answer/cwd/log/resume/environment/network boundary test.
Mocked tests establish protocol behavior, not actual namespace enforcement.
Ruff check and formatting passed for the added Python files. These focused
checks are not a full repository regression pass.

To reproduce scoring independently of the failed execution boundary:

```bash
scripts/arw-experiment-eval verify \
  --attempts evals/experiment_understanding/evidence/20261110-independent/run/attempts.json \
  --receipt evals/experiment_understanding/evidence/20261110-independent/run/receipt.json
```
