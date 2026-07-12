# Stack Research

**Domain:** Codex-native, headless academic research workbench plugin
**Researched:** 2026-07-12
**Confidence:** MEDIUM

## Recommendation in One Sentence

Build a small polyglot system: a Python 3.14 control plane for durable workflow state, schemas, hooks, and audit evidence; the pinned C/C++ file-base fork as the single files-first stdio MCP and rebuildable SQLite/FTS graph projection; and a materialized Codex plugin that vendors ARS unchanged and invokes versioned launchers installed by the same release bundle.

The confidence is MEDIUM rather than HIGH because the core runtime, MCP, SQLite, and license choices are well verified, but Codex plugin packaging and custom-agent authoring are still evolving. In particular, official plugin documentation defines skills, hooks, apps, and MCP configuration, but does not define a plugin-level custom-agent manifest field. The stack below therefore does not depend on one.

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

Use exact versions in `uv.lock`; the ranges below express compatibility policy, not permission to resolve fresh versions during release builds.

| Library | Version | Purpose | When to Use | License |
|---------|---------|---------|-------------|---------|
| `pydantic` | `2.13.4` (`>=2.13,<3`) | Strict runtime models and JSON Schema generation | All canonical record envelopes: run, state, event, assignment, result, artifact, source, claim, experiment, review, gate, waiver, and human-review item | MIT |
| `jsonschema` | `4.26.0` (`>=4.26,<5`) | Independent validation of checked-in schemas | CI drift checks, fixtures, and validating C-produced JSON without relying on the same Pydantic code that generated the schema | MIT |
| `portalocker` | `3.2.0` (`>=3.2,<4`) | Cross-platform advisory run locks | Serialize parent-orchestrator writes and test lock contention on Linux, macOS, and Windows | BSD-3-Clause |
| `platformdirs` | `4.10.0` (`>=4.10,<5`) | Per-user cache/data locations | Put disposable indexes, downloaded build caches, and installed runtime data outside research source trees; canonical run evidence still belongs in the workspace | MIT |
| `pypdf` | `6.14.2` (`>=6.14,<7`), optional extra | Permissively licensed PDF text extraction | Text-bearing PDFs only. Record extractor version and content hash. Image-only or failed extraction becomes a human/OCR review item, not silently empty evidence. | BSD-3-Clause |
| `mcp` Python SDK | `1.28.1` (`>=1.28.1,<2`), test dependency only | Protocol client and in-memory/stdio test harness | Black-box MCP conformance and Codex-facing integration tests. Do not put a Python MCP proxy in the production path. | MIT |
| `hatchling` | `1.31.0` | Build backend for the Python control-plane wheel | Build the `arw` CLI/hook package; keep platform-specific file-base binaries as separate release artifacts | MIT |

Do not add an ORM, workflow framework, web framework, message broker, or telemetry backend to v1. The standard library (`pathlib`, `hashlib`, `json`, `sqlite3`, `tempfile`, `os.replace`, `subprocess`) covers the remaining kernel needs.

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

Python owns:

- `arw init/status/resume/transition/checkpoint/finalize`;
- strict schema models and schema generation;
- the append-only ledger and atomic `state.json` projection;
- immutable assignment/result/artifact manifests;
- Material Passport and integrity-gate evaluation;
- hook executables;
- optional PDF extraction and human-review queue generation;
- release manifest, audit summary, and evidence-bundle generation.

It does not own graph truth, model transcripts, or a second full-text index.

### C/C++ owns the data plane

The pinned file-base source remains C11 with its existing C++14 preprocessor unit. It owns:

- MCP stdio framing and capability negotiation;
- allowed-root enforcement, canonical path checks, symlink escape rejection, and output caps;
- file discovery and incremental metadata updates;
- the `files` table and FTS5 indexes;
- code/document structural graph extraction;
- validated research-manifest projection and bounded graph queries.

Do not port file-base to Python or Rust in v1. A rewrite would discard the tested parsers, incremental index, graph query layer, and existing C test suite without improving the authoritative provenance model.

## Storage and Indexing

### Canonical storage: files, not a database

Keep the existing run layout under the research workspace:

```text
experiments/runs/<task_slug>__<YYYYMMDD-HHMMSS>__<hash8>/
  run_manifest.json
  state.json
  passport.json
  events.jsonl
  assignments/
  results/
  input/
  evidence/
  experiment/
  paper/
  reviews/
  audit/
  exports/
```

