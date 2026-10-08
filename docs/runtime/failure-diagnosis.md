# Read-only failure diagnosis

`arw learn diagnose --project-root PROJECT --run-root RUN --input REQUEST.json`
reads the current run journal and existing parent-accepted `learning-evidence`
artifacts. It emits a deterministic `arw.failure-diagnosis.v1` report and its
SHA-256 digest on stdout. It writes no diagnosis, source, product, memory,
policy, or ledger file; it does not execute any proposed probe.

The strict request contains `schema_version: "arw.failure-diagnosis-request.v1"`,
one `acceptance_artifact_id`, one to eight ordered `failure_artifact_ids`, and
optional ordered `change_artifact_ids`. The request cannot contain a hidden
cause or an acceptance override. The acceptance artifact uses
`arw.failure-acceptance.v1` with stable sample IDs, expected decimal values,
and units. Each `arw.failed-attempt.v1` receipt binds its exact acceptance
content hash, records `status: failed`, and supplies observed values, units,
and optional traced source sample IDs. `arw.failure-edit.v1` records bounded
before/after edits and the attempt identity. All three source types must be
separately accepted by the parent as `learning-evidence`; the acceptance event
must precede each failed receipt event. Accepted event, manifest, and retained
source hashes are rechecked before analysis.

The result lists recurrence, opposing edits, and expectation mismatch as
`yes` or `unknown` from the supplied evidence. Every judgment cites canonical
event and artifact IDs and SHA-256 digests. It offers three explicit
mechanisms: sign inversion, unit-label mismatch, and sample-ID mapping. A
`kept` status means available observations are compatible with a mechanism;
`ruled_out` means a necessary observable pattern is contradicted;
`unresolved` means the needed distinction is missing. Each mechanism has a
falsifier and a proposed probe with different predicted results for the
competitors. `actual_evidence` stays null until separately accepted probe
evidence can be supported by a future contract. This command does not run or
attach probe results. `causal_status` is always `unknown`.

To continue, a parent can separately accept the report as an artifact and
save a regular memory handoff that cites the report's exact artifact and event
hashes. A later request can add `prior_diagnosis_artifact_id` and
`handoff_memory_id`; the command resolves `research.memory.read` only then.
The memory extension revalidates its canonical body and links. When a newer
handoff exists, `previous_handoff_memory_id` requires the existing memory
`supersedes` chain. A previous `ruled_out` mechanism is not re-recommended;
contradictory new evidence raises `conflicting_successor_evidence` for review.
No heuristic is created, evaluated, qualified, or promoted by this command.

The base command works without optional learning or memory extensions. A
requested handoff with no memory provider returns `CapabilityUnavailable`.
The three bundled sign, unit, and mapping cases are self-authored local
engineering fixtures. Their hidden cause is withheld from the diagnosis
request; a compatible pattern is not proof of scientific causality. Missing,
corrupt, ambiguous, noncanonical, or late evidence fails closed.
