## ADDED Requirements

### Requirement: Complete optional-dependency CI uses a compatible minor

The regular Python CI job SHALL use Python 3.14 as its test environment and SHALL retain all project extras and dev, ars-test and storm groups with complete non-host test discovery.

#### Scenario: Latest Python lacks an optional ML wheel
- **WHEN** the latest Python minor has no compatible torch wheel
- **THEN** the complete optional-dependency job still selects Python 3.14 and resolves the original optional scope

### Requirement: Latest Python core coverage is independent

Regular CI SHALL run a separate Linux core job on floating `3.x`, installing only core and dev requirements, running canonical state, manifest, recovery and platform regressions, and requiring neither candidate artifacts nor another job's success.

#### Scenario: Optional installation fails
- **WHEN** an optional-dependency job fails to resolve its environment
- **THEN** latest-Python core coverage remains independently runnable and reports its own result

### Requirement: CI environment selection preserves runtime compatibility policy

The fix SHALL preserve `requires-python = ">=3.13"`, open dependency ranges and lockfile-free installation. Documentation SHALL distinguish CI environment selection from runtime compatibility and distinguish resolver checks from real execution.

#### Scenario: Installing on another compatible runtime
- **WHEN** a user selects a newer interpreter that satisfies the minimum
- **THEN** project metadata adds no Python upper bound or exact version lock, and dependency qualification remains environment-specific
