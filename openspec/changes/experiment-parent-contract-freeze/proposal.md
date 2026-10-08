## Why

Experiment contracts can currently be published as immutable files, but the parent journal never accepts them. The CLI therefore cannot establish whether a specific contract was accepted before the related external provenance.

## What Changes

- Add a parent-owned contract freeze command and `experiment.contract.accepted` event through the existing writer transaction.
- Validate successor contracts against an accepted predecessor in the same claim and contract chain.
- Derive acceptance order only from the validated journal and report its narrow scope; caller-supplied timestamps or sequences cannot strengthen it.
- Preserve old receipt bytes and version-specific replay while adding focused transaction and tamper tests.

## Capabilities

### New Capabilities

- `experiment-parent-contract-freeze`: Parent journal contract admission, succession, and bounded timing evidence.

### Modified Capabilities

None.

## Impact

Experiment CLI and acceptance, parent event contracts/reducer/manifest validation, checked schemas, tests, and runtime documentation change. External experiment execution and public scientific pilot studies remain outside this first implementation.
