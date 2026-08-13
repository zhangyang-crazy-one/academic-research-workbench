# Modifications and Source Partitioning

Academic Research Workbench preserves each upstream source identity and records
the locally reshaped ARS adapter as a bundled, digest-bound plugin skill.

## academic-research-skills

- Upstream revision: `c22c17eed8a5753aa60681be9734919f2e2f5b42`
- Adapter version: `0.1.20`
- Bundled adapter: `skills/academic-research-suite/` (Codex router plus `ars/` workflows and references)
- Local source modifications: this repository's Codex adapter packaging and workflow reshaping are carried in the bundled snapshot. The formatter additionally enforces class-aware paragraph indentation, role-based one-/two-column float sizing, starred-float/barrier source-order auditing, and full-document rendered-page inspection before a LaTeX/PDF export can be called camera-ready. Upstream commit identities remain pinned in `manifest.json`.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

## experiment-agent

- Upstream revision: `9b063fa895eaf1f63ac99ac03f924f8d31aa8d26`
- Bundled adapter component: `skills/academic-research-suite/ars/`
- Local source modifications: the bundled adapter integrates the pinned experiment-agent material into the reshaped local ARS skill; upstream commit identity remains pinned in `manifest.json`.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

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
