"""v2 compatibility baseline: pinned file-base native binary MCP surface.

Pins the protocol negotiation (MCP 2025-11-25) and the exact advertised
tool set of the vendored file-base binary — the actual staged provider v2
must stay compatible with during migration. Skipped when the binary is not
materialized locally; CI always materializes it via scripts/materialize-sources.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process

from .normalize import read_golden_json

pytestmark = pytest.mark.v2_compat

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NATIVE_BINARY = REPOSITORY_ROOT / ".file-base" / "bin" / "file-base"
GOLDEN_DIR = Path(__file__).parent / "golden" / "filebase"

pytestmark = [
    pytest.mark.v2_compat,
    pytest.mark.skipif(
        not NATIVE_BINARY.is_file() or not os.access(NATIVE_BINARY, os.X_OK),
        reason="file-base native binary not materialized (.file-base/bin/file-base)",
    ),
]


def test_native_binary_surface_matches_golden(tmp_path: Path) -> None:
    """Protocol negotiation + tool list of the pinned binary are frozen."""
    environment = {
        "CBM_ALLOWED_ROOT": str(tmp_path),
        "CBM_ALLOWED_ROOT_ID": "research-root",
        "CBM_CACHE_DIR": str(tmp_path / "cache"),
        "CBM_DISABLE_UPDATE_CHECK": "1",
        "CBM_LOG_LEVEL": "error",
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
    }
    result = invoke_jsonrpc_process(
        [str(NATIVE_BINARY)],
        [
            canonical_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "v2-compat-baseline", "version": "1.0.0"},
                },
            ),
            '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
            canonical_request(2, "tools/list", {}),
        ],
        cwd=tmp_path,
        environment=environment,
    )
    assert result.completed.returncode == 0, result.completed.stderr[-500:]

    golden = read_golden_json(GOLDEN_DIR / "native_surface.json")
    initialize = result.responses[0]["result"]
    assert initialize["protocolVersion"] == golden["protocol_version"] == "2025-11-25"
    assert initialize["serverInfo"]["name"] == golden["server_name"]
    # Capability negotiation is contract-significant: clients gate tool
    # discovery on it before issuing tools/list.
    assert initialize["capabilities"] == golden["capabilities"]

    tools = result.responses[1]["result"]["tools"]
    names = [tool["name"] for tool in tools]
    assert names == golden["tool_names"], (
        "file-base tool surface drifted; during migration the staged provider "
        "must keep its advertised contract stable"
    )
    descriptions = {tool["name"]: tool["description"] for tool in tools}
    assert descriptions == golden["tool_descriptions"]
    # Input/output schemas are wire contract: a changed schema breaks clients.
    input_schemas = {tool["name"]: tool["inputSchema"] for tool in tools}
    assert input_schemas == golden["input_schemas"]
    output_schemas = {tool["name"]: tool.get("outputSchema") for tool in tools}
    assert output_schemas == golden["output_schemas"]


CONFINEMENT_ALLOWED = REPOSITORY_ROOT / "tests" / "fixtures" / "confinement" / "allowed"


def _native_call(identifier: int, name: str, arguments: dict[str, object]) -> str:
    return canonical_request(identifier, "tools/call", {"name": name, "arguments": arguments})


def test_native_read_file_call_envelopes_match_golden(tmp_path: Path) -> None:
    """Native tools/call behavior is frozen: happy path + traversal denial.

    tools/list metadata alone cannot catch dispatch or result regressions;
    these goldens pin actual native read_file behavior on the confinement
    fixture root.
    """
    environment = {
        "CBM_ALLOWED_ROOT": str(CONFINEMENT_ALLOWED),
        "CBM_ALLOWED_ROOT_ID": "phase1-fixture",
        "CBM_CACHE_DIR": str(tmp_path / "cache"),
        "CBM_DISABLE_UPDATE_CHECK": "1",
        "CBM_LOG_LEVEL": "error",
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
    }
    read_args = {
        "schema_version": "1.0.0",
        "allowed_root": "phase1-fixture",
        "relative_path": "paper.tex",
        "max_bytes": 4096,
        "max_lines": 200,
    }
    result = invoke_jsonrpc_process(
        [str(NATIVE_BINARY)],
        [
            canonical_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "v2-compat-baseline", "version": "1.0.0"},
                },
            ),
            '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
            _native_call(2, "read_file", read_args),
            _native_call(3, "read_file", {**read_args, "relative_path": "../outside/secret.txt"}),
        ],
        cwd=tmp_path,
        environment=environment,
    )
    assert result.completed.returncode == 0, result.completed.stderr[-500:]

    golden = read_golden_json(GOLDEN_DIR / "native_calls.json")
    assert len(result.responses) == 3, "init + two tool calls expected"
    collected: dict[str, dict[str, object]] = {}
    for identifier, response in zip(("2", "3"), result.responses[1:], strict=True):
        assert response.get("jsonrpc") == "2.0"
        assert str(response.get("id")) == identifier
        content = response["result"]["content"]
        assert len(content) == 1 and content[0]["type"] == "text"
        try:
            payload = json.loads(content[0]["text"])
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise AssertionError(f"native payload malformed: {error}") from error
        # structuredContent is the machine contract; it must mirror the text
        # payload for clients that consume either channel.
        structured = response["result"].get("structuredContent")
        assert isinstance(structured, dict), f"call {identifier} lost structuredContent"
        assert structured.get("status") == payload.get("status"), (
            f"call {identifier}: structuredContent/text status mismatch"
        )
        # message prose is unpinned; everything else is pinned, including the
        # isError flag and the full structuredContent body.
        payload.pop("message", None)
        structured = {k: v for k, v in structured.items() if k != "message"}
        collected[identifier] = {
            "isError": response["result"].get("isError"),
            "payload": payload,
            "structured": structured,
        }
    assert collected == golden
