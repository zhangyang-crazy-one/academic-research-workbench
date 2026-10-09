## Why

PR #96 is ready for integration but all package metadata still reports 0.1.0. Pinned launcher and installation checks would reject a package whose version alone was bumped.

## What Changes

- Align package, Codex/Claude manifests, CodeMeta and MCP version identity to 0.2.0.
- Permit matching 0.1.0 and 0.2.0 retained installation bindings; reject mismatched package/plugin/wheel identities.
- Refresh affected technical metadata digests and prepare release notes.
- Preserve the existing formal release authority gate and all historical evidence bytes.

## Capabilities

### New Capabilities
- `release-version-consistency`: Consistent 0.2.0 distribution identity with explicit legacy installation compatibility.

### Modified Capabilities
None.

## Impact

Packaging metadata, launcher checks, MCP server identity, integration-lock model/schema, version probes and release documentation. No new runtime dependencies, source refresh or model API calls.
