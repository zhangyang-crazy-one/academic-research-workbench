## Context

ARW ships as a Codex-native (and Claude-transformable) headless research control-plane plugin (`v0.2.1`). On `main` (`1c5781f9`):

- The pinned native `file-base` binary (`DeusData/codebase-memory-mcp` v0.11.0 + ARW patches) honors `CBM_RUNTIME_DIR` (`src/daemon/bootstrap.c:240`), validating private directory ownership/permissions and Unix socket path length (`sockaddr_un.sun_path`). Because `extensions/file-base-mcp/bin/provider` does not set `CBM_RUNTIME_DIR`, `file-base` shares `/tmp/cbm-daemon-<uid>` with any host `codebase-memory-mcp` daemon and spins in `version_cohort.conflict_retry` until MCP startup times out.
- `default_router(..., plugin_manifest=...)` intersects registered capabilities with `interface.capabilities` in `plugin.json`, but `cli.py` (`provenance`) and `composition.py` (`configured_semantic_provider`) omit `plugin_manifest`, `bin/arw` omits `ARW_PLUGIN_MANIFEST` on `provenance` and `resume --memory-handoff`, `"evidence"` maps to `()`, and `packaging/claude/plugin.json` omits `interface.capabilities`.
- `src/arw/evidence_revision.py` (`impact_checklist`) was added in PR #189 for read-only impact review over `GraphStore`, but is unreachable from `bin/arw` or the workbench skill.
- `bin/arw` (`bootstrap_wheel_runtime`) computes uncached SHA-256 digests over both `covered_files` and `staged_payloads` (reading every staged payload, including the 285 MiB native binary, at least twice per invocation) and re-runs `python -I -S` version checks immediately after `select_python` already verified `>=3.13`.

## Goals / Non-Goals

- **Goals**:
  - Eliminate native `file-base` daemon cohort collisions without modifying or recompiling the SHA-256-pinned native binary or breaking existing `arw files enable` project configs.
  - Enforce one consistent fail-closed `plugin_manifest` resolution contract across all manifest-gated CLI and MCP entrypoints, while keeping source-checkout development fallbacks intact.
  - Provide a bounded, read-only `arw evidence impact` CLI command backed by `evidence.impact` capability routing.
  - Remove redundant per-invocation file hashing and interpreter probes in `bin/arw`, and align skill routing documentation with the shipped CLI surface.
- **Non-Goals**:
  - Rebuilding `.file-base/bin/file-base`, upgrading upstream `codebase-memory-mcp` (#136), or changing MCP wire schemas.
  - Persisting cross-invocation digest trust caches or weakening `installed_core_preflight` / `verify_staged_core` tamper checks.
  - Auto-accepting manuscript or claim revisions from `arw evidence impact` (checklists remain strictly read-only and require human review).

## Decisions

1. **Short, owner-private `CBM_RUNTIME_DIR` in `extensions/file-base-mcp/bin/provider`**:
   - If `CBM_RUNTIME_DIR` is explicitly set, require an absolute, existing, non-symlink directory owned by the effective UID (`exit 64`/`66` on violation).
   - Otherwise, prefer `$CBM_CACHE_DIR/rt` when its length is `<= 56` bytes (staying well within POSIX `sun_path` limits even after appending `/cbm-daemon-<uid>/cbm-<key>.sock`). When `$CBM_CACHE_DIR` is longer (e.g. deep project paths or pytest `tmp_path`), use `<tmp-root>/arw-fb-<uid>-<12hex(sha256(CBM_CACHE_DIR))>` (`0700`, verified real directory owned by effective UID, falling back to `mktemp -d` if squatted). Existing `.codex/config.toml` and `.mcp.json` entries require no migration.
   - Direct native binary tests (`tests/compat/test_filebase_mcp_contract.py`, `tests/integration/test_mcp_confinement.py`, `tests/integration/test_extension_extraction.py`) supply an isolated `TemporaryDirectory(prefix="arw-fb-")` via `CBM_RUNTIME_DIR` and run `<binary> daemon stop` during fixture teardown so no background daemon lingers.

2. **Shared `resolve_plugin_manifest` helper & `evidence.impact` route**:
   - Add `resolve_plugin_manifest(*, fallback_anchor: Path | None = None) -> Path | None` in `src/arw/composition.py` implementing the 3-step contract: explicit `ARW_PLUGIN_MANIFEST` (must be an existing non-symlink regular file), fail-closed `plugin_manifest_missing` when `ARW_PLUGIN_ROOT` is set without `ARW_PLUGIN_MANIFEST`, and source-tree `.codex-plugin/plugin.json` fallback when neither env var is set.
   - Wire `provenance`, `semantic`, `evidence`, and `resume --memory-handoff` through `ARW_PLUGIN_MANIFEST` in `bin/arw` and `resolve_plugin_manifest` in Python.
   - Register `evidence.impact` in `default_router` (and `core_provider_records`), map `"evidence": ("evidence.impact",)`, and add `src/arw/cli_evidence.py` (`arw evidence impact`) reading bounded JSON (`<= 64 KiB`) for `EvidenceUpdate` and optional proposed text mappings without mutating `GraphStore` or the journal.
   - Add matching `interface.capabilities` to `packaging/claude/plugin.json` so Claude plugin manifests declare the same capability surface as Codex.

3. **Single-invocation digest memoization in `bin/arw` & complete skill table**:
   - Memoize `sha(path)` by resolved path inside `bootstrap_wheel_runtime`'s inline Python verifier (after symlink rejection) and reuse the already-validated interpreter from `select_python`. No state persists across invocations.
   - Expand `skills/academic-research-workbench/references/control-plane-capabilities.md` and `bin/arw` `usage()` to cover all shipped CLI commands and opt-in stdio MCP servers while preserving progressive-loading compactness.

## Risks / Trade-offs

- **Socket path length on macOS/Linux**: `sun_path` caps at 104/108 bytes → cap `<parent>` at 56 bytes before falling back to hashed `/tmp` / `/private/tmp` directory names (`~31` bytes).
- **Frozen compatibility contracts**: `tests/compat/test_cli_contract.py` pins v1 commands and flags, and `tests/staged/test_cli_launcher.py` pins `arw health --json` top-level keys → `arw evidence` is purely additive, existing command flags are untouched, and `health_report()` keys remain unchanged.

## Migration Plan

Drop-in compatible: existing staged plugins, run ledgers, and `arw files enable` host configurations continue to work unchanged while gaining daemon isolation, complete manifest gating, and `arw evidence impact`.
