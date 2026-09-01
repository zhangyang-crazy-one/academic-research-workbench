"""KnowledgeProvider port: rebuildable research-graph projections.

Derived from the v1 graph contracts (`arw.graph_models`,
`arw.graph_store.GraphStore`, `arw.graph_projection`). The provider is always
a disposable projection over the canonical ledger — never canonical truth.
"""

from __future__ import annotations

from typing import Protocol

from arw.graph_models import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
)


class KnowledgeProvider(Protocol):
    """Rebuildable graph projection plus bounded evidence queries."""

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt: ...

    def build_incremental(self, projection: GraphProjectionInput) -> GraphProjectionReceipt: ...

    def delete_and_rebuild(self, projection: GraphProjectionInput) -> GraphProjectionReceipt: ...

    def query(self, request: GraphQueryRequest) -> GraphQueryResult: ...


class NullKnowledgeProvider:
    """L0 no-op provider: ARW remains fully functional with no graph backend."""

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        raise KnowledgeUnavailable("knowledge graph is not enabled")

    def build_incremental(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        raise KnowledgeUnavailable("knowledge graph is not enabled")

    def delete_and_rebuild(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        raise KnowledgeUnavailable("knowledge graph is not enabled")

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        raise KnowledgeUnavailable("knowledge graph is not enabled")


class KnowledgeUnavailable(RuntimeError):
    """Raised when a knowledge capability is requested but not enabled."""
