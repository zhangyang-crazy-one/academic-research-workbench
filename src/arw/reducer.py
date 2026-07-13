"""Pure reduction of accepted canonical events into runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from arw.models import (
    AttemptClosedPayload,
    AttemptStartedPayload,
    CanonicalEvent,
    HumanDecisionRequestedPayload,
    HumanDecisionResolvedPayload,
    LifecycleTransitionedPayload,
    PassportAcceptedPayload,
    RecoveryHealth,
    ResumeAcceptedPayload,
    Sha256,
    StableRuntimeId,
    StrictModel,
    ZERO_HASH,
)
from arw.workflows import (
    WorkflowDefinitionError,
    actor_can_commit,
    event_category,
    legal_transitions,
    require_transition,
    require_workflow,
)


REDUCER_VERSION = "1.0.0"


class ReducerError(ValueError):
    """Accepted events cannot be reduced under the bound workflow."""


class BlockerState(StrictModel):
    code: StableRuntimeId
    source_event_id: str | None = None


class PendingDecisionState(StrictModel):
    decision_id: StableRuntimeId
    blocker_code: StableRuntimeId
    source_event_ids: list[str]
    starting_revision: int
    allowed_choices: list[StableRuntimeId]
    rationale_required: bool
    unlock_transitions: list[StableRuntimeId]


class AttemptState(StrictModel):
    attempt_id: StableRuntimeId
    base_revision: int
    consumed_sha256: list[Sha256]


class RuntimeState(StrictModel):
    run_id: str
    workflow_definition_id: str
    stage: str
    accepted_revision: int
    ledger_head_sha256: str
    current_passport_sha256: str | None = None
    recovery_health: RecoveryHealth = "healthy"
    blockers: list[BlockerState] = Field(default_factory=list)
    pending_human_decisions: list[PendingDecisionState] = Field(default_factory=list)
    active_attempts: list[AttemptState] = Field(default_factory=list)
    legal_next_transitions: list[str] = Field(default_factory=list)
    accepted_artifact_manifest_sha256: list[str] = Field(default_factory=list)
    accepted_passport_sha256: list[str] = Field(default_factory=list)
    consumed_passport_sha256: list[str] = Field(default_factory=list)
    reducer_version: Literal["1.0.0"] = REDUCER_VERSION
    schema_version: Literal["1.0.0"] = "1.0.0"

    @classmethod
    def empty(cls, *, run_id: str, workflow_definition_id: str) -> "RuntimeState":
        return cls(
            run_id=run_id,
            workflow_definition_id=workflow_definition_id,
            stage="initialized",
            accepted_revision=0,
            ledger_head_sha256=ZERO_HASH,
            legal_next_transitions=list(legal_transitions(workflow_definition_id, "initialized")),
        )


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def reduce_events(
    workflow_definition_id: str,
    events: list[CanonicalEvent] | tuple[CanonicalEvent, ...],
    *,
    now: datetime | None = None,
    recovery_health: RecoveryHealth = "healthy",
) -> RuntimeState:
    """Fold validated events without filesystem or projection state."""

    require_workflow(workflow_definition_id)
    if not events:
        raise ReducerError("a run requires at least run.initialized")
    run_id = events[0].run_id
    stage = "initialized"
    revision = 0
    head = ZERO_HASH
    decisions: dict[str, PendingDecisionState] = {}
    attempts: dict[str, AttemptState] = {}
    blockers: dict[str, BlockerState] = {}
    artifacts: list[str] = []
    passports: list[str] = []
    consumed_passports: list[str] = []
    current_passport: str | None = None
    fresh_until: str | None = None

    for event in events:
        if event.run_id != run_id:
            raise ReducerError("event run identity changed")
        if event.expected_revision != revision or event.resulting_revision != revision + 1:
            raise ReducerError("event revision is not contiguous")
        role = event.actor_role or "parent_control_plane"
        try:
            category = event_category(event.event_type)
        except WorkflowDefinitionError as error:
            raise ReducerError(str(error)) from error
        if not actor_can_commit(role, category):
            raise ReducerError(f"actor role {role!r} is not authorized for {category}")
        payload = event.payload
        if event.event_type == "run.initialized":
            if revision != 0:
                raise ReducerError("run.initialized must be first")
        elif event.event_type == "lifecycle.transitioned":
            assert isinstance(payload, LifecycleTransitionedPayload)
            if payload.from_stage != stage:
                raise ReducerError("transition from_stage differs from accepted stage")
            try:
                transition = require_transition(workflow_definition_id, stage, payload.transition_id)
            except WorkflowDefinitionError as error:
                raise ReducerError(f"transition is not legal: {error}") from error
            if transition.to_stage != payload.to_stage:
                raise ReducerError("transition to_stage differs from registered definition")
            stage = payload.to_stage
        elif event.event_type == "human_decision.requested":
            assert isinstance(payload, HumanDecisionRequestedPayload)
            if payload.decision_id in decisions:
                raise ReducerError("decision ID already pending")
            decisions[payload.decision_id] = PendingDecisionState(
                decision_id=payload.decision_id,
                blocker_code=payload.blocker_code,
                source_event_ids=list(payload.source_event_ids),
                starting_revision=payload.starting_revision,
                allowed_choices=list(payload.allowed_choices),
                rationale_required=payload.rationale_required,
                unlock_transitions=list(payload.unlock_transitions),
            )
            blockers[payload.blocker_code] = BlockerState(
                code=payload.blocker_code, source_event_id=event.event_id
            )
        elif event.event_type == "human_decision.resolved":
            assert isinstance(payload, HumanDecisionResolvedPayload)
            pending = decisions.get(payload.decision_id)
            if pending is None or payload.choice not in pending.allowed_choices:
                raise ReducerError("decision resolution is not allowed")
            if pending.rationale_required and not payload.rationale:
                raise ReducerError("decision rationale is required")
            decisions.pop(payload.decision_id)
            blockers.pop(pending.blocker_code, None)
        elif event.event_type == "attempt.started":
            assert isinstance(payload, AttemptStartedPayload)
            if payload.attempt_id in attempts:
                raise ReducerError("attempt ID is already active")
            attempts[payload.attempt_id] = AttemptState(
                attempt_id=payload.attempt_id,
                base_revision=payload.base_revision,
                consumed_sha256=list(payload.consumed_sha256),
            )
        elif event.event_type == "attempt.closed":
            assert isinstance(payload, AttemptClosedPayload)
            if payload.attempt_id not in attempts:
                raise ReducerError("attempt is not active")
            attempts.pop(payload.attempt_id)
        elif event.event_type == "artifact.accepted":
            artifacts.append(payload.manifest_sha256)  # type: ignore[union-attr]
        elif event.event_type == "passport.accepted":
            assert isinstance(payload, PassportAcceptedPayload)
            if payload.stage != stage or payload.based_on_revision > revision:
                raise ReducerError("Passport does not bind the accepted stage/revision")
            if payload.parent_passport_sha256 != current_passport:
                raise ReducerError("Passport parent is not current")
            if current_passport is not None and payload.supersedes_passport_sha256 != current_passport:
                raise ReducerError("Passport supersession is not linear")
            passports.append(payload.passport_sha256)
            current_passport = payload.passport_sha256
            fresh_until = payload.fresh_until
        elif event.event_type == "resume.accepted":
            assert isinstance(payload, ResumeAcceptedPayload)
            if payload.passport_sha256 != current_passport:
                raise ReducerError("resume Passport is stale")
            if payload.passport_sha256 in consumed_passports:
                raise ReducerError("resume Passport was already consumed")
            consumed_passports.append(payload.passport_sha256)

        revision = event.resulting_revision
        head = event.event_sha256

    effective_now = now
    if effective_now is not None and effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=UTC)
    if fresh_until and effective_now and effective_now > _parse_utc(fresh_until):
        blockers["evidence-expired"] = BlockerState(code="evidence-expired")

    if recovery_health == "recoverable_tail":
        next_transitions = ["recover"]
    elif recovery_health == "blocked" or blockers:
        next_transitions = []
    else:
        next_transitions = list(legal_transitions(workflow_definition_id, stage))
    return RuntimeState(
        run_id=run_id,
        workflow_definition_id=workflow_definition_id,
        stage=stage,
        accepted_revision=revision,
        ledger_head_sha256=head,
        current_passport_sha256=current_passport,
        recovery_health=recovery_health,
        blockers=list(blockers.values()),
        pending_human_decisions=list(decisions.values()),
        active_attempts=list(attempts.values()),
        legal_next_transitions=next_transitions,
        accepted_artifact_manifest_sha256=artifacts,
        accepted_passport_sha256=passports,
        consumed_passport_sha256=consumed_passports,
    )
