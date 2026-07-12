# Project Research Summary

**Project:** Academic Research Workbench
**Domain:** Private, Codex-native, headless academic research workflow and provenance plugin
**Researched:** 2026-07-12
**Confidence:** MEDIUM

## Executive Summary

Academic Research Workbench v1.0 is not a writing UI or a prompt collection. It is a private, local-first Codex plugin that turns the pinned Academic Research Suite (ARS) methodology and patched file-base MCP into an executable research system whose runs can be resumed and audited without relying on chat memory. Experts should build it as a modular monolith with two processes and one authority: a short-lived Python control plane is the sole writer of canonical run records, while one long-lived C/C++ file-base stdio MCP serves bounded file retrieval and disposable SQLite/FTS projections. Codex supplies the parent conversation and native subagent execution; hooks improve context and policy visibility but do not own state or security.

The implementation should begin with executable contract and licensing gates, then establish the append-only ledger, immutable artifact manifests, Material Passport revisions, atomic checkpoints, and pure replay reducer before adding agents or graph semantics. A files-first MCP with allowed-root confinement and hard output budgets can proceed once shared schemas freeze. Subagents must work from immutable assignments and return schema-valid proposals that only the parent can accept. The semantic graph is built later and must be deletable and reproducible from authoritative files; it never decides provenance, gate status, or the next legal transition.

The principal risks are false claims of orchestration, split-brain recovery, unsafe filesystem access, stale or non-equivalent graph projections, evolving Codex plugin/hook contracts, weak evidence tests, and incompatible source licensing. Mitigate them with explicit execution modes and worker lifecycle evidence, single-writer compare-and-swap transactions, hard-kill and I/O fault tests, descriptor-safe path handling, bounded MCP schemas, projection watermarks and rebuild comparators, installed-plugin compatibility tests, and a staged-package license/SBOM gate. Desktop UI and Chinese-military-specific assumptions remain out of v1.

## Decision Resolution

### Confirmed v1 Decisions

- **Private, headless Codex plugin:** v1 ships a local plugin, CLI/runtime, stdio MCP, hooks, subagents, machine-readable artifacts, and audit summaries. No desktop shell is included.
- **Pinned necessary source:** ARS adapter `0.1.19` and its selected upstream commits, file-base commit `ee68144af5453addda995a27cce8142999f318fb`, ordered local patches, dependency locks, notices, and source hashes are release inputs.
- **Two languages, two responsibilities:** Python `>=3.13,<3.15` owns the workflow control plane; the pinned C11/C++14 file-base owns MCP framing, bounded retrieval, indexing, and disposable graph/query projections.
- **Append-only provenance is authoritative:** immutable input/artifact bytes, validated manifests, hash-chained ledger events, and immutable Passport checkpoints are canonical. `state.json`, SQLite, FTS, graph data, hook logs, and transcripts are derived or observational.
- **One canonical writer:** workers and hooks never edit accepted state. The parent orchestrator invokes the runtime, which validates and serializes every canonical mutation.
- **Files-first, query-only agent MCP:** agents receive bounded `list_files`, `read_file`, `search_files`, outline/context, projection-status, and allowlisted graph/evidence queries. Crawl, extraction, sync, and graph rebuild are administrative operations behind the parent-controlled runtime CLI, not general worker tools.
- **Rebuildable semantic graph:** stable IDs, source hashes, ledger watermarks, supersession edges, projection receipts, and delete/rebuild equivalence are mandatory. No reverse synchronization from graph to provenance is allowed.
- **Real subagent evidence:** planned, dispatched, started, result-received, accepted, rejected, and superseded are distinct states. Inline role prompting may remain as an explicitly degraded mode but cannot claim independent review.
- **Hooks are adapters:** command hooks hydrate context, flag or deny supported misuse, validate envelopes, and request continuation. Runtime, MCP, OS permissions, and state transitions remain correct when hooks are disabled, untrusted, concurrent, or incomplete.
- **General academic abstractions:** multilingual/CJK support is a retrieval capability, not a Chinese military domain model. Domain packs are deferred.

