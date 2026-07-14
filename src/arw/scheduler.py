"""Bounded, deterministic parent-side scheduling primitives.

This module buffers host observations and returns them in the frozen
assignment order.  It deliberately has no journal or canonical-write
dependency; a later runtime may decide how to record these observations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from arw.execution import (
    DEFAULT_EXECUTION_POLICY,
    AdapterFailure,
    DispatchSpec,
    ExecutionAdapter,
    ExecutionPolicySnapshot,
    HostResult,
)


RETRYABLE_FAILURES = frozenset({"timeout", "process_failure", "repairable_envelope"})
NON_RETRYABLE_FAILURES = frozenset(
    {
        "permission_denied",
        "stale_inputs",
        "superseded",
        "cancelled",
        "scientific_disagreement",
        "identity_mismatch",
        "policy_violation",
        "digest_mismatch",
    }
)

SchedulerPolicy = ExecutionPolicySnapshot
DEFAULT_SCHEDULER_POLICY = DEFAULT_EXECUTION_POLICY
AttemptStatus = Literal[
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "force_terminated",
]
ObservationClassification = Literal["observed", "rejected_stale"]


def retry_is_eligible(
    reason: str | None,
    *,
    attempt_number: int,
    policy: SchedulerPolicy = DEFAULT_SCHEDULER_POLICY,
) -> bool:
    """Return whether the frozen policy permits its one automatic retry."""

    return (
        reason in RETRYABLE_FAILURES
        and attempt_number < policy.max_attempts_per_assignment
    )


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    assignment_id: str
    attempt_id: str
    attempt_number: int
    status: AttemptStatus
    result: HostResult | None
    failure_reason: str | None
    error: str | None
    retry_eligible: bool
    cancellation_requested: bool = False
    force_termination_requested: bool = False
    classification: ObservationClassification = "observed"
    late_result: bool = False


@dataclass(frozen=True, slots=True)
class ScheduledOutcome:
    """The terminal observation plus immutable attempt history for one assignment."""

    assignment_id: str
    acceptance_key: tuple[int, int, str]
    status: AttemptStatus
    result: HostResult | None
    attempts: tuple[AttemptOutcome, ...]
    retry_reason: str | None
    retry_eligible: bool
    classification: ObservationClassification
    late_result: bool


def _failure_reason(error: BaseException) -> str:
    reason = getattr(error, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    return "process_failure"


def _error_text(error: BaseException) -> str:
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


class DeterministicScheduler:
    """Run attempts concurrently while returning frozen-order observations."""

    def __init__(
        self,
        adapter: ExecutionAdapter,
        *,
        policy: SchedulerPolicy = DEFAULT_SCHEDULER_POLICY,
    ) -> None:
        self.adapter = adapter
        self.policy = policy

    async def run(self, specs: Iterable[DispatchSpec]) -> tuple[ScheduledOutcome, ...]:
        frozen_specs = tuple(specs)
        self._validate_specs(frozen_specs)
        if not frozen_specs:
            return ()

        first_attempts = await self._collect(frozen_specs)
        retry_specs = tuple(
            spec.for_retry(spec.attempt_number + 1)
            for spec in frozen_specs
            if first_attempts[spec.assignment_id].retry_eligible
        )
        retry_attempts = await self._collect(retry_specs) if retry_specs else {}

        outcomes: list[ScheduledOutcome] = []
        for spec in sorted(frozen_specs, key=lambda item: item.frozen_order_key):
            first = first_attempts[spec.assignment_id]
            attempts = (first,)
            final = first
            if spec.assignment_id in retry_attempts:
                final = retry_attempts[spec.assignment_id]
                attempts = (first, final)
            outcomes.append(
                ScheduledOutcome(
                    assignment_id=spec.assignment_id,
                    acceptance_key=spec.frozen_order_key,
                    status=final.status,
                    result=final.result,
                    attempts=attempts,
                    retry_reason=first.failure_reason,
                    retry_eligible=final.retry_eligible,
                    classification=final.classification,
                    late_result=final.late_result,
                )
            )
        return tuple(outcomes)

    async def schedule(self, specs: Iterable[DispatchSpec]) -> tuple[ScheduledOutcome, ...]:
        """Alias used by parent runtimes that call the component a scheduler."""

        return await self.run(specs)

    def _validate_specs(self, specs: tuple[DispatchSpec, ...]) -> None:
        assignment_ids = [spec.assignment_id for spec in specs]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("assignment IDs must be unique in one schedule")
        keys = [spec.frozen_order_key for spec in specs]
        if len(keys) != len(set(keys)):
            raise ValueError("frozen acceptance keys must be unique")
        for spec in specs:
            if spec.policy_snapshot.max_attempts_per_assignment > self.policy.max_attempts_per_assignment:
                raise ValueError("spec policy permits more attempts than the scheduler policy")

    async def _collect(
        self, specs: tuple[DispatchSpec, ...]
    ) -> dict[str, AttemptOutcome]:
        if not specs:
            return {}
        semaphore = asyncio.Semaphore(self.policy.max_concurrency)
        completed: dict[str, AttemptOutcome] = {}

        async def one(spec: DispatchSpec) -> None:
            async with semaphore:
                completed[spec.assignment_id] = await self._run_attempt(spec)

        async with asyncio.TaskGroup() as group:
            for spec in specs:
                group.create_task(one(spec))
        return completed

    async def _run_attempt(self, spec: DispatchSpec) -> AttemptOutcome:
        host_task = asyncio.create_task(self.adapter.dispatch(spec))
        try:
            result = await asyncio.wait_for(
                asyncio.shield(host_task), timeout=spec.effective_timeout_seconds
            )
        except asyncio.TimeoutError as first_timeout:
            return await self._cancel_after_timeout(spec, host_task, first_timeout)
        except Exception as error:
            reason = _failure_reason(error)
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="failed",
                result=None,
                failure_reason=reason,
                error=_error_text(error),
                retry_eligible=retry_is_eligible(
                    reason, attempt_number=spec.attempt_number, policy=self.policy
                ),
            )

        if result.attempt_id != spec.attempt_id:
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="failed",
                result=result,
                failure_reason="identity_mismatch",
                error="host result attempt_id does not match dispatch spec",
                retry_eligible=False,
                classification="rejected_stale",
                late_result=True,
            )
        return AttemptOutcome(
            assignment_id=spec.assignment_id,
            attempt_id=spec.attempt_id,
            attempt_number=spec.attempt_number,
            status="completed",
            result=result,
            failure_reason=None,
            error=None,
            retry_eligible=False,
        )

    async def _cancel_after_timeout(
        self,
        spec: DispatchSpec,
        host_task: asyncio.Task[HostResult],
        first_timeout: BaseException,
    ) -> AttemptOutcome:
        cancel_error: str | None = None
        try:
            await self.adapter.request_cancel(spec)
        except Exception as error:
            cancel_error = _error_text(error)

        try:
            late_result = await asyncio.wait_for(
                asyncio.shield(host_task),
                timeout=spec.effective_cancellation_grace_seconds,
            )
        except asyncio.TimeoutError:
            force_error: str | None = None
            try:
                await self.adapter.force_terminate(spec)
            except Exception as error:
                force_error = _error_text(error)
            finally:
                host_task.cancel()
                await asyncio.gather(host_task, return_exceptions=True)
            details = [f"initial timeout: {_error_text(first_timeout)}"]
            if cancel_error:
                details.append(f"cooperative cancellation failed: {cancel_error}")
            if force_error:
                details.append(f"force termination failed: {force_error}")
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="force_terminated",
                result=None,
                failure_reason="cancelled",
                error="; ".join(details),
                retry_eligible=False,
                cancellation_requested=True,
                force_termination_requested=True,
                classification="rejected_stale",
            )
        except Exception as error:
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="cancelled",
                result=None,
                failure_reason="cancelled",
                error=_error_text(error),
                retry_eligible=False,
                cancellation_requested=True,
                classification="rejected_stale",
            )

        return AttemptOutcome(
            assignment_id=spec.assignment_id,
            attempt_id=spec.attempt_id,
            attempt_number=spec.attempt_number,
            status="cancelled",
            result=late_result,
            failure_reason="cancelled",
            error=cancel_error,
            retry_eligible=False,
            cancellation_requested=True,
            classification="rejected_stale",
            late_result=True,
        )


BoundedScheduler = DeterministicScheduler

