"""v2 compatibility baseline: file-plane MCP contract golden fixtures.

Pins the JSON-RPC wire contract of the in-repo files MCP server
(``python -m arw.files_mcp``): the exact read-only tool set, golden
request/response envelopes (id echo, jsonrpc version, isError) for each
tool, and the error taxonomy for adversarial inputs. All happy-path
requests are schema-valid against the strict request models so the
goldens pin real tool behavior, not validation rejections. Runs against
the pure-Python server — no native file-base binary required.

Note on required taxonomy categories: the file-base *native* contract's
``not_found``/``not_indexed``/``too_large``/``unsupported``/
``extraction_failed``/``access_denied`` distinctions belong to the native
binary profile (see test_filebase_mcp_contract.py) and the v1 confinement
suites; the Python read-only profile pinned here exposes its own
discriminated statuses, which are pinned wholesale below. ``access_denied``
for sensitive paths is enforced at sync time (sensitive files never enter
an indexable manifest) and is covered by tests/integration/test_files_security.py.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from arw.files import FilesAdminService
from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process

from .normalize import read_golden_json

pytestmark = pytest.mark.v2_compat

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).parent / "golden" / "mcp"

# Server tool order is contract-significant (tools/list sequence).
EXPECTED_TOOLS = ["list_files", "read_file", "search_files", "get_outline", "get_context"]

INIT_REQUEST = canonical_request(
    1,
    "initialize",
    {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "v2-compat-baseline", "version": "1.0.0"},
    },
)

# MCP lifecycle: the client must send notifications/initialized after the
# initialize response and before normal requests. Notifications carry no id
# and receive no response.
INITIALIZED_NOTIFICATION = (
    '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
)


def _prepare(tmp_path: Path) -> tuple[Path, str, dict[str, dict[str, Any]]]:
    """Deterministic corpus: fixed bytes, fixed clock, fixed id sequence.

    Returns (control_root, selected_generation_id, manifest records by path).
    """
    root = tmp_path / "root"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "notes" / "中文.md").write_text("# 标题\n\n中文证据行\n", encoding="utf-8")
    (root / "notes" / "binary.txt").write_bytes(b"valid\xffinvalid")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    control = tmp_path / "control"
    sequence = itertools.count(1)
    service = FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_test_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    receipt = service.sync("research-root", extractor_version="1.0.0")
    generation_id = receipt.selected_generation_id
    assert generation_id is not None, "sync must select a generation"
    manifest_path = (
        service.generation_path("research-root", generation_id) / "identity-manifest.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise AssertionError(f"identity manifest unreadable: {error}") from error
    records = {item["relative_path"]: item for item in manifest["records"]}
    assert ".env" not in records, "sensitive files must never enter the manifest"
    return control, generation_id, records


def _server(control: Path, requests: list[str]):
    return invoke_jsonrpc_process(
        [
            sys.executable,
            "-m",
            "arw.files_mcp",
            "--control-root",
            str(control),
            "--root-id",
            "research-root",
        ],
        requests,
        cwd=REPOSITORY_ROOT,
        environment={**os.environ, "PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"},
    )


def _call(identifier: int, name: str, arguments: dict[str, object]) -> str:
    return canonical_request(identifier, "tools/call", {"name": name, "arguments": arguments})


def _payload(response: dict[str, Any]) -> dict[str, Any]:
    try:
        content = response["result"]["content"]
        first = content[0]
        text = first["text"]
    except (KeyError, IndexError, TypeError) as error:
        raise AssertionError(f"malformed tool envelope: {error}") from error
    assert len(content) == 1 and first["type"] == "text"
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise AssertionError(f"tool payload is not valid JSON: {error}") from error
    assert isinstance(payload, dict)
    return payload


def _scrub(value: object) -> object:
    """Replace only deliberately unstable fields with a placeholder.

    - ``hit_id``: HMAC-signed token, key is per-installation.
    - ``message``: prose detail; structure and codes are pinned, prose is not.

    Everything else — including deterministic SHA-256 digests of the fixed
    fixture bytes — is pinned exactly.
    """
    if isinstance(value, dict):
        return {
            key: ("<SCRUBBED>" if key in {"hit_id", "message"} else _scrub(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _collect_payloads(
    result: Any, identifiers: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Map tool-call response ids to pinned envelopes + scrubbed payloads.

    The JSON-RPC envelope is contract-significant: id echo, jsonrpc version,
    and isError are pinned alongside the decoded payload.
    """
    responses = result.responses
    assert len(responses) == len(identifiers) + 1, "expected init + tool responses"
    tool_responses = responses[1:]
    collected: dict[str, dict[str, Any]] = {}
    for identifier, response in zip(identifiers, tool_responses, strict=True):
        assert response.get("jsonrpc") == "2.0", f"response {identifier} lost jsonrpc"
        assert str(response.get("id")) == identifier, (
            f"response id mismatch: expected {identifier}, got {response.get('id')}"
        )
        try:
            is_error = response["result"]["isError"]
        except (KeyError, TypeError) as error:
            raise AssertionError(f"response {identifier} missing isError: {error}") from error
        scrubbed = _scrub(_payload(response))
        assert isinstance(scrubbed, dict)
        collected[identifier] = {"isError": is_error, "payload": scrubbed}
    return collected


