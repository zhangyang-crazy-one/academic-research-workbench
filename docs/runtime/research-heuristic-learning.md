# Governed research learning

## Venue evidence extension

`arw learn observe-venue --project-root PROJECT --run-root RUN --artifact-id ID --request REQUEST.json`
projects an accepted `arw.venue-exemplar.v1` or `arw.venue-outcome.v1` artifact
into the ordinary append-only learning observation event. An exemplar annotation
must reference separately accepted source bytes by ID and SHA-256 and a prior
accepted `arw.venue-source-review.v1` that binds the URL, DOI, category, year,
source hash, access basis, and reviewer. Full-text
annotations locate each of the six argument functions; metadata-only records
cannot claim structural or empirical patterns. An outcome must bind retained
evidence bytes, the narrative digest/version selected for its originating
paper run, and any named historically promoted and used heuristic IDs.

An accepted `arw.venue-evidence-policy.v1` can be selected through the existing
project learning configuration. It names the exact exemplar observations for
review. Each accepted `arw.venue-evidence-sample.v1` classifies one as supporting,
counterexample, or unknown with reviewer and rationale. The v2 receipt records
all counts and fails qualification when counterexamples are at least supporting.
Existing `arw.learning-policy.v1` policies continue to use mean delta.

`arw learn applicable --input CONDITIONS.json --venue-id VENUE --domain-id DOMAIN`
returns only promoted lessons matching the requested fit and existing task
conditions. It includes approved scope and venue evidence counts. The caller
may show these as Phase 2 suggestions; no narrative or official venue rule is
changed. Quantity guidance is descriptive, explicitly nonmandatory, and must
name exceptions and what counterexamples still need inspection.

`arw learn phase2-advisories --project-root PROJECT --run-root RUN --input
CONDITIONS.json --venue-id VENUE --domain-id DOMAIN` is the paper-only Phase 2
read interface. It binds the selected narrative version/digest, includes the
sorted promoted advice and its deterministic set hash, and leaves both the
narrative and run journal unchanged. A run whose startup selection became
stale cannot use this interface. Historical venue outcome observations can
still cite that run's authentic earlier narrative selection.

For an ARS Phase 2 handoff, run the query from the current paper run and retain
its returned JSON with the outline task context:

```sh
bin/arw learn phase2-advisories --project-root PROJECT --run-root RUN \
  --input CONDITIONS.json --venue-id VENUE --domain-id DOMAIN \
  > phase2-advisories.json
```

The outline reviewer checks the returned narrative digest against current
`narrative status`, preserves the advisory-set hash, and treats every item as
optional context. Empty `items` means no approved matching lessons, even when
the project has evaluated candidates. It does not authorize importing those
candidates as advice.

The existing ARS planner also consumes this interface directly for
`ars-plan`, `ars-outline`, or academic-paper full routing. Use an interpreter
with the current ARW wheel and research-learning extension. In a source
checkout, explicitly use the current source paths rather than an older
editable installation. Run this example from the repository root:

```sh
PYTHONPATH="$PWD/src:$PWD/extensions/research-learning/src" .venv/bin/python \
  skills/academic-research-suite/codex/scripts/ars_codex_full_runtime.py \
  ars-outline --arw-project-root PROJECT --arw-run-root RUN \
  --venue-id VENUE --domain-id DOMAIN --applicability-file CONDITIONS.json
```

The opt-in output carries `phase2_venue_context` with the exact applicability
bytes hash and governed advisory snapshot. The structure architect's
`task_context` receives that same context when agent-team planning is enabled;
inline Phase 2 consumes the top-level context. Before dispatch or outlining,
reload the narrative status and reject stale context. The planner reads and
hands off suggestions; it does not execute agents, accept output, promote
candidates, or change the narrative. Missing/partial options, stale selection,
wrong project/run binding, and unrelated workflow routing fail explicitly.
Calls without these options retain the original plan JSON shape. A provider
without the Phase 2 API fails as `CapabilityUnavailable`; the context records
runtime source locations for inspection. This setup changes no trust settings,
installs no provider, and invokes no model. The actual CLI governance tests use
an explicitly approved synthetic paper fixture. The fourteen-source research
corpus has no author-selected paper narrative and cannot supply this context;
these tests grant no production adoption or promotion.

`arw learn legacy-style-drafts --project-root PROJECT --input PROFILE.json`
exports old `style_learning` exemplar, consensus, and artifact notes as
unverified drafts. The output contains no fabricated exemplar source hash or
support count. Admit the legacy profile artifact, run `observe-venue` on its
artifact ID, then call `arw learn migrate-style-candidate --project-root PROJECT
--run-root RUN --input CLAUSE.json --request REQUEST.json`. The clause input
names the legacy observation and exact draft ID, a new heuristic ID, domain,
venue/domain applicability, and ordinary task applicability. Every migrated
clause requires a typed `legacy_guidance_review` declaring nonmandatory status,
exceptions, and counterexample needs. A separately recognized numeric range
can add typed `venue_quantity_guidance`; migration does not guess quantities
from prose. Migration records a canonical candidate with unknown
evidence and zero asserted support. It cannot evaluate or promote; a verified
successor must first bind accepted full-text exemplar observations. The existing
nine NLP examples do not satisfy a real two-domain, ten-exemplar target.

The research-learning extension provides project-scoped, evidence-bound lessons
for subsequent research decisions. Its standalone acceptance example is:

```bash
.venv/bin/python extensions/research-learning/examples/qualified_lesson.py OUTPUT
```

The example exercises canonical observation capture, manual candidate publication,
receipt-based shadow evaluation, explicit qualification, consented project
promotion, applicability matching, and an accepted author choice. Numeric inputs
are synthetic fixtures. The later decision explicitly retains an unmeasured
outcome rather than claiming an improvement.

The implementation supports six evaluator modes over accepted sample receipts,
three evidence buckets, deduplication, policy-change re-evaluation, rejection and
successor versions, opt-in activation, authorized retention, and disposable
SQLite projections. Versioned reader contracts remain in core when the extension
is absent. No memory or figure-compiler extension is required.

Tests are `tests/integration/test_research_learning.py` and
`tests/compat/test_research_learning_events.py`. They cover lifecycle behavior,
policy and scope failures, exact retries, process termination at durability
boundaries, historical byte fixtures, schema drift and import direction. The
fixture is an engineering acceptance case, not evidence of research efficacy.

See the [extension guide](../../extensions/research-learning/README.md) for CLI,
configuration, evaluation semantics and actual limits. `research-workflow-evolver`
remains a separate future change: this extension does not generate or execute a
workflow, policy, or skill.
