# Requirements: Academic Research Workbench

**Defined:** 2026-07-12
**Core Value:** Every research run must be reproducible, resumable, and auditable from source files through claims, experiments, review gates, and final artifacts.

## v1 Requirements

### Plugin And Workflow Integration

- [x] **PKG-01**: An operator can install the repository as a Codex plugin from a clean checkout and pass manifest validation.
- [x] **PKG-02**: An operator can invoke the workbench skill and route a request to a declared ARS workflow family and execution mode.
- [x] **PKG-03**: An installed plugin can start its bundled files-first MCP without relying on the source checkout's absolute path.
- [x] **PKG-04**: An operator can inspect plugin, runtime, ARS snapshot, file-base snapshot, schema, and patch-set versions from one command.
- [x] **PKG-05**: A run records whether each requested role used a native subagent, an assignment-injected role, or an explicitly degraded inline mode.

### Supply Chain And Licensing

- [x] **SUP-01**: A maintainer can reproduce the selected ARS and file-base source trees from recorded upstream revisions and ordered local patches.
- [x] **SUP-02**: A build fails when a source tree, patch, dependency lock, or expected artifact differs from its recorded digest.
- [x] **SUP-03**: A staged plugin contains license texts, modification notices, third-party notices, an SBOM, and a machine-readable source manifest for every bundled component.
- [x] **SUP-04**: A release cannot be qualified until the intended use and distribution class satisfies every bundled component's license or records separate permission.
- [x] **SUP-05**: Default packaging excludes papers, extracted full text, run data, credentials, indexes, and other workspace-private material.

### Runtime And Provenance

- [x] **RUN-01**: An operator can initialize a run with a stable identifier, immutable input snapshot, schema version, workflow mode, and declared capability set.
- [x] **RUN-02**: Every accepted canonical transition is appended as a deterministic, sequence-ordered, hash-chained event by one runtime writer.
- [x] **RUN-03**: The runtime rejects invalid, duplicate, stale-revision, out-of-order, or unauthorized canonical transitions without partially changing accepted state.
- [x] **RUN-04**: An operator can reconstruct the same validated run state from canonical events and immutable manifests without chat history or projection databases.
- [x] **RUN-05**: Accepted artifacts and Material Passport revisions are immutable, content-addressed, and linked to the transition that accepted or superseded them.
- [x] **RUN-06**: An operator can checkpoint and resume a run after process termination without repeating accepted work or accepting stale worker results.
- [x] **RUN-07**: Status output identifies the current stage, accepted revision, blockers, pending human decisions, active attempts, and next legal transition.
- [x] **RUN-08**: Recovery quarantines torn, corrupt, or unverifiable tail data and reports the last fully committed canonical revision.

### Files-First MCP

- [x] **FILE-01**: An authorized client can list files under configured roots with stable file identity, type, size, digest, extraction state, and index freshness.
- [x] **FILE-02**: An authorized client can read bounded byte or line ranges and receives explicit truncation, encoding, and continuation metadata.
- [x] **FILE-03**: An authorized client can run bounded exact and full-text searches with pagination, source locations, snippets, and freshness metadata.
- [x] **FILE-04**: An authorized client can request bounded document outlines and context windows for supported research formats.
- [x] **FILE-05**: The MCP rejects path traversal, symlink or junction escape, disallowed roots, sensitive-path access, and over-budget requests before returning content.
- [x] **FILE-06**: Index updates correctly represent create, modify, rename, delete, ignore-rule, and extraction-version changes without retaining stale searchable content.
- [x] **FILE-07**: CJK text, Markdown, LaTeX, BibTeX, source code, and declared direct-text or extracted-PDF cases have explicit coverage and extraction provenance.
- [x] **FILE-08**: Agent-facing MCP tools are read-only and bounded, while crawl, extraction, rebuild, and repair operations require parent-controlled administrative commands.

### Subagents, Hooks, And Handoffs

- [x] **AGT-01**: The parent orchestrator can dispatch a specialized worker from an immutable assignment containing scoped inputs, capabilities, attempt identity, and output schema.
- [x] **AGT-02**: A worker can only return a schema-valid immutable proposal and cannot directly mutate canonical run state.
- [x] **AGT-03**: The parent accepts, rejects, retries, cancels, or supersedes worker proposals in deterministic order and records each lifecycle event.
- [x] **AGT-04**: Independent-review workflows use distinct worker identities and isolated assignments, preserve individual reports and dissent, and record synthesis separately.
- [x] **AGT-05**: Bounded concurrency, timeout, cancellation, and retry policies prevent orphaned attempts from blocking run recovery.
- [x] **AGT-06**: Hooks can hydrate context, validate envelopes, surface policy warnings, and request continuation without becoming canonical writers or the sole security boundary.
- [x] **AGT-07**: Disabling or bypassing hooks cannot bypass runtime state rules, MCP filesystem confinement, integrity gates, or provenance recording.

