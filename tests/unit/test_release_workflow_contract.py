"""CI transfer and release verifier prerequisites must agree on clean runners."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict:
    return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"),
                     Loader=yaml.BaseLoader)


def test_release_permissions_limit_write_access_to_publish() -> None:
    release = _workflow("release.yml")
    assert release["permissions"] == {"actions": "read", "contents": "read"}
    qualify = release["jobs"]["qualify"]
    publish = release["jobs"]["publish"]
    assert qualify.get("permissions", release["permissions"]).get("contents") == "read"
    assert publish["permissions"] == {"contents": "write"}


def test_ci_candidate_archive_name_matches_both_downloaders() -> None:
    ci = _workflow("ci.yml")
    release = _workflow("release.yml")
    package_steps = ci["jobs"]["package-boundary"]["steps"]
    build = next(step["run"] for step in package_steps
                 if step.get("name") == "Build one candidate and generate its isolated legal evidence")
    assert "--output build/candidate-bundle.tar.gz" in build
    assert "test -s build/candidate-bundle.tar.gz" in build
    uploaded = next(step["with"]["path"] for step in package_steps
                    if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert uploaded == "build/candidate-bundle.tar.gz"
    python_steps = ci["jobs"]["python"]["steps"]
    assert any("--archive build/candidate-from-ci-transfer/candidate-bundle.tar.gz"
               in step.get("run", "") for step in python_steps)
    qualify_steps = release["jobs"]["qualify"]["steps"]
    assert any("--archive candidate-transfer/candidate-bundle.tar.gz"
               in step.get("run", "") for step in qualify_steps)
    publish_steps = release["jobs"]["publish"]["steps"]
    assert any("--archive verified-candidate-transfer/candidate-bundle.tar.gz"
               in step.get("run", "") for step in publish_steps)


def test_release_candidate_bundle_commands_use_installed_validator_environment() -> None:
    release = _workflow("release.yml")
    for job_name in ("qualify", "publish"):
        steps = release["jobs"][job_name]["steps"]
        install_index = next(index for index, step in enumerate(steps)
                             if step.get("name") == "Install declared runtime validator dependencies")
        commands = [(index, line.strip()) for index, step in enumerate(steps)
                    for line in step.get("run", "").splitlines()
                    if "scripts/candidate-bundle " in line]
        assert commands, job_name
        assert all(index > install_index and line.startswith(".venv/bin/python scripts/candidate-bundle ")
                   for index, line in commands), job_name


def test_publish_clean_install_command_supplies_verifier_dependency(tmp_path: Path) -> None:
    release = _workflow("release.yml")
    steps = release["jobs"]["publish"]["steps"]
    install = next(step["run"] for step in steps
                   if step.get("name") == "Install declared runtime validator dependencies")
    assert install == "uv venv && .venv/bin/python scripts/install-unmanaged-deps.py dev"
    assert any(".venv/bin/python scripts/check-release-candidate" in step.get("run", "")
               for step in steps)
    with (ROOT / "pyproject.toml").open("rb") as source:
        dev = tomllib.load(source)["dependency-groups"]["dev"]
    assert any(requirement.startswith("packaging>=") for requirement in dev)

    fake_uv = tmp_path / "uv"
    fake_uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARW_TEST_UV_ARGS"\n',
                       encoding="utf-8")
    fake_uv.chmod(0o755)
    args_file = tmp_path / "uv-args.txt"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["ARW_TEST_UV_ARGS"] = str(args_file)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/install-unmanaged-deps.py"), "--dry-run", "dev"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert args[:3] == ["pip", "install", "--python"]
    assert "--dry-run" in args
    assert any(requirement.startswith("packaging>=") for requirement in args)
