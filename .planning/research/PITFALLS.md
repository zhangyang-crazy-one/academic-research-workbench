# Pitfalls Research

**Domain:** Codex-native, MCP-backed, auditable academic research workbench plugin
**Researched:** 2026-07-12
**Confidence:** HIGH for technical and protocol risks; MEDIUM for license conclusions pending counsel and intended distribution model

## Executive Risk Position

The project fails its core promise if it can produce polished research artifacts without proving who or what produced them, from which exact inputs, under which runtime and permissions, and through which verified state transitions. The ledger and immutable artifacts therefore have to be the product kernel. Subagents, hooks, the semantic graph, and the MCP server are execution and query mechanisms around that kernel, never substitutes for it.

The most dangerous implementation shortcut is to operationalize the existing ARS planner literally. Its current `ars_codex_full_runtime.py` explicitly says that it does **not** spawn agents or execute hooks; it emits a structured plan. Treating fields such as `dispatch: parallel_independent_review` as evidence that independent workers ran would create fake orchestration and scientifically false provenance. The current ARS hook pack is likewise only a disabled `SessionStart` announcement and is not a durable runtime.

The legal boundary is also an early architecture constraint, not release paperwork. The supplied file-base checkout is MIT-licensed and carries a substantial permissive third-party inventory. The actual ARS and experiment-agent license files are CC BY-NC 4.0. That permits sharing and adaptation only for noncommercial purposes under attribution and marking conditions; it does not support an assumption that a commercial Codex plugin or marketplace package can bundle ARS unchanged. Keep licensed source partitions explicit and obtain separate permission or replace/reimplement the NC material before any commercial distribution.

## Evidence Snapshot

| Observation | Verified evidence | Implication |
|-------------|-------------------|-------------|
| file-base source revision | Checkout `HEAD` is `ee68144af5453addda995a27cce8142999f318fb`, matching the integration plan | A reproducible pin exists, but must be verified during every build |
| Local patch identity | Current dirty diff exactly equals `file-base-server-name.patch`; SHA-256 `dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a` | The current checkout is an in-place patched tree; clean-tree patch application must replace this workflow |
| file-base license | Actual `LICENSE` is MIT; SHA-256 `1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb` | Redistribution is permissive if notices and third-party obligations are preserved |
| file-base bundled dependencies | Actual `THIRD_PARTY.md` lists MIT, Apache-2.0, BSD-2/3-Clause, ISC, 0BSD, CC0, Unlicense/public-domain components and embedded model data | Binary notices/SBOM generation remains mandatory; the root MIT file is not the whole inventory |
| ARS license | Actual `ars/LICENSE` is CC BY-NC 4.0; SHA-256 `b3848009d12a173f549ef98d9ee486e64459e8eb5d9f895bff53782b4aa86d7c` | Commercial redistribution/use cannot be assumed |
| Experiment-agent license | Actual `ars/experiment-agent/LICENSE` is CC BY-NC 4.0; SHA-256 `f66a510318fa9c98534f64c844403bf54d9019613f5a818f9d92075b91133d25` | This source needs the same legal partition or separate permission |
| Existing orchestration | Planner docstring says it is side-effect free and does not spawn agents or execute hooks | Planner output is intent, not execution evidence |
| Existing hook runtime | `codex/hooks/hooks.json` defines one disabled announcement hook; current Codex docs require event-keyed hook configuration and trust review | Do not package the current file as if it enforces lifecycle policy |

## Critical Pitfalls

### Pitfall 1: Fake Orchestration and Reviewer Independence Theater

**What goes wrong:**
The runtime reports that source discovery, verification, experiment execution, peer review, or editorial synthesis ran as separate agents when it only emitted a plan or executed role prompts inline. Reviewer outputs may share context or be generated serially in one conversation, while the ledger claims they were blind and independent. A polished finding matrix then launders one model response into apparently multi-agent scientific consensus.

**Why it happens:**
The existing full-runtime planner already emits agent names, `dispatch` labels, independence groups, and output contracts. These fields look executable but are descriptive only. Teams also tend to equate prompt-role changes with process isolation and to infer execution from a successful final artifact.

**How to avoid:**
- Define separate `planned`, `dispatched`, `started`, `result_received`, `accepted`, and `superseded` events. A plan can never satisfy an execution gate.
- Record real worker/run ID, parent run ID, assignment hash, base revision, input artifact hashes, agent profile, model/provider, permission mode, start/end time, result hash, and transcript/evidence reference.
- Label inline role-prompt execution honestly as `execution_mode: inline_role_prompt`; never claim reviewer independence in that mode.
- Give independent reviewers immutable assignment snapshots and deny access to sibling results until their own result is accepted.
- Require the synthesizer to preserve dissent, methodology concerns, and unresolved findings in a finding matrix.
- Add a canary worker fixture that writes a worker-unique nonce; fail if the parent cannot prove distinct worker lifecycles and isolated inputs.

**Warning signs:**
- Agent names and `dispatch` fields exist, but there are no assignment/result files or lifecycle events.
- All reviewer artifacts have the same transcript, timestamps, model call, or context hash.
- The runtime can claim “parallel” while no process, subagent, or task IDs exist.
- A result says “verified” or “independent” based only on prose in the answer.
- The same model output both raises and resolves a concern without an independent artifact.

**Phase to address:**
Phase 0 defines honest provenance modes and a failing executable fixture. Phase 2 implements real subagent dispatch, isolation, and reviewer-independence tests. Phase 4 evaluates handoff accuracy and independence empirically.

**Confidence:** HIGH — directly verified in the existing planner and Codex hook contracts.

---

### Pitfall 2: Mutable Provenance and Competing Sources of Truth

**What goes wrong:**
`state.json`, a Material Passport, a graph node, or a mutable manifest is edited in place and becomes the only account of what happened. Event deletion, reordering, artifact replacement, or graph repair can silently rewrite scientific history. SHA-256 fields do not help if an attacker or bug can replace both an artifact and its mutable hash record.

**Why it happens:**
Mutable state is convenient for status queries, and graph stores make relationships easy to update. “Append-only JSONL” is also often implemented as an ordinary writable file without sequence validation, tamper evidence, or a replay oracle.

