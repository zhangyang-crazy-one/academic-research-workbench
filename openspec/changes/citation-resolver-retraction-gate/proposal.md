## Why

GitHub issue #36 requires authors to verify supporting citations before claims enter a paper. A bibliographic entry or a heuristic contamination flag does not prove that an indexed work exists or has not been retracted.

## What Changes

- Introduce a versioned `ReferenceRecord` with a per-use role and immutable provider check receipts.
- Resolve DOI/arXiv/title against Crossref, OpenAlex, DBLP and arXiv with deterministic comparison, bounded responses, explicit network opt-in and content-addressed offline replay.
- Distinguish verified, not_found, retracted, unknown, unavailable and ambiguous outcomes. Recheck appends evidence; old blockers remain visible.
- Evaluate citation gates by use: supporting not_found/retracted blocks; a retracted work studied as the object of research enters human review without automatic waiver or PASS.
- Derive supported contamination signals from receipts without treating API outage as nonexistence.

## Capabilities

### New Capabilities

- `citation-verification`: Reference identity, provider receipts, offline replay, retraction checks and per-use gates.

### Modified Capabilities

None.

## Impact

Adds a Python research policy module, optional CLI workflow, schemas/tests and provider adapter. Uses existing strict contracts, canonical JSON, immutable file publication and parent-owned admission. No dependency pin, lockfile, or automatic network request.
