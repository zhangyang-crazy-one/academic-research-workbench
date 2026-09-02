"""Store-backed files MCP server (PR5 task 4.1 — MCP as transport adapter).

Serves the same five read tools as ``arw.files_mcp`` but resolves them
through the native :class:`arw_ext.local_store.files.LocalStoreFilesAdapter`
over the local projection store instead of re-loading a v1 files generation.
This is the production read path that consumes the store populated by
``arw files sync`` (review: previously the sync populated the store but no
installed read path consumed it).

The MCP layer is a thin transport adapter: it parses JSON-RPC, dispatches to
the provider, and serializes the result.  No business logic lives here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from arw.file_contracts import CursorError
from arw.file_models import (
    FilesContextRequest,
    FilesListRequest,
    FilesOutlineRequest,
    FilesReadRequest,
    FilesSearchRequest,
)
from arw.files_mcp import TOOL_MODELS, _tool_envelope
from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads

# Reuse the v1 MCP request/response contract; the provider is the only
# difference.  TOOL_MODELS maps tool names to their request models.
_DISPATCH = {
    "list_files": ("list_files", FilesListRequest),
    "read_file": ("read_file", FilesReadRequest),
    "search_files": ("search_files", FilesSearchRequest),
    "get_outline": ("get_outline", FilesOutlineRequest),
    "get_context": ("get_context", FilesContextRequest),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academic-research-files-store")
    parser.add_argument("--store", required=True, type=Path)
    return parser


def _handle(adapter, request: object) -> dict[str, object] | None:
    if not isinstance(request, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    identifier = request.get("id")
    if identifier is None:
        return None
    method = request.get("method")
    params = request.get("params", {})
    try:
        if method == "initialize":
            result: object = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "academic-research-files-store", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": f"Local-store {name}.",
                        "inputSchema": model.model_json_schema(mode="validation"),
                    }
                    for name, model in TOOL_MODELS.items()
                ]
            }
        elif method == "tools/call" and isinstance(params, dict):
            name = params.get("name")
            arguments = params.get("arguments", {})
            entry = _DISPATCH.get(name if isinstance(name, str) else "")
            if entry is None:
                payload, is_error = (
                    {"error_code": "unknown_tool", "message": "tool is not registered"},
                    True,
                )
                result = _tool_envelope(payload, error=is_error)
            else:
                method_name, model = entry
                try:
                    parsed = model.model_validate(arguments)
                    result_model = getattr(adapter, method_name)(parsed)
                    payload = result_model.model_dump(mode="json")
                    is_error = getattr(result_model, "status", "ok") not in {
                        "ok",
                        "stale_conflict",
                        "encoding_error",
                    }
                    result = _tool_envelope(payload, error=is_error)
                except Exception as error:  # noqa: BLE001 - envelope boundary
                    code = getattr(error, "code", "tool_error")
                    result = _tool_envelope(
                        {"error_code": code, "message": str(error)}, error=True
                    )
        else:
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32601, "message": "Method not found"},
            }
    except CursorError as error:
        result = _tool_envelope(
            {"error_code": error.code, "message": str(error)}, error=True
        )
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments.count("--store") != 1:
        print(
            "files-store-mcp: startup-error: exactly one --store is required",
            file=sys.stderr,
        )
        return 64
    args = build_parser().parse_args(arguments)
    # Composition-root seam: construct the native provider over the store.
    from arw.composition import local_store_files_provider

    try:
        adapter = local_store_files_provider(args.store)
    except Exception as error:  # noqa: BLE001 - startup boundary
        code = getattr(error, "code", "store_unavailable")
        print(f"files-store-mcp: startup-error: {code}: {error}", file=sys.stderr)
        return 78
    for raw_line in sys.stdin.buffer:
        try:
            request = strict_json_loads(raw_line)
        except (UnicodeError, ValueError) as error:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {error}"},
            }
        else:
            response = _handle(adapter, request)
        if response is not None:
            sys.stdout.buffer.write(canonical_json_bytes(response))
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
