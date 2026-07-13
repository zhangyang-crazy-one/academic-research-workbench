from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
FORBIDDEN_FRAGMENTS = ("Paper4Master", "Examination", str(Path.home()), str(REPOSITORY_ROOT))


def _required_executable(relative_path: str) -> Path:
    executable = REPOSITORY_ROOT / relative_path
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"required installed-path behavior is absent: {relative_path}")
    return executable


def test_installed_cli_runs_offline_outside_source_checkout(tmp_path: Path) -> None:
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
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
    }

    staged = subprocess.run(
        [str(stage_script), "--clean", "--stage-root", str(stage_root)],
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
    }
    assert health["python"].split(".")[:2] in (["3", "13"], ["3", "14"])
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
    assert summary["inherited_pythonpath"] is False
