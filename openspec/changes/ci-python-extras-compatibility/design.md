## Context

The Python job currently resolves every optional extra plus the dev, ars-test and storm groups on floating `3.x`. The retained PR #176 log reports CPython 3.15.0, no cp315 torch wheel, and exit 1 before tests. The same log lists cp314 among available torch ABIs. The baseline contains no `openspec/specs/` or `openspec/config.yaml`; existing changes concern release qualification rather than this CI contract.

## Goals / Non-Goals

Goals: restore complete optional-dependency CI on a compatible minor and retain independent latest-Python core regressions. Non-goals: runtime restrictions, dependency locks/upper bounds, application changes, optional ML qualification on CPython 3.15, and hosted release/native qualification.

## Decisions

Keep the existing `python` job and candidate relationship, changing only its setup-python minor to `3.14`. Keep all existing dependency groups, quality gates and complete test discovery. This selection describes a CI test environment; it does not restrict supported runtime versions.

Add `python-core-latest` on Linux using floating `3.x`, the same regular-event condition, no job dependencies and only the declared core plus dev group. Run canonical, manifest, recovery, platform and CI contract regressions. Keeping this separate from the optional job avoids dependency wheel availability blocking core compatibility signals. Existing macOS and package-boundary jobs also continue floating but do not replace explicit Linux core coverage.

Tests parse the actual workflow to assert the complete optional install remains on 3.14, the independent latest core lane retains runnable tests without optional installs, both lanes use the same event policy, and runtime/dependency ranges remain open. Run these tests before changing the workflow, then rerun after the smallest fix.

## Risks / Trade-offs

- Open dependency resolution can change → record an actual 3.14 dry-run resolution separately from runtime tests; a resolver PASS is not an ML inference PASS.
- No local CPython 3.15 → retain original hosted failure evidence and explicitly leave current hosted latest-core and cp315 optional execution unverified.
- New latest-core job is a new check name → repository branch-protection configuration is outside this patch; retain the existing Python check name.

## Migration Plan

Merge through normal review; hosted CI runs both lanes. Update the full-extras CI minor after the complete ecosystem resolves and passes on a newer minor. No runtime metadata migration is required.
