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
