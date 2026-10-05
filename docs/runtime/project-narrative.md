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

## Startup and handoff

From the project root, initialize the existing ARW project identity if needed,
register the paper scope, and select a validated plan:

```sh
bin/arw memory init-project --project-root PROJECT --project-id project.example
bin/arw narrative register --project-root PROJECT
bin/arw narrative select --project-root PROJECT --plan plan.json
bin/arw narrative status --project-root PROJECT
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
