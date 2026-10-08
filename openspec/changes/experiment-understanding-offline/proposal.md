## Why

Issue #77 asks whether an experiment route reconstructs the response to changed
settings, rather than merely guessing the best setting. Authors need separate,
replayable evidence for that distinction before using model-assisted experiment
analysis in paper production. The owner amendment authorizes the offline suite
first and defers a paid same-model comparison.

## What changes

- Add an independent, versioned three-task, four-binary-factor synthetic CPU
  response-table suite with frozen seeds, eight observed rows per task, hidden
  sixteen-row references, budgets, metrics, and stopping rules.
- Add a deterministic offline scorer with four distinct axes, typed invalid and
  missing outcomes, all-attempt denominators, delivered-only slices, and a
  replayable digest receipt.
- Add a fixed pair-effect ridge baseline using the same observations, a public
  input command, tests, and an exact proposed live-run plan.

## Impact and boundaries

The experiment-analysis workflow can produce auditable local evaluation
evidence; it cannot yet claim a live model advantage. No external benchmark
data, paid model calls, automatic learning promotion, or #69 claim-type changes
are part of this change. The existing 32-case evaluation corpus and contracts
remain separate.