**How to avoid:**
- Make the append-only ledger the transition record and immutable, content-addressed artifact versions the evidence record.
- Give every event a run ID, monotonic sequence, event ID/idempotency key, prior-event digest, base revision, timestamp, actor, operation, and artifact digests.
- Treat `state.json`, passports, query indexes, and graphs as derived snapshots with `derived_from_event_seq` and ledger-head digest.
- Represent corrections, waivers, invalidations, human verification, and withdrawals as new events; never overwrite the original assertion.
- Verify the hash chain and every referenced artifact on resume/finalize. Optionally sign finalized run roots when evidence crosses trust boundaries.
- Keep one canonical writer. Workers return immutable envelopes; they never write canonical state.

**Warning signs:**
- `state.json` can be edited without producing a ledger event.
- A graph write changes whether a claim is considered verified.
- Artifact paths are stable but content can change in place.
- Event records have timestamps but no sequence, predecessor digest, or idempotency key.
- Replaying the ledger does not reproduce the current state byte-for-byte or semantically.

**Phase to address:**
Phase 0 fixes schemas and authority rules. Phase 1 implements ledger validation, immutable artifact versions, replay, compare-and-swap, and single-writer ownership. Phase 3 proves the graph is only a projection.

**Confidence:** HIGH — required by the project brief and supported by W3C PROV’s distinction among entities, activities, agents, derivations, and revisions.

---

### Pitfall 3: Non-Atomic Checkpoints and Split-Brain Resume

**What goes wrong:**
A crash lands between artifact creation, ledger append, and state replacement. Resume sees an event for a missing artifact, a new state with no event, a torn final JSONL line, two accepted results for one revision, or a checkpoint that looks complete but lacks durable bytes. Retrying may duplicate a transition or overwrite a newer result.

**Why it happens:**
Atomic rename is mistaken for a complete transaction. It does not make a multi-file protocol atomic by itself, and buffered writes may not survive power loss. Concurrent appenders to a regular file are also not a substitute for a single serialized writer.

**How to avoid:**
- Use a documented commit protocol: write immutable artifact to a temporary file, flush and `fsync`, atomically rename, sync its directory; append one revisioned event and sync; derive state to a temporary file, sync, atomically replace, then sync the state directory.
- Treat state as recoverable cache. If a crash occurs after the event but before state replacement, replay the ledger.
- Serialize canonical writes with an inter-process lock and revision compare-and-swap.
- Make every command idempotent through a caller-supplied operation ID and a deterministic result for duplicates.
- On resume, tolerate only a torn final ledger record: seal and preserve the damaged segment, start a new segment from the last validated event digest, and append an explicit recovery event. Corruption in the middle is blocking; never silently rewrite canonical history.
- Consider SQLite WAL for transactional metadata if the file protocol becomes more complex than can be proved and tested safely.

**Warning signs:**
- Tests call `checkpoint` and then `resume` only after a clean process exit.
- `write_text(state.json)` or equivalent writes directly to the canonical path.
- An event references a path before the artifact is durably installed.
- Two processes can append canonical events.
- Duplicate CLI commands advance the state twice.
- Recovery logic “uses whichever file is newest.”

**Phase to address:**
Phase 1. The exit gate must include crash/restart, stale revision, duplicate command, lock contention, disk-full, I/O error, and crash-during-recovery cases.

**Confidence:** HIGH — SQLite’s atomic-commit and crash-testing documentation demonstrates that atomicity must be tested under interrupted and reordered writes, not inferred from happy paths.

---

### Pitfall 4: Recovery Tests That Never Simulate Failure

**What goes wrong:**
The project advertises crash-safe resume because it can stop and restart normally. Real faults occur during writes, lock acquisition, graph sync, hook execution, result acceptance, and recovery itself. Those paths remain untested and may corrupt or silently skip work.

**Why it happens:**
Graceful stop/resume fixtures are easy, deterministic, and fast. Process kills, failpoints, partial writes, and compound failures require a dedicated harness and clear post-crash invariants.

**How to avoid:**
- Add deterministic failpoints before and after every durable write, rename, `fsync`, ledger append, lock acquisition, transition, and graph epoch swap.
- Spawn the runtime in a child process and terminate it with an uncatchable kill at each failpoint.
- Inject short writes, `ENOSPC`, permission changes, I/O errors, lock-holder death, malformed/torn JSON, missing artifacts, and stale worker delivery.
- After each fault, assert one oracle: the transition is wholly absent or wholly committed; provenance remains internally consistent; retry is idempotent; mandatory work is not skipped.
- Include compound faults, such as an I/O error while recovering from a crash.
- Persist raw fault schedule, exit status, filesystem snapshot hashes, recovery log, and oracle results as test evidence.

**Warning signs:**
- “Recovery test” means calling a `stop` command before restart.
- No tests use child processes, failpoints, filesystem fault injection, or hard termination.
- Corrupt state is silently recreated without recording what was lost.
- Test assertions check only that the command exits zero, not that provenance is equivalent.

**Phase to address:**
Phase 0 creates one failure-driven end-to-end fixture. Phase 1 expands it across every commit boundary. Phase 4 makes recovery and evidence-chain cases part of the fixed benchmark.

**Confidence:** HIGH — official SQLite testing uses simulated I/O errors, random crashes during writes, post-crash integrity checks, and compound-failure tests.

---

### Pitfall 5: Partial, In-Place, or Non-Equivalent Graph Rebuilds

**What goes wrong:**
The semantic graph contains a mixture of old and new projection generations. Deleted or renamed files remain searchable; superseded claims look current; one stage is rebuilt while edges from another remain stale. Rebuilding after cache deletion returns different answers, making the graph an unauditable second truth store.

**Why it happens:**
Incremental upserts are easier than complete reconciliation. “Idempotent insert” is confused with deletion handling, supersession semantics, and atomic publication of a complete graph generation.

**How to avoid:**
- Build a complete projection into a shadow database/generation keyed by schema version, canonical manifest digest, and ledger head.
- Validate counts, referential integrity, source path/hash coverage, required query invariants, and no dangling active edges before atomically marking the generation current.
- Use stable IDs derived from run ID plus canonical artifact identity; use explicit tombstones and `SUPERSEDES`/invalidation edges for deletion and revision history.
- Make incremental sync consume a ledger sequence range and record a watermark. A missed sequence blocks publication rather than being skipped.
- Run a golden equivalence test: full rebuild from canonical artifacts, incremental rebuild from the same start, and a fresh cache deletion must produce equivalent normalized query results.
- Never allow graph state to advance workflow gates.

