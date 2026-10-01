# Source-bound writing transformations

The optional `arw_writing` package implements `WritingTransformer` outside the
kernel. The composition root resolves five operations. Missing extension files
produce the ordinary `CapabilityUnavailable` receipt. There is no nested model
client: the first adapter accepts explicit session-generated, exact-span edits.
It applies edits rather than accepting an unbound output file. Actual model
identity, prompt digest, parameters, original bytes and candidate bytes are kept;
regeneration is not promised to be deterministic.

| Operation | Author-directed use |
| --- | --- |
| `writing.academic_rewrite` | Academic tone and manuscript organization |
| `writing.naturalize` | Clear, natural phrasing and reading rhythm |
| `writing.statistical_humanize` | Change explicitly selected surface regularities |
| `writing.claim_preserving_rewrite` | Rephrase around the retained claim and limitations |
| `writing.citation_aware_rewrite` | Revise phrasing around evidence attribution |

All operations share the exact-span engine and conservative gate. None substitutes
for ARS evidence checks. Author intent is supplied with the proposal, not inferred
from a metric. Controls (`change`, `increase`, `decrease`) compare actual results;
paragraph cadence supports `change` only. Unsupported/ineffective controls cannot
be promoted through the acceptance path.

## Diagnostic definition v1

`arw.writing-surface.en-zh.v1` uses English word tokens, individual Chinese
characters and decimal-number tokens. Sentence segmentation uses punctuation and
blank lines, preserves decimal dots, and is a surface heuristic. Paragraphs split
at blank lines. All variances are population variances, rounded to six decimals.

| Control | Measured effect |
| --- | --- |
| `sentence_structure` | Number of sentences plus comma/semicolon clause boundaries |
| `length_rhythm` | Sentence token-length population variance |
| `connectors` | Fixed English/Chinese connector lexicon count |
| `lexical_repetition` | Token count minus distinct token count |
| `syntactic_repetition` | Repeated first-two-token sentence starts (surface proxy) |
| `paragraph_cadence` | Ordered paragraph token-length vector |

Additional outputs retain lexical diversity, trigram repetitions, token-frequency
map, sentence/paragraph lengths and paragraph variance. Inputs under 50 tokens
carry a short-text caution. Other scripts are unsupported; mixed foreign-language
text is not fully characterized. No syntactic parser or semantic-equivalence model
is claimed. The exact fixture metrics are pinned in `tests/integration/test_writing.py`.
No detector runs by default. Metric changes never establish watermark absence,
human authorship or meaning. The separate detection report below is opt-in.

## Optional detector audit

`writing audit` reads two local UTF-8 files without editing them. `writing
prepare` and `writing record` also accept `--detectors CONFIG.json` and attach
the same audit to the source-bound candidate bundle. All three commands accept
`--allow-network` only for a configured HTTP detector; this sends **both full
texts** to its configured endpoint. There is no automatic external request.

```sh
PYTHONPATH=src:extensions/academic-humanization/src python -m arw.cli writing audit \
  --source original.txt --revision revised.txt --detectors detectors.json
```

The JSON configuration is `{"detectors": [{"backend": ..., ...}]}`. Supported
backends are:

| Backend | Required config | Scope |
| --- | --- | --- |
| `naive_bayes_local` | `model_path`, `label` | Offline multinomial model JSON (`arw.naive-bayes-model.v1`), lowercase ASCII word tokenizer. User supplies training counts. |
| `transformers_local` | `model_path`, `label` | Optional installed `transformers` and `torch`, with a local sequence-classification model directory. Loads with `local_files_only=True`, CPU inference and full input length check; it never downloads weights. |
| `hmac_green` | `key`, `vocabulary`, `gamma`, `min_tokens` | Exact `arw.hmac-green-whitespace.v1` generator contract only. `key_id` is a non-secret reference. |
| `http_json` | `endpoint`, `model`, `version` | Explicit `--allow-network`; POST JSON `{text, model}`, response JSON `{score, label, version}`. HTTPS is required except loopback. Redirects and URL credentials/query are rejected. No provider has been qualified by this adapter alone. |

The `tests/fixtures/writing_detection/synthetic_nb.json` model provides a
reproducible **synthetic** classification example. Its score has no measured
accuracy on real AI or human writing. For `transformers_local`, the author must
supply and separately validate an offline model, its license, language coverage,
class labels and false-positive rate. This repository does not download or
endorse a model. The digest of local model bytes, package version, token count,
target label and configured length limit are recorded. Inputs exceeding that
limit are `unsupported` rather than silently truncated.

