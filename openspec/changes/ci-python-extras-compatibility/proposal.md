## Why

PR #176 run 39569504862 job 119121900907 selected CPython 3.15 through `3.x`; installing all extras failed because torch supplied no cp315 wheel. Optional ML dependency availability must not prevent independent latest-Python core coverage.

## What Changes

- Select Python 3.14 as the complete optional-dependency CI environment, retaining all extras, dev, ars-test and storm coverage.
- Add an independent floating `3.x` Linux core job without optional ML dependencies or candidate/native prerequisites.
- Protect both lanes with regression tests and document the CI support matrix and evidence limits.
- Preserve open runtime Python and dependency ranges without adding locks or upper bounds.

## Capabilities

### New Capabilities
- `ci-python-compatibility`: Independent CI coverage for complete optional dependencies and latest-Python core behavior.

### Modified Capabilities
None.

## Impact

Only `.github/workflows/ci.yml`, CI contract tests, support documentation and this change's planning/evidence. No application code or dependency metadata changes.