`events.jsonl`, immutable artifacts, and manifests are authoritative. `state.json` is a replaceable current-state projection. Every event envelope should contain:

- `schema_version`, `event_id`, `command_id`, `run_id`, and monotonic `sequence`;
- UTC RFC 3339 timestamp;
- expected and resulting state revision;
- `event_type` discriminator and typed payload;
- actor/agent/assignment IDs where relevant;
- `prev_event_sha256` and `event_sha256` over deterministic UTF-8 JSON bytes.

For deterministic bytes, serialize with sorted keys, compact separators, UTF-8, and no NaN/Infinity. Keep floating-point measurements out of the hash envelope or serialize them as declared decimal strings.

### Crash-safe write protocol

Use one cross-platform lock per run. The parent orchestrator is the only canonical writer.

1. Validate command ID, expected revision, and transition.
2. Write immutable artifact/result to a temporary file in the destination directory; flush and `fsync`.
3. Rename with `os.replace`; `fsync` the directory where supported.
4. Append one complete event line; flush and `fsync`.
5. Regenerate `state.json` from the accepted event sequence, write-temp/flush/`fsync`/replace.
6. On resume, validate the hash chain and replay the ledger; never trust a newer-looking `state.json` over the ledger.

Idempotency comes from `command_id`; stale worker output is rejected by assignment input hash and expected state revision.

### Rebuildable SQLite projection

Use the file-base database only as a cache. Store it in the user cache directory, keyed by SHA-256 of the canonical allowed root, rather than beside manuscripts. Every projected row carries canonical path, source SHA-256, schema version, and indexed timestamp.

Recommended file schema:

```sql
files(
  file_id INTEGER PRIMARY KEY,
  rel_path TEXT NOT NULL UNIQUE,
  mime TEXT NOT NULL,
  extension TEXT,
  language TEXT,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  mtime_ns INTEGER NOT NULL,
  line_count INTEGER,
  is_binary INTEGER NOT NULL,
  extraction_state TEXT NOT NULL,
  indexed_at TEXT NOT NULL
)
```

Use external-content FTS5 tables linked to `files`/document text:

- `unicode61 remove_diacritics 2` for English prose, identifiers, paths, Markdown, BibTeX, and LaTeX tokens;
- a separate `trigram` index for CJK and substring fallback.

Do not use Porter stemming globally; SQLite documents that it is English-specific. Trigram queries shorter than three Unicode characters require an explicit bounded fallback because they do not match normally. Tests must cover Chinese without spaces, LaTeX control sequences, citation keys, DOI strings, and mixed CJK/Latin text.

Use WAL only for a local cache on one host. SQLite explicitly does not support WAL over network filesystems and permits only one writer at a time. If a cache path is detected on a network filesystem, use rollback-journal mode or refuse that cache location; canonical run files remain unaffected.

## Files-First MCP Contract

Expose these read-only tools from the C file-base server:

- `list_files`
- `read_file`
- `search_files`
- `get_file_outline`
- `get_file_context`
- `ingest_research_manifest`
- `sync_research_run`

Every tool gets an explicit input and output JSON Schema and returns MCP `structuredContent` plus a compact text rendering for compatibility. Required common fields include `schema_version`, `root_id`, `rel_path`, `sha256`, result count, truncation state, and next cursor where applicable.

Hard requirements:

- resolve the candidate path and its ancestors before checking it against allowed roots;
- reject absolute paths, `..` escape, symlink escape, device files, sockets, and unapproved roots;
- cap bytes, lines, rows, snippets, traversal depth, and query time server-side;
- paginate lists and search results with opaque cursors;
- distinguish `not_found`, `not_indexed`, `binary`, `too_large`, `unsupported`, `extraction_failed`, and `access_denied`;
- keep reads side-effect free; indexing/sync tools remain separately approval-gated;
- disable upstream update checks in reproducible/offline mode.

Use pypdf in the Python preprocessing path for text-bearing PDFs and feed a hashed extraction artifact to file-base. Do not bundle Poppler or MuPDF merely for v1 extraction: Poppler introduces GPL obligations and MuPDF is AGPL/commercial. OCR is an optional, explicitly invoked adapter; scanned PDFs default to `blocked_human_review` or `extraction_failed`, never to “verified.”

## Schemas and Validation

### Contract source

Author schemas as strict Pydantic models with:

- `ConfigDict(strict=True, extra="forbid")`;
- discriminated unions on `event_type`, `result_type`, `artifact_type`, and `gate_type`;
- explicit `schema_version` literals;
- constrained IDs, relative paths, SHA-256 strings, timestamps, and sequence numbers;
- no implicit datetime, number, or enum coercion at canonical boundaries.

