"""Mocked selection contracts, not evidence of real namespace qualification."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

ROOT = Path(__file__).resolve().parents[2]
PARENT_NAMESPACE = "net:[100]"


@pytest.fixture
def smoke() -> dict[str, Any]:
    source = (ROOT / "scripts/smoke-staged-plugin").read_text()
    embedded = source.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    definitions = {
        "CanaryDefect",
        "EnvironmentPrerequisiteError",
        "write_json",
        "write_command",
        "bwrap_prefix",
        "offline_installed_command",
        "main",
        "run_route",
    }
    module = ast.parse(embedded)
    module.body = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name in definitions
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "argparse": argparse,
        "NoReturn": NoReturn,
        "Path": Path,
        "PROJECT_ROOT": ROOT,
        "json": json,
        "re": re,
        "subprocess": subprocess,
        "shutil": shutil,
        "sys": sys,
        "datetime": datetime,
        "timezone": timezone,
        "os": SimpleNamespace(
            readlink=lambda path: PARENT_NAMESPACE,
            environ={"PATH": "/usr/bin:/bin"},
            getpid=lambda: 1,
        ),
    }
    # Load only reviewed definitions from the checked-in script, never main.
    exec(compile(module, "smoke-namespace-contract", "exec"), namespace)  # noqa: S102
    return namespace


def _mock_probes(smoke: dict[str, Any], replies: list[tuple[int, str, str]]):
    calls: list[list[str]] = []

    def probe(argv, **kwargs):
        # Only the identity preflight may run; launching an installed payload
        # through this mocked tool would not prove network isolation.
        assert argv[-3:] == ["--", "/usr/bin/readlink", "/proc/self/ns/net"]
        assert "--clearenv" in argv
        assert argv[argv.index("--cap-drop") + 1] == "ALL"
        calls.append(argv)
        status, stdout, stderr = replies[len(calls) - 1]
        return subprocess.CompletedProcess(argv, status, stdout, stderr)

    smoke["subprocess"] = SimpleNamespace(
        run=probe, TimeoutExpired=subprocess.TimeoutExpired
    )
    return calls


def _assert_source_hiding(prefix: list[str], fresh_root: Path) -> None:
    def arguments(option: str, count: int):
        return [
            prefix[index + 1 : index + 1 + count]
            for index, value in enumerate(prefix)
            if value == option
        ]

    assert arguments("--ro-bind", 2) == [["/", "/"]]
    assert [str(ROOT)] in arguments("--tmpfs", 1)
    assert ["/tmp"] in arguments("--tmpfs", 1)
    assert arguments("--bind", 2) == [[str(fresh_root), str(fresh_root)]]


@pytest.mark.parametrize(
    "reply",
    [
        (0, "net:[100]\n", ""),  # Success without isolation is not authority.
        (0, "net:[200]\nnet:[300]\n", ""),
        (0, "net:[200]", ""),
        (0, "not-a-namespace\n", ""),
        (1, "net:[200]\n", ""),
        (0, "net:[200]\n", "warning"),
    ],
)
def test_invalid_namespace_probes_fail_before_installed_launch(
    smoke: dict[str, Any], tmp_path: Path, reply: tuple[int, str, str]
) -> None:
    calls = _mock_probes(smoke, [reply])

    def forbidden_launch(*args, **kwargs):
        pytest.fail("invalid namespace evidence must not launch installed code")

    smoke["run_recorded"] = forbidden_launch
    installed = {
        "installed_root": tmp_path / "installed",
        "fresh_root": tmp_path,
        "unrelated_cwd": tmp_path,
    }
    evidence = tmp_path / "evidence"
    with pytest.raises(
        smoke["CanaryDefect"], match="namespace isolation is unavailable"
    ):
        smoke["offline_installed_command"](installed, ["health", "--json"], evidence)

    assert len(calls) == 1
    assert all("unshare" not in call for call in calls)
    assert all("--map-current-user" not in call for call in calls)
    assert all("--map-root-user" not in call for call in calls)
    receipt = json.loads((evidence / "network-isolation.json").read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["selected_backend"] is None
    assert all(not attempt["isolated"] for attempt in receipt["preflight"])
    expected = (
        "environment-prerequisite-unavailable"
        if reply[0] != 0
        else "isolation-evidence-invalid"
    )
    assert receipt["classification"] == expected


def test_denied_backend_never_attempts_an_alternate_namespace(
    smoke: dict[str, Any], tmp_path: Path
) -> None:
    calls = _mock_probes(smoke, [(1, "", "Operation not permitted")])

    def forbidden_launch(*args, **kwargs):
        pytest.fail("a denied namespace must not launch installed code")

    smoke["run_recorded"] = forbidden_launch
    installed = {
        "installed_root": tmp_path / "installed",
        "fresh_root": tmp_path,
        "unrelated_cwd": tmp_path,
    }
    evidence = tmp_path / "evidence"
    with pytest.raises(
        smoke["CanaryDefect"], match="namespace isolation is unavailable"
    ):
        smoke["offline_installed_command"](installed, ["health", "--json"], evidence)

    assert len(calls) == 1
    assert calls[0][0:2] == ["bwrap", "--unshare-net"]
    assert "unshare" not in calls[0]
    assert "--map-current-user" not in calls[0]
    assert "--map-root-user" not in calls[0]
    _assert_source_hiding(calls[0], tmp_path)
    receipt = json.loads((evidence / "network-isolation.json").read_text())
    assert receipt["selected_backend"] is None
    assert receipt["status"] == "FAIL"
    assert receipt["classification"] == "environment-prerequisite-unavailable"
    assert (
        receipt["required_capability"] == "original-bwrap-network-namespace-isolation"
    )
    assert "network-isolation.json" in receipt["actionable_safe_hint"]
    assert receipt["preflight"][0]["stderr"] == "Operation not permitted"


@pytest.mark.parametrize(
    ("reply", "expected_status"),
    [
        ((0, "net:[200]\n", ""), 0),
        ((1, "", "Operation not permitted"), 78),
        ((0, "net:[100]\n", ""), 70),
    ],
)
def test_mocked_main_distinguishes_environment_from_isolation_defect(
    smoke: dict[str, Any], tmp_path: Path, capsys, reply, expected_status: int
) -> None:
    calls = _mock_probes(smoke, [reply])
    smoke["parse_args"] = lambda: SimpleNamespace(version=False, mcp=False, route=False)

    def mock_installed_check(args):
        # Main dispatch only: no plugin or installed payload is executed.
        smoke["bwrap_prefix"](
            tmp_path,
            tmp_path,
            offline=True,
            isolation_evidence=tmp_path / "network-isolation.json",
        )
        return 0

    smoke["run_install_cli"] = mock_installed_check
    assert smoke["main"]() == expected_status
    assert len(calls) == 1
    output = capsys.readouterr()
    if expected_status == 78:
        assert "environment prerequisite unavailable" in output.err
        assert "Original bwrap --unshare-net isolation is required" in output.err
        assert "network-isolation.json" in output.err
        assert "rerun in an environment" in output.err
    elif expected_status == 70:
        assert "environment prerequisite unavailable" not in output.err
    else:
        assert output.err == ""


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("bwrap", 5)],
)
def test_unavailable_original_tool_has_typed_prerequisite_failure(
    smoke: dict[str, Any], tmp_path: Path, error: Exception
) -> None:
    def failed_probe(*args, **kwargs):
        raise error

    smoke["subprocess"] = SimpleNamespace(
        run=failed_probe, TimeoutExpired=subprocess.TimeoutExpired
    )
    evidence = tmp_path / "network-isolation.json"
    with pytest.raises(smoke["EnvironmentPrerequisiteError"]):
        smoke["bwrap_prefix"](
            tmp_path, tmp_path, offline=True, isolation_evidence=evidence
        )
    receipt = json.loads(evidence.read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["classification"] == "environment-prerequisite-unavailable"
    assert receipt["preflight"][0]["failure"] == type(error).__name__


def test_unavailable_parent_identity_has_typed_prerequisite_failure(
    smoke: dict[str, Any], tmp_path: Path
) -> None:
    def missing_identity(path):
        raise FileNotFoundError()

    def forbidden_probe(*args, **kwargs):
        pytest.fail("missing parent identity must not launch a probe")

    smoke["os"].readlink = missing_identity
    smoke["subprocess"] = SimpleNamespace(run=forbidden_probe)
    evidence = tmp_path / "network-isolation.json"
    with pytest.raises(smoke["EnvironmentPrerequisiteError"]):
        smoke["bwrap_prefix"](
            tmp_path, tmp_path, offline=True, isolation_evidence=evidence
        )
    receipt = json.loads(evidence.read_text())
    assert receipt["status"] == "FAIL"
    assert receipt["classification"] == "environment-prerequisite-unavailable"
    assert receipt["preflight"][0]["phase"] == "parent-namespace"


def test_original_namespace_backend_is_preferred_when_isolated(
    smoke: dict[str, Any], tmp_path: Path
) -> None:
    calls = _mock_probes(smoke, [(0, "net:[200]\n", "")])
    prefix = smoke["bwrap_prefix"](tmp_path, tmp_path, offline=True)
    assert len(calls) == 1
    assert prefix[:2] == ["bwrap", "--unshare-net"]
    assert prefix[prefix.index("--cap-drop") + 1] == "ALL"
    _assert_source_hiding(prefix, tmp_path)


def test_authenticated_prefix_does_not_probe_or_change_namespaces(
    smoke: dict[str, Any], tmp_path: Path
) -> None:
    def forbidden_probe(*args, **kwargs):
        pytest.fail("authenticated route must not use offline preflight")

    smoke["os"].readlink = forbidden_probe
    smoke["subprocess"] = SimpleNamespace(run=forbidden_probe)
    prefix = smoke["bwrap_prefix"](tmp_path, tmp_path, offline=False)
    assert prefix[0] == "bwrap"
    assert "unshare" not in prefix
    assert "--unshare-net" not in prefix
    assert "--cap-drop" not in prefix
    _assert_source_hiding(prefix, tmp_path)


@pytest.mark.parametrize("error_type", ["EnvironmentPrerequisiteError", "CanaryDefect"])
@pytest.mark.parametrize("failed_command", ["health", "route"])
def test_mocked_route_cleans_dummy_auth_on_offline_error_without_host_launch(
    smoke: dict[str, Any], tmp_path: Path, error_type: str, failed_command: str
) -> None:
    args = SimpleNamespace(
        stage_root=tmp_path / "stage",
        fresh_home=tmp_path / "fresh",
        evidence_root=tmp_path / "evidence",
        max_attempts=1,
    )
    smoke["materialize_stage_if_missing"] = lambda *args, **kwargs: False
    smoke["next_attempt_number"] = lambda root: 1
    dummy_auth: list[Path] = []

    def mock_install(stage, fresh, evidence, **kwargs):
        # Only a unit marker is created. No credentials, plugin add or auth
        # copying occurs; the real successful route still retains auth later.
        codex_home = fresh / "codex-home"
        codex_home.mkdir(parents=True)
        marker = codex_home / "auth.json"
        marker.write_text("unit-only cleanup marker")
        dummy_auth.append(marker)
        return {"codex_home": codex_home}

    smoke["install_exact_stage"] = mock_install
    calls: list[str] = []
    failure = smoke[error_type]("unit offline preflight failure")

    def mock_offline(installed, arguments, evidence):
        calls.append(arguments[0])
        if arguments[0] == failed_command:
            raise failure
        return subprocess.CompletedProcess(arguments, 0, "{}", "")

    smoke["offline_installed_command"] = mock_offline

    def forbidden_host(*args, **kwargs):
        pytest.fail("offline error must not launch the host/model canary")

    smoke["run_host_route"] = forbidden_host
    with pytest.raises(smoke[error_type]) as caught:
        smoke["run_route"](args)
    assert caught.value is failure
    assert len(dummy_auth) == 1
    assert not dummy_auth[0].exists()
    assert calls == (["health"] if failed_command == "health" else ["health", "route"])
    assert not list(args.evidence_root.rglob("classification.json"))
