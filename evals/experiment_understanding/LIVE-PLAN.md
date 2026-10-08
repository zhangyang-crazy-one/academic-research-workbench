# Proposed live comparison — approval required before any model call

This is a reviewable proposal for issue #77, not a record of a run. No model
has been called, no token or dollar cost has been incurred, and
`live_comparison.status` is `not_measured`.

## Frozen inputs and arms

- Use the three committed `original-cpu-surrogates-1` tasks. Verify the
  `manifest.json` hashes immediately before the run. Each task has four binary
  factors, eight fixed observed configurations, sixteen hidden reference rows,
  and one final response-table submission. Do not add adaptive observations.
- Generate each task's public JSON with `scripts/arw-experiment-eval prepare`.
  Send **only that JSON** to the model. Keep `hidden-reference.json`, its
  producer `v1_fixture.py`, the scorer, manifest, and repository filesystem
  outside the model's accessible context and tools. The evaluator reads the
  hidden table only after all planned attempts are sealed.
- Compare `baseline` and `arw-route` on exactly the same public JSON bytes for
  each task. Run each arm in a fresh context. Baseline instructions: predict
  all sixteen response values and select the maximum from the eight observations;
  output only the attempt JSON. ARW-route instructions: before output, organize
  the observed main-factor contrasts, then the observable pair contrasts and
  uncertainty, and use that structured analysis to fill the same sixteen-row
  JSON contract. Both arms have the same data, response schema and limits.
- Compute the deterministic pair-effect ridge on those exact observations as
  an additional offline baseline. Keep any future sampling-policy experiment
  separate; this plan tests response reconstruction, not sample acquisition.

## Proposed execution limits

| Setting | Frozen value for approval |
| --- | --- |
| Model and reasoning | `gpt-6-sol`, `high`, both arms |
| Tasks and arms | 3 tasks × 2 arms |
| Maximum paid calls | **6 total**, one per task/arm, no retry or model judge |
| Model-visible observations | Exactly 8 rows per call, same per task in both arms |
| Output | One selected config plus 16 finite response values; JSON only |
| Output cap | 4,096 tokens per call if the selected host supports that cap |
| Stop | Stop after the first submission, failure or budget overrun for each slot; retain the failed slot |

Before execution, the operator must confirm the host supports those settings
and set a maximum authorized spend. If a setting or spend cap cannot be
enforced, stop and return for review. Do not inspect or load credentials until
separate authorization covers the paid run.

## Evidence and cost collection

Predeclare six attempt IDs (`baseline.<task-id>` and `arw-route.<task-id>`) in
one attempts file. Retain the exact public input bytes and SHA-256, route prompt
bytes and SHA-256, raw model output, model ID, supported model settings,
timestamps, and provider-reported input/output/total token counts and billed
USD where available. Record elapsed milliseconds from the host clock. Map
missing provider cost fields to `unavailable`, never to zero or an estimate.
Malformed, refused or absent outputs remain attempts with `delivery=0`.

After sealing all six outputs, run the offline scorer and verify its receipt
against the retained inputs. Report all-attempt quality, delivered-only raw
errors and quality, delivery rate, actual observed costs, and the ridge slice.
Only then may the report state a live same-model comparison; the current
offline receipt must continue to say `not_measured`. Do not feed the scores into
automatic learning evaluation, qualification or promotion. These synthetic
surrogates do not establish performance on real CPU workloads or scientific
causal understanding.
