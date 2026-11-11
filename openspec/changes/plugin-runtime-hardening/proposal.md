## Why

Paper-production workflows in Codex and Claude Code rely on ARW's plugin launcher (`bin/arw`), bounded `file-base` MCP retrieval, manifest-gated control-plane commands, and skill routing references. Inspection and live reproduction on `main` (`1c5781f9`) exposed four concrete plugin-layer gaps:

1. The native `file-base` MCP launcher (`extensions/file-base-mcp/bin/provider`) and direct native compatibility/confinement tests leave `CBM_RUNTIME_DIR` unset, defaulting to `/tmp/cbm-daemon-<uid>` and deadlocking (`version_cohort.conflict_retry`) whenever upstream `codebase-memory-mcp` runs on the same host.
2. Capability gating on `.codex-plugin/plugin.json` is bypassed by `arw provenance` and `arw semantic`, missing from `bin/arw resume --memory-handoff` (#145), left unmapped (`"evidence": ()`) despite `.codex-plugin/plugin.json` declaring `"evidence"`, and omitted from `packaging/claude/plugin.json`.
3. `src/arw/evidence_revision.py` (landed in PR #189) provides bounded read-only dependency impact checklists for manuscript/claim/experiment updates, but has no `arw` CLI command, capability route, or skill routing entry.
4. `bin/arw` re-hashes every staged payload file multiple times within a single startup check and spawns redundant interpreter version probes, while `skills/academic-research-workbench/references/control-plane-capabilities.md` omits over half of the shipped deterministic control-plane commands.

## What Changes

- Isolate `CBM_RUNTIME_DIR` in `extensions/file-base-mcp/bin/provider` (and in direct native binary tests with clean daemon teardown) so bounded source retrieval coexists with upstream `codebase-memory-mcp` and multiple project caches without re-building the pinned native binary.
- Centralize fail-closed plugin manifest resolution (`resolve_plugin_manifest`) and enforce manifest capability gating across `provenance`, `semantic`, `evidence`, and `resume --memory-handoff`; declare matching `interface.capabilities` in `packaging/claude/plugin.json`.
- Expose `src/arw/evidence_revision.py` through the read-only `arw evidence impact` CLI subcommand and the `evidence.impact` capability route so manuscript and claim revision workflows can inspect source-change impact directly from the plugin control plane.
- Deduplicate per-invocation SHA-256 reads and redundant Python version probes in `bin/arw`, and complete `bin/arw help` plus `skills/academic-research-workbench/references/control-plane-capabilities.md` across all shipped deterministic commands and opt-in stdio MCP servers.

## Capabilities

### New Capabilities
- `plugin-runtime-hardening`: Isolated native file-base daemon runtime, uniform manifest capability gating, read-only `arw evidence impact` CLI/routing, deduplicated launcher preflight reads, and complete skill capability routing.

### Modified Capabilities
None.

## Impact

Touches `extensions/file-base-mcp/bin/provider`, `bin/arw`, `src/arw/composition.py`, `src/arw/cli.py`, `src/arw/cli_semantic.py`, new `src/arw/cli_evidence.py`, `packaging/claude/plugin.json`, `skills/academic-research-workbench/references/control-plane-capabilities.md`, and regression/compatibility tests. Does not alter canonical journal schemas, frozen v1 CLI options, SBOM-pinned hook/ARS/native-binary bytes, or release qualification gates.
