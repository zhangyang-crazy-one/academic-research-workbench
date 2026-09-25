"""Bounded input framing for the Python line-delimited MCP adapters."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator, Mapping
from typing import Any, BinaryIO

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads

MAX_FRAME_BYTES = 64 * 1024
MAX_JSON_DEPTH = 64
_DRAIN_BYTES = 8192
MAX_RESPONSE_BYTES = 256 * 1024
LEGACY_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")
MODERN_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = (MODERN_VERSION, *reversed(LEGACY_VERSIONS))
_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
_INFO_KEY = "io.modelcontextprotocol/clientInfo"
_SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"


class ProtocolError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def rpc_error(code: int, message: str, identifier: object = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {"code": code, "message": message},
    }


class StdioProtocol:
    """One dual-era JSON-RPC dispatcher for the four Python tool adapters."""

    def __init__(
        self,
        *,
        name: str,
        version: str,
        tools: Callable[[], list[dict[str, Any]]],
        call_tool: Callable[[Mapping[str, Any]], dict[str, Any]],
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self.server_info = {"name": name, "version": version}
        self.tools = tools
        self.call_tool = call_tool
        self.capabilities = capabilities or {"tools": {}}

    def handle(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        identifier = request.get("id")
        if identifier is None:
            return None
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(params, Mapping):
            return rpc_error(-32602, "Invalid params", identifier)
        meta = params.get("_meta")
        modern = method == "server/discover" or "_meta" in params
        if modern:
            if not isinstance(meta, Mapping):
                return rpc_error(-32602, "Invalid params", identifier)
            requested = meta.get(_VERSION_KEY)
            if not isinstance(requested, str):
                return rpc_error(-32602, "Invalid params", identifier)
            if requested != MODERN_VERSION:
                return {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {
                        "code": -32022,
                        "message": "Unsupported protocol version",
                        "data": {
                            "supported": list(SUPPORTED_VERSIONS),
                            "requested": requested,
                        },
                    },
                }
            if not isinstance(meta.get(_CAPABILITIES_KEY), Mapping):
                return rpc_error(-32602, "Invalid params", identifier)
            client_info = meta.get(_INFO_KEY)
            if client_info is not None and (
                not isinstance(client_info, Mapping)
                or not isinstance(client_info.get("name"), str)
                or not isinstance(client_info.get("version"), str)
            ):
                return rpc_error(-32602, "Invalid params", identifier)

        try:
            if method == "initialize" and not modern:
                requested = params.get("protocolVersion")
                version = (
                    requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[-1]
                )
                result: dict[str, Any] = {
                    "protocolVersion": version,
                    "capabilities": self.capabilities,
                    "serverInfo": self.server_info,
                }
            elif method == "server/discover" and modern:
                result = {
                    "supportedVersions": list(SUPPORTED_VERSIONS),
                    "capabilities": self.capabilities,
                }
            elif method == "ping" and not modern:
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                if not isinstance(params.get("name"), str) or not isinstance(
                    params.get("arguments", {}), Mapping
                ):
                    raise ProtocolError(-32602, "Invalid params")
                result = self.call_tool(params)
            else:
                raise ProtocolError(-32601, "Method not found")
        except ProtocolError as error:
            return rpc_error(error.code, str(error), identifier)

        if modern:
            result = {
                **result,
                "resultType": "complete",
                "_meta": {
                    **result.get("_meta", {}),
                    _SERVER_INFO_KEY: self.server_info,
                },
            }
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def run_stdio(handle: Callable[[dict[str, Any]], dict[str, Any] | None]) -> int:
    """Serve every frame through the #26 reader and one bounded output path."""
    for request, error in iter_requests(sys.stdin.buffer):
        response = error
        if request is not None:
            try:
                response = handle(request)
            except Exception:  # noqa: BLE001 - isolated per-request protocol boundary
                response = rpc_error(-32603, "Internal error", request.get("id"))
        if response is not None:
            try:
                encoded = canonical_json_bytes(response)
            except Exception:  # noqa: BLE001 - serialize failures stay per-request
                encoded = canonical_json_bytes(
                    rpc_error(
                        -32603, "Internal error", request.get("id") if request else None
                    )
                )
            if len(encoded) > MAX_RESPONSE_BYTES:
                encoded = canonical_json_bytes(
                    rpc_error(
                        -32603,
                        "OutputBudgetExceeded",
                        request.get("id") if request else None,
                    )
                )
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()
    return 0


def _check_depth(raw: bytes) -> None:
    depth = 0
    quoted = False
    escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:  # backslash
                escaped = True
            elif byte == 34:  # quote
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):  # [ {
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting limit exceeded")
        elif byte in (93, 125):  # ] }
            depth -= 1


def parse_request(raw: bytes) -> tuple[dict[str, Any] | None, dict[str, object] | None]:
    """Parse one bounded payload and classify JSON-RPC framing errors."""
    try:
        _check_depth(raw)
        request = strict_json_loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        return None, rpc_error(-32700, "Parse error")
    if not isinstance(request, dict):
        return None, rpc_error(-32600, "Invalid Request")
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return None, rpc_error(-32600, "Invalid Request")
    return request, None


def iter_requests(
    stream: BinaryIO,
) -> Iterator[tuple[dict[str, Any] | None, dict[str, object] | None]]:
    """Read frames with bounded memory, draining oversized lines before resuming."""
    while True:
        raw = stream.readline(MAX_FRAME_BYTES + 2)
        if not raw:
            return
        complete = raw.endswith(b"\n")
        payload = raw[:-1] if complete else raw
        if len(payload) > MAX_FRAME_BYTES:
            while not complete:
                chunk = stream.readline(_DRAIN_BYTES)
                if not chunk:
                    break
                complete = chunk.endswith(b"\n")
            yield None, rpc_error(-32700, "Parse error")
        else:
            yield parse_request(payload)
