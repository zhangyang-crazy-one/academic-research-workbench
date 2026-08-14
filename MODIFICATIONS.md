# Modifications and Source Partitioning

Academic Research Workbench preserves each upstream source identity and records
the locally reshaped ARS adapter as a bundled, digest-bound plugin skill.

## academic-research-skills

- Upstream revision: `8cc7f8f4cccda721646d9df590b42721c93cba31`
- Upstream suite version: `v3.19.0` plus post-tag `main` updates through 2026-08-09
- Adapter version: `0.1.26`
- Bundled adapter: `skills/academic-research-suite/` (Codex router plus `ars/` workflows and references)
- Local source modifications: this repository's Codex adapter packaging and workflow reshaping are carried in the bundled snapshot. The formatter additionally enforces class-aware paragraph indentation, role-based one-/two-column float sizing, starred-float/barrier source-order auditing, and full-document rendered-page inspection before a LaTeX/PDF export can be called camera-ready. Upstream commit identities remain pinned in `manifest.json`.
- Codex path overlay: vendored workflow entrypoints use `WORKFLOW.md`; upstream checks that address Claude `SKILL.md` entrypoints are translated and their byte-level locks are repinned to the adapted files.
- Venue overlay: the Codex adapter adds a source-audited annual profile registry for the October 2026 ARR cycle, COLING 2027, NAACL 2027, and ECIR 2027. Official venue-year rules remain normative; accepted-paper patterns are explicitly non-normative editorial evidence.
- Evidence-row integration: the post-v3.19 Phase E shared evidence-row schema, validator, paginated renderer, and producer/consumer contracts are vendored from upstream. The Codex overlay preserves deterministic rendering and the explicitly degraded legacy-absence state without deriving evidence at display time.
- Human-subjects reference migration: the #680 reference update and its #666 authority-resolver boundary are vendored from upstream; Codex-local checks address the renamed `deep-research/WORKFLOW.md` entrypoint and retain the fail-closed unresolved state.
- Staging boundary: raw upstream evaluation transcripts under `ars/evals/heldout/*/runs/` remain source-and-test-only and are excluded from installed plugins. Public contracts, schemas, fixtures, and measurement summaries remain bundled.
- Legal projection: the integration lock records the repository's actual `public` visibility without treating visibility as non-commercial permission; intended use, distribution class, approval, and CC BY-NC permission remain unresolved release blockers.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

## experiment-agent

- Upstream revision: `e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651` (`v1.1.0`)
- Bundled adapter component: `skills/academic-research-suite/ars/`
- Local source modifications: the bundled adapter integrates the pinned experiment-agent material into the reshaped local ARS skill; upstream commit identity remains pinned in `manifest.json`.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

## knowledge-storm (opt-in)

- Upstream: <https://github.com/stanford-oval/storm> (`knowledge-storm` >= 1.1, `tavily-python`).
- Role: optional deep-research pipeline for experiment planning and deep-thinking passes, exposed as the `arw storm` command. Never part of the default route; writes only into an operator-chosen output directory and emits an `arw-storm-run-receipt.v1` audit receipt.
- Model access: LiteLLM over any OpenAI-compatible endpoint (defaults to `GEMINI_API_KEY` / `GOOGLE_GEMINI_BASE_URL`). Retrieval defaults to Tavily with a keyless DuckDuckGo fallback.
- Installation: optional `storm` dependency group; the installed plugin's offline runtime reports a fail-closed message when the group is absent.

## file-base

ARW's MCP is the locally modified `codebase-memory-mcp` adapter. The runtime
launcher keeps the upstream-compatible `file-base` name, while
`vendor/mcp-manifest.json` is the canonical machine-readable identity for the
upstream commit, patched tree, ordered ARW patch series, protocol, binary, and
capability profile. It is not an unpinned external MCP dependency.

- Upstream revision: `ee68144af5453addda995a27cce8142999f318fb`
- Materialized source: `vendor/sources/file-base`
- License: MIT, with the preserved generated third-party notices for bundled dependencies.
- Ordered patch 0001: `vendor/patches/file-base/0001-file-base-server-name.patch`
- Patch SHA-256: `dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a`
- Effect: applies the existing server-name/file-discovery integration patch without rewriting the upstream legal tooling.
- Ordered patch 0002: `vendor/patches/file-base/0002-phase1-confined-read.patch`
- Patch SHA-256: `1197346f62d06f0bad62c1e58fd374082b2f88e3eb8301746103f8066ba5c029`
- Effect: adds the Phase 1 native `read_file` MCP capability with explicit allowed-root capabilities, descriptor-relative no-follow traversal, sensitive-path denials, regular-file enforcement, strict UTF-8 output, and byte/line ceilings. It also disables the upstream update probe when the launcher explicitly sets `CBM_DISABLE_UPDATE_CHECK`, retains upstream-suite compatibility for MCP identity, control-file discovery, and bounded text/PDF discovery behavior, and avoids passing null zero-length fingerprint/function arrays to `qsort` or empty worker buffers to `memcpy` as diagnosed by UBSan.
- Upstream test policy: `vendor/sources/file-base/tests` remains unchanged and is manifest-bound at SHA-256 `4ace6a4c832b8d3e04d9366f5d7684833eadf338fd4be367e03fb7f8d274da2a`; the same `Makefile.cbm:test` inventory is used for normal, ASan+UBSan, and separate TSan runs.

The machine-readable source manifest is authoritative for exact tree, patch, artifact, and legal-input digests. Later patches must be appended in order and must update this document, the manifest, generated notices, and the SBOM.