### Phase 0 Probes — Not Yet Product Decisions

- **Installed MCP launcher resolution:** prove command discovery from an installed plugin cache; do not assume undocumented `PLUGIN_ROOT` interpolation in `.mcp.json`.
- **Custom agent packaging:** v1 must work with native subagents plus assignment-injected ARS roles. Probe an optional project-scoped `.codex/agents` installer, but do not make plugin-native custom-agent TOML a dependency.
- **Experiment ownership:** the minimum contract is ingestion of externally executed experiments into one strict provenance schema. Add controlled workbench execution only if the Phase 0 probe proves sandboxing, approvals, environment capture, and identical record semantics.
- **Append-only file layout:** the authoritative mechanism is fixed as an append-only file journal, resolving the research suggestion of a canonical SQLite ledger against the project constraint. Phase 1 may choose a single journal or sealed segments based on crash/fault evidence; SQLite remains projection/cache only.
- **Operating-system support:** select the v1 matrix before promising race-safe root confinement. Windows junction/reparse behavior and static binary packaging require empirical tests.
- **Retrieval budgets and quality:** benchmark CJK, LaTeX, BibTeX, identifiers, direct-text/extracted PDFs, short substrings, and malformed files before freezing byte, page, row, and timeout defaults.
- **Graph equivalence oracle:** define normalization for order, generated timestamps, schema migrations, deletes, renames, and supersession before graph implementation.
- **Threat model and E2E fixture:** declare whether local-history replacement by a malicious user is in scope, and select one representative run that exercises claims, sources, an experiment record, independent review, a failed gate, human handoff, crash/resume, and final audit evidence.

### Licensing Gates

- ARS and experiment-agent are verified as **CC BY-NC 4.0**; file-base is **MIT** with additional permissive third-party notices. The collective plugin must not be labeled simply MIT.
- A private repository does not by itself establish noncommercial use. Before the release bundle vendors ARS, record the intended use/distribution class and obtain legal/owner confirmation where internal business or commercial advantage is possible.
- If commercial use or distribution is intended, release is blocked until ARS and experiment-agent receive written commercial permission/dual licensing or are replaced by independently authored compatible contracts.
- Every build must verify source/tree/patch hashes and scan the staged package. Ship accurate `LICENSES/`, modification markings, `THIRD_PARTY_NOTICES.md`, SBOM, build manifest, and source/patch manifest. Never package private papers, extracted full text, indexes, or run data by default.

## Key Findings

### Recommended Stack

Use a small polyglot stack and avoid additional workflow services. Python provides transparent file-oriented state and existing ARS validator compatibility; the pinned file-base retains its proven parsers, embedded SQLite, and MCP implementation. Exact dependency versions belong in `uv.lock`, and release builds use clean materialized source snapshots plus an ordered patch series rather than submodules, runtime clones, or an in-place patched checkout. See [STACK.md](./STACK.md).

**Core technologies:**

- **Codex plugin contract:** tested floor `codex-cli 0.144.1` — plugin installation, skill routing, hooks, and MCP host integration; test both the pinned minimum and current supported release.
- **Python 3.14.6, compatible with 3.13:** control-plane CLI, schemas, reducer, ledger, checkpoints, hooks, gates, evidence reports, and optional `pypdf` extraction.
- **ARS adapter 0.1.19 and pinned upstream commits:** workflow methodology, role prompts, handoff semantics, and integrity policy; vendor unchanged and adapt at explicit boundaries.
- **Pinned file-base C/C++ fork:** files-first stdio MCP, allowed-root enforcement, FTS/outlines, structural indexing, and research projection; extend rather than rewrite.
- **MCP `2025-11-25` over stdio:** local, private, headless Codex transport with negotiated capabilities and structured bounded output.
- **SQLite 3.51.3 + FTS5:** disposable file and graph projections, preferably separate `files.sqlite` and `research-graph.sqlite` stores served by one process.
- **Pydantic 2 + JSON Schema Draft 2020-12 + independent `jsonschema` validation:** strict cross-language contracts with checked-in schema drift gates.
- **`uv`, pytest, Hypothesis, Ruff, ASan/UBSan/TSan:** reproducible dependency resolution and evidence-producing unit, property, recovery, protocol, and native safety tests.

