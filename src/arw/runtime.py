"""Sole-writer replay, validation, and canonical append transactions."""

from __future__ import annotations

from pathlib import Path

from pydantic import model_validator

from arw.journal import (
    JournalError,
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
    replay_run,
)
from arw.manifests import ManifestError, install_artifact_manifest, validate_content_file
from arw.models import (
    ArtifactAcceptanceRequest,
    ArtifactAcceptedPayload,
    ArtifactManifest,
    AttemptCloseRequest,
    AttemptClosedPayload,
    AttemptStartRequest,
    AttemptStartedPayload,
    CanonicalEvent,
    HumanDecisionRequest,
    HumanDecisionRequestedPayload,
    HumanDecisionResolveRequest,
    HumanDecisionResolvedPayload,
    LifecycleTransitionRequest,
    LifecycleTransitionedPayload,
    Rejection,
    RuntimeCommandRequest,
    StrictModel,
)
from arw.reducer import ReducerError, RuntimeState, reduce_events
from arw.workflows import (
    WorkflowDefinitionError,
    actor_can_commit,
    event_category,
    require_transition,
)


class CommandOutcome(StrictModel):
    accepted: bool
    state: RuntimeState
    event: CanonicalEvent | None = None
    rejection: Rejection | None = None

    @model_validator(mode="after")
    def accepted_or_rejected(self) -> "CommandOutcome":
        if self.accepted and (self.event is None or self.rejection is not None):
            raise ValueError("accepted outcomes require only an event")
        if not self.accepted and (self.event is not None or self.rejection is None):
            raise ValueError("rejected outcomes require only a rejection")
        return self


