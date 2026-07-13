# Roadmap: Academic Research Workbench

## Overview

Academic Research Workbench v1.0 progresses from a legally classified, reproducible, executable Codex-plugin baseline to a durable sole-writer runtime, secure files-first retrieval, independent subagent execution, rebuildable research projections, scientific evidence gates, and final qualification of an installed staged package. Verification begins with schema, launcher, confinement, and recovery probes in Phase 1, grows with each capability, and culminates in a representative crash/resume research audit fixture. The milestone remains headless and domain-general; desktop UI, Chinese-military-specific assumptions, canonical graph writes, worker or hook canonical writes, and hook-only enforcement are excluded.

## Phases

- [x] **Phase 1: Contract, License, and Executable Baseline** - Prove the staged plugin, source and license chain, authority schemas, filesystem boundary, and seed verification fixture before deeper implementation. (completed 2026-07-13)
- [x] **Phase 2: Durable Provenance Runtime** - Make canonical research runs deterministic, immutable, replayable, and recoverable through the sole writer. (completed 2026-07-13)
- [ ] **Phase 3: Secure Files-First Data Plane** - Give authorized agents bounded multilingual research retrieval without exposing an unrestricted filesystem bridge.
- [ ] **Phase 4: Subagent Orchestration, Hooks, and Human Gates** - Execute scoped workers with deterministic handoffs, genuine review independence, defense-in-depth hooks, and explicit human decisions.
- [ ] **Phase 5: Rebuildable Research Graph and Evidence Queries** - Project canonical artifacts into disposable, equivalent graph generations and bounded evidence-chain queries.
- [ ] **Phase 6: Scientific Integrity and Audit Dossier** - Turn scientific checks, experiment provenance, evidence access, and unresolved claims into immutable receipts and an inspectable dossier.
- [ ] **Phase 7: Installed E2E Recovery and Release Qualification** - Qualify the staged package through compatibility, adversarial recovery, representative research, and release-blocking evidence gates.

## Phase Details

### Phase 1: Contract, License, and Executable Baseline

**Goal**: An operator can install and exercise a legally classified, reproducibly sourced plugin baseline whose authority and filesystem boundaries are proven before feature expansion.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: PKG-01, PKG-02, PKG-03, PKG-04, SUP-01, SUP-02, SUP-03, SUP-04, SUP-05, RUN-01, RUN-02, FILE-05, VER-01
**Success Criteria** (what must be TRUE):

  1. From a clean checkout, an operator can stage and install the plugin, pass manifest validation, route a request to a declared ARS workflow and mode, launch the bundled MCP without a source-checkout absolute path, and print all plugin/runtime/source/schema/patch versions.
  2. A maintainer can reproduce the pinned ARS and file-base trees from revisions and ordered patches; digest drift fails the build, while the staged package contains the source manifest, licenses, modification and third-party notices, and SBOM but no papers, extracted text, credentials, run data, or indexes.
  3. Release readiness records the intended use and distribution classification for every bundled source, with license texts and permission evidence; an incompatible or unresolved classification visibly blocks qualification.
  4. A cross-language schema gate and executable seed fixture initialize a declared-capability run, admit events only through one writer in deterministic sequence and hash-chain order, and preserve raw init/append/forced-stop/replay evidence for the growing recovery suite.
  5. Before any content is returned, launcher-level confinement probes show the MCP rejecting traversal, symlink or junction escape, disallowed roots, sensitive paths, and over-budget requests, with inspectable security evidence for each case.

**Plans**: 7 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Python/package/test bootstrap and clean installed-plugin contract

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Installed skill route and fresh-host compatibility convergence
- [x] 01-03-PLAN.md — Pre-vendoring license gate, offline source materialization, and digest closure

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-04-PLAN.md — Extended legal inventory, release BLOCKED classifier, and private-safe stage
- [x] 01-05-PLAN.md — Sole-writer canonical run and forced-stop replay

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-06-PLAN.md — Red-first confined native MCP, upstream/sanitizer suites, and installed launcher

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 01-07-PLAN.md — Final build identity, independent schemas, and clean integrated evidence

### Phase 2: Durable Provenance Runtime

