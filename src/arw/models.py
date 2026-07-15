"""Strict canonical run, event, and operator boundary models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


SCHEMA_VERSION = "1.0.0"
ZERO_HASH = "0" * 64

RunId = Annotated[
    str,
    StringConstraints(
        pattern=r"^run-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
EventId = Annotated[
    str,
    StringConstraints(
        pattern=r"^evt-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
CommandId = Annotated[
    str,
    StringConstraints(
        pattern=r"^cmd-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ActorId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9.-]{2,63}$")]
ProbeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9.-]{2,63}$")]
UtcTimestamp = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    ),
]
Capability = Literal["canonical-journal", "forced-stop-replay"]
ActorRole = Literal["parent_control_plane", "operator", "worker", "hook"]
RecoveryHealth = Literal["healthy", "recoverable_tail", "blocked"]
RecoveryFaultClass = Literal["incomplete-record", "malformed-record", "truncated-utf8"]
CheckpointKind = Literal["stage_handoff", "human_decision", "explicit", "recovery"]
JournalLayout = Literal["segmented-v1"]
StableRuntimeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._-]{2,95}$")]


class StrictModel(BaseModel):
    """Base configuration for every canonical boundary model."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_extra={"$schema": "https://json-schema.org/draft/2020-12/schema"},
    )


