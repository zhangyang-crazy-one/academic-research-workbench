# Research learning

This optional extension turns accepted research evidence into explicit, scoped
heuristic candidates. It implements five replaceable ports: `ObservationProvider`
(canonical observation capture), `HeuristicExtractor` (manual/import candidate
publication), `HeuristicStore` (inspection and disposable projection),
`HeuristicEvaluator` (receipt-based evaluation and qualification), and
`HeuristicPromoter` (consented, reviewed ledger promotion).

The runtime capability prefix is `research.learning`. Concrete providers are
loaded only by `arw.composition`. Neither the memory nor artifact compiler
extension is imported. Their accepted artifacts can be referenced through the
ordinary canonical artifact contract. Imported memory remains advisory data;
there is no memory-to-policy execution path.

## Running the example

```bash
uv run --frozen python extensions/research-learning/examples/qualified_lesson.py OUTPUT
```

Use a new output directory. The standalone example creates a run, accepts a
synthetic retrieval-failure receipt, observes it, proposes a manually authored
heuristic, evaluates accepted shadow samples, qualifies, records an approved
project promotion, and inspects a later accepted author decision. Synthetic
metrics demonstrate computation only. The later decision's benefit remains
explicitly unmeasured.

## Configuration and CLI

The project must have an explicit `.arw/project.json` with
`{"schema_version":"arw.project.v1","project_id":"project.example"}`.
The operator controls `.arw/learning-policy.json`:

```json
{"enabled":true,"disabled_run_ids":[],"evaluation_policy_artifact_id":"artifact.policy-v1"}
```

Missing configuration defaults to disabled. The policy artifact must already be
accepted by the selected run. Changing its ID/digest invalidates earlier
qualification for new promotion; a new evaluation is required. The file above is
activation configuration, while the accepted artifact is the immutable,
versioned evaluation policy.

```bash
arw learn status --project-root PROJECT
arw learn observe --project-root PROJECT --run-root RUN --event-id EVENT --request REQUEST.json
arw learn extract --project-root PROJECT --run-root RUN --input CANDIDATE.json --request REQUEST.json
arw learn evaluate HEURISTIC --project-root PROJECT --run-root RUN --sample-artifact-id SAMPLE --request REQUEST.json
arw learn qualify HEURISTIC --project-root PROJECT --run-root RUN --request REQUEST.json
arw learn promote HEURISTIC --project-root PROJECT --run-root RUN --to project --consent --approval-artifact-id APPROVAL --request REQUEST.json
arw learn applicable --project-root PROJECT --input CONDITIONS.json
arw learn use HEURISTIC --project-root PROJECT --run-root DECISION_RUN --decision-artifact-id DECISION
arw learn inspect HEURISTIC --project-root PROJECT
arw learn rebuild --project-root PROJECT
```

Requests use the existing `RuntimeCommandRequest` schema and parent role, unique
command/event IDs, and current expected revision. Exact retries use the original
request. `import`, `reject`, `list`, and authorized `purge` are also available.
JSON output reports typed faults without including submitted secret contents.
Schemas under `schemas/v1/research-learning-*.schema.json` and
`research-heuristic*.schema.json` define the portable input documents.

## Evaluation semantics

`replay`, `held-out`, `shadow`, `A-B`, `human-review`, and `benchmark` consume
actual accepted sample receipts, rather than executing a model or inventing
measurements. Every sample binds the candidate, metric, mode, policy version,
canonical run, baseline, outcome, proposed action, and actual action. A caller
must supply exactly the recorded policy run subset, with one sample per run.
Human review additionally requires reviewer identity and an explicit decision.
Shadow comparison never changes the accepted workflow.

The evaluator computes mean `(outcome - baseline)` and compares it to the
operator's recorded `minimum_delta`; this is a local policy criterion, not a
scientific constant. Counterexamples and unknowns remain distinct. Empty
counterexamples preserve search/evaluation coverage. If requested, the
`supporting-fraction` version `1` confidence formula records counts and result;
confidence remains advisory and does not independently grant promotion.

Promotion requires a PASS evaluation, explicit qualification receipt, an
accepted approval artifact binding the exact candidate digest, qualification,
reviewer and destination scope, plus `--consent`. Domain/global promotion also
requires an explicitly transfer-authorized, accepted reviewer attestation with
independent project/run IDs and source/evaluation digests. This is reviewed
transfer evidence; the extension does not fetch or independently reproduce an
external project's experiment. Such promotion still emits an advisory heuristic,
not an executable policy.

## Deferred and unsupported behavior

`arw learn evolve` returns `CapabilityUnavailable`, naming
`research-workflow-evolver`. There is no `WorkflowEvolver` port, workflow-candidate
table, skill generation, or prompt rewrite in this extension. A model-assisted
extractor may supply candidates through the input contract with producer/version,
model identity and input/output digests; no hosted-model extractor is bundled.

Read [CONTRACT-INVENTORY.md](CONTRACT-INVENTORY.md),
[PROJECT-IDENTITY.md](PROJECT-IDENTITY.md), and [PRIVACY.md](PRIVACY.md) for the
storage, identity, recovery and retention boundaries.
