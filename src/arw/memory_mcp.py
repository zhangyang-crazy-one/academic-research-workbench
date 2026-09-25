"""Optional four-tool memory transport with process-bound project and harness."""

import argparse
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_memory import MemoryInput, MemoryQuery
from arw.mcp_stdio import StdioProtocol, run_stdio

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
        return StdioProtocol(
            name="arw-memory",
            version="0.1.0",
            tools=self.tools,
            call_tool=self._call_tool,
        ).handle(message)

    @staticmethod
    def tools():
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
        return [
            {"name": name, "description": name, "inputSchema": schemas[name]}
            for name in TOOLS
        ]

    def _call_tool(self, params):
        try:
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
            "content": [
                {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
            ],
            "structuredContent": value,
            "isError": failed,
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
    return run_stdio(server.handle)


if __name__ == "__main__":
    raise SystemExit(main())