class ImmutableInput(StrictModel):
    """Digest-bound repository-relative input identity."""

    path: str
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def relative_posix_path(cls, value: str) -> str:
        if not value or "\x00" in value or "\\" in value:
            raise ValueError("immutable input path must be a non-empty POSIX path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("immutable input path must be normalized and relative")
        return value


class RunManifest(StrictModel):
    """Immutable identity written exactly once when a run is initialized."""

    schema_version: Literal["1.0.0"]
    run_id: RunId
    created_at: UtcTimestamp
    immutable_input: ImmutableInput
    workflow_family: Literal["academic-pipeline"]
    workflow_mode: Literal["inline-role-prompts"]
    workflow_definition_id: StableRuntimeId | None = None
    workflow_definition_sha256: Sha256 | None = None
    journal_layout: JournalLayout | None = None
    capabilities: list[Capability] = Field(min_length=1)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value

    @model_validator(mode="after")
    def workflow_identity_is_complete(self) -> Self:
        if (self.workflow_definition_id is None) != (self.workflow_definition_sha256 is None):
            raise ValueError("workflow definition ID and digest must be provided together")
        if self.journal_layout is not None and self.workflow_definition_id is None:
            raise ValueError("segmented journals require a bound workflow definition")
        return self


class RunInitializedPayload(StrictModel):
    manifest_sha256: Sha256


class BaselineProbePayload(StrictModel):
    probe_id: ProbeId
    status: Literal["pass", "fail"]
    summary: Annotated[str, Field(min_length=1, max_length=256)]


class LifecycleTransitionedPayload(StrictModel):
    transition_id: StableRuntimeId
    from_stage: StableRuntimeId
    to_stage: StableRuntimeId


class HumanDecisionRequestedPayload(StrictModel):
    decision_id: StableRuntimeId
    blocker_code: StableRuntimeId
    starting_revision: Annotated[int, Field(ge=0)]
    allowed_choices: list[StableRuntimeId] = Field(min_length=1)
    rationale_required: bool
    source_event_ids: list[EventId]
    unlock_transitions: list[StableRuntimeId]

    @field_validator("allowed_choices", "source_event_ids", "unlock_transitions")
    @classmethod
    def values_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("decision values must be unique")
        return value


class HumanDecisionResolvedPayload(StrictModel):
    decision_id: StableRuntimeId
    choice: StableRuntimeId
    rationale: Annotated[str, Field(min_length=1, max_length=2048)] | None = None


class AttemptStartedPayload(StrictModel):
    attempt_id: StableRuntimeId
    base_revision: Annotated[int, Field(ge=0)]
    consumed_sha256: list[Sha256]


class AttemptClosedPayload(StrictModel):
    attempt_id: StableRuntimeId
    outcome: Literal["completed", "failed", "cancelled", "superseded"]
    proposal_sha256: Sha256 | None = None


class ArtifactAcceptedPayload(StrictModel):
    artifact_id: StableRuntimeId
    manifest_sha256: Sha256
    artifact_sha256: Sha256
    attempt_id: StableRuntimeId | None = None


class PassportAcceptedPayload(StrictModel):
    passport_sha256: Sha256
    parent_passport_sha256: Sha256 | None
    supersedes_passport_sha256: Sha256 | None
    checkpoint_kind: CheckpointKind
    based_on_revision: Annotated[int, Field(ge=0)]
    stage: StableRuntimeId
    fresh_until: UtcTimestamp | None = None


class ResumeAcceptedPayload(StrictModel):
    passport_sha256: Sha256


class RecoveryCompletedPayload(StrictModel):
    recovery_id: StableRuntimeId
    prior_valid_revision: Annotated[int, Field(ge=0)]
    prior_valid_head_sha256: Sha256
    original_segment_sha256: Sha256
    original_segment_byte_count: Annotated[int, Field(ge=1)]
    quarantine_sha256: Sha256
    quarantine_receipt_sha256: Sha256
    fault_offset: Annotated[int, Field(ge=0)]
    fault_class: RecoveryFaultClass
    reason_code: StableRuntimeId


class RecoveryReceipt(StrictModel):
    schema_version: Literal["1.0.0"]
    run_id: RunId
    recovery_id: StableRuntimeId
    segment_relative_path: str
    original_segment_sha256: Sha256
    original_segment_byte_count: Annotated[int, Field(ge=1)]
    accepted_byte_end: Annotated[int, Field(ge=1)]
    fault_offset: Annotated[int, Field(ge=1)]
    fault_class: RecoveryFaultClass
    quarantine_raw_path: str
    quarantine_raw_sha256: Sha256
    prior_valid_revision: Annotated[int, Field(ge=1)]
    prior_valid_head_sha256: Sha256
    operator_id: ActorId
    reason_code: StableRuntimeId
    reason_text: Annotated[str, Field(min_length=1, max_length=2048)]
    command_id: CommandId
    event_id: EventId
    occurred_at: UtcTimestamp

    @field_validator("segment_relative_path", "quarantine_raw_path")
    @classmethod
    def recovery_paths_are_normalized(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or "\x00" in value
            or "\\" in value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("recovery paths must be normalized relative POSIX paths")
        return value

    @model_validator(mode="after")
    def offsets_fit_original_segment(self) -> Self:
        if self.accepted_byte_end != self.fault_offset:
            raise ValueError("accepted byte end must equal the fault offset")
        if self.fault_offset >= self.original_segment_byte_count:
            raise ValueError("fault offset must precede the end of the damaged segment")
        return self


# Phase 4 records are imported lazily by the validators below.  The lazy
# boundary is intentional: ``orchestration_models`` imports the Phase 2
# primitives from this module, while canonical event construction needs to
# retain the richer immutable assignment/proposal records from Plan 01.
Phase4ExecutionMode = Literal[
    "native_profile",
    "assignment_injected_subagent",
    "degraded_inline",
    "blocked",
]
Phase4ExecutionProvenance = Literal[
    "native_profile",
    "assignment_injected_subagent",
    "degraded_inline",
    "unavailable",
]
Phase4AttemptStatus = Literal[
    "prepared",
    "active",
    "cancel_requested",
    "force_terminated",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
    "rejected_stale",
    "superseded",
    "blocked",
]
Phase4RetryReason = Literal[
    "timeout",
    "process_failure",
    "repairable_envelope",
    "permission_denied",
    "stale_inputs",
    "superseded",
    "cancelled",
    "scientific_disagreement",
    "identity_mismatch",
    "policy_violation",
    "digest_mismatch",
]


def _phase4_record(value: object, model_name: str) -> object:
    """Validate a Plan 01 immutable record without creating an import cycle."""

    from arw import orchestration_models

    model = getattr(orchestration_models, model_name)
    if isinstance(value, model):
        # ``model_copy`` deliberately skips validation.  Canonical event
        # boundaries therefore revalidate even already-typed objects so a
        # caller cannot preserve a stale self-hash or omit a required binding.
        value = value.model_dump(mode="python")
    try:
        return model.model_validate(value)
    except Exception as error:  # Pydantic turns this into a strict payload error.
        raise ValueError(f"invalid Phase 4 {model_name}: {error}") from error


def _phase4_record_digest(value: object) -> str:
    from arw.orchestration_models import canonical_orchestration_model_bytes
    from arw.canonical import sha256_hex

    return sha256_hex(canonical_orchestration_model_bytes(value))  # type: ignore[arg-type]


def _phase4_hashes(value: object) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise TypeError("Phase 4 hash collections must be arrays")


class Phase4Payload(StrictModel):
    """Common non-authoritative source provenance retained by a parent event."""

    source_actor_id: ActorId | None = None
    source_actor_role: Literal["worker", "hook", "reviewer", "operator"] | None = None
    source_identity_id: StableRuntimeId | None = None
    source_host_agent_id: str | None = None
    source_evidence_sha256: Annotated[
        tuple[Sha256, ...], BeforeValidator(_phase4_hashes), Field(max_length=128)
    ] = ()

    @field_validator("source_evidence_sha256")
    @classmethod
    def source_hashes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Phase 4 source evidence hashes must be unique")
        return value


class ExecutionRoleMode(StrictModel):
    role_id: StableRuntimeId
    execution_mode: Phase4ExecutionMode
    execution_provenance: Phase4ExecutionProvenance
    independence_eligible: bool
    worker_identity_id: StableRuntimeId | None = None


class ExperimentProvenanceAcceptedPayload(Phase4Payload):
    """Parent-authored acceptance of one immutable external provenance record."""

    provenance_id: StableRuntimeId
    experiment_id: StableRuntimeId
    provenance_sha256: Sha256


class ExecutionModeSelectedPayload(Phase4Payload):
    execution_mode: Phase4ExecutionMode
    execution_provenance: Phase4ExecutionProvenance
    role_modes: Annotated[
        tuple[ExecutionRoleMode, ...], BeforeValidator(_phase4_hashes), Field(max_length=64)
    ] = ()
    role_catalog_sha256: Sha256 | None = None
    policy_sha256: Sha256 | None = None
    dag_sha256: Sha256 | None = None
    rationale: Annotated[str, Field(min_length=1, max_length=2048)] | None = None

    @model_validator(mode="after")
    def execution_claim_is_honest(self) -> Self:
        if self.execution_mode == "degraded_inline":
            if self.execution_provenance != "degraded_inline":
                raise ValueError("degraded_inline requires degraded_inline provenance")
            if any(item.independence_eligible for item in self.role_modes):
                raise ValueError("degraded_inline cannot record an independent role")
        if self.execution_mode == "blocked" and self.execution_provenance != "unavailable":
            raise ValueError("blocked execution requires unavailable provenance")
        if self.execution_mode == "native_profile" and self.execution_provenance != "native_profile":
            raise ValueError("native_profile requires native_profile provenance")
        if (
            self.execution_mode == "assignment_injected_subagent"
            and self.execution_provenance != "assignment_injected_subagent"
        ):
            raise ValueError(
                "assignment_injected_subagent requires assignment_injected_subagent provenance"
            )
        return self


class AssignmentPreparedPayload(Phase4Payload):
    assignment: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "ImmutableAssignment"))]
    assignment_sha256: Sha256

    @model_validator(mode="after")
    def assignment_digest_is_exact(self) -> Self:
        assignment = self.assignment
        if not hasattr(assignment, "canonical_sha256"):
            raise ValueError("assignment must be an ImmutableAssignment record")
        if assignment.canonical_sha256() != self.assignment_sha256:  # type: ignore[attr-defined]
            raise ValueError("assignment digest does not match immutable bytes")
        return self


