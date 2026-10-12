## Why

#119 needs actual CPU executions beyond synthetic evaluator fixtures. Authors need inspectable proof that a frozen contract, externally generated raw observations, parent provenance acceptance and offline numerical replay form a complete usable workflow.

## What Changes

- Provide three public standard-library numerical mini-experiments and analytically generated inputs.
- Execute each through real CLI freeze, authorized external CPU subprocess, parent provenance intake, offline accept and cold replay.
- Preserve an intentionally failing v1 and post-result relaxed v2 without inheriting prior timing.
- Retain raw outputs, original costs, manifests and source digests; missing monetary/hardware-resource costs stay unknown.

## Capabilities

### New Capabilities
- `public-cpu-pilots`: retained reproducible numerical experiment validation.

### Modified Capabilities
None.

## Impact

Pilot scripts and evidence/examples only. No evaluator, event, dependencies or production execution-policy changes. CPU-only, no model/API calls. One unmerged PR for #119.