Do not add an ORM, daemon workflow framework, web framework, message broker, graph server, telemetry service, Python production MCP proxy, or authoritative database in v1.

### Expected Features

Feature IDs refer to [FEATURES.md](./FEATURES.md).

**Must have (v1 table stakes):**

- **TS-1–TS-3:** cleanly installable plugin, pinned/licensed source bundle, and executable routing of existing ARS workflow families with honest degradation reporting.
- **TS-4–TS-5:** explicit lifecycle/status/resume backed by append-only events, immutable artifacts, Material Passports, atomic checkpoints, revision CAS, and replay without conversation memory.
- **TS-6–TS-7:** bounded files-first retrieval with explicit format coverage, allowed roots, safe path opening, ignore policy, read-only worker defaults, and visible truncation/staleness.
- **TS-8–TS-9:** actual specialized subagents, immutable handoffs, parent-only acceptance, deterministic merging, independent reviewers, and lifecycle hooks whose limitations are visible.
- **TS-10–TS-11:** machine-readable integrity verdicts, explicit waivers, human-review/access states, concise diagnostics, and a computed next legal action.
- **TS-12:** installed-plugin, protocol, security, crash/recovery, stale-result, graph-rebuild, and audit tests that preserve inspectable raw evidence.

**Should have (P1 differentiators, not optional polish):**

- **DF-1–DF-2:** canonical files versus disposable projections, plus bounded claim-to-source/result/figure/review/gate evidence-chain queries.
- **DF-3–DF-4:** proven crash recovery/stale-work rejection and research-aware multilingual/CJK/LaTeX/BibTeX/PDF retrieval.
- **DF-5:** blind independent review with individual reports, a finding matrix, and dissent preservation before synthesis.
- **DF-6–DF-8:** complete audit dossier, honest evidence-access semantics, and gate-aware next-task computation from canonical state.

**Defer (v1.x or v2+):**

- Hardened Markdown-to-paper AST and strict publication export, additional source connectors, OCR/DOCX/spreadsheet adapters, and operator repair commands belong in v1.x after runtime schemas stabilize.
- Read-only desktop/Open Science Desktop UI, domain packs, remote/team coordination, and opt-in telemetry belong in v2+.
- Universal ingestion, hidden cloud sync, silent credentials/paywall access, canonical graph writes, worker canonical writes, and automatic gate bypass are anti-features, not backlog items.

### Architecture Approach

Use a local modular monolith with a filesystem integration bus, a short-lived Python sole-writer runtime, and one long-lived C/C++ query process. A pure reducer reconstructs state from the run manifest, valid hash-chained events, and referenced immutable manifests. Workers propose results through per-attempt inboxes; the parent accepts them deterministically. File and graph databases are separately disposable projections with explicit ledger watermarks. Gates produce immutable evidence receipts rather than booleans. See [ARCHITECTURE.md](./ARCHITECTURE.md).

**Major components:**

1. **Plugin bundle and ARS router** — installation metadata, workflow/mode selection, pinned role prompts, MCP wiring, hook definitions, launchers, and notices.
2. **Parent Codex orchestrator** — user decisions, legal transition selection, direct-child dispatch, deterministic task ordering, and runtime invocation.
3. **Python runtime kernel** — schemas, state machine, locks, idempotency, journal append, immutable artifact acceptance, Passport checkpoints, gates, waivers, finalize, and recovery.
4. **Assignment/result boundary** — immutable input snapshots, scoped scratch areas, attempt identity, blind-review groups, strict result envelopes, freshness checks, and stale-result rejection.
5. **Hook pack** — context hydration and observable policy assistance without canonical authority.
6. **Patched file-base MCP** — root-confined file catalog, bounded reads/search/outlines/context, extraction provenance, and structured query responses.
7. **Research graph projector** — manifest-only nodes/edges, stable IDs, supersession, watermarks, shadow rebuilds, and projection receipts.
8. **Verification and evidence runner** — citation, semantic claim, temporal, statistical, experiment, figure, review, format, access, and finalization evidence bundles.

