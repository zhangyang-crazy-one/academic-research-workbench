"""KnowledgeProvider adapter for the v1 graph projection store."""

from __future__ import annotations

from arw.graph_models import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
)
from arw.graph_store import GraphStore


class GraphProjectionAdapter:
    """KnowledgeProvider over the v1 GraphStore generation engine."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self._store.build_full(projection)

    def build_incremental(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self._store.build_incremental(projection)

    def delete_and_rebuild(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self._store.delete_and_rebuild(projection)

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        return self._store.query(request)
