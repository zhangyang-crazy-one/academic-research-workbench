"""Sole-writer replay, validation, and canonical append transactions."""

from __future__ import annotations

import logging
import os
import signal
from datetime import UTC, datetime
from pathlib import Path

from pydantic import model_validator

from arw.kernel.ledger.execution_provenance import (
    ExecutionProvenanceState,
    project_execution_provenance,
)
from arw.kernel.ledger.journal import (
    JournalError,
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
    publish_recovery_event_unlocked,
    replay_run,
)
from arw.kernel.ledger.manifests import (
    ManifestError,
    install_artifact_manifest,
    install_material_passport,
    load_artifact_manifest,
    load_material_passport,
    validate_accepted_event_manifests,
    validate_content_file,
    write_passport_pointer,
)
from arw.kernel.ledger.recovery import (
    RecoveryError,
    load_recovery_receipt,
    prepare_recovery_evidence,
)
from arw.kernel.ledger.reducer import ReducerError, RuntimeState, reduce_events
from arw.kernel.ledger.workflows import (
    WorkflowDefinitionError,
    actor_can_commit,
    event_category,
    require_transition,
    require_workflow,
)
from arw.kernel.state.models import (
    PHASE4_EVENT_PAYLOAD_TYPES,
    PHASE4_EVENT_TYPES,
    ArtifactAcceptanceRequest,
    ArtifactAcceptedPayload,
    ArtifactManifest,
    AttemptClosedPayload,
    AttemptCloseRequest,
    AttemptStartedPayload,
    AttemptStartRequest,
    CanonicalEvent,
    CheckpointRequest,
    DatasetMetadataAcceptedPayload,
    ExecutionActionFinishedPayload,
    ExecutionActionStartedPayload,
    ExecutionArtifactBoundPayload,
    ExecutionContextAcceptedPayload,
    ExperimentProvenanceAcceptedPayload,
    HumanDecisionRequest,
    HumanDecisionRequestedPayload,
    HumanDecisionResolvedPayload,
    HumanDecisionResolveRequest,
    LifecycleTransitionedPayload,
    LifecycleTransitionRequest,
    MaterialPassport,
    PassportAcceptedPayload,
    PassportAttemptSnapshot,
    PassportDecisionSnapshot,
    PassportPointer,
    RecoveryCompletedPayload,
    RecoveryRequest,
    Rejection,
    ResumeAcceptedPayload,
    ResumeRequest,
    RunManifest,
    RuntimeCommandRequest,
    StrictModel,
)

_logger = logging.getLogger("arw.kernel.execution.runtime")
_MAX_SUBMISSION_JSON_BYTES = 256 * 1024


def _discard_orphan(root: Path, relative: str, digest: str | None) -> None:
    """Remove one unreferenced content-addressed manifest after a failed accept.

    The writer lock is held for the whole ``_execute`` transaction, so the
    digest can only name a file installed by the current attempt or by a
    previously failed attempt; no accepted event can reference it.
    """

    if digest is None:
        return
    try:
        (root / relative / f"{digest}.json").unlink(missing_ok=True)
    except OSError as error:
        _logger.warning(
            "could not remove orphaned manifest %s/%s.json: %s",
            relative,
            digest,
            error,
        )


