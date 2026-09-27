"""Issue #26: every Python MCP loop recovers at the next request frame."""

from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace

import pytest

from arw import files_mcp, files_store_mcp, graph_mcp, memory_mcp
from arw.mcp_stdio import (
    MAX_FRAME_BYTES,
    MODERN_VERSION,
    SUPPORTED_VERSIONS,
    StdioProtocol,
    iter_requests,
    parse_request,
    run_stdio,
)

LIST = b'{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n'
PING = b'{"jsonrpc":"2.0","id":7,"method":"ping"}\n'


class BoundedBytesIO(io.BytesIO):
    def readline(self, size=-1):
        assert 0 < size <= MAX_FRAME_BYTES + 2
        return super().readline(size)


def _run_loop(kind: str, frames: bytes, monkeypatch, *, fault: bool = False):
    source = BoundedBytesIO(frames)
    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", SimpleNamespace(buffer=source))
        patch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        if kind == "graph":
            server = graph_mcp.GraphMcpServer(None)
            if fault:
                original = server.handle

                def handle(request):
                    if request["method"] == "ping":
                        raise RuntimeError("private handler failure")
                    return original(request)

                patch.setattr(server, "handle", handle)
            assert graph_mcp.run_stdio(server) == 0
        elif kind == "files":
            server = files_mcp.FilesMcpServer.__new__(files_mcp.FilesMcpServer)
            if fault:
                original = server.handle

                def handle(request):
                    if request["method"] == "ping":
                        raise RuntimeError("private handler failure")
                    return original(request)

                patch.setattr(server, "handle", handle)
            patch.setattr(files_mcp, "load_query_generation", lambda *_: object())
            patch.setattr(files_mcp, "FilesMcpServer", lambda _: server)
            assert (
                files_mcp.main(
                    ["--control-root", "/unused", "--root-id", "research-root"]
                )
                == 0
            )
        elif kind == "store":
            if fault:
                original = files_store_mcp._handle

                def handle(adapter, request):
                    if request["method"] == "ping":
                        raise RuntimeError("private handler failure")
                    return original(adapter, request)

                patch.setattr(files_store_mcp, "_handle", handle)
            files_store_mcp._run_loop(None)
        else:
            server = memory_mcp.MemoryMcpServer.__new__(memory_mcp.MemoryMcpServer)
            if fault:
                original = server.handle

                def handle(request):
                    if request["method"] == "ping":
                        raise RuntimeError("private handler failure")
                    return original(request)

                patch.setattr(server, "handle", handle)
            patch.setattr(
                memory_mcp, "MemoryMcpServer", lambda *_args, **_kwargs: server
            )
            patch.setattr(
                sys,
                "argv",
                ["memory_mcp", "--project-root", "/unused", "--harness", "codex"],
            )
            assert memory_mcp.main() == 0
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.mark.parametrize("kind", ["graph", "files", "store", "memory"])
@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (b"{malformed\n", -32700),
        (b"\xff\n", -32700),
        (b"[]\n", -32600),
        (b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]\n', -32600),
        (
            b'{"jsonrpc":"2.0","method":"ping","params":'
            + b"[" * 65
            + b"0"
            + b"]" * 65
            + b"}\n",
            -32700,
        ),
        (b"x" * (MAX_FRAME_BYTES + 100_000) + b"\n", -32700),
    ],
)
def test_bad_frame_then_tools_list(kind, bad, code, monkeypatch):
    responses = _run_loop(kind, bad + LIST, monkeypatch)
    assert len(responses) == 2
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == code
    assert responses[1]["id"] == 9
    assert responses[1]["result"]["tools"]


@pytest.mark.parametrize("kind", ["graph", "files", "store", "memory"])
def test_handler_failure_then_tools_list(kind, monkeypatch):
    responses = _run_loop(kind, PING + LIST, monkeypatch, fault=True)
    assert len(responses) == 2
    assert responses[0] == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32603, "message": "Internal error"},
    }
    assert responses[1]["result"]["tools"]


def test_exact_frame_limit_and_string_escapes():
    prefix = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"text":"'
    suffix = b'"}}'
    payload = prefix + b"{" * (MAX_FRAME_BYTES - len(prefix) - len(suffix)) + suffix
    request, error = parse_request(payload)
    assert error is None
    assert request["method"] == "ping"
    assert len(payload) == MAX_FRAME_BYTES
    frames = list(iter_requests(BoundedBytesIO(payload + b"\n" + LIST)))
    assert frames[0][1] is None
    assert frames[1][0]["id"] == 9
    quoted = json.dumps(
        {"jsonrpc": "2.0", "method": "ping", "params": {"text": '\\"' + "[" * 100}}
    ).encode()
    assert parse_request(quoted)[1] is None
    assert parse_request(b"[" * 64 + b"0" + b"]" * 64)[1]["error"]["code"] == -32600
    assert parse_request(b"[" * 65 + b"0" + b"]" * 65)[1]["error"]["code"] == -32700


def test_reader_drains_to_eof_in_bounded_chunks():
    frames = list(iter_requests(BoundedBytesIO(b"x" * (MAX_FRAME_BYTES + 100_000))))
    assert len(frames) == 1
    assert frames[0][1]["error"]["code"] == -32700


def _modern(method, identifier, extra=None, *, version=MODERN_VERSION):
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": method,
        "params": {
            **(extra or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "fixture",
                    "version": "1.0",
                },
            },
        },
    }