**Warning signs:**
- Reindex only performs upserts.
- A delete or rename test is absent.
- Queries can see nodes from two schema or projection versions.
- A rebuild mutates the only graph in place.
- `indexed_at` is the only freshness marker; no source hash or ledger watermark exists.
- Graph loss prevents run resume.

**Phase to address:**
Phase 3, with required groundwork in Phase 0 schemas and Phase 1 immutable artifacts. Phase 1F must already handle file deletion, rename, and stale-cache detection.

**Confidence:** HIGH — this follows directly from the project’s declared graph-as-projection boundary.

---

### Pitfall 6: Unrestricted Filesystem Bridge and Symlink/TOCTOU Escape

**What goes wrong:**
`read_file`, search, context, or indexing tools can read credentials, private corpora, browser/session stores, files outside allowed roots, or paths swapped through symlinks between validation and open. A model or malicious indexed document can then exfiltrate those bytes through MCP output or a later network tool.

**Why it happens:**
Path-prefix checks and ignore files are treated as authorization. MCP roots are treated as UI hints. Hook-based blocking is treated as a sandbox even though current Codex documentation explicitly says `PreToolUse` interception is incomplete.

**How to avoid:**
- Enforce authorization inside the MCP server on every operation. Roots and allowlists are inputs to policy, not the policy implementation.
- Canonicalize roots once; reject absolute paths, `..`, device paths, alternate streams, and paths outside an allowed root.
- Open through directory handles with no-follow semantics where available, then verify the opened object remains under the authorized root; do not validate one path and later reopen another by string.
- Default tools to read-only and deny credential/key/session patterns, `.git` internals, private caches, and unpublished corpora unless explicitly opted in.
- Separate index roots from export roots. Never package or export private indexed content by default.
- Apply OS sandboxing and minimal process permissions in addition to Codex approvals and hooks.
- Test symlink chains, junctions, bind mounts, case-folding, rename races, deleted roots, and nested repositories on each supported OS.

**Warning signs:**
- Authorization is `resolved_path.startswith(root_string)`.
- `.cbmignore` is the only secret control.
- The server accepts arbitrary absolute paths.
- Tests cover `../` but not symlink replacement or platform-specific links.
- A trusted hook is required for filesystem safety.
- Indexing defaults include `.env`, keys, browser data, or downloaded private PDFs.

**Phase to address:**
Phase 1F. Phase 2 hooks are defense in depth only. Phase 4 adds prompt-injection/exfiltration red-team cases.

**Confidence:** HIGH — MCP roots require boundary validation and current Codex docs state that `PreToolUse` is not a complete enforcement boundary.

---

### Pitfall 7: Unbounded MCP Output, Search, and Traversal

**What goes wrong:**
A single tool call returns a multi-megabyte PDF/text file, all matches in a corpus, an unbounded graph traversal, or base64 media. Codex context is flooded, stdio/JSON parsing spikes memory, requests hit client timeouts, and useful evidence is truncated without an auditable indication. Expensive regex or traversal becomes a local denial of service.

**Why it happens:**
MCP supports rich content blocks, but it does not automatically bound a custom tool’s result. Protocol pagination for `tools/list` does not paginate project-defined `search_files` or `read_file`; those tools need their own cursor contracts.

**How to avoid:**
- Give every listing/search/traversal tool explicit `limit`, opaque cursor, stable ordering, `next_cursor`, `truncated`, returned-count, total-if-cheap, and execution-time fields.
- Start with opinionated defaults: at most 200 rows, 64 KiB text per response, traversal depth 3, and a short server-side query deadline. Expose lower caller limits and conservative hard caps.
- Return metadata and resource links for large artifacts; require chunked range reads with line/byte boundaries and content hash.
- Cap regex length/complexity, FTS match count, context radius, graph depth/fan-out, PDF pages, decompressed bytes, and concurrent calls.
- Define MCP `outputSchema`; validate server results and return `isError: true` with actionable bounded errors.
- Emit explicit truncation/provenance metadata so a partial result can never be mistaken for a complete search.

**Warning signs:**
- Tool schemas have no limit or cursor.
- `read_file` returns the whole file by default.
- “No matches” and “search timed out/truncated” share the same result shape.
- A result embeds large binary/base64 content when a resource link would suffice.
- Client timeout is the only resource limit.
- Graph queries accept arbitrary depth.

**Phase to address:**
Phase 1F, verified by boundary, timeout, cancellation, oversized-file, high-fan-out, and context-budget tests.

**Confidence:** HIGH — current MCP defines pagination, structured output schemas, error handling, timeouts, and security duties, but custom domain tools must implement their own bounded result contracts.

---

### Pitfall 8: Stale Codex Plugin, Hook, and MCP Contracts

**What goes wrong:**
The package installs but its skill, MCP server, or hooks are undiscovered, skipped as untrusted, parsed but not executed, or invoked with changed fields. The runtime assumes a hook can block an action it cannot intercept, relies on an unstable transcript format, hardcodes one MCP protocol version, or emits capabilities it did not negotiate.

**Why it happens:**
The existing ARS adapter preserves Claude-era metadata and internal full-runtime manifests. Current Codex plugin packaging uses `.codex-plugin/plugin.json`, root-level `.mcp.json`, and event-keyed hook configuration. Current Codex also launches matching hooks concurrently, requires trust for non-managed plugin hooks, supports only command handlers today, cannot stop a subagent from `SubagentStart`, and documents incomplete `PreToolUse` interception.

**How to avoid:**
- Build to the current Codex plugin layout: one `.codex-plugin/plugin.json`, plugin-root `skills/`, `.mcp.json`, and `hooks/hooks.json`, with `./`-relative paths confined to the plugin.
- Treat the ARS full-runtime manifest as source metadata, not a Codex plugin manifest or execution engine.
- Replace/translate the existing ARS hook metadata into the current release schema; do not package the current announcement file as policy enforcement.
- Make safety invariants server/runtime enforced. Hooks add context, deny supported calls, and record evidence, but are not the only boundary.
- Add an installed-package compatibility suite that starts a fresh Codex task, verifies plugin discovery, hook trust behavior, `SessionStart`/resume, subagent events, MCP initialize/version negotiation, capability declarations, `tools/list`, tool calls, output-schema validation, approvals, and shutdown.
- Test against a pinned minimum and current Codex release. Record Codex version and MCP protocol version in every run.
- Do not parse `transcript_path` as a stable API; persist first-party event data instead.

