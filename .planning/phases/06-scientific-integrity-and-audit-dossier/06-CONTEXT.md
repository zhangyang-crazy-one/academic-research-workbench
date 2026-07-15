# Phase 6: Scientific Integrity and Audit Dossier - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 closes the scientific-integrity and auditability layer on top of the
append-only runtime and the Phase 5 rebuildable research graph. It must make
freshness, external experiment provenance, evidence access limitations, and
release-candidate audit evidence inspectable from canonical artifacts. The
graph remains a disposable projection and never becomes scientific authority.

The phase is not a general-purpose experiment runner, a paper authoring
system, or a license waiver. Controlled execution, desktop UX, OCR/office
format expansion, cloud synchronization, and the Science Workbench v2 paper
AST/export workflow remain outside this boundary.
</domain>

<decisions>
## Implementation Decisions

### Integrity receipts and freshness

- **D-01:** An integrity receipt is immutable, content-addressed, and records
  its subject/input digests, method, tool/version identity, verdict, reasons,
  and observed time/freshness metadata.
- **D-02:** A changed subject or input digest always invalidates a prior
  receipt. A receipt also declares a freshness window/`valid_until` so an
  otherwise unchanged result can become stale deterministically.
- **D-03:** Stale or mismatched receipts fail closed and point to the exact
  replacement evidence required; no mutable projection or caller-supplied
  freshness flag can revive them.

### External experiment provenance

- **D-04:** Phase 6 qualifies externally executed experiment evidence through a
  strict common schema rather than silently executing work. The schema covers
  dataset/source digests, model and configuration identity, metrics and
  artifacts, environment/toolchain, runner identity, timestamps, and links to
  immutable manifests.
- **D-05:** Controlled execution is disabled unless all four gates are present:
  an approved sandbox, explicit approval, environment capture, and a
  provenance-equivalence probe. Missing or failed gates produce a blocked
  decision and must never be represented as a completed reproduction.
- **D-06:** Imported provenance is independently validated against canonical
  bytes and source digests. A producer cannot self-attest a passing verdict by
  supplying a boolean or an unchecked hash.

### Evidence access and claim boundaries

- **D-07:** Evidence uses exactly these access states:
  `publicly_verified`, `locally_supplied`, `restricted`, `unavailable`, and
  `human_review_required`.
- **D-08:** Claim-level gates may consume an access state but may not silently
  upgrade it. Restricted, unavailable, ambiguous-license, or otherwise
  inaccessible evidence routes to human review or a blocker with an explicit
  reason.
- **D-09:** The workbench must not claim citation verification, reproduction,
  independent review, or audit completion unless the corresponding lifecycle
  evidence exists and is fresh. Local possession is not equivalent to public
  verification.

### Canonical audit dossier

- **D-10:** One canonical machine-readable dossier manifest/JSON document is
  the source for deterministic JSON and Markdown renderings. Rendered output
  is non-authoritative and references canonical artifact/event hashes.
- **D-11:** The dossier includes run history; run/assignment/result/artifact
  manifests and Material Passports; integrity receipts; external experiment
  provenance; evidence access-state decisions; review matrix, minority and
  dissent records; waivers/corrections; graph projection receipts and
  watermarks; test/benchmark logs and versions; build/source provenance; and
  blockers plus the technical/release verdict.
- **D-12:** Dossier generation is deterministic, cold-replayable, and bounded.
  It must not export secrets, private full text, uncontrolled paths, or
  material whose license/permission gate is unresolved. The dossier records
  such blockers instead of implying a release authorization.

### Compatibility and composition

- **D-13:** Phase 6 composes the Phase 4 canonical lifecycle, human-gate, and
  review evidence and the Phase 5 graph projection contracts. It does not
  replace their sole-writer or non-authority boundaries with a second state
  store.
- **D-14:** Schema and registry changes are derived from the checked-in
  contract source where practical, with independent validation and drift
  checks. Existing evidence remains readable through explicit schema/version
  adapters rather than ad-hoc coercion.

### The agent's discretion

- Exact Python model names, schema decomposition, event discriminators, and
  directory layout for receipts/provenance/dossiers.
- Default freshness intervals and clock-skew tolerances, provided they are
  explicit, tested, and represented in the receipt.
- The deterministic renderer implementation and the minimal report templates,
  provided canonical hashes and source references remain visible.
- Whether a validation is implemented as a pure function, runtime command, or
  verifier script, provided it is exercised by unit, integration, cold-replay,
  and staged verification tests.
- The precise mapping from existing Phase 4/5 evidence records into dossier
  sections, provided no evidence is upgraded or dropped silently.
</decisions>

<canonical_refs>
## Canonical References

- `.planning/PROJECT.md` — product boundary, append-only authority, security,
  and delivery constraints.
