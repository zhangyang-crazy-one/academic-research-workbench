## Context

Project narrative versioning exists, while accepted paper outputs have no machine checked connection to retained text. Artifact acceptance already validates content digests and is the parent owned admission point.

## Goals / Non-Goals

**Goals:** Bind annotations to actual bounded UTF-8 bytes and exact paragraph spans; enforce six function coverage, graph links and stale version refusal for outline, blueprint and prose; retain a distinct human semantic review outcome.

**Non-Goals:** Inferring claims, post hoc status, or scientific correctness from arbitrary prose; requiring six chapters or a positive result.

## Decisions

- Use one versioned realization JSON contract with `stage`, current narrative digest, source path and digest, ordered annotated nodes and predecessor artifact ID. Each node names a byte span plus span SHA-256. Acceptance reads the source through the confined file reader and checks these bytes. A forged sidecar cannot validate absent or changed source text.
- Use explicit typed references from claim to contribution, evidence and boundary, and evidence to contribution and boundary. Missing references fail mechanically; declarations of scope and hypothesis history remain subject to human review.
- Read the selected narrative under its project lock during acceptance. Blueprint must reference an accepted outline; draft must reference an accepted blueprint and carry every blueprint claim ID. This gives a replayable provenance chain.
- Old `NarrativePlan` v1 remains valid. New realization checks attach to new paper outputs, leaving previous journal events intact.

## Risks / Trade-offs

- Explicit annotation can misdescribe meaning → report semantic support as unknown and require human review; never claim automatic post hoc discovery.
- Inline ARS writes outside ARW cannot be intercepted → document the controlled admission requirement.
- Additional artifact reads cost I/O → impose bounded source and sidecar sizes.
