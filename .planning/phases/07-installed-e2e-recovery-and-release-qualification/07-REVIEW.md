---
phase: 07-installed-e2e-recovery-and-release-qualification
reviewer: codex
status: findings-open
scope: committed Phase 7 changes from 7813473..HEAD
---

# Phase 7 Code Review

## Verification performed

The bounded Phase 7 suite passed locally with repository-local temporary
storage and offline flags:

```text
tests/integration/test_phase7_installed_e2e.py
tests/integration/test_phase7_fault_matrix.py
tests/integration/test_phase7_verifier.py
tests/staged/test_phase7_qualification.py
tests/unit/test_integration_lock.py
67 passed
```

The findings below are fail-closed/security issues in the verifier and
evidence boundary. They are not test-implementation failures and should be
resolved before treating the technical qualification as independently
replayable.

## Findings

### F-001 — HIGH: `--clean` evidence-root traversal can escape the evidence base

`scripts/verify-phase-7:90-108` calls `Path.absolute()` and performs a lexical
`is_relative_to(EVIDENCE_BASE)` check before resolving `..` components. A path
such as `build/evidence/../../outside` passes that check and resolves outside
`build/evidence`; if the destination contains the ownership marker, `--clean`
will remove it. The same unresolved path is then used for marker creation.

Fix by rejecting `..` components (and absolute paths outside the base) before
resolution, then comparing the fully resolved candidate against a resolved
`EVIDENCE_BASE`; deletion must only be permitted when the resolved directory
remains below that base and its marker is a direct regular file.

### F-002 — HIGH: phase-7 input symlink and root-boundary checks are bypassed

`scripts/verify-phase-7:328-330` resolves `ARW_PHASE7_STAGE`,
`ARW_PHASE7_LOCK`, and `ARW_PHASE7_CANARY` before passing them to
`validate_stage_and_inputs`. The latter's `is_symlink()` checks therefore see
the resolved target rather than the user-supplied path. An environment value
can consequently point the verifier at a symlink or an arbitrary external
receipt tree. There is also no requirement that the stage, lock, and canary
remain under their owned project-local bases.

Fix by lstat-ing the lexical input and every parent component first, rejecting
symlinks and paths outside the expected stage/evidence roots; only then derive
a resolved read path and bind that exact path in the receipt.

### F-003 — HIGH: prior-phase receipts are not content-bound or semantically
validated

`_validate_phase5` (`scripts/verify-phase-7:164-195`) trusts the mutable
`stage-tree.json.sha256` value as long as it equals the equally mutable
`verdict.json.stage_identity_sha256`; it never recomputes the stage-tree digest
or verifies canonical bytes. `_validate_phase41`
(`scripts/verify-phase-7:214-243`) checks only file presence, one boolean, case
count, and two `returncode` fields. It does not validate the case-result,
review-packet, host, or assessment schemas or bind their bytes to the verdict.
An edited receipt corpus can therefore retain a fabricated technical PASS.

Fix by requiring canonical JSON, deriving each receipt digest from its exact
bytes, validating all required schemas/expected case IDs and statuses, and
requiring a parent manifest/aggregate digest that covers every receipt before
accepting the prior-phase PASS.

### F-004 — HIGH: `aggregate_verdict` hard-codes technical PASS

`scripts/verify-phase-7:290-310` constructs PASS for VER-02/04/06/08 without
inspecting the supplied summaries or command records. The public helper even
returns technical PASS for `test_commands=[]` (the current regression probe at
`tests/integration/test_phase7_verifier.py:75-87` exercises this behavior).
The CLI reaches it after preflight checks, but any caller or future integration
that invokes the helper directly can launder incomplete evidence into a PASS.

Fix by making aggregation consume typed, already-validated receipt objects,
asserting all required evidence and non-empty successful command receipts, and
returning BLOCKED whenever any required input is missing, stale, malformed, or
not PASS. Keep legal release blockers as a separate, fixed gate only after the
technical predicate succeeds.

