# Offline research evaluation harness

This is a local contract and synthetic fixture harness for issue #38. The 32
English/Chinese tasks in `corpus/v1.json` were authored for ARW; twelve are
adversarial. No AstaBench, LitQA2, or other third-party benchmark content is
included. The harness does not run a model, fetch data, read credentials,
upload results, or schedule work. No empirical same-model baseline versus
ARW-route comparison has been performed.

## Input and run

Create two local JSON files, one with `route: "baseline"` and one with
`route: "arw-route"`. Each has this shape (shown with one result for brevity;
the real input must contain exactly one result for **every** corpus case):

```json
{
  "schema_version": "arw.eval-bundle.v1",
  "route": "baseline",
  "corpus_version": "self-authored-2",
  "results": [
    {"task_id": "cite-01", "answer": {"citations": [{"id": "source-method-a", "status": "valid"}]}}
  ]
}
```

Answers use exactly the fields declared by the case checker:
`citations` (ID and `valid`/`retracted`/`unknown` status),
`locator`/`quote`/`quote_sha256`, `gate`
(`pass`/`block`/`human_review`), `route`, or `text`.
Optional bundle fields are `run_id`, `build_identity_sha256`, `model_id`, and
`cost` (`tokens`, `usd`, `elapsed_ms`). They must be recorded facts, never
estimated. Omitted cost fields and model/build identity are reported as
`unavailable`; zero is only recorded when the input explicitly says zero.
The literal `unavailable` is a receipt marker, not a valid input `model_id`.
If both bundles record a `model_id`, they must agree or the comparison fails.
The receipt's `pairing` is `matched` only when both recorded IDs agree; if
either is absent it is `unavailable`. This records ID agreement, not proof of
identical model settings or an empirical same-model experiment.

```bash
scripts/arw-eval --baseline /local/baseline.json \
  --arw-route /local/arw-route.json --receipt /local/receipt.json
```

The CLI writes a new local file and refuses to overwrite an existing path.
Inputs are capped at 1 MiB each, must be regular files, and may not be
symlinks. Reads use a no-follow file descriptor and recheck file identity and
size after reading. Receipt and optional candidate are staged as separate
local files before exclusive installation; an ordinary install failure rolls
back any output installed by that invocation. Independent paths cannot form a
single filesystem transaction across a process crash. Unknown fields,
duplicate JSON keys, missing/duplicate case results,
wrong checker shapes, and corpus mismatches fail with a JSON error on stderr.
The complete corpus, bundle, receipt, and candidate-context shapes are in
`schemas/v1/eval-run.schema.json` (`$defs`). The result bundles are retained by
the operator; the receipt does not copy raw answers.

## Metrics and receipt

Citation precision/recall compare exact source IDs; status accuracy counts
exact ID-and-status matches over expected citations (a missing ID counts as
wrong). The corpus must contain at least one expected citation ID. In
evaluator version `2`, predicting no citations against this corpus yields
precision `0`, not a vacuous perfect score. Quote/locator accuracy checks exact
locator equality and SHA-256 of the UTF-8 quote bytes against both the
answer's declared digest and corpus reference digest. It is **not** evidence
of semantic claim support, source authenticity, or paper truth. Gate TP/FP/TN/FN
use `block` as the positive class and collapse `pass` and `human_review` into
the negative class. The nine `gate_<expected>_as_<actual>` counts retain every
three-way distinction, including `gate_human_review_as_block`. A retracted
supporting citation or supporting not-found source expects `block`; a retracted
paper studied as the research object expects `human_review`, without automatic
pass or waiver. These are synthetic per-use decisions, not a live citation
resolver result. Route accuracy compares exact route labels.
Leakage hits count literal project-specific sentinel occurrences in answer
text. `summary.delta` is `arw-route` minus `baseline` for each metric; its
direction is descriptive, including for error counts. These deterministic
checks do not measure broad research quality or
human-reviewed semantics.

Receipt bytes are canonical UTF-8 JSON with sorted keys, compact separators,
and one terminal newline. SHA-256 values bind original corpus/bundle bytes,
canonical per-case scores, canonical summary, and the complete receipt body
excluding `receipt_sha256`. Verify against retained inputs by replay:

```python
from pathlib import Path
from evals.offline import verify_receipt

assert verify_receipt(
    Path("/local/receipt.json").read_bytes(),
    "evals/corpus/v1.json",
    "/local/baseline.json",
    "/local/arw-route.json",
)
```

