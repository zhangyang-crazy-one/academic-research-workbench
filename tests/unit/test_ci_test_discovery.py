"""Protect the full-tree CI invocation from path allowlists."""

from __future__ import annotations

import shlex
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_ci_runs_configured_test_tree_with_only_codex_host_excluded() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    testpaths = config["tool"]["pytest"]["ini_options"]["testpaths"]
    assert testpaths == ["tests"]
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["python"]["steps"]
    validator_invocations = sum(
        step.get("run", "").count("scripts/validate-skills")
        for job in workflow["jobs"].values()
        for step in job["steps"]
    )
    assert validator_invocations == 1
    validator_steps = [
        step for step in steps if "scripts/validate-skills" in step.get("run", "")
    ]
    assert len(validator_steps) == 1
    validator = validator_steps[0]
    assert validator["name"] == "Validate source skills and stage allowlist"
    assert shlex.split(validator["run"]) == [
        ".venv/bin/python",
        "scripts/validate-skills",
    ]
    assert steps.index(validator) > next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Resolve development environment from declared ranges"
    )
    complete = [
        step for step in steps if step.get("name") == "Run complete non-host test tree"
    ]
    assert len(complete) == 1
    command = shlex.split(complete[0]["run"])
    assert command[:4] == [".venv/bin/python", "-m", "pytest", "-q"]
    assert command[command.index("-m") + 1] == "pytest"
    assert command[command.index("-m", 3) + 1] == "not codex_host and not v2_compat"
    assert command[-1].rstrip("/") == testpaths[0]
    assert not any(
        token.startswith(("tests/unit/", "tests/integration/", "tests/staged/"))
        for token in command
    )
    assert not any(token.startswith("--ignore") for token in command)
    assert any(
        step.get("name") == "Materialize pinned source snapshots" for step in steps
    )
    assert any(
        step.get("name") == "Verify source manifest wire digests" for step in steps
    )
    v2_steps = [
        step for step in steps if step.get("name") == "Run v2 compatibility baseline"
    ]
    assert len(v2_steps) == 1
    assert "-m v2_compat tests/compat" in v2_steps[0]["run"]
    compat_modules = set((ROOT / "tests/compat").glob("test_*.py"))
    assert compat_modules
    marker = "pytest.mark." + "v2_compat"
    for module in (ROOT / "tests").rglob("test_*.py"):
        assert (marker in module.read_text(encoding="utf-8")) == (
            module in compat_modules
        ), module
