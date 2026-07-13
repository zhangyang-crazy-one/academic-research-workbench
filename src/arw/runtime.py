"""Sole-writer replay, validation, and canonical append transactions."""

from __future__ import annotations

import os
import signal
from datetime import UTC, datetime
from pathlib import Path

from pydantic import model_validator

from arw.journal import (
    JournalError,
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
    publish_recovery_event_unlocked,
    replay_run,
)
from arw.manifests import (
    ManifestError,
    install_artifact_manifest,
    install_material_passport,
    load_material_passport,
    validate_accepted_event_manifests,
    validate_content_file,
    write_passport_pointer,
)
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
    MaterialPassport,
    PassportAcceptedPayload,
    PassportAttemptSnapshot,
    PassportDecisionSnapshot,
    PassportPointer,
    CheckpointRequest,
    Rejection,
    RecoveryCompletedPayload,
    RecoveryRequest,
    ResumeAcceptedPayload,
    ResumeRequest,
    RuntimeCommandRequest,
    StrictModel,
)
from arw.recovery import (
    RecoveryError,
    load_recovery_receipt,
    prepare_recovery_evidence,
)
from arw.reducer import ReducerError, RuntimeState, reduce_events
from arw.workflows import (
    WorkflowDefinitionError,
    actor_can_commit,
    event_category,
    require_transition,
    require_workflow,
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

    def read_state(self, *, now: datetime | None = None) -> RuntimeState:
        replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        return reduce_events(
            replayed.workflow_definition_id,
            replayed.events,
            now=now,
            recovery_health=replayed.recovery_health,
        )

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
        after_append=None,
        now: datetime | None = None,
    ) -> CommandOutcome:
        effective_now = now or datetime.strptime(
            request.occurred_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        with locked_replay(self.run_root, lock_timeout=self.lock_timeout) as (root, replayed):
            state = reduce_events(
                replayed.workflow_definition_id,
                replayed.events,
                now=effective_now,
                recovery_health=replayed.recovery_health,
            )
            if request.run_id != replayed.run_id:
                return self._rejection(state, "run-id-mismatch", "request run identity differs")
            if replayed.journal_layout != "segmented-v1":
                return self._rejection(
                    state,
                    "legacy-run-read-only",
                    "Phase 2 mutation requires a segmented journal",
                )
            if replayed.recovery_health != "healthy":
                code = (
                    "recovery-required"
                    if replayed.recovery_health == "recoverable_tail"
                    else "recovery-blocked"
                )
                return self._rejection(
                    state,
                    code,
                    replayed.recovery_message or "journal recovery health is not healthy",
                )
            validate_accepted_event_manifests(root, replayed.events)
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
            if category == "lifecycle" and any(
                item.code == "evidence-expired" for item in state.blockers
            ):
                return self._rejection(
                    state, "evidence-expired", "expired Passport evidence blocks transitions"
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
                    now=effective_now,
                )
            except (ReducerError, WorkflowDefinitionError) as error:
                return self._rejection(state, "invalid-command", str(error))
            event, appended = append_runtime_event_unlocked(root, replayed, candidate)
            accepted_state = reduce_events(
                appended.workflow_definition_id,
                appended.events,
                now=effective_now,
            )
            if accepted_state != reduced:
                raise JournalError("post-append reducer state differs from validated candidate")
            if after_append is not None:
                after_append(accepted_state, event)
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

    def create_checkpoint(self, request: CheckpointRequest) -> CommandOutcome:
        digest_holder: dict[str, str] = {}

        def validate(state, replayed):
            coherent = request.checkpoint_kind == "explicit"
            if request.checkpoint_kind == "stage_handoff" and replayed.events:
                last = replayed.events[-1]
                if last.event_type == "lifecycle.transitioned" and isinstance(
                    last.payload, LifecycleTransitionedPayload
                ):
                    transition = require_transition(
                        state.workflow_definition_id,
                        last.payload.from_stage,
                        last.payload.transition_id,
                    )
                    coherent = transition.coherent_checkpoint
            elif request.checkpoint_kind == "human_decision" and replayed.events:
                coherent = replayed.events[-1].event_type == "human_decision.resolved"
            elif request.checkpoint_kind == "recovery" and replayed.events:
                coherent = replayed.events[-1].event_type == "recovery.completed" and isinstance(
                    replayed.events[-1].payload, RecoveryCompletedPayload
                )
            if not coherent:
                return "incoherent-checkpoint", "checkpoint kind does not match the boundary"
            workflow = require_workflow(state.workflow_definition_id)
            passport = MaterialPassport(
                schema_version="1.0.0",
                run_id=state.run_id,
                workflow_definition_id=state.workflow_definition_id,
                workflow_definition_sha256=workflow.sha256,
                based_on_revision=state.accepted_revision,
                ledger_head_sha256=state.ledger_head_sha256,
                stage=state.stage,
                checkpoint_kind=request.checkpoint_kind,
                parent_passport_sha256=state.current_passport_sha256,
                supersedes_passport_sha256=state.current_passport_sha256,
                accepted_artifact_manifest_sha256=list(
                    state.accepted_artifact_manifest_sha256
                ),
                pending_human_decisions=[
                    PassportDecisionSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in state.pending_human_decisions
                ],
                active_attempts=[
                    PassportAttemptSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in state.active_attempts
                ],
                fresh_until=request.fresh_until,
                created_at=request.occurred_at,
                created_by=request.actor_id,
            )
            try:
                installed = install_material_passport(self.run_root, passport)
            except ManifestError as error:
                return "passport-manifest-invalid", str(error)
            digest_holder["value"] = installed.stem
            return None

        def after_append(state, _event):
            if os.environ.get("ARW_TEST_FAILPOINT") == "post-passport-event-pre-pointer-sigkill":
                os.kill(os.getpid(), signal.SIGKILL)
            write_passport_pointer(
                self.run_root,
                PassportPointer(
                    run_id=state.run_id,
                    passport_sha256=digest_holder["value"],
                    accepted_revision=state.accepted_revision,
                    ledger_head_sha256=state.ledger_head_sha256,
                ),
            )

        return self._execute(
            request,
            event_type="passport.accepted",
            prevalidate=validate,
            payload_factory=lambda state, _replayed: PassportAcceptedPayload(
                passport_sha256=digest_holder["value"],
                parent_passport_sha256=state.current_passport_sha256,
                supersedes_passport_sha256=state.current_passport_sha256,
                checkpoint_kind=request.checkpoint_kind,
                based_on_revision=state.accepted_revision,
                stage=state.stage,
                fresh_until=request.fresh_until,
            ),
            after_append=after_append,
        )

    def resume(self, request: ResumeRequest) -> CommandOutcome:
        now = datetime.strptime(request.occurred_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )

        def validate(state, _replayed):
            if state.current_passport_sha256 != request.passport_sha256:
                return "stale-passport", "resume Passport is not current"
            if request.passport_sha256 in state.consumed_passport_sha256:
                return "passport-consumed", "resume Passport was already consumed"
            if any(item.code == "evidence-expired" for item in state.blockers):
                return "evidence-expired", "Passport evidence is expired"
            try:
                passport = load_material_passport(self.run_root, request.passport_sha256)
            except ManifestError as error:
                return "passport-invalid", str(error)
            if passport.run_id != state.run_id or passport.stage != state.stage:
                return "passport-invalid", "Passport does not match accepted run state"
            return None

        return self._execute(
            request,
            event_type="resume.accepted",
            prevalidate=validate,
            payload_factory=lambda _state, _replayed: ResumeAcceptedPayload(
                passport_sha256=request.passport_sha256
            ),
            now=now,
        )

    def rebuild_passport_pointer(self) -> PassportPointer:
        with locked_replay(self.run_root, lock_timeout=self.lock_timeout) as (root, replayed):
            validate_accepted_event_manifests(root, replayed.events)
            state = reduce_events(replayed.workflow_definition_id, replayed.events)
            if state.current_passport_sha256 is None:
                raise JournalError("run has no accepted Passport")
            accepted_event = next(
                event
                for event in reversed(replayed.events)
                if event.event_type == "passport.accepted"
                and isinstance(event.payload, PassportAcceptedPayload)
                and event.payload.passport_sha256 == state.current_passport_sha256
            )
            pointer = PassportPointer(
                run_id=state.run_id,
                passport_sha256=state.current_passport_sha256,
                accepted_revision=accepted_event.resulting_revision,
                ledger_head_sha256=accepted_event.event_sha256,
            )
            write_passport_pointer(root, pointer)
            return pointer

    def recover(self, request: RecoveryRequest) -> CommandOutcome:
        """Quarantine one terminal tail and continue in a recovery-first segment."""

        with locked_replay(self.run_root, lock_timeout=self.lock_timeout) as (root, replayed):
            state = reduce_events(
                replayed.workflow_definition_id,
                replayed.events,
                recovery_health=replayed.recovery_health,
            )
            existing = [
                event
                for event in replayed.events
                if event.event_id == request.event_id
                or event.command_id == request.command_id
                or (
                    event.event_type == "recovery.completed"
                    and isinstance(event.payload, RecoveryCompletedPayload)
                    and event.payload.recovery_id == request.recovery_id
                )
            ]
            if existing:
                event = existing[-1]
                if event.event_type == "recovery.completed" and isinstance(
                    event.payload, RecoveryCompletedPayload
                ):
                    try:
                        receipt = load_recovery_receipt(root, request.recovery_id)
                    except RecoveryError as error:
                        return self._rejection(state, "recovery-blocked", str(error))
                    exact = (
                        event.event_id == request.event_id
                        and event.command_id == request.command_id
                        and event.run_id == request.run_id
                        and event.expected_revision == request.expected_revision
                        and event.prev_event_sha256 == request.expected_head_sha256
                        and event.occurred_at == request.occurred_at
                        and event.actor_id == request.actor_id
                        and event.actor_role == request.actor_role
                        and event.payload.recovery_id == request.recovery_id
                        and event.payload.original_segment_sha256
                        == request.original_segment_sha256
                        and event.payload.reason_code == request.reason_code
                        and receipt.reason_text == request.reason_text
                    )
                    if exact and replayed.recovery_health == "healthy":
                        return CommandOutcome(accepted=True, state=state, event=event)
                return self._rejection(
                    state,
                    "conflicting-recovery",
                    "recovery identity already exists with different evidence",
                )
            if request.run_id != replayed.run_id:
                return self._rejection(state, "run-id-mismatch", "request run identity differs")
            if replayed.journal_layout != "segmented-v1":
                return self._rejection(
                    state, "legacy-run-read-only", "recovery requires a segmented journal"
                )
            if not actor_can_commit(request.actor_role, "recovery"):
                return self._rejection(
                    state,
                    "unauthorized-actor",
                    "only an operator can commit recovery",
                )
            if replayed.recovery_health == "blocked":
                return self._rejection(
                    state,
                    "recovery-blocked",
                    replayed.recovery_message or "journal corruption is not recoverable",
                )
            if replayed.recovery_health != "recoverable_tail":
                return self._rejection(
                    state, "recovery-not-required", "journal has no recoverable terminal tail"
                )
            if request.expected_revision != replayed.revision:
                return self._rejection(
                    state,
                    "stale-revision",
                    f"expected revision {request.expected_revision}, accepted {replayed.revision}",
                )
            if request.expected_head_sha256 != replayed.last_event_sha256:
                return self._rejection(
                    state, "stale-ledger-head", "request head differs from the trustworthy prefix"
                )
            damaged = replayed.segments[-1]
            if request.original_segment_sha256 != damaged.sha256:
                return self._rejection(
                    state,
                    "stale-segment",
                    "request segment digest differs from the classified damaged segment",
                )
            try:
                prepared = prepare_recovery_evidence(root, request, replayed)
                event = build_runtime_event(
                    replayed,
                    event_type="recovery.completed",
                    event_id=request.event_id,
                    command_id=request.command_id,
                    occurred_at=request.occurred_at,
                    actor_id=request.actor_id,
                    actor_role=request.actor_role,
                    payload=RecoveryCompletedPayload(
                        recovery_id=request.recovery_id,
                        prior_valid_revision=replayed.revision,
                        prior_valid_head_sha256=replayed.last_event_sha256,
                        original_segment_sha256=damaged.sha256,
                        original_segment_byte_count=damaged.byte_count,
                        quarantine_sha256=prepared.raw_sha256,
                        quarantine_receipt_sha256=prepared.receipt_sha256,
                        fault_offset=damaged.fault_offset,
                        fault_class=damaged.fault_class,
                        reason_code=request.reason_code,
                    ),
                )
                reduced = reduce_events(
                    replayed.workflow_definition_id,
                    (*replayed.events, event),
                    recovery_health="healthy",
                )
                accepted_event, appended = publish_recovery_event_unlocked(
                    root, replayed, event
                )
            except (JournalError, RecoveryError, ReducerError) as error:
                return self._rejection(state, "recovery-failed", str(error))
            accepted_state = reduce_events(
                appended.workflow_definition_id,
                appended.events,
                recovery_health=appended.recovery_health,
            )
            if accepted_state != reduced:
                raise JournalError("post-recovery state differs from validated candidate")
            return CommandOutcome(
                accepted=True,
                state=accepted_state,
                event=accepted_event,
            )
