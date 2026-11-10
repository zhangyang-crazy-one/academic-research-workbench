"""Keep optional ML wheel availability separate from latest-Python core CI."""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
CORE_TESTS = {
    "tests/unit/test_canonical.py",
    "tests/unit/test_manifests.py",
    "tests/unit/test_recovery_scan.py",
    "tests/unit/test_platform_support.py",
    "tests/unit/test_ci_python_compatibility.py",
}


def _jobs() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]


def _python_version(job: dict) -> str:
    return next(
        step["with"]["python-version"]
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )


def test_complete_optional_environment_uses_compatible_ci_minor() -> None:
    job = _jobs()["python"]
    assert _python_version(job) == "3.14", (
        "Full optional CI must not float to a Python ABI without ML wheels"
    )
    install = next(
        step["run"]
        for step in job["steps"]
        if step.get("name") == "Resolve development environment from declared ranges"
    )
    assert shlex.split(install) == [
        "uv",
        "venv",
        "&&",
        "./scripts/install-python",
        "--all-extras",
        "--group",
        "dev",
        "--group",
        "ars-test",
        "--group",
        "storm",
    ]


def test_latest_python_core_is_independent_of_optional_ecosystem() -> None:
    jobs = _jobs()
    assert "python-core-latest" in jobs, "Latest Python needs independent core coverage"
    job = jobs["python-core-latest"]
    assert _python_version(job) == "3.x"
    assert job["runs-on"] == "ubuntu-latest"
    assert not job.get("needs")
    assert not job.get("continue-on-error", False)
    assert job["if"] == jobs["python"]["if"]
    steps = job["steps"]
    assert not any("download-artifact" in step.get("uses", "") for step in steps)
    install = next(
        step["run"] for step in steps if "scripts/install-python" in step.get("run", "")
    )
    assert shlex.split(install) == [
        "uv",
        "venv",
        "&&",
        "./scripts/install-python",
        "--group",
        "dev",
    ]
    test_step = next(step for step in steps if "-m pytest" in step.get("run", ""))
    assert steps.index(test_step) > next(
        index for index, step in enumerate(steps) if step.get("run") == install
    )
    assert not test_step.get("if")
    assert not test_step.get("continue-on-error", False)
    command = shlex.split(test_step["run"])
    assert command[:4] == [".venv/bin/python", "-m", "pytest", "-q"]
    assert set(command[4:]) == CORE_TESTS
    assert all((ROOT / path).is_file() for path in CORE_TESTS)


def test_ci_environment_choice_does_not_restrict_runtime_ranges() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["requires-python"] == ">=3.13"
    requirements = list(metadata["project"]["dependencies"])
    for group in metadata["project"]["optional-dependencies"].values():
        requirements.extend(group)
    for group in metadata["dependency-groups"].values():
        requirements.extend(group)
    for requirement in requirements:
        assert all(
            spec.operator not in {"<", "<=", "==", "===", "~="}
            for spec in Requirement(requirement).specifier
        )
    assert not (ROOT / "uv.lock").exists()
    assert not (ROOT / ".python-version").exists()
