"""Phase 7 installed-package and external ARS qualification probes.

The test deliberately executes the copied stage from a directory outside the
checkout.  The local ARS adapter remains an explicit external input and only
bounded route evidence is retained; no workflow transcript or source text is
copied into the installed package or the qualification receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arw.canonical import canonical_json_bytes
from arw.integration_lock import (
    EXPECTED_ARS_ADAPTER_VERSION,
    _tree_sha256,
    observe_hook_definition,
    observe_stage_identity,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARS_ROOT = Path(
    os.environ.get(
        "ARW_ARS_ROOT", "/home/zhangyangrui/.codex/skills/academic-research-suite"
    )
).resolve()
PLUGIN_NAME = "academic-research-workbench"
LOCK_PATH = REPOSITORY_ROOT / "build/evidence/phase-07/integration-lock.json"
CANARY_PATH = REPOSITORY_ROOT / "build/evidence/phase-07/host-canary/canary.json"
CODEX_LAUNCHER = Path("/usr/local/sbin/codex")
CODEX_NATIVE = Path(
    "/usr/local/lib/node_modules/@openai/codex/node_modules/"
    "@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _publish_once(path: Path, payload: object) -> None:
    encoded = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == encoded:
            return
        # Evidence is append-only.  A later plan may legitimately produce a
        # new stage/lock identity; retain the old receipt and publish the new
        # canonical bytes under a content-addressed sibling instead of
        # overwriting or failing the next qualification run.
        suffix = hashlib.sha256(encoded).hexdigest()[:16]
        path = path.with_name(f"{path.stem}-{suffix}{path.suffix}")
        if path.exists():
            assert path.read_bytes() == encoded, f"retained receipt drifted: {path}"
            return
    path.write_bytes(encoded)


@pytest.fixture
def installed_stage(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Build one exact stage and copy it into a source-hidden marketplace."""

    assert ARS_ROOT.is_dir() and not ARS_ROOT.is_symlink(), (
        "ARW_ARS_ROOT must point at the explicit local ARS adapter"
    )
    outside = tmp_path / "outside-working-directory"
    outside.mkdir()
    stage = tmp_path / "stage" / PLUGIN_NAME
    stage_tmp = tmp_path / "stage-tmp"
    evidence = tmp_path / "stage-evidence"
    environment = {
        "HOME": str(tmp_path / "caller-home"),
        "CODEX_HOME": str(tmp_path / "caller-codex-home"),
        "PATH": os.environ.get("PATH", os.defpath),
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
        "TMPDIR": str(REPOSITORY_ROOT / "build/tmp/phase-07/ars-smoke"),
        "ARW_STAGE_TMP_ROOT": str(stage_tmp),
    }
    stage_command = [
        str(REPOSITORY_ROOT / "scripts/stage-plugin"),
        "--clean",
        "--stage-root",
        str(stage),
        "--evidence-root",
        str(evidence),
    ]
    # When the exact host receipt is retained, build the positive lock-bound
    # stage.  A missing lock remains an explicit blocked qualification rather
    # than silently inferring one from route fields.
    if LOCK_PATH.is_file() and CANARY_PATH.is_file():
        stage_command.extend(("--integration-lock", str(LOCK_PATH)))
    staged = _run(stage_command, cwd=outside, environment=environment)
    assert staged.returncode == 0, staged.stderr

    marketplace_root = tmp_path / "marketplace/plugins" / PLUGIN_NAME
    shutil.copytree(stage, marketplace_root)
    assert not (marketplace_root / "skills/academic-research-suite").exists()
    assert not any(
        path.is_symlink() for path in marketplace_root.rglob("*")
    )
    return marketplace_root, outside, environment


