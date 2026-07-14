"""Deterministic, bounded Phase 4 scheduler tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arw.execution import (
    DispatchSpec,
    DeterministicFakeAdapter,
    FakeDispatchPlan,
    HostResult,
    PermissionDenied,
    ProcessFailure,
)
from arw.scheduler import DEFAULT_SCHEDULER_POLICY, DeterministicScheduler


def _spec(
    assignment_id: str,
    *,
    layer: int,
    ordinal: int,
    timeout_seconds: float | None = None,
    cancellation_grace_seconds: float | None = None,
) -> DispatchSpec:
    return DispatchSpec(
        assignment_id=assignment_id,
        attempt_id=f"attempt-{assignment_id}-1",
        acceptance_key=(layer, ordinal),
        assignment_path=Path("assignments") / f"{assignment_id}.json",
        attempt_root=Path("attempts") / assignment_id,
        timeout_seconds=timeout_seconds,
        cancellation_grace_seconds=cancellation_grace_seconds,
    )


def _result(spec: DispatchSpec) -> HostResult:
    return HostResult(
        attempt_id=spec.attempt_id,
        host_agent_id=f"host-{spec.assignment_id}",
        proposal_path=spec.attempt_root / "result" / "proposal.json",
    )


def test_p04_03_t01_frozen_cursor_is_permutation_invariant() -> None:
    specs = tuple(
        _spec(f"task-{index:02d}", layer=index // 3, ordinal=index % 3)
        for index in range(9)
    )
    plans = {
        spec.assignment_id: FakeDispatchPlan(
            delay_seconds=(len(spec.assignment_id) % 4) * 0.001,
            result=_result(spec),
        )
        for spec in specs
    }
    adapter = DeterministicFakeAdapter(plans)

    outcomes = asyncio.run(DeterministicScheduler(adapter).run(tuple(reversed(specs))))

    assert [outcome.assignment_id for outcome in outcomes] == [
        spec.assignment_id for spec in specs
    ]
    assert adapter.max_active <= DEFAULT_SCHEDULER_POLICY.max_concurrency
    assert adapter.completion_order != [outcome.assignment_id for outcome in outcomes]
    assert all(outcome.status == "completed" for outcome in outcomes)


def test_p04_03_t01_retry_taxonomy_is_bounded() -> None:
    retry_spec = _spec("retryable", layer=0, ordinal=0)
    denied_spec = _spec("denied", layer=0, ordinal=1)
    adapter = DeterministicFakeAdapter(
        {
            retry_spec.assignment_id: (
                FakeDispatchPlan(error=ProcessFailure("child exited unexpectedly")),
                FakeDispatchPlan(),
            ),
            denied_spec.assignment_id: (
                FakeDispatchPlan(error=PermissionDenied("root denied")),
                FakeDispatchPlan(),
            ),
        }
    )

    outcomes = asyncio.run(
        DeterministicScheduler(adapter).run((retry_spec, denied_spec))
    )

    retry_outcome = outcomes[0]
    denied_outcome = outcomes[1]
    assert retry_outcome.status == "completed"
    assert len(retry_outcome.attempts) == 2
    assert retry_outcome.attempts[0].retry_eligible is True
    assert retry_outcome.attempts[1].retry_eligible is False
    assert len(adapter.dispatches_for("retryable")) == 2
    assert denied_outcome.status == "failed"
    assert denied_outcome.retry_eligible is False
    assert len(adapter.dispatches_for("denied")) == 1


def test_p04_03_t01_timeout_cancel_force_and_late_result_are_observations() -> None:
    spec = _spec(
        "late",
        layer=0,
        ordinal=0,
        timeout_seconds=0.001,
        cancellation_grace_seconds=0.001,
    )
    adapter = DeterministicFakeAdapter(
        {
            spec.assignment_id: FakeDispatchPlan(
                wait_for_cancel=True,
                cooperative_cancel=False,
                result=_result(spec),
            )
        }
    )

    outcomes = asyncio.run(DeterministicScheduler(adapter).run((spec,)))
    outcome = outcomes[0]

    assert adapter.lifecycle_for(spec.assignment_id) == (
        "dispatch",
        "request_cancel",
        "force_terminate",
    )
    assert outcome.status == "force_terminated"
    assert outcome.classification == "rejected_stale"
    assert outcome.late_result is False
    assert outcome.retry_eligible is False
    assert not hasattr(adapter, "append_event")
    assert not hasattr(adapter, "journal")
