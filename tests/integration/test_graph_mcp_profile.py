from __future__ import annotations

import json

from arw.graph_mcp import GraphMcpServer
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from tests.integration.test_graph_projection import _fixture_records


def test_mcp_lifecycle_lists_only_allowlisted_graph_tools(tmp_path) -> None:
    store = GraphStore(tmp_path / "control", "research-root")
    store.build(project_canonical_records(_fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64))
    server = GraphMcpServer(store)
    initialize = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialize["result"]["protocolVersion"] == "2025-11-25"
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = [tool["name"] for tool in tools["result"]["tools"]]
    assert names == ["trace_claim", "trace_source", "trace_experiment", "trace_review", "trace_gate_evidence", "graph_health"]
    assert "query_graph" not in names
    assert "index_repository" not in names


def test_mcp_call_rejects_raw_query_and_returns_structured_result(tmp_path) -> None:
    store = GraphStore(tmp_path / "control", "research-root")
    store.build(project_canonical_records(_fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64))
    server = GraphMcpServer(store)
    rejected = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "trace_claim", "arguments": {"entity_id": "claim-004", "cypher": "MATCH (n) RETURN n"}},
        }
    )
    assert rejected["result"]["isError"] is True
    accepted = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "trace_claim", "arguments": {"entity_id": "claim-004", "max_rows": 5}},
        }
    )
    assert accepted["result"]["isError"] is False
    payload = json.loads(accepted["result"]["content"][0]["text"])
    assert payload["operation"] == "trace_claim"
    assert payload["status"] == "ok"

