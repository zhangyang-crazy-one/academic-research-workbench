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
Statistical detector status is `unsupported`, with no detector/model/key configured.
Metric changes never establish watermark absence, human authorship or meaning.

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