### F-005 — MEDIUM: verifier subprocesses inherit secrets and redaction is
incomplete

`run_command` (`scripts/verify-phase-7:124-151`) starts from
`os.environ.copy()`, so API keys and credential variables are available to
every verifier subprocess. `_redact` only recognizes a subset of
`NAME=value` forms and does not reliably redact JSON/colon forms or bare token
material. A test or tool that prints `"api_key": "..."` can therefore persist
secret bytes in `stdout.log`/`stderr.log`.

Fix by constructing a positive environment allowlist (explicitly stripping
all credential variables), applying structured key/value redaction, and
failing closed if retained streams contain secret markers rather than merely
hashing the output.

### F-006 — MEDIUM: fault sidecar metadata is caller-forgeable

`src/arw/evidence.py:47-98` accepts arbitrary `fault_id`, `boundary`,
`replay_classification`, `reason_code`, retry count, and digest strings. It
does not require IDs to exist in `FAULT_SPECS`, enforce boundary/ID parity,
bound retries to the phase policy, or require a canonical recovery-event
digest for a `RECOVERED_*` classification. Hashing this payload proves only
that the supplied text was written, not that the runtime ledger produced the
claim.

Fix with a strict sidecar model: known fault registry ID, matching boundary,
bounded retry count (maximum one fresh retry), SHA-256 format checks, and a
mandatory validated canonical recovery event for recovered classifications.
The parent should publish the sidecar only after replay verifies those
bindings.

## Overall assessment

The initial implementation covered the intended happy-path journeys but was
not independently fail-closed against tampered or externally supplied
receipts. The remediation below closes those findings; technical qualification
still remains distinct from the legal release gate.

## Remediation verification (2026-07-16)

F-001, F-002, and F-005 are fixed in the verifier/evidence boundary. The
retained Phase 5 and Phase 4.1 receipts now require canonical JSON parsing,
content checks, and schema/expected-case checks, while stage, lock, canary, and
clean evidence roots are checked lexically with `lstat` before resolution.
Verifier subprocesses use a positive environment allowlist and fail closed on
secret markers. Fault sidecars bind a registered `FAULT_SPECS` identity and
boundary, bounded retry count, SHA-256-shaped fields, and recovered-event
digest presence. Those checks are useful hygiene, but they do not yet provide
an independent parent manifest or ledger binding.

## Residual findings after 86199d7

### F-003R — HIGH: prior receipts remain mutable without an independent aggregate binding

`_validate_phase41` verifies each case against its schema and verifies the
mutable `raw-evidence-inventory.json` against the mutable files it lists, but
does not require the phase verdict to bind the canonical hashes of the host,
assessment, packet, evaluation, and case-result corpus. An attacker can edit
those receipts to a different internally consistent PASS corpus, update the
inventory digest, and retain a fabricated technical PASS. `_validate_stage_tree`
recomputes staged file bytes but accepts `stage-tree.json.sha256` as a copied
build-identity value; it does not derive an independent stage-tree/parent
manifest digest. The verifier still needs a canonical parent manifest that
covers every retained receipt and is itself bound by the phase verdict.

### F-004R — HIGH: aggregate helper still launders arbitrary successful commands

`aggregate_verdict` only checks that `test_commands` is a non-empty list with
zero return codes and SHA-256-shaped stream fields. It does not enforce the
required command names, exact argv, command count, or semantic result receipts.
Therefore a direct caller can pass one fabricated successful `echo` record and
typed dummy PASS receipt summaries and receive technical `PASS` (verified
locally with `argv=["echo", "evil"]`). Aggregation must consume a typed,
complete command manifest with required names and validated result digests,
and remain `BLOCKED` for any missing or unexpected command.

### F-006R — MEDIUM: sidecar event/recovery digests are still caller-forgeable

