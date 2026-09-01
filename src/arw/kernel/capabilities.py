"""Capability vocabulary and routing table.

Extensions register capability names; the composition root resolves them to
provider instances. The kernel references capabilities by name only and
never imports concrete adapters.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class CapabilityUnavailable(RuntimeError):
    """Raised when a capability has no registered provider."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"capability has no provider: {capability}")
        self.capability = capability


class CapabilityRouter:
    """Static capability -> provider factory routing table.

    Factories are lazy: registering a capability does not import or start
    its provider. Only the composition root may populate the table.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Callable[[], Any]] = {}

    def register(self, capability: str, factory: Callable[[], Any]) -> None:
        self._providers[capability] = factory

    def resolve(self, capability: str) -> Any:
        try:
            factory = self._providers[capability]
        except KeyError:
            raise CapabilityUnavailable(capability) from None
        return factory()

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


# v2 capability vocabulary (stable identifiers for extension registration).
CAPABILITIES: tuple[str, ...] = (
    "files.local",
    "files.search",
    "knowledge.graph",
    "knowledge.provenance",
    "knowledge.semantic_search",
    "research.literature",
    "research.deep_survey",
    "research.experiment",
    "artifact.inspect",
    "artifact.sanitize",
    "audit.replay",
)
