from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.candidate_inputs import candidate_stage_args, configured_package_environment

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
FORBIDDEN_FRAGMENTS = (
    "Paper4Master",
    "Examination",
    str(Path.home()),
    str(REPOSITORY_ROOT),
)


def _required_executable(relative_path: str) -> Path:
    executable = REPOSITORY_ROOT / relative_path
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"required installed-path behavior is absent: {relative_path}")
    return executable


def test_installed_health_rejects_incomplete_stage_and_foreign_root(
    tmp_path: Path,
) -> None:
    """A wheel-shaped file cannot substitute for a closed installed stage."""
    stage = tmp_path / "installed-plugin"
    (stage / "bin").mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "bin/arw", stage / "bin/arw")
    (stage / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    native = stage / "libexec/file-base-mcp"
    native.parent.mkdir()
    native.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    native.chmod(0o755)
    wheel = (
        stage / "share/arw/wheels/academic_research_workbench-0.1.0-py3-none-any.whl"
    )
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"local launcher test wheel")
    project = tmp_path / "project"
    project.mkdir()
    environment = {
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "PATH": os.environ["PATH"],
        "ARW_PYTHON": str(REPOSITORY_ROOT / ".venv/bin/python") if (REPOSITORY_ROOT / ".venv/bin/python").exists() else sys.executable,
    }

    def health(root: str | None = None) -> tuple[int, dict[str, object]]:
        env = {**environment, **({"ARW_PLUGIN_ROOT": root} if root is not None else {})}
        result = subprocess.run(
            [str(stage / "bin/arw"), "health", "--json"],
            cwd=project,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode, json.loads(result.stdout)

    status, automatic = health()
    assert status == 65
    assert automatic["reason_code"] == "runtime_artifact_invalid"

    explicit = tmp_path / "explicit-plugin-root"
    explicit.mkdir()
    (explicit / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    assert health(str(explicit)) == (65, {
        "schema_version": "arw.files-opt-in.v1",
        "status": "rejected",
        "reason_code": "plugin_root_mismatch",
        "action": "repair the installed ARW runtime and retry",
    })
    assert health("relative-plugin-root")[1]["reason_code"] == "plugin_root_mismatch"
    linked = tmp_path / "linked-plugin-root"
    linked.symlink_to(explicit, target_is_directory=True)
    assert health(str(linked))[1]["reason_code"] == "plugin_root_mismatch"


@pytest.mark.requires_retained_evidence("candidate")
@pytest.mark.requires_materialized_sources
@pytest.mark.requires_native_file_base
def test_installed_cli_bootstraps_unlocked_runtime_then_runs_offline(
    tmp_path: Path,
) -> None:
    stage_script = _required_executable("scripts/stage-plugin")
    smoke_script = _required_executable("scripts/smoke-staged-plugin")
    unrelated_cwd = tmp_path / "unrelated-working-directory"
    unrelated_cwd.mkdir()
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    evidence_root = tmp_path / "evidence"
    environment = {
        "HOME": str(tmp_path / "isolated-home"),
        "CODEX_HOME": str(tmp_path / "isolated-codex-home"),
        "PATH": os.environ["PATH"],
        "PYTHONNOUSERSITE": "1",
        **configured_package_environment(),
    }

    staged = subprocess.run(
        [str(stage_script), "--clean", "--stage-root", str(stage_root), *candidate_stage_args()],
        cwd=unrelated_cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert staged.returncode == 0, staged.stderr

    smoke = subprocess.run(
        [
            str(smoke_script),
            "--install-cli",
            "--fresh-home",
            str(tmp_path / "install-home"),
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

    launcher_stdout = (evidence_root / "plugin" / "launcher" / "stdout.log").read_text()
    health = json.loads(launcher_stdout)
    assert health == {
        "command": "health",
        "python": health["python"],
        "runtime_identity": health["runtime_identity"],
        "status": "ok",
        "file_base": health["file_base"],
        "platform": health["platform"],
    }
    assert health["file_base"]["state"] == "disabled"
    assert health["file_base"]["reason_code"] == "opt_in_required"
    assert health["platform"]["tier"] == "tier-1"
    major, minor = (int(value) for value in health["python"].split(".")[:2])
    assert (major, minor) >= (3, 13)
    assert len(health["runtime_identity"]) == 64

    runtime_commands = (
        "init",
        "append",
        "replay",
        "status",
        "transition",
        "decision-request",
        "decision-resolve",
        "attempt-start",
        "attempt-close",
        "artifact-accept",
        "checkpoint",
        "resume",
        "recover",
        "passport-pointer-rebuild",
    )
    for command in runtime_commands:
        help_result = subprocess.run(
            [str(stage_root / "bin/arw"), command, "--help"],
            cwd=unrelated_cwd,
            env={**environment, "CODEX_HOME": str(tmp_path / "isolated-codex-home")},
            text=True,
            capture_output=True,
            check=False,
        )
        assert help_result.returncode == 0, (command, help_result.stderr)
        assert f"usage: arw {command}" in help_result.stdout

    evidence_text = "\n".join(
        path.read_text(errors="replace")
        for path in evidence_root.rglob("*")
        if path.is_file()
    )
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in evidence_text

    summary = json.loads((evidence_root / "summary.json").read_text())
    assert summary["source_imported"] is False
    assert summary["network_isolation"] == "linux-user-network-namespace"
    assert summary["runtime_dependency_bootstrap"] == (
        "configured-package-index-before-isolated-canary"
    )
    assert summary["inherited_pythonpath"] is False


@pytest.mark.requires_retained_evidence("candidate")
@pytest.mark.requires_materialized_sources
@pytest.mark.requires_native_file_base
def test_installed_cli_defaults_codex_home_when_unset(tmp_path: Path) -> None:
    stage_script = _required_executable("scripts/stage-plugin")
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    isolated_home = tmp_path / "isolated-home"
    default_codex_home = isolated_home / ".codex"
    default_codex_home.mkdir(parents=True)
    environment = {
        "HOME": str(isolated_home),
        "PATH": os.environ["PATH"],
        "PYTHONNOUSERSITE": "1",
        **configured_package_environment(),
    }

    staged = subprocess.run(
        [str(stage_script), "--clean", "--stage-root", str(stage_root), *candidate_stage_args()],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert staged.returncode == 0, staged.stderr

    help_result = subprocess.run(
        [str(stage_root / "bin/arw"), "status", "--help"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "usage: arw status" in help_result.stdout
    assert (default_codex_home / "arw" / "runtime").is_dir()


def test_installed_cli_reports_actionable_error_without_home(tmp_path: Path) -> None:
    launcher = REPOSITORY_ROOT / "bin/arw"
    result = subprocess.run(
        [str(launcher), "status", "--help"],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "ARW_RUNTIME": "plugin"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 78
    assert "bootstrap-config" in result.stderr
    assert "HOME" in result.stderr


def test_installed_cli_reports_missing_runtime_artifact(tmp_path: Path) -> None:
    launcher = REPOSITORY_ROOT / "bin/arw"
    result = subprocess.run(
        [str(launcher), "status", "--help"],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "ARW_RUNTIME": "plugin",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 66
    assert "runtime-artifact-missing" in result.stderr
    assert "find:" not in result.stderr
