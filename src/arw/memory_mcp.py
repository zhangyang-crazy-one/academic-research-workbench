"""Optional four-tool memory transport with process-bound project and harness."""

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_memory import MemoryInput, MemoryQuery

TOOLS = ("memory_save", "memory_search", "memory_read", "memory_doctor")


class MemoryMcpServer:
    def __init__(self, project_root, *, run_root=None, harness="claude", manifest=None):
        self.run_root = run_root
        self.router = default_router(
            memory_project_root=project_root,
            memory_run_root=run_root,
            memory_harness=harness,
            plugin_manifest=manifest,
        )

    def call(self, name, arguments):
        if name not in TOOLS:
            raise CapabilityUnavailable(name)
        provider = self.router.resolve(
            "research.memory." + name.removeprefix("memory_")
        )
        if name == "memory_doctor":
            if arguments:
                raise ValueError("doctor has no caller-controlled roots")
            return provider.doctor()
        if name == "memory_search":
            return provider.search(
                MemoryQuery.model_validate_json(json.dumps(arguments))
            )
        if name == "memory_read":
            if set(arguments) - {"memory_id", "query"} or "memory_id" not in arguments:
                raise ValueError("invalid read arguments")
            return provider.read(
                arguments["memory_id"],
                query=MemoryQuery.model_validate_json(
                    json.dumps(arguments.get("query", {}))
                ),
            )
        if self.run_root is None:
            raise CapabilityUnavailable(
                "memory_save requires process-bound writable run"
            )
        value = MemoryInput.model_validate_json(json.dumps(arguments))
        state = replay_run(self.run_root)
        request = RuntimeCommandRequest(
            schema_version="1.0.0",
            run_id=state.run_id,
            event_id="evt-" + str(uuid.uuid4()),
            command_id="cmd-" + str(uuid.uuid4()),
            expected_revision=state.revision,
            occurred_at=datetime.now(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            actor_id="memory-parent-adapter",
            actor_role="parent_control_plane",
        )
        return provider.save(value, request=request)

    def handle(self, message):
        identifier = message.get("id")
        method = message.get("method")
        if identifier is None:
            return None
        response = {"jsonrpc": "2.0", "id": identifier}
        if method == "initialize":
            return {
                **response,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "arw-memory", "version": "0.1.0"},
                },
            }
        if method == "ping":
            return {**response, "result": {}}
        if method == "tools/list":
            schemas = {
                "memory_save": MemoryInput.model_json_schema(),
                "memory_search": MemoryQuery.model_json_schema(),
                "memory_read": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "query": MemoryQuery.model_json_schema(),
                    },
                    "required": ["memory_id"],
                    "additionalProperties": False,
                },
                "memory_doctor": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
            return {
                **response,
                "result": {
                    "tools": [
                        {
                            "name": name,
                            "description": name,
                            "inputSchema": schemas[name],
                        }
                        for name in TOOLS
                    ]
                },
            }
        if method != "tools/call":
            return {
                **response,
                "error": {"code": -32601, "message": "CapabilityUnavailable"},
            }
        try:
            params = message.get("params", {})
            value = self.call(params["name"], params.get("arguments", {}))
            failed = False
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            value = {
                "code": "CapabilityUnavailable"
                if isinstance(error, CapabilityUnavailable)
                else getattr(error, "code", "memory_request_invalid")
            }
            failed = True
        return {
            **response,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
                ],
                "structuredContent": value,
                "isError": failed,
            },
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument(
        "--harness", choices=("codex", "claude", "cursor", "other"), required=True
    )
    args = parser.parse_args()
    manifest = os.environ.get("ARW_PLUGIN_MANIFEST")
    if os.environ.get("ARW_PLUGIN_ROOT") and not manifest:
        return 66
    server = MemoryMcpServer(
        args.project_root,
        run_root=args.run_root,
        harness=args.harness,
        manifest=Path(manifest) if manifest else None,
    )
    while True:
        raw = sys.stdin.buffer.readline(65_538)
        if not raw:
            return 0
        if len(raw) > 65_536:
            return 65
        try:
            message = strict_json_loads(raw.decode("utf-8"))
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError()
            response = server.handle(message)
        except (ValueError, TypeError):
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Invalid request"},
            }
        if response is not None:
            encoded = canonical_json_bytes(response)
            if len(encoded) > 262_144:
                encoded = canonical_json_bytes(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32603, "message": "OutputBudgetExceeded"},
                    }
                )
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