Generate and commit Draft 2020-12 schemas under `schemas/v1/`. Treat those checked-in files as the cross-language contract consumed by C and fixtures. CI regenerates schemas and fails on drift. A schema change requires either backward-compatible additive change or a new schema version plus migration/replay tests.

Use the independent `jsonschema` validator against generated schemas in CI. This catches the failure mode where Pydantic both produces and validates an incorrect contract.

### C validation

Continue using vendored yyjson `0.12.0` for parsing. Validate required fields, types, bounds, enum values, and unknown-field policy before projecting a research manifest. Never infer canonical claims, gates, or run status from Markdown prose.

## Codex Plugin, Subagents, and Hooks

### Plugin structure

Assemble a materialized release tree:

```text
plugin/
  .codex-plugin/plugin.json
  .mcp.json
  skills/
    academic-research-workbench/SKILL.md
    academic-research-suite/
      SKILL.md
      manifest.json
      ars/...
  hooks/
    hooks.json
    arw_hook.py
  assets/
  LICENSES/
  THIRD_PARTY_NOTICES.md
```

Only `plugin.json` belongs under `.codex-plugin/`. All manifest component paths start with `./` and remain inside the plugin root.

### Subagent strategy

Use Codex's native subagent workflow, initiated by the workbench skill and parent orchestrator. Store ARS role prompts under the skill as source prompts. Each child receives an immutable assignment snapshot containing input hashes, allowed roots, output schema, and policy; it returns a schema-valid result envelope. The parent accepts results in deterministic task order and is the sole canonical writer.

Do not make v1 depend on plugin-bundled custom-agent TOML. Official Codex documentation currently defines custom agents only under `~/.codex/agents/` or project `.codex/agents/`, says that format may evolve, and the plugin manifest has no `agents` field. Project-scoped custom profiles may be offered later as an optional installer feature, not as the runtime contract.

### Hook strategy

Use command hooks only; Codex currently parses but skips prompt/agent hook handlers.

- `SessionStart`: locate and validate the selected run/passport and add concise context.
- `SubagentStart`: inject assignment ID, hashes, allowed roots, and output contract.
- `SubagentStop`: validate the result envelope and request continuation if incomplete.
- `PreToolUse`: deny supported obvious violations for Bash, `apply_patch`, and MCP calls.
- `PostToolUse`: record lightweight evidence and schedule projection sync.
- `Stop`: continue only when the current user-requested deliverable or mandatory gate remains open.

Hooks are defense in depth, not the state machine or security boundary. Official documentation says `PreToolUse` interception is incomplete, does not cover every shell/tool path, and `SubagentStart` cannot stop startup. Also, plugin hooks are skipped until users review and trust their current hash. The CLI/runtime must remain correct when hooks are absent, disabled, changed, or run concurrently.

Never parse Codex transcript files as a stable API; the hook documentation explicitly says the transcript format may change.

## Packaging and Reproducible Builds

### Source vendoring

Use materialized source snapshots, not submodules and not mutable ignored checkouts:

```text
vendor/
  manifest.lock.json
  ars/                       # immutable selected files
  file-base/upstream/        # exact upstream tree
patches/
  file-base/0001-server-name.patch
  file-base/0002-files-first.patch
  file-base/0003-research-projection.patch
```

`manifest.lock.json` records repository URL, full commit, Git tree SHA, included/excluded paths, source archive SHA-256, license ID, license file SHA-256, patch list, and patch SHA-256. Build in a fresh temporary copy, verify the upstream tree first, apply patches with `git apply --check`, and fail if any patch is already applied or fuzzy.

Do not reuse Paper4Master's current build script unchanged: it mutates the checkout in place and detects patch state with source-text greps. That is convenient locally but is not a reproducible release build.

### Release artifacts

Produce versioned, platform-specific release bundles containing:

1. the materialized plugin tree;
2. a pure Python `arw` wheel and frozen `uv.lock`;
3. the matching file-base binary for the platform;
4. `SHA256SUMS`, build manifest, SBOM, source/patch manifest, and third-party notices;
5. a small installer that installs stable `arw`, `arw-hook`, and `academic-research-workbench-file-base` launchers, then registers the marketplace/plugin.

