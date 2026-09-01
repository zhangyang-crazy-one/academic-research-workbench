"""Bounded, deterministic parent-side scheduling primitives.

This module buffers host observations and returns them in the frozen
assignment order.  It deliberately has no journal or canonical-write
dependency; a later runtime may decide how to record these observations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
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
from arw.kernel.core.faults import inject


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
    "interrupted",
]
ObservationClassification = Literal["observed", "rejected_stale"]
ResultValidator = Callable[[DispatchSpec, HostResult], Awaitable[None]]


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
    error: str | None
    cancellation_requested: bool
    force_termination_requested: bool


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


def _consume_task_result(task: asyncio.Task[HostResult]) -> None:
    """Consume a detached host observation without cancelling the host."""

    try:
        task.result()
    except (BaseException, asyncio.CancelledError):
        return


class DeterministicScheduler:
    """Run attempts concurrently while returning frozen-order observations."""

    def __init__(
        self,
        adapter: ExecutionAdapter,
        *,
        policy: SchedulerPolicy = DEFAULT_SCHEDULER_POLICY,
        cancel_observer: Callable[[DispatchSpec, float], Awaitable[None]] | None = None,
        result_validator: ResultValidator | None = None,
    ) -> None:
        self.adapter = adapter
        self.policy = policy
        self.cancel_observer = cancel_observer
        self.result_validator = result_validator

    async def run(self, specs: Iterable[DispatchSpec]) -> tuple[ScheduledOutcome, ...]:
        frozen_specs = tuple(specs)
        self._validate_specs(frozen_specs)
        if not frozen_specs:
            return ()

        # Execute exactly the generation supplied by the sole-writer parent.
        # A retry is a new canonical attempt, so this component must never
        # manufacture or dispatch one on its own.
        attempt_outcomes = await self._collect(frozen_specs)

        outcomes: list[ScheduledOutcome] = []
        for spec in sorted(frozen_specs, key=lambda item: item.frozen_order_key):
            final = attempt_outcomes[spec.assignment_id]
            outcomes.append(
                ScheduledOutcome(
                    assignment_id=spec.assignment_id,
                    acceptance_key=spec.frozen_order_key,
                    status=final.status,
                    result=final.result,
                    attempts=(final,),
                    retry_reason=final.failure_reason,
                    retry_eligible=final.retry_eligible,
                    classification=final.classification,
                    late_result=final.late_result,
                    error=final.error,
                    cancellation_requested=final.cancellation_requested,
                    force_termination_requested=final.force_termination_requested,
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
        # Host dispatch is intentionally below the parent's canonical
        # ``attempt.prepared``/dispatch lifecycle events.  The guarded seam
        # allows Phase 7 to terminate this boundary deterministically without
        # giving a child authority to create a retry.
        inject("phase7.host-dispatch")
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
                    reason,
                    attempt_number=spec.attempt_number,
                    policy=spec.policy_snapshot,
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
        if self.result_validator is not None:
            try:
                await self.result_validator(spec, result)
            except Exception as error:
                reason = _failure_reason(error)
                return AttemptOutcome(
                    assignment_id=spec.assignment_id,
                    attempt_id=spec.attempt_id,
                    attempt_number=spec.attempt_number,
                    status="failed",
                    result=result,
                    failure_reason=reason,
                    error=_error_text(error),
                    retry_eligible=retry_is_eligible(
                        reason,
                        attempt_number=spec.attempt_number,
                        policy=spec.policy_snapshot,
                    ),
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
        if self.cancel_observer is not None:
            try:
                await self.cancel_observer(
                    spec,
                    asyncio.get_running_loop().time()
                    + spec.effective_cancellation_grace_seconds,
                )
            except Exception as error:
                # A failed canonical request authorizes no host action.  The
                # still-running child is detached and any late result remains
                # non-authoritative evidence for parent recovery.
                host_task.add_done_callback(_consume_task_result)
                return AttemptOutcome(
                    assignment_id=spec.assignment_id,
                    attempt_id=spec.attempt_id,
                    attempt_number=spec.attempt_number,
                    status="interrupted",
                    result=None,
                    failure_reason="cancelled",
                    error=f"parent cancellation record failed: {_error_text(error)}",
                    retry_eligible=False,
                    classification="rejected_stale",
                )
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
            late_result: HostResult | None = None
            try:
                await self.adapter.force_terminate(spec)
            except Exception as error:
                force_error = _error_text(error)
            finally:
                if not host_task.done():
                    host_task.cancel()
                forced_result = await asyncio.gather(host_task, return_exceptions=True)
                if forced_result and isinstance(forced_result[0], HostResult):
                    late_result = forced_result[0]
            details = [f"initial timeout: {_error_text(first_timeout)}"]
            if cancel_error:
                details.append(f"cooperative cancellation failed: {cancel_error}")
            if force_error:
                details.append(f"force termination failed: {force_error}")
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="force_terminated" if force_error is None else "interrupted",
                result=late_result,
                failure_reason="timeout",
                error="; ".join(details),
                retry_eligible=retry_is_eligible(
                    "timeout",
                    attempt_number=spec.attempt_number,
                    policy=spec.policy_snapshot,
                ),
                cancellation_requested=True,
                force_termination_requested=force_error is None,
                classification="rejected_stale",
                late_result=late_result is not None,
            )
        except Exception as error:
            return AttemptOutcome(
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                status="cancelled",
                result=None,
                failure_reason="timeout",
                error=_error_text(error),
                retry_eligible=retry_is_eligible(
                    "timeout",
                    attempt_number=spec.attempt_number,
                    policy=spec.policy_snapshot,
                ),
                cancellation_requested=True,
                classification="rejected_stale",
            )

        return AttemptOutcome(
            assignment_id=spec.assignment_id,
            attempt_id=spec.attempt_id,
            attempt_number=spec.attempt_number,
            status="cancelled",
            result=late_result,
            failure_reason="timeout",
            error=cancel_error,
            retry_eligible=retry_is_eligible(
                "timeout",
                attempt_number=spec.attempt_number,
                policy=spec.policy_snapshot,
            ),
            cancellation_requested=True,
            classification="rejected_stale",
            late_result=True,
        )


BoundedScheduler = DeterministicScheduler
