"""Pure reduction of accepted canonical events into runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from arw.models import (
    AssignmentPreparedPayload,
    AssignmentSupersededPayload,
    AttemptClosedPayload,
    AttemptLifecyclePayload,
    AttemptPreparedPayload,
    AttemptStartedPayload,
    ArtifactAcceptedPayload,
    CanonicalEvent,
    ExecutionModeSelectedPayload,
    GateEvaluatedPayload,
    HookObservedPayload,
    HumanDecisionRequestedPayload,
    HumanDecisionRecordedPayload,
    HumanDecisionResolvedPayload,
    LifecycleTransitionedPayload,
    PassportAcceptedPayload,
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
from arw.workflows import (
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
    decision: object
    source_event_id: str


class HumanDecisionState(StrictModel):
    decision_id: StableRuntimeId
    decision_kind: str
    gate_id: StableRuntimeId
    subject_sha256: Sha256
    applicable_transition: StableRuntimeId
    scope: str
    rationale: str
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
    active_attempts: list[AttemptState] = Field(default_factory=list)
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


def _phase4_attempt_status(attempt_id: str, history: list[AttemptLifecycleState]) -> str | None:
    for item in reversed(history):
        if item.attempt_id == attempt_id:
            return item.status
    return None


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
    phase4_proposals: list[ProposalState] = []
    panel_reports: list[object] = []
    panel_syntheses: list[object] = []
    hook_observations: list[object] = []
    gates: dict[str, GateState] = {}
    failed_gate_ids: set[str] = set()
    human_decision_history: list[HumanDecisionState] = []
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
            if attempt.attempt_id in attempt_ids:  # type: ignore[attr-defined]
                raise ReducerError("attempt ID was already used")
            if attempt.assignment_id != payload.assignment_id:  # type: ignore[attr-defined]
                raise ReducerError("attempt assignment identity differs")
            previous_attempts = [
                item
                for item in phase4_attempt_history
                if item.assignment_id == payload.assignment_id
            ]
            if attempt.attempt_number > 1:  # type: ignore[attr-defined]
                if not previous_attempts or max(item.attempt_number for item in previous_attempts) != attempt.attempt_number - 1:  # type: ignore[attr-defined]
                    raise ReducerError("retry must follow the immediately preceding attempt")
                if any(item.status not in {"failed", "interrupted", "force_terminated"} for item in previous_attempts if item.attempt_number == attempt.attempt_number - 1):
                    raise ReducerError("retry requires a terminal repairable attempt")
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
        elif event.event_type == "attempt.lifecycle":
            assert isinstance(payload, AttemptLifecyclePayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("attempt lifecycle references an unknown assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("attempt lifecycle assignment digest is stale")
            known = attempts.get(payload.attempt_id)
            if known is None and _phase4_attempt_status(payload.attempt_id, phase4_attempt_history) is None:
                raise ReducerError("attempt lifecycle references an unknown attempt")
            if payload.attempt_number > 1 and not any(
                item.assignment_id == payload.assignment_id
                and item.attempt_number == payload.attempt_number - 1
                and item.status in {"failed", "interrupted", "force_terminated"}
                for item in phase4_attempt_history
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
        elif event.event_type == "proposal.accepted":
            assert isinstance(payload, ProposalAcceptedPayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("proposal cannot precede its assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("proposal assignment digest is stale")
            attempt_status = _phase4_attempt_status(payload.attempt_id, phase4_attempt_history)
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
            if any(item.proposal_sha256 == payload.proposal_sha256 for item in phase4_proposals):
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
        elif event.event_type == "proposal.rejected":
            assert isinstance(payload, ProposalRejectedPayload)
            phase4_event_seen = True
            assignment = phase4_assignments.get(payload.assignment_id)
            if assignment is None:
                raise ReducerError("proposal rejection cannot precede its assignment")
            if assignment.assignment_sha256 != payload.assignment_sha256:
                raise ReducerError("proposal rejection assignment digest is stale")
            if any(item.proposal_sha256 == payload.proposal_sha256 for item in phase4_proposals):
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
        elif event.event_type == "review.report_accepted":
            assert isinstance(payload, ReviewReportAcceptedPayload)
            phase4_event_seen = True
            report_id = payload.report.report_id  # type: ignore[attr-defined]
            if any(item.report_id == report_id for item in panel_reports):  # type: ignore[attr-defined]
                raise ReducerError("review report ID was already recorded")
            panel_reports.append(payload.report)
        elif event.event_type == "review.synthesis_accepted":
            assert isinstance(payload, ReviewSynthesisAcceptedPayload)
            phase4_event_seen = True
            matrix = payload.finding_matrix
            report_hashes = {item.report_sha256 for item in panel_reports}  # type: ignore[attr-defined]
            if not set(matrix.synthesis.source_report_sha256) <= report_hashes:  # type: ignore[attr-defined]
                raise ReducerError("synthesis references an unaccepted review report")
            panel_syntheses.append(matrix)
            if matrix.gate_verdict == "BLOCKED":  # type: ignore[attr-defined]
                blockers["formal-review-blocked"] = BlockerState(
                    code="formal-review-blocked", source_event_id=event.event_id
                )
        elif event.event_type == "hook.observed":
            assert isinstance(payload, HookObservedPayload)
            phase4_event_seen = True
            if any(item.idempotency_key == payload.observation.idempotency_key for item in hook_observations):  # type: ignore[attr-defined]
                raise ReducerError("hook observation idempotency key was already recorded")
            hook_observations.append(payload.observation)
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
                decision=decision,
                source_event_id=event.event_id,
            )
            gates[gate_id] = gate
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
        elif event.event_type == "human_decision.recorded":
            assert isinstance(payload, HumanDecisionRecordedPayload)
            phase4_event_seen = True
            decision = payload.decision
            decision_id = decision.decision_id  # type: ignore[attr-defined]
            if any(item.decision_id == decision_id for item in human_decision_history):
                raise ReducerError("human decision ID was already recorded")
            predecessor = decision.supersedes_decision_id  # type: ignore[attr-defined]
            if decision.decision_kind == "correction" and not any(item.decision_id == predecessor for item in human_decision_history):  # type: ignore[attr-defined]
                raise ReducerError("correction must supersede an accepted human decision")
            human_decision_history.append(
                HumanDecisionState(
                    decision_id=decision_id,
                    decision_kind=decision.decision_kind,  # type: ignore[attr-defined]
                    gate_id=decision.gate_id,  # type: ignore[attr-defined]
                    subject_sha256=decision.subject_sha256,  # type: ignore[attr-defined]
                    applicable_transition=decision.applicable_transition,  # type: ignore[attr-defined]
                    scope=decision.scope,  # type: ignore[attr-defined]
                    rationale=decision.rationale,  # type: ignore[attr-defined]
                    source_event_id=event.event_id,
                    decision=decision,
                )
            )
            if decision.decision_kind in {"waiver", "replacement", "approval"}:  # type: ignore[attr-defined]
                for blocker_code in tuple(blockers):
                    if blocker_code == decision.gate_id or decision.scope == blocker_code:  # type: ignore[attr-defined]
                        blockers.pop(blocker_code, None)
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
    if blockers:
        status: Literal["RUNNING", "PASS", "FAIL", "BLOCKED"] = "BLOCKED"
    elif failed_gate_ids:
        status = "FAIL"
    elif stage == "completed":
        status = "PASS"
    elif phase4_event_seen and current_assignments and all(
        item.assignment_id in terminal_assignment_ids for item in current_assignments
    ):
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
        # Keep the Phase 2 passport/status compatibility projection narrow;
        # Phase 4 assignment-bound lifecycle detail lives in ``attempts``.
        active_attempts=[
            AttemptState(
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
        hook_observations=tuple(hook_observations),
        gates=tuple(gates.values()),
        human_decision_history=tuple(human_decision_history),
        status=status,
    )
