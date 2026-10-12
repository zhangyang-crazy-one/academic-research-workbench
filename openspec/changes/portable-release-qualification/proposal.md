## Why

The owner requires a permissive formal release policy: publishing ARW must not require one harness, model or exact host version. Current Codex-only canary/lock requirements prevent authors from using otherwise working authenticated platforms.

## What Changes

- Make package installation, core CLI functionality and evidence integrity the default formal release checks.
- Record observed tool versions without making them exact release compatibility pins.
- Keep native Codex/other platform qualification as optional deployment-specific checks, with original readers retained.
- Preserve candidate hashes, clean source identity, original CI subjects, licensing and independent publication authority.

## Capabilities

### New Capabilities
- `portable-release-qualification`: Host-independent candidate qualification and transferable installed-core observations.

### Modified Capabilities
None. Historical platform-specific qualification contracts remain readable.

## Impact

Release preparation, candidate-bundle validation, formal release check, operator documentation and regression tests. No runtime model selector, login state or research acceptance gate changes.
