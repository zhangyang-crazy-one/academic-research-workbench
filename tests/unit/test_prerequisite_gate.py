"""Exercise the real pytest hook against a source-only temporary checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as prerequisite_gate

ROOT = Path(__file__).resolve().parents[2]


def test_missing_prerequisites_skip_locally_and_fail_in_qualification(
    tmp_path: Path,
) -> None:
    checkout_tests = tmp_path / "checkout/tests"
    checkout_tests.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/conftest.py", checkout_tests / "conftest.py")
    (checkout_tests / "test_probe.py").write_text(
        """import pytest

@pytest.mark.requires_native_file_base
def test_native():
    assert False

@pytest.mark.requires_materialized_sources
def test_sources():
    assert False

@pytest.mark.requires_retained_evidence('build/evidence/phase-99/receipt.json')
def test_evidence():
    assert False

@pytest.mark.codex_host
def test_host():
    assert False

@pytest.mark.requires_offline_network_isolation
def test_offline_network():
    assert False
""",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-c",
        str(ROOT / "pyproject.toml"),
        str(checkout_tests),
    ]
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = {
        **os.environ,
        "ARW_CODEX_LAUNCHER": str(tmp_path / "absent-codex"),
        "PATH": str(empty_path),
    }
    environment.pop("ARW_STRICT_PREREQS", None)

    local = subprocess.run(
        command, env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    assert "5 skipped" in local.stdout
    for expected in (
        "scripts/build-file-base",
        "scripts/materialize-sources",
        "scripts/verify-phase-*",
        "install Codex",
        "strace",
    ):
        assert expected in local.stdout

    strict = subprocess.run(
        command,
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    assert "5 errors" in strict.stdout
    for expected in (
        ".file-base/bin/file-base",
        "vendor/sources",
        "phase-99/receipt.json",
        "Codex host binary",
        "strace",
    ):
        assert expected in strict.stdout


def test_offline_network_prerequisite_rejects_other_platforms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prerequisite_gate.sys, "platform", "darwin")
    assert "Linux" in prerequisite_gate._offline_network_missing()[0]


@pytest.mark.parametrize(
    ("usable", "expected"),
    [
        ({"strace"}, "network namespace"),
        ({"strace", "unshare"}, None),
        ({"strace", "bwrap"}, None),
    ],
)
def test_offline_network_prerequisite_probes_actual_isolation(
    monkeypatch: pytest.MonkeyPatch, usable: set[str], expected: str | None
) -> None:
    monkeypatch.setattr(prerequisite_gate.sys, "platform", "linux")
    monkeypatch.setattr(
        prerequisite_gate.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0 if Path(command[0]).name in usable else 1)

    monkeypatch.setattr(prerequisite_gate.subprocess, "run", run)
    missing = prerequisite_gate._offline_network_missing()
    if expected is None:
        assert missing == []
    else:
        assert len(missing) == 1 and expected in missing[0]
    assert commands[0][0] == "/usr/bin/strace"
    assert any(
        "--unshare-net" in command or "--net" in command for command in commands[1:]
    )


def test_qualification_entrypoints_force_strict_prerequisites() -> None:
    for phase in range(1, 8):
        script = (ROOT / f"scripts/verify-phase-{phase}").read_text(encoding="utf-8")
        assert "ARW_STRICT_PREREQS" in script


def test_paper_method_prerequisite_rejects_other_platforms(monkeypatch):
    monkeypatch.setattr(prerequisite_gate.sys, "platform", "darwin")
    assert "Linux" in prerequisite_gate._paper_method_isolation_missing()[0]


@pytest.mark.parametrize("worker_version_supported", [False, True])
def test_paper_method_prerequisite_checks_system_python_and_namespace(
    monkeypatch,
    worker_version_supported,
):
    from arw_paper_method import sandbox

    monkeypatch.setattr(prerequisite_gate.sys, "platform", "linux")
    monkeypatch.setattr(prerequisite_gate.sys, "version_info", (3, 13))
    monkeypatch.setattr(prerequisite_gate.Path, "is_file", lambda _: True)
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0 if worker_version_supported else 1)

    monkeypatch.setattr(prerequisite_gate.subprocess, "run", run)

    def unavailable():
        raise sandbox.SandboxError("isolation_execution_failed")

    monkeypatch.setattr(sandbox, "probe_namespace", unavailable)
    missing = prerequisite_gate._paper_method_isolation_missing()
    assert commands[0][0] == "/usr/bin/python3"
    if worker_version_supported:
        assert "isolation_execution_failed" in missing[0]
    else:
        assert "python3 >=3.13" in missing[0]


def test_paper_method_prerequisite_skip_and_strict_error(tmp_path):
    checkout_tests = tmp_path / "checkout/tests"
    checkout_tests.mkdir(parents=True)
    hook = (ROOT / "tests/conftest.py").read_text()
    hook += "\ndef _paper_method_isolation_missing():\n    return ['simulated unavailable paper-method isolation']\n"
    (checkout_tests / "conftest.py").write_text(hook)
    (checkout_tests / "test_probe.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.requires_paper_method_isolation\n"
        "def test_worker():\n    assert False\n\n"
        "def test_pure_contract():\n    assert True\n"
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-c",
        str(ROOT / "pyproject.toml"),
        str(checkout_tests),
    ]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("ARW_STRICT_PREREQS", None)
    local = subprocess.run(
        command, env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    assert "1 passed, 1 skipped" in local.stdout
    strict = subprocess.run(
        command,
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    assert "1 passed, 1 error" in strict.stdout
    assert "simulated unavailable paper-method isolation" in strict.stdout


def test_issue27_stage_acceptance_does_not_skip_in_strict_mode() -> None:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/staged/test_file_base_opt_in_stage.py",
    ]
    environment = os.environ.copy()
    for name in (
        "ARW_ISSUE27_CODEX_STAGE",
        "ARW_ISSUE27_CLAUDE_STAGE",
        "ARW_STRICT_PREREQS",
    ):
        environment.pop(name, None)
    local = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    assert "2 skipped" in local.stdout
    strict = subprocess.run(
        command,
        cwd=ROOT,
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    assert "2 errors" in strict.stdout
    assert "ARW_ISSUE27_CODEX_STAGE" in strict.stdout
    assert "ARW_ISSUE27_CLAUDE_STAGE" in strict.stdout
