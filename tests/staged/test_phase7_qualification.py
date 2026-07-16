"""Phase 7 installed-stage, host, hook, and inventory qualification probes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from arw.integration_lock import (
    EXPECTED_CODEX_CLI_VERSION,
    EXPECTED_ARS_ADAPTER_VERSION,
    IntegrationLockError,
    build_integration_lock,
    discover_codex_native_binary,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_QUALIFICATION_CANDIDATES = (
    (
        REPOSITORY_ROOT / "build/stage/phase-07-live-route-fix",
        REPOSITORY_ROOT / "build/evidence/phase-07-live-route-fix",
    ),
    (
        REPOSITORY_ROOT / "build/stage/phase-07-live-bundled",
        REPOSITORY_ROOT / "build/evidence/phase-07-live-bundled",
    ),
    (
        REPOSITORY_ROOT / "build/stage/phase-07-qualified",
        REPOSITORY_ROOT / "build/evidence/phase-07",
    ),
)


def _qualification_inputs() -> tuple[Path, Path, Path]:
    for stage, evidence in _QUALIFICATION_CANDIDATES:
        lock = evidence / "integration-lock.json"
        canary = next(
            (path for path in (evidence / "canary.json", evidence / "host-canary/canary.json") if path.is_file()),
            None,
        )
        staged_lock = stage / "supply-chain/integration-lock.json"
        if lock.is_file() and canary is not None and staged_lock.is_file() and lock.read_bytes() == staged_lock.read_bytes():
            return stage, lock, canary
    return _QUALIFICATION_CANDIDATES[0][0], _QUALIFICATION_CANDIDATES[0][1] / "integration-lock.json", _QUALIFICATION_CANDIDATES[0][1] / "canary.json"


STAGE_ROOT, LOCK_PATH, CANARY_PATH = _qualification_inputs()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def qualified_stage() -> Path:
    for path in (STAGE_ROOT, LOCK_PATH, CANARY_PATH):
        if not path.exists():
            pytest.skip(f"Phase 7 retained qualification input is missing: {path}")
    return STAGE_ROOT


def test_exact_stage_inventory_sbmom_build_identity_and_host_lock(
    qualified_stage: Path,
) -> None:
    inventory = json.loads(
        (qualified_stage / "supply-chain/stage-inventory.json").read_text()
    )
    files = inventory["files"]
    assert files == sorted(files)
    assert inventory["symlinks"] == []
    assert "hooks/arw_hook.py" in files
    assert "hooks/hooks.json" in files
    assert "skills/academic-research-suite/SKILL.md" in files
    assert any(path.startswith("skills/academic-research-suite/ars/") for path in files)

    lock = json.loads(LOCK_PATH.read_text())
    assert lock["codex_host"]["cli_version"] == EXPECTED_CODEX_CLI_VERSION
    assert lock["ars"]["adapter_version"] == EXPECTED_ARS_ADAPTER_VERSION
    assert lock["ars"]["bundled"] is True
    assert lock["technical_qualification"] == "PASS"
    assert lock["release_qualification"] == "BLOCKED"

    sbom = json.loads((qualified_stage / "SBOM.cdx.json").read_text())
    components = {row["bom-ref"]: row for row in sbom["components"]}
    assert components["artifact:supply-chain/integration-lock.json"]["hashes"] == [
        {"alg": "SHA-256", "content": _digest(qualified_stage / "supply-chain/integration-lock.json")}
    ]
    assert components["artifact:hooks/arw_hook.py"]["hashes"] == [
        {"alg": "SHA-256", "content": _digest(qualified_stage / "hooks/arw_hook.py")}
    ]

    identity = json.loads((qualified_stage / "share/arw/build-identity.json").read_text())
    payloads = {row["path"]: row for row in identity["staged_payloads"]}
    assert payloads["hooks/arw_hook.py"]["sha256"] == _digest(
        qualified_stage / "hooks/arw_hook.py"
    )
    assert payloads["supply-chain/integration-lock.json"]["sha256"] == _digest(
        qualified_stage / "supply-chain/integration-lock.json"
    )

    environment = {
        **os.environ,
        "HOME": str(REPOSITORY_ROOT / "build/tmp/phase-07/staged-home"),
        "CODEX_HOME": str(REPOSITORY_ROOT / "build/tmp/phase-07/staged-codex-home"),
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
        "ARW_PLUGIN_ROOT": str(qualified_stage),
        "ARW_INTEGRATION_LOCK": str(LOCK_PATH),
        "ARW_CODEX_LAUNCHER": os.environ.get(
            "ARW_CODEX_LAUNCHER", shutil.which("codex") or "codex"
        ),
        "ARW_CODEX_NATIVE_BINARY": os.environ.get(
            "ARW_CODEX_NATIVE_BINARY",
            str(
                discover_codex_native_binary(
                    Path(
                        os.environ.get(
                            "ARW_CODEX_LAUNCHER", shutil.which("codex") or "codex"
                        )
                    )
                )
            ),
        ),
        "ARW_HOST_CANARY_EVIDENCE": str(CANARY_PATH),
    }
    route = subprocess.run(
        [str(qualified_stage / "bin/arw"), "route", "--json"],
        cwd=REPOSITORY_ROOT / "build/tmp/phase-07",
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    assert route.returncode == 0, route.stderr
    route_payload = json.loads(route.stdout)
    assert route_payload["integration_status"] == "PASS"
    assert route_payload["integration_lock_sha256"] == _digest(LOCK_PATH)

    help_result = subprocess.run(
        [str(qualified_stage / "bin/arw"), "help"],
        cwd=REPOSITORY_ROOT / "build/tmp/phase-07",
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0
    for command in (
        "orchestration-prepare",
        "orchestration-dispatch",
        "orchestration-panel",
        "orchestration-gate",
        "orchestration-hook",
        "orchestration-recover",
    ):
        assert command in help_result.stdout


def test_unsupported_codex_host_version_fails_closed(qualified_stage: Path, tmp_path: Path) -> None:
    launcher = tmp_path / "codex"
    launcher.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"--version\" ]; then printf 'codex-cli 0.144.3\\n'; exit 0; fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    with pytest.raises(IntegrationLockError, match="unsupported.*0.144.4"):
        build_integration_lock(
            stage_root=qualified_stage,
            codex_launcher=launcher,
            codex_native_binary=discover_codex_native_binary(launcher),
            host_canary_evidence=CANARY_PATH,
        )


def test_official_hook_definition_is_observational_and_parity_inputs_are_present(
    qualified_stage: Path,
) -> None:
    hooks = json.loads((qualified_stage / "hooks/hooks.json").read_text())
    assert set(hooks["hooks"]) == {"SessionStart", "SubagentStop", "Stop"}
    for rows in hooks["hooks"].values():
        assert rows and rows[0]["hooks"][0]["type"] == "command"
        assert "${PLUGIN_ROOT}/hooks/arw_hook.py" in rows[0]["hooks"][0]["command"]
    canary = json.loads(CANARY_PATH.read_text())
    assert canary["hook_status_classification"] == "PASS"
    assert canary["live_hook_execution"] == "observed"
    assert canary["fresh_home_default_trust"] == "untrusted_skipped"
    assert canary["secret_material_retained"] is False
    assert canary["absolute_path_material_retained"] is False