def _valid_requests(
    generation_id: str, records: dict[str, dict[str, Any]]
) -> list[tuple[int, str, dict[str, object]]]:
    """Schema-valid calls for all five tools against the seeded corpus."""
    a_txt = records["notes/a.txt"]
    zh_md = records["notes/中文.md"]
    return [
        (2, "list_files", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "max_files": 50,
            "cursor": None,
        }),
        (3, "read_file", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "file_id": a_txt["file_id"],
            "relative_path": "notes/a.txt",
            "expected_digest": None,
            "byte_range": None,
            "line_range": {"start_line": 1, "max_lines": 10},
            "cursor": None,
        }),
        (4, "search_files", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "mode": "full_text",
            "query": "beta",
            "max_hits": 10,
            "max_snippet_bytes": 200,
            "cursor": None,
        }),
        (5, "get_outline", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": generation_id,
            "file_id": zh_md["file_id"],
            "expected_digest": zh_md["digest"],
            "max_nodes": 50,
            "cursor": None,
        }),
        (6, "get_context", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": generation_id,
            "file_id": a_txt["file_id"],
            "expected_digest": a_txt["digest"],
            "hit_id": None,
            "location": {"start_byte": 6, "end_byte": 10, "start_line": 2, "end_line": 2},
            "before_lines": 1,
            "after_lines": 1,
        }),
    ]


def test_tools_list_matches_golden(tmp_path: Path) -> None:
    control, _, _ = _prepare(tmp_path)
    result = _server(control, [INIT_REQUEST, INITIALIZED_NOTIFICATION, canonical_request(2, "tools/list", {})])
    assert result.completed.returncode == 0, result.completed.stderr
    golden = read_golden_json(GOLDEN_DIR / "tools_list.json")
    # The negotiated handshake is contract-significant: dropping v1 protocol
    # compatibility or changing capabilities must fail this gate.
    init_result = result.responses[0]["result"]
    assert init_result["protocolVersion"] == golden["protocol_version"]
    assert init_result["capabilities"] == golden["capabilities"]
    server_info = init_result["serverInfo"]
    assert server_info["name"] == golden["server_name"]
    tools = result.responses[1]["result"]["tools"]
    assert [tool["name"] for tool in tools] == golden["tool_names"] == EXPECTED_TOOLS
    assert [tool["description"] for tool in tools] == golden["tool_descriptions"]
    # Input schemas are part of the wire contract; pin them wholesale.
    assert {tool["name"]: tool["inputSchema"] for tool in tools} == golden["input_schemas"]


