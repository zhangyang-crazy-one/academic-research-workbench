from __future__ import annotations

import base64
import hashlib
import itertools
import json
import os
import sys
from pathlib import Path
from typing import Any

from arw.files import FilesAdminService
from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process, snapshot_tree


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXACT_TOOLS = {"list_files", "read_file", "search_files", "get_outline", "get_context"}


def _service(control: Path) -> FilesAdminService:
    sequence = itertools.count(1)
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_test_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _prepared_root(tmp_path: Path) -> tuple[Path, Path, FilesAdminService, dict[str, dict[str, Any]]]:
    root = tmp_path / "root"
    (root / "notes").mkdir(parents=True)
    (root / "notes/a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (root / "notes/中文.md").write_text("# 标题\n\n中文证据行\n", encoding="utf-8")
    (root / "notes/binary.txt").write_bytes(b"valid\xffinvalid")
    control = tmp_path / "control"
    service = _service(control)
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    receipt = service.sync("research-root", extractor_version="1.0.0")
    manifest = json.loads(
        (
            service.generation_path("research-root", receipt.selected_generation_id)
            / "identity-manifest.json"
        ).read_text(encoding="utf-8")
    )
    records = {item["relative_path"]: item for item in manifest["records"]}
    return root, control, service, records


def _invoke(control: Path, root_id: str, requests: list[str]):
    return invoke_jsonrpc_process(
        [
            sys.executable,
            "-m",
            "arw.files_mcp",
            "--control-root",
            str(control),
            "--root-id",
            root_id,
        ],
        requests,
        cwd=REPOSITORY_ROOT,
        environment={
            **os.environ,
            "PYTHONNOUSERSITE": "1",
            "UV_OFFLINE": "1",
        },
    )


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    content = response["result"]["content"]
    assert len(content) == 1 and content[0]["type"] == "text"
    payload = json.loads(content[0]["text"])
    assert isinstance(payload, dict)
    return payload


def _call(identifier: int, name: str, arguments: dict[str, object]) -> str:
    return canonical_request(
        identifier,
        "tools/call",
        {"name": name, "arguments": arguments},
    )


def test_files_profile_advertises_exact_read_only_tool_set(tmp_path: Path) -> None:
    root, control, _, _ = _prepared_root(tmp_path)
    before_root = snapshot_tree(root)
    before_control = snapshot_tree(control)
    requests = [
        canonical_request(
            1,
            "initialize",
            {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}},
        ),
        canonical_request(2, "tools/list", {}),
    ]
    for identifier, forbidden in enumerate(
        ("sync", "crawl", "extract", "rebuild", "repair", "index_repository"), start=3
    ):
        requests.append(_call(identifier, forbidden, {}))

    result = _invoke(control, "research-root", requests)
    assert result.completed.returncode == 0, result.completed.stderr
    assert result.responses[0]["result"]["serverInfo"]["name"] == "academic-research-files"
    tools = result.responses[1]["result"]["tools"]
    assert {tool["name"] for tool in tools} == EXACT_TOOLS
    assert len(tools) == 5
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
    for response in result.responses[2:]:
        assert response["result"]["isError"] is True
        assert _tool_payload(response)["error_code"] == "unknown_tool"
    assert snapshot_tree(root) == before_root
    assert snapshot_tree(control) == before_control


def test_startup_requires_one_registered_root_and_closed_generation(tmp_path: Path) -> None:
    control = tmp_path / "control"
    root = tmp_path / "root"
    root.mkdir()
    service = _service(control)
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")

    absent = _invoke(control, "research-root", [canonical_request(1, "tools/list", {})])
    assert absent.completed.returncode != 0
    assert "selected_generation" in absent.completed.stderr

    unknown = _invoke(control, "another-root", [canonical_request(1, "tools/list", {})])
    assert unknown.completed.returncode != 0
    assert "root" in unknown.completed.stderr.lower()


