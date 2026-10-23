# Independent mechanism figure review — round 2

Status: human_pending. Advisory only. Publication approval: false. Last budgeted round.

## Original findings

- **R1-TITLE-WRAP**: resolved. Normal representation now wraps before vector.; normal tool-loop now wraps before retry or stop. Neither original claim breaks inside those words. A new edge-label wrapping issue is recorded separately as R2-EDGE-WRAP.
- **R1-EDGE-LABELS**: partially_resolved. lookup, sum, call, observed, retry, stop, counterexample, guard now appear beside source exits. The tool-loop continue/stop predicates appear as separate nearby boxes. Typed payloads remain in the distant bottom list. Retry and stop predicates are inside a shared decision card and do not have short direct links to their respective ports. Their left/right box placement does not itself identify the top/bottom exits. New counterexample wrapping issue is separate.
- **R1-REPRESENTATION-PRIMITIVES**: partially_resolved. Actual PNG now has named red->e_red and blue->e_blue rows, three sequential operation boxes, and a side-by-side before/after state. One-hot coordinates, axis-wise summation and output are still text lines. There is no visible matrix/coordinate sum showing how output coordinate 1 receives one count from red and coordinate 2 from blue. No content was omitted; residual is visual explanatory depth.
- **R1-CONSTRAINT-DIFF**: partially_resolved. Before/after states are now paired, and retain/exclude/unknown operations are three separate boxes. Retained fact and newly added not penguin predicate still have identical visual treatment; changed guard is not isolated within an aligned before/after expression. Unknown state is explicitly stated in text and not contradicted.
- **R1-LOOP-COUNTER-SOURCE**: resolved_by_explicit_source_revision. Normal tool-loop now visibly gives attempts=0 and answer_present=false, increments attempts before request, allows found or missing, and sets answer_present from observation. One-time initialization versus retry scope remains a diagram reading ambiguity recorded as R2-INIT-SCOPE, not a missing source-counter rule.

## Normal new/residual findings

### R2-EDGE-WRAP — readability / medium

- **affected_ids**: constraint:edge-label.counterexample, constraint:edge.counterexample
- **source_requirement**: The retained counterexample relation must be identifiable in the actual pixels at the 180mm/8pt minimum profile.
- **pixel_observation**: The new right-side label breaks counterexample as countere / xample. Its second line lies at the level of the blue outgoing horizontal segment; the route passes immediately through/along the second-line region.
- **difference**: Local labeling fixes the earlier remote legend problem but introduces a narrow-gutter word split and line/label collision risk. Body text and claim remain readable.
- **recommendation**: Provide enough label width or route a reserved label area above/below the segment; keep the entire edge name intact.
- **pass_condition**: Actual PNG shows counterexample as an intact word without line through its text bounds, clipping or collision.
- **uncertainty**: The pixel overlap is localized to the right gutter. This is not a finding of missing semantics or an arrow reversal.

### R2-INIT-SCOPE — readability / medium

- **affected_ids**: tool-loop:request, tool-loop:label.request.2, tool-loop:label.request.3, tool-loop:edge.retry
- **source_requirement**: The explicit source amendment defines initial attempts=0, then increments attempts before each request; retry must retain the same observed episode, including accumulated attempts.
- **pixel_observation**: The request card displays Initial state: attempts=0 ... as numbered step 1, followed by a down arrow to Increment attempts... as step 2. Retry enters the same enclosing request card; no once-only marker or bypass separates initialization from repeated execution.
- **difference**: The wording Initial state supports the intended once-only interpretation, but the new sequential-box grammar also permits reading initialization as part of each request invocation. Under that unintended reading the no-answer counter would be reset; actual implementation nontermination has not been demonstrated.
- **recommendation**: Distinguish a one-time incoming initial-state annotation from the repeatable increment/request operation, or explicitly mark step 1 once and route retry to step 2.
- **pass_condition**: A reader can trace two missing results to attempts=1 then attempts=2 without traversing a reset step, and can identify the bounded stop condition.
- **uncertainty**: This is a semantic reading ambiguity, not a confirmed scientific_error: source wording says Initial state and does not explicitly instruct resetting on retry. Do not count this as a normal-figure confirmed science false positive.


## Blind cases: actual pixel differences

### R2-BLIND-1 — necessary_content_omission / high

- **affected_ids**: case-1:label.project.3, case-1:project
- **source_requirement**: representation project.steps[1] explicitly requires Lookup X=[E(red), E(blue)].
- **pixel_observation**: The central operation sequence reads 1. E(red)=[1,0]; E(blue)=[0,1]. / 2. Step omitted. / 3. Sum sequence axis: y=[1,1].
- **difference**: The actual lookup that forms the sequence representation is absent, replaced by an omission placeholder. Token names and final vector remain present.
- **recommendation**: Restore the source-specified lookup step; preserve the given input order.
- **pass_condition**: Case pixels show the concrete lookup expression rather than Step omitted., with its position between embedding definitions and summation.
- **uncertainty**: Top-level claim still names lookup, so the whole concept has not vanished. The necessary internal transformation is specifically omitted.

### R2-BLIND-2 — scientific_error / high

