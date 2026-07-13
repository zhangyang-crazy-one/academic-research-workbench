from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
ROUTE_KEYS = {
    "schema_version",
    "workflow_family",
    "execution_mode",
    "source_adapter_version",
    "experiment_execution",
}


def _required_executable(relative_path: str) -> Path:
    executable = REPOSITORY_ROOT / relative_path
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"required installed-path behavior is absent: {relative_path}")
    return executable


def _operator_auth_file() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return Path(os.environ.get("ARW_CODEX_AUTH_FILE", codex_home / "auth.json"))


def _run(
    command: list[str], cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="session")
def installed_route_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    root = tmp_path_factory.mktemp("installed-route")
    unrelated_cwd = root / "unrelated-working-directory"
    unrelated_cwd.mkdir()
    stage_root = root / "stage" / PLUGIN_NAME
    evidence_root = root / "evidence"
    isolated_environment = root / "caller-environment"
    environment = {
        "HOME": str(isolated_environment / "home"),
        "CODEX_HOME": str(isolated_environment / "codex-home"),
        "PATH": os.environ["PATH"],
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
        "ARW_CODEX_AUTH_FILE": str(_operator_auth_file()),
    }

    staged = _run(
        [
            str(_required_executable("scripts/stage-plugin")),
            "--clean",
            "--stage-root",
            str(stage_root),
        ],
        unrelated_cwd,
        environment,
    )
    assert staged.returncode == 0, staged.stderr

    canary = _run(
        [
            str(_required_executable("scripts/smoke-staged-plugin")),
            "--route",
            "--fresh-home",
            str(root / "fresh-host"),
            "--evidence-root",
            str(evidence_root),
            str(stage_root),
        ],
        unrelated_cwd,
        environment,
    )
    return evidence_root, canary


@pytest.mark.codex_host
def test_fresh_installed_skill_returns_schema_valid_route(
    installed_route_evidence: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    evidence, canary = installed_route_evidence
    assert canary.returncode == 0, (
        "installed route canary did not converge\n"
        f"stdout:\n{canary.stdout}\n"
        f"stderr:\n{canary.stderr}"
    )
    direct = json.loads((evidence / "plugin/route/direct/result.json").read_text())
    final = json.loads((evidence / "plugin/route/final.json").read_text())
    route = final["route_result"]
    schema = json.loads((evidence / "plugin/route/route-result.schema.json").read_text())

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(direct)
    jsonschema.Draft202012Validator(schema).validate(route)
    assert set(route) == ROUTE_KEYS
    assert route["workflow_family"]
    assert route["execution_mode"]
    assert route["source_adapter_version"] == "0.1.19"
    assert route["experiment_execution"] == "disabled"
    assert direct == route

    attempts = sorted((evidence / "plugin/route/attempts").glob("*/classification.json"))
    assert attempts
    attempt_records = [json.loads(path.read_text()) for path in attempts]
    assert attempt_records[-1]["classification"] == "pass"
    assert all(record["classification"] != "blocking-unknown" for record in attempt_records)

    final_attempt = evidence / "plugin/route/attempts" / final["attempt"]
    assert (final_attempt / "command.json").is_file()
    assert (final_attempt / "stdout.jsonl").is_file()
    assert (final_attempt / "stderr.log").is_file()
    assert json.loads((final_attempt / "exit.json").read_text())["status"] == 0

    command = json.loads((final_attempt / "command.json").read_text())
    assert command["cwd"] == "<isolated-working-directory>"
    assert command["environment"] == {
        "CODEX_HOME": "<isolated-codex-home>",
        "HOME": "<isolated-home>",
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "unset",
        "tool_network_access": "disabled",
    }

    identity = json.loads((evidence / "plugin/installed-identity.json").read_text())
    assert identity["stage_sha256"] == identity["installed_sha256"]
    assert len(identity["stage_sha256"]) == 64
    assert identity["installed_manifest_version"].startswith("0.1.0+codex.")