### Critical Pitfalls

See [PITFALLS.md](./PITFALLS.md) for the complete risk catalog.

1. **Fake orchestration and review independence** — require real worker IDs, immutable assignments/results, lifecycle events, isolated reviewer inputs, canary evidence, and honest `inline_role_prompt` degradation labels.
2. **Mutable or split-brain provenance** — enforce one writer, sequence/hash-chained events, immutable versions, CAS, durable commit order, replay, and explicit correction/waiver/invalidation events.
3. **Recovery theater** — inject hard kills, torn writes, `ENOSPC`, I/O errors, lock death, stale delivery, and faults during recovery; assert wholly absent or wholly committed transitions and preserve raw evidence.
4. **Unsafe or unbounded MCP access** — use root capabilities and safe-open semantics, reject path/symlink/junction escapes and sensitive files, cap bytes/rows/time/depth/pages/concurrency, paginate, and expose truncation.
5. **Graph becoming a second truth store** — project only validated manifests into a shadow generation, publish atomically, track ledger watermarks, and prove fresh/full/incremental equivalence after delete/rename/supersede.
6. **Stale host contracts and incompatible bundles** — continuously test the installed plugin, hook trust/degradation, MCP negotiation, and current Codex behavior; block release on exact source, patch, license, notice, and SBOM checks.

## Requirements Category Map

| Category | Required Outcome | Feature Coverage |
|---|---|---|
| **PKG — Plugin and workflow integration** | Installed private plugin exposes the ARS router, stable launchers, MCP, hooks, version identity, and honest compatibility/degradation status | TS-1, TS-3 |
| **SUP — Supply chain and licensing** | Exact ARS/file-base snapshots, patches, locks, build metadata, notices, SBOM, and approved use/distribution class | TS-2, TS-12 |
| **RUN — Runtime and provenance** | Single-writer append-only ledger, immutable manifests/Passports, pure replay, atomic checkpoints, status, resume, and stale/duplicate rejection | TS-4, TS-5, DF-3, DF-8 |
| **FILE — Retrieval and security** | Root-confined, bounded, multilingual files-first MCP with extraction provenance and visible coverage/staleness | TS-6, TS-7, DF-4, DF-7 |
| **AGT — Agents, hooks, and handoffs** | Real direct-child workers, immutable assignment/result contracts, parent-only acceptance, independent review, and defense-in-depth hooks | TS-8, TS-9, DF-5 |
| **GRAPH — Rebuildable research projection** | Disposable graph and file indexes with stable IDs, source hashes, watermarks, rebuild receipts, and bounded evidence queries | DF-1, DF-2 |
| **SCI — Integrity and human gates** | Fresh evidence receipts, PASS/FAIL/BLOCKED states, explicit waivers, access-tier semantics, and finalization refusal on unresolved evidence | TS-10, TS-11, DF-6, DF-7 |
| **VER — Executable evidence and release quality** | Real install/E2E/recovery/security/rebuild fixtures with raw artifacts, versioned benchmarks, and an inspectable audit bundle | TS-12, DF-3, DF-6 |

## Implications for Roadmap

Based on the combined research, use the following seven-phase structure. Phase numbers are sequential roadmap gates, but Phase 2 implementation may overlap Phase 1 after Phase 0 schemas and root-capability contracts freeze. Verification fixtures begin in Phase 0 and grow with every phase.

### Phase 0: Contract, License, and Executable Baseline

**Rationale:** Packaging, source rights, authority rules, and host/runtime contracts can invalidate later work; prove them before graph or agent investment.

