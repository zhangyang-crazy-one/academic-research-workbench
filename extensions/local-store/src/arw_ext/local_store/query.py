"""Read-only query engine mirroring ``arw.graph_store.GraphStore.query``.

The local-store adapter reuses the *exact* BFS trace, allow-list per
operation, error mapping, and row shape as the v1 graph_store so the v2
oracle (``arw.graph_oracle.assert_equivalent``) can compare a query page
produced through the local store with one produced through v1.

The query engine never mutates the DB; it opens its own read-only SQLite
connection when needed (the store adapter's public ``query`` method passes
the open connection in directly).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, cast

from arw.graph_models import (
    GRAPH_SCHEMA_VERSION,
    GraphQueryOperation,
    GraphQueryRequest,
    GraphQueryResult,
    GraphResultStatus,
)

# ---------------------------------------------------------------------------
# Error mapping mirrors ``GraphStore._error_result``
# ---------------------------------------------------------------------------


def _error_result(
    request: GraphQueryRequest,
    code: str,
    message: str,
) -> GraphQueryResult:
    status = cast(
        GraphResultStatus,
        code
        if code in {"projection_stale", "projection_corrupt", "projection_unavailable"}
        else "projection_unavailable",
    )
    return GraphQueryResult(
        schema_version=GRAPH_SCHEMA_VERSION,
        operation=request.operation,
        status=status,
        projection_generation_id=None,
        projection_manifest_sha256=None,
        ledger_watermark=None,
        rows=[],
        next_cursor=None,
        reason_code=code,
    )


# ---------------------------------------------------------------------------
# Trace engine (BFS, same allow-list as ``GraphStore._trace``)
# ---------------------------------------------------------------------------


_TRACE_OPERATIONS: frozenset[GraphQueryOperation] = frozenset(
    {
        "trace_claim",
        "trace_source",
        "trace_experiment",
        "trace_review",
        "trace_gate_evidence",
        "graph_health",
    }
)

_ALLOWED_EDGE_TYPES: dict[GraphQueryOperation, frozenset[str]] = {
    "trace_claim": frozenset(
        {
            "supported_by",
            "uses_dataset",
            "uses_experiment",
            "uses_figure",
            "corrects",
            "supersedes",
            "derived_from",
        }
    ),
    "trace_source": frozenset({"supported_by", "derived_from", "supersedes"}),
    "trace_experiment": frozenset({"uses_experiment", "derived_from", "supersedes"}),
    "trace_review": frozenset(
        {"reviews", "dissent_for", "synthesizes", "evidenced_by", "supersedes"}
    ),
    "trace_gate_evidence": frozenset({"evidenced_by", "requires", "supersedes"}),
}


def trace_rows(
    connection: sqlite3.Connection,
    request: GraphQueryRequest,
    *,
    selected_ledger_watermark: int,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    """Run one BFS trace and return the row list (mirrors GraphStore._trace)."""

    if request.operation not in _TRACE_OPERATIONS:
        return []

    if request.operation == "graph_health":
        return [
            {
                "entity_type": "GraphHealth",
                "entity_id": request.entity_id or "<graph_health>",
                "source_digest": "0" * 64,
                "payload_digest": "0" * 64,
                "supersession_state": "active",
                "ledger_watermark": selected_ledger_watermark,
                "attributes": {"operation": "graph_health"},
                "relationships": [],
            }
        ]

    if request.entity_id is None:
        raise _QueryError("invalid_query", "trace operation requires entity_id")

    allowed = _ALLOWED_EDGE_TYPES[request.operation]
    pending: list[tuple[str, int]] = [(request.entity_id, 0)]
    visited: set[str] = {request.entity_id}
    rows: list[dict[str, Any]] = []

    while pending:
        if deadline is not None and time.monotonic() > deadline:
            raise _QueryError("query_timeout", "graph query exceeded its deadline")
        entity_id, depth = pending.pop(0)
        node = connection.execute(
            "SELECT entity_type, entity_id, source_digest, payload_digest, "
            "supersession_state, ledger_watermark, attributes_json FROM nodes "
            "WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if node is None:
            raise _QueryError(
                "entity_not_found", "requested graph entity is not present"
            )
        relationships: list[dict[str, Any]] = []
        outgoing = connection.execute(
            "SELECT edge_type, to_entity_id, evidence_digest, supersession_state, "
            "ledger_watermark FROM edges WHERE from_entity_id = ? "
            "ORDER BY edge_type, to_entity_id LIMIT ?",
            (entity_id, request.max_fanout + 1),
        ).fetchall()
        incoming = connection.execute(
            "SELECT edge_type, from_entity_id, evidence_digest, supersession_state, "
            "ledger_watermark FROM edges WHERE to_entity_id = ? "
            "ORDER BY edge_type, from_entity_id LIMIT ?",
            (entity_id, request.max_fanout + 1),
        ).fetchall()
        if len(outgoing) > request.max_fanout or len(incoming) > request.max_fanout:
            raise _QueryError(
                "query_budget_exceeded", "edge fanout exceeds the server ceiling"
            )
        for edge_type, target, evidence_digest, state, watermark in outgoing:
            relationships.append(
                {
                    "direction": "outgoing",
                    "edge_type": edge_type,
                    "entity_id": target,
                    "evidence_digest": evidence_digest,
                    "supersession_state": state,
                    "ledger_watermark": watermark,
                }
            )
        for edge_type, source, evidence_digest, state, watermark in incoming:
            relationships.append(
                {
                    "direction": "incoming",
                    "edge_type": edge_type,
                    "entity_id": source,
                    "evidence_digest": evidence_digest,
                    "supersession_state": state,
                    "ledger_watermark": watermark,
                }
            )
        rows.append(
            {
                "entity_type": node[0],
                "entity_id": node[1],
                "source_digest": node[2],
                "payload_digest": node[3],
                "supersession_state": node[4],
                "ledger_watermark": node[5],
                "attributes": _loads(node[6]),
                "relationships": sorted(
                    relationships,
                    key=lambda item: (
                        item["direction"],
                        item["edge_type"],
                        item["entity_id"],
                    ),
                ),
            }
        )
        if depth >= request.max_depth:
            continue
        for relationship in relationships:
            target = relationship["entity_id"]
            if relationship["edge_type"] not in allowed or target in visited:
                continue
            visited.add(target)
            pending.append((target, depth + 1))
            if len(visited) >= request.max_rows:
                return rows
    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _QueryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _loads(raw: str) -> dict[str, Any]:
    import json

    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_query(
    connection: sqlite3.Connection,
    request: GraphQueryRequest,
    *,
    selected_generation_id: str,
    selected_manifest_sha256: str | None,
    selected_ledger_watermark: int,
) -> GraphQueryResult:
    """Execute one query request and return the v2 wire result.

    Mirrors :meth:`arw.graph_store.GraphStore.query` exactly: same error
    codes (``projection_stale``, ``projection_corrupt``,
    ``projection_unavailable``, ``invalid_query``), same byte cap on the
    encoded rows, and same row shape (entity_type / entity_id /
    source_digest / payload_digest / supersession_state / ledger_watermark /
    attributes / relationships).
    """

    try:
        if (
            request.expected_ledger_watermark is not None
            and request.expected_ledger_watermark != selected_ledger_watermark
        ):
            return _error_result(
                request,
                "projection_stale",
                "selected graph watermark differs from request",
            )
        deadline = time.monotonic() + request.timeout_ms / 1000
        rows = trace_rows(
            connection,
            request,
            selected_ledger_watermark=selected_ledger_watermark,
            deadline=deadline,
        )
        from arw.kernel.core.canonical import canonical_json_bytes

        encoded = canonical_json_bytes(rows)
        if len(encoded) > request.max_bytes:
            return _error_result(
                request,
                "query_budget_exceeded",
                "query result exceeds byte ceiling",
            )
        return GraphQueryResult(
            schema_version=GRAPH_SCHEMA_VERSION,
            operation=request.operation,
            status="ok",
            projection_generation_id=selected_generation_id,
            projection_manifest_sha256=selected_manifest_sha256,
            ledger_watermark=selected_ledger_watermark,
            rows=rows[: request.max_rows],
            next_cursor=None,
            reason_code=None,
        )
    except _QueryError as error:
        return _error_result(request, error.code, error.message)
    except sqlite3.Error as error:
        return _error_result(
            request,
            "projection_corrupt",
            f"read-only graph query failed: {error}",
        )


__all__ = ["execute_query", "trace_rows"]
