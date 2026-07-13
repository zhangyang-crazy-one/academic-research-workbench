from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/confinement"
ALLOWED_ROOT = FIXTURE_ROOT / "allowed"
OUTSIDE_SECRET = FIXTURE_ROOT / "outside/secret.txt"
ROOT_CAPABILITY = "phase1-fixture"


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
