"""Strict canonical run, event, and operator boundary models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


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
    quarantine_sha256: Sha256
    fault_offset: Annotated[int, Field(ge=0)]
    reason_code: StableRuntimeId


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
    )
    event_sha256: Sha256

    @model_validator(mode="after")
    def valid_variant_and_revision(self) -> Self:
        expected_payload = EVENT_PAYLOAD_TYPES[self.event_type]
        if not isinstance(self.payload, expected_payload):
            raise ValueError("event_type and payload variant do not match")
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
