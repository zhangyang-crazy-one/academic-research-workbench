# Source-bound writing transformations

## Advisory narrative fit

`arw writing narrative-fit` reads one accepted manuscript artifact, the selected
project narrative, a reviewed venue profile, and optionally promoted venue
heuristics. It never changes the narrative, journal, manuscript, acceptance
decision, or venue profile. A capture writes a self-contained snapshot when
`--snapshot-out` is supplied; replay reads that file offline and emits the same
canonical report bytes even after the active narrative or profile changes.
The smallest live invocation is `arw writing narrative-fit --run-root RUN
--target VENUE_ID`: it selects the latest accepted draft in that run and
converts the matching entry in the bundled annual venue registry into a frozen
profile. The bundled hard-gate prose remains `unknown` until an exact reviewed
typed predicate is supplied. Each rule points to the exact bundled file digest
and JSON locator; the registry does not assign a single official source URL to
each statement, so the report does not invent one. An absent target or draft
is an actionable error.

```sh
PYTHONPATH=src:extensions/academic-humanization/src:extensions/research-learning/src \
  python -m arw.cli writing narrative-fit --run-root PROJECT/runs/RUN \
  --target venue-id --manuscript-artifact-id draft-artifact \
  --profile reviewed-venue-profile.json --snapshot-out fit-snapshot.json
PYTHONPATH=src:extensions/academic-humanization/src \
  python -m arw.cli writing narrative-fit --target venue-id --snapshot fit-snapshot.json
```

For a proposed realization whose graph may fail, accept the exact UTF-8
manuscript source through the ordinary artifact path and pass its artifact ID
with `--realization PROPOSED.json` (a path relative to the run root). The
proposed sidecar must name those same bytes. Mechanical graph or span failures
appear in the structural layer with a reason code. Changed accepted bytes,
source digests, or frozen evidence are input-integrity errors.

An accepted `writing-derived` draft can also be the manuscript artifact. Fit
reads the original accepted receipt, verifies its human-approved candidate and
nested draft realization, then binds the retained candidate text by path and
SHA-256. Its `writing_candidate_receipt` snapshot binding freezes the receipt,
run and artifact manifest bytes, accepted event identity, candidate path/digest,
and canonical realization digest. It also freezes the accepted source and human
review proofs. Capture and offline replay check these links with the same
validator. An explicit `--realization` sidecar is accepted for this mode only
when it matches the realization inside the accepted receipt. Historical
standalone realization and manuscript-source snapshots keep their exact byte
equality checks.

The profile contract (`arw.venue-fit-profile.v1`) names a venue, version,
`verified_on`, `review_due`, and provenance for each official or structural
rule: source URL, exact source SHA-256, locator, and reviewer for typed
predicates. Rules expressed only in natural language remain `unknown`. The
bounded typed predicates are exact Markdown heading presence, exact text
presence, a maximum page count measured only from an explicitly accepted PDF,
and a listed-marker search. The last predicate reports a bounded observation,
never comprehensive anonymity. Page count without `--pdf-artifact-id` is
`not_evaluated`. Fit snapshots contain manuscript and referenced predecessor
or evidence bytes, so store them as private project data.

`--heuristic-id` selects only a promoted heuristic reviewed by the local
learning service for the specified `--domain-id` and venue. Its inspected
record, promotion event ID, supporting, counterexample and unknown evidence
remain separate from official requirements. A heuristic without a reviewed
typed match stays `unknown`; learned counts are descriptive, with no
acceptance probability. With no selected heuristic, the empirical layer says
`not_evaluated`, not that the venue has no relevant patterns. Optional
`--judgment` accepts an existing
`arw.fit-judgment.v1` JSON with reviewer, assessment, input digest, and, when
model assisted, model ID, provider and prompt version. This command never
invokes a model. Judgment cannot change the three deterministic layers.
The initial report exposes `input_binding.judgment_input_sha256`; use that
digest in a reviewed judgment file. For a promoted heuristic, a separate
`--heuristic-annotations` JSON may bind its ID to a reviewed typed predicate
and reviewer, for example `{"heuristic.id":{"predicate":{"kind":
"heading_present","value":"Limitations"},"reviewed_by":"reviewer.id"}}`.

