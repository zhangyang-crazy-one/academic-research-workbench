from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPOSITORY_ROOT / "build/evidence/phase-01/pre-vendor-license"
RECEIPT_PATH = EVIDENCE_ROOT / "receipt.json"
EXPECTED_PINS = {
    "academic-research-skills": {
        "revision": "8cc7f8f4cccda721646d9df590b42721c93cba31",
        "upstream_url": "https://github.com/Imbad0202/academic-research-skills.git",
    },
    "experiment-agent": {
        "revision": "e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651",
        "upstream_url": "https://github.com/Imbad0202/experiment-agent.git",
    },
    "file-base": {
        "revision": "ee68144af5453addda995a27cce8142999f318fb",
        "upstream_url": "https://github.com/DeusData/codebase-memory-mcp.git",
    },
}
REQUIRED_NATIVE_TOOLS = {
    "scripts/license-gate.sh",
    "scripts/license-policy.json",
    "scripts/license-gate-check.py",
    "scripts/license-gate-check-npm.py",
    "scripts/gen-third-party-notices.sh",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt() -> dict[str, object]:
    script = REPOSITORY_ROOT / "scripts/pre-vendor-license-gate"
    assert script.is_file(), "pre-vendor gate script is absent"
    assert RECEIPT_PATH.is_file(), "passing pre-vendor receipt is absent"
    digest_file = EVIDENCE_ROOT / "receipt.sha256"
    assert digest_file.is_file(), "receipt digest sidecar is absent"
    assert digest_file.read_text(encoding="utf-8").strip() == _sha256(RECEIPT_PATH)
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def test_exact_clean_pins_pass_native_gate_before_vendor_copy() -> None:
    receipt = _receipt()
    assert receipt["schema_version"] == "1.0.0"
    assert receipt["technical_qualification"] == "PASS"

    components = {item["id"]: item for item in receipt["components"]}
    assert set(components) == set(EXPECTED_PINS)
    for component_id, expected in EXPECTED_PINS.items():
        component = components[component_id]
        assert component["revision"] == expected["revision"]
        assert component["upstream_url"] == expected["upstream_url"]
        assert component["clean"] is True
        assert component["status_porcelain"] == ""
        assert len(component["git_tree"]) == 40
        assert len(component["tree_sha256"]) == 64

    observations = receipt["vendor_sources_observations"]
    assert observations[0] == {"exists": False, "phase": "before"}
    assert observations[-1] == {"exists": False, "phase": "after"}
    assert all(observation["exists"] is False for observation in observations)
    assert any(observation["phase"].startswith("during:") for observation in observations)

    native = receipt["native_file_base_gate"]
    tools = {item["path"]: item for item in native["tools"]}
    assert REQUIRED_NATIVE_TOOLS <= set(tools)
    assert native["entrypoint"] == "scripts/license-gate.sh"
    assert native["unmodified"] is True
    assert native["generated_notices"]
    assert all(command["status"] == 0 for command in native["commands"])
    assert all(command["argv"] for command in native["commands"])
    assert all(command["stdout_path"] and command["stderr_path"] for command in native["commands"])
    invocations = (EVIDENCE_ROOT / "commands/native-invocations.log").read_text(encoding="utf-8")
    assert "scancode --license --quiet --processes 2" in invocations
    assert "scripts/license-gate-check.py" in invocations
    assert "scripts/license-gate-check-npm.py" in invocations
    assert "npm ci --ignore-scripts --silent" in invocations


def test_receipt_closes_every_legal_input_and_raw_output() -> None:
    receipt = _receipt()
    legal_paths = {item["path"] for item in receipt["legal_inputs"]}
    assert REQUIRED_NATIVE_TOOLS <= legal_paths
    assert "LICENSE" in legal_paths
    assert any(path.startswith("vendored/") and "LICENSE" in path for path in legal_paths)
    assert "vendored/nomic/NOTICE" in legal_paths

    licenses = {item["component"]: item for item in receipt["component_licenses"]}
    assert licenses["academic-research-skills"]["source_path"] == "LICENSE"
    assert licenses["experiment-agent"]["source_path"] == "LICENSE"
    assert licenses["academic-research-skills"]["attribution_required"] is True
    assert licenses["academic-research-skills"]["modification_marking_required"] is True
    assert licenses["experiment-agent"]["noncommercial_restriction"] is True

    raw = receipt["raw_evidence"]
    assert raw
    for item in raw:
        path = EVIDENCE_ROOT / item["path"]
        assert path.is_file(), f"missing raw evidence: {item['path']}"
        assert _sha256(path) == item["sha256"]

    identities = receipt["tool_identities"]
    assert identities["git"].startswith("git version ")
    assert identities["python"]
    assert identities["node"].startswith("v")
    assert identities["npm"]
    assert "ScanCode version: 32.5.0" in identities["scancode"]