**Warning signs:**
- Tests import plugin files directly but never install the package cache copy.
- Environment flags are treated as proof that Codex enabled a plugin or trusted hooks.
- Hook JSON uses custom `event` records rather than the current event-keyed schema and no adapter translates it.
- `SubagentStart` is expected to block a worker.
- `PreToolUse` is expected to intercept web, every shell path, or all side effects.
- Server replies with one hardcoded MCP version regardless of the client request.
- Renaming `serverInfo.name` is treated as MCP compatibility completion.

**Phase to address:**
Phase 0 is a release-blocking contract-repair phase. Phase 2 implements current hooks/subagents. Compatibility tests run continuously thereafter.

**Confidence:** HIGH — verified against current official Codex plugin/hook/config documentation and the current MCP lifecycle specification.

---

### Pitfall 9: License Incompatibility and Non-Redistributable Bundles

**What goes wrong:**
The plugin is labeled MIT or “private” while bundling CC BY-NC 4.0 ARS content, omits attribution/change notices, loses third-party notices from a static file-base binary, packages restricted source/full text, or later moves to a paid/commercial marketplace without relicensing. Users cannot determine which terms govern code, prompts, docs, models, generated indexes, and source snapshots.

**Why it happens:**
A repository-level license is mistaken for a complete dependency license. Private development is assumed to settle future distribution rights. CC BY-NC is treated as ordinary open-source software licensing even though Creative Commons discourages CC licenses for software and the NC term restricts commercial use.

**How to avoid:**
- In Phase 0, create a machine-readable source/license inventory with upstream URL, commit, included paths, patch hash, SPDX/license reference, notice path, modification markers, and intended use/distribution class.
- Keep three partitions: original workbench code, MIT/permissive file-base code and notices, and CC BY-NC ARS material. Do not relicense the combined tree as MIT.
- For a potentially commercial plugin, obtain written commercial permission/dual license for ARS and experiment-agent or replace them with clean-room, independently authored contracts. Do not infer permission.
- Preserve ARS attribution, license link/text, copyright, disclaimer, and modification notices. Preserve file-base MIT notice plus generated third-party notices/SBOM in source and binary packages.
- Gate builds on license scanning and exact notice generation. Scan the actual staged package, not only the source repository.
- Treat third-party PDFs/corpora separately: indexing permission is not redistribution permission. Exclude private/full-text source content and derived caches from packages by default.
- Have counsel review commercial/internal-company ambiguity and marketplace terms before public or paid distribution.

**Warning signs:**
- A single top-level `license: MIT` covers the whole plugin.
- No `THIRD_PARTY_NOTICES`, SBOM, or staged-package license test exists.
- The roadmap says “open source later” without a rights plan for ARS.
- Modified CC material is shipped without identifying changes.
- File-base UI/model/grammar assets are included but only the root MIT file is copied.
- Paid PDFs, extracted text, or local indexes appear in release archives.

**Phase to address:**
Phase 0, before vendoring or public package scaffolding. Phase 1F verifies file-base binary notices. Phase 4 enforces source-access/export policy.

**Confidence:** MEDIUM for distribution conclusions — the license texts and restrictions are verified; final applicability depends on facts and jurisdiction and requires counsel.

---

### Pitfall 10: Source Drift and Irreproducible Vendoring

**What goes wrong:**
A build uses whatever happens to be in a local ignored checkout, applies a patch twice or partially, downloads an unpinned dependency, or rebuilds from an upstream branch that moved. The binary reports the expected version while its source, generated grammars, embedded model data, or notices differ from the audited snapshot.

**Why it happens:**
In-place local patching is fast. Commit pins are recorded in prose instead of verified by tooling. Generated and vendored assets have separate provenance that is easy to omit.

**How to avoid:**
- Build in a new temporary tree from an exact upstream commit; require a clean baseline; verify the upstream tree digest; apply exactly one patch whose SHA-256 is in a machine-readable lock; fail on fuzz, offset, rejects, or residual dirt.
- Record a SLSA-like build definition: source commit, patch digests, external parameters, resolved dependencies/assets, builder/toolchain versions, timestamps, and output digests.
- Disable update checks and network fetching in reproducible/offline builds. Vendor or lock every required grammar, model asset, extractor, and UI dependency.
- Generate and compare an expected source manifest before compilation and an SBOM/notice set after packaging.
- Add a reproducible-build test on two clean workers; investigate any binary difference or document unavoidable nondeterminism.
- Record the exact upstream and patch provenance in every workbench run that invokes file-base.

**Warning signs:**
- Build instructions start from `.external/...` without checking cleanliness.
- `git apply --check` fails because the working tree is already patched, yet the build proceeds.
- A version string is the only source identity.
- Git commit is pinned but generated assets are not hashed.
- Documentation disagrees on inventory counts (the supplied file-base materials currently mention both 158 and 159 grammars).
- CI has network access and fetches floating branches/tags.

**Phase to address:**
Phase 0 establishes the source lock and license inventory. Phase 1F implements clean, verified file-base builds. Every release repeats the staged-package provenance gate.

**Confidence:** HIGH — the supplied checkout is at the pinned commit and its dirty diff exactly matches the supplied patch, demonstrating both that provenance can be recovered and why in-place builds are fragile.

---

### Pitfall 11: Scientific Source Drift and Access-State Laundering

**What goes wrong:**
A claim links to a DOI/URL but not the exact evidence version used. Metadata, abstracts, web pages, datasets, preprints, and software change; papers are corrected or retracted. A cached abstract is later represented as full-text verification, or inaccessible/paid evidence is marked supported by inference. Re-running the audit produces a different verdict without an explicit provenance change.

**Why it happens:**
Stable identifiers are confused with immutable content. Retrieval caches optimize by citation key only. Access state, parser version, quoted span, and license are omitted from claim-evidence links.

**How to avoid:**
- Identify each evidence entity by canonical identifier/URL plus retrieved time, source version/status, content hash when bytes are lawfully available, access tier, media type, license state, and extractor/version.
- Store claim-level evidence spans or structured locations with the source hash; distinguish metadata-only, abstract, open full text, local private full text, and inaccessible/paid.
- Make corrections, retractions, new versions, and cache invalidations new provenance events. Never mutate an old “verified” record in place.
- Reverify on source hash/status change, verifier version change, claim change, citation change, or configured staleness policy.
- Route inaccessible or unclear-license full text to `blocked_human_review`; machine inference cannot upgrade it to `human_verified`.
- Preserve legal boundaries: when snapshots cannot be redistributed, retain metadata and local digest/reference rather than exporting the bytes.

