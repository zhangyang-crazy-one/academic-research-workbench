# Project paper narrative

ARW selects a paper's argument strategy at project startup, before an outline
or manuscript draft. The selection records a reasoned order for six argument
functions and the links from research problem to intended contribution,
supporting evidence, and a bounded conclusion. It does not freeze the result.
An unexpected result can narrow, overturn, or become the paper's contribution
without changing the strategy by stealth.

The five route names are `method_rq` (method or research-question led),
`observation_mechanism` (observation and proposed mechanism),
`resource_evaluation` (resource and its evaluation), `theory`, and `custom`.
The six functions are `problem`, `gap`, `contribution`, `argument`, `evidence`,
and `knowledge_boundary`. Their order is a reasoning plan, not a required six
chapters. For example, a method paper can introduce its target question and
method before evaluation, while an observational study can lead with a
surprising pattern and examine competing explanations. Proofs, experiments,
observations, annotation validation, and theoretical arguments are all
possible evidence. A prior hypothesis is optional, and a negative result can
be a complete contribution. Mark post hoc explanations as post hoc.

## Content-bound realization

Paper output admission uses `arw.narrative-realization.v1`. The parent accepts
`narrative-outline`, `narrative-blueprint`, and `narrative-draft` JSON artifacts
through `artifact-accept`. Each JSON record names the current narrative SHA,
the actual retained UTF-8 source path and digest, and annotated paragraph byte
spans with their own digests. Nodes carry one of the six function IDs and,
where relevant, claim, contribution, evidence, and knowledge-boundary IDs.
Blueprint records name an accepted outline artifact; drafts name an accepted
blueprint. A draft must realize each blueprint claim. A newly discovered claim
needs an explicit revision reason and human review. The content reader checks
the manuscript itself and rejects changed bytes or forged spans, including on
replay after acceptance.

New admission rejects annotations bound only to explicit Markdown ATX or
Setext headings as `narrative_heading_only`. Bind the function to its body
paragraph instead; a heading and body prose in one paragraph remain valid.
This syntax check cannot determine whether arbitrary prose actually performs
the claimed function. Historical accepted v1 events retain their original
reports and replay byte/span checks; this added admission policy does not
reinterpret their scientific review.
The `arw.narrative-fit-snapshot.v1` advisory capture and offline replay both use
the explicit `structural-v1` validator policy, preserving the original frozen
report. They still revalidate source, graph, ordering, and evidence bindings;
they do not infer trust from the snapshot's declared validation result. New
artifact, writing, and Phase 4 admission use `admission-v2`, which additionally
enforces the heading rule. This policy distinction adds no fields to old wire
records.

A survey can use `other` evidence for a documented taxonomy, cross-paper
comparison, or literature synthesis. Its source artifacts should bind the
reviewed literature or retained synthesis records, and its knowledge boundary
should describe selection, coverage, versions, and unverified source claims.
It needs no invented new experiment. Semantic support still remains unknown
until reviewed, as it does for a proof or experimental paper.

The deterministic check requires six function annotations, a connected
claim–contribution–evidence–boundary path, and the selected first-occurrence
order. Local interleaving needs an explicit reason and enters human review.
Two functions may occupy one paragraph or section; this is reported for human
review without imposing a chapter count. An accepted `narrative-check` report
under `narrative/reports/sha256/` is digest-bound to the event. Its mechanical
result can be `PASS` while its semantic support remains `UNKNOWN`; a node's
declaration that evidence supports a claim does not prove that science. If an
evidence node names an accepted evidence artifact, its retained digest is
checked. Without one, the report records `evidence_source_unknown`.

An optional accepted `arw.hypothesis-history.v1` annotation binds a claim's
declared `prespecified`, `post_hoc`, or `unknown` designation to a retained
note and span. A contradictory draft label is rejected. An unknown or absent
history stays in human review. The check cannot infer an unannotated post hoc
explanation from natural language or establish that a claimed prior note was
in fact recorded before data collection.

For new plans, `arw.narrative-plan.v2` includes three typed
`transition_anchors`. Each transition description cites a concrete planned
contribution ID, evidence form, or scope-boundary ID. Realization resolves
those references to actual nodes. Existing v1 plans and historical journal
bytes remain valid; reports mark their absent transition anchors as unknown.
These anchors identify argumentative objects and do not freeze results.

Phase 4 assignments that produce paper output declare a frozen
`paper_output_role` (`outline`, `blueprint`, or `draft`); their proposed output
artifact declares the same role and carries the realization. A paper-body
assignment must select `draft` at preparation. The writing revision service
also requires an accepted, exact human review binding before recording
accepted paper prose. ARW controls these admission paths; an arbitrary ARS
inline file write outside the control plane is not automatically intercepted.

## Startup and handoff

From the project root, initialize the existing ARW project identity if needed,
register the paper scope, and select a validated plan:

```sh
bin/arw memory init-project --project-root PROJECT --project-id project.example
bin/arw narrative register --project-root PROJECT
bin/arw narrative select --project-root PROJECT --plan plan.json
bin/arw narrative status --project-root PROJECT
bin/arw narrative trail --project-root PROJECT --json
bin/arw init --run-root PROJECT/RUN --request init-request.json --task-kind paper --project-root PROJECT
```

`plan.json` uses `arw.narrative-plan.v1`. One illustrative strategy is:

```json
{
  "schema_version": "arw.narrative-plan.v1",
  "route": "resource_evaluation",
  "rationale": "The resource itself is the contribution, so evaluation must follow its definition.",
  "problem_to_contribution": "A documented resource gap motivates a reusable annotated corpus.",
  "contribution_to_evidence": "The corpus design is tested through annotation validation and task evaluation.",
  "evidence_to_conclusion": "Quality and task results support only the measured uses and populations.",
  "scope_boundary": "Unmeasured domains and downstream deployments remain outside the claim.",
  "function_order": ["problem", "gap", "contribution", "argument", "evidence", "knowledge_boundary"],
  "evidence_forms": ["annotation_validation", "experiment"]
}
```