Use a PATH launcher name in `.mcp.json`, matching the official plugin examples that invoke an MCP command. Do not assume `${PLUGIN_ROOT}` is provided to MCP processes: OpenAI currently documents `PLUGIN_ROOT` and `PLUGIN_DATA` for plugin hooks, not for MCP subprocess environment expansion. The combined private installer must install the launcher before enabling the MCP server and must fail its smoke test if command discovery is wrong.

Codex marketplace installs do not run npm lifecycle scripts. Therefore, do not rely on plugin installation to compile C, create a Python environment, or download ARS/file-base. Build and verify those artifacts before plugin registration.

Recommended initial binary matrix:

- Linux x86_64 and arm64: static musl build where file-base tests pass;
- macOS arm64 and x86_64: pinned Xcode/Clang image;
- Windows x86_64: pinned MinGW-w64 image.

Set `SOURCE_DATE_EPOCH` from the pinned upstream commit, strip build paths with compiler prefix-map flags, omit timestamps from generated C data, and record compiler/linker versions. Reproducibility means a clean build from the lock manifests yields equivalent binaries and identical source/SBOM inputs; make bit-for-bit equality a release gate once toolchain normalization is proven.

### License gate — mandatory before vendoring

Actual licenses were verified from both local snapshots and the pinned GitHub commits:

| Component | Pin | Verified License | Required Action |
|-----------|-----|------------------|-----------------|
| academic-research-skills | `c22c17e...` | CC BY-NC 4.0 | Preserve attribution, license, notices, and modification markings. Do not distribute or use for a primarily commercial purpose without separate permission. |
| experiment-agent | `9b063fa...` | CC BY-NC 4.0 | Same restriction and attribution duty as ARS. |
| codebase-memory-mcp / file-base | `ee68144...` | MIT | Preserve copyright and MIT text in source and binary distributions. |
| file-base bundled dependencies | Pinned inside `ee68144...` | MIT, Apache-2.0, BSD-2-Clause/BSD-like, public-domain SQLite; see upstream notices | Preserve upstream generated notices and rerun the license gate after every source refresh. |
| pypdf | `6.14.2` | BSD-3-Clause | Include in Python SBOM/notices when the PDF extra ships. |

This is a hard product constraint, not paperwork. A private repository does not automatically make business use “NonCommercial.” If the workbench will be distributed or used primarily for commercial advantage, obtain an ARS commercial grant or replace the vendored ARS content before release. Do not label the whole plugin simply `MIT`; use an accurate SPDX expression/`LicenseRef` and `LICENSES/` inventory for the collective package.

## Installation and Verification

```bash
# Pinned Python and dependencies
uv python install 3.14.6
uv sync --frozen --python 3.14.6

# Verify vendored sources, commits, licenses, and patch hashes
uv run arw vendor verify

# Build file-base from a clean temporary source tree
uv run arw build file-base --clean --locked

# Python and protocol tests
uv run pytest -q

# C safety suites; exact wrapper target may differ by platform
make -C build/file-base-src -f Makefile.cbm test
make -C build/file-base-src -f Makefile.cbm test-tsan

# Reproducibility and inventory gates
uv lock --check
uv export --format cyclonedx1.5 -o dist/python-sbom.cdx.json
uv run arw release verify dist/
```

Release verification must also start the installed MCP launcher over stdio, negotiate `2025-11-25`, list tools, validate every tool schema, index a multilingual fixture, execute bounded reads/searches, delete the cache, rebuild it, and compare query results.

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

Every end-to-end test writes an inspectable evidence directory containing commands, exit codes, wall time, environment manifest, logs, hashes, assertions, and final gate verdict. “Test passed” without evidence is insufficient for this project.

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

**For local v1 headless use:**

- Use MCP stdio, local canonical run directories, and a user-cache SQLite projection.
- Use native Codex subagents with read-only assignments and parent-only canonical writes.

**For a future remote/multi-user service:**

- Add Streamable HTTP, authenticated tenant roots, PostgreSQL for coordination, object storage for immutable artifacts, and a real task queue.
- Keep the same JSON Schemas and append-only evidence model; do not promote the graph to authority.

**For network-mounted research workspaces:**

- Keep canonical artifacts on the mounted workspace if required.
- Keep SQLite/WAL cache local to each host or use rollback journaling; never share one WAL cache across hosts.

**For commercial distribution or business-primary use:**

- Stop before vendoring ARS.
- Obtain a separate commercial license/grant or replace the ARS content with independently authored contracts.

**For scanned PDFs:**

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

---
*Stack research for: Academic Research Workbench v1.0 headless core*
*Researched: 2026-07-12*
