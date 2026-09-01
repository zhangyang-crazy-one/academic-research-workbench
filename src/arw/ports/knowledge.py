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
    """L0 no-op provider: typed empty/unavailable results, never raises.

    ARW remains fully functional at L0 with no knowledge backend installed;
    kernel code may call the port unconditionally.
    """

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return GraphProjectionReceipt(
            schema_version="1.0.0",
            root_id="null",
            candidate_generation_id="null-unavailable",
            previous_generation_id=None,
            selected_generation_id=None,
            projection_manifest_sha256=None,
            input_sha256=projection.input_sha256,
            ledger_watermark=projection.ledger_watermark,
            status="BLOCKED",
            reason_codes=["knowledge_not_enabled"],
        )

    def build_incremental(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self.build_full(projection)

    def delete_and_rebuild(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self.build_full(projection)

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        return GraphQueryResult(
            schema_version="1.0.0",
            operation=request.operation,
            status="projection_unavailable",
            projection_generation_id=None,
            projection_manifest_sha256=None,
            ledger_watermark=None,
            rows=[],
            next_cursor=None,
            reason_code="knowledge_not_enabled",
        )
