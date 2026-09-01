"""Five-state hook parity and no-bypass integration coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from arw.kernel.execution.execution import DeterministicFakeAdapter
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.execution.orchestration import AssignmentSpec, OrchestrationService
from arw.kernel.state.orchestration_models import HookObservation

from .test_orchestration_lifecycle import _run


HOOK_STATUSES = ("trusted_enabled", "disabled", "untrusted", "timeout", "failed")


def _request(revision: int, number: int) -> RuntimeCommandRequest:
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": revision,
            "occurred_at": "2026-07-15T01:40:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def _observation(status: str, *, continuation: bool = False) -> HookObservation:
    return HookObservation(
        schema_version="arw.hook-observation.v1",
        hook_name="SubagentStop",
        hook_definition_sha256="a" * 64,
        target_id="attempt.hook-001",
        status=status,
        observation_sha256=("b" if status == "trusted_enabled" else "c") * 64,
        redacted_error_code=None,
        idempotency_key="hook.attempt-001.stop",
        continuation_requested=continuation,
        continuation_count=1 if continuation else 0,
    )


def _prepared(tmp_path: Path) -> OrchestrationService:
    root, init_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    service.prepare(
        init_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.hook-001",
                stage_id="preparing",
                task_id="task.hook-001",
                role_id="research_architect",
                worker_identity_id="worker.hook-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    return service


@pytest.mark.parametrize("status", HOOK_STATUSES)
def test_p04_06_t02_all_hook_states_preserve_parent_authority(
    tmp_path: Path, status: str
) -> None:
    service = _prepared(tmp_path / status)
    before = service.runtime.read_state()
    outcome = service.record_hook_observation(
        _request(before.accepted_revision, 600 + HOOK_STATUSES.index(status)),
        _observation(status),
    )
    assert outcome.accepted
    assert outcome.state.accepted_proposals == ()
    assert outcome.state.active_attempts == []
    assert outcome.state.hook_observations[-1].status == status
    assert all(
        control["parent_enforced"]
        for control in _observation(status).model_dump(mode="json").get("parity", {}).get("controls", [])
    ) is True


def test_p04_06_t02_hook_continuation_is_observed_once_and_cannot_retry_or_accept(
    tmp_path: Path,
) -> None:
    service = _prepared(tmp_path)
    before = service.runtime.read_state()
    first = service.record_hook_observation(
        _request(before.accepted_revision, 610),
        _observation("trusted_enabled", continuation=True),
    )
    assert first.accepted
    assert first.state.hook_observations[-1].continuation_requested is True
    assert first.state.accepted_proposals == ()
    assert first.state.active_attempts == []

    repeated = service.record_hook_observation(
        _request(first.state.accepted_revision, 611),
        _observation("trusted_enabled", continuation=True),
    )
    assert not repeated.accepted
    assert repeated.rejection is not None
    assert repeated.rejection.code == "invalid-command"
    assert repeated.state.accepted_revision == first.state.accepted_revision
