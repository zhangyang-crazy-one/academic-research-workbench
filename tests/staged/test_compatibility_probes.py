from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_skill_route import installed_route_evidence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FRAGMENTS = (
    "Paper4Master",
    "Examination",
    str(Path.home()),
    str(REPOSITORY_ROOT),
)


def _smoke_namespace(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    script = REPOSITORY_ROOT / "scripts/smoke-staged-plugin"
    source = script.read_text(encoding="utf-8")
    python_source = source.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    python_source = python_source.rsplit("\nraise SystemExit(main())", 1)[0]
    monkeypatch.setattr(sys, "argv", [str(script), str(REPOSITORY_ROOT)])
    namespace: dict[str, object] = {"__name__": "smoke_staged_plugin_test"}
    exec(compile(python_source, str(script), "exec"), namespace)
    return namespace


def test_smoke_reuses_an_existing_stage_without_rebuilding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _smoke_namespace(monkeypatch)
    stage_root = tmp_path / "qualified-stage"
    stage_root.mkdir()
    lock = stage_root / "supply-chain/integration-lock.json"
    lock.parent.mkdir()
    lock.write_text('{"qualified":true}\n', encoding="utf-8")
    before = lock.read_bytes()

    def unexpected_restage(*args, **kwargs):
        pytest.fail("an existing stage must not be passed to stage-plugin")

    monkeypatch.setitem(namespace, "run_recorded", unexpected_restage)
    materialized = namespace["materialize_stage_if_missing"](
        stage_root,
        tmp_path / "evidence",
        cachebuster="must-not-be-used",
    )

    assert materialized is False
    assert lock.read_bytes() == before
    assert not (tmp_path / "evidence").exists()


def test_route_smoke_validates_official_hook_receipt_and_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _smoke_namespace(monkeypatch)
    inspect_definition = namespace["inspect_installed_hook_definition"]
    validate_receipt = namespace["validate_hook_receipt"]
    defect = namespace["CanaryDefect"]
    definition = inspect_definition(REPOSITORY_ROOT)
    plugin_data = tmp_path / "plugin-data"
    payload = {
        "session_id": "session-smoke-001",
        "transcript_path": None,
        "cwd": str(tmp_path),
        "hook_event_name": "SessionStart",
        "model": "gpt-smoke",
        "permission_mode": "default",
        "source": "startup",
    }
    environment = os.environ.copy()
    environment["PLUGIN_ROOT"] = str(REPOSITORY_ROOT)
    environment["PLUGIN_DATA"] = str(plugin_data)
    emitted = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "hooks/arw_hook.py")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        cwd=tmp_path,
    )
    assert emitted.returncode == 0, emitted.stderr

    receipt_root = plugin_data / "hook-observations/v1"
    receipt_path = next(receipt_root.glob("*.json"))
    receipt = validate_receipt(
        receipt_path,
        receipt_root=receipt_root,
        installed_root=REPOSITORY_ROOT,
        expected_definition_sha256=definition["definition_sha256"],
    )
    assert receipt["authority"] == "observational"
    assert receipt["hook_definition_sha256"] == definition["definition_sha256"]

    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["authority"] = "canonical"
    receipt_path.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(defect, match="canonical|content addressed"):
        validate_receipt(
            receipt_path,
            receipt_root=receipt_root,
            installed_root=REPOSITORY_ROOT,
            expected_definition_sha256=definition["definition_sha256"],
        )