class AssignmentSupersededPayload(AssignmentPreparedPayload):
    predecessor_assignment_id: StableRuntimeId
    predecessor_assignment_sha256: Sha256

    @model_validator(mode="after")
    def explicit_supersession_is_exact(self) -> Self:
        assignment = self.assignment
        if assignment.supersedes_assignment_id != self.predecessor_assignment_id:  # type: ignore[attr-defined]
            raise ValueError("superseding assignment does not name its predecessor")
        return self


class AttemptPreparedPayload(Phase4Payload):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "AttemptDescriptor"))]
    attempt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def attempt_binds_assignment(self) -> Self:
        attempt = self.attempt
        if attempt.assignment_id != self.assignment_id:  # type: ignore[attr-defined]
            raise ValueError("attempt does not bind the assignment")
        if attempt.status != "prepared":  # type: ignore[attr-defined]
            raise ValueError("attempt.prepared requires a prepared descriptor")
        if attempt.retry_reason is not None or attempt.retry_eligible:  # type: ignore[attr-defined]
            raise ValueError("a fresh attempt cannot carry predecessor retry state")
        if attempt.host_agent_id is not None or attempt.cancellation_deadline_at is not None:  # type: ignore[attr-defined]
            raise ValueError("a fresh attempt cannot predeclare host observations")
        if self.attempt_sha256 is not None and _phase4_record_digest(attempt) != self.attempt_sha256:
            raise ValueError("attempt digest does not match immutable bytes")
        return self


