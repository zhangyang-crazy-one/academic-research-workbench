"""Agent / local-dev runtime mode is explicit and does not require Codex CLI."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY_ROOT / "bin" / "arw"
AGENT_LAUNCHER = REPOSITORY_ROOT / "bin" / "arw-agent"


def _path_without_codex(*extra_dirs: Path) -> str:
    parts: list[str] = [str(path) for path in extra_dirs]
    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        if (Path(item) / "codex").exists():
            continue
        parts.append(item)
    return os.pathsep.join(parts)


def _agent_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    environment = {
        "PATH": _path_without_codex(Path(sys.executable).parent),
        "HOME": str(tmp_path / "home"),
        "PYTHONNOUSERSITE": "1",
        "ARW_PYTHON": sys.executable,
        "ARW_RUNTIME": "agent",
    }
    environment.update(extra)
    environment.pop("CODEX_HOME", None)
    assert shutil.which("codex", path=environment["PATH"]) is None
    return environment


def _run(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd or REPOSITORY_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_agent_wrapper_is_checkout_only_and_forces_agent_mode() -> None:
    source = AGENT_LAUNCHER.read_text(encoding="utf-8")
    assert AGENT_LAUNCHER.stat().st_mode & stat.S_IXUSR
    assert "export ARW_RUNTIME=agent" in source
    assert 'exec "$SCRIPT_DIR/arw"' in source
    staged = (REPOSITORY_ROOT / "scripts" / "stage-plugin").read_text(encoding="utf-8")
    assert 'copy_file "bin/arw"' in staged
    assert "bin/arw-agent" in staged
    assert 'copy_file "bin/arw-agent"' not in staged
    assert '"bin/arw-agent"' not in staged.split("static_files = {", 1)[1].split("}", 1)[0]


def test_plugin_mode_stays_fail_closed_when_wheels_are_absent(tmp_path: Path) -> None:
    result = _run(
        [str(LAUNCHER), "health", "--json"],
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path / "home"),
            "PYTHONNOUSERSITE": "1",
            "ARW_PYTHON": sys.executable,
        },
    )
    assert result.returncode == 66, result.stderr
    assert "runtime-artifact-missing" in result.stderr
    assert "agent-runtime-missing" not in result.stderr


def test_explicit_plugin_runtime_does_not_use_checkout_venv(tmp_path: Path) -> None:
    result = _run(
        [str(LAUNCHER), "status", "--help"],
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path / "home"),
            "PYTHONNOUSERSITE": "1",
            "ARW_RUNTIME": "plugin",
            "ARW_PYTHON": sys.executable,
        },
    )
    assert result.returncode == 66, result.stderr
    assert "runtime-artifact-missing" in result.stderr


def test_unknown_runtime_mode_is_rejected(tmp_path: Path) -> None:
    result = _run(
        [str(LAUNCHER), "health", "--json"],
        env=_agent_env(tmp_path, ARW_RUNTIME="dev"),
    )
    assert result.returncode == 78
    assert "bootstrap-config" in result.stderr
    assert "ARW_RUNTIME" in result.stderr


def test_agent_mode_health_json_without_codex_or_wheels(tmp_path: Path) -> None:
    result = _run(
        [str(LAUNCHER), "health", "--json"],
        env=_agent_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "health"
    assert payload["status"] == "ok"
    assert payload["runtime_mode"] == "agent"
    assert payload["interpreter_source"] == "arw-python"
    assert payload["runtime_identity"]
    assert len(payload["runtime_identity"]) == 64
    major, minor = (int(value) for value in payload["python"].split(".")[:2])
    assert (major, minor) >= (3, 13)
    assert "codex" not in result.stdout.lower()
    assert not (tmp_path / "home" / ".codex" / "arw" / "runtime").exists()


def test_arw_agent_entrypoint_runs_health_without_codex(tmp_path: Path) -> None:
    env = _agent_env(tmp_path)
    env.pop("ARW_RUNTIME")
    result = _run([str(AGENT_LAUNCHER), "health", "--json"], env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["runtime_mode"] == "agent"
    assert payload["status"] == "ok"


def test_agent_mode_discovers_checkout_venv_when_arw_python_unset(
    tmp_path: Path,
) -> None:
    env = _agent_env(tmp_path)
    env.pop("ARW_PYTHON")
    result = _run([str(LAUNCHER), "health", "--json"], env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["interpreter_source"] == "checkout-venv"
    assert payload["runtime_mode"] == "agent"


def test_local_dev_alias_matches_agent_mode(tmp_path: Path) -> None:
    result = _run(
        [str(LAUNCHER), "health", "--json"],
        env=_agent_env(tmp_path, ARW_RUNTIME="local-dev"),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["runtime_mode"] == "agent"


def test_agent_mode_route_and_version_and_phase2_help_without_codex(
    tmp_path: Path,
) -> None:
    env = _agent_env(tmp_path)
    help_result = _run([str(AGENT_LAUNCHER), "help"], env=env)
    assert help_result.returncode == 0, help_result.stderr
    assert "Usage: arw <command> [options]" in help_result.stdout

    version = _run([str(LAUNCHER), "version", "--json"], env=env)
    assert version.returncode == 0, version.stderr
    version_payload = json.loads(version.stdout)
    assert version_payload["command"] == "version"
    assert version_payload["runtime_mode"] == "agent"
    assert version_payload["identity_source"] == "editable-checkout"
    assert version_payload["package_version"] == "0.1.0"
    assert version_payload["status"] == "ok"

    route = _run([str(LAUNCHER), "route", "--json"], env=env)
    assert route.returncode == 0, route.stderr
    route_payload = json.loads(route.stdout)
    assert route_payload["schema_version"] == "1.0.0"
    assert route_payload["integration_status"] == "BLOCKED"
    assert route_payload["release_qualification"] == "BLOCKED"
    assert route_payload["reason_codes"]

    status_help = _run([str(LAUNCHER), "status", "--help"], env=env)
    assert status_help.returncode == 0, status_help.stderr
    assert "usage: arw status" in status_help.stdout

    init_help = _run([str(LAUNCHER), "init", "--help"], env=env)
    assert init_help.returncode == 0, init_help.stderr
    assert "usage: arw init" in init_help.stdout

    for command in ("append", "replay", "files", "memory", "writing", "learn", "semantic"):
        command_help = _run([str(LAUNCHER), command, "--help"], env=env)
        assert command_help.returncode == 0, (command, command_help.stderr)
        assert f"usage: arw {command}" in command_help.stdout


def test_agent_mode_without_interpreter_or_wheel_fails_explicitly(tmp_path: Path) -> None:
    plugin_root = tmp_path / "empty-plugin"
    (plugin_root / "bin").mkdir(parents=True)
    shutil.copy(LAUNCHER, plugin_root / "bin" / "arw")
    copied = plugin_root / "bin" / "arw"
    copied.chmod(copied.stat().st_mode | stat.S_IXUSR)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "PYTHONNOUSERSITE": "1",
        "ARW_RUNTIME": "agent",
    }
    result = _run([str(copied), "health", "--json"], env=env, cwd=tmp_path)
    assert result.returncode == 66, result.stderr
    assert "agent-runtime-missing" in result.stderr
    assert "runtime-artifact-missing" not in result.stderr