@pytest.mark.parametrize("kind", ["graph", "files", "store", "memory"])
def test_four_servers_serve_modern_discover_list_call_and_legacy(kind, monkeypatch):
    # The request stream is one process: modern and legacy frames interleave.
    requests = [
        _modern("server/discover", 1),
        _modern("tools/list", 2),
        _modern("tools/call", 3, {"name": "not_a_tool", "arguments": {}}),
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
        {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}},
        _modern("tools/list", 6),
    ]
    frames = b"".join(json.dumps(request).encode() + b"\n" for request in requests)
    responses = _run_loop(kind, frames, monkeypatch)
    assert [response["id"] for response in responses] == list(range(1, 7))
    discover = responses[0]["result"]
    assert discover["supportedVersions"] == list(SUPPORTED_VERSIONS)
    assert discover["capabilities"]["tools"] == (
        {} if kind == "memory" else {"listChanged": False}
    )
    assert discover["resultType"] == "complete"
    assert discover["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
    assert responses[1]["result"]["tools"]
    assert responses[1]["result"]["resultType"] == "complete"
    if kind == "graph":
        assert responses[2]["error"]["code"] == -32602
    else:
        assert responses[2]["result"]["isError"] is True
        assert responses[2]["result"]["resultType"] == "complete"
    assert responses[3]["result"]["protocolVersion"] == "2025-11-25"
    assert "resultType" not in responses[3]["result"]
    assert "resultType" not in responses[4]["result"]
    assert responses[5]["result"]["resultType"] == "complete"


@pytest.mark.parametrize(
    "requested", ["2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28", "1900-01-01"]
)
def test_initialize_negotiates_only_legacy(requested):
    protocol = StdioProtocol(
        name="fixture", version="1", tools=list, call_tool=lambda _: {}
    )
    response = protocol.handle(
        {"id": 1, "method": "initialize", "params": {"protocolVersion": requested}}
    )
    expected = (
        requested
        if requested in {"2025-03-26", "2025-06-18", "2025-11-25"}
        else "2025-11-25"
    )
    assert response["result"]["protocolVersion"] == expected
    assert "resultType" not in response["result"]


def test_modern_metadata_errors_and_response_budget(monkeypatch):
    protocol = StdioProtocol(
        name="fixture", version="1", tools=list, call_tool=lambda _: {}
    )
    unsupported = protocol.handle(_modern("tools/list", 1, version="1900-01-01"))
    assert unsupported["error"] == {
        "code": -32022,
        "message": "Unsupported protocol version",
        "data": {"supported": list(SUPPORTED_VERSIONS), "requested": "1900-01-01"},
    }
    malformed = _modern("tools/list", 2)
    del malformed["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]
    assert protocol.handle(malformed)["error"]["code"] == -32602
    assert (
        protocol.handle({"id": 3, "method": "server/discover", "params": {}})["error"][
            "code"
        ]
        == -32602
    )
    assert protocol.handle(_modern("ping", 4))["error"]["code"] == -32601

    output = io.BytesIO()
    oversized = StdioProtocol(
        name="fixture",
        version="1",
        tools=lambda: [{"name": "large", "description": "x" * 300_000}],
        call_tool=lambda _: {},
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            sys,
            "stdin",
            SimpleNamespace(
                buffer=io.BytesIO(
                    json.dumps(_modern("tools/list", 5)).encode() + b"\n" + PING
                )
            ),
        )
        patch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        assert run_stdio(oversized.handle) == 0
    first, second = [json.loads(line) for line in output.getvalue().splitlines()]
    assert first["error"]["message"] == "OutputBudgetExceeded"
    assert second["result"] == {}


def test_response_serialization_failure_is_isolated(monkeypatch):
    output = io.BytesIO()

    def handle(request):
        if request["id"] == 1:
            return {"jsonrpc": "2.0", "id": 1, "result": {"bad": object()}}
        return {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}

    frames = (
        b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    )
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(frames)))
        patch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        assert run_stdio(handle) == 0
    first, second = [json.loads(line) for line in output.getvalue().splitlines()]
    assert first["error"]["code"] == -32603
    assert second["result"] == {"ok": True}


@pytest.mark.parametrize("kind", ["graph", "files", "store", "memory"])
def test_modern_known_tool_reaches_adapter(kind, monkeypatch):
    calls = []
    if kind == "graph":

        class FakeStore:
            def query(self, request):
                calls.append(request.operation)
                return SimpleNamespace(
                    status="ok",
                    model_dump=lambda **_: {
                        "operation": request.operation,
                        "status": "ok",
                    },
                )

        handler = graph_mcp.GraphMcpServer(FakeStore()).handle
        name, arguments = "graph_health", {}
    elif kind == "files":
        server = files_mcp.FilesMcpServer.__new__(files_mcp.FilesMcpServer)
        monkeypatch.setattr(
            server,
            "handle_tool",
            lambda name, args: (calls.append(name) or {"status": "ok"}, False),
        )
        handler = server.handle
        name, arguments = "list_files", {}
    elif kind == "store":
        adapter = SimpleNamespace(
            list_files=lambda request: (
                calls.append("list_files")
                or SimpleNamespace(model_dump=lambda **_: {"status": "ok"})
            )
        )
        handler = lambda request: files_store_mcp._handle(adapter, request)
        name, arguments = (
            "list_files",
            {"schema_version": "1.0.0", "root_id": "research-root"},
        )
    else:
        server = memory_mcp.MemoryMcpServer.__new__(memory_mcp.MemoryMcpServer)
        monkeypatch.setattr(
            server, "call", lambda name, args: calls.append(name) or {"status": "ok"}
        )
        handler = server.handle
        name, arguments = "memory_doctor", {}
    response = handler(_modern("tools/call", 7, {"name": name, "arguments": arguments}))
    assert calls == [name]
    assert response["result"]["isError"] is False
    assert response["result"]["resultType"] == "complete"
    assert response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
