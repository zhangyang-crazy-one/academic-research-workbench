from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

import arw.files_mcp as files_mcp
from arw.files import FilesAdminService, load_query_generation
from arw.files_mcp import FilesMcpServer
from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process, snapshot_tree


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTECTED = "ARW-TEST-PROTECTED-BODY-7A31"
REPLACEMENT = "ARW-TEST-RUNTIME-DB-REPLACEMENT-91D2"


def _service(control: Path) -> FilesAdminService:
    sequence = itertools.count(1)
    return FilesAdminService(
        control,
        id_factory=lambda kind: f"{kind}_security_{next(sequence):03d}",
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _prepare(tmp_path: Path) -> tuple[Path, Path, FilesAdminService, FilesMcpServer, dict[str, Any]]:
    root = tmp_path / "root"
    root.mkdir()
    (root / "paper.md").write_text(
        f"# Evidence\n\ncurrent research evidence {PROTECTED}\n", encoding="utf-8"
    )
    (root / ".env").write_text("ARW-TEST-PRIVATE-ENV-5521\n", encoding="utf-8")
    (root / ".arwignore").write_text(".env\n", encoding="utf-8")
    control = tmp_path / "control"
    service = _service(control)
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    service.sync("research-root", extractor_version="1.0.0")
    generation = load_query_generation(control, "research-root")
    record = next(item for item in generation.identity.records if item.relative_path == "paper.md")
    return root, control, service, FilesMcpServer(generation), record.model_dump(mode="json")


def _call(server: FilesMcpServer, name: str, arguments: dict[str, object]) -> tuple[dict[str, Any], bool]:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    result = response["result"]
    payload = json.loads(result["content"][0]["text"])
    return payload, bool(result["isError"])


def _search(server: FilesMcpServer, query: str) -> tuple[dict[str, Any], bool]:
    return _call(
        server,
        "search_files",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "mode": "full_text",
            "query": query,
            "max_hits": 10,
            "max_snippet_bytes": 128,
            "cursor": None,
        },
    )


def test_runtime_database_replacement_is_integrity_error_without_body(tmp_path: Path) -> None:
    root, _, service, server, _ = _prepare(tmp_path)
    first_id = server.generation.selected.generation_id
    first_database = server.generation.database_path

    (root / "paper.md").write_text(
        f"# Replaced\n\n{REPLACEMENT}\n", encoding="utf-8"
    )
    second = service.sync("research-root", extractor_version="1.0.0")
    second_database = service.generation_path(
        "research-root", second.selected_generation_id
    ) / "files.sqlite3"
    first_database.unlink()
    shutil.copyfile(second_database, first_database)

    payload, error = _search(server, REPLACEMENT)
    assert error is True
    assert payload["error_code"] == "generation_integrity_changed"
    assert REPLACEMENT not in json.dumps(payload)
    assert server.generation.selected.generation_id == first_id


def test_descriptor_swap_during_read_returns_no_replacement_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _, server, record = _prepare(tmp_path)
    target = root / "paper.md"
    target.write_text("A" * (2 * 1024 * 1024), encoding="utf-8")
    service = _service(tmp_path / "race-control")
    service.register_root(root_id="race-root", root_path=root, policy_id="research-files-v1")
    service.sync("race-root", extractor_version="1.0.0")
    generation = load_query_generation(service.control_root, "race-root")
    server = FilesMcpServer(generation)
    record = next(item for item in generation.identity.records if item.relative_path == "paper.md")

    real_read = os.read
    swapped = False

    def racing_read(descriptor: int, amount: int) -> bytes:
        nonlocal swapped
        body = real_read(descriptor, amount)
        if body and not swapped:
            swapped = True
            target.rename(root / "paper.original")
            target.write_text(REPLACEMENT, encoding="utf-8")
        return body

    monkeypatch.setattr(files_mcp.os, "read", racing_read)
    payload, error = _call(
        server,
        "read_file",
        {
            "schema_version": "1.0.0",
            "root_id": "race-root",
            "file_id": record.file_id,
            "relative_path": record.relative_path,
            "expected_digest": record.digest,
            "byte_range": {"start": 0, "max_bytes": 64},
            "line_range": None,
            "cursor": None,
        },
    )
    assert error is False
    assert payload["status"] == "stale_conflict"
    assert payload["error_code"] == "descriptor_changed"
    assert "content" not in payload
    assert REPLACEMENT not in json.dumps(payload)