Freshness is a separate live comparison: add `--freshness --run-root RUN
--profile PROFILE --as-of YYYY-MM-DD`. It checks selected narrative and
profile bytes against the frozen input and flags `needs_recheck` after the
profile's `review_due`, even when its bytes are unchanged. Offline replay
does not silently refresh source facts. The report is advisory and supplies
minimal review suggestions for typed mismatches; it does not revise a plan,
create an acceptance decision, or infer compliance from prose.

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
| `openai_gpt2_detector_local` | `model_path` | Fixed offline preset for OpenAI's English GPT-2 output detector, target class `Fake`; checks all six pinned files and accepts safetensors only. |
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

### Official GPT-2 detector preset

The `openai_gpt2_detector_local` preset pins
[`openai-community/roberta-base-openai-detector`](https://huggingface.co/openai-community/roberta-base-openai-detector/tree/6cba99c003b711c7fe94f8a3aa2be35a792cb6fa)
at revision `6cba99c003b711c7fe94f8a3aa2be35a792cb6fa` (MIT). Its six
exact file SHA-256 digests live in `arw_writing.gpt2_preset`; the 500,975,390
byte `model.safetensors` digest is
`3abd6d2b005f5876b945cb5b68ddde04f6e28fbd9c5d6dc5adfb06ba647e0546`.
The downloader never selects `pytorch_model.bin` or other pickle weights.
No weights are bundled with ARW. Local inference requires an explicitly
supplied `model_path`; missing, changed or extra model files cannot score.
The preset checks package versions, input hash and full pinned model identity
in each report. It refuses non-ASCII alphabetic input conservatively, and
input over 512 model tokens is unsupported rather than truncated.

For a separate temporary CPU environment, use the following commands. The
`--download` flag is the only step that fetches the public model files; its
destination is the local directory you choose. It never sends manuscript
text. The installation commands fetch Python packages, so review their
licenses in your environment before running them.

```sh
UV_CACHE_DIR=/tmp/arw-gpt2-uv-cache uv venv /tmp/arw-gpt2-detector-venv --python python3.13
UV_CACHE_DIR=/tmp/arw-gpt2-uv-cache uv pip install --python /tmp/arw-gpt2-detector-venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu
UV_CACHE_DIR=/tmp/arw-gpt2-uv-cache uv pip install --python /tmp/arw-gpt2-detector-venv/bin/python 'transformers>=4.45,<5' safetensors 'pydantic>=2.13.4' 'jsonschema>=4.26.0' 'portalocker>=3.2.0' 'platformdirs>=4.11.6'
/tmp/arw-gpt2-detector-venv/bin/python examples/fetch_openai_gpt2_detector.py --destination /tmp/arw-gpt2-detector --download
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /tmp/arw-gpt2-detector-venv/bin/python examples/openai_gpt2_detector_demo.py --model-path /tmp/arw-gpt2-detector --output-dir /tmp/arw-gpt2-demo
```

Without `--download`, `fetch_openai_gpt2_detector.py` only verifies already
present files. The demo contains two fixed public English paragraphs with no
known GPT-2 or human ground-truth labels. Its two scores prove that this pinned
model ran locally; they do not measure classification accuracy. The
[model card](https://huggingface.co/openai-community/roberta-base-openai-detector)
describes this as a detector trained for English GPT-2 outputs and explicitly
warns against using it as a ChatGPT detector for serious misconduct
allegations. Its softmax score is not an authorship probability. No validity is
claimed for newer models, Chinese, mixed-language papers, or short passages;
false-positive rates for a particular manuscript domain are unknown.

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
Custom adapters must return a JSON-object `parameters` value and set
`config_sha256` to SHA-256 of the repository's canonical JSON serialization of
`{"kind": kind, "backend": backend, "version": version, "parameters": parameters}`.
Available results must name and explain their score. The runtime rejects a
stale or malformed fingerprint and checks parameter equality again before
computing a delta. A regression fixture changes `model_sha256` while reusing
one stale fingerprint; detection raises `invalid envelope`, so no delta is
reported.
Configuration fingerprints omit secret key bytes, so reports from separate
runs cannot independently prove key equality. Classifier softmax or normalized
likelihood is uncalibrated and is not the probability of AI authorship. Scores
are not author-identity conclusions, proof of watermark absence, or evidence
that a revision evades a detector. This workflow does not search edits against
detectors or optimize writing to lower their scores.

The audit reuses the bundled fact-locked results checker for numeric values,
citations and table-row associations. `mechanical_status` may be `passed` or
`failed`; `semantic_status` remains `human_review_required`. Installed plugin
runs resolve the checker inside the launcher-bound `ARW_PLUGIN_ROOT`; source
runs use the source tree. If the checker is missing, the status is `unsupported`;
unsafe symlink paths report `error`. The existing
exact-span writing preservation checks still apply. A mechanical failure
rejects a writing proposal. Human review is still required for logical
direction, conclusion strength, citation scope, conditions and meaning.

## Execution and review

### Rule review tasks and findings

Every `writing prepare` result includes `verification.rule_review.plan`: five
provider-neutral tasks for argument structure, fact integrity, claim strength,
definitions/boundaries, and traceable revision. The plan binds the exact source
and candidate SHA-256 values and has its own digest inside `verification_sha256`.
It is a task list, not an automatic language-model judgment. The result's
`rule_review.status` is `not_run` until a reviewer submits a report. Reviewer
guidance does not prescribe paragraph order, a fixed number of contributions,
or vocabulary changes; it explicitly preserves already cautious claims.

A human reviewer or explicitly chosen review provider can add `rule_review` to
the accepted `writing-human-review` artifact described below. Its schema is
`arw.writing-rule-review.v1` with `source_sha256`, `candidate_sha256`,
`plan_sha256`, nonempty `provider` and `reviewer`, all five `coverage` entries in
plan order, and zero or more `findings`. Each coverage entry records `category`,
`status` (`reviewed`, `not_applicable`, `not_reviewed`) and an explanation.
Each finding records `category`, advisory `severity` (`warning` or `suggestion`),
independent `confidence` (`low`, `medium`, `high`), `review_status` (`open`,
`resolved`, `accepted_risk`), exact `candidate_span` character offsets and quote,
optional exact `source_span`, `evidence`, `reason` and `minimal_change`. For an
`accepted_risk` or `resolved` finding, `resolution_reason` explains that state.
For an
`APPROVED` review, every category must have been reviewed or explicitly marked
not applicable, and no finding may remain open. An empty findings list means
only that the named reviewer recorded no findings; it does **not** prove semantic
equivalence or absence of defects. The parent review artifact also binds the
proposal and verification hashes, decision, and unresolved preservation
dimensions. The accepted artifact manifest digest is retained in `review_binding`.

For a public synthetic example, a reviewer could mark a local passage about
`ModelX` as a low-confidence `suggestion` in `claim_strength`, quote its exact
candidate character span, explain the source evidence, and request one small
scope clarification. `tests/integration/test_writing_review_rules.py` exercises
this report end to end. It labels its reviewer as a **synthetic fixture** and
does not submit a real manuscript for model review. Changing the quote, span,
plan or text digest invalidates the report. A submitted but incomplete report
cannot approve a candidate. New reviews using the earlier v1 envelope without
`rule_review` remain valid for a candidate prepared by this version; their bundle
states `rule_review.status: not_run` rather than claiming the five tasks passed.
Previously accepted bundles remain readable. A pending review bound to a
pre-change `verification_sha256` must be regenerated against the new plan; stale
approval is not silently reused. The bundle retains the validated report values;
`review_binding` identifies the
accepted artifact containing the reviewer's exact submitted bytes.

Semantic findings remain reviewer opinions. High confidence does not turn them
into mechanically proven contradictions. Only the existing exact preservation
and fact-lock checks produce automatic `reject`; writing diagnostics and AI
classifier/watermark scores do not determine writing quality or reviewer
approval. No reviewer provider runs or transmits text automatically.

```sh
bin/arw writing prepare --run-root RUN --source-id artifact.manuscript --proposal proposal.json
bin/arw writing record --run-root RUN --source-id artifact.manuscript --proposal proposal.json --request request.json
bin/arw writing record --run-root RUN --source-id artifact.manuscript --proposal proposal.json --request new-request.json --review-artifact-id artifact.review
```

The proposal schema is `Proposal` in `arw_writing.transformer`: explicit capability,
source SHA-256, author target, language, protected terms/spans, controls, generation
identity and ordered edits with character offsets. Invalid, overlapping, unchanged
or oversized candidates fail. Text is bounded to 1 MiB per source/candidate, so a
complete manuscript fits; configured detectors still score at most 64 KiB per
text. Preservation findings reference the whole source and candidate by SHA-256
(`arw.writing-preservation.v2`) instead of copying them per review dimension.
CLI proposal JSON is bounded to 2 MiB. Sources must already be accepted and their
current bytes must match their canonical manifest.

New receipts use `arw.writing-citation-bindings.v2`: source and candidate each
have an `assertions` table of UTF-8 byte offsets, lengths and SHA-256 sentence
digests, plus small citation-to-assertion indexes. The assertion sentence is
read from the retained text, so six citations in one sentence do not copy that
sentence six times. Reading validates the exact scope and digest; older
sentence-valued citation bindings remain readable with their original matching
rules. An index or digest mismatch is invalid evidence, not a semantic verdict.
Before `writing record` publishes a receipt or accepted paper candidate, it
checks the complete canonical receipt against the 8 MiB retained-source limit.
An oversized result returns recoverable `receipt_budget_exceeded` without
writing a new candidate or receipt; revise the proposal or controls and retry.

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

## Public evidence without a selected narrative

For a run without an author-selected narrative, explicitly pass
`--without-selected-narrative --manuscript-artifact-id ACCEPTED_ID`. This bounded
mode accepts retained Markdown, plain text, PDF, or an
`arw.venue-source-capsule.v2` JSON artifact. It requires an explicit accepted ID,
never silently falls back from the selected-narrative path, and rejects a run
that already has a narrative binding. It does not accept realization, judgment,
or heuristic selection options. The empirical layer remains `not_evaluated`;
source-corpus annotations do not become promoted venue patterns.

Public captures use the separate `arw.narrative-fit-public-snapshot.v1`
contract. Existing selected-narrative snapshots and report contracts retain
their versions. Replay dispatches by snapshot version and checks the accepted
event, manifest, retained content, exact profile bytes, and any actual accepted
PDF proof. The report uses `selected_narrative_status=not_selected`, null
narrative digest/version, and structural `UNKNOWN`/`not_evaluated`. It makes no
claim about an author's argument graph.

For a source capsule, `retained_source_capsule_sha256` binds the accepted capsule;
`external_reviewed_pdf_sha256` records the separately reviewed external PDF.
`manuscript_source_sha256` is null because the capsule is not the full manuscript.
A capsule's recorded page count cannot satisfy a PDF-page predicate: only
actual accepted PDF bytes supplied through `--pdf-artifact-id` are counted and
re-counted. That PDF must match the capsule's recorded external PDF digest.
Text predicates are unevaluated for capsules and PDFs; heading predicates
require actual Markdown. Plain-text literal checks remain bounded exact matches.

A historical corpus audit may use an explicitly curated profile with empty
rule lists when official rules have not been supplied. Its profile date records
curation, not verification of absent venue requirements. Reports then include
`official_requirements_status=not_evaluated` and the limit
`official_profile_requirements_not_supplied`. Empty rule lists do not constitute
an overall fit or compliance result. No historical venue rules are inferred
from a different annual venue profile.
