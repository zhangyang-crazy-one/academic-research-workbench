# New-evidence impact and local-revision pilot

This small **advisory composition** produces a reviewable affected claim, plan,
experiment, and paragraph list. It does not introduce a kernel, journal, truth
engine, or automatic invalidation path. It never revokes, admits, or overwrites
accepted outputs. Support withdrawal is a reason to review remaining support,
not proof that a conclusion is false.

## Run

From a development checkout with dependencies installed:

```sh
.venv/bin/python scripts/run-evidence-revision-pilot --output /tmp/revision-report.json
PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_evidence_revision.py
```

The output filename must not already exist. The runner creates only a temporary
disposable graph and a new report. It exits nonzero if the labeled pilot fails.
The retained example is
[`../evidence/evidence-revision/public-report.json`](../evidence/evidence-revision/public-report.json).
The public input and labels are `evals/evidence_revision/public.json`.

## Composition and review contract

`arw.evidence_revision.impact_checklist` takes the existing `GraphStore`, a
caller-declared `EvidenceUpdate`, an expected ledger watermark, and optional
reviewer-supplied candidate text. Integrators must supply graph records from
original-validated manifests and the current authoritative watermark. A graph
is a disposable projection, not proof of scientific support. This pilot uses
explicit synthetic records, not a real accepted research run.

- Existing `trace_source` queries obtain one node and its bounded relationships.
  The composition follows incoming dependency edges only. Generic trace walks
  both directions, which would wrongly pull in sibling claims sharing another
  source. Supported links are `supported_by`, `derived_from`, `uses_experiment`,
  `uses_dataset`, `uses_figure`, and `supersedes`.
- The existing intake `VersionedReading.affected_records` convention supplies
  explicit additional record IDs. Integrators can copy those IDs from the
  literature intake upgrade report into `EvidenceUpdate.affected_records`.
  The pilot exercises that bridge; it does not change intake acceptance.
- Claims and experiments retain existing graph types. Plan/paragraph artifacts
  require explicit `revision_kind` attributes. There is no prose classification.
- Every candidate retains its current payload digest as a proposed `supersedes`
  target, original text, reviewer text if supplied, and a decision trace with
  the update ID and first dependency path. This is a report-local explanation,
  not a new accepted decision event or a grant of revision authority.
- No relation label bypasses tracing. Even `irrelevant` updates traverse declared
  dependencies, avoiding an operator label silently suppressing real links.
- Unrelated proposals are reported as `unapplied_proposals`. No replacement text
  is invented. Missing candidate text means review work remains.
- Missing/corrupt/stale projections, missing declared records, budget exhaustion,
  or generation changes produce `incomplete`, never an empty success. Any partial
  candidates remain advisory. Query counts include failed and final anchor reads.
- A later actual revision must use the existing author/parent admission and
  immediate-predecessor checks. Revalidate the authoritative state then. A saved
  checklist is not authorization and cannot ensure the ledger stays unchanged
  after it returns.

## Two update rounds and measured result

The synthetic fixture has two research branches, each with a claim, plan,
experiment, and paragraph. They share an auxiliary source with an unrelated
claim, making undirected over-revision detectable. A separate plan is linked
only through `affected_records`.

1. Additional support for alpha and counterevidence for beta: eight affected
   records.
2. Withdrawal of alpha support plus the explicitly linked plan, new beta
   support, and an unrelated update: nine affected records, zero for the
   unrelated update.

The candidate snapshots from round one remain retained. Round two recomputes
against unchanged accepted records, rather than treating unaccepted candidate
text as current truth. Reusing round-one candidates gives **nine stale/missing
candidate errors** against round-two labels. The current two-round run records:

| Measure | Value | Meaning |
| --- | ---: | --- |
| Required revision pairs | 17 | Sum of update-record labels, not distinct records |
| Missed required revisions | 0 | Required IDs absent from candidate list |
| False revisions | 0 | Candidate IDs not labeled required |
| Stale candidate errors | 0 | Missing or nonmatching scripted candidate text |
| Accepted stale items pending review | 17 | No accepted output was revised |
| Local graph queries / rows | 27 / 27 | Includes final generation rechecks |
| Local graph response bytes | 26,250 | Serialized query results, not network bytes |
| External retrieval calls | 0 | No source retrieval path executes |
| Model calls / input / output tokens | 0 / 0 / 0 | No model path executes |

The report carries the fixture and accepted-record hashes and each update's
checklist, costs, scores, and predecessor-candidate comparison. A read-only test
also compares all graph files byte-for-byte before and after composition.

## Limits and negative controls

This is a **public deterministic routing test**, not a hidden-answer benchmark,
independent scientific assessment, or demonstration of autonomous paper repair.
Text and relations are scripted reviewer inputs. Labels are consumed only by
the scorer, not the traversal, but both remain public and deliberately simple.
Zero candidate text errors means the supplied text was routed correctly, not
that a model discovered a valid scientific correction. Accepted stale-item
counts are label-based pending-review counts, not verified errors in a real paper.

Tests remove a required dependency and observe eight misses across two rounds;
inject missing, false, and stale candidates and observe nonzero scores; exercise
stale/corrupt/missing graphs, budget limits, cycles, `supersedes`, generation
changes, irrelevant labels with actual links, and preservation of unrelated
conclusions and graph bytes. Unregistered semantic dependencies, untyped artifact
roles, or misleading operator labels remain outside demonstrated coverage.
Runtime wall time, external retrieval quality, real-model token budgets,
scientific correctness, accepted-output correction quality, and large-graph
scaling are not measured. Local retrieval is explicitly nonzero; zero model and
external costs apply only to this no-call pilot.

Reruns preserve routing, text, scores, and cost counts. The existing graph store
assigns a fresh generation ID and corresponding manifest hash to each temporary
graph; those two provenance fields intentionally differ between runs. They are
retained in reports rather than replaced with synthetic stable identifiers.

Malformed/non-object trace attributes, missing or unknown artifact roles (including
list/dict roles), and non-string or blank original/reviewer text fail closed as
`incomplete`. The malformed record is not emitted as a candidate. Artifact roles
are restricted to `plan` and `paragraph`; claim/experiment roles come only from
the corresponding graph entity types. Omitting reviewer text is allowed and
still requires human review, but explicitly supplying null or malformed text is
not treated as an omitted proposal.