class CommandOutcome(StrictModel):
    accepted: bool
    state: RuntimeState
    event: CanonicalEvent | None = None
    rejection: Rejection | None = None

    @model_validator(mode="after")
    def accepted_or_rejected(self) -> CommandOutcome:
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

    def read_execution_provenance(self) -> ExecutionProvenanceState:
        replayed = replay_run(self.run_root, lock_timeout=self.lock_timeout)
        if replayed.recovery_health != "healthy":
            raise JournalError(
                replayed.recovery_message or "execution provenance replay is blocked"
            )
        # The normal reducer performs the same semantic checks on cold replay.
        reduce_events(replayed.workflow_definition_id, replayed.events)
        return project_execution_provenance(replayed.events)

    def _append_execution_provenance(
        self,
        request: RuntimeCommandRequest,
        event_type: str,
        payload: StrictModel,
        *,
        prevalidate=None,
    ) -> CommandOutcome:
        return self._execute(
            request,
            event_type=event_type,
            payload_factory=lambda _state, _replayed: payload,
            prevalidate=prevalidate,
        )

    def accept_execution_context(
        self,
        request: RuntimeCommandRequest,
        context: ExecutionContextAcceptedPayload | dict,
    ) -> CommandOutcome:
        payload = ExecutionContextAcceptedPayload.model_validate(context)
        return self._append_execution_provenance(
            request, "execution_provenance.context_accepted", payload
        )

    def accept_dataset_metadata(
        self,
        request: RuntimeCommandRequest,
        metadata: DatasetMetadataAcceptedPayload | dict,
    ) -> CommandOutcome:
        payload = DatasetMetadataAcceptedPayload.model_validate(metadata)
        return self._append_execution_provenance(
            request, "execution_provenance.dataset_metadata_accepted", payload
        )

    def start_execution_action(
        self,
        request: RuntimeCommandRequest,
        action: ExecutionActionStartedPayload | dict,
    ) -> CommandOutcome:
        payload = ExecutionActionStartedPayload.model_validate(action)
        return self._append_execution_provenance(
            request, "execution_provenance.action_started", payload
        )

    def finish_execution_action(
        self,
        request: RuntimeCommandRequest,
        observation: ExecutionActionFinishedPayload | dict,
    ) -> CommandOutcome:
        payload = ExecutionActionFinishedPayload.model_validate(observation)
        return self._append_execution_provenance(
            request, "execution_provenance.action_finished", payload
        )

    def bind_execution_artifact(
        self,
        request: RuntimeCommandRequest,
        binding: ExecutionArtifactBoundPayload | dict,
    ) -> CommandOutcome:
        payload = ExecutionArtifactBoundPayload.model_validate(binding)

        def validate(_state: RuntimeState, replayed):
            try:
                source = next(
                    (
                        e
                        for e in replayed.events
                        if e.event_id == payload.source_event_id
                    ),
                    None,
                )
                if source is None or source.event_sha256 != payload.source_event_sha256:
                    return "invalid-binding", "source event is missing or stale"
                if payload.source_kind == "run_input":
                    manifest = RunManifest.model_validate_json(
                        (self.run_root / "run-manifest.json").read_bytes()
                    )
                    if (
                        manifest.run_id != request.run_id
                        or source.event_type != "run.initialized"
                        or manifest.immutable_input.path != payload.relative_path
                        or manifest.immutable_input.sha256 != payload.content_sha256
                        or source.payload.manifest_sha256
                        != payload.source_manifest_sha256
                    ):
                        return (
                            "invalid-binding",
                            "run input differs from immutable manifest",
                        )
                    path = validate_content_file(
                        self.run_root,
                        payload.relative_path,
                        payload.content_sha256,
                        expected_byte_count=payload.byte_count,
                    )
                elif payload.source_kind == "proposal":
                    if source.event_type != "proposal.accepted":
                        return "invalid-binding", "proposal was not accepted"
                    path = validate_content_file(
                        self.run_root,
                        f"attempts/{payload.attempt_id}/result/{payload.relative_path}",
                        payload.content_sha256,
                        expected_byte_count=payload.byte_count,
                    )
                else:
                    if source.event_type != "artifact.accepted":
                        return "invalid-binding", "artifact was not accepted"
                    manifest = load_artifact_manifest(
                        self.run_root, payload.source_manifest_sha256
                    )
                    if (
                        manifest.run_id != request.run_id
                        or manifest.content_path != payload.relative_path
                        or manifest.content_sha256 != payload.content_sha256
                    ):
                        return (
                            "invalid-binding",
                            "artifact differs from accepted manifest",
                        )
                    path = validate_content_file(
                        self.run_root,
                        payload.relative_path,
                        payload.content_sha256,
                        expected_byte_count=payload.byte_count,
                    )
                if path.stat().st_size != payload.byte_count:
                    return (
                        "invalid-binding",
                        "artifact byte count differs from accepted source",
                    )
            except (OSError, ValueError, ManifestError) as error:
                return "invalid-binding", str(error)
            return None

        return self._append_execution_provenance(
            request,
            "execution_provenance.artifact_bound",
            payload,
            prevalidate=validate,
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
        rollback=None,
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
                if rollback is not None:
                    rollback()
                return self._rejection(state, "invalid-command", str(error))
            try:
                event, appended = append_runtime_event_unlocked(root, replayed, candidate)
            except JournalError:
                if rollback is not None:
                    rollback()
                raise
            accepted_state = reduce_events(
                appended.workflow_definition_id,
                appended.events,
                now=effective_now,
            )
            if accepted_state != reduced:
                # The event is durable here, so the candidate's manifest must stay.
                raise JournalError("post-append reducer state differs from validated candidate")
            if after_append is not None:
                after_append(accepted_state, event)
            return CommandOutcome(accepted=True, state=accepted_state, event=event)

    def execute_transition(
        self,
        request: LifecycleTransitionRequest,
        *,
        additional_prevalidate=None,
    ) -> CommandOutcome:
        transition_holder = {}

        def validate(state, _replayed):
            if state.blockers:
                return "runtime-blocked", "accepted blockers prevent lifecycle transitions"
            if request.from_stage != state.stage:
                return "stale-stage", "request from-stage differs from accepted stage"
            try:
                transition_holder["value"] = require_transition(
                    state.workflow_definition_id, state.stage, request.transition_id
                )
            except WorkflowDefinitionError as error:
                return "invalid-transition", str(error)
            if additional_prevalidate is not None:
                rejection = additional_prevalidate(state, _replayed)
                if rejection is not None:
                    return rejection
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

    def append_phase4_event(
        self,
        request: RuntimeCommandRequest,
        *,
        event_type: str,
        payload: StrictModel,
        prevalidate=None,
    ) -> CommandOutcome:
        """Append one parent-authored Phase 4 event through the normal gate.

        The caller supplies an already validated immutable payload, but it does
        not supply sequence, revision, hash-chain, actor, or journal fields.
        Those remain owned by ``_execute`` and the reducer.
        """

        if event_type not in PHASE4_EVENT_TYPES:
            raise ValueError(f"not a registered Phase 4 event: {event_type}")
        expected_type = PHASE4_EVENT_PAYLOAD_TYPES[event_type]
        if not isinstance(payload, expected_type):
            raise TypeError(
                f"{event_type} requires {expected_type.__name__}, got {type(payload).__name__}"
            )
        return self._execute(
            request,
            event_type=event_type,
            payload_factory=lambda _state, _replayed: payload,
            prevalidate=prevalidate,
        )

    def append_experiment_provenance(
        self,
        request: RuntimeCommandRequest,
        *,
        provenance_id: str,
        experiment_id: str,
        provenance_sha256: str,
    ) -> CommandOutcome:
        """Accept one parent-validated external provenance manifest.

        The manifest is published separately by ``ingest_experiment_provenance``;
        this method owns only the hash-chained acceptance event and performs no
        subprocess or producer-authority inference.
        """

        payload = ExperimentProvenanceAcceptedPayload(
            provenance_id=provenance_id,
            experiment_id=experiment_id,
            provenance_sha256=provenance_sha256,
        )
        return self.append_phase4_event(
            request,
            event_type="experiment.provenance.accepted",
            payload=payload,
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
        digest_holder: dict[str, str] = {}

        def validate(state, replayed):
            if any(
                event.event_type in {"artifact.accepted", "research_artifact_accepted"}
                and isinstance(event.payload, ArtifactAcceptedPayload)
                and event.payload.artifact_id == request.artifact_id
                for event in replayed.events
            ):
                return "duplicate-artifact", "artifact ID was already accepted"
            if request.attempt_id is None:
                if request.base_revision != state.accepted_revision:
                    return "stale-artifact-base", "artifact base revision is not current"
                known_hashes = {
                    state.ledger_head_sha256,
                    *state.accepted_artifact_manifest_sha256,
                    *state.accepted_passport_sha256,
                }
                if any(value not in known_hashes for value in request.consumed_sha256):
                    return "stale-consumed-input", "artifact consumes an unknown hash"
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
            submission_error = self._validate_submission_artifact(request, replayed, state)
            if submission_error is not None:
                return submission_error
            if request.artifact_kind in {"reference-record", "reference-use", "citation-check-receipt"}:
                from arw.kernel.policy.citations import validate_citation_artifact
                try:
                    validate_citation_artifact(self.run_root, request, replayed.events)
                except (ValueError, RuntimeError, OSError) as error:
                    return "citation-artifact-invalid", str(error)
            if request.artifact_kind == "provenance-record":
                from arw.kernel.core.canonical import strict_json_loads
                from arw.kernel.ledger.source_locations import (
                    read_retained_bytes,
                    validate_precise_provenance,
                )
                try:
                    raw = read_retained_bytes(self.run_root, request.content_path, max_bytes=65_536)
                    from arw.kernel.core.canonical import sha256_hex
                    if sha256_hex(raw) != request.content_sha256:
                        return "source-locator-invalid", "provenance changed during validation"
                    payload = strict_json_loads(raw)
                    if isinstance(payload, dict) and payload.get("schema_version") == "2.0.0":
                        if request.media_type != "application/json":
                            return "source-locator-invalid", "precise provenance requires application/json"
                        validate_precise_provenance(self.run_root, raw, replayed.events, artifact_id=request.artifact_id)
                except (ValueError, RuntimeError) as error:
                    return "source-locator-invalid", str(error)
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
            digest_holder["value"] = installed.stem
            return None

        def rollback():
            _discard_orphan(
                self.run_root, "manifests/artifacts/sha256", digest_holder.get("value")
            )

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
            rollback=rollback,
        )

    def _validate_submission_artifact(self, request, replayed, state):
        """Validate reserved submission kinds before generic artifact admission."""

        from arw.kernel.core.canonical import strict_json_loads
        from arw.kernel.execution.submission import (
            SUBMISSION_ARTIFACT_MODELS,
            SubmissionWorkflowError,
            validate_submission_payload,
        )
        from arw.kernel.ledger.source_locations import read_retained_bytes
        from arw.kernel.state.submission import (
            JournalRequirementsSnapshot,
            ReviewResponse,
            ReviewRound,
            SubmissionCheckReport,
            SubmissionPacket,
            SubmissionResultObservation,
            SubmissionVerifierObservation,
            confirmation_gate_id,
            response_subject_sha256,
        )

        model_type = SUBMISSION_ARTIFACT_MODELS.get(request.artifact_kind)
        if model_type is None:
            return None
        try:
            raw = read_retained_bytes(
                self.run_root,
                request.content_path,
                max_bytes=_MAX_SUBMISSION_JSON_BYTES,
            )
            value = validate_submission_payload(request.artifact_kind, raw)
        except (ManifestError, OSError, ValueError, UnicodeError, SubmissionWorkflowError) as error:
            return "submission-contract-invalid", str(error)[:2048]
        if getattr(value, "run_id", request.run_id) != request.run_id:
            return "submission-run-mismatch", "submission payload run_id differs from request"

        accepted: dict[str, tuple[str, str, str]] = {}
        accepted_kinds: dict[str, str] = {}
        packets: dict[str, list[tuple[int, str]]] = {}
        packet_values: dict[str, list[tuple[int, str, SubmissionPacket]]] = {}
        review_comments: dict[str, set[str]] = {}
        review_comment_rounds: dict[tuple[str, str], int] = {}
        response_records: dict[str, tuple[str, str, str, str]] = {}
        response_heads: dict[tuple[str, str], tuple[str, str, ReviewResponse]] = {}
        accepted_content_sha256: set[str] = set()
        accepted_manifest_sha256: set[str] = set()
        accepted_manifests: dict[str, ArtifactManifest] = {}
        accepted_content_kinds: dict[str, set[str]] = {}
        for event in replayed.events:
            if event.event_type != "artifact.accepted" or not isinstance(
                event.payload, ArtifactAcceptedPayload
            ):
                continue
            try:
                manifest = load_artifact_manifest(
                    self.run_root, event.payload.manifest_sha256
                )
            except ManifestError:
                continue
            accepted[event.payload.artifact_id] = (
                event.payload.manifest_sha256,
                event.payload.artifact_sha256,
                event.event_id,
            )
            accepted_kinds[event.payload.artifact_id] = manifest.artifact_kind
            accepted_content_sha256.add(event.payload.artifact_sha256)
            accepted_manifest_sha256.add(event.payload.manifest_sha256)
            accepted_manifests[event.payload.manifest_sha256] = manifest
            accepted_content_kinds.setdefault(event.payload.artifact_sha256, set()).add(
                manifest.artifact_kind
            )
            if manifest.artifact_kind in {"submission-packet", "submission-review-round"}:
                try:
                    previous = validate_submission_payload(
                        manifest.artifact_kind,
                        read_retained_bytes(
                            self.run_root,
                            manifest.content_path,
                            max_bytes=_MAX_SUBMISSION_JSON_BYTES,
                        ),
                    )
                except (ManifestError, OSError, ValueError, UnicodeError):
                    continue
                if isinstance(previous, SubmissionPacket):
                    packets.setdefault(previous.submission_id, []).append(
                        (previous.packet_version, event.payload.manifest_sha256)
                    )
                    packet_values.setdefault(previous.submission_id, []).append(
                        (
                            previous.packet_version,
                            event.payload.manifest_sha256,
                            previous,
                        )
                    )
                if isinstance(previous, ReviewRound):
                    review_comments.setdefault(previous.submission_id, set()).update(
                        item.comment_id for item in previous.comments
                    )
                    for item in previous.comments:
                        review_comment_rounds[(previous.submission_id, item.comment_id)] = (
                            item.round_number
                        )
            if manifest.artifact_kind == "submission-response":
                try:
                    response = validate_submission_payload(
                        manifest.artifact_kind,
                        read_retained_bytes(
                            self.run_root,
                            manifest.content_path,
                            max_bytes=_MAX_SUBMISSION_JSON_BYTES,
                        ),
                    )
                except (ManifestError, OSError, ValueError, UnicodeError):
                    continue
                if isinstance(response, ReviewResponse):
                    response_records[response.response_id] = (
                        response.submission_id,
                        response.comment_id,
                        event.payload.manifest_sha256,
                        event.event_id,
                    )
                    response_heads[(response.submission_id, response.comment_id)] = (
                        response.response_id,
                        event.payload.manifest_sha256,
                        response,
                    )

        def require_reference(reference, *, expected_kind: str | None = None):
            found = accepted.get(reference.artifact_id)
            if found is None:
                return "submission-reference-unknown", (
                    f"submission reference is not accepted: {reference.artifact_id}"
                )
            if (
                found[0] != reference.manifest_sha256
                or found[1] != reference.content_sha256
                or found[2] != reference.accepting_event_id
            ):
                return "submission-reference-digest-mismatch", (
                    f"submission reference digest mismatch: {reference.artifact_id}"
                )
            if expected_kind is not None and accepted_kinds.get(reference.artifact_id) != expected_kind:
                return "submission-reference-kind-mismatch", (
                    f"submission reference kind mismatch: {reference.artifact_id}"
                )
            return None

        def require_packet(submission_id: str, packet_manifest: str | None = None):
            candidates = packets.get(submission_id, [])
            if not candidates:
                return "submission-packet-unknown", "submission has no accepted packet"
            if packet_manifest is not None and packet_manifest not in {
                item[1] for item in candidates
            }:
                return "submission-packet-unknown", "referenced packet manifest is not accepted"
            return None

        def read_accepted_json(manifest_sha256: str, *, label: str):
            manifest = accepted_manifests.get(manifest_sha256)
            if manifest is None:
                return None, ("submission-reference-unknown", f"{label} is not accepted")
            try:
                raw_value = read_retained_bytes(
                    self.run_root,
                    manifest.content_path,
                    max_bytes=_MAX_SUBMISSION_JSON_BYTES,
                )
                return strict_json_loads(raw_value), None
            except (ManifestError, OSError, UnicodeError, ValueError) as error:
                return None, ("submission-evidence-invalid", f"{label} is invalid: {error}")

        def parse_patch_scope(scope_text: str):
            try:
                scope = strict_json_loads(scope_text.encode("utf-8"))
            except (UnicodeError, ValueError) as error:
                return None, ("submission-patch-scope-invalid", f"approved patch scope is invalid: {error}")
            if not isinstance(scope, dict):
                return None, ("submission-patch-scope-invalid", "approved patch scope must be a JSON object")
            required = {"operation_mode", "block_ids", "operations", "roadmap_item_ids", "comment_ids"}
            if set(scope) != required:
                return None, ("submission-patch-scope-invalid", "approved patch scope has an unexpected shape")
            if scope.get("operation_mode") not in {"ars_markdown_patch", "external_evidence", "automatic_word_patch", "automatic_pdf_remap"}:
                return None, ("submission-patch-scope-invalid", "approved patch scope has an unknown operation mode")
            arrays = {}
            for name in ("block_ids", "operations", "roadmap_item_ids", "comment_ids"):
                raw_values = scope.get(name)
                if not isinstance(raw_values, list) or not raw_values or any(
                    not isinstance(item, str) or not item or len(item) > 160 for item in raw_values
                ) or len(raw_values) != len(set(raw_values)):
                    return None, ("submission-patch-scope-invalid", f"approved patch scope field {name} is invalid")
                arrays[name] = set(raw_values)
            return (scope, arrays), None

        def validate_patch_report(value, current_packet, report, block_manifest, patch_document):
            if not isinstance(report, dict) or report.get("report_format_version") != "1.3" or report.get("mode") != "patch":
                return "submission-patch-report-invalid", "apply report is not a current ARS patch report"
            if not isinstance(block_manifest, dict) or block_manifest.get("manifest_format_version") != "1.0":
                return "submission-patch-manifest-invalid", "block manifest is not a current ARS block manifest"
            blocks = block_manifest.get("blocks")
            if not isinstance(blocks, list) or not blocks:
                return "submission-patch-manifest-invalid", "block manifest has no blocks"
            block_ids = [item.get("block_id") for item in blocks if isinstance(item, dict)]
            if len(block_ids) != len(blocks) or len(block_ids) != len(set(block_ids)):
                return "submission-patch-manifest-invalid", "block manifest block IDs are invalid"
            if any(
                not isinstance(item.get("block_id"), str)
                or not item["block_id"].startswith("B")
                or not item["block_id"][1:].isdigit()
                or len(item["block_id"]) < 5
                or not isinstance(item.get("old_hash"), str)
                or len(item["old_hash"]) != 12
                or any(character not in "0123456789abcdef" for character in item["old_hash"])
                for item in blocks
                if isinstance(item, dict)
            ):
                return "submission-patch-manifest-invalid", "block manifest entries are malformed"
            base_hash = report.get("base_draft_hash")
            output_hash = report.get("output_draft_hash")
            if not isinstance(base_hash, str) or len(base_hash) != 12 or not all(c in "0123456789abcdef" for c in base_hash):
                return "submission-patch-report-invalid", "apply report base hash is invalid"
            if not isinstance(output_hash, str) or len(output_hash) != 12 or not all(c in "0123456789abcdef" for c in output_hash):
                return "submission-patch-report-invalid", "apply report output hash is invalid"
            if not current_packet.manuscript.content_sha256.startswith(base_hash):
                return "submission-patch-base-stale", "apply report base hash does not match the current manuscript"
            if not value.patch.candidate_manuscript_sha256.startswith(output_hash):
                return "submission-patch-candidate-mismatch", "apply report output hash does not match the candidate manuscript"
            if report.get("revision_round") != value.round_number:
                return "submission-patch-round-mismatch", "apply report round differs from the response round"
            witness = report.get("authorization_witness")
            if not isinstance(witness, dict) or witness.get("status") != "pass":
                return "submission-patch-authorization-invalid", "apply report lacks a passing authorization witness"
            ops = report.get("ops_applied")
            if not isinstance(ops, list) or not ops:
                return "submission-patch-report-invalid", "apply report has no applied operations"
            parsed_scope, scope_error = parse_patch_scope(value.patch.approved_scope)
            if scope_error:
                return scope_error
            _scope, allowed = parsed_scope
            if value.patch.comment_ids[0] not in allowed["comment_ids"] or not set(value.patch.comment_ids) <= allowed["comment_ids"]:
                return "submission-patch-scope-mismatch", "patch comments exceed the approved scope"
            if value.patch.base_manuscript_sha256 != current_packet.manuscript.content_sha256:
                return "submission-patch-base-stale", "patch base does not match the current manuscript"
            for item in ops:
                if not isinstance(item, dict):
                    return "submission-patch-report-invalid", "apply report operation is not an object"
                if item.get("block_id") not in allowed["block_ids"] and item.get("block_id") != "DOC-BODY-START":
                    return "submission-patch-scope-mismatch", "apply report operation exceeds the approved block scope"
                if item.get("op") not in allowed["operations"]:
                    return "submission-patch-scope-mismatch", "apply report operation exceeds the approved operation scope"
                roadmap_ids = item.get("roadmap_item_ids")
                if not isinstance(roadmap_ids, list) or not set(roadmap_ids) <= allowed["roadmap_item_ids"]:
                    return "submission-patch-scope-mismatch", "apply report roadmap mapping exceeds the approved scope"
            if patch_document is not None:
                if not isinstance(patch_document, dict) or patch_document.get("patch_format_version") != "1.1":
                    return "submission-patch-document-invalid", "patch document is not a current ARS patch"
                if patch_document.get("base_draft_hash") != base_hash:
                    return "submission-patch-base-mismatch", "patch document and apply report bind different bases"
                patch_ops = patch_document.get("ops")
                if not isinstance(patch_ops, list) or len(patch_ops) != len(ops):
                    return "submission-patch-report-mismatch", "patch document and apply report operation counts differ"
                for patch_op, report_op in zip(patch_ops, ops, strict=True):
                    if not isinstance(patch_op, dict) or patch_op.get("block_id") != report_op.get("block_id") or patch_op.get("op") != report_op.get("op"):
                        return "submission-patch-report-mismatch", "patch document and apply report target different operations"
                patch_digest = report.get("patch_digest")
                if patch_digest != value.patch.patch_document.content_sha256:
                    return "submission-patch-digest-mismatch", "apply report patch digest differs from the accepted patch document"
            mode = parsed_scope[0].get("operation_mode")
            media_type = next(
                (component.media_type for component in current_packet.components if component.role == "main_manuscript"),
                "",
            ).lower()
            if mode in {"automatic_word_patch", "automatic_pdf_remap"} or (
                patch_document is not None
                and ("word" in media_type or "pdf" in media_type)
            ):
                return "submission-revision-unsupported", "automatic Word/PDF patching or location remapping is unsupported; import external evidence instead"
            if mode == "ars_markdown_patch" and not any(token in media_type for token in ("markdown", "text/plain", "latex", "tex")):
                return "submission-revision-unsupported", "ARS patch adapter supports only Markdown/plain-text/LaTeX manuscripts"
            return None

        if isinstance(value, SubmissionPacket):
            for reference in (
                value.manuscript,
                value.policy_snapshot,
                *tuple(item.artifact for item in value.components),
                *value.audit_evidence,
                *value.response_evidence,
            ):
                expected_kind = (
                    "journal-requirements"
                    if reference is value.policy_snapshot
                    else None
                )
                error = require_reference(reference, expected_kind=expected_kind)
                if error:
                    return error
            predecessors = packets.get(value.submission_id, [])
            if value.packet_version == 1:
                if predecessors:
                    return "submission-predecessor-stale", "initial packet already has an accepted head"
            else:
                current_predecessor = max(predecessors, key=lambda item: item[0], default=None)
                if current_predecessor is None or value.predecessor_manifest_sha256 != current_predecessor[1]:
                    return "submission-predecessor-stale", "packet predecessor is not the accepted current history"
                if value.packet_version != current_predecessor[0] + 1:
                    return "submission-predecessor-stale", "packet version is not monotonic"
            return None
        if isinstance(value, JournalRequirementsSnapshot):
            for reference in value.retained_source_artifacts:
                error = require_reference(reference)
                if error:
                    return error
            return None
        if isinstance(value, ReviewRound):
            error = require_packet(value.submission_id)
            if error:
                return error
            if any(
                item.comment_id in review_comments.get(value.submission_id, set())
                for item in value.comments
            ):
                return "duplicate-review-import", "review comment identity is already accepted"
            return require_reference(value.source_letter)
        if isinstance(value, ReviewResponse):
            error = require_packet(value.submission_id)
            if error:
                return error
            if value.comment_id not in review_comments.get(value.submission_id, set()):
                return "review-comment-unknown", "response references an unaccepted review comment"
            expected_round = review_comment_rounds.get((value.submission_id, value.comment_id))
            if expected_round != value.round_number:
                return "review-round-mismatch", "response round does not match the accepted comment"
            if value.response_id in response_records:
                return "submission-response-identity-reused", "response ID is already accepted"
            current_response = response_heads.get((value.submission_id, value.comment_id))
            if current_response is None:
                if value.predecessor_response_id is not None:
                    return "submission-response-predecessor-stale", "response predecessor is not accepted"
            elif value.predecessor_response_id != current_response[0]:
                return "submission-response-predecessor-stale", "response predecessor is not the accepted current response"
            if value.status in {"addressed", "not_adopted"}:
                decision = next(
                    (
                        item
                        for item in state.human_decision_history
                        if item.decision_id == value.author_decision_id
                    ),
                    None,
                )
                expected_scope = (
                    f"submission:{value.submission_id}:response:{value.comment_id}"
                )
                if decision is None:
                    return "author-decision-unknown", "response closure requires an accepted human decision"
                gate = next(
                    (item for item in state.gates if item.gate_id == decision.gate_id),
                    None,
                )
                if (
                    decision.decision_kind != "approval"
                    or decision.scope != expected_scope
                    or decision.gate_id != confirmation_gate_id(expected_scope)
                    or decision.subject_sha256 != response_subject_sha256(value)
                    or gate is None
                    or gate.verdict != "PASS"
                    or gate.subject_sha256 != response_subject_sha256(value)
                ):
                    return "author-decision-scope-invalid", "response closure decision is not bound to this response"
            current_packets = packet_values.get(value.submission_id, [])
            current_packet = max(current_packets, key=lambda item: item[0], default=None)
            if current_packet is not None:
                for locator in value.locations:
                    if locator.manuscript_sha256 != current_packet[2].manuscript.content_sha256:
                        return "submission-location-stale", "response location is not bound to the current manuscript"
                    if (
                        locator.render_sha256 is not None
                        and (
                            locator.render_sha256 not in accepted_content_sha256
                            or not any(
                                "render" in kind or "pdf" in kind
                                for kind in accepted_content_kinds.get(locator.render_sha256, set())
                            )
                        )
                    ):
                        return "submission-location-render-unknown", "response render locator is not accepted"
            for reference in value.evidence:
                error = require_reference(reference)
                if error:
                    return error
            if value.patch is not None:
                if value.patch.block_manifest_sha256 not in accepted_manifest_sha256:
                    return "submission-patch-manifest-unknown", "patch block manifest is not accepted"
                error = require_reference(value.patch.apply_report)
                if error:
                    return error
                if value.patch.patch_document is not None:
                    error = require_reference(value.patch.patch_document)
                    if error:
                        return error
                if current_packet is not None:
                    if value.patch.base_manuscript_sha256 != current_packet[2].manuscript.content_sha256:
                        return "submission-patch-base-stale", "patch base does not match the current manuscript"
                    if (
                        value.patch.candidate_manuscript_sha256
                        not in accepted_content_sha256
                        and value.patch.candidate_manuscript_sha256
                        != current_packet[2].manuscript.content_sha256
                    ):
                        return "submission-patch-candidate-unknown", "patch candidate is not an accepted artifact"
                    block_manifest, error = read_accepted_json(
                        value.patch.block_manifest_sha256,
                        label="patch block manifest",
                    )
                    if error:
                        return error
                    report, error = read_accepted_json(
                        value.patch.apply_report.manifest_sha256,
                        label="patch apply report",
                    )
                    if error:
                        return error
                    patch_document = None
                    if value.patch.patch_document is not None:
                        patch_document, error = read_accepted_json(
                            value.patch.patch_document.manifest_sha256,
                            label="patch document",
                        )
                        if error:
                            return error
                    patch_error = validate_patch_report(
                        value,
                        current_packet[2],
                        report,
                        block_manifest,
                        patch_document,
                    )
                    if patch_error is not None:
                        return patch_error
            return None
        if isinstance(value, SubmissionCheckReport):
            error = require_packet(value.submission_id, value.packet_manifest_sha256)
            if error:
                return error
            for check in value.checks:
                for reference in check.evidence:
                    error = require_reference(reference)
                    if error:
                        return error
            return None
        if isinstance(value, SubmissionVerifierObservation):
            error = require_packet(value.submission_id, value.packet_manifest_sha256)
            if error:
                return error
            for check in value.checks:
                for reference in check.evidence:
                    error = require_reference(reference)
                    if error:
                        return error
            return None
        if isinstance(value, SubmissionResultObservation):
            error = require_packet(value.submission_id, value.packet_manifest_sha256)
            if error:
                return error
            if value.receipt is not None:
                return require_reference(value.receipt)
            return None
        return None

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
                    PassportAttemptSnapshot(
                        attempt_id=item.attempt_id,
                        base_revision=item.base_revision,
                        consumed_sha256=list(item.consumed_sha256),
                    )
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

        def rollback():
            _discard_orphan(self.run_root, "passports/sha256", digest_holder.get("value"))

        def after_append(state, event):
            if os.environ.get("ARW_TEST_FAILPOINT") == "post-passport-event-pre-pointer-sigkill":
                os.kill(os.getpid(), signal.SIGKILL)
            try:
                write_passport_pointer(
                    self.run_root,
                    PassportPointer(
                        run_id=state.run_id,
                        passport_sha256=digest_holder["value"],
                        accepted_revision=state.accepted_revision,
                        ledger_head_sha256=state.ledger_head_sha256,
                    ),
                )
            except OSError as error:
                _logger.warning(
                    "passport.accepted event %s committed but Passport pointer "
                    "could not be written: %s",
                    event.event_id,
                    error,
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
            rollback=rollback,
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