**Warning signs:**
- `source_id` is only DOI or URL.
- Cache keys omit content/verifier version and access tier.
- “Verified” does not name the evidence span or experiment output.
- Abstract-only support and full-text support share one status.
- Retraction/correction status is not checked or recorded.
- A changed web page silently changes an old run’s evidence.

**Phase to address:**
Phase 0 defines source, claim, access, and verification schemas. Phase 1F preserves file hashes/extraction provenance. Phase 4 implements revalidation, human gates, and claim-evidence benchmarks.

**Confidence:** HIGH — the Science Workbench contract explicitly distinguishes access states; W3C PROV requires fixed-aspect entities to make provenance meaningful for changing resources.

---

### Pitfall 12: Weak Evals and Benchmark Theater

**What goes wrong:**
Tests prove JSON shape and prompt coverage but not scientific correctness, runtime execution, recovery, security, or evidence traceability. A benchmark reports one aggregate score without raw runs, scorer version, confidence intervals, failure categories, or hard invariants. The same model produces and grades outputs, allowing style to masquerade as validity.

**Why it happens:**
Static validators are cheap and deterministic. Research quality is multidimensional, and exact gold answers are difficult. Teams optimize the benchmark they can run rather than the failures the product must prevent.

**How to avoid:**
- Split evals into deterministic invariants and model-quality judgments. Provenance completeness, state transitions, graph equivalence, access-state honesty, path isolation, and recovery are hard pass/fail gates.
- Build task-specific datasets with normal, boundary, adversarial, multilingual/CJK, LaTeX/BibTeX, malformed PDF, stale source, contradictory evidence, inaccessible source, malicious prompt, and crash cases.
- Evaluate orchestration decisions, tool selection/arguments, handoff accuracy, worker-result acceptance, citation existence, claim relevance, statistical interpretation, reviewer independence, and final artifact traceability separately.
- Keep a held-out regression set and add every production failure. Version datasets, rubrics, scorers, model/runtime config, seeds, and expected invariants.
- Calibrate automated graders against blinded expert review; measure agreement and preserve disagreements. Never use an uncalibrated same-model judge as the only oracle.
- Publish raw run artifacts and per-case results alongside any aggregate score. A high average cannot waive a zero-tolerance provenance or security failure.

**Warning signs:**
- Tests assert that prompts mention “audit” or that files exist, but never inspect execution evidence.
- Evaluation is described as “looks good” or only one LLM score.
- No adversarial, edge, multilingual, failure, or inaccessible-source cases exist.
- Benchmark data, scorer, or model configuration is unversioned.
- Recovery and graph rebuilds are not benchmark dimensions.
- Failed cases are removed rather than added to regression tests.

**Phase to address:**
Phase 0 establishes acceptance invariants and one real end-to-end case. Phase 4 owns the fixed benchmark, human calibration, raw evidence, and continuous regression suite.

**Confidence:** HIGH — current OpenAI evaluation guidance recommends task-specific real-world evals, comprehensive logging, continuous evaluation, human calibration, and typical/edge/adversarial cases.

---

### Pitfall 13: Untrusted Research Content Becomes Runtime Instruction

**What goes wrong:**
An indexed Markdown file, PDF, bibliography note, reviewer comment, dataset cell, or MCP tool result contains prompt injection that tells an agent to ignore policy, read other files, reveal credentials, alter the ledger, or upload private data. Malformed/compressed documents can also exhaust or exploit extractors.

**Why it happens:**
Research sources mix prose and instructions, and agent prompts often paste retrieved content directly into a high-authority context. Local files are mistakenly trusted because they are local. The supplied patch’s direct-PDF heuristic is a discovery probe, not a safe or complete extraction pipeline.

**How to avoid:**
- Label retrieved material as untrusted data with explicit delimiters and source IDs; never concatenate it into developer/system instructions.
- Permit canonical writes only through schema-validated parent runtime commands. Workers and content cannot directly advance gates.
- Run document extraction in a sandbox with CPU, memory, file-size, page-count, decompression, recursion, and timeout limits; identify MIME by content, not extension.
- Keep network egress disabled by default for source-processing workers; require explicit consent and minimal payloads for external verification.
- Sanitize tool outputs, prevent terminal/control-sequence injection, and validate structured content before model exposure.
- Add adversarial fixtures whose source text requests secret access, policy override, graph mutation, and false verification.

**Warning signs:**
- Retrieved text is inserted above or beside runtime policy without a data boundary.
- A source can name a tool and cause it to run without assignment policy.
- Local documents are called “trusted input.”
- PDF extraction runs with host credentials and unrestricted resources.
- Tool output is logged/rendered without escaping or size limits.

**Phase to address:**
Phase 1F hardens ingestion/extraction and output. Phase 2 isolates worker permissions and canonical writes. Phase 4 red-teams source injection and data exfiltration.

**Confidence:** HIGH — ARS itself declares research materials untrusted, and MCP requires input validation, access controls, output sanitization, timeouts, and audit logging.

---

### Pitfall 14: Stale, Duplicate, or Nondeterministically Merged Worker Results

**What goes wrong:**
A worker returns after the run has advanced, retries deliver the same result twice, or parallel results are merged in arrival order. A stale analysis overwrites a newer claim set, reviewers see different base artifacts, and resume repeats only part of a merge.

**Why it happens:**
Parallelism is added before assignment/result schemas and acceptance semantics are stable. “Parent is the only writer” is declared but not enforced with revisions and idempotency.

**How to avoid:**
- Assignment envelopes include assignment ID, base run revision, stage, allowed inputs and hashes, output schema/version, permission policy, deadline, and independence group.
- Result envelopes include assignment ID, base revision, consumed hashes, produced hashes, status, warnings, model/runtime metadata, and idempotency key.
- Parent acceptance is a compare-and-swap transaction: reject stale base revisions, unknown inputs, schema mismatch, duplicate IDs, and unauthorized paths.
- Merge accepted results in deterministic task order, not completion order. Preserve each immutable result even when rejected or superseded.
- Resume reconstructs pending/accepted/rejected assignments from the ledger and never blindly redispatches completed work.

