"""Modern stdio wire fixture for the real files adapter; legacy goldens stay frozen."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.file_plane_helpers import canonical_request

from .normalize import read_golden_json
from .test_mcp_contract import GOLDEN_DIR, _payload, _prepare, _server, _valid_requests

pytestmark = pytest.mark.v2_compat


def _modern(
    identifier: int, method: str, params: dict[str, object] | None = None
) -> str:
    return canonical_request(
        identifier,
        method,
        {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "fixture",
                    "version": "1.0",
                },
            },
        },
    )


def test_modern_files_retrieval_workflow(tmp_path: Path) -> None:
    control, generation_id, records = _prepare(tmp_path)
    _, name, arguments = _valid_requests(generation_id, records)[0]
    result = _server(
        control,
        [
            _modern(1, "server/discover"),
            _modern(2, "tools/list"),
            _modern(3, "tools/call", {"name": name, "arguments": arguments}),
        ],
    )
    assert result.completed.returncode == 0, result.completed.stderr
    assert len(result.responses) == 3
    fixture = read_golden_json(GOLDEN_DIR / "modern_era.json")
    discovery, listed, called = (response["result"] for response in result.responses)
    assert discovery["supportedVersions"] == fixture["supported_versions"]
    assert discovery["capabilities"] == {"tools": {"listChanged": False}}
    assert [tool["name"] for tool in listed["tools"]] == fixture["tool_names"]
    assert called["isError"] is False
    assert _payload(result.responses[2])["complete_page"] is True
    for response in (discovery, listed, called):
        assert response["resultType"] == "complete"
        assert (
            response["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
            == fixture["server_name"]
        )
