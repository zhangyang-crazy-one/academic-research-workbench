# Task 3.2 — source-preserving strategy assessment (2026-10-23)

Status: not implemented; no strategy selection or independent review claimed.
Source: frozen revision 3, linked to unchanged v2 scientific answers via
`evidence/round3/mechanical.json`. The round3 coordinate table and rule diff are
repairs inside the original explanation, not three strategy candidates.

| Strategy | Available source facts | Required implementation / missing input |
| --- | --- | --- |
| Instance walkthrough | Ordered red/blue lookup and exact sum; once-only init, increment, found/missing alternatives and bound; bird/penguin counterexample and guard | Add a view contract referencing component/step IDs and source states, then draw a single concrete object through those steps. Representation and constraint need no new scientific facts. A loop trace must explicitly select a synthetic observation sequence (for example two missing responses); the bound's consequences can be derived, but a selected trace must be declared and bound rather than presented as an observed experiment. |
| Controlled contrast | Constraint has a sourced before/after rule with a single added guard. Loop has sourced alternative observation outcomes and complementary predicates | Constraint supports an analytic rule comparison now. Loop supports a truth-table comparison under fixed attempts, if labeled analytic, without inventing an experiment. **Representation has only one fixed input `[red, blue]`, one frozen embedding and one summation rule.** It supplies no author-defined alternative input/mask/operation and corresponding expected output under held-constant settings. Comparing lookup to sum or red to blue is not by itself a controlled change of the method. Need a source amendment naming the changed factor, control/treatment inputs or operations, held-constant facts, exact expected outputs and analytic/synthetic status. No alternative is silently invented here. |
| Overview + expansion | Every object chain, typed relation and innovation's sourced steps are available | Add a compact chain with a detail panel linked to the *same* innovation ID and its exact ports/steps. The compact and expanded references need explicit view identities; the current IR requires exactly one cell per component, so moving the existing rows is insufficient. No new science is needed. |

Implementation sequence for a complete 3.2 packet:

1. Extend the IR with bounded strategy/view references (same source digest;
   separate view IDs; step/port references checked against facts). Keep detailed
   SVG rendering separate from scientific truth. Reject unsupported contrasts.
2. Add fixed manual layouts for the three distinct explanatory grammars above.
   Permit overview/detail references to the same semantic component without
   cloning an object identity or dropping its detailed expansion.
3. Obtain the precise representation contrast declaration above; explicitly bind
   any selected synthetic loop trace and analytically computed branch outcomes.
   Preserve v3 bytes/SHA when making any source amendment.
4. Render 3 strategies × 3 tasks, retain identical scientific source bindings
   for each task, mechanical checks and real PNG/PDF outputs. Do not substitute
   color or row/column permutations for a different explanation.
5. Supply all candidates to the main agent's separate pixel/reference reviewer;
   retain reasons for any selection and outstanding findings. Human acceptance
   and publication qualification remain separate and pending.

This repair does not change the existing `candidate_exception` statement or mark
3.2 complete. A source-grounded subset is feasible, but the requested full set of
three strategies across the three samples cannot honestly claim a representation
control/treatment from the currently frozen facts.
