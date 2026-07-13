---
phase: 02-durable-provenance-runtime
reviewed: 2026-07-13
scope: Phase 02 implementation, staged package, verifier, and evidence boundaries
status: passed-with-fixed-findings
---

# Phase 2 Code Review

## Result

No open Critical, Warning, or Info finding remains. Review fixes are in `b5e672b`; the resulting supply-chain identity refresh is in `231b02b`.

## Fixed Findings

| Severity | Area | Finding | Resolution |
|---|---|---|---|
| Critical | `scripts/verify-phase-2`, `scripts/stage-plugin` | `--clean` accepted unowned paths and could recursively delete unrelated directories. | Phase 2 evidence is confined below `build/evidence`; reusable stage paths require an ownership inventory and evidence paths require an ownership marker. Destructive-boundary tests preserve external sentinels. |
| Warning | `src/arw/cli.py`, `src/arw/journal.py`, `src/arw/reducer.py` | CLI replay validated bytes and hashes but not runtime authority; legacy append could add role-less events to segmented runs. | Journal replay now applies the same reducer per accepted event, reports a trustworthy blocked prefix, requires explicit Phase 2 roles, and limits baseline append to legacy journals. |
| Warning | `src/arw/reducer.py`, `src/arw/runtime.py` | Pending decisions could be bypassed by lifecycle commands; shared blocker codes and reused stable IDs produced ambiguous state. | Lifecycle transitions reject accepted blockers; blocker ownership survives partial resolution; decision, attempt, and artifact IDs are single-use and replay-validated. |
| Warning | `src/arw/manifests.py`, `src/arw/journal.py` | Replayed Passport and artifact manifests were not checked against the full pre-event state. | Replay now binds workflow/head/revision/stage, artifacts, decisions, attempts, producer/time, attempt base, and consumed hashes before accepting the selecting event. |
| Warning | `src/arw/runtime.py` | Duplicate artifact IDs could install an orphan manifest before rejection. | Duplicate IDs and consumed hashes are checked before any store write; full-tree rejection tests remain byte-identical. |
| Warning | `src/arw/journal.py` | Writer locks could follow a symbolic link. | Mutating lock acquisition rejects symlinks and non-files before portalocker opens the path. |
| Warning | `src/arw/cli.py` | Status without `--at` omitted current freshness evaluation. | CLI status uses current UTC by default and keeps `--at` as deterministic clock injection. |

## Reviewed Areas

| Area | Result |
|---|---|
| Sole-writer lifecycle and rejection invariants | PASS |
| Segmented replay, trusted-prefix blocking, and legacy compatibility | PASS |
| Artifact/Passport authority, lineage, freshness, and exact resume | PASS |
| Tail classification, quarantine cross-binding, and crash idempotency | PASS |
| Strict schemas, installed launcher, stage allowlist, and private exclusions | PASS |
| Phase verdict raw evidence, technical/release split, and supply-chain identity | PASS |

## Residual Risk

- Race-sensitive file replacement beyond deterministic symlink rejection remains assigned to Phase 3 requirement VER-03; Phase 2 does not claim descriptor-relative artifact ingestion.
- Unkeyed hashes prove internal byte consistency, not resistance to an attacker who can rewrite the repository and every root of trust.
- SUP-04 remains a legal release blocker and is not waived by technical completion.

## Verification

- Full frozen offline suite: `138 passed in 160.58s`.
- Phase 1 and Phase 2 technical verifiers: `PASS`; release `BLOCKED`.
- Python compile, Bash syntax, whitespace, source, license, schema, and staged-package gates passed.