class AttemptLifecyclePayload(Phase4Payload):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt_id: StableRuntimeId
    attempt_number: Annotated[int, Field(ge=1, le=2)]
    status: Phase4AttemptStatus
    proposal_nonce: StableRuntimeId | None = None
    retry_reason: Phase4RetryReason | None = None
    retry_eligible: bool = False
    host_agent_id: str | None = None
    cancellation_deadline_at: UtcTimestamp | None = None
    proposal_sha256: Sha256 | None = None
    reason_code: StableRuntimeId | None = None

    @model_validator(mode="after")
    def retry_and_cancellation_bounds_are_exact(self) -> Self:
        if self.retry_eligible and self.retry_reason is None:
            raise ValueError("retry eligibility requires a retry reason")
        if self.retry_eligible and self.retry_reason not in {
            "timeout",
            "process_failure",
            "repairable_envelope",
        }:
            raise ValueError("only repairable failures may receive a retry")
        if self.attempt_number >= 2 and self.retry_eligible:
            raise ValueError("retry budget is exhausted after two attempts")
        if self.status == "cancel_requested" and self.cancellation_deadline_at is None:
            raise ValueError("cancellation requests require a deadline")
        return self


class ProposalAcceptedPayload(Phase4Payload):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt_id: StableRuntimeId
    proposal: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "WorkerProposal"))]
    proposal_sha256: Sha256
    acceptance_key: Annotated[
        tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)], StableRuntimeId],
        BeforeValidator(_phase4_hashes),
    ]
    accepted_status: Literal["accepted"] = "accepted"

    @model_validator(mode="after")
    def proposal_bindings_are_exact(self) -> Self:
        proposal = self.proposal
        if proposal.assignment_id != self.assignment_id or proposal.attempt_id != self.attempt_id:  # type: ignore[attr-defined]
            raise ValueError("proposal does not bind the assignment attempt")
        if _phase4_record_digest(proposal) != self.proposal_sha256:
            raise ValueError("proposal digest does not match immutable bytes")
        return self


class ProposalRejectedPayload(Phase4Payload):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt_id: StableRuntimeId
    proposal_sha256: Sha256
    outcome: Literal[
        "rejected", "rejected_invalid", "rejected_stale", "rejected_cancelled", "rejected_superseded"
    ]
    reason_code: StableRuntimeId
    acceptance_key: Annotated[
        tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)], StableRuntimeId],
        BeforeValidator(_phase4_hashes),
    ]
    raw_bytes_retained: bool = True