def test_list_is_paginated_restart_safe_and_live_freshness_aware(tmp_path: Path) -> None:
    root, control, _, records = _prepared_root(tmp_path)
    request = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "max_files": 1,
        "cursor": None,
    }
    before = snapshot_tree(control)
    first = _invoke(control, "research-root", [_call(1, "list_files", request)])
    assert first.completed.returncode == 0, first.completed.stderr
    first_page = _tool_payload(first.responses[0])
    assert first_page["complete_page"] is True
    assert len(first_page["files"]) == 1
    assert first_page["next_cursor"]

    token = first_page["next_cursor"]
    tampered_token = token[:-1] + ("A" if token[-1] != "A" else "B")
    tampered = _invoke(
        control,
        "research-root",
        [_call(1, "list_files", {**request, "cursor": tampered_token})],
    )
    assert tampered.responses[0]["result"]["isError"] is True
    assert _tool_payload(tampered.responses[0])["error_code"] == "cursor_tampered"

    rebound = _invoke(
        control,
        "research-root",
        [_call(1, "list_files", {**request, "max_files": 2, "cursor": token})],
    )
    assert rebound.responses[0]["result"]["isError"] is True
    assert _tool_payload(rebound.responses[0])["error_code"] == "cursor_query_mismatch"

    second_request = {**request, "cursor": first_page["next_cursor"]}
    second = _invoke(control, "research-root", [_call(1, "list_files", second_request)])
    second_page = _tool_payload(second.responses[0])
    assert second_page["files"]
    assert second_page["files"][0]["file_id"] != first_page["files"][0]["file_id"]

    (root / "notes/a.txt").write_text("changed after generation\n", encoding="utf-8")
    live = _invoke(
        control,
        "research-root",
        [_call(1, "list_files", {**request, "max_files": 200})],
    )
    payload = _tool_payload(live.responses[0])
    changed = next(item for item in payload["files"] if item["file_id"] == records["notes/a.txt"]["file_id"])
    assert changed["freshness"] == "stale_metadata"
    assert changed["current_digest"] == hashlib.sha256(
        (root / "notes/a.txt").read_bytes()
    ).hexdigest()
    assert changed["indexed_digest"] == records["notes/a.txt"]["digest"]
    assert snapshot_tree(control) == before


def test_read_byte_line_continuations_and_encoding_fail_closed(tmp_path: Path) -> None:
    root, control, _, records = _prepared_root(tmp_path)
    text_record = records["notes/a.txt"]
    common = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "file_id": text_record["file_id"],
        "relative_path": "notes/a.txt",
        "expected_digest": text_record["digest"],
        "line_range": None,
        "cursor": None,
    }
    first = _invoke(
        control,
        "research-root",
        [_call(1, "read_file", {**common, "byte_range": {"start": 0, "max_bytes": 5}})],
    )
    chunk = _tool_payload(first.responses[0])
    assert chunk["status"] == "ok"
    assert chunk["encoding"] == "bytes"
    assert base64.b64decode(chunk["content"]) == b"alpha"
    assert chunk["truncated"] is True
    assert chunk["next_cursor"]

    continued = _invoke(
        control,
        "research-root",
        [
            _call(
                1,
                "read_file",
                {
                    **common,
                    "byte_range": {"start": 0, "max_bytes": 5},
                    "cursor": chunk["next_cursor"],
                },
            )
        ],
    )
    assert _tool_payload(continued.responses[0])["content"] != chunk["content"]

    lines = _invoke(
        control,
        "research-root",
        [
            _call(
                1,
                "read_file",
                {
                    **common,
                    "byte_range": None,
                    "line_range": {"start_line": 2, "max_lines": 1},
                },
            )
        ],
    )
    line_payload = _tool_payload(lines.responses[0])
    assert line_payload["encoding"] == "utf-8"
    assert line_payload["content"] == "beta\n"

    invalid = records["notes/binary.txt"]
    invalid_read = _invoke(
        control,
        "research-root",
        [
            _call(
                1,
                "read_file",
                {
                    **common,
                    "file_id": invalid["file_id"],
                    "relative_path": "notes/binary.txt",
                    "expected_digest": invalid["digest"],
                    "byte_range": None,
                    "line_range": {"start_line": 1, "max_lines": 1},
                },
            )
        ],
    )
    denied = _tool_payload(invalid_read.responses[0])
    assert denied["status"] == "encoding_error"
    assert "content" not in denied
    assert "next_cursor" not in denied
    assert snapshot_tree(root)


def test_read_replacement_conflict_returns_no_body(tmp_path: Path) -> None:
    root, control, _, records = _prepared_root(tmp_path)
    record = records["notes/a.txt"]
    (root / "notes/a.txt").write_text("replacement secret must not leak\n", encoding="utf-8")
    result = _invoke(
        control,
        "research-root",
        [
            _call(
                1,
                "read_file",
                {
                    "schema_version": "1.0.0",
                    "root_id": "research-root",
                    "file_id": record["file_id"],
                    "relative_path": "notes/a.txt",
                    "expected_digest": record["digest"],
                    "byte_range": {"start": 0, "max_bytes": 64},
                    "line_range": None,
                    "cursor": None,
                },
            )
        ],
    )
    conflict = _tool_payload(result.responses[0])
    assert conflict["status"] == "stale_conflict"
    assert conflict["error_code"] == "digest_mismatch"
    assert "content" not in conflict
    assert "next_cursor" not in conflict
    assert "replacement secret" not in json.dumps(conflict)
