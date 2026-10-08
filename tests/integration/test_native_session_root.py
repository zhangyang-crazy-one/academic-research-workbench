"""Direct-native read_file must stay bound to the current daemon session."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.file_plane_helpers import canonical_request, invoke_jsonrpc_process


def _binary() -> Path:
    configured = os.environ.get("ARW_FILE_BASE_NATIVE_BINARY")
    if not configured:
        pytest.skip("set ARW_FILE_BASE_NATIVE_BINARY to a native build")
    binary = Path(configured)
    assert binary.is_file() and os.access(binary, os.X_OK)
    return binary


@pytest.fixture
def runtime_parent() -> Path:
    # The production CBM_RUNTIME_DIR override isolates the endpoint and keeps
    # the Unix socket path short enough for every supported Linux host.
    with tempfile.TemporaryDirectory(prefix="arw72-") as directory:
        yield Path(directory)


def _environment(
    tmp_path: Path, runtime_parent: Path, root: Path | None, root_id: str | None
) -> dict[str, str]:
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "CBM_CACHE_DIR": str(tmp_path / "cache"),
        "CBM_RUNTIME_DIR": str(runtime_parent),
        "CBM_DISABLE_UPDATE_CHECK": "1",
        "CBM_LOG_LEVEL": "error",
    }
    if root is not None:
        environment["CBM_ALLOWED_ROOT"] = str(root)
    if root_id is not None:
        environment["CBM_ALLOWED_ROOT_ID"] = root_id
    return environment


def _request(
    root_id: str,
    relative_path: str = "paper.txt",
    *,
    max_bytes: int = 4096,
    max_lines: int = 200,
) -> str:
    return canonical_request(
        3,
        "tools/call",
        {
            "name": "read_file",
            "arguments": {
                "schema_version": "1.0.0",
                "allowed_root": root_id,
                "relative_path": relative_path,
                "max_bytes": max_bytes,
                "max_lines": max_lines,
            },
        },
    )


def _probe(binary: Path, tmp_path: Path, environment: dict[str, str], request: str):
    result = invoke_jsonrpc_process(
        [str(binary)],
        [
            canonical_request(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "arw-session-root-test", "version": "1"},
                },
            ),
            canonical_request(2, "tools/list", {}),
            request,
        ],
        cwd=tmp_path,
        environment=environment,
        timeout=30,
    )
    assert result.completed.returncode == 0, result.completed.stderr[-1000:]
    assert len(result.responses) == 3
    listed = {tool["name"] for tool in result.responses[1]["result"]["tools"]}
    call = result.responses[2]["result"]
    payload = json.loads(call["content"][0]["text"])
    assert call["structuredContent"] == payload
    return listed, call["isError"], payload


@pytest.mark.parametrize("first", ["A", "B"])
@pytest.mark.parametrize("same_id", [True, False])
def test_shared_daemon_rejects_other_root_in_both_start_orders(
    tmp_path: Path, runtime_parent: Path, first: str, same_id: bool
) -> None:
    binary = _binary()
    (tmp_path / "home").mkdir()
    roots = {name: tmp_path / name for name in ("A", "B")}
    for name, root in roots.items():
        root.mkdir()
        (root / "paper.txt").write_text(f"synthetic-{name}\n", encoding="utf-8")
    ids = {"A": "shared", "B": "shared" if same_id else "other"}
    second = "B" if first == "A" else "A"
    initial = _environment(tmp_path, runtime_parent, roots[first], ids[first])
    started = subprocess.run(
        [str(binary), "daemon", "start"],
        cwd=tmp_path,
        env=initial,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    try:
        first_tools, first_error, first_payload = _probe(
            binary, tmp_path, initial, _request(ids[first])
        )
        assert "read_file" in first_tools
        assert first_error is False
        assert first_payload["content"] == f"synthetic-{first}\n"

        other = _environment(tmp_path, runtime_parent, roots[second], ids[second])
        other_tools, _, other_payload = _probe(
            binary, tmp_path, other, _request(ids[second])
        )
        assert "read_file" not in other_tools
        assert other_payload["status"] == "denied"
        # Another root ID keeps the public root_denied contract; the same ID
        # naming a different installed root is the session mismatch.
        assert other_payload["reason"] == (
            "root_session_mismatch" if same_id else "root_denied"
        )
        assert "synthetic-" not in json.dumps(other_payload)
    finally:
        stopped = subprocess.run(
            [str(binary), "daemon", "stop"],
            cwd=tmp_path,
            env=initial,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert stopped.returncode == 0, stopped.stderr


@pytest.mark.parametrize("daemon_has_root", [True, False])
def test_unconfigured_daemon_or_session_cannot_use_process_fallback(
    tmp_path: Path,
    runtime_parent: Path,
    daemon_has_root: bool,
) -> None:
    binary = _binary()
    (tmp_path / "home").mkdir()
    root = tmp_path / "B"
    root.mkdir()
    (root / "paper.txt").write_text("synthetic-B\n", encoding="utf-8")
    daemon_environment = _environment(
        tmp_path,
        runtime_parent,
        root if daemon_has_root else None,
        "B" if daemon_has_root else None,
    )
    client_environment = _environment(
        tmp_path,
        runtime_parent,
        None if daemon_has_root else root,
        None if daemon_has_root else "B",
    )
    started = subprocess.run(
        [str(binary), "daemon", "start"],
        cwd=tmp_path,
        env=daemon_environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    try:
        tools, _, payload = _probe(binary, tmp_path, client_environment, _request("B"))
        assert "read_file" not in tools
        assert payload["status"] == "denied"
        # A daemon without the capability denies the root itself; a session
        # without an installed root mismatches the daemon's capability.
        assert payload["reason"] == (
            "root_session_mismatch" if daemon_has_root else "root_denied"
        )
        assert "synthetic-B" not in json.dumps(payload)
    finally:
        stopped = subprocess.run(
            [str(binary), "daemon", "stop"],
            cwd=tmp_path,
            env=daemon_environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert stopped.returncode == 0, stopped.stderr


def test_same_session_preserves_path_and_budget_denials(
    tmp_path: Path, runtime_parent: Path
) -> None:
    binary = _binary()
    (tmp_path / "home").mkdir()
    root = tmp_path / "A"
    root.mkdir()
    (root / "paper.txt").write_text("synthetic-A\n", encoding="utf-8")
    (root / "link.txt").symlink_to(root / "paper.txt")
    environment = _environment(tmp_path, runtime_parent, root, "A")
    started = subprocess.run(
        [str(binary), "daemon", "start"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    try:
        for request, reason in (
            (_request("A", "../paper.txt"), "path_traversal"),
            (_request("A", "/etc/passwd"), "absolute_path"),
            (_request("A", "link.txt"), "symlink_escape"),
            (_request("A", max_bytes=4097), "budget_exceeded"),
            (_request("A", max_lines=201), "budget_exceeded"),
        ):
            _, _, payload = _probe(binary, tmp_path, environment, request)
            assert payload["status"] == "denied"
            assert payload["reason"] == reason
    finally:
        stopped = subprocess.run(
            [str(binary), "daemon", "stop"],
            cwd=tmp_path,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert stopped.returncode == 0, stopped.stderr
