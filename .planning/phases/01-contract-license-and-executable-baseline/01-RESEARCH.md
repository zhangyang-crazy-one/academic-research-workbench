# Phase 1: Contract, License, and Executable Baseline - Research

**Researched:** 2026-07-13
**Domain:** Codex plugin packaging, reproducible source/licensing, append-only provenance, and confined local MCP execution
**Confidence:** HIGH for architecture and local executable baselines; MEDIUM for host behavior pending the required installed-package probes

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### D-01 Plugin identity and installability
- The product name is `Academic Research Workbench`; the plugin/repository slug is `academic-research-workbench`.
- The repository must contain a valid `.codex-plugin/plugin.json`, one routable skill, MCP configuration, hook declarations or stubs that match supported plugin contracts, and stable launcher entrypoints.
- Validation must exercise a staged or installed plugin path, not only the source checkout.

### D-02 Headless walking skeleton
- The first executable slice is install -> skill route -> runtime init/append/replay -> bounded MCP fixture read -> evidence output.
- No desktop, browser, or synthetic UI is required. CLI output and versioned JSON/Markdown artifacts are the user interaction for Phase 1.
- A successful demo must be repeatable from a clean checkout and must not depend on absolute paths into Paper4Master, Examination, or the developer's home directory.

### D-03 Canonical authority
- A short-lived Python control-plane CLI is the only canonical writer.
- Canonical events are deterministic, sequence ordered, and hash chained from the first Phase 1 fixture.
- SQLite, FTS, graph data, hook logs, transcripts, and generated state are projections or observations, never authority.
- Hooks and workers cannot write accepted state directly.

### D-04 Source pinning and bundling
- Pin file-base to upstream commit `ee68144af5453addda995a27cce8142999f318fb` and preserve the existing Paper4Master patch as an ordered, hashed patch input.
- Pin the selected ARS 0.1.19 source snapshot and record its exact tree digest and upstream provenance before adapting it.
- Materialize reproducible source snapshots and patch series; do not depend on mutable submodules, upstream branches, ignored local checkouts, or runtime network clones.
- Preserve upstream license texts, modification markings, third-party notices, source manifests, dependency locks, and SBOM inputs.

### D-05 Licensing gate
- ARS/experiment-agent CC BY-NC 4.0 content and file-base MIT content must remain separately identified; the collective plugin must not be labeled simply MIT.
- Private repository status is not treated as proof of noncommercial use.
- Development may proceed, but release qualification must fail until intended use/distribution classification and any required owner permission are recorded.
- The staged package must exclude private papers, extracted full text, run data, credentials, and indexes by default.

### D-06 MCP confinement probe
- The MCP process receives explicit allowed roots and enforces path, symlink/junction, sensitive-file, and output-budget restrictions internally.
- Hooks may warn or hydrate context but are not accepted as the filesystem security boundary.
- Phase 1 may use a thin fixture-level MCP command surface, but traversal, escape, disallowed-root, sensitive-path, and over-budget probes must be executable and preserve evidence.

### D-07 Version and schema identity
- One command must report plugin, runtime, ARS snapshot, file-base snapshot, patch set, and schema versions.
- Cross-language contracts use checked-in JSON Schema with independent validation at the runtime/MCP boundary.
- Source, patch, schema, and staged-artifact digest drift is a build failure.

### D-08 Compatibility probes
- Installed MCP launcher resolution, custom-agent distribution, Codex hook behavior, experiment ownership, operating-system support, and exact retrieval budgets are empirical probes rather than assumed product capabilities.
- Native Codex subagents plus immutable assignment-injected ARS roles are the required fallback; plugin-native custom-agent registration is optional unless proven by the supported contract.
- Controlled experiment execution remains disabled; Phase 1 only records the decision/probe contract for later phases.

### D-09 Verification evidence
- Every Phase 1 smoke, schema, digest, install, launcher, confinement, and recovery probe writes inspectable raw output plus a concise verdict.
- The seed recovery case includes init, append, forced stop, replay, and last-valid-revision evidence.
- Tests must assert behavior from a clean staged package and use repository-owned fixtures.

### the agent's Discretion
- Exact Python package layout, CLI framework or standard-library argument parsing, build tool details, and test runner organization.
- Whether the append-only Phase 1 journal uses one file or sealed segments, provided later crash/fault testing can evolve without rewriting accepted evidence.
- Initial supported OS matrix; Linux x86_64 may be the first proven target if other platforms remain explicitly unclaimed.
- Exact byte, row, page, and timeout defaults for Phase 1 fixtures, provided limits are explicit, small, and reported in tool results.

### Deferred Ideas (OUT OF SCOPE)
- Full runtime lifecycle, Passport checkpointing, stale worker rejection, and comprehensive fault recovery belong to Phase 2.
- Production files-first indexing and research-format retrieval belong to Phase 3.
- Full subagent execution, independent reviewer panels, and human gate UX belong to Phase 4.
- Semantic graph projection and evidence-chain queries belong to Phase 5.
- Complete integrity receipts and audit dossier belong to Phase 6.
- Cross-matrix installed-package release qualification belongs to Phase 7.
- Desktop UI, domain packs, remote collaboration, and telemetry remain v2 or later.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| PKG-01 | Install from a clean checkout and pass manifest validation. | Repository layout, stage builder, plugin validator, isolated local marketplace smoke. [CITED: `.planning/REQUIREMENTS.md`] |
| PKG-02 | Invoke the workbench skill and route to a declared ARS workflow family and execution mode. | One thin routable skill plus a schema-constrained `route` result and authenticated staged Codex smoke. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`] |
| PKG-03 | Installed plugin starts bundled files-first MCP without a source-checkout absolute path. | Staged launcher canary and isolated install probe; relative-launch behavior is measured before the final launcher is frozen. [VERIFIED: local `codex-cli 0.144.1` help] |
| PKG-04 | One command reports plugin, runtime, ARS, file-base, schema, and patch-set versions. | `arw version --json` reads only checked-in/generated build manifests. [CITED: `.planning/REQUIREMENTS.md`] |
| SUP-01 | Reproduce ARS and file-base trees from revisions and ordered patches. | Materialized vendor inputs, source manifest, clean temporary patch application. [CITED: `.planning/research/SUMMARY.md`] |
| SUP-02 | Fail on source, patch, lock, or artifact digest drift. | Manifest verifier plus one mutation-negative fixture per digest class. [CITED: `.planning/REQUIREMENTS.md`] |
| SUP-03 | Stage licenses, notices, SBOM, and machine-readable source manifest. | Prescribed `LICENSES/`, notices, CycloneDX export, build/source manifests, and inventory gate. [VERIFIED: local `uv 0.11.28` supports `cyclonedx1.5`] |
| SUP-04 | Block release until use/distribution satisfies every license or records permission. | Machine-readable licensing decision with PASS/BLOCKED verdict; technical smoke may pass while release remains BLOCKED. [CITED: ARS CC BY-NC 4.0 license; `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`] |
| SUP-05 | Exclude papers, extracted text, run data, credentials, indexes, and private material. | Allowlist-based stage assembly plus forbidden-canary scan. [CITED: `.planning/REQUIREMENTS.md`] |
| RUN-01 | Initialize run identity, immutable input snapshot, schema, mode, and capabilities. | Minimal strict run manifest and `run.initialized` event. [CITED: `.planning/REQUIREMENTS.md`] |
| RUN-02 | Sole writer appends deterministic sequence-ordered hash-chained events. | Locked JSONL append, canonical JSON bytes, injected IDs/clock, hash-chain and contention tests. [CITED: `.planning/research/SUMMARY.md`] |
| FILE-05 | Reject traversal, escape, disallowed roots, sensitive files, and over-budget requests before content. | Linux-first descriptor-safe read probe with explicit deny policy and no-content negative assertions. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`] |
| VER-01 | Independently validate schemas across Python and MCP boundaries and block drift. | Pydantic generation, checked-in Draft 2020-12 schemas, independent `jsonschema` validation, and C/MCP fixture responses. [CITED: `.planning/research/SUMMARY.md`] |
</phase_requirements>

