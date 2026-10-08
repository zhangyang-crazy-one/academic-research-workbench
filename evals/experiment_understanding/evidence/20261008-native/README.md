# Native Codex observation, 2026-10-08

Six fresh Codex native agents were requested as `gpt-6.1-sol/high`, with no
history fork, retries or model judge. Both arms received identical public JSON
per task: eight observed rows and the same sixteen possible outputs. The
`arw-route` arm adds a structured contrast/uncertainty prompt. This is a
contract-informed prompt comparison, not execution of a complete ARW workflow.

| Route | Delivered | Selection regret | Conditional effect MAE | Pair interaction MAE |
| --- | --- | --- | --- | --- |
| baseline | 3/3 | 7.433333 | 5.759375 | 7.154861 |
| arw-route | 3/3 | 7.433333 | 6.221875 | 7.497917 |
| offline pair-effect ridge | 3/3 | 7.433333 | 5.760743 | 7.080665 |

Lower errors are better. The structured arm did not improve these three
synthetic tasks. With all deliveries valid, the all-attempt and delivered-only
quality denominators coincide. Full normalized qualities and raw per-task
errors are in the score receipts. No additional sample was acquired.

`live-observation.json` is parent-owned observational evidence for actual
native submissions; it has no provider signature or scientific admission.
`offline-score.json` is still the unchanged v1 offline scorer receipt and its
`live_comparison.status` remains `not_measured`: that scorer does not attest
how caller-supplied answers were produced. Both receipts replay exactly from
retained attempts; the native report references their byte digests.

No direct API call or credential read was used. Provider token counts and
billed USD are unavailable, with no approved or enforced USD cap. Measured
elapsed values are parent dispatch-to-capture wall time, including scheduling
and capture delay; the first slot has unavailable elapsed time because its
start timestamp was not captured. They are not inference-time benchmarks.

The host accepted explicit model/reasoning settings and fresh-context requests.
Tool prohibition and the 4096-token target were instructions, not host-enforced
isolation/output caps. No tool calls were observed in returned agent results;
this does not establish inaccessible hidden files. Hidden reference/producer
and grader were excluded from each supplied prompt and history; grading began
after all six answers had been captured. Raw replies, exact prompts, public
inputs, predeclared plan, host observations and SHA-256 inventory are retained.
No cost estimate, platform billing verification, qualification, memory
promotion or parent-ledger mutation is claimed.

Replay from this repository root:

```bash
python3 -m evals.experiment_understanding.offline verify --attempts evals/experiment_understanding/evidence/20261008-native/attempts.json --receipt evals/experiment_understanding/evidence/20261008-native/offline-score.json
python3 -m evals.experiment_understanding.offline verify --attempts evals/experiment_understanding/evidence/20261008-native/ridge-attempts.json --receipt evals/experiment_understanding/evidence/20261008-native/ridge-score.json
```

These original arithmetic surrogates cannot establish real-workload or causal
understanding performance. Scores do not authorize learning promotion.