**Goal**: Operators can trust canonical run state to survive invalid input and process failure without losing, duplicating, or silently rewriting accepted research work.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: RUN-03, RUN-04, RUN-05, RUN-06, RUN-07, RUN-08
**Success Criteria** (what must be TRUE):

  1. Invalid, duplicate, stale-revision, out-of-order, and unauthorized transitions are rejected without a partial canonical change, and the rejection identifies the accepted revision that remains in force.
  2. Given only canonical events and immutable manifests, an operator can replay the same validated state without chat history or projection databases; accepted artifacts and Material Passport revisions remain content-addressed and linked to their accepting or superseding transition.
  3. After injected process termination, an operator can checkpoint and resume without repeating accepted work or accepting stale results; the recovery fixture preserves the fault point, raw tail bytes, quarantine output, and last fully committed revision as evidence.
  4. Status output reports the current stage, accepted revision, blockers, pending human decisions, active attempts, and next legal transition after both normal replay and recovery.

**Plans**: 5 plans

Plans:
**Wave 1**

- [x] 02-01-PLAN.md - Registered workflow, authority, pure reducer, rejection, and shared status contracts

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md - Segmented journal, sole-writer transitions, decisions, and attempts

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md - Content-addressed artifacts, Material Passports, freshness, and exact resume

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md - Explicit quarantine recovery, corruption blocking, and crash evidence

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 02-05-PLAN.md - Staged end-to-end qualification, schema identity, and full regression

### Phase 3: Secure Files-First Data Plane

**Goal**: Authorized agents can inspect and search declared research roots through useful, bounded, provenance-aware tools while administrative mutation remains parent-controlled.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: FILE-01, FILE-02, FILE-03, FILE-04, FILE-06, FILE-07, FILE-08, VER-03
**Success Criteria** (what must be TRUE):

  1. An authorized client can list stable file identities and request bounded byte or line ranges, receiving type, size, digest, extraction state, freshness, encoding, truncation, and continuation metadata.
  2. An authorized client can perform paginated exact and full-text search and request bounded outlines or context windows with source locations, snippets, extraction provenance, and explicit staleness.
  3. Create, modify, rename, delete, ignore-rule, and extractor-version changes update searchable results without stale content across CJK, Markdown, LaTeX, BibTeX, source-code, direct-text, and declared extracted-PDF fixtures.
  4. Agent-facing tools remain read-only and bounded while crawl, extraction, rebuild, and repair require parent-controlled administrative commands; the security evidence suite covers replacement races, malformed input, sensitive files, and output-budget exhaustion in addition to the Phase 1 confinement cases.

**Plans**: TBD

### Phase 4: Subagent Orchestration, Hooks, and Human Gates

**Goal**: The parent can execute specialized and independent research work through immutable proposals while retaining deterministic canonical control and accountable human gate decisions.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: PKG-05, AGT-01, AGT-02, AGT-03, AGT-04, AGT-05, AGT-06, AGT-07, SCI-02, SCI-03
**Success Criteria** (what must be TRUE):

  1. The parent can dispatch a worker from an immutable assignment containing scoped inputs, capabilities, attempt identity, and output schema, and the worker can return only a schema-valid immutable proposal rather than mutate canonical state.
  2. The parent deterministically accepts, rejects, retries, cancels, or supersedes proposals and records every lifecycle event; bounded concurrency, timeout, cancellation, and retry evidence shows that orphaned attempts cannot block recovery.
  3. An independent-review run preserves distinct worker identities, isolated assignments, individual reports, dissent, and separate synthesis evidence; each role is honestly recorded as native, assignment-injected, or degraded inline, and degraded inline work cannot claim independence.
  4. Hooks can hydrate context, validate envelopes, warn on policy, and request continuation, while paired hook-enabled and hook-disabled evidence shows that runtime rules, filesystem confinement, integrity gates, and provenance cannot be bypassed.
  5. Gate records distinguish PASS, FAIL, and BLOCKED, prevent finalization without required fresh evidence, and let a human append a scoped waiver, correction, access decision, or approval with rationale without rewriting prior evidence.

**Plans**: TBD

### Phase 5: Rebuildable Research Graph and Evidence Queries