- `.planning/REQUIREMENTS.md` — SCI-01/04/05/06/07 and VER-07 acceptance
  obligations plus traceability rules.
- `.planning/ROADMAP.md` — Phase 6 goal, success criteria, and dependency on
  Phase 5.
- `.planning/STATE.md` — current milestone and prior phase execution state.
- `.planning/research/SUMMARY.md`, `ARCHITECTURE.md`, `FEATURES.md`,
  `PITFALLS.md`, `STACK.md` — researched contracts, threat boundaries, and
  verification expectations.
- `.planning/phases/04-subagent-orchestration-hooks-and-human-gates/04-CONTEXT.md`
  and `04-VALIDATION.md` — canonical lifecycle, review, hook, and human-gate
  decisions that Phase 6 must consume.
- `.planning/phases/04.1-phase-4-qualification-closure-ars-integration-lock-and-insta/04.1-CONTEXT.md`
  and retained summaries/verification — host, package, integration-lock, and
  release-boundary evidence.
- `.planning/phases/05-rebuildable-research-graph-and-evidence-queries/05-04-SUMMARY.md`
  — graph qualification and its non-authoritative projection boundary.
- `src/arw/evidence.py`, `manifests.py`, `models.py`, `runtime.py`, and
  `schema_registry.py` — current evidence, immutable manifest, ledger, and
  schema primitives.
- `src/arw/review.py` — blind review, synthesis, minority/dissent, and report
  hash contracts to be represented without weakening isolation.
- `src/arw/graph_models.py`, `graph_projection.py`, `graph_store.py`, and
  `graph_mcp.py` — rebuildable graph projection, receipts, bounds, and MCP
  query semantics.
- `docs/runtime/durable-provenance.md` and `docs/runtime/research-graph.md` —
  operator-facing provenance and projection expectations.
- `scripts/stage-plugin`, `scripts/verify-phase-5`, and
  `tests/staged/test_supply_chain_inventory.py` — package allowlist, inventory,
  and evidence-bound verification conventions.
- `tests/integration/test_human_gates.py`,
  `test_graph_rebuild.py`, and `test_graph_authority.py` — existing replay and
  authority tests that Phase 6 extends.
</canonical_refs>

<code_context>
## Existing Code Context

- `src/arw/evidence.py` currently writes allowlisted command/recovery evidence;
  Phase 6 should extend this with strict integrity/provenance records without
  allowing arbitrary environment or secret capture.
- `src/arw/manifests.py` already provides immutable, content-addressed
  assignment/artifact/Passport storage and safe-root checks. New receipts and
  dossier inputs should use the same write-once and canonical-byte semantics.
- `src/arw/runtime.py` and `src/arw/models.py` own canonical ledger acceptance,
  artifact freshness, and strict envelopes. Dossier generation must replay
  these records rather than infer authority from SQLite or Markdown.
- `src/arw/review.py` contains blind reviewer/synthesizer identity and dissent
  policy. Phase 6 should aggregate exact report hashes and preserve minority
  findings, not re-run or collapse review isolation.
- Phase 5 graph modules expose bounded, rebuildable projections with receipts
  and watermarks. Their output is useful dossier evidence but remains
  non-authoritative and disposable.
- `scripts/stage-plugin` is the release boundary: its positive allowlist and
  inventory/SBOM checks matter more than `.gitignore`. Private evidence and
  scratch outputs must remain excluded while the dossier records bounded
  references and blockers.
</code_context>

<specifics>
## Concrete Acceptance Shape

- A changed input digest and an expired freshness window produce a visibly
  invalid receipt with deterministic reason codes.
- A valid external experiment envelope can be cold-replayed from its source
  digests, environment capture, and artifact hashes; a missing qualification
  gate is blocked rather than treated as execution.
- Every claim can be traced to one of the five access states, and inaccessible
  or unclear material reaches a human-review/blocker path.
- A fresh dossier can be rendered twice with byte-identical JSON/Markdown and
  can be reconstructed after projection/cache loss from canonical records.
- The dossier exposes technical qualification separately from the still
  blocked legal/intended-use release verdict (including SUP-04/P04-09 where
  applicable); it cannot turn a technical pass into publication permission.
</specifics>

<deferred>
## Deferred Ideas

- Controlled experiment execution or a native scheduler-backed runner after a
  separately qualified sandbox, approval, and provenance-equivalence design.
- Full Science Workbench v2 paper AST/export and end-to-end research-to-paper
  replacement claims.
- Desktop UX, OCR/image-only PDF recovery, office-format expansion, cloud sync,
  telemetry, and multi-user remote coordination.
- Broad license remediation or commercial permission acquisition; Phase 6 only
  records the blocker and preserves accurate attribution/notice evidence.
</deferred>

---

*Phase: 06-scientific-integrity-and-audit-dossier*
*Context gathered: 2026-07-15*