## Summary

Phase 1 should be implemented as one narrow walking skeleton: a valid staged Codex plugin routes one request, a short-lived Python CLI initializes and appends to a canonical JSONL journal under an inter-process lock, a bundled file-base process performs one internally confined fixture read, and every operation emits raw and summarized evidence. This directly exercises all 13 Phase 1 requirements without implementing Phase 2 lifecycle semantics or Phase 3 indexing. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`]

The existing Paper4Master build and launcher scripts are import references, not release tooling. The build script patches a mutable checkout in place and checks marker strings rather than commit/tree/patch digests; the launcher defaults the allowed root and cache to the source project. The supplied patch adds text/PDF-file discovery and renames the server, but it does not establish the complete FILE-05 boundary. Phase 1 must replace those assumptions with clean materialization, hashed ordered patches, staged-relative launchers, and executable confinement probes. [VERIFIED: `/home/zhangyangrui/orca/projects/Paper4Master/scripts/build-file-base-mcp`; `/home/zhangyangrui/orca/projects/Paper4Master/scripts/file-base-mcp`; `/home/zhangyangrui/orca/projects/Paper4Master/patches/file-base-server-name.patch`]

The legal outcome is deliberately two-dimensional: technical qualification may pass, while release qualification remains `BLOCKED` until intended use/distribution and any permission are recorded. The staged bundle must preserve the distinct CC BY-NC 4.0 and MIT inputs rather than claim a blanket MIT license. [CITED: ARS CC BY-NC 4.0 license; file-base MIT license; `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`]

**Primary recommendation:** Build and test the smallest complete `stage -> install -> route -> init -> append -> forced-stop -> replay -> confined-read -> evidence` path, and make every uncertain Codex host behavior an evidence-producing canary inside that path. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`]

## Project Constraints (from AGENTS.md)

