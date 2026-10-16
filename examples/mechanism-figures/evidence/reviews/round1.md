# Independent mechanism figure review — round 1

Status: human_pending. Publication approval: false.

Actual PNGs, frozen answers and SVG were inspected. Producer report and scores were not read. Role separation does not establish statistical independence.

## Findings

### R1-TITLE-WRAP — readability / medium

- **affected_ids**: representation:mechanism.claim, tool-loop:mechanism.claim
- **source_requirement**: The frozen claim must remain readable at the declared 180 mm profile; the words count vector and retry communicate the mechanism.
- **pixel_observation**: representation title ends its first line with vect and places or. on the next line; tool-loop title breaks retry as ret / ry. These are visible in the actual PNG, not inferred from SVG font size.
- **difference**: Characters are present, but word-internal wrapping interrupts the central claim despite unused width/space below.
- **recommendation**: Use word-aware English wrapping and explicit safe fallback only for genuinely overlong tokens; reserve an adequate claim block.
- **pass_condition**: Re-render both claims at the same profile: vector and retry each appear intact, with no clipping or overlap.
- **uncertainty**: No missing glyphs observed; this is word-wrap quality, not proof that every font/platform fails.

### R1-EDGE-LABELS — readability / high

- **affected_ids**: representation:edge.lookup, representation:edge.sum, representation:relation.lookup, representation:relation.sum, tool-loop:edge.call, tool-loop:edge.observed, tool-loop:edge.retry, tool-loop:edge.stop, tool-loop:relation.retry, tool-loop:relation.stop, constraint:edge.counterexample, constraint:edge.guard
- **source_requirement**: Frozen relations define concrete payloads and triggers; the tool-loop question specifically asks when retry and stop occur.
- **pixel_observation**: All relation descriptions sit in a detached list beneath the last card. No arrow carries its own name/payload. tool-loop has two identical gray dashed control exits on the right of decide, while the retry/stop predicate text is inside the card or far below. Mapping requires tracing a long perimeter route.
- **difference**: The graph is topologically interpretable, but branch meaning is not spatially attached to the corresponding route. The source provides the needed labels; this is placement loss, not missing scientific facts.
- **recommendation**: Place compact retry and stop labels plus predicates beside their exits; place short typed payload labels on the corresponding data/action/observation routes. A separate details legend may remain.
- **pass_condition**: A reader looking only at decide and its outgoing routes can identify each trigger and destination without the bottom list. Other edges can be matched to payloads without full-page backtracking.
- **uncertainty**: No route-crossing defect or reversed arrow was observed. Severity reflects the central comprehension task, not a generic prohibition on legends.

### R1-REPRESENTATION-PRIMITIVES — reference_gap / high

- **affected_ids**: representation:tokens, representation:project, representation:result
- **source_requirement**: Question: How does this fixed token sequence become a count vector? Source supplies two tokens, E(red)=[1,0], E(blue)=[0,1], sequence and embedding axes, and y=[1,1].
- **pixel_observation**: The three cards show these objects as prose lines. No token tiles, 2x2 lookup matrix, axis-aligned vector entries, or visible summation operator is drawn. Large blank card areas dominate the 180 x 290.336 mm artifact.
- **difference**: Compared with the actually viewed VGGT Fig2, where colored token stacks and grouping make the transformed object visible, this figure requires reconstructing the transformation from text. The reference is explanatory precedent only; attention layers are not applicable to this synthetic mechanism.
- **recommendation**: Within the provided facts, draw red/blue token objects, the two supplied one-hot rows with labeled axes, and a visible sum across the sequence axis yielding [1,1]. Preserve the absence of trained attention.
- **pass_condition**: The actual PNG allows a reader to follow each token to its given vector and see the axis and operation yielding both output coordinates; no learned/attention claim is added.
- **uncertainty**: The current profile does not mandate a venue aspect ratio or a specific pictogram language. This is an advisory mechanism-explanation gap, not an invented format violation.

### R1-CONSTRAINT-DIFF — reference_gap / medium

- **affected_ids**: constraint:before, constraint:revise, constraint:after
- **source_requirement**: Source requires retained bird(penguin), exclusion of penguins from may_fly, and retention of unknown flight for other birds.
- **pixel_observation**: Before/after expressions and the exception operations are embedded in separate prose cards. The retained fact, newly added guard, and unchanged unknown status are not visually distinguished; the blue innovation outline surrounds a whole text box.
- **difference**: The viewer can repeat the prose but cannot visually separate retained evidence from the single changed predicate. The observed reference figures attach different representations and outputs to the relevant operation rather than using only a generic card outline.
- **recommendation**: Show the rule before and after in an aligned comparison with only the sourced added guard highlighted. Keep a retained penguin counterexample and a clearly marked unknown state for other birds. Do not substitute observed flight examples.
- **pass_condition**: A reader can point to the unchanged fact, changed guard and remaining unknown status in the PNG, with no implication that every other bird actually flies.
- **uncertainty**: may_fly is not formally defined by the source. Treat it as the supplied conceptual permission/possibility term; do not infer that the figure asserts observed flight.

### R1-LOOP-COUNTER-SOURCE — necessary_content_omission / medium

- **affected_ids**: tool-loop:request, tool-loop:observe, tool-loop:decide, tool-loop:done
- **source_requirement**: The frozen claim calls the loop bounded; decide tests attempts < 2 / attempts >= 2; done permits a bounded no-answer exit.
- **pixel_observation**: Actual cards show no attempts initialization or increment. observe always states observation=found and answer_present=true; the only supplied worked path therefore stops on answer presence, while the no-answer bound is a declared alternative.
- **difference**: This insufficiency originates in the frozen scientific answer as well as the figure. The predicate is accurately copied, but finite retry behavior cannot be derived without a supplied counter-update convention or externally provided attempts state.
- **recommendation**: Request/source-author a counter-state definition or explicitly label attempts as externally supplied state and the unsuccessful branch as a conditional rule rather than a demonstrated trace. The renderer must not invent failed observations or an increment rule.
- **pass_condition**: Either authoritative revised facts define counter initialization/update and branch conditions, or the figure clearly limits its claim to selecting retry/stop given externally supplied attempts. The found example is not presented as evidence for an unsuccessful execution.
- **uncertainty**: A conventional externally maintained counter could resolve the gap, but that convention is absent from the input. This is not evidence of an infinite running implementation or of an empirical error.

Full source, reader retell, actual-pixel reference comparison, resource accounting and uncertainty are recorded in `round1.json`.

Elapsed wall interval: 190.028 seconds. Nested tool calls through report write: 24. Token/monetary usage: unavailable.