def test_route_smoke_distinguishes_automation_bypass_from_persisted_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _smoke_namespace(monkeypatch)
    classify = namespace["classify_attempt"]
    direct = {"schema_version": "1.0.0", "workflow_family": "academic-research-suite"}
    result_path = tmp_path / "host-result.json"
    result_path.write_text(json.dumps(direct), encoding="utf-8")
    command_event = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item-route",
                "type": "command_execution",
                "command": '"$plugin_root/bin/arw" route --json',
                "aggregated_output": json.dumps(direct),
                "exit_code": 0,
                "status": "completed",
            },
        }
    )
    host = subprocess.CompletedProcess([], 0, command_event, "")
    installed = {"identity": {"installed_sha256": "a" * 64}}
    hook_evidence = {
        "definition_sha256": "b" * 64,
        "receipt_count": 1,
        "receipt_events": ["SessionStart"],
        "valid": True,
    }

    automated = classify(
        "001",
        installed,
        host,
        direct,
        result_path,
        hook_evidence,
        hook_trust_mode="automation-bypass",
    )
    persisted = classify(
        "001",
        installed,
        host,
        direct,
        result_path,
        hook_evidence,
        hook_trust_mode="persisted-trust",
    )

    assert automated["classification"] == persisted["classification"] == "pass"
    assert automated["hook_status"] == "automation-bypass-executed"
    assert persisted["hook_status"] == "persisted-trusted-executed"
    assert automated["installed_command_evidence"] == persisted["installed_command_evidence"]
    assert automated["installed_command_evidence"][0]["successful"] is True


@pytest.mark.codex_host
def test_installed_host_reports_honest_compatibility_boundary(
    installed_route_evidence: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    evidence, canary = installed_route_evidence
    assert canary.returncode == 0, (
        "installed compatibility canary did not converge\n"
        f"stdout:\n{canary.stdout}\n"
        f"stderr:\n{canary.stderr}"
    )
    compatibility = json.loads(
        (evidence / "plugin/compatibility/result.json").read_text()
    )

    assert compatibility["schema_version"] == "1.0.0"
    assert compatibility["technical_qualification"] == "PASS"
    assert compatibility["host"]["fresh_process"] is True
    assert compatibility["host"]["installed_skill_invoked"] is True
    assert compatibility["host"]["authentication_material_retained"] is False
    assert compatibility["hooks"] == {
        "authority": "none",
        "canonical_write": False,
        "contract": "default-plugin-hooks-file",
        "definition_sha256": compatibility["hooks"]["definition_sha256"],
        "mode": "observational-read-only",
        "receipt_contract": "arw.codex-hook-observation.v1",
        "receipt_count": compatibility["hooks"]["receipt_count"],
        "receipt_events": compatibility["hooks"]["receipt_events"],
        "status": "automation-bypass-executed",
        "trust": "automation-bypass-not-persisted",
    }
    assert len(compatibility["hooks"]["definition_sha256"]) == 64
    assert compatibility["hooks"]["receipt_count"] >= 1
    assert "SessionStart" in compatibility["hooks"]["receipt_events"]
    assert compatibility["custom_agents"] == {
        "plugin_distribution": "unproven",
        "fallback": [
            "native-codex-subagents",
            "immutable-assignment-injected-roles",
        ],
    }
    assert compatibility["experiments"] == {
        "execution": "disabled",
        "ownership": "deferred",
    }
    assert compatibility["unresolved_non_authentication_results"] == []

    attempts = compatibility["attempts"]
    assert attempts
    assert attempts[-1]["classification"] == "pass"
    assert all(attempt["classification"] != "blocking-unknown" for attempt in attempts)
    assert attempts[-1]["installed_identity_sha256"]
    assert attempts[-1]["hook_status"] == "automation-bypass-executed"
    assert attempts[-1]["hook_receipt_count"] >= 1
    assert attempts[-1]["successful_installed_commands"] == 1
    assert all(
        attempt["installed_identity_sha256"]
        for attempt in attempts
        if attempt["classification"] != "authentication-required"
    )

    evidence_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in evidence.rglob("*")
        if path.is_file()
    )
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in evidence_text

    assert "PYTHONPATH=unset" in evidence_text or '"PYTHONPATH": "unset"' in evidence_text
    summary = json.loads((evidence / "summary.json").read_text())
    assert summary["technical_qualification"] == "PASS"
    assert summary["installed_from_exact_stage"] is True
    assert summary["source_imported"] is False
    assert summary["inherited_pythonpath"] is False
    assert summary["route_final_attempt"] == attempts[-1]["attempt"]
