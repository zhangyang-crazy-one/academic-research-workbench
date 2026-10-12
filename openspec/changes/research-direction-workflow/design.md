## Context

The owner includes #115/#116 in v0.2.0. A real earlier editable snapshot demonstrated successful manual identity/init/handoff and ordinary material acceptance, but not latest-main E2E or scientific validation. Startup, readiness, versioned reading and domain-pack adaptation require distinct proof scopes.

## Goals / Non-Goals

Goals: one core identity, deterministic retained startup requests, ordinary canonical runs, explicit layered readiness, external replaceable content, original-validator delegation and offline examples. No model execution, automatic paper selection, duplicated ledger, automatic scientific verdict or domain ontology in core.

## Decisions

Move existing project identity operations into core and keep the old memory aliases. Research startup retains an immutable plan and input carrying project identity, direction and initial phase; the existing run manifest binds that input. It uses existing journal initialization/replay and narrative guards for paper runs. Exact incomplete initialization may resume only under the writer lock with identical manifest bytes and absent journal; complete or conflicting histories never get overwritten. Retained plan/init IDs make retries idempotent, and explicit project/run pins reject conflicts after directory moves. Status reports lifecycle and workflow stage separately, and exposes unassessed executor, retrieval and scientific conditions.

Direction packages are bounded strict data with independent digest/version/license and unresolved scope declarations. A fixed bundled ARS validator validates profiles and replays branches; package files never supply executable code. Explicit binding snapshots join ARS project_ref to the stable ARW project/run and exact input digests. Checks delegate accepted references, citation receipts and experiment receipts to their original readers. Definition/source/branch changes yield stale downstream rows; old snapshots remain inspectable. Preparation creates ordinary candidate artifacts and existing acceptance requests, never upgrades a URL or unaccepted file to AcceptedRef.

Versioned literature intake keeps webpage/PDF/version identities distinct and separates bibliographic status, actual byte availability, declared reading range, artifact acceptance, human support and experiment replay. Operationalization records map existing assumptions/evidence/overlays plus narrowly bounded explanatory fields. Mechanical reports retain denominators, missing controls/costs, negative and unsupported cases, and human-review requirements. Synthetic walkthroughs explicitly preserve replayed/synthetic status; paid pilot work remains separately authorized.

## Risks / Trade-offs

Partial writes -> report committed steps and resume exact requests; conflicting history -> fail closed. Mutable content -> hash-bound snapshots and downstream stale reports. Package instructions -> data-only loading, canonical path bounds, original validators. Overstated readiness -> per-operation not_evaluated rather than a single success verdict. Construct validity and philosophical interpretation remain author/reviewer decisions.
