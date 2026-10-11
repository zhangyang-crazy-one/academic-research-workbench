## Why

ARW currently exposes a Codex-specific production dispatch route even though its parent scheduler already accepts an execution adapter. Users need to select native agent platforms, external CLI harnesses and explicitly configured API harnesses without changing scientific provenance rules.

## What Changes

- Add versioned named harness configuration, assignment/role selection and an explicit CLI dispatch selector.
- Preserve the qualified Codex route and support bounded external command drivers and OpenAI-compatible Responses/Chat Completions API drivers; other APIs may use a configured command driver or an application-registered adapter.
- Keep authentication in runtime environment or an explicitly selected local `.env`; exclude credential values from manifests, receipts and diagnostics.
- Add platform-neutral observations and versioned host identity receipts while preserving existing Codex receipts byte-for-byte.
- Apply parent-owned assignment/result validation, bounded output, cancellation and timeout rules to every harness; qualify capabilities rather than equating a harness name with independence.

## Capabilities

### New Capabilities
- `configurable-execution-harnesses`: Explicit, extensible execution selection with CLI/API transports and common parent acceptance.

### Modified Capabilities
None.

## Impact

Execution configuration/adapters, CLI dispatch selection, host identity decoding, schemas, tests and runtime documentation. No new mandatory dependency or model API call is required to develop or validate this feature. This change is included before the v0.2.0 release candidate is frozen.
