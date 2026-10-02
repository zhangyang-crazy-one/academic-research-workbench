# Project paper narrative protocol (ARW adapter)

Use this adapter rule for an ARW project registered for paper writing, including
`ars-plan`, `ars-outline`, `academic-paper` Phase 2/3/4, and a later agent or
resumed session. The canonical record is the project narrative history, not a
conversation summary, an agent's memory, or a draft outline. Read the current
snapshot with `bin/arw narrative status --project-root PROJECT` before planning
or writing; carry its `project_id`, `version`, and `sha256` through the handoff.
If status is `missing_selection`, choose a plan with the author before producing
an outline or manuscript prose. If status is `not_applicable`, do not impose a
paper framework on a general research or non-paper task. If history is invalid,
or an assigned snapshot differs from current state, stop that paper output and
surface the conflict. A pending proposal leaves the selected plan in force.

The six argument functions are **problem positioning**, **gap and why it
matters**, **intended contribution**, **argument path**, **evidence test**, and
**knowledge gain with scope boundary**. `function_order` orders these functions
once for the paper's contribution type; it is not a six-section template. A
chosen route (`method_rq`, `observation_mechanism`, `resource_evaluation`,
`theory`, or justified `custom`) specifies the order of exposition. Keep the
reason for that choice and the links from problem to contribution, contribution
to evidence, and evidence to bounded conclusion visible in planning. CARS can
shape the introduction, and CER can connect individual claims to evidence, but
neither silently replaces the project plan.

Phase 2 `Paper Outline + Evidence Map` maps the selected functions and actual
evidence needs to appropriate sections. Phase 3 `Argument Blueprint` develops
CER chains and objections from that approved outline. Phase 4 follows those
artifacts. `ars-plan` may ask Socratic questions to select a route; `ars-outline`
must load the selected route before outlining. Handoffs and resume reload the
current snapshot rather than reconstructing one from prior prose. An agent with
an older version must request fresh context; it cannot overwrite the project
selection.

Apply this ARW adapter rule when a vendored ARS example assumes a universal
IMRaD order, exactly 3–5 sub-arguments, at least 150 words under every heading,
or at least three body paragraphs per section. Those counts and structures are
examples for suitable papers, not admission requirements. Choose the number of
claims, headings, and paragraphs needed to make the actual contribution and
evidence legible, subject to a real target venue's requirements. Keep CARS,
CER, and evidence traceability where applicable. A formal proof, experiment,
observation, annotation validation, theoretical argument, or a justified other
form can support a claim. A hypothesis may be absent. Negative or null results
can be the contribution; never recast an explanation devised after seeing
results as a pre-specified hypothesis. The plan fixes argumentative *method*
and presentation order, never facts, findings, or scientific conclusions.

An author-directed change requires a reason, a proposal against the current
`sha256`, and explicit approval of that exact proposal. Until approval, agents
keep the selected plan. The operator uses `approve --author-confirmed` to
declare that the author confirmed that exact proposal; the flag and author ID
do not independently authenticate the author. After approval, reload the
incremented version before generating new paper output. A run already
prepared for Phase 4 has
immutable assignments carrying the old snapshot; its attempt, dispatch, and
admission reject as stale. Start a new paper run and prepare new assignments
for the new version. A run started but not yet prepared can prepare against
the then-current version. A later conclusion that narrows or rejects
the intended claim is an honest scientific update; it does not by itself change
the narrative method. If the method truly no longer fits, propose a versioned
change and explain why.
