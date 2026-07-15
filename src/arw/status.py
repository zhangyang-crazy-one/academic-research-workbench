"""Strict read-only projections of the pure runtime reducer state."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from arw.reducer import (
    AssignmentState,
    AttemptLifecycleState,
    AttemptState,
    BlockerState,
    GateState,
    HumanDecisionState,
    PendingDecisionState,
    ProposalState,
    RuntimeState,
)
from arw.models import RecoveryHealth, RunId, Sha256, StableRuntimeId, StrictModel


class StatusReport(StrictModel):
    schema_version: Literal["1.0.0"]
    reducer_version: Literal["1.0.0"]
    run_id: RunId
    workflow_definition_id: StableRuntimeId
    current_stage: StableRuntimeId
    accepted_revision: Annotated[int, Field(ge=0)]
    ledger_head_sha256: Sha256
    current_passport_sha256: Sha256 | None
    recovery_health: RecoveryHealth
    blockers: list[BlockerState]
    pending_human_decisions: list[PendingDecisionState]
    active_attempts: list[AttemptState]
    legal_next_transitions: list[StableRuntimeId]
    status: Literal["RUNNING", "PASS", "FAIL", "BLOCKED"]
    execution_mode: Literal[
        "native_profile",
        "assignment_injected_subagent",
        "degraded_inline",
        "blocked",
    ] | None
    execution_provenance: str | None
    role_catalog_sha256: Sha256 | None
    policy_sha256: Sha256 | None
    dag_sha256: Sha256 | None
    assignments: tuple[AssignmentState, ...]
    assignment_revisions: tuple[AssignmentState, ...]
    attempts: tuple[AttemptLifecycleState, ...]
    proposals: tuple[ProposalState, ...]
    accepted_proposal_sha256: tuple[Sha256, ...]
    rejected_proposal_sha256: tuple[Sha256, ...]
    deterministic_commit_cursor: tuple[int, int, StableRuntimeId] | None
    panel_reports: tuple[object, ...]
    panel_syntheses: tuple[object, ...]
    hook_observations: tuple[object, ...]
    gates: tuple[GateState, ...]
    human_decision_history: tuple[HumanDecisionState, ...]


def build_status_report(state: RuntimeState) -> StatusReport:
    """Project a reduced state without recalculating any runtime decision."""

    return StatusReport(
        schema_version=state.schema_version,
        reducer_version=state.reducer_version,
        run_id=state.run_id,
        workflow_definition_id=state.workflow_definition_id,
        current_stage=state.stage,
        accepted_revision=state.accepted_revision,
        ledger_head_sha256=state.ledger_head_sha256,
        current_passport_sha256=state.current_passport_sha256,
        recovery_health=state.recovery_health,
        blockers=list(state.blockers),
        pending_human_decisions=list(state.pending_human_decisions),
        active_attempts=list(state.active_attempts),
        legal_next_transitions=list(state.legal_next_transitions),
        status=state.status,
        execution_mode=state.execution_mode,
        execution_provenance=state.execution_provenance,
        role_catalog_sha256=state.role_catalog_sha256,
        policy_sha256=state.policy_sha256,
        dag_sha256=state.dag_sha256,
        assignments=state.assignments,
        assignment_revisions=state.assignment_revisions,
        attempts=state.attempts,
        proposals=state.proposals,
        accepted_proposal_sha256=state.accepted_proposal_sha256,
        rejected_proposal_sha256=state.rejected_proposal_sha256,
        deterministic_commit_cursor=state.deterministic_commit_cursor,
        panel_reports=state.panel_reports,
        panel_syntheses=state.panel_syntheses,
        hook_observations=state.hook_observations,
        gates=state.gates,
        human_decision_history=state.human_decision_history,
    )


def render_status_text(report: StatusReport) -> str:
    """Render only fields already present in the strict report."""

    passport = report.current_passport_sha256 or "none"
    blockers = ", ".join(item.code for item in report.blockers) or "none"
    decisions = ", ".join(item.decision_id for item in report.pending_human_decisions) or "none"
    attempts = ", ".join(item.attempt_id for item in report.active_attempts) or "none"
    transitions = ", ".join(report.legal_next_transitions) or "none"
    return "\n".join(
        (
            f"run: {report.run_id}",
            f"workflow: {report.workflow_definition_id}",
            f"stage: {report.current_stage}",
            f"revision: {report.accepted_revision}",
            f"ledger head: {report.ledger_head_sha256}",
            f"passport: {passport}",
            f"recovery: {report.recovery_health}",
            f"status: {report.status}",
            f"execution mode: {report.execution_mode or 'unset'}",
            f"blockers: {blockers}",
            f"pending decisions: {decisions}",
            f"active attempts: {attempts}",
            f"legal transitions: {transitions}",
            f"contract: schema {report.schema_version}, reducer {report.reducer_version}",
        )
    ) + "\n"
