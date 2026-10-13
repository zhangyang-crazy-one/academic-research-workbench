# Public CPU experiment pilots (#119)

Three real standard-library CPU executions validate the contract workflow:

| Experiment | Public analytic input | Acceptance |
|---|---|---|
| Composite trapezoid integration of x² on [0,1] | n = 8, 16, 32; target 1/3 | v1 absolute tolerance 0 fails; relaxed v2 tolerance 0.002 passes |
| Central finite differences for sin at zero | h = 0.1, 0.05, 0.025; target 1 | v1 absolute tolerance 0.001 passes |
| Monte Carlo unit-circle area estimate of pi | seeds 7, 11, 19; 20,000 samples each; target Python double pi | v1 absolute tolerance 0.04 passes |

The code and analytically generated inputs are provided here for inspection and
redistribution under CC BY-NC 4.0, consistent with the repository research
adapter license. No third-party dataset, GPU, model or API is required. These
are numerical mini-experiments, not empirical publication benchmarks or an
accuracy estimate for arbitrary research.

Run from a source checkout with the declared Python dependencies installed:

```bash
.venv/bin/python scripts/run-public-cpu-pilots --output build/my-cpu-pilot-evidence
```

The destination must not exist. The orchestrator invokes the actual
`arw experiment freeze`, `accept --publish` and `replay` CLI entry point in
separate processes. Initialization and provenance intake use the original typed
parent service. Execution is a separate inspected worker process, explicitly
authorized by the owner's #119 development request. The offline evaluator does
not start or authorize that process. No production arbitrary-execution policy
is relaxed; `controlled_execution_qualified` remains false.

## Retained observations

[evidence/report.json](evidence/report.json) records all three runs and four
receipts. Each run retains its configuration and worker source, actual raw CSV,
worker stdout/stderr, execution timestamps/costs, source manifests, canonical
parent journal, versioned contract, provenance intake, CLI requests and outputs,
and immutable acceptance results. [inventory.json](evidence/inventory.json)
binds the retained files to SHA-256.

The trapezoid v1 failure remains byte-identical and cold-replayable after the
post-result v2 freeze. Initial v1s report `verified_predeclared`; v2 reports
`predeclaration_contradicted`. This proves **only that the contract preceded
provenance acceptance in the parent journal**. It does not prove pre-data-
collection timing, prior access to results, statistical validity or causality.

Wall time and process CPU time are measured for each worker's numerical loop;
they exclude CLI/parent overhead. Process count and architecture are retained.
Monetary, energy and peak-memory cost are `unknown`, with no fabricated zero.
Model calls are explicitly zero because the inspected workflow contains none.
Cold replay and changed-raw-data refusal are covered by
`tests/integration/test_public_cpu_pilots.py`.

## Interpretation of the trapezoid failure

The v1 failure is the finite-step trapezoidal approximation error for x², not
merely floating-point roundoff. At n=8,16,32 the exact discretization errors
are 1/(6n²); their mean is 7/6144 (approximately 0.00113932291667). A zero
tolerance rejects this error; the recorded v2 tolerance 0.002 accepts it.
The JSON target is a Python floating approximation to 1/3, which adds only a
much smaller representation difference. Retained report/receipt bytes are
unchanged. These three analytic mini-experiments exercise mean@1 only and
prove workflow integrity; they do not cover grouped row IDs, missing-value
policies or the full range of real research experiments.