### Rebuildable Research Graph

- [x] **GRAPH-01**: An operator can project validated manifests into stable nodes and edges for Run, Stage, Artifact, Claim, Source, Dataset, Experiment, Figure, Review, and Gate.
- [x] **GRAPH-02**: Every projected entity records stable identity, source digest, schema version, supersession state, and canonical ledger watermark.
- [x] **GRAPH-03**: An operator can delete and rebuild graph and file indexes and obtain equivalent normalized query results from unchanged canonical inputs.
- [x] **GRAPH-04**: Incremental projection produces results equivalent to a full rebuild after modifications, renames, deletes, corrections, and supersessions.
- [x] **GRAPH-05**: An authorized client can issue bounded allowlisted queries that trace claims to sources, datasets, experiments, figures, reviews, and gate evidence.
- [x] **GRAPH-06**: Graph or index corruption, staleness, or unavailability cannot alter provenance, gate verdicts, accepted state, or the next legal transition.

### Scientific Integrity And Human Gates

- [x] **SCI-01**: Each integrity check emits a versioned immutable evidence receipt with inputs, method, tool version, verdict, reasons, and freshness metadata.
- [x] **SCI-02**: Gate outcomes distinguish PASS, FAIL, and BLOCKED and prevent finalization when required fresh evidence is absent or unresolved.
- [x] **SCI-03**: A human can record an explicit waiver, correction, access decision, or approval with rationale and scope without rewriting prior evidence.
- [x] **SCI-04**: An operator can ingest externally executed experiment provenance, datasets, model/configuration identity, metrics, and artifacts through a strict common schema.
- [x] **SCI-05**: Controlled experiment execution remains disabled unless its sandbox, approval, environment-capture, and provenance-equivalence probe passes.
- [x] **SCI-06**: Evidence access states distinguish publicly verified, locally supplied, restricted, unavailable, and human-review-required material.
- [x] **SCI-07**: A run cannot claim independent review, citation verification, experiment reproduction, or audit completion when required lifecycle evidence is missing.

### Verification And Release Evidence

- [x] **VER-01**: Continuous integration validates schemas independently across Python and MCP boundaries and blocks incompatible schema drift.
- [ ] **VER-02**: Installed-plugin tests exercise manifest discovery, skill routing, launcher resolution, MCP negotiation, hooks, and version reporting from a staged package.
- [x] **VER-03**: Security tests cover traversal, symlink or junction escape, race-sensitive file replacement, sensitive files, malformed input, and output-budget exhaustion.
- [ ] **VER-04**: Recovery tests inject hard termination, torn writes, I/O failure, disk exhaustion, lock death, duplicate delivery, and stale worker completion while preserving raw evidence.
- [x] **VER-05**: Projection tests compare clean, full-rebuild, incremental, delete, rename, migration, and supersession query results under a declared normalization oracle.
- [ ] **VER-06**: One representative end-to-end fixture covers sources, claims, an experiment record, a figure or result, independent review, a failed gate, human resolution, crash/resume, and final audit output.
- [x] **VER-07**: A release candidate produces an inspectable audit dossier containing run history, manifests, Passports, evidence receipts, review matrix, waivers, projection receipts, test logs, benchmark versions, and build provenance.
- [ ] **VER-08**: Release qualification fails on unresolved licensing, integrity, recovery, security, compatibility, or staged-package evidence gates.

## User Stories

- As a researcher, I can resume a long academic workflow after interruption and know exactly which evidence and decisions remain valid.
- As a reviewer, I can trace a manuscript claim through sources, datasets, experiments, figures, reviews, and gate verdicts without trusting conversation memory.
- As an operator, I can install and upgrade the plugin from pinned inputs and prove which source, patch, schema, and binary produced a run.
- As a maintainer, I can delete every derived index and rebuild equivalent query results from canonical files.
- As a security-conscious user, I can restrict research tools to declared roots and verify that workers cannot mutate accepted provenance.

## Acceptance Criteria

- Every v1 requirement maps to exactly one roadmap phase and has executable verification evidence.
- The representative end-to-end fixture succeeds from a clean staged plugin installation and after injected crash recovery.
- Deleting all SQLite, FTS, and graph projections does not lose accepted provenance and rebuilds equivalent normalized queries.
- A worker, hook, or MCP client cannot bypass canonical state transitions or allowed-root and output-budget enforcement.
- The staged package passes source-digest, license, notices, SBOM, compatibility, security, recovery, and audit gates.

## v2 Requirements

### Publication Pipeline

- **PUB-01**: An operator can normalize a manuscript into a versioned paper AST and validate citation, structure, and venue-specific output contracts.
- **PUB-02**: An operator can produce strict publication exports with artifact and layout evidence linked to the run.

