from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from arw.files import FilesAdminService


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/confinement"
ALLOWED_ROOT = FIXTURE_ROOT / "allowed"
OUTSIDE_SECRET = FIXTURE_ROOT / "outside/secret.txt"
ROOT_CAPABILITY = "phase1-fixture"


def _request(identifier: int, method: str, params: dict[str, object]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params},
        separators=(",", ":"),
        sort_keys=True,
    )


def _snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    records = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            records.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            records.append((relative, "directory", ""))
        else:
            records.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(records)


def _required_executable(relative_path: str) -> Path:
    executable = REPOSITORY_ROOT / relative_path
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"required installed-path behavior is absent: {relative_path}")
    return executable


def _isolated_environment(root: Path) -> dict[str, str]:
    return {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "PATH": os.environ["PATH"],
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }


def test_launcher_rejects_implicit_root_and_cache(tmp_path: Path) -> None:
    launcher = _required_executable("scripts/file-base-mcp")
    result = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=_isolated_environment(tmp_path / "isolation"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert "CBM_ALLOWED_ROOT" in result.stderr
    assert "CBM_ALLOWED_ROOT_ID" in result.stderr
    assert "CBM_CACHE_DIR" in result.stderr
    assert str(REPOSITORY_ROOT) not in result.stderr
    assert str(Path.home()) not in result.stderr


def test_launcher_rejects_partial_files_profile_capability(tmp_path: Path) -> None:
    launcher = _required_executable("scripts/file-base-mcp")
    environment = _isolated_environment(tmp_path / "isolation")
    environment["ARW_FILES_CONTROL_ROOT"] = str(tmp_path / "control")
    result = subprocess.run(
        [str(launcher)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 64
    assert "control root and root ID" in result.stderr


def test_staged_launcher_starts_installed_one_root_files_profile(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "evidence.txt").write_text("installed files profile\n", encoding="utf-8")
    control = tmp_path / "control"
    identifiers = iter(
        [
            "rootinst_stage_001",
            "generation_stage_001",
            "attempt_stage_001",
            "file_stage_001",
            "receipt_stage_001",
        ]
    )
    service = FilesAdminService(
        control,
        id_factory=lambda _kind: next(identifiers),
        clock=lambda: "2026-07-14T00:00:00Z",
    )
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    service.sync("research-root", extractor_version="1.0.0")
    root_before = _snapshot(root)
    control_before = _snapshot(control)

    stage_root = tmp_path / "stage" / PLUGIN_NAME
    staged = subprocess.run(
        [
            str(_required_executable("scripts/stage-plugin")),
            "--clean",
            "--stage-root",
            str(stage_root),
            "--evidence-root",
            str(tmp_path / "stage-evidence"),
        ],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "PIP_NO_INDEX": "1", "UV_OFFLINE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert staged.returncode == 0, staged.stderr

    environment = _isolated_environment(tmp_path / "installed-isolation")
    environment.update(
        {
            "ARW_FILES_CONTROL_ROOT": str(control),
            "ARW_FILES_ROOT_ID": "research-root",
        }
    )
    launched = subprocess.run(
        [str(stage_root / "scripts/file-base-mcp")],
        cwd=tmp_path,
        env=environment,
        input=_request(1, "tools/list", {}) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert launched.returncode == 0, launched.stderr
    response = json.loads(launched.stdout)
    assert {item["name"] for item in response["result"]["tools"]} == {
        "list_files",
        "read_file",
        "search_files",
        "get_outline",
        "get_context",
    }
    assert _snapshot(root) == root_before
    assert _snapshot(control) == control_before


def test_exact_installed_mcp_launcher_performs_bounded_read(tmp_path: Path) -> None:
    smoke_script = _required_executable("scripts/smoke-staged-plugin")
    unrelated_cwd = tmp_path / "unrelated-working-directory"
    unrelated_cwd.mkdir()
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    evidence_root = tmp_path / "evidence"
    environment = _isolated_environment(tmp_path / "caller-isolation")

    smoke = subprocess.run(
        [
            str(smoke_script),
            "--mcp",
            "--fresh-home",
            str(tmp_path / "installed-home"),
            "--evidence-root",
            str(evidence_root),
            str(stage_root),
        ],
        cwd=unrelated_cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert smoke.returncode == 0, smoke.stderr

    manifest = json.loads(
        (stage_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["mcpServers"] == "./.mcp.json"
    mcp_config = json.loads((stage_root / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_config == {
        "mcpServers": {
            "file-base": {
                "command": "./scripts/file-base-mcp",
                "env": {
                    "CBM_DISABLE_UPDATE_CHECK": "1",
                    "CBM_LOG_LEVEL": "warn",
                },
            }
        }
    }
    assert os.access(stage_root / "scripts/file-base-mcp", os.X_OK)
    assert os.access(stage_root / "libexec/file-base-mcp", os.X_OK)

    result = json.loads(
        (evidence_root / "plugin/mcp/result.json").read_text(encoding="utf-8")
    )
    expected = (ALLOWED_ROOT / "paper.tex").read_text(encoding="utf-8")
    assert result == {
        "allowed_root": ROOT_CAPABILITY,
        "bytes_read": len(expected.encode("utf-8")),
        "content": expected,
        "lines_read": len(expected.splitlines()),
        "platform_claim": "linux",
        "relative_path": "paper.tex",
        "schema_version": "1.0.0",
        "status": "ok",
        "truncated": False,
    }

    config_probe = json.loads(
        (evidence_root / "plugin/mcp/config-probe.json").read_text(encoding="utf-8")
    )
    assert config_probe == {
        "configured_command": "./scripts/file-base-mcp",
        "host_listed": True,
        "resolved_inside_installed_plugin": True,
        "server_name": "file-base",
        "technical_qualification": "PASS",
    }
    summary = json.loads((evidence_root / "summary.json").read_text(encoding="utf-8"))
    assert summary == {
        "explicit_allowed_root": True,
        "explicit_cache": True,
        "inherited_pythonpath": False,
        "installed_from_exact_stage": True,
        "mcp_transport": "json-rpc-2.0-line-delimited-stdio",
        "network_isolation": "linux-user-network-namespace",
        "source_imported": False,
        "stage_name": PLUGIN_NAME,
        "technical_qualification": "PASS",
    }

    outside_canary = OUTSIDE_SECRET.read_bytes().strip()
    assert outside_canary
    evidence_bytes = b"\n".join(
        path.read_bytes() for path in evidence_root.rglob("*") if path.is_file()
    )
    assert outside_canary not in evidence_bytes
    evidence_text = evidence_bytes.decode("utf-8", errors="replace")
    assert str(REPOSITORY_ROOT) not in evidence_text
    assert str(Path.home()) not in evidence_text