Run the exact local example with `python examples/writing_detection_demo.py
--output-dir /tmp/arw-writing-demo`. It writes public synthetic input/config
files and invokes `writing audit`. The deliberately repetitive all-green
sequence violates the independent-null approximation; its z score is an
algorithm execution check, **not** a calibrated p value or significance claim.

The watermark z score tests green-token excess under an approximate independent
null. It requires the exact key, vocabulary, literal whitespace tokenization,
and HMAC/hash green-list generator described in the code. This is a local
synthetic analogue of green-list statistical watermarking, **not a detector
for arbitrary KGW or other language-model watermarks**. If the generation
algorithm, tokenizer, key or vocabulary is unknown, do not substitute these
parameters: report `not_run` or `unsupported`. The key itself and its hash are
excluded from reports. A user-supplied z threshold is labeled `user_config`;
there is no calibrated operating threshold here.

Each detector's `classification` or `watermark` result records backend,
version, public parameter fingerprint, input SHA-256, raw score and meaning,
status (`available`, `not_run`, `unsupported`, `error`), and a bounded failure
class where applicable. A delta is emitted only if both results are available
and share backend, version and public configuration in the same invocation.
Configuration fingerprints omit secret key bytes, so reports from separate
runs cannot independently prove key equality. Classifier softmax or normalized
likelihood is uncalibrated and is not the probability of AI authorship. Scores
are not author-identity conclusions, proof of watermark absence, or evidence
that a revision evades a detector. This workflow does not search edits against
detectors or optimize writing to lower their scores.

The audit reuses the bundled fact-locked results checker for numeric values,
citations and table-row associations. `mechanical_status` may be `passed` or
`failed`; `semantic_status` remains `human_review_required`. If the checker is
unavailable in an installation, the status is `unsupported`; the existing
exact-span writing preservation checks still apply. A mechanical failure
rejects a writing proposal. Human review is still required for logical
direction, conclusion strength, citation scope, conditions and meaning.

## Execution and review

```sh
bin/arw writing prepare --run-root RUN --source-id artifact.manuscript --proposal proposal.json
bin/arw writing record --run-root RUN --source-id artifact.manuscript --proposal proposal.json --request request.json
bin/arw writing record --run-root RUN --source-id artifact.manuscript --proposal proposal.json --request new-request.json --review-artifact-id artifact.review
```

The proposal schema is `Proposal` in `arw_writing.transformer`: explicit capability,
source SHA-256, author target, language, protected terms/spans, controls, generation
identity and ordered edits with character offsets. Invalid, overlapping, unchanged
or oversized candidates fail. Text is bounded to 64 KiB per source/candidate.
CLI proposal JSON is bounded to 256 KiB. Sources must already be accepted and their
current bytes must match their canonical manifest.

Exact observed drift in protected quantities, equations, citation IDs, quotes,
qualifiers and named terms is rejected. Citation-to-assertion bindings and all
contextual dimensions are retained for review. Absence of lexical differences is
never semantic PASS: every changed candidate needs a real explicit review.
`writing record` without approval admits a `writing-review-receipt`, including
rejected candidates and findings; it does not admit revised manuscript prose.

A `writing-human-review` artifact accepted by the parent must contain:

```json
{
  "schema_version": "arw.writing-review.v1",
  "source_sha256": "<exact source digest>",
  "candidate_sha256": "<exact candidate digest>",
  "proposal_sha256": "<exact proposal digest>",
  "verification_sha256": "<exact verification digest>",
  "decision": "APPROVED",
  "reviewed_dimensions": ["<every unresolved dimension in emitted order>"],
  "reviewer": "<actual reviewer identity>",
  "rationale": "<actual review outcome>"
}
```

The service verifies this receipt's binding and requires all controls effective;
hard drift cannot be overridden. It does not authenticate human identity independently
of the parent artifact admission. Hosts must collect the real decision and must not
manufacture approval. Test reviewers are explicitly synthetic fixtures.

Accepted `writing-derived` bundles retain original/candidate, author goal, generation
identity, diagnostics/version, scoped findings, source and review manifest/event
hashes. The existing runtime writer handles admission, stale revisions and gates;
no new event decoder is needed. Exact retries are idempotent and changed command
inputs conflict. Files are create-only. Rollback disables new extension calls but
existing artifact events/bundles remain readable and replayable.