An input change invalidates the receipt, including changes to whitespace.
The receipt is a local integrity record, not an admitted ARW artifact.

## Optional research-learning candidate

Use `--candidate-context /local/context.json --candidate-out
/local/sample-candidate.json` together. Context must give a real candidate's
`heuristic_id`, its exact `proposed_action`, a recorded `actual_action`, and an
`arw.learning-policy.v1` object. The bundles must both record the same
canonical `run_id`; that ID must be in the policy's `run_subset`. The policy
must use `mode: "benchmark"` and a bounded rate metric such as
`citation_recall`. The adapter validates the current policy and
`EvaluationSample` schemas and emits only the sample body.
Only the five bounded rates (`citation_precision`, `citation_recall`,
`citation_status_accuracy`, `quote_locator_digest_accuracy`, and
`route_accuracy`) can be mapped into a benchmark sample. Gate confusion
counts and leakage counts remain in the receipt and are not promoted as rates.

The local context is an assertion by the operator; this harness cannot prove
that its policy, run, or heuristic were accepted by the parent. Before using
the candidate, the parent must check the actual project learning policy,
accepted policy artifact, candidate action and run membership, accept each
per-run sample artifact, and then call the existing learning evaluator with
the exact policy run subset. An aggregate eval receipt is not a substitute
for those per-run accepted samples. The harness writes no learning ledger,
does not call `evaluate`/`qualify`/`promote`, and cannot change a gate.

Live same-model comparisons, model judges, public benchmark imports, hosted
jobs, and online execution require a separate authorized change and, for
external datasets, a specific license and redistribution review.

## Independent four-factor CPU understanding fixture (issue #77)

`evals/experiment_understanding/v1/` is a separate, original three-task suite.
It does not change the 32 cases above. Each task has four binary factors,
sixteen possible configurations, eight fixed observed rows, one frozen seed and
a precomputed full reference table. The response is an arithmetic CPU-workload
surrogate, **not** measured hardware throughput. The committed producer
`v1_fixture.py` regenerates the hidden table; `manifest.json` binds the exact
task, observation and reference bytes. No WhatWorkedBench data or code is
redistributed. `prepare` reads only the public task and observation files; it
never opens the hidden reference. Give a model only this public output, never
the source tree, producer, manifest or hidden reference.

```bash
# One agent-facing task input: exactly eight approved observations, no answers.
scripts/arw-experiment-eval prepare --task-id cpu-batch-v1 --output /tmp/cpu-batch-input.json
# Local statistical baseline from those same eight rows (no model call).
scripts/arw-experiment-eval ridge --output /tmp/ridge-attempts.json
scripts/arw-experiment-eval score --attempts /tmp/ridge-attempts.json --receipt /tmp/ridge-receipt.json
scripts/arw-experiment-eval verify --attempts /tmp/ridge-attempts.json --receipt /tmp/ridge-receipt.json
```

The JSON contracts are in `evals/experiment_understanding/v1.schema.json`. A
scoring input predeclares one `plan` slot per task per route and retains every
submitted `attempt`. A delivered attempt names its task/observation digests,
the exact eight `observations_used` IDs, selected configuration, and all sixteen
`{config,value}` rows. The scorer retains absent slots and extra/duplicate
submissions in the all-attempt denominator. An invalid or missing table gets
`delivery=0`, null raw errors, zero quality, and typed reason codes (including
missing or duplicate configurations, unapproved/budget-overrun observations,
nonfinite values and digest mismatch). No error is falsely recorded as zero.

The four reported axes are selection regret (true best value minus selected
configuration value), mean absolute conditional contrast error across all
factor/context combinations, mean absolute pair-interaction contrast error,
and full-table delivery rate. Lower raw error is better. Each error also has a
predeclared 0–1 quality score; all-attempt quality uses zero for undelivered
slots, while `delivered_only_error` and `delivered_only_quality` show the
surviving slice. Missing cost fields remain `unavailable`; explicit zero stays
zero. The receipt binds raw input byte digests, per-task digests, scores and a
canonical receipt digest, and `verify` recomputes it from retained inputs.
`live_comparison.status` remains `not_measured` until a separately authorized
same-model run. This suite does not add #69 claim types, write to the learning
ledger, or promote a heuristic. The proposed paid-run protocol is in
`evals/experiment_understanding/LIVE-PLAN.md`.