**Warning signs:**
- Result acceptance checks only that JSON parses.
- Worker outputs write directly into canonical artifact paths.
- Merge order depends on wall-clock completion.
- Retried workers create duplicate claims or events.
- A stale result is “fixed up” silently to fit current state.

**Phase to address:**
Phase 1 defines revision, idempotency, and acceptance transactions. Phase 2 implements workers and deterministic merge tests.

**Confidence:** HIGH — directly implied by the single-parent-writer architecture and current Codex multi-agent nondeterminism guidance.

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Treat `state.json` as canonical | Simple implementation | Silent history rewrites and irrecoverable split-brain | Never |
| Call planner output “execution” | Compelling demo | Scientifically false agent/reviewer provenance | Never |
| Use hooks as the security boundary | Central-looking policy | Bypass through unsupported paths, disabled/untrusted hooks, concurrency | Never |
| Patch an ignored checkout in place | Fast local build | Non-idempotent, unreproducible source state | Local exploration only; never release/CI |
| Build graph before canonical schemas stabilize | Early visual value | Competing semantics and expensive migrations | Never for canonical research nodes |
| Whole-file MCP reads | Minimal API | Context exhaustion and data leakage | Tiny test fixtures only, with hard byte cap |
| Direct PDF text heuristic as extraction | No dependency | False positives/negatives; no page/span provenance | Discovery/classification only, never evidence verification |
| Same-model grading only | Cheap iteration | Correlated blind spots and benchmark gaming | Smoke tests only, clearly labeled |
| Generic “<5% difference” reproducibility rule | Easy verdict | Scientifically invalid across metrics/distributions | Never as a universal rule; define metric-specific tolerances |
| Depend on MCP experimental tasks for durable runs | Built-in-looking async model | Task TTL/deletion and client-version dependence can lose provenance | Optional transport optimization only; ledger remains authoritative |
| Package all sources under one license label | Easy manifest | Misrepresentation and blocked redistribution | Never |
| Cache verification by citation key | Fast repeat checks | Access/version/source drift hidden | Only if key includes source hash, access tier, verifier version, and policy |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Codex plugin package | Put all files under `.codex-plugin/` or omit the required manifest | Keep only `.codex-plugin/plugin.json` there; use plugin-root `skills/`, `.mcp.json`, `hooks/`, and `assets/` with `./`-relative paths |
| Plugin cache | Test the source directory directly | Install the package and test the cached installed copy in a fresh task |
| Plugin hooks | Assume enabled plugin means trusted hooks | Test trust review, changed-hook hash invalidation, disabled hooks, and managed-hook policy |
| Hook execution | Expect multiple hooks to run serially or one to prevent another from starting | Design for concurrent matching hooks and enforce invariants in the runtime/server |
| `SubagentStart` | Return `continue: false` to stop a worker | Current Codex does not stop subagent start that way; validate before dispatch in the parent |
| `PreToolUse` | Rely on it to intercept every shell/web/file side effect | Use it as defense in depth; server/OS permissions enforce boundaries |
| MCP lifecycle | Hardcode one protocol version or use capabilities before negotiation | Implement initialize/version negotiation, capability checks, initialized state, timeouts, and clean shutdown |
| MCP tools | Return text-only ad hoc JSON | Publish input/output JSON Schemas, validate both sides, distinguish protocol and execution errors |
| MCP roots | Trust caller paths after one prefix check | Canonicalize, authorize, open safely, and revalidate against roots on every operation |
| Custom MCP search/read | Assume MCP list pagination applies automatically | Add domain-specific opaque cursors and hard result budgets |
| MCP experimental tasks | Use task records as the run ledger | Treat tasks as ephemeral; persist canonical workbench events/artifacts independently |
| file-base patch | Treat server rename and generic file discovery as complete files-first support | Add first-class files table, bounded reads, FTS, extraction provenance, deletion/rename, and security tests |
| ARS full-runtime planner | Execute emitted labels as if they were runtime evidence | Use it only as routing input; runtime emits separate lifecycle evidence |
| Bibliographic APIs | Conflate metadata, abstract, OA hint, and full text | Persist access tier and source version; human-gate inaccessible evidence |
| PDF/doc extraction | Run parsers unsandboxed and trust extension | Content sniffing plus sandbox, resource budgets, page/span provenance, and malformed-file tests |
| License packaging | Copy only root licenses | Generate notices/SBOM from the staged source and binary payload, including grammars, model data, UI, and ARS partitions |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Whole-file/tool-result responses | Slow JSON, memory spikes, context truncation | 64 KiB default response cap, chunk/range reads, resource links | One multi-MB PDF/text file can be enough |
| Unbounded search results | Codex receives thousands of low-value matches | Stable ranking, 200-row pages, opaque cursor, explicit truncation | Thousands of files or common terms |
| Regex over full corpus | CPU saturation and timeouts | FTS-first, regex complexity/length limits, deadlines | Tens of MB with pathological patterns |
| CJK/LaTeX naive tokenization | Apparently fast index with poor recall | Dedicated tokenizer tests and gold queries | Immediately on the motivating corpus |
| In-place full graph rebuild | Long periods of mixed or unavailable state | Shadow generation, validation, atomic publication | Any nontrivial run; worsens rapidly above ~100k nodes |
| Replay ledger from byte zero on every command | Startup latency grows with run age | Validated snapshots keyed to ledger head, then replay tail | Roughly 100k events or 100 MB ledger |
| Rehash every large corpus file every query | High I/O, battery/SSD cost | Metadata fast path plus verified content hashing on ingestion/change | Multi-GB corpora |
| Unlimited subagent fan-out | Rate, memory, evidence, and merge explosion | Bounded concurrency, task budgets, deterministic queue | Dozens of workers/artifacts, much earlier under large context |
| Unbounded PDF extraction | Hangs or memory exhaustion | Page, bytes, decompression, CPU, memory, and timeout caps | A single malformed or adversarial document |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Trusting local research files | HIGH — prompt injection, unauthorized tool use | Treat all source content as untrusted data; isolate instructions and validate actions |
| Prefix-only path authorization | CRITICAL — root escape and secret theft | Handle-based safe open, canonical roots, no-follow, post-open validation |
| Indexing credentials/private corpora by default | CRITICAL — persistent leakage through search/graph/export | Deny patterns and roots by default; explicit consent and separate private index |
| Letting workers write canonical state | CRITICAL — provenance forgery/races | Read-only workers; parent-only schema/CAS acceptance |
| Assuming hooks enforce all policy | HIGH — bypass when untrusted, disabled, unsupported, or concurrent | Runtime/server/OS enforcement; hooks only reinforce and observe |
| Unbounded tool output/query | HIGH — local denial of service and context poisoning | Hard bytes/rows/time/depth/concurrency budgets |
| Logging secrets or full private content | HIGH — audit trail becomes exfiltration store | Structured redaction, content hashes, minimal snippets, protected run permissions |
| Executing extractors with host authority | HIGH — parser exploit/resource abuse | Sandboxed subprocess, no network, least privilege, resource limits |
| Silent external verification upload | CRITICAL — unpublished-data disclosure | Explicit provider, payload class, consent, and minimal metadata-only default |
| Guessable/shared run or task IDs | HIGH — cross-run disclosure/confusion | High-entropy IDs plus authorization context; never use MCP task IDs as access control |
| Trusting MCP tool annotations/results | HIGH — deceptive side-effect claims or injected output | Treat annotations as untrusted, validate result schema, sanitize before model exposure |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Binary “verified” badge | Hides metadata-only, abstract-only, machine, and human distinctions | Show access tier, verifier, evidence span, timestamp, and remaining blockers |
| Silent truncation | User assumes search/read was complete | Surface `truncated`, limits, cursor, and coverage summary prominently |
| Ambiguous resume | User cannot tell what reran or was reused | Show ledger head, checkpoint revision, reused artifacts, invalidations, and next action |
| Simulated agent labels | User believes independent experts ran | Display actual execution mode and worker evidence links |
| Hidden waivers | “Ready” papers contain bypassed gates | List waiver actor, reason, scope, timestamp, and affected claims in final summary |
| Graph freshness hidden | Stale relationships look authoritative | Show projection generation, source ledger head, schema version, and rebuild status |
| License/access state hidden | User exports material they cannot redistribute | Show per-source access/license/export policy and block unsafe bundles |
| Recovery that silently discards data | User sees success but loses provenance | Block, quarantine damage, record recovery event, and explain required human action |

