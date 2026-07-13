---
phase: 02-durable-provenance-runtime
audited: 2026-07-13
register_authored_at_plan_time: true
threats_total: 20
threats_open: 0
status: secured
---

# Phase 2 Security Verification

## Threat Register

| Threats | Status | Verified mitigation evidence |
|---|---|---|
| T-02-01 to T-02-04 | CLOSED | Bound workflow identity, explicit actor authority, pure reducer validation, shared strict status model, current-UTC/injected freshness, and read-only tree snapshots. |
| T-02-05 to T-02-08 | CLOSED | Strict segment discovery, per-event byte/hash/reducer validation, role-bearing sole writer, stale/duplicate rejection, bounded lock, and lock-symlink denial. |
| T-02-09 to T-02-12 | CLOSED | Relative no-symlink content checks, immutable digest stores, event-only acceptance, full pre-event manifest binding, linear Passport lineage, single-use resume, and immutable dynamic freshness. |
| T-02-13 to T-02-16 | CLOSED | Final-suffix-only recovery, exact raw/receipt hashes and offsets, operator-only recovery-first continuation, three crash failpoints, exact retry, and forged-evidence blocking. |
| T-02-17 to T-02-20 | CLOSED | Twenty-two checked schemas, aggregate installed identity, positive stage allowlist/private canaries, owned clean roots, raw command/tree/hash evidence, full offline regression, and dual phase verifiers. |

## Security Audit 2026-07-13

| Metric | Count |
|---|---:|
| Threats found in plan-time register | 20 |
| Closed | 20 |
| Open | 0 |

The review found destructive clean-root, replay-authority, manifest-state-binding, blocker-bypass, orphan-manifest, and writer-lock gaps while verifying the register. All were fixed in `b5e672b` and covered by deterministic rejection, tampering, safety, or full-tree tests before this audit was recorded.

## Accepted Risks

- SUP-04 remains `BLOCKED` until accountable intended-use, distribution, approval, and compatible permission evidence exists. It is not accepted as a release exception.
- VER-03 retains the later race-sensitive replacement matrix; deterministic traversal and symlink cases in the Phase 2 scope are closed.

## Audit Trail

- 2026-07-13: Verified all 20 Phase 2 plan-time threats against implementation, staged execution, retained raw evidence, and 138 passing offline tests. `threats_open: 0`.
