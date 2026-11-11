# Verification — `plugin-runtime-hardening`

Date: 2026-11-11
Base `main`: `1c5781f9`

## 已验证 (Verified)

- **Native `file-base` daemon isolation (`CBM_RUNTIME_DIR`)**:
  - Before fix: `tests/compat/test_filebase_mcp_contract.py` timed out at 15.0s (`3 failed`) while upstream `codebase-memory-mcp` held `/tmp/cbm-daemon-<uid>` (`msg=version_cohort.conflict_retry reason=version`).
  - After fix: live execution against pinned `.file-base/bin/file-base` passed `tests/compat` (**77 passed, 0 failed, 0 skipped**), `tests/integration/test_extension_extraction.py` (**4 passed**), and `tests/integration/test_mcp_confinement.py` (**9 passed, 2 skipped** for retained ASan/TSan evidence), with zero residual `file-base` daemon processes after teardown.
- **Manifest capability gating & `arw evidence impact`**:
  - `tests/unit/test_plugin_runtime_hardening.py` + `tests/integration/test_installed_graph_manifest.py` + core/health/opt-in/launcher/evidence suites: **93 passed, 5 skipped** (external candidate/retained-stage prerequisites only).
  - Verified `arw provenance`, `arw semantic`, and `arw evidence impact` fail closed when omitted from `plugin.json`, `bin/arw resume --memory-handoff` binds `.codex-plugin/plugin.json` while plain `resume` and `resume --help` work without a manifest, and `packaging/claude/plugin.json` matches `.codex-plugin/plugin.json` `interface.capabilities`.
- **Static & skill/overlay checks**:
  - `bash -n bin/arw extensions/file-base-mcp/bin/provider` passed.
  - `scripts/validate-skills` passed (`validated 3 allowlisted skills`).
  - `ruff check --isolated --select E4,E7,E9,F`, `ruff format --check`, `pyright` (`0 errors, 0 warnings`), `openspec validate plugin-runtime-hardening --strict --no-interactive`, Codex overlay tests (**127 passed**), and `ars_codex_quality_gates.py all --json` passed.

## 未验证 (Unverified)

- Hosted GitHub Actions CI across Ubuntu/macOS/Python `3.x` on the pushed PR head (pending remote CI completion).
- Full `scripts/stage-plugin` + `scripts/qualify-codex-host` live Codex host canary qualification and installed startup wall-clock/RSS A/B benchmarks (#150 follow-up).
- Automatic manuscript rewriting from `arw evidence impact` (intentionally unsupported; checklists are read-only and require human review) and cross-project impact propagation (deferred).
