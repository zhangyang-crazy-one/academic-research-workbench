# Durable Provenance Runtime

## Authority

Canonical authority consists of `run-manifest.json`, accepted journal events, and
immutable manifests selected by those events. `passport.json`, status output,
indexes, graphs, transcripts, hooks, and quarantine files do not independently
change accepted state.

New Phase 2 runs declare `journal_layout: segmented-v1` and bind a registered
workflow definition ID and SHA-256. Existing Phase 1 `events.jsonl` runs remain
replayable and read-only to Phase 2 commands.

## Commands

All mutating commands take a strict JSON request. The installed launcher routes
them to the sole writer:

```bash
bin/arw init --run-root RUN --request init.json
bin/arw transition --run-root RUN --request transition.json
bin/arw decision-request --run-root RUN --request decision.json
bin/arw decision-resolve --run-root RUN --request resolution.json
bin/arw attempt-start --run-root RUN --request attempt-start.json
bin/arw attempt-close --run-root RUN --request attempt-close.json
bin/arw artifact-accept --run-root RUN --request artifact.json
bin/arw checkpoint --run-root RUN --request checkpoint.json
bin/arw resume --run-root RUN --request resume.json
bin/arw recover --run-root RUN --request recovery.json
```

The caller supplies run, event, command, expected revision, timestamp, actor,
and command payload fields. The writer derives sequence, resulting revision,
previous event hash, and event hash. A rejected command exits `65`, returns the
accepted state and structured rejection, and does not modify canonical files.

## Status

```bash
bin/arw status --json --run-root RUN
bin/arw status --json --at 2026-07-13T09:26:00Z --run-root RUN
bin/arw replay --run-root RUN
```

Status is read-only and reports run/workflow identity, stage, accepted revision,
ledger head, current Passport, recovery health, blockers, pending decisions,
active attempts, and legal next transitions. `--at` injects the time used for
freshness projection; it never changes Passport bytes.

A healthy, recoverable-tail, or blocked state with at least one trustworthy
event exits `0`. Missing authority or damage before any trustworthy prefix exits
nonzero. Consumers must inspect `recovery_health` and `blockers`, not only the
process exit status.

## Passports

`checkpoint` accepts only an explicit operator boundary, a registered coherent
stage handoff, a just-resolved human decision, or an accepted recovery boundary.
Each Material Passport is canonical JSON stored at
`passports/sha256/<sha256>.json`. Its accepted event binds the exact prior
revision/head, stage, artifacts, pending decisions, attempts, freshness,
parent, and superseded Passport.

Resume is operator-authored and consumes only the exact current unconsumed
Passport at the expected revision. Stale, superseded, expired, or already
consumed Passports cannot create a branch. `passport.json` is a derived pointer;
status and replay ignore it. Repair is explicit:

```bash
bin/arw passport-pointer-rebuild --run-root RUN
```

## Recovery

Only a malformed, incomplete, or truncated-UTF-8 final record after a fully
validated prefix is recoverable. A changed accepted event, hash/revision/sequence
failure, middle corruption, manifest mismatch, later record after corruption,
segment-layout defect, or invalid prior recovery binding is blocked for human
forensics.

For a recoverable tail, status reports `recoverable_tail`, blocker
`tail-recovery-required`, the last accepted revision/head, and legal transition
`recover`. Construct the recovery request with those revision/head values and
the SHA-256 of the complete damaged final segment, then run `recover`.

Recovery leaves the damaged segment unchanged and writes:

```text
quarantine/<recovery_id>/segment.raw
quarantine/<recovery_id>/receipt.json
journal/segments/<next-number>.jsonl
```

The next segment begins with exactly one `recovery.completed` event. It binds
the previous revision/head, complete original segment digest/count, quarantine
raw digest, receipt digest, fault offset/class, operator, command/event IDs,
timestamp, and reason. Exact retries are idempotent. Conflicting evidence or a
non-tail fault remains blocked; operators must preserve the run and investigate
rather than truncate, rewrite, reorder, or delete canonical bytes.

## Qualification

From the repository root:

```bash
UV_OFFLINE=1 ./scripts/verify-phase-2 --clean \
  --evidence-root build/evidence/phase-02
```

The verifier stages the plugin, runs the projection-free crash/recovery fixture
through fresh installed processes, retains command streams and tree hashes, and
writes `build/evidence/phase-02/verdict.json`. Technical qualification does not
override the separate SUP-04 release block.
