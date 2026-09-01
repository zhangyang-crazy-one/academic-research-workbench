"""Deterministic, bounded Phase 4 scheduler tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arw.kernel.execution.execution import (
    DispatchSpec,
    DeterministicFakeAdapter,
    ExecutionPolicySnapshot,
    FakeDispatchPlan,
    HostResult,
    PermissionDenied,
    ProcessFailure,
)
from arw.kernel.execution.scheduler import DEFAULT_SCHEDULER_POLICY, DeterministicScheduler


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

    scheduler = DeterministicScheduler(adapter)
    outcomes = asyncio.run(scheduler.run((retry_spec, denied_spec)))

    retry_outcome = outcomes[0]
    denied_outcome = outcomes[1]
    assert retry_outcome.status == "failed"
    assert len(retry_outcome.attempts) == 1
    assert retry_outcome.attempts[0].retry_eligible is True
    assert len(adapter.dispatches_for("retryable")) == 1
    assert denied_outcome.status == "failed"
    assert denied_outcome.retry_eligible is False
    assert len(adapter.dispatches_for("denied")) == 1

    # Only a caller that has already materialized the fresh canonical attempt
    # may submit the second generation.
    retry_generation = asyncio.run(scheduler.run((retry_spec.for_retry(2),)))
    assert retry_generation[0].status == "completed"
    assert retry_generation[0].retry_eligible is False
    assert len(adapter.dispatches_for("retryable")) == 2


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

    async def run_generations():
        scheduler = DeterministicScheduler(adapter)
        first = (await scheduler.run((spec,)))[0]
        second = (await scheduler.run((spec.for_retry(2),)))[0]
        return first, second

    outcome, retry = asyncio.run(run_generations())

    assert adapter.lifecycle_for(spec.assignment_id) == (
        "dispatch",
        "request_cancel",
        "force_terminate",
        "dispatch",
        "request_cancel",
        "force_terminate",
    )
    assert outcome.status == "force_terminated"
    assert outcome.classification == "rejected_stale"
    assert outcome.late_result is False
    assert outcome.retry_eligible is True
    assert retry.status == "force_terminated"
    assert retry.retry_eligible is False
    assert len(adapter.dispatches_for(spec.assignment_id)) == 2
    assert not hasattr(adapter, "append_event")
    assert not hasattr(adapter, "journal")


def test_p04_03_t01_force_failure_is_interrupted_not_force_terminated() -> None:
    spec = _spec(
        "force-fails",
        layer=0,
        ordinal=0,
        timeout_seconds=0.001,
        cancellation_grace_seconds=0.001,
    )

    class ForceFailureAdapter(DeterministicFakeAdapter):
        async def force_terminate(self, spec: DispatchSpec) -> None:
            self._lifecycle.setdefault(spec.assignment_id, []).append("force_terminate")
            raise RuntimeError("force boundary unavailable")

    adapter = ForceFailureAdapter(
        {
            spec.assignment_id: FakeDispatchPlan(
                wait_for_cancel=True,
                cooperative_cancel=False,
            )
        }
    )
    outcome = asyncio.run(DeterministicScheduler(adapter).run((spec,)))[0]

    assert outcome.status == "interrupted"
    assert outcome.force_termination_requested is False
    assert outcome.classification == "rejected_stale"
    assert outcome.error is not None and "force termination failed" in outcome.error


def test_p04_03_t01_parent_cancel_observation_precedes_adapter_signal() -> None:
    spec = _spec(
        "ordered-cancel",
        layer=0,
        ordinal=0,
        timeout_seconds=0.001,
        cancellation_grace_seconds=0.001,
    )
    adapter = DeterministicFakeAdapter(
        {
            spec.assignment_id: FakeDispatchPlan(
                wait_for_cancel=True,
                cooperative_cancel=True,
            )
        }
    )
    events: list[str] = []

    async def observe(_spec: DispatchSpec, _deadline: float) -> None:
        events.append("parent-cancel-recorded")

    original_request_cancel = adapter.request_cancel

    async def request_cancel_with_observation(spec: DispatchSpec) -> None:
        events.append("adapter-cancel-called")
        await original_request_cancel(spec)

    adapter.request_cancel = request_cancel_with_observation  # type: ignore[method-assign]
    asyncio.run(
        DeterministicScheduler(adapter, cancel_observer=observe).run((spec,))
    )

    assert events == ["parent-cancel-recorded", "adapter-cancel-called"]


def test_p04_03_t01_frozen_attempt_budget_overrides_scheduler_default() -> None:
    policy = ExecutionPolicySnapshot(max_attempts_per_assignment=1)
    spec = DispatchSpec(
        assignment_id="frozen-one",
        attempt_id="attempt-frozen-one-1",
        acceptance_key=(0, 0),
        assignment_path=Path("assignments/frozen-one.json"),
        attempt_root=Path("attempts/frozen-one"),
        policy_snapshot=policy,
    )
    adapter = DeterministicFakeAdapter(
        {spec.assignment_id: FakeDispatchPlan(error=ProcessFailure("failed"))}
    )

    outcome = asyncio.run(DeterministicScheduler(adapter).run((spec,)))[0]

    assert outcome.status == "failed"
    assert outcome.retry_eligible is False
    assert len(adapter.dispatches_for(spec.assignment_id)) == 1


def test_p04_03_t01_failed_parent_cancel_record_never_signals_host() -> None:
    spec = _spec(
        "cancel-record-fails",
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
            )
        }
    )

    async def reject_record(_spec: DispatchSpec, _deadline: float) -> None:
        raise RuntimeError("canonical append rejected")

    outcome = asyncio.run(
        DeterministicScheduler(adapter, cancel_observer=reject_record).run((spec,))
    )[0]

    assert adapter.lifecycle_for(spec.assignment_id) == ("dispatch",)
    assert outcome.status == "interrupted"
    assert outcome.retry_eligible is False
    assert outcome.error is not None and "parent cancellation record failed" in outcome.error
