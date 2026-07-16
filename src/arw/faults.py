"""Guarded deterministic fault controls used by the Phase 7 qualification matrix.

Fault injection is deliberately separate from canonical state.  The control is
only accepted when ``ARW_TEST_MODE=1`` and the stable fault id is known.  A
normal process has no configured plan, and production callers cannot activate a
fault by passing a request field or a scheduler option.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from typing import Final, Literal


FAULT_PLAN_ENV: Final[str] = "ARW_TEST_FAULT_ID"
FAULT_MODE_ENV: Final[str] = "ARW_TEST_MODE"

FaultBoundary = Literal[
    "canonical-write",
    "journal-fsync",
    "lock-acquire",
    "lock-owner",
    "host-dispatch",
    "result-acceptance",
]


class FaultConfigurationError(RuntimeError):
    """A caller attempted to configure an unknown or unguarded fault."""


class InjectedFault(RuntimeError):
    """A deterministic test fault reached its configured boundary."""

    def __init__(self, fault_id: str, boundary: FaultBoundary) -> None:
        self.fault_id = fault_id
        self.boundary = boundary
        super().__init__(f"injected fault {fault_id} at {boundary}")


@dataclass(frozen=True, slots=True)
class FaultSpec:
    fault_id: str
    boundary: FaultBoundary
    action: Literal["raise", "sigkill", "torn-write"] = "raise"


# IDs are intentionally stable and are also checked into the Phase 7 fixture.
# Keep additions backwards compatible; changing an id invalidates retained
# fault-matrix evidence.
FAULT_SPECS: Final[dict[str, FaultSpec]] = {
    "phase7.canonical-write-before-commit": FaultSpec(
        "phase7.canonical-write-before-commit", "canonical-write"
    ),
    "phase7.hard-termination": FaultSpec(
        "phase7.hard-termination", "canonical-write", "sigkill"
    ),
    "phase7.torn-final-write": FaultSpec(
        "phase7.torn-final-write", "canonical-write", "torn-write"
    ),
    "phase7.journal-fsync": FaultSpec("phase7.journal-fsync", "journal-fsync"),
    "phase7.io-failure": FaultSpec("phase7.io-failure", "journal-fsync"),
    "phase7.disk-exhaustion": FaultSpec("phase7.disk-exhaustion", "journal-fsync"),
    "phase7.lock-acquire": FaultSpec("phase7.lock-acquire", "lock-acquire"),
    "phase7.lock-owner-death": FaultSpec(
        "phase7.lock-owner-death", "lock-owner", "sigkill"
    ),
    "phase7.host-dispatch": FaultSpec("phase7.host-dispatch", "host-dispatch"),
    "phase7.result-acceptance": FaultSpec(
        "phase7.result-acceptance", "result-acceptance"
    ),
    # These IDs identify scheduler/admission observations in the retained
    # matrix.  Their concrete trigger is supplied by the deterministic fake
    # adapter, not by an untrusted runtime request.
    "phase7.duplicate-delivery": FaultSpec(
        "phase7.duplicate-delivery", "result-acceptance"
    ),
    "phase7.stale-worker-completion": FaultSpec(
        "phase7.stale-worker-completion", "result-acceptance"
    ),
    "phase7.timeout": FaultSpec("phase7.timeout", "host-dispatch"),
    "phase7.repairable-proposal": FaultSpec(
        "phase7.repairable-proposal", "result-acceptance"
    ),
    "phase7.malformed-proposal": FaultSpec(
        "phase7.malformed-proposal", "result-acceptance"
    ),
}


def configured_fault() -> FaultSpec | None:
    """Return the opt-in plan, rejecting unsafe configuration eagerly.

    ``ARW_TEST_FAULT_ID`` without the explicit test-mode marker is treated as
    a configuration error rather than silently ignored.  This prevents a
    production launch wrapper from accidentally believing a fault was active.
    """

    value = os.environ.get(FAULT_PLAN_ENV)
    if value in (None, ""):
        return None
    if os.environ.get(FAULT_MODE_ENV) != "1":
        raise FaultConfigurationError(
            f"{FAULT_PLAN_ENV} requires {FAULT_MODE_ENV}=1"
        )
    try:
        return FAULT_SPECS[value]
    except KeyError as error:
        raise FaultConfigurationError(f"unknown deterministic fault id: {value}") from error


def active_fault(fault_id: str) -> FaultSpec | None:
    """Return the active spec for specialized boundaries such as torn writes."""

    spec = configured_fault()
    if spec is None or spec.fault_id != fault_id:
        return None
    return spec


def inject(fault_id: str, *, kill: bool = False) -> None:
    """Inject ``fault_id`` when it is the active test plan.

    ``kill`` is reserved for the owner-death boundary and remains explicit at
    the call site.  All other faults raise an ordinary exception so the parent
    process can retain bounded stderr and classify the failure.
    """

    spec = configured_fault()
    if spec is None or spec.fault_id != fault_id:
        return
    if kill or spec.action == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    raise InjectedFault(spec.fault_id, spec.boundary)


def fault_ids() -> tuple[str, ...]:
    """Return the sorted, evidence-facing registry of stable IDs."""

    return tuple(sorted(FAULT_SPECS))