- **affected_ids**: case-2:edge.call, case-2:request.out, case-2:observe.input
- **source_requirement**: tool-loop relation call is action request.out -> observe.input and carries the lookup request and arguments.
- **pixel_observation**: The orange route has its arrowhead at the request card right-side call port, pointing back into request; the observe card left-side port has no receiving arrowhead. SVG edge.call point order independently confirms the reverse path.
- **difference**: The action direction is reversed relative to the frozen answer although the labels and card order still imply request then observation.
- **recommendation**: Restore request-to-observe routing and the arrowhead at observe.input.
- **pass_condition**: The actual orange route departs request.out and terminates with an arrowhead at observe.input.
- **uncertainty**: This is an arrow direction defect, not a claim that the separately visible gray feedback route is itself reversed.

### R2-BLIND-3 — scientific_error / high

- **affected_ids**: case-3:label.project.6, case-3:project.out, case-3:result.input
- **source_requirement**: representation must retain the utterance identity: project.out object_id=utterance,state=sum and result.input the same identity/state.
- **pixel_observation**: The central output line reads output out: vector2 / unrelated@sum, while the final card receives vector2 / utterance@sum and says retain the utterance identity.
- **difference**: The producer output identity changes to an unsupported unrelated object and breaks continuity across sum even though the numeric vector remains [1,1].
- **recommendation**: Use utterance@sum consistently at project output and result input.
- **pass_condition**: Actual pixels show matching utterance@sum on both sides of the sum connection.
- **uncertainty**: No alternate unrelated object is defined in either frozen v1 or revised source; the identity change is not supported.

### R2-BLIND-4 — readability / medium

- **affected_ids**: case-4:label.decide.4, case-4:decide
- **source_requirement**: tool-loop stop condition is explicitly answer_present OR attempts >= 2; its role as stopping must remain unambiguous.
- **pixel_observation**: The right predicate box says removed: answer_present OR attempts >= 2 instead of identifying it as stop. A stop edge label and the complete stop condition in the bottom relation list remain visible.
- **difference**: The stopping role is replaced by an unsupported removal annotation in the decision panel. The condition itself has NOT been fully deleted: its expression and a remote stop association remain. This supports a labeling/conflicting presentation diagnosis, not a claim of wholesale predicate omission.
- **recommendation**: Restore the stop role in the local decision box and remove the unsupported removed annotation.
- **pass_condition**: The local predicate is explicitly labeled stop and agrees with the surviving stop edge/bottom relation.
- **uncertainty**: Without injection truth, this is classified as role-label corruption/readability. It may be intended as an annotation, but no source authorizes a removal operation. No blind ground-truth category is inferred.

### R2-BLIND-5 — scientific_error / high

- **affected_ids**: case-5:label.project.4, case-5:project, case-5:result
- **source_requirement**: representation sums E(red)=[1,0] and E(blue)=[0,1] along sequence axis to y=[1,1].
- **pixel_observation**: The third operation box says Sum sequence axis: y=[999,999]. The later after-state still says y=[1,1].
- **difference**: [999,999] contradicts both the supplied algebra and the final rendered result; no source supplies that value.
- **recommendation**: Restore the supplied sum [1,1] and ensure all displayed occurrences agree.
- **pass_condition**: The operation and final state both display [1,1], consistent with the two given one-hot vectors.
- **uncertainty**: This is not an empirical estimate with uncertainty: the task supplies exact synthetic vectors.

### R2-BLIND-6 — readability / high

- **affected_ids**: case-6:mechanism.claim
- **source_requirement**: Author-defined profile has minimum 8pt, and the synthetic claim must remain readable in actual pixels.
- **pixel_observation**: The top claim is extremely small relative to the question and all body labels; it occupies a short sliver near the upper left and cannot be read comfortably at this supplied image scale. SVG mechanism.claim font-size=2 confirms the pixel observation.
- **difference**: The main scientific summary and its synthetic qualifier are rendered far below the minimum, despite normal body text remaining readable.
- **recommendation**: Render the claim at least 8pt with adequate wrapping and height.
- **pass_condition**: Actual pixels show the entire claim and synthetic qualifier legibly at the declared minimum or larger, without clipping.
- **uncertainty**: The text has not been semantically replaced according to inspected SVG; the diagnosed defect is visibility/profile compliance, not a false scientific claim.

## Binding and limits

Normal 18/18 exact binding fields match; actual font file and project-compatible render libraries/interpreter match. v1 retention and explicit source amendment verified. Blind PNGs match 6/6; their full SVG/source/IR bindings were not supplied. Detailed evidence: `round2-binding.json`.

Normal figures: no confirmed scientific error; tool-loop initialization scope has a separately identified reading ambiguity. Blind truth was not read, so hit/miss/false-positive rates are unavailable. Role separation is not statistical independence.

Reference comparison reuses actual OpenHands ICLR2025 Fig2 and VGGT author arXiv v1 Fig2 pixels from round1; CVPR PDF version equivalence remains unverified. No repeat downloads.

Measured wall interval: 206.364 seconds. Nested tool calls: 19. Tokens/amount: unavailable.
