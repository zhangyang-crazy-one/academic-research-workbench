# Proposed live comparison — native authenticated Codex execution plan

This is the execution plan for issue #77, not a record of a live run. No live
model calls have been recorded under this plan; token usage and USD billing
remain unmeasured, and `live_comparison.status` is `not_measured`.

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
  all sixteen response values and select the predicted maximum from all sixteen
  candidate configurations using the same eight observed rows;
  output only the attempt JSON. ARW-route instructions: before output, organize
  the observed main-factor contrasts, then the observable pair contrasts and
  uncertainty, and use that structured analysis to fill the same sixteen-row
  JSON contract and select the predicted maximum from those same sixteen
  candidates. Both arms have the same eight-observation budget, candidate set,
  response schema and limits.
- Compute the deterministic pair-effect ridge on those exact observations as
  an additional offline baseline. Keep any future sampling-policy experiment
  separate; this plan tests response reconstruction, not sample acquisition.

## Proposed execution limits

| Setting | Declared execution limit |
| --- | --- |
| Model and reasoning | Codex native authenticated `gpt-6.1-sol`, `high`, both arms |
| Tasks and arms | 3 tasks × 2 arms |
| Maximum model calls | **6 total**, one per task/arm, no retry or model judge |
| Model-visible observations | Exactly 8 rows per call, same per task in both arms |
| Output | One selected config plus 16 finite response values; JSON only |
| Output cap | 4,096 tokens per call if the selected host supports that cap |
| Stop | Stop after the first submission, failure or budget overrun for each slot; retain the failed slot |

Use Codex's native model through its existing local authentication. Do not
call a model API directly, introduce an API key, or inspect credential contents.
Provide any other required configuration through the project's `.env` without
including secrets in evidence or commits. Do not switch models without explicit
user authorization.

Before execution, confirm the host supports the declared settings and enforces
the six-call limit. The run uses the user-authorized native authenticated
Codex route. If the host cannot enforce a required setting, stop and return
for review.
Provider-reported token usage or USD billing may be unavailable for authenticated
CLI calls; record `unavailable` for each missing field, never zero or a fabricated
estimate, and do not claim an enforceable USD cap without host evidence.

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
