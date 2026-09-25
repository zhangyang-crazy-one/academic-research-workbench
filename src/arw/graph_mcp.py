"""Dual-era stdio adapter for bounded research graph traces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from arw.graph_models import GraphQueryRequest, GraphQueryResult
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_json_bytes
from arw.mcp_stdio import ProtocolError, StdioProtocol
from arw.mcp_stdio import run_stdio as serve_stdio

TOOL_NAMES = (
    "trace_claim",
    "trace_source",
    "trace_experiment",
    "trace_review",
    "trace_gate_evidence",
    "graph_health",
)


def _text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8").rstrip("\n")


class GraphMcpServer:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.protocol = StdioProtocol(
            name="academic-research-workbench-graph",
            version="0.1.0",
            tools=self._tools,
            call_tool=self._call_tool,
            capabilities={"tools": {"listChanged": False}},
        )

    @staticmethod
    def _tools() -> list[dict[str, Any]]:
        properties = {
            "entity_id": {"type": "string", "maxLength": 192},
            "max_depth": {"type": "integer", "minimum": 0, "maximum": 8},
            "max_fanout": {"type": "integer", "minimum": 1, "maximum": 200},
            "max_rows": {"type": "integer", "minimum": 1, "maximum": 500},
            "max_bytes": {"type": "integer", "minimum": 256, "maximum": 262144},
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 5000},
            "expected_ledger_watermark": {"type": ["integer", "null"], "minimum": 0},
            "cursor": {"type": ["string", "null"], "maxLength": 4096},
        }
        tools = []
        for name in TOOL_NAMES:
            required = [] if name == "graph_health" else ["entity_id"]
            tools.append(
                {
                    "name": name,
                    "description": f"Bounded read-only {name.replace('_', ' ')} over a verified disposable research graph.",
                    "inputSchema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                    "outputSchema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "required": ["schema_version", "operation", "status", "rows"],
                        "additionalProperties": True,
                    },
                }
            )
        return tools

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        return self.protocol.handle(message)

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if set(params) - {"name", "arguments", "_meta"}:
            raise ProtocolError(-32602, "tools/call parameters are invalid")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in TOOL_NAMES or not isinstance(arguments, Mapping):
            raise ProtocolError(-32602, "unknown graph tool or arguments")
        payload = dict(arguments)
        payload["schema_version"] = "1.0.0"
        payload["operation"] = name
        try:
            request = GraphQueryRequest.model_validate(payload, strict=True)
            result = self.store.query(request)
        except (ValidationError, ValueError) as error:
            result = GraphQueryResult(
                schema_version="1.0.0",
                operation=name,
                status="projection_unavailable",
                projection_generation_id=None,
                projection_manifest_sha256=None,
                ledger_watermark=None,
                rows=[],
                reason_code="invalid_query",
            )
            result_message = str(error)
        else:
            result_message = None
        payload_result = result.model_dump(mode="json")
        if result_message:
            payload_result["message"] = result_message
        return {
            "content": [{"type": "text", "text": _text(payload_result)}],
            "structuredContent": payload_result,
            "isError": result.status != "ok",
        }


def run_stdio(server: GraphMcpServer) -> int:
    return serve_stdio(server.handle)