**Delivers:** Confirmed source locks and partitions; use/distribution decision; current schema registry and provenance modes; threat-model and OS declarations; valid plugin skeleton; stable launcher strategy; installed-cache smoke test; real subagent canary; thin init/append/replay/resume fixture; selected representative E2E scenario.

**Requirements:** PKG, SUP, foundations for RUN/AGT/VER.

**Features:** TS-1, TS-2, TS-3 baseline, TS-12 seed.

**Avoids:** Fake orchestration, stale Codex/MCP contracts, license incompatibility, source drift, and benchmark theater.

### Phase 1: Durable Provenance Runtime

**Rationale:** Lifecycle, agents, gates, and graph projections all depend on one stable canonical state and acceptance transaction.

**Delivers:** Strict schemas; run identity; single-writer lock; append-only journal or sealed segments; deterministic event bytes/hash chain; pure reducer; immutable artifact and Passport versions; idempotent commands; revision CAS; atomic checkpoints; status/resume/finalize skeleton; stale/duplicate rejection; crash repair and quarantine behavior.

**Requirements:** RUN and VER.

**Features:** TS-4, TS-5, DF-3.

**Avoids:** Mutable provenance, non-atomic checkpoints, split-brain resume, duplicate transitions, stale result acceptance, and clean-shutdown-only recovery tests.

### Phase 2: Secure Files-First Data Plane

**Rationale:** Research agents need useful retrieval, but file access and bounds must be designed together; security cannot be retrofitted after tool contracts ship.

**Delivers:** Clean reproducible file-base build; first-class file/extraction/outline schemas; `list_files`, bounded range reads, FTS/exact search, outline/context tools; allowed-root capabilities; safe-open and sensitive-path policy; incremental rename/delete handling; extraction provenance; CJK/LaTeX/BibTeX/PDF fixtures; structured errors, pagination, truncation, and staleness.

**Requirements:** FILE, SUP, and VER.

**Features:** TS-6, TS-7, DF-4, DF-7 foundation.

**Avoids:** Unrestricted filesystem bridges, symlink/TOCTOU escape, prompt-injection propagation, unbounded output/traversal, unsafe extraction, and irreproducible in-place patching.

### Phase 3: Subagent Orchestration, Hooks, and Base Gates

**Rationale:** Real delegation is safe only after immutable assignments, result acceptance, and runtime policy exist. Hooks should be added after equivalent core checks work without them.

**Delivers:** Assignment/attempt/result lifecycle; direct-child bounded concurrency; native subagent fallback with ARS role injection; deterministic merge order; cancellation/retry; blind reviewer fan-out; dissent-preserving synthesis; base PASS/FAIL/BLOCKED and waiver records; SessionStart/SubagentStart/SubagentStop/PreToolUse/PostToolUse/Stop adapters; explicit hook degradation reporting.

**Requirements:** AGT, SCI foundation, PKG, and VER.

**Features:** TS-3, TS-8, TS-9, TS-10 foundation, DF-5.

**Avoids:** Planner labels masquerading as execution, canonical worker writes, reviewer leakage, hook-only security, transcript parsing, and nondeterministic result merges.

### Phase 4: Rebuildable Research Graph and Evidence Queries

**Rationale:** Graph semantics should consume stable canonical schemas, accepted artifacts, and gate records; building earlier would create a competing model of truth.

**Delivers:** Separate disposable file/graph projections; manifest-only research entities and relationships; stable IDs; source hashes; supersession and invalidation; ledger watermarks; shadow generations; atomic publication; projection status; bounded claim/evidence/figure/review/gate queries; exact full/incremental/fresh-rebuild comparator.

**Requirements:** GRAPH, RUN, FILE, and SCI.

**Features:** DF-1, DF-2, DF-8 foundation.

**Avoids:** Graph authority, prose-inferred scientific state, partial in-place rebuilds, stale deletes/renames, mixed generations, and unbounded traversal.

### Phase 5: Scientific Integrity, Diagnostics, and Audit Bundle

**Rationale:** Full verification becomes reliable only after real execution paths and stable subject hashes exist; gate semantics must still have been modeled earlier.

