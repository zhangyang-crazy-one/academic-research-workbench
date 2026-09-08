"""Replaceable advisory learning adapters; canonical writes remain parent-owned."""

from typing import Protocol

from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_learning import HeuristicInput


class ObservationProvider(Protocol):
    def observe(self, event_id: str, *, request: RuntimeCommandRequest) -> dict: ...


class HeuristicExtractor(Protocol):
    def extract(
        self, value: HeuristicInput, *, request: RuntimeCommandRequest
    ) -> dict: ...


class HeuristicStore(Protocol):
    def inspect(self, heuristic_id: str) -> dict: ...
    def list(self, *, max_items: int = 20) -> dict: ...
    def rebuild(self) -> dict: ...


class HeuristicEvaluator(Protocol):
    def evaluate(
        self,
        heuristic_id: str,
        sample_artifact_ids: list[str],
        *,
        request: RuntimeCommandRequest,
    ) -> dict: ...
    def qualify(self, heuristic_id: str, *, request: RuntimeCommandRequest) -> dict: ...


class HeuristicPromoter(Protocol):
    def promote(
        self,
        heuristic_id: str,
        *,
        to_scope: str,
        consent: bool,
        approval_artifact_id: str,
        request: RuntimeCommandRequest,
    ) -> dict: ...
