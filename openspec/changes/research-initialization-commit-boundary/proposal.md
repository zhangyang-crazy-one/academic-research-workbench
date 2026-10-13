## Why

Issue #125 shows that research resume can replace lost accepted history with a new initialization event. Research materials must remain attributable to their original parent ledger; missing history must never become a healthy empty run.

## What Changes

- Require a durable, exact initialization transaction before resuming an empty partial run.
- Seal completion after the original first event and before any later parent write.
- Reject missing completed history, ambiguous legacy partial runs and damaged transaction records without modifying the scene.
- Preserve genuine SIGKILL initialization recovery and existing complete runs.

## Capabilities

### New Capabilities
- `safe-initialization-recovery`: distinguish incomplete initialization from missing committed history.

### Modified Capabilities
None.

## Impact

Journal initialization/writer entry, research startup/status, isolated fault tests and recovery documentation. No new dependencies, canonical event types, scientific authority or hook behavior. One PR for #125; no merge before owner review.
