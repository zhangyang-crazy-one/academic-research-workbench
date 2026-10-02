# Design: stable project paper narrative

## Authority and lifecycle

The project `.arw/project.json` provides stable identity. Paper registration
creates `.arw/narrative/events.jsonl`; first selection records a validated
`arw.narrative-plan.v1`. Every event has project identity, sequence, version,
previous digest, and its own digest over canonical bytes. The selected
snapshot is the replayed projection; a proposal cannot become current until
an exact author-confirmed approval event names it. A per-project lock protects
read-modify-write, and a compare-and-swap expected digest rejects stale plans.
Do not reconstruct a missing or corrupt journal from agent notes.

`not_applicable` means no paper registration. `missing_selection` means the
paper project has been registered but cannot start paper planning or writing.
`selected` has an active snapshot. `pending_change` still exposes that active
snapshot plus the pending proposal digest. Invalid history is an error, not a
new-project state. A stale version or conflicting proposal is rejected.

The plan has `route`, `rationale`, three relationship statements
(`problem_to_contribution`, `contribution_to_evidence`,
`evidence_to_conclusion`), `scope_boundary`, `function_order`, and
`evidence_forms`. It deliberately contains no frozen hypothesis, finding,
effect size, or conclusion value. The six functions each appear once in
`function_order`; the order is not a chapter schema. Hypothesis-driven,
observational, resource evaluation, theoretical, and custom plans remain
possible, as do formal proof, experiment, observation, annotation validation,
theoretical argument, and justified other evidence.

## Runtime integration

`init --task-kind paper --project-root PROJECT` must load the current project
snapshot and bind the run to its project ID, version and digest while the
project read lock is held. The run must be inside the project. Current paper
operations reload the selected snapshot at entry and compare any carried
digest. The lock stays held through a write-sensitive operation so an approval
cannot race it. Handoff and resume also reload current state; they do not
accept stale assignment or plan context. A run prepared for Phase 4 carries
the complete snapshot in immutable assignments. After approval advances the
project version, that run's old attempt, dispatch, and admission are refused;
the author starts a new paper run and prepares new assignments. A run started
but not yet prepared may prepare from the then-current version.
`--task-kind other` bypasses paper
registration and cannot carry a paper binding.

This boundary belongs to the ARW kernel and command path, not a Codex hook or
model prompt. The ARS router and role adapter provide human-readable guidance
for structure selection. Phase 2 maps functions to Outline + Evidence Map;
Phase 3 maps the outline to CER Argument Blueprint; Phase 4 drafts from those
artifacts. CARS remains an introduction technique. The adapter overrides
vendored example counts (3–5 sub-arguments, 150 words beneath every heading,
three body paragraphs per section) where they would force padding or distort
the chosen contribution. A venue's actual format requirements still apply.
Machine validation covers ARW paper startup and its controlled service,
assignment, writing, handoff, and resume paths. Direct ARS inline paper work
must follow the skill protocol into ARW paper startup. There is no global file
write interceptor for an agent that bypasses ARW's control plane. Non-paper
work remains available under `--task-kind other` without paper registration.

## Change protocol and limits

An agent can propose a new complete plan only with a reason and the current
digest. Approval must name the exact proposal, record an author ID, and require
the operator's `--author-confirmed` declaration before incrementing the
version. The CLI records these assertions; the host must collect the real
author decision and cannot claim independent identity authentication. The
proposal remains inactive until approved. Past versions
stay replayable. Scientific updates that revise or narrow the conclusion need
not change the narrative method; if the method itself changes, use this
versioned protocol. An explanatory hypothesis formed after results must retain
its post hoc status.
