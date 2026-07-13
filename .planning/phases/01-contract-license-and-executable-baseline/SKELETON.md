# Walking Skeleton — Academic Research Workbench

**Phase:** 1
**Generated:** 2026-07-13

## Capability Proven End-to-End

> From a clean checkout, an operator can install the staged headless plugin, route an ARS request, initialize and append/replay canonical JSONL through the sole writer, perform one root-confined MCP fixture read, and inspect raw plus summarized evidence.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Host framework | Codex plugin contract at verified floor `codex-cli 0.144.1` | The product is a Codex-native headless plugin; manifest, skill, hooks companion, and stdio MCP are the real host surface. |
| User interface | Routable skill plus `arw` JSON CLI | Phase 1 interaction is install/route/command/evidence, not a browser or desktop UI. |
| Control plane | Python `>=3.13,<3.15`, built/tested with 3.14.6 | Strict models, deterministic files, subprocess evidence, and short-lived sole-writer commands fit the project contract. |
| Canonical data layer | Append-only UTF-8 canonical JSONL plus immutable run manifest | JSONL is the only accepted write/read authority; no database, graph, hook, worker, transcript, or evidence summary decides provenance. |
| Data-plane service | Pinned file-base C/C++ MCP at `ee68144...` plus ordered hashed patches | Reuses the existing MCP baseline while placing path, symlink, sensitive-file, and output-budget controls inside the process. |
| Cross-language contract | Checked-in JSON Schema Draft 2020-12 generated from strict Pydantic models and independently validated with `jsonschema` | Detects Python/MCP contract drift without trusting the schema generator to validate itself. |
| Authentication | None in Phase 1 | This is a local plugin with explicit root capabilities; the Codex host may require user authentication for its own canary, but host identity is not canonical authority. |
| Installed Python strategy | Stage-relative `bin/arw` plus checked-in hash-locked wheelhouse and `$CODEX_HOME/arw/runtime/<identity>/venv` | The launcher resolves its own installed root, uses a compatible PATH/ARW_PYTHON interpreter only to create the cache-local venv, installs with `--no-index --require-hashes`, clears PYTHONPATH/user site, and never imports repository source. |
| Installed MCP strategy | Stage-relative `scripts/file-base-mcp` execs `libexec/file-base-mcp` with explicit root/cache capabilities | `.mcp.json` uses only the plugin-root-relative shape proven by probe→adapt→restage/reinstall→successful fresh-host launch; no cwd, source path, HOME grant, or wrapper-only confinement is accepted. |
| Dev deployment target | Exact allowlisted stage installed into an isolated repo-owned local Codex marketplace and `CODEX_HOME` | Tests run outside the repository with isolated HOME/CODEX_HOME, cleared PYTHONPATH, source access denied, and network disabled. Authentication is the only external host gate. |
| Source admission gate | Execute the exact pinned clean upstream native license gate, policy, checkers, and notice generator before populating `vendor/sources/**` | Makes the AGENTS.md license-before-vendoring rule an evidence-backed hard predecessor rather than a post-copy audit. |
| Release classification | Technical PASS and legal release PASS/BLOCKED are separate | SUP-04 is resolved as technical PASS/release BLOCKED until use/distribution and authentic permission evidence are recorded. |
| Canonical component licenses | ARS `vendor/sources/academic-research-skills/LICENSE` → `LICENSES/academic-research-skills-CC-BY-NC-4.0.txt`; experiment-agent `vendor/sources/experiment-agent/LICENSE` → `LICENSES/experiment-agent-CC-BY-NC-4.0.txt`; file-base MIT remains separate | The adapter duplicate `ars/LICENSE` is provenance alias only; the collective plugin is not labeled MIT. |
| Directory layout | Plugin metadata at root; `src/arw/` control plane; `schemas/v1/`; `vendor/`; `scripts/`; `tests/`; generated `build/` | Keeps authoritative source/contracts distinct from generated stage, cache, run, and evidence outputs. |

## Stack Touched in Phase 1

- [ ] Project scaffold — frozen uv environment, package metadata, lint/test entrypoints
- [ ] Routing — one real installed skill route and one machine-readable CLI route
- [ ] Compatibility — valid observational hook companion plus empirical hook/custom-agent/disabled-experiment probes and required fallback evidence
- [ ] Canonical storage — one real run manifest read and deterministic JSONL init/append/replay
- [ ] MCP boundary — one real bounded multilingual fixture read plus pre-content denial matrix
- [ ] Dev deployment — exact stage installed into an isolated local marketplace and exercised by a fresh Codex process outside the repository with no source/network/PYTHONPATH access
- [ ] Supply chain — exact-pin pre-vendoring native license gate, network-denied source reconstruction, post-patch extended gate, generated notices, C/Python/new dependency inventory, ordered patches, and release BLOCKED semantics
- [ ] Native safety — unchanged upstream C suite, combined ASan+UBSan, and a separate TSan build/run under network denial with distinct raw evidence
- [ ] Evidence — raw command outputs, including pre-vendor and all native safety domains, plus technical/release summaries keyed by the build-manifest digest

## Out of Scope (Deferred to Later Slices)

- Phase 2: full lifecycle transitions, Passport checkpoints, stale-worker handling, broad crash/torn-write recovery, and status/resume semantics.
- Phase 3: production indexing, FTS/search, extraction, outlines, pagination, and general files-first retrieval.
- Phase 4: full subagents, independent review panels, hook-driven UX, worker lifecycle, and human gate workflows.
- Phase 5: semantic graph projection and evidence-chain graph queries.
- Phases 6–7: full scientific receipts/audit dossier and cross-platform installed release qualification.
- Desktop/browser UI, remote collaboration, domain packs, telemetry, and a service database.

## Subsequent Slice Plan

Each later phase adds one headless vertical slice while preserving the sole-writer JSONL authority, strict schema boundary, explicit filesystem capabilities, and rebuildable-projection rule:

- Phase 2: durable provenance runtime and broader recovery.
- Phase 3: secure files-first retrieval.
- Phase 4: subagent orchestration, hooks, and accountable human gates.
- Phase 5: rebuildable research graph and bounded evidence queries.
- Phase 6: scientific integrity receipts and audit dossier.
- Phase 7: installed end-to-end recovery and release qualification.
