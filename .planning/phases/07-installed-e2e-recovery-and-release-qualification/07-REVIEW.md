---
phase: 07-installed-e2e-recovery-and-release-qualification
reviewer: codex
status: findings-fixed
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

F-001 through F-006 are fixed in the verifier/evidence boundary. The retained
Phase 5 and Phase 4.1 receipts now require canonical JSON parsing, recomputed
content/stage digests, schema and expected-case checks, and parent inventory
coverage. Stage, lock, canary, and clean evidence roots are checked lexically
with `lstat` before resolution. Verifier subprocesses use a positive
environment allowlist and fail closed on secret markers. Fault sidecars bind a
registered `FAULT_SPECS` identity/boundary, bounded retry count, SHA-256
digests, and recovered-event digest presence.

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

The Phase 7 verifier also completed with technical qualification PASS and
release qualification BLOCKED. This does not clear the legal release gate.
