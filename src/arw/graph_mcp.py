"""Official MCP 2025-11-25 stdio adapter for bounded research graph traces."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.graph_models import GraphQueryRequest, GraphQueryResult
from arw.graph_store import GraphStore


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
        request_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error(request_id, -32600, "invalid JSON-RPC request")
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "academic-research-workbench-graph", "version": "0.1.0"},
                },
            }
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self._tools()}}
        if method == "tools/call":
            return self._call_tool(request_id, message.get("params"))
        return self._error(request_id, -32601, "method not found")

    def _call_tool(self, request_id: Any, params: Any) -> dict[str, Any]:
        if not isinstance(params, Mapping) or set(params) - {"name", "arguments"}:
            return self._error(request_id, -32602, "tools/call parameters are invalid")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name not in TOOL_NAMES or not isinstance(arguments, Mapping):
            return self._error(request_id, -32602, "unknown graph tool or arguments")
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
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": _text(payload_result)}],
                "structuredContent": payload_result,
                "isError": result.status != "ok",
            },
        }

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def run_stdio(server: GraphMcpServer) -> int:
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            message = strict_json_loads(line)
            if not isinstance(message, Mapping):
                response = server._error(None, -32600, "request must be an object")
            else:
                response = server.handle(message)
        except (UnicodeError, ValueError, json.JSONDecodeError) as error:
            response = server._error(None, -32700, f"invalid JSON: {error}")
        if response is not None:
            sys.stdout.buffer.write(canonical_json_bytes(response))
            sys.stdout.buffer.flush()
    return 0