**Delivers:** Citation and claim relevance checks; source access/version/retraction states; temporal/statistical/experiment/figure/review/format gates; evidence receipts; freshness invalidation; human-review queue; scoped waivers; gate-aware status and next action; source retention/export policy; compact machine-readable and Markdown audit dossier.

**Requirements:** SCI, RUN, GRAPH, and VER.

**Features:** TS-10, TS-11, DF-6, DF-7, DF-8.

**Avoids:** Boolean “verified” laundering, abstract/full-text conflation, scientific source drift, hidden waivers, stale verdicts, inaccessible evidence marked supported, and same-model-only evaluation.

### Phase 6: End-to-End Recovery and Release Qualification

**Rationale:** Release confidence requires the installed system to compose all prior guarantees under real failure, not a new layer of static tests.

**Delivers:** Pinned-minimum/current Codex matrix; clean install and launcher tests; MCP negotiation and approvals; hooks trusted/untrusted/disabled tests; representative research-to-review run; hard-kill/I/O/disk-full/lock/compound-fault matrix; stale and malicious worker/source cases; graph deletion/rebuild proof; calibrated benchmark results; complete evidence bundle; staged-package source/license/SBOM scan.

**Requirements:** VER plus release gates for every category.

**Features:** TS-12, DF-3, DF-6, and final acceptance of TS-1–TS-11/DF-1–DF-8.

**Avoids:** “Looks done” failures where source layout, JSON parsing, a clean resume, one graph answer, or a high aggregate score substitutes for installed, adversarial, and recoverable behavior.

### Phase Ordering Rationale

- Freeze authority, schemas, legal partitions, and host contracts first; every later component consumes them.
- Establish provenance and acceptance before worker execution so parallel work cannot create canonical races or false evidence.
- Build files-first retrieval with security as one phase; every read/query contract must be bounded from its first release.
- Add hooks after runtime/MCP invariants exist, ensuring disabled or untrusted hooks affect convenience rather than correctness.
- Project the graph only after canonical claim, source, result, review, and gate records stabilize.
- Model gate records early but harden scientific verifiers after real artifacts exist.
- Treat E2E evidence as cumulative: each phase contributes fixtures and receipts that Phase 6 composes into release proof.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 0:** Current Codex packaging/launcher behavior, custom-agent adapter feasibility, intended-use licensing, threat model, experiment ownership, and v1 OS matrix are blocking probes.
- **Phase 1:** The append/segment/fsync protocol, cross-platform locking, torn-tail handling, and failpoint oracle need a focused durability design review.
- **Phase 2:** Portable safe-open semantics, Windows reparse points, tokenizer quality, PDF extraction limits, and static native builds require platform/corpus experiments.
- **Phase 3:** Verify current hook event/failure behavior and optional custom-profile installation; do not research a new orchestration framework.
- **Phase 4:** Define and test the graph equivalence normalization and migration policy before selecting final indexes/query DSL.
- **Phase 5:** Source retention/export rules and human/automated evaluator calibration need policy and empirical research.

Phases with standard patterns that can skip a broad research phase:

