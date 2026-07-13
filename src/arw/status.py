"""Strict read-only projections of the pure runtime reducer state."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from arw.reducer import AttemptState, BlockerState, PendingDecisionState, RuntimeState
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
            f"blockers: {blockers}",
            f"pending decisions: {decisions}",
            f"active attempts: {attempts}",
            f"legal transitions: {transitions}",
            f"contract: schema {report.schema_version}, reducer {report.reducer_version}",
        )
    ) + "\n"