class RuntimeCommandService:
    """The only service allowed to turn validated requests into canonical events."""

    def __init__(self, run_root: Path, *, lock_timeout: float = 0.2) -> None:
        self.run_root = run_root
        self.lock_timeout = lock_timeout

    def read_state(self) -> RuntimeState:
        replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        return reduce_events(replayed.workflow_definition_id, replayed.events)

    @staticmethod
    def _rejection(state: RuntimeState, code: str, message: str) -> CommandOutcome:
        return CommandOutcome(
            accepted=False,
            state=state,
            rejection=Rejection(
                code=code,
                message=message,
                run_id=state.run_id,
                accepted_revision=state.accepted_revision,
                ledger_head_sha256=state.ledger_head_sha256,
                current_passport_sha256=state.current_passport_sha256,
                legal_next_transitions=list(state.legal_next_transitions),
                recovery_health=state.recovery_health,
            ),
        )

    def _execute(
        self,
        request: RuntimeCommandRequest,
        *,
        event_type: str,
        payload_factory,
        prevalidate=None,
    ) -> CommandOutcome:
        with locked_replay(self.run_root, lock_timeout=self.lock_timeout) as (root, replayed):
            state = reduce_events(replayed.workflow_definition_id, replayed.events)
            if request.run_id != replayed.run_id:
                return self._rejection(state, "run-id-mismatch", "request run identity differs")
            if replayed.journal_layout != "segmented-v1":
                return self._rejection(
                    state,
                    "legacy-run-read-only",
                    "Phase 2 mutation requires a segmented journal",
                )
            if request.event_id in replayed.event_ids:
                return self._rejection(state, "duplicate-event-id", "event ID was already accepted")
            if request.command_id in replayed.command_ids:
                return self._rejection(
                    state, "duplicate-command-id", "command ID was already accepted"
                )
            if request.expected_revision != replayed.revision:
                return self._rejection(
                    state,
                    "stale-revision",
                    f"expected revision {request.expected_revision}, accepted {replayed.revision}",
                )
            category = event_category(event_type)
            if not actor_can_commit(request.actor_role, category):
                return self._rejection(
                    state,
                    "unauthorized-actor",
                    f"actor role {request.actor_role!r} cannot commit {category}",
                )
            if prevalidate is not None:
                rejection = prevalidate(state, replayed)
                if rejection is not None:
                    code, message = rejection
                    return self._rejection(state, code, message)
            payload = payload_factory(state, replayed)
            candidate = build_runtime_event(
                replayed,
                event_type=event_type,
                event_id=request.event_id,
                command_id=request.command_id,
                occurred_at=request.occurred_at,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                payload=payload,
            )
            try:
                reduced = reduce_events(
                    replayed.workflow_definition_id,
                    (*replayed.events, candidate),
                )
            except (ReducerError, WorkflowDefinitionError) as error:
                return self._rejection(state, "invalid-command", str(error))
            event, appended = append_runtime_event_unlocked(root, replayed, candidate)
            accepted_state = reduce_events(appended.workflow_definition_id, appended.events)
            if accepted_state != reduced:
                raise JournalError("post-append reducer state differs from validated candidate")
            return CommandOutcome(accepted=True, state=accepted_state, event=event)

    def execute_transition(self, request: LifecycleTransitionRequest) -> CommandOutcome:
        transition_holder = {}

        def validate(state, _replayed):
            if request.from_stage != state.stage:
                return "stale-stage", "request from-stage differs from accepted stage"
            try:
                transition_holder["value"] = require_transition(
                    state.workflow_definition_id, state.stage, request.transition_id
                )
            except WorkflowDefinitionError as error:
                return "invalid-transition", str(error)
            return None

        def payload(state, _replayed):
            transition = transition_holder["value"]
            return LifecycleTransitionedPayload(
                transition_id=transition.transition_id,
                from_stage=state.stage,
                to_stage=transition.to_stage,
            )

        return self._execute(
            request,
            event_type="lifecycle.transitioned",
            payload_factory=payload,
            prevalidate=validate,
        )

    def request_decision(self, request: HumanDecisionRequest) -> CommandOutcome:
        def validate(state, _replayed):
            if any(
                item.decision_id == request.decision_id
                for item in state.pending_human_decisions
            ):
                return "duplicate-decision", "decision ID is already pending"
            unknown = set(request.unlock_transitions) - set(state.legal_next_transitions)
            if unknown:
                return "invalid-decision-transition", "decision names a non-legal transition"
            return None

        return self._execute(
            request,
            event_type="human_decision.requested",
            prevalidate=validate,
            payload_factory=lambda state, _replayed: HumanDecisionRequestedPayload(
                decision_id=request.decision_id,
                blocker_code=request.blocker_code,
                starting_revision=state.accepted_revision,
                allowed_choices=list(request.allowed_choices),
                rationale_required=request.rationale_required,
                source_event_ids=list(request.source_event_ids),
                unlock_transitions=list(request.unlock_transitions),
            ),
        )

    def resolve_decision(self, request: HumanDecisionResolveRequest) -> CommandOutcome:
        def validate(state, _replayed):
            pending = next(
                (
                    item
                    for item in state.pending_human_decisions
                    if item.decision_id == request.decision_id
                ),
                None,
            )
            if pending is None:
                return "unknown-decision", "decision ID is not pending"
            if request.choice not in pending.allowed_choices:
                return "invalid-decision-choice", "choice is not allowed"
            if pending.rationale_required and not request.rationale:
                return "decision-rationale-required", "decision requires a rationale"
            return None

        return self._execute(
            request,
            event_type="human_decision.resolved",
            prevalidate=validate,
            payload_factory=lambda _state, _replayed: HumanDecisionResolvedPayload(
                decision_id=request.decision_id,
                choice=request.choice,
                rationale=request.rationale,
            ),
        )

    def start_attempt(self, request: AttemptStartRequest) -> CommandOutcome:
        def validate(state, _replayed):
            if request.base_revision != state.accepted_revision:
                return "stale-attempt-base", "attempt base revision is not current"
            if any(item.attempt_id == request.attempt_id for item in state.active_attempts):
                return "duplicate-attempt", "attempt ID is already active"
            known_hashes = {
                state.ledger_head_sha256,
                *state.accepted_artifact_manifest_sha256,
                *state.accepted_passport_sha256,
            }
            if any(value not in known_hashes for value in request.consumed_sha256):
                return "stale-consumed-input", "attempt consumes an unknown or stale hash"
            return None

        return self._execute(
            request,
            event_type="attempt.started",
            prevalidate=validate,
            payload_factory=lambda _state, _replayed: AttemptStartedPayload(
                attempt_id=request.attempt_id,
                base_revision=request.base_revision,
                consumed_sha256=list(request.consumed_sha256),
            ),
        )

    def close_attempt(self, request: AttemptCloseRequest) -> CommandOutcome:
        def validate(state, _replayed):
            if not any(item.attempt_id == request.attempt_id for item in state.active_attempts):
                return "unknown-attempt", "attempt ID is not active"
            return None

        return self._execute(
            request,
            event_type="attempt.closed",
            prevalidate=validate,
            payload_factory=lambda _state, _replayed: AttemptClosedPayload(
                attempt_id=request.attempt_id,
                outcome=request.outcome,
                proposal_sha256=request.proposal_sha256,
            ),
        )

    def accept_artifact(self, request: ArtifactAcceptanceRequest) -> CommandOutcome:
        manifest_holder: dict[str, ArtifactManifest] = {}
        digest_holder: dict[str, str] = {}

        def validate(state, _replayed):
            if request.attempt_id is None:
                if request.base_revision != state.accepted_revision:
                    return "stale-artifact-base", "artifact base revision is not current"
            else:
                attempt = next(
                    (
                        item
                        for item in state.active_attempts
                        if item.attempt_id == request.attempt_id
                    ),
                    None,
                )
                if attempt is None:
                    return "stale-artifact-attempt", "artifact attempt is not active"
                if request.base_revision != attempt.base_revision:
                    return "stale-artifact-base", "artifact base differs from its attempt"
                if request.consumed_sha256 != attempt.consumed_sha256:
                    return "stale-consumed-input", "artifact inputs differ from its attempt"
            try:
                validate_content_file(
                    self.run_root, request.content_path, request.content_sha256
                )
            except ManifestError as error:
                return "artifact-content-invalid", str(error)
            manifest = ArtifactManifest(
                schema_version=request.schema_version,
                run_id=request.run_id,
                artifact_id=request.artifact_id,
                artifact_kind=request.artifact_kind,
                media_type=request.media_type,
                content_path=request.content_path,
                content_sha256=request.content_sha256,
                producer_id=request.actor_id,
                attempt_id=request.attempt_id,
                base_revision=request.base_revision,
                consumed_sha256=list(request.consumed_sha256),
                created_at=request.occurred_at,
            )
            try:
                installed = install_artifact_manifest(self.run_root, manifest)
            except ManifestError as error:
                return "artifact-manifest-invalid", str(error)
            manifest_holder["value"] = manifest
            digest_holder["value"] = installed.stem
            return None

        return self._execute(
            request,
            event_type="artifact.accepted",
            prevalidate=validate,
            payload_factory=lambda _state, _replayed: ArtifactAcceptedPayload(
                artifact_id=request.artifact_id,
                manifest_sha256=digest_holder["value"],
                artifact_sha256=request.content_sha256,
                attempt_id=request.attempt_id,
            ),
        )