class ReviewReportAcceptedPayload(Phase4Payload):
    report: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "ReviewReport"))]
    report_sha256: Sha256

    @model_validator(mode="after")
    def report_digest_is_bound(self) -> Self:
        from arw.orchestration_models import review_report_body_sha256

        if self.report.report_sha256 != self.report_sha256:  # type: ignore[attr-defined]
            raise ValueError("review report digest does not match the report record")
        if review_report_body_sha256(self.report) != self.report_sha256:  # type: ignore[arg-type]
            raise ValueError("review report digest is not derived from canonical report body")
        return self


class HostIdentityAcceptedPayload(Phase4Payload):
    receipt: Annotated[
        object, BeforeValidator(lambda value: _phase4_record(value, "HostIdentityReceipt"))
    ]
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def host_identity_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.receipt) != self.receipt_sha256:
            raise ValueError("host identity receipt digest does not match immutable bytes")
        return self


class PanelPreparedPayload(Phase4Payload):
    manifest: Annotated[
        object, BeforeValidator(lambda value: _phase4_record(value, "PanelManifest"))
    ]
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def panel_manifest_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.manifest) != self.manifest_sha256:
            raise ValueError("panel manifest digest does not match immutable bytes")
        return self


class HumanAuthorityAcceptedPayload(Phase4Payload):
    authority: Annotated[
        object, BeforeValidator(lambda value: _phase4_record(value, "HumanAuthority"))
    ]
    authority_sha256: Sha256

    @model_validator(mode="after")
    def human_authority_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.authority) != self.authority_sha256:
            raise ValueError("human authority digest does not match immutable bytes")
        return self


class ReviewSynthesisAcceptedPayload(Phase4Payload):
    finding_matrix: Annotated[
        object, BeforeValidator(lambda value: _phase4_record(value, "ReviewFindingMatrix"))
    ]
    finding_matrix_sha256: Sha256

    @model_validator(mode="after")
    def synthesis_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.finding_matrix) != self.finding_matrix_sha256:
            raise ValueError("finding matrix digest does not match immutable bytes")
        return self


class HookObservedPayload(Phase4Payload):
    observation: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "HookObservation"))]
    observation_sha256: Sha256

    @model_validator(mode="after")
    def hook_observation_digest_is_bound(self) -> Self:
        if self.observation.observation_sha256 != self.observation_sha256:  # type: ignore[attr-defined]
            raise ValueError("hook observation digest does not match the observation")
        return self


class GateEvaluatedPayload(Phase4Payload):
    decision: Annotated[object, BeforeValidator(lambda value: _phase4_record(value, "GateDecision"))]
    decision_sha256: Sha256

    @model_validator(mode="after")
    def gate_decision_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.decision) != self.decision_sha256:
            raise ValueError("gate decision digest does not match immutable bytes")
        return self


class HumanDecisionRecordedPayload(Phase4Payload):
    decision: Annotated[
        object, BeforeValidator(lambda value: _phase4_record(value, "HumanDecisionRecord"))
    ]
    decision_sha256: Sha256
    authority_sha256: Sha256

    @model_validator(mode="after")
    def human_decision_digest_is_bound(self) -> Self:
        if _phase4_record_digest(self.decision) != self.decision_sha256:
            raise ValueError("human decision digest does not match immutable bytes")
        if self.decision.authority_sha256 != self.authority_sha256:  # type: ignore[attr-defined]
            raise ValueError("human decision does not bind the accepted authority")
        return self


PHASE4_EVENT_TYPES = frozenset(
    {
        "execution.mode_selected",
        "assignment.prepared",
        "assignment.superseded",
        "attempt.prepared",
        "attempt.lifecycle",
        "proposal.accepted",
        "proposal.rejected",
        "host_identity.accepted",
        "panel.prepared",
        "review.report_accepted",
        "review.synthesis_accepted",
        "hook.observed",
        "gate.evaluated",
        "human_authority.accepted",
        "human_decision.recorded",
        "experiment.provenance.accepted",
    }
)