- **Phase 6:** Use established installed-package, fault-injection, conformance, security, and evidence-bundle patterns already defined by prior phases; plan concrete fixtures rather than reopening architecture.

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack | MEDIUM | Python, file-base, SQLite, MCP, schemas, and exact pins are well supported; Codex packaging, cross-platform release, and custom-agent distribution remain empirical gates. |
| Features | MEDIUM | Scope and P1 capabilities are strongly grounded in `PROJECT.md` and adjacent systems, but priority/cost judgments lack broad user or market research. |
| Architecture | HIGH | The single-writer, immutable-files, pure-reducer, worker-proposal, bounded-MCP, and rebuildable-projection boundaries agree across research and directly implement fixed project constraints. Host integration details remain Phase 0 probes. |
| Pitfalls | HIGH | Technical risks are tied to inspected local code/contracts and authoritative protocol/testing guidance. Project-specific CC BY-NC applicability remains MEDIUM pending intended use and counsel/owner confirmation. |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Licensing intent:** classify private use versus internal commercial/business use before vendoring into a release; document permission or replacement path.
- **Codex installation contracts:** prove launcher discovery, installed-cache behavior, hook trust/change handling, and native subagent evidence on the supported compatibility window.
- **Experiment execution:** decide whether v1 only ingests external runs or also executes controlled experiments; preserve one canonical experiment schema in either case.
- **Durability details:** choose journal segmentation and prove crash safety, directory durability, locking, and recovery semantics on the supported filesystems.
- **OS support:** declare platforms before setting safe-open and binary release gates; do not claim untested Windows/macOS parity.
- **Retrieval quality:** benchmark CJK/LaTeX/BibTeX/PDF extraction and exact/substring fallback before freezing limits and tokenizers.
- **Graph equivalence:** specify normalized query equality across rebuild modes, schema versions, ordering, timestamps, deletions, and supersession.
- **Scientific retention policy:** define when source bytes, snippets, hashes, or metadata may be retained/exported and how deletion/retraction affects immutable records.
- **Evaluation fixture:** select and version the representative end-to-end corpus, hard invariants, human rubric, and dissent-preserving review expectations.
- **Threat boundary:** decide whether tamper evidence protects against bugs/malicious content only or requires an external signature/anchor against a malicious local writer.

## Sources

### Primary (HIGH confidence)

- [PROJECT.md](../PROJECT.md) — fixed scope, core value, active requirements, constraints, and exclusions.
- [STACK.md](./STACK.md) — exact pins, language boundaries, package layout, build and license inventory, and test stack.
- [FEATURES.md](./FEATURES.md) — table stakes, differentiators, anti-features, dependencies, MVP definition, and feature confidence.
- [ARCHITECTURE.md](./ARCHITECTURE.md) — authority hierarchy, component boundaries, commands/tools, data flow, recovery semantics, and build order.
- [PITFALLS.md](./PITFALLS.md) — technical, security, legal, recovery, evaluation, and phase-specific failure modes.
- `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md` and `codex/references/science_workbench_mvp.md` — ARS routing, security boundaries, run/evidence contract, and human-review semantics.
- Local pinned ARS/file-base source, licenses, notices, current patch, planner, hooks, handoff schemas, and Paper4Master integration materials enumerated in the four research reports.
- [OpenAI Codex plugin documentation](https://developers.openai.com/codex/plugins/build), [subagents](https://developers.openai.com/codex/subagents), [hooks](https://learn.chatgpt.com/codex/hooks), and [MCP integration](https://developers.openai.com/codex/mcp) — current host contracts and limitations.
- [MCP specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) — lifecycle, tools, roots, pagination, schemas, and security duties.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html), [testing](https://www.sqlite.org/testing.html), [FTS5](https://www.sqlite.org/fts5.html), and [WAL](https://www.sqlite.org/wal.html) — durability, crash testing, search, and local-cache constraints.
- [W3C PROV-O](https://www.w3.org/TR/prov-o/) and [PROV-AQ](https://www.w3.org/TR/prov-aq/) — provenance entities, revision, changing resources, and trust boundaries.
- [CC BY-NC 4.0 legal code](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en), [Creative Commons FAQ](https://creativecommons.org/faq/), and [MIT License](https://opensource.org/license/mit) — verified license texts and software-license guidance.

### Secondary (MEDIUM confidence)

- Table-stake/differentiator labels and relative complexity estimates in `FEATURES.md` — informed product judgments without a broad external market study.
- Commercial/internal-use applicability of CC BY-NC — license facts are verified, but the project-specific conclusion depends on intended use, jurisdiction, and owner/legal review.

### Tertiary (LOW confidence)

- None adopted as a roadmap dependency. Unverified assumptions are isolated above as Phase 0 probes or licensing gates.

---
*Research completed: 2026-07-12*
*Ready for roadmap: yes, contingent on Phase 0 blocking gates*