### Additional Ingestion

- **ING-01**: An operator can enable OCR, DOCX, spreadsheet, and slide adapters that report extraction provenance and quality.
- **ING-02**: An operator can configure additional scholarly source connectors with explicit credentials, licensing, access state, and rate limits.

### Extended Surfaces

- **UI-01**: A user can inspect canonical runs and read-only graph queries through an Open Science Desktop adapter.
- **DOM-01**: A maintainer can install separately versioned domain packs without changing core research schemas.
- **TEAM-01**: Multiple identified users can coordinate remote runs under explicit consent, transport, and conflict-resolution policies.
- **TEL-01**: An operator can opt into documented, redacted, auditable telemetry while local-first operation remains the default.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Desktop or browser UI in v1.0 | Runtime contracts, provenance, recovery, and security must stabilize before a presentation layer is added. |
| Chinese-military-specific ontology or defaults | The motivating dataset is domain-specific, but the core plugin must support general academic and ontology-abstraction workflows. |
| Semantic graph as canonical storage | Graph data is disposable and must never decide scientific provenance or workflow legality. |
| Canonical writes by subagents or hooks | Multiple writers would create races, ambiguous provenance, and non-deterministic acceptance. |
| Unrestricted filesystem access | It risks path escape, credential leakage, private-corpus ingestion, prompt injection, and unbounded outputs. |
| Silent credentials, paywall bypass, or hidden network calls | Evidence access must remain legal, consented, visible, and accurately classified. |
| Fully autonomous bypass of mandatory gates | Scientific waivers, restricted evidence, and final readiness require explicit accountable decisions. |
| Universal binary ingestion in v1 | OCR and office formats require separate quality, licensing, and resource-bound validation. |
| Hidden cloud sync, analytics, or telemetry | Private and unpublished research remains local by default. |
| Unpinned remote dependencies | Drifting source and patches make builds, licenses, and results non-reproducible. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PKG-01 | Phase 1 | Complete |
| PKG-02 | Phase 1 | Complete |
| PKG-03 | Phase 1 | Complete |
| PKG-04 | Phase 1 | Complete |
| PKG-05 | Phase 4 | Complete |
| SUP-01 | Phase 1 | Complete |
| SUP-02 | Phase 1 | Complete |
| SUP-03 | Phase 1 | Complete |
| SUP-04 | Phase 1 | Complete |
| SUP-05 | Phase 1 | Complete |
| RUN-01 | Phase 1 | Complete |
| RUN-02 | Phase 1 | Complete |
| RUN-03 | Phase 2 | Complete |
| RUN-04 | Phase 2 | Complete |
| RUN-05 | Phase 2 | Complete |
| RUN-06 | Phase 2 | Complete |
| RUN-07 | Phase 2 | Complete |
| RUN-08 | Phase 2 | Complete |
| FILE-01 | Phase 3 | Complete |
| FILE-02 | Phase 3 | Complete |
| FILE-03 | Phase 3 | Complete |
| FILE-04 | Phase 3 | Complete |
| FILE-05 | Phase 1 | Complete |
| FILE-06 | Phase 3 | Complete |
| FILE-07 | Phase 3 | Complete |
| FILE-08 | Phase 3 | Complete |
| AGT-01 | Phase 4 | Complete |
| AGT-02 | Phase 4 | Complete |
| AGT-03 | Phase 4 | Complete |
| AGT-04 | Phase 4 | Complete |
| AGT-05 | Phase 4 | Complete |
| AGT-06 | Phase 4 | Complete |
| AGT-07 | Phase 4 | Complete |
| GRAPH-01 | Phase 5 | Complete |
| GRAPH-02 | Phase 5 | Complete |
| GRAPH-03 | Phase 5 | Complete |
| GRAPH-04 | Phase 5 | Complete |
| GRAPH-05 | Phase 5 | Complete |
| GRAPH-06 | Phase 5 | Complete |
| SCI-01 | Phase 6 | Complete |
| SCI-02 | Phase 4 | Complete |
| SCI-03 | Phase 4 | Complete |
| SCI-04 | Phase 6 | Complete |
| SCI-05 | Phase 6 | Complete |
| SCI-06 | Phase 6 | Complete |
| SCI-07 | Phase 6 | Complete |
| VER-01 | Phase 1 | Complete |
| VER-02 | Phase 7 | Pending |
| VER-03 | Phase 3 | Complete |
| VER-04 | Phase 7 | Pending |
| VER-05 | Phase 5 | Complete |
| VER-06 | Phase 7 | Pending |
| VER-07 | Phase 6 | Complete |
| VER-08 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 54 total
- Mapped to phases: 54
- Unmapped: 0

---
*Requirements defined: 2026-07-12*
*Last updated: 2026-07-16 after Phase 6 technical qualification; release remains blocked*
