## 1. Native file-base daemon runtime isolation

- [x] 1.1 Isolate and validate `CBM_RUNTIME_DIR` in `extensions/file-base-mcp/bin/provider` with socket-length-safe path selection and fail-closed ownership/symlink checks.
- [x] 1.2 Isolate `CBM_RUNTIME_DIR` and stop spawned daemons on teardown in `tests/compat/test_filebase_mcp_contract.py`, `tests/integration/test_mcp_confinement.py`, and `tests/integration/test_extension_extraction.py`; verify live coexistence while upstream `codebase-memory-mcp` is active.

## 2. Uniform manifest capability gating and Claude manifest parity

- [x] 2.1 Add `resolve_plugin_manifest` in `src/arw/composition.py` and gate `provenance` (`src/arw/cli.py`), `semantic` (`src/arw/composition.py`), and `resume --memory-handoff` (`bin/arw`) on `.codex-plugin/plugin.json` while preserving source-checkout and non-handoff `resume` behavior.
- [x] 2.2 Declare matching `interface.capabilities` in `packaging/claude/plugin.json` and add unit/integration regressions for manifest gating across `provenance`, `semantic`, `evidence`, and `resume --memory-handoff`.

## 3. Read-only `arw evidence impact` CLI and capability route

- [x] 3.1 Register `evidence.impact` in `src/arw/composition.py` (`default_router`, `manifest_to_router["evidence"]`, and `core_provider_records`) and implement bounded read-only `src/arw/cli_evidence.py` (`arw evidence impact`) wired into `src/arw/cli.py` and `bin/arw`.
- [x] 3.2 Add end-to-end workflow acceptance and negative/tamper tests for `arw evidence impact` (read-only checklist over projected claims/plans/paragraphs, watermark/incomplete rejection, and manifest capability gating), distinguishing implemented read-only checklists from unsupported automatic manuscript rewriting and deferred cross-project impact propagation.

## 4. Launcher startup deduplication and skill capability routing

- [x] 4.1 Memoize per-file SHA-256 digests within `bin/arw` `bootstrap_wheel_runtime` and remove redundant post-`select_python` interpreter version subprocess probes.
- [x] 4.2 Update `bin/arw` `usage()` and `skills/academic-research-workbench/references/control-plane-capabilities.md` to cover all shipped deterministic CLI commands and opt-in stdio MCP entrypoints; verify `scripts/validate-skills`, Ruff/Pyright, compatibility baseline, and targeted suites.
