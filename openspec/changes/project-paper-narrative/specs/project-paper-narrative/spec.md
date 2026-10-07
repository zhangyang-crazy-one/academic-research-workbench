# Project paper narrative

## ADDED Requirements

### Requirement: Choose a reasoned paper argument strategy before output
The system SHALL require an explicit selected project narrative before
starting a paper run or producing its outline or manuscript prose. The plan
SHALL identify a route, explain its fit, order all six argument functions,
connect problem, intended contribution, evidence and bounded conclusion, and
name acceptable evidence forms. The functions SHALL NOT imply six required
chapters. The plan SHALL NOT lock an empirical finding or scientific conclusion.

#### Scenario: First paper startup
Given an initialized project and a selected validated plan, when a paper run
starts inside the project, the run records the project identity and selected
version/digest. Phase 2 receives that plan before producing an Outline and
Evidence Map.

#### Scenario: Paper startup with no selection
Given a registered paper project with no selected plan, when a paper run or
paper-writing operation starts, it fails with `missing_selection` and emits no
paper output.

#### Scenario: Different contribution types
A method or RQ-led paper, observation and mechanism paper, resource evaluation,
theoretical paper, or justified custom paper can each choose a suitable order.
Proofs, experiments, annotation validation and other justified evidence forms
are accepted. A plan need not contain a hypothesis, and a negative result is
not rejected for lacking a positive effect.

### Requirement: Preserve one current project choice across agents and sessions
The system SHALL replay the canonical project history at paper entry,
dispatch, handoff, and resume, and SHALL expose one selected version and digest
to every connected agent. A worker's stale assignment or plan SHALL NOT
silently replace the selected version. Missing, conflicting, and corrupt
states SHALL be distinct.

#### Scenario: Second startup and agent switch
Given a selected version, a second paper startup and a different agent load
the same current project version and digest. They do not infer a new strategy
from their prompts or conversation summaries.

#### Scenario: Resume after approved change
Given a run prepared for Phase 4 under an earlier valid selection and a later
approved version, resume checks against the current version. The old assignment's
attempt, dispatch, and admission are rejected. A new paper run with fresh
assignments uses the approved version; the old run remains audit history.

#### Scenario: Damaged journal
Given an incomplete, noncanonical, identity-mismatched or hash-mismatched
history, the system reports `corrupt_history` and does not treat it as an
unregistered project or silently rebuild it.

### Requirement: Change only through an exact author-approved version
A proposed replacement SHALL include the current digest and a nonblank reason.
It SHALL remain inactive until a separate approval records the author's
decision against the exact proposal digest and requires an explicit operator
declaration that the author confirmed it. The declaration does not establish
independent identity authentication. Approval SHALL append history and
advance the version once. A concurrent or stale action SHALL fail visibly.

#### Scenario: Pending proposal
After proposal, status is `pending_change` and all current paper work still
uses the previously selected version.

#### Scenario: Concurrent selection or stale proposal
If two agents attempt the first selection, only one succeeds. If an agent
proposes against an old digest or approves an obsolete proposal, it receives a
conflict and cannot overwrite the current selection.

### Requirement: Reuse ARS argument artifacts without forcing a template
The ARS adapter SHALL apply the selected strategy to Phase 2 Outline +
Evidence Map, Phase 3 Argument Blueprint/CER, and Phase 4 drafting. CARS may
organize an introduction. Vendored 3–5 sub-argument, 150-word heading, and
three-paragraph section examples SHALL NOT be mandatory when inappropriate
for the contribution or venue. Evidence, uncertainty and scope SHALL remain
traceable. Post hoc explanations SHALL NOT be presented as pre-specified
hypotheses.

#### Scenario: Compact proof or negative result
A short proof with one central lemma, or a negative result with limited
evidence, may use the number of claims and paragraphs needed for a coherent
case. Its evidence limits and knowledge gain appear in the map and blueprint;
padding solely to satisfy example counts is not required.

### Requirement: Keep non-paper work compatible
The system SHALL allow general research, code, review, and administrative runs
without registering or selecting a paper narrative. A non-paper run SHALL NOT
carry a paper narrative binding.

#### Scenario: General task startup
Given an unregistered project, a run marked `other` starts under its ordinary
contract and narrative status remains `not_applicable`.