def test_tool_happy_paths_match_golden(tmp_path: Path) -> None:
    """Schema-valid calls must reach tool dispatch and return ok payloads."""
    control, generation_id, records = _prepare(tmp_path)
    calls = _valid_requests(generation_id, records)
    result = _server(
        control, [INIT_REQUEST, INITIALIZED_NOTIFICATION, *[_call(i, name, args) for i, name, args in calls]]
    )
    assert result.completed.returncode == 0, result.completed.stderr
    golden = read_golden_json(GOLDEN_DIR / "tool_happy_paths.json")
    actual = _collect_payloads(result, tuple(str(i) for i, _, _ in calls))
    # Every happy-path response must be a real success, never a validation error.
    for identifier, envelope in actual.items():
        assert not envelope["isError"], f"call {identifier} marked isError"
        assert "error_code" not in envelope["payload"], (
            f"call {identifier} was rejected: {envelope['payload']}"
        )
    # Pagination termination is contract-significant: a complete page must
    # carry next_cursor null exactly (never a cursor token).
    list_payload = actual["2"]["payload"]
    assert list_payload["complete_page"]
    assert list_payload["next_cursor"] is None
    assert actual == golden


def test_error_taxonomy_matches_golden(tmp_path: Path) -> None:
    """Schema-valid adversarial calls must reach the pinned error branches."""
    control, generation_id, records = _prepare(tmp_path)
    a_txt = records["notes/a.txt"]
    binary = records["notes/binary.txt"]
    valid_read = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "file_id": a_txt["file_id"],
        "relative_path": "notes/a.txt",
        "expected_digest": None,
        "byte_range": None,
        "line_range": {"start_line": 1, "max_lines": 10},
        "cursor": None,
    }
    requests = [
        INIT_REQUEST,
        # unknown tool name
        _call(2, "not_a_tool", {}),
        # schema-invalid request (wrong type) -> invalid_request
        _call(3, "read_file", {**valid_read, "file_id": 123}),
        # schema-valid request naming another root -> root_denied
        _call(4, "read_file", {**valid_read, "root_id": "other-root"}),
        # schema-valid request, file_id/relative_path mismatch -> identity_mismatch
        _call(5, "read_file", {**valid_read, "relative_path": "notes/中文.md"}),
        # schema-valid read of a binary file -> invalid_utf8 refusal branch
        _call(6, "read_file", {
            **valid_read,
            "file_id": binary["file_id"],
            "relative_path": "notes/binary.txt",
        }),
        # schema-valid context anchor beyond end of file -> anchor_out_of_range
        _call(8, "get_context", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": generation_id,
            "file_id": a_txt["file_id"],
            "expected_digest": a_txt["digest"],
            "hit_id": None,
            "location": {"start_byte": 100000, "end_byte": 100010},
            "before_lines": 1,
            "after_lines": 1,
        }),
        # schema-valid outline request for a binary file -> degraded branch
        _call(9, "get_outline", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": generation_id,
            "file_id": binary["file_id"],
            "expected_digest": binary["digest"],
            "max_nodes": 50,
            "cursor": None,
        }),
        # schema-valid outline request for a plain text file -> no_structure
        _call(10, "get_outline", {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": generation_id,
            "file_id": a_txt["file_id"],
            "expected_digest": a_txt["digest"],
            "max_nodes": 50,
            "cursor": None,
        }),
    ]
    requests.insert(1, INITIALIZED_NOTIFICATION)
    result = _server(control, requests)
    assert result.completed.returncode == 0, result.completed.stderr
    golden = read_golden_json(GOLDEN_DIR / "error_taxonomy.json")
    actual = _collect_payloads(result, ("2", "3", "4", "5", "6", "8", "9", "10"))
    # Full-envelope compare: every field is pinned after scrubbing only the
    # deliberately unstable prose (message) and per-installation signed tokens.
    assert actual == golden
    for identifier, expected in golden.items():
        payload = expected["payload"]
        if expected["isError"]:
            assert "error_code" in payload, (
                f"golden {identifier} marks isError without an error_code"
            )
