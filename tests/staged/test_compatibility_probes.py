from __future__ import annotations

import json
import subprocess
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
        "canonical_write": False,
        "contract": "default-plugin-hooks-file",
        "mode": "observational-read-only",
        "status": compatibility["hooks"]["status"],
    }
    assert compatibility["hooks"]["status"] in {
        "executed",
        "discovered-untrusted-skipped",
    }
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