def test_source_hidden_installed_ars_route_and_bounded_receipt(
    installed_stage: tuple[Path, Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    installed, outside, environment = installed_stage
    run_root = tmp_path / "run"
    run_root.mkdir()
    command_environment = {
        **environment,
        "HOME": str(run_root / "home"),
        "CODEX_HOME": str(run_root / "codex-home"),
        "PYTHONPATH": str(tmp_path / "source-checkout-must-not-be-imported"),
        "ARW_ARS_ROOT": str(ARS_ROOT),
        "ARW_PLUGIN_ROOT": str(installed),
    }
    if (installed / "supply-chain/integration-lock.json").is_file():
        command_environment.update(
            {
                "ARW_INTEGRATION_LOCK": str(LOCK_PATH),
                "ARW_CODEX_LAUNCHER": str(CODEX_LAUNCHER),
                "ARW_CODEX_NATIVE_BINARY": str(CODEX_NATIVE),
                "ARW_HOST_CANARY_EVIDENCE": str(CANARY_PATH),
            }
        )

    result = _run(
        [str(installed / "bin/arw"), "route", "--json"],
        cwd=outside,
        environment=command_environment,
    )
    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["workflow_family"] == "academic-pipeline"
    assert route["source_adapter_version"] == EXPECTED_ARS_ADAPTER_VERSION
    assert route["source_dependency_model"] == "external-exact-installation"
    assert route["source_bundled"] is False
    assert route["paper_ast_export"] == "deferred-v2"
    if (installed / "supply-chain/integration-lock.json").is_file():
        assert route["integration_status"] == "PASS"
        assert route["integration_lock_sha256"] == _digest(LOCK_PATH)
        assert route["reason_codes"] == []
    else:
        assert route["integration_status"] == "BLOCKED"
        assert route["reason_codes"] == ["integration_inputs_incomplete"]

    workflow = ARS_ROOT / "ars/academic-pipeline/WORKFLOW.md"
    assert workflow.is_file() and not workflow.is_symlink()
    fixture_input = canonical_json_bytes(
        {"fixture": "phase7-installed-ars-route", "claim": "bounded"}
    )
    route_output = canonical_json_bytes(route)
    # This is the retained ARS handoff boundary: identity and content digests
    # only.  Full workflow text, credentials, and absolute roots never enter
    # the receipt.
    ars_evidence = {
        "schema_version": "arw.external-ars-route-evidence.v1",
        "workflow": "academic-pipeline",
        "adapter_version": EXPECTED_ARS_ADAPTER_VERSION,
        "dependency_model": "external-exact-installation",
        "bundled": False,
        "workflow_sha256": _digest(workflow),
        "adapter_tree_sha256": _tree_sha256(ARS_ROOT, ignore_runtime_caches=True),
        "input_sha256": hashlib.sha256(fixture_input).hexdigest(),
        "output_sha256": hashlib.sha256(route_output).hexdigest(),
        "command_summary": ["academic-pipeline", "route"],
        "network": "disabled",
        "secret_material_retained": False,
        "absolute_path_material_retained": False,
    }
    ars_path = tmp_path / "ars-route-evidence.json"
    ars_path.write_bytes(canonical_json_bytes(ars_evidence))
    retained = ars_path.read_bytes()
    assert str(REPOSITORY_ROOT).encode() not in retained
    assert str(ARS_ROOT).encode() not in retained
    assert b"auth.json" not in retained
    assert b"OPENAI_API_KEY" not in retained

    lock_sha = _digest(LOCK_PATH) if LOCK_PATH.is_file() else None
    receipt = {
        "schema_version": "arw.installed-qualification.v1",
        "technical_qualification": "PASS" if route["integration_status"] == "PASS" else "BLOCKED",
        "release_qualification": "BLOCKED",
        "stage_sha256": observe_stage_identity(installed),
        "integration_lock_sha256": lock_sha,
        "ars_route_evidence_sha256": _digest(ars_path),
        "hook_definition_sha256": observe_hook_definition(installed)[2],
        "host_canary_sha256": _digest(CANARY_PATH) if CANARY_PATH.is_file() else None,
        "mcp_status": "not-invoked-in-route-smoke",
        "route_result_sha256": hashlib.sha256(route_output).hexdigest(),
        "reason_codes": list(route["reason_codes"]),
        "secret_material_retained": False,
        "absolute_path_material_retained": False,
    }
    _publish_once(
        REPOSITORY_ROOT / "build/evidence/phase-07/installed-qualification.json",
        receipt,
    )


def test_installed_route_rejects_implicit_external_ars_root(
    installed_stage: tuple[Path, Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    installed, outside, environment = installed_stage
    command_environment = {
        **environment,
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "ARW_PLUGIN_ROOT": str(installed),
    }
    result = _run(
        [str(installed / "bin/arw"), "route", "--json"],
        cwd=outside,
        environment=command_environment,
    )
    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["integration_status"] == "BLOCKED"
    assert route["reason_codes"] == ["integration_lock_not_verified"]
    assert route["source_dependency_model"] == "external-exact-installation"
    assert route["source_bundled"] is False