The project must be a real directory and the paper run must be inside it. The
first selection is version 1. A second `select` cannot replace it. `status`
returns `selected` with the current snapshot, `pending_change` with the same
current snapshot and a proposal digest, `missing_selection` after registration,
or `not_applicable` for a project without paper registration. Invalid or
incomplete history fails as `corrupt_history`; it is not interpreted as an
empty plan. The append-only file is `.arw/narrative/events.jsonl`. Preserve it
with the project and do not hand-edit or regenerate it from an agent summary.

Read `status` at every agent dispatch and session resume, and bind the returned
version and SHA-256 to the task context. `init --task-kind paper` requires the
selection and binds the run to its project/version. A run started but not yet
prepared for Phase 4 can prepare from the then-current selection. Phase 4
assignments prepared under an older version are immutable; after an approved
change their attempt, dispatch, and admission fail as stale. Start a new paper
run and prepare fresh assignments for the new version. The old run and history
remain available for audit. A non-paper run uses `--task-kind other`
and needs no paper registration or narrative plan. General literature review,
code, and administrative work should not be mislabeled `paper` merely because
they belong to a research project.

The machine checks apply at ARW paper startup and its controlled service,
assignment, writing, handoff, and resume operations. A direct ARS inline paper
request must follow the bundled skill protocol and enter through ARW paper
startup before outlining or drafting. ARW does not intercept arbitrary file
writes by an agent that bypasses its control plane; use the paper run for work
that needs a verified project narrative.

In ARS, the chosen route guides Phase 2's `Paper Outline + Evidence Map`, then
Phase 3's `Argument Blueprint` and CER links, then drafting. `ars-plan` asks
enough to choose the route; `ars-outline` loads it before outlining. CARS is
available for the introduction, while the six functions can occur across any
section arrangement. The ARW adapter protocol at
`skills/academic-research-suite/codex/references/project_narrative_protocol.md`
explains how this selection supersedes unsuitable vendored example counts for
sub-arguments, heading length, and paragraphs.

## Deliberate changes

When new evidence makes the chosen exposition inappropriate, prepare a new
complete `plan.json`, explain why, and submit against the currently selected
digest:

```sh
bin/arw narrative propose --project-root PROJECT --plan revised-plan.json \
  --expected-sha256 CURRENT_SHA256 --reason "Why this strategy must change"
bin/arw narrative approve --project-root PROJECT \
  --proposal-sha256 PROPOSAL_SHA256 --author-id AUTHOR_ID --author-confirmed
bin/arw narrative status --project-root PROJECT
```

Only an explicit author decision should invoke `approve`. The required
`--author-confirmed` flag is the operator's declaration that the author has
approved this exact proposal. `--author-id` records the claimed author identity;
the CLI does not independently authenticate either declaration. A pending
proposal does not change the active plan. Approval appends a new
version, retaining the previous choice, reason, and proposal in history.
Concurrent selection, an old expected digest, or an old proposal fails rather
than silently replacing a newer choice. Agents should show the author the
proposed plan and reason before approval, then reload the new snapshot. A stale
agent or plan cannot treat its earlier digest as current.

If an author explicitly abandons a pending replacement without choosing a
successor, record that decision against the exact proposal:

```sh
bin/arw narrative withdraw --project-root PROJECT \
  --proposal-sha256 PROPOSAL_SHA256 --author-id AUTHOR_ID \
  --reason "Why this proposal was withdrawn" --author-confirmed
bin/arw narrative trail --project-root PROJECT --json
```

Withdrawal leaves the selected plan active and allows a later independent
proposal. The flag is an operator assertion of author confirmation, not
independent identity authentication. A proposal awaiting approval or
withdrawal has `unknown` disposition; the trail does not guess the outcome.
The complete current event chain is checked before exporting even an old view:

```sh
bin/arw narrative trail --project-root PROJECT --json \
  --at-sequence 2 --expected-head-sha256 CURRENT_HISTORY_HEAD
```

For one explicitly named paper run, `--run-root PROJECT/RUN` adds accepted
artifact event references and explicit artifact or memory successor links from
that run's validated journal. It cannot be combined with `--at-sequence`,
because current run records would misrepresent an old project view.

The export includes the original plan, its recorded rationale, event sequence
and digest, any explicit proposal or withdrawal reason, and successor links.
`change_reason` records why a plan was adopted; `supersession_reason` records
the later proposal that replaced it. The claimed author confirmation is a
separate source. `current_choice_ids`, `abandoned_choice_ids`, and
`unresolved_questions` are derived on read. Paper handoff and resume expose a
smaller `narrative_trail` summary with the same current and abandoned routes;
history alone never makes an abandoned route a suggested next action. A
non-paper project with no narrative registration returns `not_applicable`.

The journal remains the authority. The trail never writes a second ledger or
infers an author's motive from a commit diff. Plan fields and transition
anchors are declared argumentative objects; they do not establish accepted
artifact provenance or scientific support. Run relations are identified as
run-scoped and are not attributed to a route unless a canonical binding says
so. History is capped at 1 MiB; the trail rejects more than 128 choices,
128 run relations, or 64 KiB of output with
`trail_limit_exceeded`. Invalid sequences, stale expected heads, and damaged
history fail explicitly rather than returning an empty trail. Synthetic tests
exercise these states; a ten-entry public author-record pilot has not been
measured and must not be inferred from those fixtures.
