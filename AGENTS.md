<!-- GSD:project-start source:PROJECT.md -->
## Project

**Academic Research Workbench**

Academic Research Workbench is a private, Codex-native plugin that turns the existing Academic Research Suite (ARS) and Paper4Master file-base graph MCP into an executable, auditable research workflow. It coordinates specialized subagents, lifecycle hooks, files-first retrieval, semantic research-graph projections, integrity gates, resumable runs, and evidence artifacts for literature review, experiment planning, manuscript production, and strict peer review.

The v1.0 milestone delivers a headless core for Codex. It is not a desktop application and does not constrain research workflows to one language, domain, dataset, or paper topic.

**Core Value:** Every research run must be reproducible, resumable, and auditable from source files through claims, experiments, review gates, and final artifacts.

### Constraints

- **Runtime**: Codex-native plugin conventions and MCP transport contracts - the deliverable must install and execute through Codex rather than remain a design document.
- **Architecture**: Append-only ledger and immutable artifact manifests are the system of record - mutable graph state cannot decide scientific provenance.
- **Source provenance**: Necessary upstream code must be pinned with patch and license inventory - vendoring must remain reviewable and legally attributable.
- **Compatibility**: Preserve ARS workflow semantics and expose file-base capabilities through bounded, machine-readable tools - existing research assets must remain usable.
- **Security**: File access is restricted to explicitly allowed roots and outputs are bounded - the MCP must not become an unrestricted filesystem bridge.
- **Delivery**: v1.0 is headless and testable - desktop UX is deferred until runtime contracts and evidence gates are stable.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommendation in One Sentence
## Recommended Stack
### Core Technologies
| Technology | Version / Pin | Purpose | Why Recommended | Confidence |
|------------|---------------|---------|-----------------|------------|
| Codex plugin contract | Test floor: `codex-cli 0.144.1` | Installation and host integration | This is the locally verified Codex release. Use `.codex-plugin/plugin.json`, `skills/`, `hooks/hooks.json`, and `.mcp.json` exactly as documented; do not invent a plugin-specific agent directory. | HIGH for the verified floor; MEDIUM for future compatibility |
| Python | `3.14.6` for builds and development; support `>=3.13,<3.15` | Workflow CLI, state machine, schema models, hook handlers, PDF text extraction, audit report generation | Python 3.14.6 is the current stable CPython release and receives support through 2030. It matches ARS's existing Python validators and is a better fit for research-document processing than adding Node solely for orchestration. Keep Python 3.13 in CI as the compatibility floor. | HIGH |
| ARS Codex adapter | Adapter `0.1.19`; `academic-research-skills@c22c17eed8a5753aa60681be9734919f2e2f5b42`; `experiment-agent@9b063fa895eaf1f63ac99ac03f924f8d31aa8d26` | Research workflows, role prompts, handoff semantics, integrity gates | Vendor the already adapted ARS package as immutable source material. The runtime operationalizes ARS contracts; it must not rewrite or fork the methodology in place. | HIGH |
| file-base | `DeusData/codebase-memory-mcp@ee68144af5453addda995a27cce8142999f318fb` (`v0.9.0-2-gee68144`) plus a numbered local patch series | Files-first MCP, structural graph, research projection, bounded retrieval | The selected revision already negotiates MCP `2025-11-25`, embeds SQLite and parsers, supports Linux/macOS/Windows builds, and is proven locally. Extend it rather than introducing a second indexing service or rewriting it. | HIGH |
| MCP | Protocol `2025-11-25`, stdio transport | Codex-to-file-base tool protocol | `2025-11-25` is the current published MCP specification and is already in file-base's supported-version list. Stdio is the correct local, private, headless transport and is directly supported by Codex. | HIGH |
| SQLite + FTS5 | Vendored file-base SQLite `3.51.3` | Rebuildable file metadata, text search, structural graph, research projection | SQLite is embedded, transactional, portable, and sufficient for a single-user local workbench. It avoids a database service while supporting FTS5 and concurrent readers. The database remains disposable. | HIGH |
| JSON Schema | Draft `2020-12` | Cross-language contracts for state, assignments, results, evidence, gates, and MCP structured output | Draft 2020-12 is supported by Pydantic and current `jsonschema`, and is language-neutral enough for Python and C consumers. | HIGH |
### Supporting Libraries
| Library | Version | Purpose | When to Use | License |
|---------|---------|---------|-------------|---------|
| `pydantic` | `2.13.4` (`>=2.13,<3`) | Strict runtime models and JSON Schema generation | All canonical record envelopes: run, state, event, assignment, result, artifact, source, claim, experiment, review, gate, waiver, and human-review item | MIT |
| `jsonschema` | `4.26.0` (`>=4.26,<5`) | Independent validation of checked-in schemas | CI drift checks, fixtures, and validating C-produced JSON without relying on the same Pydantic code that generated the schema | MIT |
| `portalocker` | `3.2.0` (`>=3.2,<4`) | Cross-platform advisory run locks | Serialize parent-orchestrator writes and test lock contention on Linux, macOS, and Windows | BSD-3-Clause |
| `platformdirs` | `4.10.0` (`>=4.10,<5`) | Per-user cache/data locations | Put disposable indexes, downloaded build caches, and installed runtime data outside research source trees; canonical run evidence still belongs in the workspace | MIT |
| `pypdf` | `6.14.2` (`>=6.14,<7`), optional extra | Permissively licensed PDF text extraction | Text-bearing PDFs only. Record extractor version and content hash. Image-only or failed extraction becomes a human/OCR review item, not silently empty evidence. | BSD-3-Clause |
| `mcp` Python SDK | `1.28.1` (`>=1.28.1,<2`), test dependency only | Protocol client and in-memory/stdio test harness | Black-box MCP conformance and Codex-facing integration tests. Do not put a Python MCP proxy in the production path. | MIT |
| `hatchling` | `1.31.0` | Build backend for the Python control-plane wheel | Build the `arw` CLI/hook package; keep platform-specific file-base binaries as separate release artifacts | MIT |
### Development Tools
| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| `uv` | `0.11.28` | Python installation, lock, sync, build, SBOM export | Commit `.python-version`, `pyproject.toml`, and `uv.lock`. CI uses `uv sync --frozen`; release jobs use a checksum-pinned uv binary. Export CycloneDX from the lockfile. |
| `pytest` | `9.1.1` | Unit, integration, recovery, and evidence tests | Use `tmp_path` for isolated run roots and golden fixtures only for stable wire artifacts. |
| `pytest-asyncio` | `1.4.0` | MCP client/server integration tests | Needed only where the MCP SDK client is asynchronous. |
| `hypothesis` | `6.156.6` | State-machine and crash/replay property tests | Generate command sequences, duplicate IDs, stale revisions, partial writes, and malformed result envelopes. |
| `ruff` | `0.15.21` | Python lint and format | One fast tool; pin it in the dev group. |
| GCC/Clang sanitizers | Compiler from each pinned build image | C correctness and concurrency | Run file-base tests with ASan+UBSan, and TSan separately. Do not ship a sanitizer build. |
| Existing file-base license gate | Pinned with file-base commit | Source and binary license inventory | Preserve `scripts/license-gate.sh`, `license-policy.json`, and generated notices; add the local patch and new dependencies to the same gate. |
| Codex CLI | `0.144.1` in release smoke tests | Plugin, hook, native-subagent, and MCP compatibility | Record exact version in audit output. Upgrade only through an explicit compatibility PR. |
## Language and Runtime Boundaries
### Python owns the control plane
- `arw init/status/resume/transition/checkpoint/finalize`;
- strict schema models and schema generation;
- the append-only ledger and atomic `state.json` projection;
- immutable assignment/result/artifact manifests;
- Material Passport and integrity-gate evaluation;
- hook executables;
- optional PDF extraction and human-review queue generation;
- release manifest, audit summary, and evidence-bundle generation.
### C/C++ owns the data plane
- MCP stdio framing and capability negotiation;
- allowed-root enforcement, canonical path checks, symlink escape rejection, and output caps;
- file discovery and incremental metadata updates;
- the `files` table and FTS5 indexes;
- code/document structural graph extraction;
- validated research-manifest projection and bounded graph queries.
## Storage and Indexing
### Canonical storage: files, not a database
- `schema_version`, `event_id`, `command_id`, `run_id`, and monotonic `sequence`;
- UTC RFC 3339 timestamp;
- expected and resulting state revision;
- `event_type` discriminator and typed payload;
- actor/agent/assignment IDs where relevant;
- `prev_event_sha256` and `event_sha256` over deterministic UTF-8 JSON bytes.
### Crash-safe write protocol
### Rebuildable SQLite projection
- `unicode61 remove_diacritics 2` for English prose, identifiers, paths, Markdown, BibTeX, and LaTeX tokens;
- a separate `trigram` index for CJK and substring fallback.
## Files-First MCP Contract
- `list_files`
- `read_file`
- `search_files`
- `get_file_outline`
- `get_file_context`
- `ingest_research_manifest`
- `sync_research_run`
- resolve the candidate path and its ancestors before checking it against allowed roots;
- reject absolute paths, `..` escape, symlink escape, device files, sockets, and unapproved roots;
- cap bytes, lines, rows, snippets, traversal depth, and query time server-side;
- paginate lists and search results with opaque cursors;
- distinguish `not_found`, `not_indexed`, `binary`, `too_large`, `unsupported`, `extraction_failed`, and `access_denied`;
- keep reads side-effect free; indexing/sync tools remain separately approval-gated;
- disable upstream update checks in reproducible/offline mode.
## Schemas and Validation
### Contract source
- `ConfigDict(strict=True, extra="forbid")`;
- discriminated unions on `event_type`, `result_type`, `artifact_type`, and `gate_type`;
- explicit `schema_version` literals;
- constrained IDs, relative paths, SHA-256 strings, timestamps, and sequence numbers;
- no implicit datetime, number, or enum coercion at canonical boundaries.
### C validation
## Codex Plugin, Subagents, and Hooks
### Plugin structure
### Subagent strategy
### Hook strategy
- `SessionStart`: locate and validate the selected run/passport and add concise context.
- `SubagentStart`: inject assignment ID, hashes, allowed roots, and output contract.
- `SubagentStop`: validate the result envelope and request continuation if incomplete.
- `PreToolUse`: deny supported obvious violations for Bash, `apply_patch`, and MCP calls.
- `PostToolUse`: record lightweight evidence and schedule projection sync.
- `Stop`: continue only when the current user-requested deliverable or mandatory gate remains open.
## Packaging and Reproducible Builds
### Source vendoring
### Release artifacts
- Linux x86_64 and arm64: static musl build where file-base tests pass;
- macOS arm64 and x86_64: pinned Xcode/Clang image;
- Windows x86_64: pinned MinGW-w64 image.
### License gate — mandatory before vendoring
| Component | Pin | Verified License | Required Action |
|-----------|-----|------------------|-----------------|
| academic-research-skills | `c22c17e...` | CC BY-NC 4.0 | Preserve attribution, license, notices, and modification markings. Do not distribute or use for a primarily commercial purpose without separate permission. |
| experiment-agent | `9b063fa...` | CC BY-NC 4.0 | Same restriction and attribution duty as ARS. |
| codebase-memory-mcp / file-base | `ee68144...` | MIT | Preserve copyright and MIT text in source and binary distributions. |
| file-base bundled dependencies | Pinned inside `ee68144...` | MIT, Apache-2.0, BSD-2-Clause/BSD-like, public-domain SQLite; see upstream notices | Preserve upstream generated notices and rerun the license gate after every source refresh. |
| pypdf | `6.14.2` | BSD-3-Clause | Include in Python SBOM/notices when the PDF extra ships. |
## Installation and Verification
# Pinned Python and dependencies
# Verify vendored sources, commits, licenses, and patch hashes
# Build file-base from a clean temporary source tree
# Python and protocol tests
# C safety suites; exact wrapper target may differ by platform
# Reproducibility and inventory gates
## Test Stack and Required Evidence
### Python kernel tests
- pure transition-table unit tests;
- Pydantic strictness and unknown-field rejection;
- generated-schema drift tests;
- deterministic event-byte and hash-chain fixtures;
- property-based command/replay tests;
- crash injection after each write step;
- duplicate command, stale revision, stale result, failed gate, waiver, and lock contention;
- mutation tests for gate predicates if time allows.
### file-base tests
- upstream C suite unchanged;
- ASan+UBSan and separate TSan runs;
- allowed-root and symlink escape attacks;
- byte/line/result/depth/timeout caps;
- UTF-8 errors, long lines, NULs, binary files, rename/delete, and interrupted reindex;
- Markdown, LaTeX, BibTeX, JSON/YAML/TOML, CSV, patch, and PDF-extraction fixtures;
- Chinese, English, mixed CJK/Latin, DOI, citation-key, and LaTeX search relevance;
- malformed and adversarial research manifests;
- graph deletion/rebuild equivalence.
### Codex/plugin tests
- manifest and relative-path validation;
- install from a local marketplace and from a pinned Git ref;
- hooks disabled, untrusted, trusted, and changed-hash behavior;
- hook stdin/stdout golden tests for every event;
- native read-only child assignment and schema-valid result handoff;
- independent reviewer blindness before synthesis;
- stop/resume after process kill and after a fresh Codex session;
- MCP approval policy: read tools approved, index/sync tools prompted;
- audit bundle inspection with exact Codex, Python, dependency, compiler, file-base, schema, and source versions.
## Alternatives Considered
| Recommended | Alternative | Why Rejected for v1 | When to Reconsider |
|-------------|-------------|---------------------|--------------------|
| Python control plane | TypeScript/Node plus `@openai/codex-sdk` | Adds a second application runtime and nested Codex control inside a Codex plugin. The durable scientific state must not depend on a model thread ID. | A standalone service outside Codex that programmatically owns many Codex threads |
| Native Codex subagents + file assignments | Python `openai-codex` SDK `0.1.0b3` | The Python SDK is explicitly beta. It is useful for external automation but unnecessary for in-host plugin delegation. | Optional external batch runner after stable SDK release |
| Extend pinned C file-base | Python MCP facade with a second index | Duplicates file metadata/FTS and creates two query semantics and two caches. | If C maintenance becomes untenable or a supported upstream files API never lands |
| Append-only JSONL + immutable artifacts | Temporal, LangGraph, Prefect, Celery | Adds services and hidden state while weakening inspectability and offline operation. | Multi-user remote execution with distributed workers |
| SQLite projection | PostgreSQL/Neo4j/Elasticsearch | Operational burden is unjustified for one local writer, and a server database invites accidental authority. | Shared multi-user remote workbench with measured contention/scale needs |
| Pydantic + checked-in JSON Schema | Protobuf | JSON artifacts are more inspectable and align with MCP and ARS; Protobuf would require generated C/Python code and opaque fixtures. | High-volume remote streaming after contracts stabilize |
| pypdf optional extraction | Bundled Poppler/MuPDF | GPL/AGPL or commercial-license consequences are disproportionate for v1. | Separate process/package after legal review and a demonstrated extraction-quality need |
| Materialized vendoring | Git submodules or runtime cloning | Submodules/runtime clones break offline installation and permit missing or drifting dependencies. | Never for release artifacts; submodules may be maintainer-only update inputs |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| MCP Python SDK `2.0.0b1` or the not-yet-current `2026-07-28` protocol | Prerelease API and future protocol target; stable `pip install mcp` still resolves to 1.x | MCP `2025-11-25`, SDK `1.28.1,<2` for tests |
| Hook state as provenance | Hooks run concurrently, may be disabled/untrusted, and interception is incomplete | Python ledger/state kernel |
| Codex transcript parsing | Official docs say transcript format is not stable | Assignment/result envelopes and hook event fields |
| Graph/SQLite status as scientific truth | Cache loss or migration would alter provenance | Ledger, manifests, artifact hashes |
| In-place patching of ignored upstream checkouts | Non-reproducible and vulnerable to stale/partially applied patches | Verified clean snapshot plus numbered patch series |
| Unbounded filesystem MCP tools | Turns the server into a data-exfiltration and denial-of-service surface | Allowed roots, canonicalization, hard caps, pagination |
| Automatic network update checks | Makes local behavior non-reproducible and leaks environment metadata | Explicit `arw vendor update` workflow |
| Symlinked skill directories in release bundles | Existing ARS notes identify Windows plugin-cache registration problems | Materialized directories |
| A global Porter FTS tokenizer | English-only stemming harms multilingual and identifier search | Unicode61 plus trigram fallback |
| A blanket MIT plugin license | ARS and experiment-agent are CC BY-NC 4.0 | Accurate collective license inventory and commercial-use gate |
## Stack Patterns by Variant
- Use MCP stdio, local canonical run directories, and a user-cache SQLite projection.
- Use native Codex subagents with read-only assignments and parent-only canonical writes.
- Add Streamable HTTP, authenticated tenant roots, PostgreSQL for coordination, object storage for immutable artifacts, and a real task queue.
- Keep the same JSON Schemas and append-only evidence model; do not promote the graph to authority.
- Keep canonical artifacts on the mounted workspace if required.
- Keep SQLite/WAL cache local to each host or use rollback journaling; never share one WAL cache across hosts.
- Stop before vendoring ARS.
- Obtain a separate commercial license/grant or replace the ARS content with independently authored contracts.
- Add an explicit OCR adapter with separate dependency/license review and record its engine, version, language pack, confidence, and output hash.
- Never merge OCR text into “verified full text” without a quality gate.
## Version Compatibility
| Component | Compatible With | Notes |
|-----------|-----------------|-------|
| Python `3.14.6` | `mcp 1.28.1`, `pydantic 2.13.4`, pytest 9 | MCP 1.28.1 has explicit Python 3.14 dependency markers and requires Pydantic `>=2.12,<3`. |
| Python `3.13.x` | Same control-plane lock | CI compatibility floor; use a universal uv lock with Python markers. |
| MCP `2025-11-25` | file-base `ee68144...` | Source lists `2025-11-25`, `2025-06-18`, and `2025-03-26`; default is latest supported. |
| Codex CLI `0.144.1` | plugin manifest, hooks, subagents, stdio MCP | Verified local floor. Re-run smoke suite before raising it. |
| ARS adapter `0.1.19` | upstream commits listed above | `VERSION`, SKILL metadata, and adapter manifest must match. |
| file-base `ee68144...` | SQLite `3.51.3`, yyjson `0.12.0` | Versions are vendored in the pinned tree; do not upgrade them independently in v1. |
| uv `0.11.28` | `uv.lock`, CycloneDX 1.5 export | Pin uv itself; a lockfile does not pin the resolver executable. |
| Plugin hooks | Codex trust review | Changed hook definitions receive a new hash and are skipped until trusted. Runtime correctness cannot depend on trust having been granted. |
## Confidence Assessment
| Area | Confidence | Basis / Remaining Risk |
|------|------------|------------------------|
| Python control plane | HIGH | Current CPython and package metadata; aligns with existing ARS scripts and audit-heavy file workflows |
| file-base C data plane | HIGH | Exact local source/commit inspected; MCP versions, SQLite version, build system, patch, and licenses verified |
| Storage/index design | HIGH | Standard append/replay and SQLite/FTS patterns; graph-authority boundary is explicit |
| Schemas | HIGH | Pydantic and JSON Schema 2020-12 support verified from official docs |
| Codex plugin/hooks | MEDIUM | Official current docs are clear, but surface is evolving and hook trust/interception limit behavior |
| Subagent packaging | MEDIUM | Native subagents are supported; plugin-level custom-agent bundling is not documented, so v1 deliberately avoids it |
| Cross-platform release | MEDIUM | Upstream build system supports target platforms, but clean build and installation matrix still needs empirical gates |
| License viability | HIGH on facts, LOW on commercial permission | Licenses are verified; whether intended use satisfies CC BY-NC requires owner/legal determination |
## Sources
### Primary official sources
- [OpenAI: Build plugins](https://developers.openai.com/codex/plugins/build) — plugin structure, manifest fields, MCP config, hook packaging, trust, marketplace behavior.
- [OpenAI: Hooks](https://learn.chatgpt.com/codex/hooks) — event schemas, concurrency, trust, supported handler type, interception limits, transcript warning.
- [OpenAI: Subagents](https://developers.openai.com/codex/subagents) — native subagents, permissions, custom-agent locations and evolving format.
- [OpenAI: MCP](https://developers.openai.com/codex/mcp) — stdio configuration and plugin-scoped MCP policy.
- [OpenAI: Codex SDK](https://developers.openai.com/codex/sdk) — SDK roles, thread resume, Python beta status.
- [MCP specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) — current protocol version and security principles.
- [MCP Python SDK releases](https://github.com/modelcontextprotocol/python-sdk/releases) and [PyPI metadata for 1.28.1](https://pypi.org/pypi/mcp/1.28.1/json) — stable 1.x line and dependency constraints.
- [Python downloads and support status](https://www.python.org/downloads/) — Python 3.14.6 and supported release lines.
- [uv project layout and lockfile](https://docs.astral.sh/uv/concepts/projects/layout/), [locking/syncing](https://docs.astral.sh/uv/concepts/projects/sync/), and [build reproducibility](https://docs.astral.sh/uv/concepts/projects/build/) — frozen installs, universal lock, SBOM export, build constraints.
- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/) — Draft 2020-12 generation.
- [SQLite FTS5](https://www.sqlite.org/fts5.html) — Unicode61, trigram, external-content tables, and tokenizer limitations.
- [SQLite WAL](https://www.sqlite.org/wal.html) — reader/writer behavior, one-writer constraint, network filesystem prohibition.
- [Pinned file-base MIT license](https://github.com/DeusData/codebase-memory-mcp/blob/ee68144af5453addda995a27cce8142999f318fb/LICENSE).
- [Pinned ARS CC BY-NC 4.0 license](https://github.com/Imbad0202/academic-research-skills/blob/c22c17eed8a5753aa60681be9734919f2e2f5b42/LICENSE).
- [Pinned experiment-agent CC BY-NC 4.0 license](https://github.com/Imbad0202/experiment-agent/blob/9b063fa895eaf1f63ac99ac03f924f8d31aa8d26/LICENSE).
### Context7 lookups
- `/modelcontextprotocol/python-sdk` — structured output and in-memory/stdio testing patterns. Context7 indexed an older stable version, so exact current version came from official GitHub/PyPI metadata.
- `/pydantic/pydantic` — strict validation, discriminated unions, and JSON parsing.
- `/pytest-dev/pytest/9.0.0` — `tmp_path` and `monkeypatch` isolation patterns; exact current pytest version came from PyPI metadata.
- `/astral-sh/uv` — frozen locks, build constraints, pinning uv, and CycloneDX export.
### Local primary evidence inspected
- `/home/zhangyangrui/my_programes/academic-research-workbench/.planning/PROJECT.md`
- `/home/zhangyangrui/orca/workspaces/Examination/审查/experiments/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
- `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md`
- `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/references/science_workbench_mvp.md`
- `/home/zhangyangrui/.codex/skills/academic-research-suite/manifest.json`
- `/home/zhangyangrui/orca/projects/Paper4Master/.mcp.json`
- `/home/zhangyangrui/orca/projects/Paper4Master/.codex/config.toml`
- `/home/zhangyangrui/orca/projects/Paper4Master/scripts/build-file-base-mcp`
- `/home/zhangyangrui/orca/projects/Paper4Master/scripts/file-base-mcp`
- `/home/zhangyangrui/orca/projects/Paper4Master/patches/file-base-server-name.patch`
- `/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp` at `ee68144af5453addda995a27cce8142999f318fb`
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