## "Looks Done But Isn't" Checklist

- [ ] **Plugin package:** The source layout exists — verify installation from the cached package in a fresh Codex task.
- [ ] **MCP server:** `initialize` succeeds — verify version negotiation, capabilities, initialized state, list/call errors, timeouts, and shutdown.
- [ ] **Hooks:** JSON parses — verify current event schema, trust review, disabled/untrusted behavior, concurrency, and actual supported blocking semantics.
- [ ] **Orchestration:** Agent plan exists — verify distinct worker lifecycle IDs, assignment/result hashes, isolated inputs, and accepted results.
- [ ] **Reviewer panel:** Multiple sections exist — verify blind assignments and preserved dissent before synthesis.
- [ ] **Ledger:** Events append — verify sequence/hash chain, middle-corruption detection, torn-tail recovery, and deletion/reordering detection.
- [ ] **Checkpoint:** Clean resume works — verify hard crashes and I/O failures at every persistence boundary.
- [ ] **Idempotency:** Retry exits zero — verify no duplicate event, artifact, claim, or stage transition.
- [ ] **Graph sync:** Queries return answers — delete the cache and prove full/incremental rebuild equivalence including delete/rename/supersede.
- [ ] **Files-first MCP:** Files can be read — verify root confinement, symlink races, secret exclusions, byte/row/time limits, and explicit truncation.
- [ ] **PDF support:** A PDF node appears — verify safe extraction, page/span provenance, malformed/scanned/encrypted documents, and no false full-text claim.
- [ ] **Citation check:** DOI exists — verify nearby claim support, source version, access tier, retraction/correction state, and evidence span.
- [ ] **Experiment record:** Command is saved — verify code/data/environment hashes, seed, hardware/runtime, logs, metric-specific tolerance, and rerun evidence.
- [ ] **Ready gate:** PDF renders — verify unresolved mandatory gates, waivers, stale figures, source access blockers, and main-result traceability.
- [ ] **License inventory:** Root licenses are copied — scan the staged package and binary notices, including ARS, grammars, embedded model data, and UI assets.
- [ ] **Benchmark:** Aggregate score is high — inspect raw cases, hard-gate failures, scorer/model versions, human calibration, and adversarial coverage.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Fake orchestration already recorded | HIGH | Freeze affected runs; mark claims/reviews unverified; preserve old artifacts; append invalidation events; rerun with real worker evidence |
| Ledger tail torn | LOW | Validate through last complete hash-linked event; quarantine tail bytes; reconstruct state; append recovery event |
| Ledger middle corrupted/deleted | HIGH | Block run; restore from verified backup/replica; compare finalized root digest; never guess missing transitions |
| State snapshot corrupt | LOW | Rebuild from validated ledger and immutable artifacts; write a new snapshot with source ledger head |
| Graph partial/stale | MEDIUM | Take projection offline; rebuild a shadow generation from canonical artifacts; compare gold queries; atomically publish |
| Unauthorized file indexed | HIGH | Stop server; revoke/export-disable index; identify all derived graph/cache/log artifacts; securely delete where policy permits; rotate exposed secrets; append incident record |
| Unbounded call wedges server | MEDIUM | Cancel/kill isolated request; restart from canonical state; tighten per-call budgets; add regression fixture |
| Stale worker result accepted | HIGH | Append invalidation/supersession; roll forward from prior valid revision; rerun dependent gates and graph projection |
| Source changed/retracted | MEDIUM | Create new source entity/version; invalidate affected verifications; queue claim re-review; preserve historical run |
| License violation found pre-release | MEDIUM | Remove/replace affected content, regenerate notices/SBOM, rebuild from clean source, rerun staged-package scan |
| License violation found post-release | HIGH | Halt distribution, preserve evidence, notify counsel/rights holder as advised, issue corrected package and downstream notice |
| Weak eval shipped a defect | MEDIUM | Add the incident as a versioned regression case, repair oracle/rubric, rerun historical baseline and current candidate |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Fake orchestration | Phase 0 + Phase 2 | Canary proves real worker start/stop/result evidence; inline mode cannot claim independence |
| Mutable provenance | Phase 0 + Phase 1 | Ledger replay reproduces state; hash-chain tampering and artifact replacement are detected |
| Non-atomic checkpoints | Phase 1 | Kill/failpoint at every write boundary yields wholly old or wholly new committed state |
| Fake recovery testing | Phase 0 + Phase 1 + Phase 4 | Hard-kill, I/O, disk-full, lock, and compound-failure matrix produces inspectable evidence |
| Partial graph rebuild | Phase 3 | Fresh/full/incremental builds return equivalent normalized gold queries after delete/rename/supersede |
| Unrestricted filesystem | Phase 1F | Cross-platform traversal, symlink/junction, rename-race, secret, and root-removal tests fail closed |
| Unbounded MCP output | Phase 1F | Every tool obeys bytes/rows/time/depth caps and explicit pagination/truncation contracts |
| Stale Codex/MCP contracts | Phase 0 + continuous | Installed-plugin matrix passes on pinned minimum/current Codex and negotiated MCP versions |
| License incompatibility | Phase 0 | Staged package license/SBOM gate passes; commercial ARS permission or clean replacement is documented |
| Source drift | Phase 0 + Phase 1F | Clean build verifies commit, patch hash, source manifest, notices, and reproducible output |
| Scientific source drift | Phase 0 + Phase 4 | Source/access/version changes invalidate only the correct claim-verification records and create review work |
| Weak evals | Phase 4, seeded in Phase 0 | Versioned normal/edge/adversarial corpus, hard invariants, raw runs, and calibrated human agreement |
| Untrusted source content | Phase 1F + Phase 2 + Phase 4 | Prompt-injection and malicious-document fixtures cannot escape policy or exfiltrate data |
| Stale/duplicate worker results | Phase 1 + Phase 2 | CAS rejects stale base revisions; retries are idempotent; merge is deterministic |