- Deliver through Codex plugin and MCP transport contracts; a design-only result is insufficient. [CITED: `AGENTS.md`]
- Keep append-only ledger and immutable artifact manifests authoritative; graph and other mutable state are not provenance authority. [CITED: `AGENTS.md`]
- Pin necessary upstream code with reviewable patch and license inventory. [CITED: `AGENTS.md`]
- Preserve ARS workflow semantics and expose file-base only through bounded machine-readable tools. [CITED: `AGENTS.md`]
- Restrict file access to explicit allowed roots and bound outputs. [CITED: `AGENTS.md`]
- Keep v1 headless and testable. [CITED: `AGENTS.md`]
- No project-defined skills were present; this research follows the explicitly supplied plugin-creator skill. [VERIFIED: `AGENTS.md` project-skill index]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Plugin discovery and skill routing | Codex host/plugin bundle | Python CLI | The host discovers metadata and skills; the CLI returns deterministic routing records. [CITED: plugin-creator `SKILL.md`] |
| Canonical run mutation | Python control plane | Filesystem storage | One short-lived process validates, locks, appends, fsyncs, and replays; stored files are the authority. [CITED: `.planning/research/SUMMARY.md`] |
| Fixture file access | C/C++ MCP data plane | Plugin launcher | The MCP process owns root/path/budget checks; the launcher only supplies configuration. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`] |
| Source and license reproducibility | Build/staging tier | CI evidence runner | Clean materialization and digest gates precede staging; CI preserves verdicts. [CITED: `.planning/REQUIREMENTS.md`] |
| Schema compatibility | Checked-in contract tier | Python and C/MCP adapters | Both sides consume or are tested against the same versioned JSON Schema. [CITED: `.planning/research/SUMMARY.md`] |
| Release classification | Qualification gate | Staged inventory | A machine-readable decision evaluates the exact staged components. [CITED: `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md`] |

## Standard Stack

### Core

| Component | Version / Pin | Purpose | Why Standard for This Phase |
|---|---|---|---|
| Codex plugin contract | Test floor `codex-cli 0.144.1` | Manifest, staged install, skill routing, MCP discovery | This exact CLI and its `plugin marketplace add`, `plugin add`, and `exec` surfaces are locally available. [VERIFIED: local CLI help] |
| Python | `>=3.13,<3.15`; build/test with `3.14.6` | Sole-writer CLI and schema models | Matches the synthesized project stack and is installed locally through uv/system Python. [VERIFIED: local `uv python list`; CITED: `.planning/research/SUMMARY.md`] |
| ARS adapter | `0.1.19`; source `c22c17eed8a5753aa60681be9734919f2e2f5b42`; experiment-agent `9b063fa895eaf1f63ac99ac03f924f8d31aa8d26` | Workflow family/mode semantics and routable source snapshot | These are locked synthesized source inputs; Phase 1 records their tree digests before adaptation. [CITED: `AGENTS.md`; `.planning/research/SUMMARY.md`] |
| file-base | `ee68144af5453addda995a27cce8142999f318fb` plus ordered patch | Bundled stdio MCP and fixture read | The named local checkout is at the exact revision; its worktree is modified, so release builds must reconstruct a clean tree and apply the patch. [VERIFIED: local `git rev-parse` and `git status`] |
| MCP | `2025-11-25`, stdio | Local host/data-plane boundary | This is the already-synthesized contract target and is supported by the pinned file-base baseline. [CITED: `.planning/research/SUMMARY.md`] |
| JSON Schema | Draft 2020-12 | Cross-language contracts | Checked-in schemas give Python and MCP responses one independently testable boundary. [CITED: `.planning/research/SUMMARY.md`] |

### Python and Test Packages

| Package | Version | Purpose | Provenance |
|---|---|---|---|
| `pydantic` | `2.13.4` (published 2026-05-06) | Strict canonical models and schema generation | [VERIFIED: PyPI registry + slopcheck] |
| `jsonschema` | `4.26.0` (published 2026-01-07) | Independent checked-in-schema validation | [VERIFIED: PyPI registry + slopcheck] |
| `portalocker` | `3.2.0` (published 2025-06-14) | Cross-process sole-writer lock | [VERIFIED: PyPI registry + slopcheck] |
| `hatchling` | `1.31.0` (published 2026-07-08) | Python build backend | [VERIFIED: PyPI registry + slopcheck] |
| `pytest` | `9.1.1` (published 2026-06-19) | Unit, schema, integration, staged-smoke tests | [VERIFIED: PyPI registry + slopcheck] |

**Installation:**

```bash
uv sync --frozen
```

Commit `pyproject.toml`, `.python-version`, and `uv.lock`; export the SBOM with `uv export --frozen --format cyclonedx1.5 --output-file build/stage/academic-research-workbench/SBOM.cdx.json`. [VERIFIED: local `uv 0.11.28` help; CITED: `.planning/research/SUMMARY.md`]

### Alternatives Considered

| Instead of | Could Use | Decision |
|---|---|---|
| Single JSONL journal | Sealed segments | Use one journal in Phase 1; keep event bytes and schemas stable so Phase 2 can segment without rewriting accepted events. [CITED: CONTEXT D-03 and discretion] |
| `portalocker` | Convention-only single process | Use `portalocker`; RUN-02 requires an enforceable sole-writer boundary. [CITED: `.planning/REQUIREMENTS.md`] |
| Pydantic + independent `jsonschema` | One validator for generation and validation | Keep independent validation to detect schema/code drift. [CITED: `.planning/research/SUMMARY.md`] |
| Materialized sources | Submodules or runtime clones | Use materialized snapshots and ordered patches; mutable/network inputs are explicitly forbidden. [CITED: CONTEXT D-04] |

## Package Legitimacy Audit

| Package | Registry | First Release | Downloads | Source Repo | slopcheck | Disposition |
|---|---|---|---|---|---|---|
| `pydantic` | PyPI | 2017-05-03 | Not reported by PyPI JSON | `github.com/pydantic/pydantic` | OK | Approved. [VERIFIED: PyPI registry + slopcheck] |
| `jsonschema` | PyPI | 2012-01-02 | Not reported by PyPI JSON | `github.com/python-jsonschema/jsonschema` | OK | Approved. [VERIFIED: PyPI registry + slopcheck] |
| `portalocker` | PyPI | 2011-02-23 | Not reported by PyPI JSON | `github.com/wolph/portalocker` | OK | Approved. [VERIFIED: PyPI registry + slopcheck] |
| `hatchling` | PyPI | 2022-01-09 | Not reported by PyPI JSON | `github.com/pypa/hatch` | OK | Approved. [VERIFIED: PyPI registry + slopcheck] |
| `pytest` | PyPI | 2010-11-25 | Not reported by PyPI JSON | `github.com/pytest-dev/pytest` | OK | Approved. [VERIFIED: PyPI registry + slopcheck] |

**Packages removed due to slopcheck `[SLOP]` verdict:** none. [VERIFIED: slopcheck 0.6.1]

**Packages flagged as suspicious `[SUS]`:** none. [VERIFIED: slopcheck 0.6.1]

## Architecture Patterns

### System Architecture Diagram

```text
clean checkout
    |
    v
source verifier --> clean ARS/file-base snapshots --> ordered patches --> stage allowlist
    |                                                            |
    |                                                            v
    |                                        staged Codex plugin + manifests/licenses/SBOM
    |                                                            |
    |                                                            v
    |                                     isolated local marketplace install
    |                                                            |
    v                                                            v
evidence runner <--- verdict/raw logs <--- Codex skill route ---> Python `arw` CLI
    ^                                                        init | append | replay
    |                                                             v
    |                                                   locked canonical JSONL
    |                                                             |
    |                                                             v
    +--- confinement verdict <--- staged MCP launcher ---> file-base fixture read
                                                         | allow root?
                                                         | safe path?
                                                         | sensitive?
                                                         | within budget?
                                                         +--> content OR typed denial