PHASE4_EVENT_PAYLOAD_TYPES: dict[str, type[StrictModel]] = {
    "execution.mode_selected": ExecutionModeSelectedPayload,
    "assignment.prepared": AssignmentPreparedPayload,
    "assignment.superseded": AssignmentSupersededPayload,
    "attempt.prepared": AttemptPreparedPayload,
    "attempt.lifecycle": AttemptLifecyclePayload,
    "proposal.accepted": ProposalAcceptedPayload,
    "proposal.rejected": ProposalRejectedPayload,
    "host_identity.accepted": HostIdentityAcceptedPayload,
    "panel.prepared": PanelPreparedPayload,
    "review.report_accepted": ReviewReportAcceptedPayload,
    "review.synthesis_accepted": ReviewSynthesisAcceptedPayload,
    "hook.observed": HookObservedPayload,
    "gate.evaluated": GateEvaluatedPayload,
    "human_authority.accepted": HumanAuthorityAcceptedPayload,
    "human_decision.recorded": HumanDecisionRecordedPayload,
    "experiment.provenance.accepted": ExperimentProvenanceAcceptedPayload,
}


EVENT_PAYLOAD_TYPES: dict[str, type[StrictModel]] = {
    "run.initialized": RunInitializedPayload,
    "baseline.probe_recorded": BaselineProbePayload,
    "lifecycle.transitioned": LifecycleTransitionedPayload,
    "human_decision.requested": HumanDecisionRequestedPayload,
    "human_decision.resolved": HumanDecisionResolvedPayload,
    "attempt.started": AttemptStartedPayload,
    "attempt.closed": AttemptClosedPayload,
    "artifact.accepted": ArtifactAcceptedPayload,
    "passport.accepted": PassportAcceptedPayload,
    "resume.accepted": ResumeAcceptedPayload,
    "recovery.completed": RecoveryCompletedPayload,
    **PHASE4_EVENT_PAYLOAD_TYPES,
}


class CanonicalEvent(StrictModel):
    """One hash-chained event accepted by the canonical writer."""

    schema_version: Literal["1.0.0"]
    event_type: Literal[
        "run.initialized",
        "baseline.probe_recorded",
        "lifecycle.transitioned",
        "human_decision.requested",
        "human_decision.resolved",
        "attempt.started",
        "attempt.closed",
        "artifact.accepted",
        "passport.accepted",
        "resume.accepted",
        "recovery.completed",
        "execution.mode_selected",
        "assignment.prepared",
        "assignment.superseded",
        "attempt.prepared",
        "attempt.lifecycle",
        "proposal.accepted",
        "proposal.rejected",
        "host_identity.accepted",
        "panel.prepared",
        "review.report_accepted",
        "review.synthesis_accepted",
        "hook.observed",
        "gate.evaluated",
        "human_authority.accepted",
        "human_decision.recorded",
        "experiment.provenance.accepted",
    ]
    event_id: EventId
    command_id: CommandId
    run_id: RunId
    sequence: Annotated[int, Field(ge=1)]
    occurred_at: UtcTimestamp
    expected_revision: Annotated[int, Field(ge=0)]
    resulting_revision: Annotated[int, Field(ge=1)]
    actor_id: ActorId
    actor_role: ActorRole | None = None
    prev_event_sha256: Sha256
    payload: (
        RunInitializedPayload
        | BaselineProbePayload
        | LifecycleTransitionedPayload
        | HumanDecisionRequestedPayload
        | HumanDecisionResolvedPayload
        | AttemptStartedPayload
        | AttemptClosedPayload
        | ArtifactAcceptedPayload
        | PassportAcceptedPayload
        | ResumeAcceptedPayload
        | RecoveryCompletedPayload
        | ExecutionModeSelectedPayload
        | AssignmentPreparedPayload
        | AssignmentSupersededPayload
        | AttemptPreparedPayload
        | AttemptLifecyclePayload
        | ProposalAcceptedPayload
        | ProposalRejectedPayload
        | HostIdentityAcceptedPayload
        | PanelPreparedPayload
        | ReviewReportAcceptedPayload
        | ReviewSynthesisAcceptedPayload
        | HookObservedPayload
        | GateEvaluatedPayload
        | HumanAuthorityAcceptedPayload
        | HumanDecisionRecordedPayload
        | ExperimentProvenanceAcceptedPayload
    )
    event_sha256: Sha256

    @model_validator(mode="after")
    def valid_variant_and_revision(self) -> Self:
        expected_payload = EVENT_PAYLOAD_TYPES[self.event_type]
        if not isinstance(self.payload, expected_payload):
            raise ValueError("event_type and payload variant do not match")
        if self.event_type in PHASE4_EVENT_TYPES and self.actor_role != "parent_control_plane":
            raise ValueError("Phase 4 canonical events require a parent_control_plane actor")
        if self.event_type not in {"run.initialized", "baseline.probe_recorded"} and self.actor_role is None:
            raise ValueError("Phase 2 events require actor_role")
        if self.resulting_revision != self.expected_revision + 1:
            raise ValueError("resulting_revision must increment expected_revision once")
        return self