## Roadmap Ordering Consequences

1. **Phase 0 must be a genuine executable and legal gate.** Stabilize schemas, provenance modes, current Codex plugin/hook/MCP contracts, source locks, and license partitions before implementing graph semantics or bundling source.
2. **Phase 1 and Phase 1F may proceed in parallel only after Phase 0 schemas freeze.** The runtime kernel owns canonical state; file-base owns bounded, root-confined read/query projection.
3. **Phase 2 depends on Phase 1 acceptance transactions.** Spawning workers before immutable assignments, result schemas, idempotency, and CAS exist creates races and fake evidence.
4. **Phase 3 follows stable canonical artifacts.** Build the graph last among core storage layers so it cannot become a competing source of truth.
5. **Phase 4 is not postponed quality work.** Its benchmark grows from Phase 0, but final scientific gates, source revalidation, red-team cases, and reproducibility evidence land after the execution paths exist.

## Open Decisions and Research Flags

- **Distribution intent (Phase 0, blocking):** Decide whether the plugin will remain private/noncommercial or may be distributed commercially. The latter requires ARS commercial permission/dual licensing or an independently authored replacement.
- **Durability mechanism (Phase 1, deeper design):** Choose and prove either a segmented append-only file protocol or a transactional SQLite-backed metadata ledger. Do not mix both without a single authority and replay model.
- **Supported operating systems (Phase 1F, deeper research):** Root confinement and safe-open behavior differ across Linux, macOS, and Windows. Declare the v1.0 support matrix before setting the filesystem exit gate.
- **Codex compatibility window (Phase 0, recurring):** Pin a minimum supported Codex version and test current release behavior. Hooks and plugin packaging are active contracts, not timeless metadata.
- **Scientific source retention (Phase 4, policy/legal):** Define when lawful evidence snapshots may be retained, when only hashes/metadata may persist, and how deletion requests interact with immutable audit records.
- **Threat model boundary (Phase 0, blocking):** State whether the workbench protects only against accidental corruption and malicious source content or also against a malicious local user with write access. Hash chains without an externally anchored/signature trust root do not defeat full local-history replacement.

## Sources

### Project and actual-file evidence

- HIGH — `/home/zhangyangrui/my_programes/academic-research-workbench/.planning/PROJECT.md`
- HIGH — `/home/zhangyangrui/orca/workspaces/Examination/审查/experiments/ARS_OPEN_SCIENCE_FILE_BASE_INTEGRATION_PLAN_20260711.md`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/SKILL.md`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/references/science_workbench_mvp.md`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/full-runtime-manifest.json`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/scripts/ars_codex_full_runtime.py`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/codex/hooks/hooks.json`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/LICENSE`
- HIGH — `/home/zhangyangrui/.codex/skills/academic-research-suite/ars/experiment-agent/LICENSE`
- HIGH — `/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/LICENSE`
- HIGH — `/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/THIRD_PARTY.md`
- HIGH — `/home/zhangyangrui/orca/projects/Paper4Master/.external/codebase-memory-mcp/scripts/license-policy.json`
- HIGH — `/home/zhangyangrui/orca/projects/Paper4Master/patches/file-base-server-name.patch`

### Authoritative external references

- HIGH — [OpenAI: Build plugins](https://developers.openai.com/codex/plugins/build)
- HIGH — [OpenAI: Codex hooks](https://learn.chatgpt.com/codex/hooks)
- HIGH — [OpenAI: Codex configuration reference](https://developers.openai.com/codex/config-reference)
- HIGH — [OpenAI: Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- HIGH — [MCP specification: Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)
- HIGH — [MCP specification: Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- HIGH — [MCP specification: Roots](https://modelcontextprotocol.io/specification/2025-11-25/client/roots)
- HIGH — [MCP specification: Pagination](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination)
- HIGH — [MCP specification: Experimental tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- HIGH — [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- HIGH — [W3C PROV-AQ: changing resources and provenance trust](https://www.w3.org/TR/prov-aq/)
- HIGH — [SQLite: How SQLite Is Tested](https://www.sqlite.org/testing.html)
- HIGH — [SQLite: Atomic Commit](https://www.sqlite.org/atomiccommit.html)
- HIGH — [SLSA Provenance v1.1](https://slsa.dev/spec/v1.1/provenance)
- HIGH — [OSI: MIT License](https://opensource.org/license/mit)
- HIGH for license text, MEDIUM for project-specific legal conclusion — [Creative Commons BY-NC 4.0 legal code](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en)
- HIGH — [Creative Commons FAQ, including software-license guidance](https://creativecommons.org/faq/)

---
*Pitfalls research for: Academic Research Workbench v1.0 headless core*
*Researched: 2026-07-12*
