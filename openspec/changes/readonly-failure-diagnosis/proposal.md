## Why

Accepted failures and edits can be retained today, but there is no bounded record that distinguishes recurring symptoms from competing, testable explanations. A later agent can repeat a ruled-out suggestion or mistake a plausible story for a proven cause.

## What Changes

- Add a read-only `learn diagnose` command over accepted frozen acceptance, failed receipt, and edit artifacts.
- Produce a typed `arw.failure-diagnosis.v1` report with canonical source references, at least two competing hypotheses, discriminating probes, explicit uncertainty, and no causal claim.
- Revalidate an optional previously accepted diagnosis through the existing memory read and successor path, and suppress probes for hypotheses already ruled out.
- Test three self-authored minimal sign, unit, and sample-mapping cases without exposing their hidden cause to the diagnosis request.

## Capabilities

### New Capabilities

- `readonly-failure-diagnosis`: Source-bound failure pattern analysis and advisory probe planning.

### Modified Capabilities

None.

## Impact

Core diagnosis contracts and read service, the learning CLI, checked schemas, focused fixtures/tests, and runtime documentation change. No ledger, producer, evaluator, policy, or promotion path is added.
