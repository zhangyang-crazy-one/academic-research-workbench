"""Host-neutral execution observations for Phase 4.

The execution adapter is deliberately smaller than the canonical runtime.  It
can start, cooperatively stop, and force-terminate a host attempt, but it has
no method for accepting proposals, appending events, resolving gates, or
mutating manifests.  Everything returned by an adapter is an observation that
the parent may validate later.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Self


def _is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


@dataclass(frozen=True, slots=True)
class ExecutionPolicySnapshot:
    """The bounded discretionary values frozen into an assignment policy."""

    max_concurrency: int = 4
    attempt_timeout_s: float = 300.0
    cancel_grace_s: float = 15.0
    max_attempts_per_assignment: int = 2
    proposal_max_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.max_concurrency > 64:
            raise ValueError("max_concurrency exceeds the scheduler safety bound")
        if self.attempt_timeout_s <= 0 or not _is_finite(self.attempt_timeout_s):
            raise ValueError("attempt_timeout_s must be a finite positive value")
        if self.cancel_grace_s < 0 or not _is_finite(self.cancel_grace_s):
            raise ValueError("cancel_grace_s must be a finite non-negative value")
        if self.max_attempts_per_assignment not in {1, 2}:
            raise ValueError("max_attempts_per_assignment must be one or two")
        if not 1 <= self.proposal_max_bytes <= 1_048_576:
            raise ValueError("proposal_max_bytes must be between one byte and 1048576")

    @property
    def attempt_timeout_seconds(self) -> float:
        return self.attempt_timeout_s

    @property
    def cancellation_grace_seconds(self) -> float:
        return self.cancel_grace_s

    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(
                {
                    "attempt_timeout_s": self.attempt_timeout_s,
                    "cancel_grace_s": self.cancel_grace_s,
                    "max_attempts_per_assignment": self.max_attempts_per_assignment,
                    "max_concurrency": self.max_concurrency,
                    "proposal_max_bytes": self.proposal_max_bytes,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    @property
    def policy_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


DEFAULT_EXECUTION_POLICY = ExecutionPolicySnapshot()


@dataclass(frozen=True, slots=True)
class DispatchSpec:
    """Immutable input to one host dispatch.

    ``acceptance_key`` accepts the two-integer form used by early Phase 4
    callers and the fully explicit three-part form.  The scheduler always
    expands it to ``(layer, task_ordinal, assignment_id)`` before ordering.
    """

    assignment_id: str
    attempt_id: str
    acceptance_key: tuple[int, int] | tuple[int, int, str]
    assignment_path: Path
    attempt_root: Path
    policy_snapshot: ExecutionPolicySnapshot = DEFAULT_EXECUTION_POLICY
    timeout_seconds: float | None = None
    cancellation_grace_seconds: float | None = None
    proposal_max_bytes: int | None = None
    attempt_number: int = 1
    proposal_nonce: str | None = None

    def __post_init__(self) -> None:
        if not self.assignment_id or not self.attempt_id:
            raise ValueError("assignment_id and attempt_id are required")
        if len(self.acceptance_key) not in {2, 3}:
            raise ValueError("acceptance_key must contain layer and task ordinal")
        if any(not isinstance(value, int) or value < 0 for value in self.acceptance_key[:2]):
            raise ValueError("acceptance_key values must be non-negative integers")
        if len(self.acceptance_key) == 3 and self.acceptance_key[2] != self.assignment_id:
            raise ValueError("acceptance_key assignment ID must echo assignment_id")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        if self.timeout_seconds is not None and (
            self.timeout_seconds <= 0 or not _is_finite(self.timeout_seconds)
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if self.cancellation_grace_seconds is not None and (
            self.cancellation_grace_seconds < 0
            or not _is_finite(self.cancellation_grace_seconds)
        ):
            raise ValueError("cancellation_grace_seconds must be finite and non-negative")
        if self.proposal_max_bytes is not None and not (
            1 <= self.proposal_max_bytes <= self.policy_snapshot.proposal_max_bytes
        ):
            raise ValueError("proposal_max_bytes exceeds the frozen policy snapshot")

    @property
    def frozen_order_key(self) -> tuple[int, int, str]:
        return (self.acceptance_key[0], self.acceptance_key[1], self.assignment_id)

    @property
    def effective_timeout_seconds(self) -> float:
        return (
            self.timeout_seconds
            if self.timeout_seconds is not None
            else self.policy_snapshot.attempt_timeout_s
        )

    @property
    def effective_cancellation_grace_seconds(self) -> float:
        return (
            self.cancellation_grace_seconds
            if self.cancellation_grace_seconds is not None
            else self.policy_snapshot.cancel_grace_s
        )

    @property
    def effective_proposal_max_bytes(self) -> int:
        return (
            self.proposal_max_bytes
            if self.proposal_max_bytes is not None
            else self.policy_snapshot.proposal_max_bytes
        )

    def for_retry(self, attempt_number: int) -> Self:
        """Return a fresh attempt without changing assignment-bound inputs."""

        if attempt_number <= self.attempt_number:
            raise ValueError("retry attempt number must increase")
        retry_attempt_id = f"{self.attempt_id}.retry-{attempt_number}"
        retry_root = self.attempt_root.parent / retry_attempt_id
        nonce_base = self.proposal_nonce or self.attempt_id
        return type(self)(
            assignment_id=self.assignment_id,
            attempt_id=retry_attempt_id,
            acceptance_key=self.acceptance_key,
            assignment_path=self.assignment_path,
            attempt_root=retry_root,
            policy_snapshot=self.policy_snapshot,
            timeout_seconds=self.timeout_seconds,
            cancellation_grace_seconds=self.cancellation_grace_seconds,
            proposal_max_bytes=self.proposal_max_bytes,
            attempt_number=attempt_number,
            proposal_nonce=f"{nonce_base}.retry-{attempt_number}",
        )


@dataclass(frozen=True, slots=True)
class HostResult:
    """Bounded host metadata; transcript text is never parsed here."""

    attempt_id: str
    host_agent_id: str
    proposal_path: Path
    transcript_reference: str | None = None
    observation_sha256: str | None = None
    output_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.host_agent_id:
            raise ValueError("host results require attempt and host identities")
        if self.output_bytes is not None and self.output_bytes < 0:
            raise ValueError("output_bytes cannot be negative")


class ExecutionAdapter(Protocol):
    """The only host operations a parent scheduler may request."""

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        """Dispatch one fresh attempt and return observational metadata."""

    async def request_cancel(self, spec: DispatchSpec) -> None:
        """Request cooperative cancellation of one active attempt."""

    async def force_terminate(self, spec: DispatchSpec) -> None:
        """Request qualified force termination after the grace period."""


class AdapterFailure(RuntimeError):
    """An adapter failure with a scheduler retry taxonomy."""

    reason: str

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.reason)


class ProcessFailure(AdapterFailure):
    reason = "process_failure"


class PermissionDenied(AdapterFailure):
    reason = "permission_denied"


class RepairableEnvelopeFailure(AdapterFailure):
    reason = "repairable_envelope"


class ScientificDisagreement(AdapterFailure):
    reason = "scientific_disagreement"


class StaleAttempt(AdapterFailure):
    reason = "stale_inputs"


@dataclass(frozen=True, slots=True)
class FakeDispatchPlan:
    """A deterministic fake behavior used by unit tests only."""

    delay_seconds: float = 0.0
    result: HostResult | None = None
    error: BaseException | None = None
    wait_for_cancel: bool = False
    cooperative_cancel: bool = True

    def __post_init__(self) -> None:
        if self.delay_seconds < 0 or not _is_finite(self.delay_seconds):
            raise ValueError("fake delay must be finite and non-negative")


class DeterministicFakeAdapter:
    """In-memory adapter with explicit, inspectable lifecycle observations.

    This fake intentionally has no canonical writer surface.  It records
    dispatch/cancel/force calls solely so tests can verify bounded behavior.
    """

    def __init__(
        self,
        plans: Mapping[str, FakeDispatchPlan | Sequence[FakeDispatchPlan]],
    ) -> None:
        self._plans = {
            assignment_id: (
                tuple(plan) if not isinstance(plan, FakeDispatchPlan) else (plan,)
            )
            for assignment_id, plan in plans.items()
        }
        self._calls: dict[str, int] = {}
        self._dispatch_specs: dict[str, list[DispatchSpec]] = {}
        self._lifecycle: dict[str, list[str]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._active = 0
        self._max_active = 0
        self._completion_order: list[str] = []

    @property
    def max_active(self) -> int:
        return self._max_active

    @property
    def completion_order(self) -> tuple[str, ...]:
        return tuple(self._completion_order)

    def dispatches_for(self, assignment_id: str) -> tuple[DispatchSpec, ...]:
        return tuple(self._dispatch_specs.get(assignment_id, ()))

    def lifecycle_for(self, assignment_id: str) -> tuple[str, ...]:
        return tuple(self._lifecycle.get(assignment_id, ()))

    def _plan_for(self, spec: DispatchSpec) -> FakeDispatchPlan:
        plans = self._plans.get(spec.assignment_id)
        if not plans:
            return FakeDispatchPlan()
        index = self._calls.get(spec.assignment_id, 0)
        self._calls[spec.assignment_id] = index + 1
        return plans[min(index, len(plans) - 1)]

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        self._lifecycle.setdefault(spec.assignment_id, []).append("dispatch")
        self._dispatch_specs.setdefault(spec.assignment_id, []).append(spec)
        plan = self._plan_for(spec)
        self._active += 1
        self._max_active = max(self._max_active, self._active)
        try:
            if plan.delay_seconds:
                await asyncio.sleep(plan.delay_seconds)
            if plan.wait_for_cancel:
                event = self._cancel_events.setdefault(spec.assignment_id, asyncio.Event())
                await event.wait()
            if plan.error is not None:
                raise plan.error
            result = plan.result or HostResult(
                attempt_id=spec.attempt_id,
                host_agent_id=f"fake-host-{spec.assignment_id}",
                proposal_path=spec.attempt_root / "result" / "proposal.json",
            )
            self._completion_order.append(spec.assignment_id)
            return result
        finally:
            self._active -= 1

    async def request_cancel(self, spec: DispatchSpec) -> None:
        self._lifecycle.setdefault(spec.assignment_id, []).append("request_cancel")
        plan = self._plans.get(spec.assignment_id, (FakeDispatchPlan(),))[min(
            self._calls.get(spec.assignment_id, 1) - 1,
            len(self._plans.get(spec.assignment_id, (FakeDispatchPlan(),))) - 1,
        )]
        if plan.cooperative_cancel:
            self._cancel_events.setdefault(spec.assignment_id, asyncio.Event()).set()

    async def force_terminate(self, spec: DispatchSpec) -> None:
        self._lifecycle.setdefault(spec.assignment_id, []).append("force_terminate")


FakeExecutionAdapter = DeterministicFakeAdapter
