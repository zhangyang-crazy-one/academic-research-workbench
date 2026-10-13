## Why

Issue #120 needs independent human labels to assess whether narrative trail preserves public research decisions. The owner supplied ten answers and explicitly requested their transcription into the CSV, including option B (optional dimensions) for the third item. These answers must be retained without being silently converted into NumPy historical judgments.

## What Changes

- Prepare ten pinned public numerical-research infrastructure decisions with source hashes and source locators.
- Retain all ten owner answers in the independent annotation sheet with response provenance and the third item's selected option.
- Add an offline import/comparison workflow using existing narrative contracts, preserving unknown and two-round handoff evidence.
- Distinguish recorded owner answers from source-history labels; keep historical comparison and pilot accuracy pending.

## Capabilities

### New Capabilities
- `public-decision-pilot`: source-bound independent annotation and transparent narrative comparison.

### Modified Capabilities
None. No trail contract changes.

## Impact

Examples, offline pilot scripts and evidence documentation. No production evaluator changes, paid model calls or new dependencies. One unmerged PR for #120; it will not close the issue before human validation.