class Rejection(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    code: StableRuntimeId
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    run_id: RunId | None = None
    accepted_revision: Annotated[int, Field(ge=0)] | None = None
    ledger_head_sha256: Sha256 | None = None
    current_passport_sha256: Sha256 | None = None
    legal_next_transitions: list[StableRuntimeId] = Field(default_factory=list)
    recovery_health: RecoveryHealth | None = None


class RuntimeCommandRequest(StrictModel):
    schema_version: Literal["1.0.0"]
    run_id: RunId
    event_id: EventId
    command_id: CommandId
    expected_revision: Annotated[int, Field(ge=0)]
    occurred_at: UtcTimestamp
    actor_id: ActorId
    actor_role: ActorRole


class LifecycleTransitionRequest(RuntimeCommandRequest):
    transition_id: StableRuntimeId
    from_stage: StableRuntimeId


class HumanDecisionRequest(RuntimeCommandRequest):
    decision_id: StableRuntimeId
    blocker_code: StableRuntimeId
    allowed_choices: list[StableRuntimeId] = Field(min_length=1)
    rationale_required: bool
    source_event_ids: list[EventId]
    unlock_transitions: list[StableRuntimeId]

    @field_validator("allowed_choices", "source_event_ids", "unlock_transitions")
    @classmethod
    def decision_values_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("decision request values must be unique")
        return value


class HumanDecisionResolveRequest(RuntimeCommandRequest):
    decision_id: StableRuntimeId
    choice: StableRuntimeId
    rationale: Annotated[str, Field(min_length=1, max_length=2048)] | None = None


class AttemptStartRequest(RuntimeCommandRequest):
    attempt_id: StableRuntimeId
    base_revision: Annotated[int, Field(ge=0)]
    consumed_sha256: list[Sha256]


class AttemptCloseRequest(RuntimeCommandRequest):
    attempt_id: StableRuntimeId
    outcome: Literal["completed", "failed", "cancelled", "superseded"]
    proposal_sha256: Sha256 | None = None


class ArtifactManifest(StrictModel):
    schema_version: Literal["1.0.0"]
    run_id: RunId
    artifact_id: StableRuntimeId
    artifact_kind: StableRuntimeId
    media_type: Annotated[str, Field(min_length=3, max_length=127)]
    content_path: str
    content_sha256: Sha256
    producer_id: ActorId
    attempt_id: StableRuntimeId | None = None
    base_revision: Annotated[int, Field(ge=0)]
    consumed_sha256: list[Sha256]
    created_at: UtcTimestamp

    @field_validator("content_path")
    @classmethod
    def normalized_content_path(cls, value: str) -> str:
        if not value or "\x00" in value or "\\" in value:
            raise ValueError("content path must be a normalized relative POSIX path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("content path must be a normalized relative POSIX path")
        return value


class ArtifactAcceptanceRequest(RuntimeCommandRequest):
    artifact_id: StableRuntimeId
    artifact_kind: StableRuntimeId
    media_type: Annotated[str, Field(min_length=3, max_length=127)]
    content_path: str
    content_sha256: Sha256
    attempt_id: StableRuntimeId | None = None
    base_revision: Annotated[int, Field(ge=0)]
    consumed_sha256: list[Sha256]

    @field_validator("content_path")
    @classmethod
    def normalized_content_path(cls, value: str) -> str:
        return ArtifactManifest.normalized_content_path(value)


class PassportDecisionSnapshot(StrictModel):
    decision_id: StableRuntimeId
    blocker_code: StableRuntimeId
    source_event_ids: list[EventId]
    starting_revision: Annotated[int, Field(ge=0)]
    allowed_choices: list[StableRuntimeId]
    rationale_required: bool
    unlock_transitions: list[StableRuntimeId]


class PassportAttemptSnapshot(StrictModel):
    attempt_id: StableRuntimeId
    base_revision: Annotated[int, Field(ge=0)]
    consumed_sha256: list[Sha256]


class MaterialPassport(StrictModel):
    schema_version: Literal["1.0.0"]
    run_id: RunId
    workflow_definition_id: StableRuntimeId
    workflow_definition_sha256: Sha256
    based_on_revision: Annotated[int, Field(ge=0)]
    ledger_head_sha256: Sha256
    stage: StableRuntimeId
    checkpoint_kind: CheckpointKind
    parent_passport_sha256: Sha256 | None = None
    supersedes_passport_sha256: Sha256 | None = None
    accepted_artifact_manifest_sha256: list[Sha256]
    pending_human_decisions: list[PassportDecisionSnapshot]
    active_attempts: list[PassportAttemptSnapshot]
    fresh_until: UtcTimestamp | None = None
    created_at: UtcTimestamp
    created_by: ActorId


class PassportPointer(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    passport_sha256: Sha256
    accepted_revision: Annotated[int, Field(ge=1)]
    ledger_head_sha256: Sha256


class CheckpointRequest(RuntimeCommandRequest):
    checkpoint_kind: CheckpointKind
    fresh_until: UtcTimestamp | None = None


class ResumeRequest(RuntimeCommandRequest):
    passport_sha256: Sha256


class RecoveryRequest(RuntimeCommandRequest):
    expected_head_sha256: Sha256
    recovery_id: StableRuntimeId
    original_segment_sha256: Sha256
    reason_code: StableRuntimeId
    reason_text: Annotated[str, Field(min_length=1, max_length=2048)]


class InitRunRequest(StrictModel):
    """Strict operator request used to construct manifest and initial event."""

    schema_version: Literal["1.0.0"]
    run_id: RunId
    occurred_at: UtcTimestamp
    immutable_input: ImmutableInput
    workflow_family: Literal["academic-pipeline"]
    workflow_mode: Literal["inline-role-prompts"]
    workflow_definition_id: StableRuntimeId | None = None
    workflow_definition_sha256: Sha256 | None = None
    journal_layout: JournalLayout | None = None
    capabilities: list[Capability] = Field(min_length=1)
    event_id: EventId
    command_id: CommandId
    actor_id: ActorId

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value

    @model_validator(mode="after")
    def workflow_identity_is_complete(self) -> Self:
        if (self.workflow_definition_id is None) != (self.workflow_definition_sha256 is None):
            raise ValueError("workflow definition ID and digest must be provided together")
        if self.journal_layout is not None and self.workflow_definition_id is None:
            raise ValueError("segmented journals require a bound workflow definition")
        return self


class AppendProbeRequest(StrictModel):
    """Strict Phase 1 append request; sequence and hashes are writer-owned."""

    schema_version: Literal["1.0.0"]
    event_type: Literal["baseline.probe_recorded"]
    event_id: EventId
    command_id: CommandId
    run_id: RunId
    occurred_at: UtcTimestamp
    expected_revision: Annotated[int, Field(ge=1)]
    actor_id: ActorId
    payload: BaselineProbePayload