```

The Python journal is the only canonical state path; plugin-host output, MCP cache, and evidence summaries are observations. [CITED: CONTEXT D-03]

### Recommended Repository Structure

```text
academic-research-workbench/
├── .codex-plugin/plugin.json
├── .mcp.json
├── hooks/hooks.json                     # valid no-op/minimal stubs; not canonical writers
├── skills/academic-research-workbench/SKILL.md
├── pyproject.toml
├── uv.lock
├── src/arw/
│   ├── cli.py                           # route, init, append, replay, version, doctor
│   ├── canonical.py                     # canonical JSON bytes + SHA-256
│   ├── models.py                        # strict Pydantic models
│   ├── journal.py                       # lock, append, fsync, replay
│   └── evidence.py                      # command/verdict artifact writer
├── schemas/v1/
│   ├── run-manifest.schema.json
│   ├── event.schema.json
│   ├── route-result.schema.json
│   ├── mcp-read-request.schema.json
│   ├── mcp-read-result.schema.json
│   ├── source-manifest.schema.json
│   └── version-report.schema.json
├── vendor/
│   ├── sources/ars/
│   ├── sources/file-base/
│   ├── patches/file-base/0001-file-base-server-name.patch
│   ├── source-manifest.json
│   └── LICENSES/
├── LICENSES/                            # staged collective license inventory
├── THIRD_PARTY_NOTICES.md
├── MODIFICATIONS.md
├── supply-chain/use-distribution.json
├── scripts/
│   ├── verify-sources
│   ├── build-file-base
│   ├── file-base-mcp
│   ├── stage-plugin
│   ├── smoke-staged-plugin
│   └── verify-phase-1
├── tests/
│   ├── unit/
│   ├── schema/
│   ├── integration/
│   ├── staged/
│   └── fixtures/{confinement,recovery,private-canaries}/
└── build/                               # generated stage, marketplace, run roots, evidence
```

Build the staged tree from an explicit allowlist; never copy the repository wholesale and then delete denylisted files. [CITED: CONTEXT D-05]

### Pattern 1: Strict, Deterministic Event Envelope

Use exactly two event variants in Phase 1: `run.initialized` and `baseline.probe_recorded`. Keep later lifecycle events out of this phase. [CITED: phase boundary and deferred ideas in CONTEXT]

Required common fields are `schema_version`, `event_type`, `event_id`, `command_id`, `run_id`, `sequence`, `occurred_at`, `expected_revision`, `resulting_revision`, `actor_id`, `prev_event_sha256`, typed `payload`, and `event_sha256`. The first event uses 64 zeroes for `prev_event_sha256`; `event_sha256` is SHA-256 over canonical UTF-8 JSON excluding that field. [CITED: CONTEXT D-03; implementation recommendation]

```python
# Source: project contract plus Python standard library
def canonical_event_bytes(event_without_hash: dict[str, object]) -> bytes:
    return (
        json.dumps(
            event_without_hash,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

event_hash = hashlib.sha256(canonical_event_bytes(unsigned_event)).hexdigest()
```

Tests inject IDs and UTC timestamps so two runs produce byte-identical fixture journals. Production defaults may generate values, but all accepted values are serialized explicitly. [CITED: CONTEXT D-03 and D-09]

### Pattern 2: Sole-Writer Append Protocol

For each mutation: acquire the run lock, replay and validate the current tail/hash/revision, compare expected revision, canonicalize one event, append the complete line, flush and `fsync`, then release. Derived `state.json` may be written afterward and is never needed for replay. [CITED: `.planning/research/SUMMARY.md`; implementation recommendation]

The Phase 1 forced-stop fixture kills the writer immediately after journal `fsync` and before derived state output. A fresh process must replay the durable event, report its revision/hash, and avoid appending a duplicate. [CITED: CONTEXT D-09]

### Pattern 3: Checked-In Schema as the Cross-Language Boundary

Pydantic models generate schemas; committed schemas are drift-checked; `jsonschema` validates run/event fixtures and the JSON returned by the C/MCP read probe. The MCP request/result boundary stays minimal: relative `path`, allowed-root capability identifier, `max_bytes`, and a result union of `ok` or typed denial with zero content on denial. [CITED: CONTEXT D-07 and D-06]

Do not expose production indexing/search schemas in Phase 1. [CITED: deferred Phase 3 scope]

### Pattern 4: Staged Plugin Smoke Path

1. Assemble `build/stage/academic-research-workbench/` from the allowlist and generate its build/source/schema digest inventory. [CITED: CONTEXT D-04/D-05]
2. Run `python3 .../plugin-creator/scripts/validate_plugin.py build/stage/academic-research-workbench`. The manifest must name `academic-research-workbench`; it should point to `./skills/` and `./.mcp.json`, and must not declare unsupported top-level `hooks`. [CITED: plugin-creator `SKILL.md` and `plugin-json-spec.md`]
3. Copy the exact stage into `build/marketplace/plugins/academic-research-workbench/`, create a repo-owned temporary marketplace, and run Codex with isolated `HOME`/`CODEX_HOME`. [VERIFIED: local `codex plugin marketplace add` and `plugin add` help]
4. Add the marketplace and plugin, capture `--json` install output, and start a fresh ephemeral `codex exec` for the routable-skill canary. [CITED: plugin-creator `installing-and-updating.md`; VERIFIED: local CLI help]
5. Probe the initial staged-relative `.mcp.json` launcher candidate. If the host does not resolve it, record that raw failure and implement the cache-local launcher strategy proven by the probe; never fall back to a Paper4Master or home-directory source path. [CITED: CONTEXT D-08]
6. Invoke installed `arw version --json`, init/append/replay, and MCP confinement cases from the installed/staged location, then scan all command files for forbidden source-checkout prefixes. [CITED: CONTEXT D-02/D-09]

Suggested command skeleton:

```bash
./scripts/stage-plugin
python3 "$PLUGIN_CREATOR_ROOT/scripts/validate_plugin.py" build/stage/academic-research-workbench
CODEX_HOME="$PWD/build/codex-home" HOME="$PWD/build/home" \
  codex plugin marketplace add "$PWD/build/marketplace"
CODEX_HOME="$PWD/build/codex-home" HOME="$PWD/build/home" \
  codex plugin add academic-research-workbench@arw-phase1 --json
./scripts/smoke-staged-plugin --evidence-root build/evidence/phase-01
```

The exact installed-cache launcher resolution is intentionally decided by this executable probe, not by additional documentation search. [CITED: CONTEXT D-08]

### Pattern 5: Internally Enforced Allowed-Root Read

On the Phase 1 Linux x86_64 target, pass one or more canonical allowed roots into the MCP process. Resolve/open paths inside the MCP, reject absolute paths and `..`, walk path components relative to a root directory descriptor without following symlinks, require a regular final file, apply the sensitive-name policy, and reject requests whose declared budget exceeds `4096` bytes or `200` lines before reading. Return typed errors (`path_traversal`, `root_denied`, `symlink_escape`, `sensitive_path`, `budget_exceeded`) with no content field. [CITED: CONTEXT D-06; implementation recommendation]

Declare macOS and Windows unproven in the version/doctor output; Windows junction coverage is not claimed by a Linux symlink test. [CITED: CONTEXT discretion and D-08]

### Anti-Patterns to Avoid

- **Source-checkout smoke:** Passing from the repository root does not prove installed discovery or launcher resolution. [CITED: CONTEXT D-01]
- **Wrapper-only confinement:** A shell or hook check is bypassable; enforcement belongs inside the MCP process. [CITED: CONTEXT D-06]
- **Dirty-checkout patching:** The Paper4Master baseline mutates a checkout and skips application based on marker strings; use a clean snapshot plus digest-verified ordered patches. [VERIFIED: Paper4Master build wrapper]
- **Copy-all staging:** It risks packaging private papers, indexes, secrets, and run data. [CITED: CONTEXT D-05]
- **Hashing parsed JSON:** Re-serialization can change bytes; hash the one canonical serialization that is appended. [CITED: CONTEXT D-03; implementation recommendation]
- **Treating technical success as legal clearance:** Keep technical and release verdicts separate. [CITED: CONTEXT D-05]
- **Expanding Phase 1 into full recovery/indexing/orchestration:** Those capabilities are explicitly deferred. [CITED: CONTEXT deferred ideas]

## Source, Patch, and License Manifest

Use `vendor/source-manifest.json` as the checked-in input contract and generate `build-manifest.json` for each stage. Each component record must contain: stable component ID, version, upstream URL, VCS revision, deterministic tree/archive digest, staged paths, ordered patch records, license IDs and file digests, modification notice, third-party notice reference, dependency-lock/SBOM reference, and use/distribution decision reference. [CITED: CONTEXT D-04/D-05/D-07]

| Component/Input | Required Pin / Digest | License Classification | Phase 1 Action |
|---|---|---|---|
| ARS adapter | `0.1.19`; source revision `c22c17eed8a5753aa60681be9734919f2e2f5b42`; derive and freeze exact tree digest before adaptation | CC BY-NC 4.0 | Materialize, preserve attribution/license, mark modifications, link use/distribution decision. [CITED: `.planning/research/SUMMARY.md`; ARS license] |
| experiment-agent input | `9b063fa895eaf1f63ac99ac03f924f8d31aa8d26`; derive exact tree digest if bundled | CC BY-NC 4.0 | Include as a separate manifest component, never merge its license identity into file-base or collective metadata. [CITED: `AGENTS.md`; `.planning/research/SUMMARY.md`] |
| file-base | `ee68144af5453addda995a27cce8142999f318fb` | MIT | Reconstruct clean source, preserve MIT text and upstream notices, build from temporary materialized tree. [VERIFIED: local checkout and license] |
| Paper4Master patch | ordered `0001`; SHA-256 `dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a` | Modification input | Copy byte-for-byte, record old/new tree digests and modified paths, apply with `git apply --check` then `git apply`. [VERIFIED: local patch digest and content] |
| ARS license text | supplied canonical path is missing; actual identical files found at `ars/LICENSE` and `ars/LICENSE.academic-research-skills`, SHA-256 `b3848009d12a173f549ef98d9ee486e64459e8eb5d9f895bff53782b4aa86d7c` | CC BY-NC 4.0 | Treat the path mismatch as a source-manifest defect to resolve during materialization; do not silently synthesize a root `LICENSE`. [VERIFIED: shallow local license search and SHA-256] |
| file-base license text | SHA-256 `1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb` | MIT | Stage under a component-specific filename and retain copyright notice. [VERIFIED: local license and SHA-256] |

Set the collective plugin manifest license to a tested mixed-license `LicenseRef` value and point human-readable notices to `LICENSES/`; the plugin validator probe must confirm the chosen string is accepted. Do not write `MIT`. [CITED: CONTEXT D-05; implementation recommendation]

The release classifier reads `supply-chain/use-distribution.json` and returns `BLOCKED` unless every staged component is `satisfied` by its license or a recorded permission. A missing/unknown decision is a successful technical test of the gate and a failing release verdict. [CITED: CONTEXT D-05]

## Evidence Layout

Use `build/evidence/phase-01/<build-manifest-sha256>/` so the evidence namespace is tied to the staged bytes. [CITED: CONTEXT D-09; implementation recommendation]

```text
build/evidence/phase-01/<build-manifest-sha256>/
├── environment.json                    # allowlisted tool/OS versions, no secret environment dump
├── stage/{inventory.json,digests.json,forbidden-scan.json}
├── source/{materialize.json,digest-check.json,license-verdict.json,sbom-check.json}
├── plugin/{validate,install,route,version,launcher}/
│   └── {command.json,stdout.log,stderr.log,exit.json,verdict.json}
├── schema/{generated-diff.json,python-validation.json,mcp-validation.json}
├── runtime/{init,append,forced-stop,replay}/
│   └── {command.json,stdout.log,stderr.log,exit.json,verdict.json}
├── confinement/<case-id>/
│   └── {request.json,response.json,stderr.log,exit.json,verdict.json}
├── summary.json
└── SUMMARY.md
```

`command.json` records argv, working directory relative to the stage/workspace, sanitized environment keys, start/end UTC, tool versions, and exit status. Negative probes preserve the denial response and assert that no fixture secret bytes occur in stdout, stderr, or response JSON. [CITED: CONTEXT D-09 and D-06]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Plugin manifest schema | A guessed manifest validator | plugin-creator scaffold/validator plus installed host smoke | The local validator reflects supported ingestion constraints; host smoke covers runtime behavior. [CITED: plugin-creator `SKILL.md`] |
| Runtime model/schema generation | Parallel ad hoc dict checks | Strict Pydantic models plus checked-in JSON Schema | One model source with independent conformance prevents silent contract drift. [CITED: `.planning/research/SUMMARY.md`] |
| Cross-process lock | PID-file convention | `portalocker` | A real advisory lock makes concurrent writers testable. [VERIFIED: PyPI registry + slopcheck; CITED: RUN-02] |
| SBOM serializer | Custom dependency JSON | `uv export --format cyclonedx1.5` | The installed build tool emits the required standard format from the lock. [VERIFIED: local uv help] |
| License conclusion | A blanket project license | Component manifest + license texts + explicit classification/permission record | Mixed MIT and CC BY-NC inputs cannot be represented honestly as only MIT. [CITED: CONTEXT D-05] |
| Filesystem boundary | Hook or shell string-prefix checks | MCP-internal component-wise safe open under explicit roots | Prefix checks do not establish confinement against traversal/symlink cases. [CITED: CONTEXT D-06] |

## Implementation Order

1. **Wave 0 — contracts and test/evidence harness:** add `pyproject.toml`, lock, strict schemas, fixtures, stage/evidence helpers, and failing tests for all 13 requirements. [CITED: `.planning/config.json` Nyquist validation]
2. **Plugin canary:** create the minimal manifest, one routable skill, no-op supported hook companion, `.mcp.json`, stage allowlist, and validator test. [CITED: CONTEXT D-01]
3. **Installed launcher probe:** install the canary from an isolated temporary marketplace and prove or reject staged-relative MCP launch; freeze only the behavior shown by evidence. [CITED: CONTEXT D-08]
4. **Supply-chain baseline:** materialize ARS/file-base, copy/hash the ordered patch, establish component licenses/notices/use decision, lock dependencies, and make all digest mutation tests pass. [CITED: CONTEXT D-04/D-05]
5. **Minimal runtime:** implement route/version, run manifest, two event types, canonical bytes/hash chain, lock/append/fsync/replay, and forced-stop fixture. [CITED: CONTEXT D-02/D-03/D-09]
6. **Fixture MCP boundary:** implement the one bounded read request/result schema and internal root/symlink/sensitive/budget denials; do not add indexing or general search. [CITED: CONTEXT D-06 and deferred Phase 3]
7. **Integrated staged smoke:** rebuild from clean inputs, install exact stage, run route/version/runtime/MCP flows, export SBOM, scan exclusions, and emit technical plus release verdicts. [CITED: ROADMAP Phase 1 success criteria]

This order front-loads host and legal invalidators while keeping enough skeleton available to probe them. [CITED: `.planning/research/SUMMARY.md`]

## Common Pitfalls

### Pitfall 1: Validator Pass Mistaken for Installability

**What goes wrong:** Source manifest validation passes, but Codex cannot discover the skill or launch the MCP from its cache. **Avoidance:** require isolated marketplace install and fresh `codex exec` evidence from the staged bytes. **Warning sign:** tests reference the repository root or developer home. [CITED: CONTEXT D-01/D-02/D-08]

### Pitfall 2: Patch Marker Checks Hide Drift

**What goes wrong:** Marker strings are present, so the baseline wrapper skips patching even when unrelated source differs. **Avoidance:** verify upstream commit/tree, patch bytes/order, post-patch tree, binary, schemas, and staged inventory digests. **Warning sign:** build logic uses `grep` as provenance. [VERIFIED: Paper4Master build wrapper; CITED: SUP-02]

### Pitfall 3: License Path/Identity Collapse

**What goes wrong:** The expected ARS root license path is absent, or a collective MIT label hides CC BY-NC material. **Avoidance:** manifest the actual source-owned license files and fail staging on missing component attribution/classification. **Warning sign:** one top-level `LICENSE` is the only license evidence. [VERIFIED: supplied ARS license path missing; CITED: CONTEXT D-05]

### Pitfall 4: Non-Deterministic Event Hashes

**What goes wrong:** Generated timestamps/IDs, key order, whitespace, or NaN coercion differ, so replay cannot reproduce bytes. **Avoidance:** inject fixture values, forbid coercion/NaN/extra fields, and hash one canonical UTF-8 representation. **Warning sign:** semantically equal events have different SHA-256 values. [CITED: CONTEXT D-03]

### Pitfall 5: Confinement Checked After Reading

**What goes wrong:** Denied content leaks before the policy result is produced. **Avoidance:** validate root/path/sensitive/budget and safely open before any bytes are returned; scan all negative-probe output for canary secrets. **Warning sign:** denial responses contain snippets or file metadata from outside roots. [CITED: FILE-05 and CONTEXT D-06]

### Pitfall 6: Overbuilding Recovery or Retrieval

**What goes wrong:** Phase 1 acquires full checkpoint repair, indexing, FTS, PDF extraction, or general worker orchestration. **Avoidance:** keep two events, one read surface, one forced-stop point, and typed evidence; leave broader behavior to Phases 2–4. **Warning sign:** new database authority or production search API appears. [CITED: CONTEXT deferred ideas]

## Code Examples

### Independent Schema Validation

```python
# Source: project VER-01 contract and jsonschema package interface
schema = json.loads(Path("schemas/v1/mcp-read-result.schema.json").read_text())
payload = json.loads(completed_process.stdout)
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator(schema).validate(payload)
```

### Version Report Shape

```json
{
  "schema_version": "1.0.0",
  "plugin": {"name": "academic-research-workbench", "version": "0.1.0"},
  "runtime": {"version": "0.1.0", "python": "3.14.6"},
  "ars": {"adapter_version": "0.1.19", "revision": "c22c17e...", "tree_sha256": "..."},
  "file_base": {"revision": "ee68144...", "binary_sha256": "..."},
  "patch_set": [{"order": 1, "sha256": "dd6022c..."}],
  "schemas": {"registry_version": "1.0.0", "aggregate_sha256": "..."},
  "platform_claim": "linux-x86_64-phase1"
}
```

The command reads generated build metadata rather than querying mutable source checkouts at runtime. [CITED: CONTEXT D-07 and D-02]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python 3.14 | Runtime/build | Yes | 3.14.6 | Python 3.13 within declared range. [VERIFIED: local uv Python inventory] |
| uv | Lock/build/SBOM | Yes | 0.11.28 | None needed. [VERIFIED: local CLI] |
| Codex CLI | Staged host smoke | Yes | 0.144.1 | No fallback; this is the declared test floor. [VERIFIED: local CLI] |
| Git | Clean materialization/patch | Yes | 2.55.0 | Archive-plus-digest workflow only if VCS unavailable in a release builder. [VERIFIED: local CLI] |
| GNU Make | file-base build | Yes | 4.4.1 | Upstream build system remains authoritative. [VERIFIED: local CLI; Paper4Master wrapper] |
| GCC | Linux native build | Yes | 16.1.1 | Clang can be added in later matrix work. [VERIFIED: local CLI] |
| pytest | Validation | Yes, global baseline | 9.0.3 globally; lock 9.1.1 | `uv sync --frozen` creates the project environment. [VERIFIED: local CLI and PyPI registry] |
| plugin validator | Manifest preflight | Yes | local skill script | Installed-host smoke remains mandatory. [VERIFIED: plugin-creator skill] |

**Missing dependencies with no fallback:** none for the Linux x86_64 Phase 1 implementation. [VERIFIED: local availability audit]

**Unproven environments:** macOS and Windows, including junction/reparse-point behavior, remain explicitly unclaimed in Phase 1. [CITED: CONTEXT discretion and D-08]

## Validation Architecture

### Test Layers and Commands

| Layer | Purpose | Command |
|---|---|---|
| Unit | Canonical bytes, hashes, strict models, route/version formatting, lock behavior | `uv run pytest -q tests/unit` |
| Schema | Generated-schema drift and independent fixture validation | `uv run pytest -q tests/schema` |
| Integration | Init/append/replay/forced-stop and direct MCP confinement | `uv run pytest -q tests/integration` |
| Staged package | Manifest, stage inventory, isolated install, skill route, launcher/version smoke | `uv run pytest -q tests/staged` |
| Phase gate | Clean materialize/build/stage plus every test and evidence summary | `./scripts/verify-phase-1 --clean --evidence-root build/evidence/phase-01` |

The authenticated/model-backed route smoke may be marked with `@pytest.mark.codex_host` for fast local runs, but it is mandatory at phase completion and cannot be replaced by static skill inspection. [CITED: PKG-02 and CONTEXT D-01]

### Requirement-to-Test Mapping

| Req ID | Behavior | Test Type | Automated Command / Target | File Exists? |
|---|---|---|---|---|
| PKG-01 | Clean stage validates and installs | staged | `uv run pytest -q tests/staged/test_manifest_install.py` | No — Wave 0 |
| PKG-02 | Installed skill returns declared ARS family/mode | staged host | `uv run pytest -q -m codex_host tests/staged/test_skill_route.py` | No — Wave 0 |
| PKG-03 | Installed-cache MCP launches with no source absolute path | staged host | `uv run pytest -q tests/staged/test_mcp_launcher.py` | No — Wave 0 |
| PKG-04 | One JSON version command reports all identities | integration | `uv run pytest -q tests/integration/test_version_report.py` | No — Wave 0 |
| SUP-01 | Clean trees reproduce from pins and ordered patch | integration/build | `uv run pytest -q tests/integration/test_source_materialization.py` | No — Wave 0 |
| SUP-02 | Mutated source/patch/lock/artifact digest fails | integration/build | `uv run pytest -q tests/integration/test_digest_drift.py` | No — Wave 0 |
| SUP-03 | Stage contains licenses/notices/SBOM/manifests | staged | `uv run pytest -q tests/staged/test_supply_chain_inventory.py` | No — Wave 0 |
| SUP-04 | Unknown/incompatible classification blocks release | integration | `uv run pytest -q tests/integration/test_license_gate.py` | No — Wave 0 |
| SUP-05 | Private canaries never enter staged inventory | staged/security | `uv run pytest -q tests/staged/test_private_exclusions.py` | No — Wave 0 |
| RUN-01 | Init writes strict manifest and first event | integration | `uv run pytest -q tests/integration/test_run_init.py` | No — Wave 0 |
| RUN-02 | Lock, deterministic sequence/hash chain, forced-stop replay | unit + integration | `uv run pytest -q tests/unit/test_canonical.py tests/integration/test_journal_replay.py` | No — Wave 0 |
| FILE-05 | All confinement denials occur before content | security integration | `uv run pytest -q tests/integration/test_mcp_confinement.py` | No — Wave 0 |
| VER-01 | Python schemas and MCP responses validate independently; drift fails | schema | `uv run pytest -q tests/schema/test_schema_drift.py tests/schema/test_cross_language.py` | No — Wave 0 |

### Forced-Stop/Replay Fixture

Create `tests/fixtures/recovery/seed/` with an immutable input file, fixed run/command/event IDs, fixed UTC timestamps, workflow family/mode, and capability list. The test performs init, appends `baseline.probe_recorded`, and activates a test-only failpoint that sends `SIGKILL` after journal `fsync` but before derived-state output. A fresh process replays from only the run manifest and JSONL, reports the last valid revision/hash, and proves no duplicate event was appended. Preserve exit status/signal, journal bytes before/after, replay JSON, and verdict. [CITED: CONTEXT D-09; Linux-first discretion]

### Confinement Fixtures

```text
tests/fixtures/confinement/
├── allowed/
│   ├── paper.tex                       # bounded success, LaTeX + UTF-8/CJK
│   ├── oversize.txt                    # exceeds 4096-byte Phase 1 budget
│   ├── .env                            # sensitive-path canary
│   └── escape-link -> ../outside/secret.txt
├── second-root/allowed.md              # valid only when explicitly configured
└── outside/secret.txt                  # unique canary that must never appear in output
```

Parameterize relative traversal, absolute outside path, symlink escape, unconfigured second root, sensitive `.env`, declared over-budget request, and valid bounded read. For every denial, assert typed error, empty/absent content, no canary in any captured output, and a case-specific evidence directory. Add Windows junction fixtures only when Windows becomes a claimed platform. [CITED: FILE-05; CONTEXT D-06/D-08]

### Evidence Artifact Paths

- Test-level raw evidence: `build/evidence/phase-01/<build-sha>/<domain>/<case-id>/`. [CITED: CONTEXT D-09]
- Runtime fixture bytes: `.../runtime/{init,append,forced-stop,replay}/`. [CITED: CONTEXT D-09]
- Confinement requests/responses: `.../confinement/<case-id>/`. [CITED: CONTEXT D-06/D-09]
- Stage inventory/digests/exclusion scan: `.../stage/`. [CITED: SUP-02/SUP-05]
- Final machine/human verdicts: `.../summary.json` and `.../SUMMARY.md`. [CITED: CONTEXT D-02/D-09]

### Cadence

- **Per implementation task:** run the narrow affected test file plus `uv run pytest -q tests/schema`; preserve raw evidence only for integration/staged tasks. [CITED: `.planning/config.json` Nyquist validation]
- **Per wave merge:** run `uv run pytest -q tests/unit tests/schema tests/integration`; if plugin/stage files changed, also run `tests/staged` without the authenticated marker. [CITED: implementation recommendation]
- **Phase completion:** run `./scripts/verify-phase-1 --clean`, including the authenticated fresh-thread route smoke, installed launcher/MCP probe, forced-stop/replay, all confinement cases, digest mutation tests, staged exclusion scan, SBOM/license gate, and summary generation. [CITED: ROADMAP Phase 1 success criteria]
- **Release verdict:** technical PASS is insufficient when `license-verdict.json` is BLOCKED; preserve both statuses. [CITED: CONTEXT D-05]

### Wave 0 Gaps

- [ ] `pyproject.toml`, `.python-version`, `uv.lock`, and pytest configuration — no test/build infrastructure currently exists. [VERIFIED: targeted project-root audit]
- [ ] `tests/unit/test_canonical.py` and `tests/integration/test_journal_replay.py` — RUN-01/RUN-02. [CITED: requirements map]
- [ ] `tests/schema/test_schema_drift.py` and `tests/schema/test_cross_language.py` — VER-01. [CITED: requirements map]
- [ ] `tests/integration/test_mcp_confinement.py` plus fixtures — FILE-05. [CITED: requirements map]
- [ ] `tests/staged/` install/route/launcher/inventory/exclusion tests — PKG-01..04 and SUP-03/SUP-05. [CITED: requirements map]
- [ ] `scripts/verify-phase-1` evidence orchestrator. [CITED: CONTEXT D-09]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | No in Phase 1 | Local headless plugin has no remote identity surface; do not add one. [CITED: phase boundary] |
| V3 Session Management | No in Phase 1 | Codex host session is observational, not canonical run authority. [CITED: CONTEXT D-03] |
| V4 Access Control | Yes | Explicit allowed-root capabilities and MCP-internal path enforcement. [CITED: CONTEXT D-06] |
| V5 Validation, Sanitization and Encoding | Yes | Strict Pydantic/JSON Schema; bounded path/budget fields; canonical UTF-8 JSON. [CITED: CONTEXT D-06/D-07] |
| V6 Stored Cryptography | Limited | Standard-library SHA-256 supplies tamper evidence, not authentication or confidentiality; do not hand-roll cryptography. [CITED: CONTEXT D-03] |
| V8 Data Protection | Yes | Allowlist staging, sensitive-path denials, no private run/source material by default. [CITED: CONTEXT D-05/D-06] |
| V12 Files and Resources | Yes | Safe root-relative open, regular-file check, output caps, and no symlink following. [CITED: FILE-05] |
| V14 Configuration | Yes | Pinned sources/locks, schema and artifact digests, explicit platform/limit/version reporting. [CITED: CONTEXT D-04/D-07/D-08] |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| Traversal/absolute path | Information disclosure | Reject before open; root-relative component walk. [CITED: FILE-05] |
| Symlink escape | Information disclosure / Tampering | Do not follow symlinks; bind open operation to allowed-root descriptor. [CITED: CONTEXT D-06] |
| Sensitive file inside allowed root | Information disclosure | Basename/path policy before content return and secret-canary assertions. [CITED: CONTEXT D-06] |
| Oversized output | Denial of service / Information disclosure | Server-side declared hard cap; reject Phase 1 over-budget requests. [CITED: FILE-05] |
| Source/patch substitution | Tampering | Exact revisions/tree/patch/lock/artifact digests and clean materialization. [CITED: SUP-01/SUP-02] |
| Concurrent canonical writers | Tampering / Repudiation | Cross-process lock, expected revision, deterministic sequence/hash chain. [CITED: RUN-02] |
| Private files entering package | Information disclosure | Explicit stage allowlist and forbidden-canary scan. [CITED: SUP-05] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| — | No unverified host behavior is adopted as a design fact; launcher resolution and routed-skill behavior are executable Phase 1 probes. | Staged Plugin Smoke Path | The probe may select a different cache-local launcher mechanism without changing phase architecture. [CITED: CONTEXT D-08] |

## Open Questions

1. **What is the intended use and distribution class?**
   - What is known: ARS inputs carry CC BY-NC 4.0, and private repository status is not accepted as proof of noncommercial use. [CITED: ARS license; CONTEXT D-05]
   - What is unclear: whether the staged plugin supports internal business/commercial advantage or will be distributed.
   - Recommendation: create `use-distribution.json` in Phase 1; default release verdict to BLOCKED until classification and any permission are attached. [CITED: CONTEXT D-05]
2. **How does `codex-cli 0.144.1` resolve a staged plugin's relative MCP command after install?**
   - What is known: the CLI supports configured marketplaces and plugin install, and the project forbids source-checkout absolute paths. [VERIFIED: local CLI help; CITED: CONTEXT D-02]
   - What is unclear: the exact cache working directory/environment available to `.mcp.json` launchers.
   - Recommendation: execute the canary in implementation step 3, preserve raw evidence, then freeze the proven staged/cache-local launcher.
3. **Which ARS license path is canonical for materialization?**
   - What is known: the supplied root path does not exist; two identical CC BY-NC files exist under `ars/` with SHA-256 `b3848009...`. [VERIFIED: local shallow search and digest]
   - What is unclear: whether the source snapshot should expose one or both staged license names.
   - Recommendation: preserve the snapshot's original path(s), choose one component-specific staged license copy, and record both source path and staged path in the manifest.

## Sources

### Primary (HIGH confidence)

- `.planning/phases/01-contract-license-and-executable-baseline/01-CONTEXT.md` — locked scope, authority, pinning, licensing, confinement, probes, evidence, and deferrals. [CITED: local file]
- `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` — exact Phase 1 IDs and success criteria. [CITED: local files]
- `.planning/research/SUMMARY.md` — synthesized current stack, architecture, legal conclusions, and dependency order. [CITED: local file]
- `AGENTS.md` — project runtime, authority, supply-chain, compatibility, security, and delivery constraints. [CITED: local file]
- plugin-creator `SKILL.md`, `plugin-json-spec.md`, and `installing-and-updating.md` — local manifest validation and marketplace/install workflow. [CITED: local skill files]
- Paper4Master `build-file-base-mcp`, `file-base-mcp`, and `file-base-server-name.patch` — current executable baseline and patch limitations. [VERIFIED: local files]
- ARS CC BY-NC 4.0 license and file-base MIT license — exact local license texts and digests. [VERIFIED: local files]
- Local Codex, uv, Python, Git, Make, GCC, pytest, and plugin-validator commands — executable environment and CLI surfaces. [VERIFIED: local commands]
- PyPI JSON/index plus slopcheck — package versions, publication metadata, repositories, and legitimacy verdicts. [VERIFIED: PyPI registry + slopcheck]

### Secondary (MEDIUM confidence)

- None. This phase research intentionally uses the supplied synthesis and narrow local probes rather than broad search.

### Tertiary (LOW confidence)

- None adopted. Unresolved host and licensing behavior is represented as an executable probe or blocking verdict, not an assumed claim.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — exact pins came from locked synthesis and were checked against local tools/registries. [CITED/VERIFIED as above]
- Architecture: HIGH — sole writer, staged package, mixed-license gate, and MCP-internal confinement are locked decisions. [CITED: CONTEXT]
- Host integration: MEDIUM — CLI commands are verified, but installed relative-launch behavior must be measured by the prescribed canary. [VERIFIED: local CLI; CITED: CONTEXT D-08]
- Pitfalls: HIGH — each is tied to a supplied script/patch/license or locked requirement. [VERIFIED/CITED as above]

**Research date:** 2026-07-13
**Valid until:** 2026-08-12 for architecture/package pins; rerun Codex host probes whenever the CLI floor changes. [CITED: CONTEXT D-08; implementation recommendation]
