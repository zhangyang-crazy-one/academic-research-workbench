"""Real installed direction workflow, including an immutable plugin tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from arw.kernel.policy.integration_lock import _tree_sha256
from tests.candidate_inputs import (
    candidate_stage_args,
    configured_package_environment,
    isolated_stage_temporary_environment,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.requires_retained_evidence("candidate")
@pytest.mark.requires_materialized_sources
@pytest.mark.requires_native_file_base
def test_installed_start_intake_numeric_walkthrough_keeps_stage_immutable(tmp_path):
    stage = tmp_path / "stage"
    host = tmp_path / "runtime-home"
    env = {
        "PATH": os.environ["PATH"],
        "CODEX_HOME": str(host),
        "PYTHONNOUSERSITE": "1",
        "ARW_PYTHON": sys.executable,
        "ARW_BUILD_PYTHON": sys.executable,
        **configured_package_environment(),
        **isolated_stage_temporary_environment(tmp_path / "temporary"),
    }
    built = subprocess.run(
        [
            str(ROOT / "scripts/stage-plugin"),
            "--stage-root",
            str(stage),
            "--evidence-root",
            str(tmp_path / "stage-evidence"),
            *candidate_stage_args(),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert built.returncode == 0, built.stderr
    initial = _tree_sha256(stage)
    health = subprocess.run(
        [str(stage / "bin/arw"), "health", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert health.returncode == 0, health.stderr
    identity = json.loads(health.stdout)["runtime_identity"]
    runtime = host / "arw/runtime" / identity / "venv/bin/python"
    project = tmp_path / "research"
    completed = subprocess.run(
        [
            str(runtime),
            str(stage / "examples/research-directions/offline_walkthrough.py"),
            "--plugin-root",
            str(stage),
            "--project-root",
            str(project),
        ],
        env={**env, "ARW_PLUGIN_ROOT": str(stage), "ARW_RUNTIME_MODE": "plugin"},
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads((project / "observations/summary.json").read_bytes())
    initial_status = json.loads((project / "observations/01.stdout.json").read_bytes())
    assert initial_status["core"]["integrity"] == "PASS"
    assert summary["result_statuses"] == ["passed", "failed"]
    assert summary["workflow_stage"] == "initialized" and summary["model_calls"] == 0
    assert summary["scientific_status"] == "not_evaluated"
    assert _tree_sha256(stage) == initial
    assert not list((stage / "skills").rglob("__pycache__"))