**Goal**: Operators can trace research evidence through a disposable graph whose full, incremental, and rebuilt forms are demonstrably equivalent and never authoritative.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04, GRAPH-05, GRAPH-06, VER-05
**Success Criteria** (what must be TRUE):

  1. An operator can project validated manifests into Run, Stage, Artifact, Claim, Source, Dataset, Experiment, Figure, Review, and Gate nodes and edges, each carrying stable identity, source digest, schema version, supersession state, and canonical ledger watermark.
  2. After deleting graph and file indexes, an operator can rebuild them from unchanged canonical inputs and obtain equivalent normalized query results, with the normalization oracle, compared outputs, watermarks, and projection receipts retained as evidence.
  3. Incremental projection matches a clean full rebuild after modify, rename, delete, correction, migration, and supersession fixtures under the same declared equivalence oracle.
  4. An authorized client can issue bounded allowlisted queries tracing claims to sources, datasets, experiments, figures, reviews, and gate evidence without unbounded traversal.
  5. Corrupt, stale, deleted, or unavailable graph and file indexes cannot change accepted provenance, gate verdicts, canonical state, or the next legal transition, as shown by before/after canonical-state evidence.

**Plans**: TBD

### Phase 6: Scientific Integrity and Audit Dossier

**Goal**: Operators and reviewers can inspect fresh scientific evidence, experiment provenance, access limitations, and unresolved claims through immutable receipts and one coherent audit dossier.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: SCI-01, SCI-04, SCI-05, SCI-06, SCI-07, VER-07
**Success Criteria** (what must be TRUE):

  1. Every integrity check emits a versioned immutable evidence receipt naming inputs, method, tool version, verdict, reasons, and freshness, and changed subject inputs visibly invalidate stale evidence.
  2. An operator can ingest externally executed datasets, model or configuration identity, metrics, and artifacts through one strict experiment-provenance schema; controlled execution remains disabled unless sandbox, approval, environment-capture, and provenance-equivalence probe evidence passes.
  3. Evidence is classified as publicly verified, locally supplied, restricted, unavailable, or human-review-required, and a run cannot claim citation verification, experiment reproduction, independent review, or audit completion when the required lifecycle evidence is absent.
  4. A release candidate produces an inspectable machine-readable and Markdown audit dossier containing run history, immutable manifests and Passports, evidence receipts, review matrix and dissent, waivers, projection receipts, test logs, benchmark versions, build provenance, and actionable blockers.

**Plans**: TBD

### Phase 7: Installed E2E Recovery and Release Qualification

**Goal**: An installed staged package earns v1.0 qualification only by completing the representative research audit through crash/resume and satisfying every release evidence gate.
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: VER-02, VER-04, VER-06, VER-08
**Success Criteria** (what must be TRUE):

  1. Tests run against an installed staged package, not the source layout, and preserve logs proving manifest discovery, skill routing, launcher resolution, MCP negotiation, hook behavior, and version reporting across the declared Codex compatibility matrix.
  2. The recovery suite injects hard termination, torn writes, I/O failure, disk exhaustion, lock death, duplicate delivery, stale worker completion, and recovery-time faults while preserving raw evidence and proving that no partial state or stale proposal becomes canonical.
  3. From the installed staged package, the representative E2E fixture processes sources and claims, ingests an experiment and figure or result, records genuinely independent review evidence, encounters a failed gate, captures human resolution, crashes and resumes, and emits the final audit dossier without repeating accepted work.
  4. Release qualification fails whenever licensing, integrity, recovery, security, graph-equivalence, subagent-independence, compatibility, or staged-package evidence is missing, stale, unresolved, or unverifiable, and names the exact blocking receipt or test artifact.

**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Contract, License, and Executable Baseline | 7/7 | Complete   | 2026-07-13 |
| 2. Durable Provenance Runtime | 5/5 | Complete    | 2026-07-13 |
| 3. Secure Files-First Data Plane | 0/TBD | Not started | - |
| 4. Subagent Orchestration, Hooks, and Human Gates | 0/TBD | Not started | - |
| 5. Rebuildable Research Graph and Evidence Queries | 0/TBD | Not started | - |
| 6. Scientific Integrity and Audit Dossier | 0/TBD | Not started | - |
| 7. Installed E2E Recovery and Release Qualification | 0/TBD | Not started | - |

---
*Roadmap created: 2026-07-12 for v1.0 MVP*
