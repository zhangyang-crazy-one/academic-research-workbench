"""Cold replay, orphan, retry, and stale-result integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from arw.kernel.state.models import RuntimeCommandRequest
from arw.orchestration import OrchestrationError, OrchestrationService
from arw.kernel.state.orchestration_models import AttemptDescriptor
from arw.execution import DeterministicFakeAdapter
from arw.journal import replay_run

from .test_orchestration_lifecycle import AssignmentSpec, _run


def _request(revision: int, number: int) -> RuntimeCommandRequest:
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": revision,
            "occurred_at": f"2026-07-15T01:10:{number % 60:02d}Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def test_p04_04_t03_cold_replay_does_not_read_projection_state(tmp_path: Path) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.replay-001",
                stage_id="preparing",
                task_id="task.replay-001",
                role_id="research_architect",
                worker_identity_id="worker.replay-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    expected = service.runtime.read_state()
    projection = root / "projection" / "status.json"
    projection.parent.mkdir()
    projection.write_text('{"status":"tampered"}\n', encoding="utf-8")
    projection.unlink()

    replayed = OrchestrationService(root, adapter=DeterministicFakeAdapter({})).runtime.read_state()
    assert replayed == expected
    assert replayed.assignments[0].assignment_id == prepared.assignments[0].assignment_id


@pytest.mark.parametrize("crash_after", [1, 2, 3, 4, 5])
def test_p04_04_t03_prepare_saga_resumes_every_accepted_prefix_once(
    tmp_path: Path, crash_after: int
) -> None:
    root, prepare_request = _run(tmp_path)
    assignments = (
        AssignmentSpec(
            assignment_id="assignment.saga-001",
            stage_id="preparing",
            task_id="task.saga-001",
            role_id="research_architect",
            worker_identity_id="worker.saga-001",
            acceptance_key=(0, 0),
        ),
        AssignmentSpec(
            assignment_id="assignment.saga-002",
            stage_id="preparing",
            task_id="task.saga-002",
            role_id="experiment_designer",
            worker_identity_id="worker.saga-002",
            acceptance_key=(0, 1),
        ),
    )
    crashing = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    original_transition = crashing.runtime.execute_transition
    original_append = crashing.runtime.append_phase4_event
    accepted = 0

    def maybe_crash(outcome):
        nonlocal accepted
        if outcome.accepted:
            accepted += 1
            if accepted == crash_after:
                raise RuntimeError("injected preparation crash")
        return outcome

    def transition(request):
        return maybe_crash(original_transition(request))

    def append(request, *, event_type, payload, **kwargs):
        return maybe_crash(
            original_append(
                request, event_type=event_type, payload=payload, **kwargs
            )
        )

    crashing.runtime.execute_transition = transition  # type: ignore[method-assign]
    crashing.runtime.append_phase4_event = append  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="injected preparation crash"):
        crashing.prepare(prepare_request, assignments=assignments)

    resumed_service = OrchestrationService(
        root, adapter=DeterministicFakeAdapter({})
    )
    resumed = resumed_service.prepare(prepare_request, assignments=assignments)
    assert resumed.state.stage == "prepared"
    assert [item.assignment_id for item in resumed.state.assignments] == [
        item.assignment_id for item in assignments
    ]
    revision = resumed.state.accepted_revision
    repeated = resumed_service.prepare(prepare_request, assignments=assignments)
    assert repeated.state.accepted_revision == revision
    assert replay_run(root).revision == revision


def test_p04_04_t03_prepare_saga_rejects_intent_drift(tmp_path: Path) -> None:
    root, prepare_request = _run(tmp_path)
    original = AssignmentSpec(
        assignment_id="assignment.saga-drift",
        stage_id="preparing",
        task_id="task.saga-drift",
        role_id="research_architect",
        worker_identity_id="worker.saga-drift",
        acceptance_key=(0, 0),
    )
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    service.prepare(prepare_request, assignments=(original,))
    drifted = AssignmentSpec(
        **{
            **{name: getattr(original, name) for name in original.__dataclass_fields__},
            "capability_ids": ("files.read", "files.search"),
        }
    )

    with pytest.raises(OrchestrationError, match="intent differs"):
        OrchestrationService(root, adapter=DeterministicFakeAdapter({})).prepare(
            prepare_request, assignments=(drifted,)
        )


def test_p04_04_t03_orphan_attempt_is_interrupted_and_requeued_once(tmp_path: Path) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.replay-002",
                stage_id="preparing",
                task_id="task.replay-002",
                role_id="research_architect",
                worker_identity_id="worker.replay-002",
                acceptance_key=(0, 0),
            ),
        ),
    )
    assignment = prepared.assignments[0]
    orphan = AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id=assignment.assignment_id,
        attempt_id="attempt.replay-002.001",
        attempt_number=1,
        proposal_nonce="nonce.replay-002.001",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )
    attempt_request = _request(prepared.state.accepted_revision, 410)
    started = service.prepare_attempt(attempt_request, assignment=assignment, attempt=orphan)
    assert started.accepted

    dispatched = service.record_attempt_lifecycle(
        _request(started.state.accepted_revision, 411),
        assignment=assignment,
        attempt=orphan,
        status="active",
    )
    assert dispatched.accepted

    recovered = service.recover_orphans(_request(dispatched.state.accepted_revision, 412))
    assert [item.attempt_id for item in recovered.active_attempts] == [
        "attempt.replay-002.001.retry-2"
    ]
    assert [item.status for item in recovered.attempts[-2:]] == ["interrupted", "prepared"]
    assert any(item.status == "interrupted" for item in recovered.attempts)
    assert OrchestrationService(root, adapter=DeterministicFakeAdapter({})).runtime.read_state() == recovered

    stale_attempt = AttemptDescriptor(
        **{
            **orphan.model_dump(mode="json"),
            "status": "completed",
            "host_agent_id": "host.late",
        }
    )
    late = service.admit_proposal(
        _request(recovered.accepted_revision, 413),
        assignment=assignment,
        attempt=stale_attempt,
    )
    assert late.accepted
    assert late.event is not None and late.event.event_type == "proposal.rejected"
    assert late.state.accepted_proposals == ()
    assert late.state.rejected_proposals[-1].outcome == "rejected_stale"
    assert replay_run(root).revision == late.state.accepted_revision


def test_p04_04_t03_recovery_closes_terminal_retry_gap_idempotently(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.retry-gap",
                stage_id="preparing",
                task_id="task.retry-gap",
                role_id="research_architect",
                worker_identity_id="worker.retry-gap",
                acceptance_key=(0, 0),
            ),
        ),
    )
    assignment = prepared.assignments[0]
    first = AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id=assignment.assignment_id,
        attempt_id="attempt.retry-gap.001",
        attempt_number=1,
        proposal_nonce="nonce.retry-gap.001",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )
    opened = service.prepare_attempt(
        _request(prepared.state.accepted_revision, 420),
        assignment=assignment,
        attempt=first,
    )
    active = service.record_attempt_lifecycle(
        _request(opened.state.accepted_revision, 421),
        assignment=assignment,
        attempt=first,
        status="active",
    )
    failed = service.record_attempt_lifecycle(
        _request(active.state.accepted_revision, 422),
        assignment=assignment,
        attempt=first,
        status="failed",
        retry_reason="process_failure",
        retry_eligible=True,
    )
    recovered = service.recover_orphans(
        _request(failed.state.accepted_revision, 423)
    )
    assert [item.attempt_number for item in recovered.active_attempts] == [2]
    assert [item.status for item in recovered.attempts[-2:]] == [
        "failed",
        "prepared",
    ]
    repeated = service.recover_orphans(
        _request(recovered.accepted_revision, 424)
    )
    assert repeated.accepted_revision == recovered.accepted_revision
    assert repeated == recovered


def test_p04_04_t03_recovery_closes_exhausted_terminal_gap_once(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.exhausted-gap",
                stage_id="preparing",
                task_id="task.exhausted-gap",
                role_id="research_architect",
                worker_identity_id="worker.exhausted-gap",
                acceptance_key=(0, 0),
            ),
        ),
    )
    assignment = prepared.assignments[0]
    first = AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id=assignment.assignment_id,
        attempt_id="attempt.exhausted-gap.001",
        attempt_number=1,
        proposal_nonce="nonce.exhausted-gap.001",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )
    opened = service.prepare_attempt(
        _request(prepared.state.accepted_revision, 430),
        assignment=assignment,
        attempt=first,
    )
    failed = service.record_attempt_lifecycle(
        _request(opened.state.accepted_revision, 431),
        assignment=assignment,
        attempt=first,
        status="failed",
        retry_reason="process_failure",
        retry_eligible=True,
    )
    second = AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id=assignment.assignment_id,
        attempt_id=f"{first.attempt_id}.retry-2",
        attempt_number=2,
        proposal_nonce=f"{first.proposal_nonce}.retry-2",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )
    retried = service.prepare_attempt(
        _request(failed.state.accepted_revision, 432),
        assignment=assignment,
        attempt=second,
    )
    exhausted = service.record_attempt_lifecycle(
        _request(retried.state.accepted_revision, 433),
        assignment=assignment,
        attempt=second,
        status="failed",
        retry_eligible=False,
    )
    recovered = service.recover_orphans(
        _request(exhausted.state.accepted_revision, 434)
    )
    assert len(recovered.rejected_proposals) == 1
    assert any(
        item.code == f"attempt-blocked.{second.attempt_id}"
        for item in recovered.blockers
    )
    repeated = service.recover_orphans(
        _request(recovered.accepted_revision, 435)
    )
    assert repeated.accepted_revision == recovered.accepted_revision