def test_root_replacement_symlink_sensitive_and_traversal_fail_closed(tmp_path: Path) -> None:
    root, _, _, server, record = _prepare(tmp_path)
    original = tmp_path / "root-original"
    root.rename(original)
    root.mkdir()
    (root / "paper.md").write_text(REPLACEMENT, encoding="utf-8")
    stale, stale_error = _search(server, "evidence")
    assert stale_error is False
    assert stale["hits"][0]["freshness"] == "stale_metadata"
    assert stale["hits"][0]["snippet"] is None
    assert REPLACEMENT not in json.dumps(stale)

    for relative_path in ("../root-original/paper.md", ".env", "escape.pem"):
        if relative_path == "escape.pem":
            (root / relative_path).symlink_to(original / "paper.md")
        payload, error = _call(
            server,
            "read_file",
            {
                "schema_version": "1.0.0",
                "root_id": "research-root",
                "file_id": record["file_id"],
                "relative_path": relative_path,
                "expected_digest": record["digest"],
                "byte_range": {"start": 0, "max_bytes": 64},
                "line_range": None,
                "cursor": None,
            },
        )
        assert error is True
        assert "content" not in payload
        assert PROTECTED not in json.dumps(payload)


def test_malformed_json_contract_cursor_query_and_budgets_are_rejected(tmp_path: Path) -> None:
    _, control, _, server, _ = _prepare(tmp_path)
    malformed_cases = [
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "mode": "full_text",
            "query": 'title:secret OR "phrase"*',
            "max_hits": 10,
            "max_snippet_bytes": 64,
            "cursor": None,
        },
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "mode": "exact",
            "query": "证" * 4096,
            "max_hits": 101,
            "max_snippet_bytes": 2049,
            "cursor": None,
        },
    ]
    for request in malformed_cases:
        payload, error = _call(server, "search_files", request)
        assert error is True
        assert payload["error_code"] == "invalid_request"
        assert "hits" not in payload

    valid, error = _search(server, "evidence")
    assert error is False
    cursor_request = {
        "schema_version": "1.0.0",
        "root_id": "research-root",
        "max_files": 1,
        "cursor": "not-a-signed-cursor",
    }
    payload, error = _call(server, "list_files", cursor_request)
    assert error is True
    assert payload["error_code"] in {"cursor_malformed", "cursor_tampered"}

    process = invoke_jsonrpc_process(
        [
            sys.executable,
            "-m",
            "arw.files_mcp",
            "--control-root",
            str(control),
            "--root-id",
            "research-root",
        ],
        ["{malformed", canonical_request(2, "tools/list", {})],
        cwd=REPOSITORY_ROOT,
        environment={**os.environ, "PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"},
    )
    assert process.completed.returncode == 0
    assert process.responses[0]["error"]["code"] == -32700
    assert len(process.responses[1]["result"]["tools"]) == 5
    assert PROTECTED not in process.completed.stderr


def test_all_query_tools_leave_root_and_control_byte_identical(tmp_path: Path) -> None:
    root, control, _, server, record = _prepare(tmp_path)
    before_root = snapshot_tree(root)
    before_control = snapshot_tree(control)

    listed, _ = _call(
        server,
        "list_files",
        {"schema_version": "1.0.0", "root_id": "research-root", "max_files": 10, "cursor": None},
    )
    read, _ = _call(
        server,
        "read_file",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "file_id": record["file_id"],
            "relative_path": record["relative_path"],
            "expected_digest": record["digest"],
            "byte_range": None,
            "line_range": {"start_line": 1, "max_lines": 10},
            "cursor": None,
        },
    )
    search, _ = _search(server, "evidence")
    outline, _ = _call(
        server,
        "get_outline",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": record["file_id"],
            "expected_digest": record["digest"],
            "max_nodes": 10,
            "cursor": None,
        },
    )
    context, _ = _call(
        server,
        "get_context",
        {
            "schema_version": "1.0.0",
            "root_id": "research-root",
            "generation_id": server.generation.selected.generation_id,
            "file_id": record["file_id"],
            "expected_digest": record["digest"],
            "hit_id": search["hits"][0]["hit_id"],
            "location": None,
            "before_lines": 1,
            "after_lines": 1,
        },
    )
    assert listed["files"] and read["status"] == "ok"
    assert search["hits"] and outline["nodes"] and context["context"]
    assert snapshot_tree(root) == before_root
    assert snapshot_tree(control) == before_control
    serialized = json.dumps([listed, read, search, outline, context])
    assert "ARW-TEST-PRIVATE-ENV-5521" not in serialized