`validate_fault_sidecar_payload` checks digest shape but not that
`event_sequence_sha256` is the digest of the run's canonical ledger sequence
or that `canonical_recovery_event_sha256` names a validated recovery event.
`validate_fault_sidecar` additionally checks only a sibling hash and is not
called by the replay/runtime path. It also accepts a non-canonical JSON
encoding when the sibling digest matches. A parent-owned publication path must
cold-replay the registered run, recompute the sequence/event bytes, require a
canonical sidecar byte representation, and reject a sidecar that is not bound
to that exact replay.

Focused evidence:

```text
tests/integration/test_phase7_verifier.py
tests/integration/test_phase7_fault_matrix.py
tests/staged/test_phase7_qualification.py
tests/integration/test_recovery_crash.py
tests/integration/test_journal_replay.py
tests/unit/test_canonical.py
34 passed
```

## Final residual review after ad85a33

The follow-up review was run against `7813473..ad85a33` with the focused
verifier, recovery, journal, and fault-matrix tests. The tests pass, but the
adversarial evidence probes below still fail the intended fail-closed
boundary. The review therefore remains `findings-open`.

### F-003R — HIGH: phase receipts still have no independent parent binding

The Phase 5 validator recomputes staged file digests and checks the mutable
`build-identity.json` rows against the mutable `stage-tree.json`, but it does
not require an independently retained digest for the complete stage-tree
manifest. `stage-tree.sha256` is the build-identity digest rather than a
digest derived from the canonical stage rows, and `stage_rows_sha256` is
optional in the verdict. A writer able to edit the retained stage, stage tree,
and verdict can produce a self-consistent replacement corpus that still
qualifies as PASS.

The Phase 4.1 validator similarly binds `raw-evidence-inventory.json` to its
own listed files and compares a few selected hashes, but that inventory and
the phase verdict are both mutable. `review-packet/manifest.json`,
`review-packet/packet-status.json`, and several checked receipts are not
covered by an immutable parent aggregate. Updating the inventory, verdict,
and receipt hashes together is accepted. Qualification needs a canonical
parent manifest (or equivalent immutable evidence index) covering every
accepted receipt and a verdict field bound to that exact parent digest.

### F-004R — HIGH: required command names do not prove command identity

`aggregate_verdict` now requires four names in the expected order, but accepts
arbitrary argv and caller-supplied stream digests for those names. A direct
probe passing `argv: ["echo", "evil"]` for all four required names, zero
return codes, and well-shaped hashes returns technical `PASS`. The aggregate
must consume a typed command manifest with exact command identity/argv and
result-file or output-content bindings produced by the verifier itself;
names and digest shape alone are insufficient.

### F-006R — MEDIUM: sidecar sequence and recovery evidence remain forgeable

`validate_fault_sidecar` verifies that `event_sequence_sha256` hashes the
sidecar's own `event_sequence`, but it never loads the run ledger or replay
result to establish that the sequence is canonical. An arbitrary sequence
such as `[{"forged": "not-ledger"}]` with its matching digest is accepted. For
`RECOVERED_*`, a caller-provided mapping containing only an arbitrary
`event_sha256` is accepted when the field matches the supplied digest. A
repository search shows no runtime/replay publication path invoking this
validator; the current use is confined to evidence tests. The parent must
cold-replay the registered run, compare canonical event bytes and the recovery
event digest, and invoke that validation before retaining the sidecar.

### Reproduction probes

```text
aggregate_verdict(required names + argv=["echo", "evil"]): technical PASS
validate_fault_sidecar(event_sequence=[{"forged":"not-ledger"}]): accepts
```

Until these three residual findings are closed and independently replayed,
Phase 7 technical qualification cannot be considered complete. The separate
SUP-04/P04-09 and CC BY-NC intended-use/distribution/permission blockers
remain unchanged.

The Phase 7 verifier's happy-path run completed with technical qualification
PASS and release qualification BLOCKED, but these residual evidence-boundary
findings mean the qualification is not independently replayable yet. This does
not clear the legal release gate.
