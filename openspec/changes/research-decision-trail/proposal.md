## Why

The project paper narrative already keeps an append-only author change history, but readers cannot inspect which recorded routes remain active, which were replaced, and which proposed branches were withdrawn. A read-only view makes those choices visible at handoff without inventing motives from Git changes or creating another canonical ledger.

## What Changes

- Add `arw narrative trail --project-root PROJECT --json`, with a historical sequence selector and optional expected-head check. The export identifies current, superseded, withdrawn, and unresolved choices with exact source events and recorded reasons.
- Add an author-confirmed withdrawal of a pending narrative proposal to the existing project journal. This is the missing fact needed to represent abandonment without a successor; it leaves the current selected strategy in force.
- Expose the same bounded current and abandoned route summary on paper handoff/resume. Keep old or corrupt history visible as a stale/corrupt error.
- Document that evidence links and decision history are provenance, not proof of scientific validity or a recommendation to reuse an abandoned route.

## Capabilities

### New Capabilities

- `research-decision-trail`: Deterministic, source-linked projection of project narrative choices and bounded handoff context.

### Modified Capabilities

None. Existing project-paper-narrative requirements remain satisfied; withdrawal adds an append-only route for an unresolved proposal.

## Impact

The existing narrative journal replay and CLI gain a withdrawal event and read-only projection. Paper handoff/resume response paths gain a bounded advisory summary. Tests use synthetic project histories; the requested ten-entry public author-record pilot remains a separate evidence task until locatable records are available and reviewed.
