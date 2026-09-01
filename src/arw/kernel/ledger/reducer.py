"""Pure reduction of accepted canonical events into runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from arw.kernel.state.models import (
    AssignmentPreparedPayload,
    AssignmentSupersededPayload,
    AttemptClosedPayload,
    AttemptLifecyclePayload,
    AttemptPreparedPayload,
    AttemptStartedPayload,
    ArtifactAcceptedPayload,
    CanonicalEvent,
    ExecutionModeSelectedPayload,
    ExperimentProvenanceAcceptedPayload,
    GateEvaluatedPayload,
    HostIdentityAcceptedPayload,
    HookObservedPayload,
    HumanAuthorityAcceptedPayload,
    HumanDecisionRequestedPayload,
    HumanDecisionRecordedPayload,
    HumanDecisionResolvedPayload,
    LifecycleTransitionedPayload,
    PassportAcceptedPayload,
    PanelPreparedPayload,
    ProposalAcceptedPayload,
    ProposalRejectedPayload,
    RecoveryHealth,
    RecoveryCompletedPayload,
    ReviewReportAcceptedPayload,
    ReviewSynthesisAcceptedPayload,
    ResumeAcceptedPayload,
    Sha256,
    StableRuntimeId,
    StrictModel,
    ZERO_HASH,
)
from arw.kernel.state.orchestration_models import RETRYABLE_FAILURES
from arw.kernel.ledger.workflows import (
    LEGACY_WORKFLOW_ID,
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


class Phase4ActiveAttemptState(StrictModel):
    """Internal Phase 4 attempt detail kept out of legacy passport snapshots."""

    attempt_id: StableRuntimeId
    base_revision: int
    consumed_sha256: list[Sha256]
    assignment_id: StableRuntimeId | None = None
    assignment_sha256: Sha256 | None = None
    attempt_number: int = 1
    status: str = "active"
    proposal_nonce: StableRuntimeId | None = None
    host_agent_id: str | None = None
    proposal_sha256: Sha256 | None = None


class AssignmentState(StrictModel):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    supersedes_assignment_id: StableRuntimeId | None = None
    acceptance_key: tuple[int, int, StableRuntimeId]
    role_id: StableRuntimeId
    worker_identity_id: StableRuntimeId
    execution_mode: str
    execution_provenance: str
    status: Literal["prepared", "active", "superseded"] = "prepared"
    assignment: object


class AttemptLifecycleState(StrictModel):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt_id: StableRuntimeId
    attempt_number: int
    status: str
    retry_reason: str | None = None
    retry_eligible: bool = False
    proposal_sha256: Sha256 | None = None
    source_event_id: str


class ProposalState(StrictModel):
    assignment_id: StableRuntimeId
    assignment_sha256: Sha256
    attempt_id: StableRuntimeId
    proposal_sha256: Sha256
    acceptance_key: tuple[int, int, StableRuntimeId]
    outcome: Literal[
        "accepted", "rejected", "rejected_invalid", "rejected_stale", "rejected_cancelled", "rejected_superseded"
    ]
    effective_status: Literal["pending_order", "accepted", "rejected"]
    reason_code: StableRuntimeId | None = None
    proposal: object | None = None
    raw_bytes_retained: bool = True
    source_event_id: str


class GateState(StrictModel):
    gate_id: StableRuntimeId
    verdict: Literal["PASS", "FAIL", "BLOCKED"]
    required: bool
    subject_sha256: Sha256
    evidence_sha256: tuple[Sha256, ...]
    decision_sha256: Sha256
    decision: object
    source_event_id: str


class HostIdentityState(StrictModel):
    receipt_id: StableRuntimeId
    receipt_sha256: Sha256
    receipt: object
    source_event_id: str


class HumanAuthorityState(StrictModel):
    authority_id: StableRuntimeId
    authority_sha256: Sha256
    authority: object
    source_event_id: str


class BlockerReleaseState(StrictModel):
    blocker_code: StableRuntimeId
    decision_id: StableRuntimeId
    action: Literal["release", "restore"]
    source_event_id: str


class HumanDecisionState(StrictModel):
    decision_id: StableRuntimeId
    decision_kind: str
    gate_id: StableRuntimeId
    subject_sha256: Sha256
    applicable_transition: StableRuntimeId
    scope: str
    rationale: str
    decision_sha256: Sha256
    authority_sha256: Sha256
    source_event_id: str
    decision: object


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
    active_attempts: list[Phase4ActiveAttemptState | AttemptState] = Field(
        default_factory=list
    )
    legal_next_transitions: list[str] = Field(default_factory=list)
    accepted_artifact_manifest_sha256: list[str] = Field(default_factory=list)
    accepted_passport_sha256: list[str] = Field(default_factory=list)
    consumed_passport_sha256: list[str] = Field(default_factory=list)
    execution_mode: Literal[
        "native_profile",
        "assignment_injected_subagent",
        "degraded_inline",
        "blocked",
    ] | None = None
    execution_provenance: str | None = None
    role_catalog_sha256: Sha256 | None = None
    policy_sha256: Sha256 | None = None
    dag_sha256: Sha256 | None = None
    assignments: tuple[AssignmentState, ...] = Field(default_factory=tuple)
    assignment_revisions: tuple[AssignmentState, ...] = Field(default_factory=tuple)
    attempts: tuple[AttemptLifecycleState, ...] = Field(default_factory=tuple)
    proposals: tuple[ProposalState, ...] = Field(default_factory=tuple)
    accepted_proposal_sha256: tuple[Sha256, ...] = Field(default_factory=tuple)
    rejected_proposal_sha256: tuple[Sha256, ...] = Field(default_factory=tuple)
    deterministic_commit_cursor: tuple[int, int, StableRuntimeId] | None = None
    panel_reports: tuple[object, ...] = Field(default_factory=tuple)
    panel_syntheses: tuple[object, ...] = Field(default_factory=tuple)
    panel_manifests: tuple[object, ...] = Field(default_factory=tuple)
    host_identity_receipts: tuple[HostIdentityState, ...] = Field(default_factory=tuple)
    human_authorities: tuple[HumanAuthorityState, ...] = Field(default_factory=tuple)
    blocker_release_history: tuple[BlockerReleaseState, ...] = Field(default_factory=tuple)
    canonical_event_sha256: tuple[Sha256, ...] = Field(default_factory=tuple)
    accepted_evidence_sha256: tuple[Sha256, ...] = Field(default_factory=tuple)
    hook_observations: tuple[object, ...] = Field(default_factory=tuple)
    gates: tuple[GateState, ...] = Field(default_factory=tuple)
    human_decision_history: tuple[HumanDecisionState, ...] = Field(default_factory=tuple)
    status: Literal["RUNNING", "PASS", "FAIL", "BLOCKED"] = "RUNNING"
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

    @property
    def accepted_proposals(self) -> tuple[ProposalState, ...]:
        return tuple(item for item in self.proposals if item.effective_status == "accepted")

    @property
    def rejected_proposals(self) -> tuple[ProposalState, ...]:
        return tuple(item for item in self.proposals if item.effective_status == "rejected")

    @property
    def human_decisions(self) -> tuple[HumanDecisionState, ...]:
        return self.human_decision_history


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _assignment_state(record: object, digest: str, *, status: str = "prepared") -> AssignmentState:
    return AssignmentState(
        assignment_id=record.assignment_id,  # type: ignore[attr-defined]
        assignment_sha256=digest,
        supersedes_assignment_id=record.supersedes_assignment_id,  # type: ignore[attr-defined]
        acceptance_key=record.acceptance_key.value,  # type: ignore[attr-defined]
        role_id=record.role_id,  # type: ignore[attr-defined]
        worker_identity_id=record.worker_identity_id,  # type: ignore[attr-defined]
        execution_mode=record.execution_mode,  # type: ignore[attr-defined]
        execution_provenance=record.execution_provenance,  # type: ignore[attr-defined]
        status=status,
        assignment=record,
    )


def _phase4_attempt_status(attempt_id: str, status_by_attempt_id: dict[str, str]) -> str | None:
    """Return the latest recorded lifecycle status for an attempt (O(1))."""
    return status_by_attempt_id.get(attempt_id)


def _recompute_proposal_order(
    assignments: dict[str, AssignmentState], proposals: list[ProposalState]
) -> tuple[tuple[ProposalState, ...], tuple[str, ...], tuple[str, ...], tuple[int, int, str] | None, bool]:
    """Return the frozen-key projection, independent of event arrival order."""

    by_assignment: dict[str, ProposalState] = {}
    for proposal in proposals:
        if proposal.assignment_id in by_assignment:
            continue
        by_assignment[proposal.assignment_id] = proposal
    ordered_assignments = sorted(
        (item for item in assignments.values() if item.status != "superseded"),
        key=lambda item: item.acceptance_key,
    )
    accepted: list[str] = []
    rejected: list[str] = []
    projected: list[ProposalState] = []
    cursor: tuple[int, int, str] | None = None
    gap = False
    for assignment in ordered_assignments:
        proposal = by_assignment.get(assignment.assignment_id)
        if proposal is None:
            gap = True
            continue
        if gap:
            projected.append(proposal.model_copy(update={"effective_status": "pending_order"}))
            continue
        if proposal.outcome == "accepted":
            accepted.append(proposal.proposal_sha256)
            projected.append(proposal.model_copy(update={"effective_status": "accepted"}))
        else:
            rejected.append(proposal.proposal_sha256)
            projected.append(proposal.model_copy(update={"effective_status": "rejected"}))
        cursor = assignment.acceptance_key
    return tuple(projected), tuple(accepted), tuple(rejected), cursor, gap


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
    decision_ids: set[str] = set()
    accepted_event_ids: set[str] = set()
    attempts: dict[str, AttemptState | Phase4ActiveAttemptState] = {}
    attempt_ids: set[str] = set()
    blockers: dict[str, BlockerState] = {}
    artifacts: list[str] = []
    artifact_ids: set[str] = set()
    passports: list[str] = []
    consumed_passports: list[str] = []
    current_passport: str | None = None
    current_passport_stage: str | None = None
    fresh_until: str | None = None
    execution_mode: str | None = None
    execution_provenance: str | None = None
    role_catalog_sha256: str | None = None
    policy_sha256: str | None = None
    dag_sha256: str | None = None
    phase4_assignments: dict[str, AssignmentState] = {}
    assignment_history: list[AssignmentState] = []
    phase4_attempt_history: list[AttemptLifecycleState] = []
    attempt_statuses: dict[str, str] = {}
    latest_attempt_by_key: dict[tuple[str, int], AttemptLifecycleState] = {}
    max_attempt_number_by_assignment: dict[str, int] = {}
    repairable_attempt_keys: set[tuple[str, int]] = set()
    phase4_proposals: list[ProposalState] = []
    proposal_sha256s: set[str] = set()
    panel_reports: list[object] = []
    report_ids: set[str] = set()
    panel_syntheses: list[object] = []
    panel_manifests: list[object] = []
    panel_ids: set[str] = set()
    host_identity_receipts: list[HostIdentityState] = []
    receipt_ids: set[str] = set()
    receipt_sha256s: set[str] = set()
    human_authorities: list[HumanAuthorityState] = []
    authority_ids: set[str] = set()
    authority_sha256s: set[str] = set()
    blocker_release_history: list[BlockerReleaseState] = []
    canonical_event_sha256: list[str] = []
    accepted_evidence_sha256: list[str] = []
    hook_observations: list[object] = []
    hook_idempotency_keys: set[str] = set()
    gates: dict[str, GateState] = {}
    failed_gate_ids: set[str] = set()
    human_decision_history: list[HumanDecisionState] = []
    human_decision_ids: set[str] = set()
    phase4_event_seen = False

    for event_index, event in enumerate(events):
        if event.run_id != run_id:
            raise ReducerError("event run identity changed")
        if event.expected_revision != revision or event.resulting_revision != revision + 1:
            raise ReducerError("event revision is not contiguous")
        if event.actor_role is None and workflow_definition_id != LEGACY_WORKFLOW_ID:
            raise ReducerError("Phase 2 events require an explicit actor role")
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
        elif event.event_type == "execution.mode_selected":
            assert isinstance(payload, ExecutionModeSelectedPayload)
            phase4_event_seen = True
            if execution_mode is not None and (
                execution_mode != payload.execution_mode
                or execution_provenance != payload.execution_provenance
            ):
                raise ReducerError("execution mode is immutable after selection")
            execution_mode = payload.execution_mode
            execution_provenance = payload.execution_provenance
            role_catalog_sha256 = payload.role_catalog_sha256
            policy_sha256 = payload.policy_sha256
            dag_sha256 = payload.dag_sha256
            if execution_mode == "blocked":
                blockers["execution-mode-blocked"] = BlockerState(
                    code="execution-mode-blocked", source_event_id=event.event_id
                )
        elif event.event_type in {"assignment.prepared", "assignment.superseded"}:
            assert isinstance(payload, (AssignmentPreparedPayload, AssignmentSupersededPayload))
            phase4_event_seen = True
            assignment = payload.assignment
            assignment_id = assignment.assignment_id  # type: ignore[attr-defined]
            if assignment_id in phase4_assignments:
                raise ReducerError("assignment ID was already used")
            if execution_mode is not None and assignment.execution_mode != execution_mode:  # type: ignore[attr-defined]
                raise ReducerError("assignment execution mode differs from frozen run mode")
            predecessor_id = assignment.supersedes_assignment_id  # type: ignore[attr-defined]
            status = "prepared"
            if predecessor_id is not None:
                predecessor = phase4_assignments.get(predecessor_id)
                if predecessor is None:
                    raise ReducerError("superseding assignment references an unknown predecessor")
                try:
                    assignment.validate_supersedes(predecessor.assignment)  # type: ignore[attr-defined]
                except ValueError as error:
                    raise ReducerError(str(error)) from error
                phase4_assignments[predecessor_id] = predecessor.model_copy(
                    update={"status": "superseded"}
                )
                status = "active"
            current = _assignment_state(assignment, payload.assignment_sha256, status=status)
            phase4_assignments[assignment_id] = current
            assignment_history.append(current)
        elif event.event_type == "attempt.prepared":
            assert isinstance(payload, AttemptPreparedPayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("attempt result cannot precede its assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("attempt assignment digest is stale")
            attempt = payload.attempt
            if attempt.status != "prepared":  # type: ignore[attr-defined]
                raise ReducerError("attempt.prepared requires a prepared descriptor")
            if attempt.attempt_id in attempt_ids:  # type: ignore[attr-defined]
                raise ReducerError("attempt ID was already used")
            if attempt.assignment_id != payload.assignment_id:  # type: ignore[attr-defined]
                raise ReducerError("attempt assignment identity differs")
            if attempt.attempt_number > 1:  # type: ignore[attr-defined]
                if (
                    max_attempt_number_by_assignment.get(payload.assignment_id)
                    != attempt.attempt_number - 1  # type: ignore[attr-defined]
                ):
                    raise ReducerError("retry must follow the immediately preceding attempt")
                predecessor = latest_attempt_by_key[
                    (payload.assignment_id, attempt.attempt_number - 1)  # type: ignore[attr-defined]
                ]
                if predecessor.status not in {
                    "failed",
                    "cancelled",
                    "interrupted",
                    "force_terminated",
                }:
                    raise ReducerError("retry requires a terminal repairable attempt")
                if (
                    not predecessor.retry_eligible
                    or predecessor.retry_reason not in RETRYABLE_FAILURES
                ):
                    raise ReducerError("retry predecessor is not canonically eligible")
            attempt_ids.add(attempt.attempt_id)  # type: ignore[attr-defined]
            attempts[attempt.attempt_id] = Phase4ActiveAttemptState(  # type: ignore[attr-defined]
                attempt_id=attempt.attempt_id,  # type: ignore[attr-defined]
                base_revision=assignment.assignment.base_revision,  # type: ignore[attr-defined]
                consumed_sha256=list(assignment.assignment.input_sha256),  # type: ignore[attr-defined]
                assignment_id=payload.assignment_id,
                assignment_sha256=payload.assignment_sha256,
                attempt_number=attempt.attempt_number,  # type: ignore[attr-defined]
                status=attempt.status,  # type: ignore[attr-defined]
                proposal_nonce=attempt.proposal_nonce,  # type: ignore[attr-defined]
                host_agent_id=attempt.host_agent_id,  # type: ignore[attr-defined]
            )
            phase4_attempt_history.append(
                AttemptLifecycleState(
                    assignment_id=payload.assignment_id,
                    assignment_sha256=payload.assignment_sha256,
                    attempt_id=attempt.attempt_id,  # type: ignore[attr-defined]
                    attempt_number=attempt.attempt_number,  # type: ignore[attr-defined]
                    status=attempt.status,  # type: ignore[attr-defined]
                    retry_reason=attempt.retry_reason,  # type: ignore[attr-defined]
                    retry_eligible=attempt.retry_eligible,  # type: ignore[attr-defined]
                    source_event_id=event.event_id,
                )
            )
            attempt_statuses[attempt.attempt_id] = attempt.status  # type: ignore[attr-defined]
            latest_attempt_by_key[(payload.assignment_id, attempt.attempt_number)] = phase4_attempt_history[-1]  # type: ignore[attr-defined]
            max_attempt_number_by_assignment[payload.assignment_id] = max(
                max_attempt_number_by_assignment.get(payload.assignment_id, 0),
                attempt.attempt_number,  # type: ignore[attr-defined]
            )
        elif event.event_type == "attempt.lifecycle":
            assert isinstance(payload, AttemptLifecyclePayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("attempt lifecycle references an unknown assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("attempt lifecycle assignment digest is stale")
            known = attempts.get(payload.attempt_id)
            if known is None and _phase4_attempt_status(payload.attempt_id, attempt_statuses) is None:
                raise ReducerError("attempt lifecycle references an unknown attempt")
            if (
                payload.attempt_number > 1
                and (payload.assignment_id, payload.attempt_number - 1)
                not in repairable_attempt_keys
            ):
                raise ReducerError("retry lifecycle is outside the repairable attempt budget")
            phase4_attempt_history.append(
                AttemptLifecycleState(
                    assignment_id=payload.assignment_id,
                    assignment_sha256=payload.assignment_sha256,
                    attempt_id=payload.attempt_id,
                    attempt_number=payload.attempt_number,
                    status=payload.status,
                    retry_reason=payload.retry_reason,
                    retry_eligible=payload.retry_eligible,
                    proposal_sha256=payload.proposal_sha256,
                    source_event_id=event.event_id,
                )
            )
            attempt_statuses[payload.attempt_id] = payload.status
            latest_attempt_by_key[(payload.assignment_id, payload.attempt_number)] = phase4_attempt_history[-1]
            max_attempt_number_by_assignment[payload.assignment_id] = max(
                max_attempt_number_by_assignment.get(payload.assignment_id, 0),
                payload.attempt_number,
            )
            if payload.status in {"failed", "cancelled", "interrupted", "force_terminated"}:
                repairable_attempt_keys.add((payload.assignment_id, payload.attempt_number))
            if known is not None:
                updated = known.model_copy(
                    update={
                        "status": payload.status,
                        "proposal_sha256": payload.proposal_sha256,
                    }
                )
                if payload.status in {
                    "completed",
                    "failed",
                    "cancelled",
                    "force_terminated",
                    "interrupted",
                    "rejected_stale",
                    "superseded",
                    "blocked",
                }:
                    attempts.pop(payload.attempt_id, None)
                else:
                    attempts[payload.attempt_id] = updated
            if payload.status == "blocked":
                blockers[f"attempt-blocked.{payload.attempt_id}"] = BlockerState(
                    code=f"attempt-blocked.{payload.attempt_id}",
                    source_event_id=event.event_id,
                )
        elif event.event_type == "proposal.accepted":
            assert isinstance(payload, ProposalAcceptedPayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("proposal cannot precede its assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("proposal assignment digest is stale")
            attempt_status = _phase4_attempt_status(payload.attempt_id, attempt_statuses)
            if attempt_status in {
                "cancelled",
                "force_terminated",
                "interrupted",
                "rejected_stale",
                "superseded",
            } or assignment.status == "superseded":
                raise ReducerError("stale proposal cannot be accepted")
            if (
                assignment.execution_mode
                not in {"native_profile", "assignment_injected_subagent"}
                and assignment.independence_eligible
            ):
                raise ReducerError("formal proposal cannot be accepted from degraded or blocked mode")
            if payload.proposal_sha256 in proposal_sha256s:
                raise ReducerError("proposal digest was already recorded")
            phase4_proposals.append(
                ProposalState(
                    assignment_id=payload.assignment_id,
                    assignment_sha256=payload.assignment_sha256,
                    attempt_id=payload.attempt_id,
                    proposal_sha256=payload.proposal_sha256,
                    acceptance_key=payload.acceptance_key,
                    outcome="accepted",
                    effective_status="pending_order",
                    proposal=payload.proposal,
                    source_event_id=event.event_id,
                )
            )
            proposal_sha256s.add(payload.proposal_sha256)
            known = attempts.pop(payload.attempt_id, None)
            if known is not None:
                phase4_attempt_history.append(
                    AttemptLifecycleState(
                        assignment_id=payload.assignment_id,
                        assignment_sha256=payload.assignment_sha256,
                        attempt_id=payload.attempt_id,
                        attempt_number=known.attempt_number,
                        status="completed",
                        retry_eligible=False,
                        proposal_sha256=payload.proposal_sha256,
                        source_event_id=event.event_id,
                    )
                )
                attempt_statuses[payload.attempt_id] = "completed"
                latest_attempt_by_key[(payload.assignment_id, known.attempt_number)] = phase4_attempt_history[-1]
                max_attempt_number_by_assignment[payload.assignment_id] = max(
                    max_attempt_number_by_assignment.get(payload.assignment_id, 0),
                    known.attempt_number,
                )
        elif event.event_type == "proposal.rejected":
            assert isinstance(payload, ProposalRejectedPayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("proposal rejection cannot precede its assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("proposal rejection assignment digest is stale")
            if payload.proposal_sha256 in proposal_sha256s:
                raise ReducerError("proposal digest was already recorded")
            phase4_proposals.append(
                ProposalState(
                    assignment_id=payload.assignment_id,
                    assignment_sha256=payload.assignment_sha256,
                    attempt_id=payload.attempt_id,
                    proposal_sha256=payload.proposal_sha256,
                    acceptance_key=payload.acceptance_key,
                    outcome=payload.outcome,
                    effective_status="rejected",
                    reason_code=payload.reason_code,
                    raw_bytes_retained=payload.raw_bytes_retained,
                    source_event_id=event.event_id,
                )
            )
            proposal_sha256s.add(payload.proposal_sha256)
        elif event.event_type == "host_identity.accepted":
            assert isinstance(payload, HostIdentityAcceptedPayload)
            phase4_event_seen = True
            receipt = payload.receipt
            if receipt.receipt_id in receipt_ids or payload.receipt_sha256 in receipt_sha256s:  # type: ignore[attr-defined]
                raise ReducerError("host identity receipt was already recorded")
            host_identity_receipts.append(
                HostIdentityState(
                    receipt_id=receipt.receipt_id,  # type: ignore[attr-defined]
                    receipt_sha256=payload.receipt_sha256,
                    receipt=receipt,
                    source_event_id=event.event_id,
                )
            )
            receipt_ids.add(receipt.receipt_id)  # type: ignore[attr-defined]
            receipt_sha256s.add(payload.receipt_sha256)
            accepted_evidence_sha256.append(payload.receipt_sha256)
        elif event.event_type == "experiment.provenance.accepted":
            assert isinstance(payload, ExperimentProvenanceAcceptedPayload)
            phase4_event_seen = True
            if payload.provenance_sha256 in accepted_evidence_sha256:
                raise ReducerError("experiment provenance was already accepted")
            accepted_evidence_sha256.append(payload.provenance_sha256)
        elif event.event_type == "panel.prepared":
            assert isinstance(payload, PanelPreparedPayload)
            phase4_event_seen = True
            manifest = payload.manifest
            if manifest.panel_id in panel_ids:  # type: ignore[attr-defined]
                raise ReducerError("panel ID was already prepared")
            receipts = {
                item.receipt_sha256: item.receipt for item in host_identity_receipts
            }
            seats = (*manifest.reviewer_seats,)  # type: ignore[attr-defined]
            if manifest.synthesizer_seat is not None:  # type: ignore[attr-defined]
                seats = (*seats, manifest.synthesizer_seat)  # type: ignore[attr-defined]
            for seat in seats:
                receipt = receipts.get(seat.identity_receipt_sha256)
                if receipt is None:
                    raise ReducerError("panel seat references unknown host identity evidence")
                if (
                    receipt.role_id != seat.role_id
                    or receipt.worker_identity_id != seat.worker_identity_id
                    or receipt.host_agent_id != seat.host_agent_id
                ):
                    raise ReducerError("panel seat differs from retained host identity evidence")
            panel_manifests.append(manifest)
            panel_ids.add(manifest.panel_id)  # type: ignore[attr-defined]
            accepted_evidence_sha256.append(payload.manifest_sha256)
            if manifest.status == "blocked":  # type: ignore[attr-defined]
                blockers[f"panel-blocked.{manifest.panel_id}"] = BlockerState(  # type: ignore[attr-defined]
                    code=f"panel-blocked.{manifest.panel_id}",  # type: ignore[attr-defined]
                    source_event_id=event.event_id,
                )
        elif event.event_type == "review.report_accepted":
            assert isinstance(payload, ReviewReportAcceptedPayload)
            phase4_event_seen = True
            report = payload.report
            report_id = report.report_id  # type: ignore[attr-defined]
            if report_id in report_ids:
                raise ReducerError("review report ID was already recorded")
            manifest = next(
                (
                    item
                    for item in panel_manifests
                    if item.manifest_sha256 == report.panel_manifest_sha256  # type: ignore[attr-defined]
                ),
                None,
            )
            if manifest is None or manifest.status != "ready":  # type: ignore[attr-defined]
                raise ReducerError("review report references an unknown or blocked panel")
            seat = next(
                (
                    item
                    for item in manifest.reviewer_seats  # type: ignore[attr-defined]
                    if item.assignment_id == report.assignment_id  # type: ignore[attr-defined]
                ),
                None,
            )
            if seat is None or (
                seat.attempt_id != report.attempt_id  # type: ignore[attr-defined]
                or seat.role_id != report.role_id  # type: ignore[attr-defined]
                or seat.worker_identity_id != report.worker_identity_id  # type: ignore[attr-defined]
                or seat.host_agent_id != report.host_agent_id  # type: ignore[attr-defined]
                or seat.identity_receipt_sha256 != report.identity_receipt_sha256  # type: ignore[attr-defined]
            ):
                raise ReducerError("review report does not bind its canonical panel seat")
            panel_reports.append(report)
            report_ids.add(report_id)
            accepted_evidence_sha256.append(payload.report_sha256)
        elif event.event_type == "review.synthesis_accepted":
            assert isinstance(payload, ReviewSynthesisAcceptedPayload)
            phase4_event_seen = True
            matrix = payload.finding_matrix
            manifest = next(
                (
                    item
                    for item in panel_manifests
                    if item.manifest_sha256 == matrix.panel_manifest_sha256  # type: ignore[attr-defined]
                ),
                None,
            )
            if manifest is None or manifest.status != "ready":  # type: ignore[attr-defined]
                raise ReducerError("synthesis references an unknown or blocked panel")
            accepted_reports = {
                item.report_sha256: item
                for item in panel_reports
                if item.panel_manifest_sha256 == matrix.panel_manifest_sha256  # type: ignore[attr-defined]
            }
            if set(matrix.synthesis.source_report_sha256) != set(accepted_reports):  # type: ignore[attr-defined]
                raise ReducerError("synthesis must bind every exact accepted panel report")
            if {item.report_sha256 for item in matrix.reports} != set(accepted_reports):  # type: ignore[attr-defined]
                raise ReducerError("synthesis report bodies differ from canonical accepted reports")
            synth_seat = manifest.synthesizer_seat  # type: ignore[attr-defined]
            if synth_seat is None or (
                synth_seat.worker_identity_id != matrix.synthesis.worker_identity_id  # type: ignore[attr-defined]
                or synth_seat.host_agent_id != matrix.synthesis.host_agent_id  # type: ignore[attr-defined]
                or synth_seat.identity_receipt_sha256
                != matrix.synthesis.identity_receipt_sha256  # type: ignore[attr-defined]
            ):
                raise ReducerError("synthesis identity differs from the canonical panel")
            panel_syntheses.append(matrix)
            accepted_evidence_sha256.append(payload.finding_matrix_sha256)
            if matrix.gate_verdict == "BLOCKED":  # type: ignore[attr-defined]
                blockers["formal-review-blocked"] = BlockerState(
                    code="formal-review-blocked", source_event_id=event.event_id
                )
        elif event.event_type == "hook.observed":
            assert isinstance(payload, HookObservedPayload)
            phase4_event_seen = True
            if payload.observation.idempotency_key in hook_idempotency_keys:  # type: ignore[attr-defined]
                raise ReducerError("hook observation idempotency key was already recorded")
            hook_observations.append(payload.observation)
            hook_idempotency_keys.add(payload.observation.idempotency_key)  # type: ignore[attr-defined]
            accepted_evidence_sha256.append(payload.observation_sha256)
        elif event.event_type == "gate.evaluated":
            assert isinstance(payload, GateEvaluatedPayload)
            phase4_event_seen = True
            decision = payload.decision
            gate_id = decision.gate_id  # type: ignore[attr-defined]
            if gate_id in gates:
                raise ReducerError("gate verdicts are append-only and cannot be overwritten")
            gate = GateState(
                gate_id=gate_id,
                verdict=decision.verdict,  # type: ignore[attr-defined]
                required=decision.required,  # type: ignore[attr-defined]
                subject_sha256=decision.subject_sha256,  # type: ignore[attr-defined]
                evidence_sha256=decision.evidence_sha256,  # type: ignore[attr-defined]
                decision_sha256=payload.decision_sha256,
                decision=decision,
                source_event_id=event.event_id,
            )
            gates[gate_id] = gate
            accepted_evidence_sha256.append(payload.decision_sha256)
            if decision.verdict in {"FAIL", "BLOCKED"}:  # type: ignore[attr-defined]
                if decision.verdict == "FAIL":  # type: ignore[attr-defined]
                    failed_gate_ids.add(gate_id)
                blockers[gate_id] = BlockerState(
                    code=gate_id, source_event_id=event.event_id
                )
            elif decision.required and decision.fresh_until and event.occurred_at > decision.fresh_until:  # type: ignore[attr-defined]
                blockers[f"stale-gate.{gate_id}"] = BlockerState(
                    code=f"stale-gate.{gate_id}", source_event_id=event.event_id
                )
        elif event.event_type == "human_authority.accepted":
            assert isinstance(payload, HumanAuthorityAcceptedPayload)
            phase4_event_seen = True
            authority = payload.authority
            if authority.authority_id in authority_ids or payload.authority_sha256 in authority_sha256s:  # type: ignore[attr-defined]
                raise ReducerError("human authority envelope was already recorded")
            human_authorities.append(
                HumanAuthorityState(
                    authority_id=authority.authority_id,  # type: ignore[attr-defined]
                    authority_sha256=payload.authority_sha256,
                    authority=authority,
                    source_event_id=event.event_id,
                )
            )
            authority_ids.add(authority.authority_id)  # type: ignore[attr-defined]
            authority_sha256s.add(payload.authority_sha256)
            accepted_evidence_sha256.append(payload.authority_sha256)
        elif event.event_type == "human_decision.recorded":
            assert isinstance(payload, HumanDecisionRecordedPayload)
            phase4_event_seen = True
            decision = payload.decision
            decision_id = decision.decision_id  # type: ignore[attr-defined]
            if decision_id in human_decision_ids:
                raise ReducerError("human decision ID was already recorded")
            gate = gates.get(decision.gate_id)  # type: ignore[attr-defined]
            if gate is None or gate.decision_sha256 != decision.prior_verdict_sha256:  # type: ignore[attr-defined]
                raise ReducerError("human decision prior verdict is not the exact gate decision")
            authority_state = next(
                (
                    item
                    for item in human_authorities
                    if item.authority_sha256 == payload.authority_sha256
                ),
                None,
            )
            if authority_state is None:
                raise ReducerError("human decision references unknown authority evidence")
            authority = authority_state.authority
            if (
                authority.authenticated_actor_id != decision.accountable_actor_id  # type: ignore[attr-defined]
                or authority.accountable_role != decision.accountable_role  # type: ignore[attr-defined]
                or decision.decision_kind not in authority.allowed_decision_kinds  # type: ignore[attr-defined]
                or decision.gate_id not in authority.allowed_gate_ids  # type: ignore[attr-defined]
                or decision.scope not in authority.allowed_scopes  # type: ignore[attr-defined]
                or event.occurred_at > authority.expires_at
            ):
                raise ReducerError("human decision exceeds its authenticated authority envelope")
            predecessor = decision.supersedes_decision_id  # type: ignore[attr-defined]
            if decision.decision_kind == "correction":  # type: ignore[attr-defined]
                prior = next(
                    (
                        item
                        for item in human_decision_history
                        if item.decision_id == predecessor
                    ),
                    None,
                )
                latest_for_scope = next(
                    (
                        item
                        for item in reversed(human_decision_history)
                        if item.gate_id == decision.gate_id  # type: ignore[attr-defined]
                        and item.scope == decision.scope  # type: ignore[attr-defined]
                    ),
                    None,
                )
                if prior is None or prior != latest_for_scope:
                    raise ReducerError(
                        "correction must supersede the latest decision in the same gate/scope"
                    )
            human_decision_history.append(
                HumanDecisionState(
                    decision_id=decision_id,
                    decision_kind=decision.decision_kind,  # type: ignore[attr-defined]
                    gate_id=decision.gate_id,  # type: ignore[attr-defined]
                    subject_sha256=decision.subject_sha256,  # type: ignore[attr-defined]
                    applicable_transition=decision.applicable_transition,  # type: ignore[attr-defined]
                    scope=decision.scope,  # type: ignore[attr-defined]
                    rationale=decision.rationale,  # type: ignore[attr-defined]
                    decision_sha256=payload.decision_sha256,
                    authority_sha256=payload.authority_sha256,
                    source_event_id=event.event_id,
                    decision=decision,
                )
            )
            human_decision_ids.add(decision_id)
            if decision.blocker_action == "release":  # type: ignore[attr-defined]
                code = decision.blocker_code  # type: ignore[attr-defined]
                if code not in blockers:
                    raise ReducerError("human decision cannot release an unknown blocker")
                blockers.pop(code)
                blocker_release_history.append(
                    BlockerReleaseState(
                        blocker_code=code,
                        decision_id=decision_id,
                        action="release",
                        source_event_id=event.event_id,
                    )
                )
            elif decision.blocker_action == "restore":  # type: ignore[attr-defined]
                code = decision.blocker_code  # type: ignore[attr-defined]
                prior_release = next(
                    (
                        item
                        for item in reversed(blocker_release_history)
                        if item.blocker_code == code and item.action == "release"
                    ),
                    None,
                )
                if prior_release is None or code in blockers:
                    raise ReducerError("human correction cannot restore an unreleased blocker")
                blockers[code] = BlockerState(
                    code=code, source_event_id=event.event_id
                )
                blocker_release_history.append(
                    BlockerReleaseState(
                        blocker_code=code,
                        decision_id=decision_id,
                        action="restore",
                        source_event_id=event.event_id,
                    )
                )
            accepted_evidence_sha256.append(payload.decision_sha256)
        elif event.event_type == "lifecycle.transitioned":
            assert isinstance(payload, LifecycleTransitionedPayload)
            if blockers:
                raise ReducerError("runtime blockers prevent lifecycle transitions")
            if fresh_until and _parse_utc(event.occurred_at) > _parse_utc(fresh_until):
                raise ReducerError("expired Passport evidence prevents lifecycle transitions")
            if payload.from_stage != stage:
                raise ReducerError("transition from_stage differs from accepted stage")
            try:
                transition = require_transition(workflow_definition_id, stage, payload.transition_id)
            except WorkflowDefinitionError as error:
                raise ReducerError(f"transition is not legal: {error}") from error
            if transition.to_stage != payload.to_stage:
                raise ReducerError("transition to_stage differs from registered definition")
            if transition.to_stage == "completed" and phase4_event_seen:
                if execution_mode in {"degraded_inline", "blocked"}:
                    raise ReducerError("formal completion is not legal in degraded or blocked mode")
                if any(
                    manifest.status == "ready"
                    and not any(
                        matrix.panel_manifest_sha256 == manifest.manifest_sha256
                        for matrix in panel_syntheses
                    )
                    for manifest in panel_manifests
                ):
                    raise ReducerError("final completion requires every ready panel synthesis")
                if any(
                    item.assignment.completion_contract.requires_human_gate
                    for item in phase4_assignments.values()
                    if item.status != "superseded"
                ) and not any(
                    gate.required and gate.verdict == "PASS" for gate in gates.values()
                ):
                    raise ReducerError("final completion requires a fresh required PASS gate")
                if not any(
                    item.decision_kind == "approval" and item.applicable_transition == payload.transition_id
                    for item in human_decision_history
                ):
                    raise ReducerError("final completion requires an authorized human decision")
            stage = payload.to_stage
        elif event.event_type == "human_decision.requested":
            assert isinstance(payload, HumanDecisionRequestedPayload)
            if payload.decision_id in decision_ids:
                raise ReducerError("decision ID was already used")
            if payload.starting_revision != revision:
                raise ReducerError("decision starting revision is not current")
            if any(
                source not in accepted_event_ids for source in payload.source_event_ids
            ):
                raise ReducerError("decision references an unknown source event")
            decision_ids.add(payload.decision_id)
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
            if not any(
                item.blocker_code == pending.blocker_code for item in decisions.values()
            ):
                blockers.pop(pending.blocker_code, None)
        elif event.event_type == "attempt.started":
            assert isinstance(payload, AttemptStartedPayload)
            if payload.attempt_id in attempt_ids:
                raise ReducerError("attempt ID was already used")
            if payload.base_revision != revision:
                raise ReducerError("attempt base revision is not current")
            known_hashes = {head, *artifacts, *passports}
            if any(value not in known_hashes for value in payload.consumed_sha256):
                raise ReducerError("attempt consumes an unknown or stale hash")
            attempt_ids.add(payload.attempt_id)
            attempts[payload.attempt_id] = Phase4ActiveAttemptState(
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
            assert isinstance(payload, ArtifactAcceptedPayload)
            if payload.artifact_id in artifact_ids:
                raise ReducerError("artifact ID was already used")
            if payload.manifest_sha256 in artifacts:
                raise ReducerError("artifact manifest was already accepted")
            artifact_ids.add(payload.artifact_id)
            artifacts.append(payload.manifest_sha256)
        elif event.event_type == "passport.accepted":
            assert isinstance(payload, PassportAcceptedPayload)
            previous = events[event_index - 1] if event_index else None
            coherent = payload.checkpoint_kind == "explicit"
            if (
                payload.checkpoint_kind == "stage_handoff"
                and previous is not None
                and previous.event_type == "lifecycle.transitioned"
                and isinstance(previous.payload, LifecycleTransitionedPayload)
            ):
                transition = require_transition(
                    workflow_definition_id,
                    previous.payload.from_stage,
                    previous.payload.transition_id,
                )
                coherent = transition.coherent_checkpoint
            elif payload.checkpoint_kind == "human_decision":
                coherent = (
                    previous is not None
                    and previous.event_type == "human_decision.resolved"
                )
            elif payload.checkpoint_kind == "recovery":
                coherent = (
                    previous is not None
                    and previous.event_type == "recovery.completed"
                )
            if not coherent:
                raise ReducerError("Passport checkpoint boundary is not coherent")
            if payload.stage != stage or payload.based_on_revision != revision:
                raise ReducerError("Passport does not bind the accepted stage/revision")
            if payload.parent_passport_sha256 != current_passport:
                raise ReducerError("Passport parent is not current")
            if payload.supersedes_passport_sha256 != current_passport:
                raise ReducerError("Passport supersession is not linear")
            if payload.passport_sha256 in passports:
                raise ReducerError("Passport was already accepted")
            passports.append(payload.passport_sha256)
            current_passport = payload.passport_sha256
            current_passport_stage = payload.stage
            fresh_until = payload.fresh_until
        elif event.event_type == "resume.accepted":
            assert isinstance(payload, ResumeAcceptedPayload)
            if payload.passport_sha256 != current_passport:
                raise ReducerError("resume Passport is stale")
            if payload.passport_sha256 in consumed_passports:
                raise ReducerError("resume Passport was already consumed")
            if current_passport_stage != stage:
                raise ReducerError("resume Passport stage is stale")
            if fresh_until and _parse_utc(event.occurred_at) > _parse_utc(fresh_until):
                raise ReducerError("resume Passport evidence is expired")
            consumed_passports.append(payload.passport_sha256)
        elif event.event_type == "recovery.completed":
            assert isinstance(payload, RecoveryCompletedPayload)
            if (
                payload.prior_valid_revision != revision
                or payload.prior_valid_head_sha256 != head
            ):
                raise ReducerError("recovery event does not bind the accepted prefix")

        canonical_event_sha256.append(event.event_sha256)
        revision = event.resulting_revision
        head = event.event_sha256
        accepted_event_ids.add(event.event_id)

    effective_now = now
    if effective_now is not None and effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=UTC)
    if fresh_until and effective_now and effective_now > _parse_utc(fresh_until):
        blockers["evidence-expired"] = BlockerState(code="evidence-expired")

    projected_proposals, accepted_proposals, rejected_proposals, commit_cursor, order_gap = (
        _recompute_proposal_order(phase4_assignments, phase4_proposals)
    )
    if order_gap and phase4_proposals:
        blockers["proposal-order-gap"] = BlockerState(code="proposal-order-gap")

    if recovery_health == "recoverable_tail":
        blockers["tail-recovery-required"] = BlockerState(
            code="tail-recovery-required"
        )
        next_transitions = ["recover"]
    elif recovery_health == "blocked":
        blockers["recovery-blocked"] = BlockerState(code="recovery-blocked")
        next_transitions = []
    elif blockers:
        next_transitions = []
    else:
        next_transitions = list(legal_transitions(workflow_definition_id, stage))
    current_assignments = [
        item for item in phase4_assignments.values() if item.status != "superseded"
    ]
    terminal_assignment_ids = {
        item.assignment_id for item in projected_proposals if item.effective_status in {"accepted", "rejected"}
    }
    required_gate_satisfied = not any(
        item.assignment.completion_contract.requires_human_gate
        for item in current_assignments
    ) or any(gate.required and gate.verdict == "PASS" for gate in gates.values())
    ready_panels_satisfied = all(
        manifest.status != "ready"
        or any(
            matrix.panel_manifest_sha256 == manifest.manifest_sha256
            for matrix in panel_syntheses
        )
        for manifest in panel_manifests
    )
    if failed_gate_ids:
        status = "FAIL"
    elif blockers:
        status: Literal["RUNNING", "PASS", "FAIL", "BLOCKED"] = "BLOCKED"
    elif stage == "completed":
        status = "PASS"
    elif phase4_event_seen and current_assignments and all(
        item.assignment_id in terminal_assignment_ids for item in current_assignments
    ) and required_gate_satisfied and ready_panels_satisfied:
        status = "PASS"
    else:
        status = "RUNNING"
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
        active_attempts=[
            item
            if isinstance(item, Phase4ActiveAttemptState)
            else AttemptState(
                attempt_id=item.attempt_id,
                base_revision=item.base_revision,
                consumed_sha256=list(item.consumed_sha256),
            )
            for item in attempts.values()
        ],
        legal_next_transitions=next_transitions,
        accepted_artifact_manifest_sha256=artifacts,
        accepted_passport_sha256=passports,
        consumed_passport_sha256=consumed_passports,
        execution_mode=execution_mode,  # type: ignore[arg-type]
        execution_provenance=execution_provenance,
        role_catalog_sha256=role_catalog_sha256,
        policy_sha256=policy_sha256,
        dag_sha256=dag_sha256,
        assignments=tuple(phase4_assignments.values()),
        assignment_revisions=tuple(assignment_history),
        attempts=tuple(phase4_attempt_history),
        proposals=projected_proposals,
        accepted_proposal_sha256=accepted_proposals,
        rejected_proposal_sha256=rejected_proposals,
        deterministic_commit_cursor=commit_cursor,  # type: ignore[arg-type]
        panel_reports=tuple(panel_reports),
        panel_syntheses=tuple(panel_syntheses),
        panel_manifests=tuple(panel_manifests),
        host_identity_receipts=tuple(host_identity_receipts),
        human_authorities=tuple(human_authorities),
        blocker_release_history=tuple(blocker_release_history),
        canonical_event_sha256=tuple(canonical_event_sha256),
        accepted_evidence_sha256=tuple(dict.fromkeys(accepted_evidence_sha256)),
        hook_observations=tuple(hook_observations),
        gates=tuple(gates.values()),
        human_decision_history=tuple(human_decision_history),
        status=status,
    )
