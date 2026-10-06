# Modifications and Source Partitioning

Academic Research Workbench preserves each upstream source identity and records
the locally reshaped ARS adapter as a bundled, digest-bound plugin skill.

## academic-research-skills

- Upstream revision: `7de1c9dfb7af9c02a9b57750761323f35a743aa2`
- Upstream suite version: `v3.22.2` (2026-09-25)
- Adapter version: `3.22.2` (adapter numbering follows the upstream ARS-Codex package, which aligns with the ARS suite release from 3.22.0)
- Bundled adapter: `skills/academic-research-suite/` (Codex router plus `ars/` workflows and references)
- ARS v3.22.2 sync (2026-10-05, issue #47): `ars/` is three-way merged from the recorded ARS-Codex 0.1.27 base to the ARS-Codex v3.22.2 target (`70b412f`), with upstream-only files (raw eval transcripts) merged from ARS `127ff85` to `7de1c9d` under the `WORKFLOW.md` path translation. ARW-owned overlays (layout-export gate, five reference packs, manuscript-artifact boundary) are byte-preserved. The router `SKILL.md` adopts the v3.22.2 routing core, Spanish intent routing, `Skill`/`${CLAUDE_PLUGIN_ROOT}` mapping, and caller contracts (run ledger, acronym check, Chinese APA, instruction/data boundary; moved intact into `codex/references/ars_v3_22_caller_contracts.md` for progressive loading), but keeps ARW's inline-first execution and current-model policy instead of the ARS-Codex package's model/delegation policy; ARW's own `codex/` adapter is preserved.
- Progressive-loading modification (2026-09-25): moved the manuscript artifact/figure guidance and agent/shared-resource index from the 603-line Codex adapter `SKILL.md` into `codex/references/manuscript_artifact_and_figures.md` and `codex/references/agent_file_index.md`, with explicit links in the router. The moved contract text and upstream CC BY-NC 4.0 attribution are preserved; the adapter remains a modified downstream work, not a new upstream release.
- Agent Skills metadata correction (2026-09-25): represented `codex_adapter` as the string `"true"` required for metadata string values. The adapter behavior is unchanged.
- Local source modifications: this repository's Codex adapter packaging and workflow reshaping are carried in the bundled snapshot. The formatter additionally enforces class-aware paragraph indentation, role-based one-/two-column float sizing, starred-float/barrier source-order auditing, and full-document rendered-page inspection before a LaTeX/PDF export can be called camera-ready. Upstream commit identities remain pinned in `manifest.json`.
- Snapshot lint hygiene: Markdown-only fixes add explicit fence languages, normalize ordered-list/table syntax, escape a literal table pipe, and render two maintainer-local feedback identifiers as non-links because those private notes are intentionally absent from the release snapshot. These changes do not alter ARS workflow policy.
- Codex path overlay: vendored workflow entrypoints use `WORKFLOW.md`; upstream checks that address Claude `SKILL.md` entrypoints are translated and their byte-level locks are repinned to the adapted files.
- Venue overlay: the Codex adapter adds a source-audited annual profile registry for the October 2026 ARR cycle, COLING 2027, NAACL 2027, and ECIR 2027. Official venue-year rules remain normative; accepted-paper patterns are explicitly non-normative editorial evidence.
- Evidence-row integration: the post-v3.19 Phase E shared evidence-row schema, validator, paginated renderer, and producer/consumer contracts are vendored from upstream. The Codex overlay preserves deterministic rendering and the explicitly degraded legacy-absence state without deriving evidence at display time.
- Folder-adapter Unicode overlay: local `folder_scan.py` adapter version `1.2.0` accepts only the explicit `{Family}{separator}{Year}{separator}{title}` grammar for Unicode family names, preserves the original family/title display text, and derives collision-safe ASCII citekeys from a private NFKC-normalized digest input. The pinned upstream revision is unchanged; this downstream modification does not alter or resolve the CC BY-NC, intended-use, distribution-class, or accountable-approval restrictions.
- Dependency-range overlay: the opt-in PDF content classifier requirement now uses `pdf-inspector>=0.2.6` instead of an exact package pin, per the repository's unlocked dependency policy. This downstream change preserves the upstream commit identity and CC BY-NC 4.0 attribution.
- Fact-locked results revision and manuscript hygiene overlay (2026-09-29): the Codex adapter adds `codex/references/fact_locked_results_revision.md`, `codex/references/manuscript_hygiene_audit.md`, `codex/scripts/check_fact_locked_revision.py`, `codex/scripts/check_manuscript_hygiene.py`, fixtures, tests, and two quality gates (`fact-locked-revision`, `manuscript-hygiene`). The revision gate imports the vendored upstream #570 token extractor without modifying it. Both scripts are advisory or detection-only and never edit manuscripts. These findings come from real use (a 2026-09 pre-submission review); this downstream modification does not alter the pinned upstream revision or resolve the CC BY-NC, intended-use, distribution-class, or accountable-approval restrictions.
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
- Model access: session-first. The default backend reuses the current agent session's model (pi/Codex OAuth over the ChatGPT backend Responses API, e.g. `gpt-5.6-terra`); `--backend litellm` switches to any OpenAI-compatible endpoint (`--api-key`/`--api-base`, or the GEMINI environment pair). Retrieval defaults to Tavily with a keyless DuckDuckGo fallback.
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

## K-Dense scientific-agent-skills database-lookup advisory

- Upstream: K-Dense Inc., `K-Dense-AI/scientific-agent-skills`, commit `49c6e97775eaa18ba791bebe23162a70ae601c18`, path `skills/database-lookup/SKILL.md` (MIT). The commit identifies reviewed source bytes, not a runtime dependency pin.
- Exact upstream skill bytes, license text, selected tree identity, scan findings, and the user-directed archive-only disposition are recorded in `third_party/admissions/k-dense-database-lookup/`. The archive is outside auto-discovered and staged skill paths.
- Local modification (2026-09-25): `skills/academic-research-workbench/references/database-lookup-advisory.md` is a new, reduced proposal reference. It removes upstream shell commands, direct request procedures, local key handling, and the mandatory self-citation instruction. It cannot grant a worker canonical write or evidence admission. Direct staging of the upstream skill is rejected; trusted admission still needs separate human review.
