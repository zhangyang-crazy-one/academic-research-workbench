from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"


def _isolated_environment(root: Path) -> dict[str, str]:
    environment = {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "PATH": os.environ["PATH"],
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
    }
    return environment


def _required_executable(relative_path: str) -> Path:
    executable = REPOSITORY_ROOT / relative_path
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"required installed-path behavior is absent: {relative_path}")
    return executable


def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_clean_allowlisted_stage_validates_and_installs(tmp_path: Path) -> None:
    stage_script = _required_executable("scripts/stage-plugin")
    smoke_script = _required_executable("scripts/smoke-staged-plugin")
    unrelated_cwd = tmp_path / "outside-checkout"
    unrelated_cwd.mkdir()
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    evidence_root = tmp_path / "evidence"
    environment = _isolated_environment(tmp_path / "isolation")

    staged = _run(
        [str(stage_script), "--clean", "--stage-root", str(stage_root)],
        unrelated_cwd,
        environment,
    )
    assert staged.returncode == 0, staged.stderr

    installed = _run(
        [
            str(smoke_script),
            "--install-cli",
            "--fresh-home",
            str(tmp_path / "install-home"),
            "--evidence-root",
            str(evidence_root),
            str(stage_root),
        ],
        unrelated_cwd,
        environment,
    )
    assert installed.returncode == 0, installed.stderr

    manifest = json.loads((stage_root / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["name"] == PLUGIN_NAME
    assert manifest["license"].startswith("LicenseRef-")

    inventory = json.loads((evidence_root / "stage" / "inventory.json").read_text())
    assert inventory["files"] == sorted(inventory["files"])
    assert inventory["symlinks"] == []

    summary = json.loads((evidence_root / "summary.json").read_text())
    assert summary["technical_qualification"] == "PASS"
    assert summary["stage_name"] == PLUGIN_NAME
    assert summary["installed_from_exact_stage"] is True

