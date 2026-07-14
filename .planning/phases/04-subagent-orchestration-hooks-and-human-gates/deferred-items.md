# Deferred Items

## Staged-plugin allowlist does not include Phase 4 schemas

- **Found during:** full repository regression run after Plan 04-02.
- **Observed failures:** 12 staged/package integration tests fail before their assertions because `scripts/stage-plugin` reports the eight existing Phase 4 schema files as unexpected extras under `share/arw/schemas/`.
- **Scope:** out of scope for Plan 04-02; the failure is in staged-plugin inventory/allowlist coverage rather than the parent-only reducer, event, or evidence boundary.
- **Next action:** update the Phase 4 staged inventory/allowlist in the owning packaging plan, then rerun the staged and installed-plugin suites.
