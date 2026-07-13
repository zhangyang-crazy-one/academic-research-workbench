# Phase 2: Durable Provenance Runtime - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves alternatives considered.

**Date:** 2026-07-13
**Phase:** 02-durable-provenance-runtime
**Areas discussed:** Runtime lifecycle, recovery and quarantine, Material Passport evolution, status and human blockers

---

## Runtime Lifecycle

| Decision | Alternatives considered | Selected |
|----------|-------------------------|----------|
| Stage model | Fixed core plus controlled extensions; manifest-declared arbitrary state machine; event-only implicit stage | Fixed core plus controlled extensions |
| Transition authority | Parent-only committer with actor-role policy; per-manifest actor matrix; actor-format/signature only | Parent-only committer with actor-role policy |
| Definition version | Fixed for full run; explicit migration event; always latest | Left to planner under immutable replay constraints |

**User's choice:** Selected the fixed core lifecycle and parent-only canonical committer, then moved to the next area before locking the definition-upgrade mechanism.
**Notes:** Workers and hooks return proposals only. The runtime must remain domain neutral.

---

## Recovery and Quarantine

| Decision | Alternatives considered | Selected |
|----------|-------------------------|----------|
| Repair authority | Explicit locked recovery; automatic repair on open; manual file editing | Explicit locked recovery |
| Damaged storage | Seal damaged segment and continue in a new segment; truncate in place; fork a new run | Seal and continue in a new segment |
| Recovery provenance | Canonical `recovery.completed` event; external evidence only | Canonical recovery event |
| Recoverable boundary | Uncommitted tail only; attempt repair of any parseable damage | Uncommitted tail only |

**User's choice:** Accepted all recommended recovery boundaries.
**Notes:** Damage within accepted history is a hard forensic block, not an automatic salvage case.

---

## Material Passport Evolution

| Decision | Alternatives considered | Selected |
|----------|-------------------------|----------|
| Revision frequency | Coherent checkpoint boundaries; every event; final delivery only | Coherent checkpoint boundaries |
| Authority | Immutable accepted revisions plus derived latest pointer; mutable latest file as authority | Immutable accepted revisions |
| Supersession | Old revision is audit-only; allow stale resume and implicit branch | Audit-only after supersession |
| Freshness | Compute dynamically without mutation; rewrite old Passport to STALE | Dynamic computation |

**User's choice:** Accepted all recommended Passport rules.
**Notes:** Ordinary artifact acceptance remains fully traceable through events and immutable manifests even when it does not create a Passport.

---

## Status and Human Blockers

| Decision | Alternatives considered | Selected |
|----------|-------------------------|----------|
| Output surfaces | Shared-reducer JSON and text; JSON only; separate state logic | Shared-reducer JSON and text |
| Stable fields | Full Phase 2 status contract; only stage and revision | Full status contract |
| Human action | Read-only status plus separate decision command; decide inside status | Separate decision command |
| Exit status | Exit code means query success; nonzero for blocked/recovery states | Query-success semantics |

**User's choice:** Accepted all recommended status and human-decision rules.
**Notes:** Automation must inspect typed status fields rather than infer scientific readiness from the CLI exit code.

---

## the agent's Discretion

- Exact workflow-definition version/migration mechanism, while preserving immutable identity and historical replay.
- Domain-neutral core stage/event vocabulary, segment paths, checkpoint projection shape, reason taxonomy, and numeric error codes.

## Deferred Ideas

- Add an independent `experiment_designer` role in Phase 4, separate from execution, statistical validation, and methodology review.
