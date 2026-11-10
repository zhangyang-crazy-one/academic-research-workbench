"""Exercise the real pytest hook against a source-only temporary checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import conftest as prerequisite_gate

ROOT = Path(__file__).resolve().parents[2]


def _assert_pytest_outcomes(
    report: Path, *, passed: int = 0, skipped: int = 0, errors: int = 0
) -> None:
    """Check exact child outcomes without depending on warning summary text."""
    suites = ET.parse(report).getroot().findall("testsuite")
    assert len(suites) == 1
    assert {
        name: int(suites[0].attrib[name])
        for name in ("tests", "failures", "errors", "skipped")
    } == {
        "tests": passed + skipped + errors,
        "failures": 0,
        "errors": errors,
        "skipped": skipped,
    }


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

    local_report = tmp_path / "local-results.xml"
    strict_report = tmp_path / "strict-results.xml"
    local = subprocess.run(
        [*command, f"--junitxml={local_report}"],
        env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    _assert_pytest_outcomes(local_report, skipped=5)
    for expected in (
        "scripts/build-file-base",
        "scripts/materialize-sources",
        "scripts/verify-phase-*",
        "install Codex",
        "strace",
    ):
        assert expected in local.stdout

    strict = subprocess.run(
        [*command, f"--junitxml={strict_report}"],
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    _assert_pytest_outcomes(strict_report, errors=5)
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


@pytest.mark.parametrize("emit_warning", [False, True])
def test_paper_method_prerequisite_skip_and_strict_error(tmp_path, emit_warning):
    checkout_tests = tmp_path / "checkout/tests"
    checkout_tests.mkdir(parents=True)
    hook = (ROOT / "tests/conftest.py").read_text()
    hook += "\ndef _paper_method_isolation_missing():\n    return ['simulated unavailable paper-method isolation']\n"
    (checkout_tests / "conftest.py").write_text(hook)
    warning = "prerequisite outcome warning regression"
    warning_code = (
        f"    import warnings\n    warnings.warn({warning!r}, RuntimeWarning)\n"
        if emit_warning
        else ""
    )
    (checkout_tests / "test_probe.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.requires_paper_method_isolation\n"
        "def test_worker():\n    assert False\n\n"
        "def test_pure_contract():\n" + warning_code + "    assert True\n"
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
    local_report = tmp_path / "local-results.xml"
    strict_report = tmp_path / "strict-results.xml"
    local = subprocess.run(
        [*command, f"--junitxml={local_report}"],
        env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    _assert_pytest_outcomes(local_report, passed=1, skipped=1)
    strict = subprocess.run(
        [*command, f"--junitxml={strict_report}"],
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    _assert_pytest_outcomes(strict_report, passed=1, errors=1)
    assert "simulated unavailable paper-method isolation" in strict.stdout
    if emit_warning:
        assert warning in local.stdout
        assert warning in strict.stdout


def test_issue27_stage_acceptance_does_not_skip_in_strict_mode(tmp_path: Path) -> None:
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
    local_report = tmp_path / "local-results.xml"
    strict_report = tmp_path / "strict-results.xml"
    local = subprocess.run(
        [*command, f"--junitxml={local_report}"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=False
    )
    assert local.returncode == 0, local.stdout + local.stderr
    _assert_pytest_outcomes(local_report, skipped=2)
    strict = subprocess.run(
        [*command, f"--junitxml={strict_report}"],
        cwd=ROOT,
        env={**environment, "ARW_STRICT_PREREQS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert strict.returncode != 0
    _assert_pytest_outcomes(strict_report, errors=2)
    assert "ARW_ISSUE27_CODEX_STAGE" in strict.stdout
    assert "ARW_ISSUE27_CLAUDE_STAGE" in strict.stdout
