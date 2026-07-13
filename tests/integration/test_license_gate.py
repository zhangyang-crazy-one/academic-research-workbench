from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRE_VENDOR_ROOT = REPOSITORY_ROOT / "build/evidence/phase-01/pre-vendor-license"
POST_VENDOR_ROOT = REPOSITORY_ROOT / "build/evidence/phase-01/license"
EXPECTED_LICENSES = {
    "academic-research-skills": (
        "CC-BY-NC-4.0",
        "vendor/sources/academic-research-skills/LICENSE",
        "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt",
    ),
    "experiment-agent": (
        "CC-BY-NC-4.0",
        "vendor/sources/experiment-agent/LICENSE",
        "LICENSES/experiment-agent-CC-BY-NC-4.0.txt",
    ),
    "file-base": (
        "MIT",
        "vendor/sources/file-base/LICENSE",
        "LICENSES/file-base-MIT.txt",
    ),
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


def _load(relative: str) -> dict[str, object]:
    path = REPOSITORY_ROOT / relative
    assert path.is_file(), f"required legal output is absent: {relative}"
    return json.loads(path.read_text(encoding="utf-8"))


def _run_gate(evidence_root: Path = POST_VENDOR_ROOT) -> subprocess.CompletedProcess[str]:
    gate = REPOSITORY_ROOT / "scripts/license-gate"
    assert gate.is_file() and os.access(gate, os.X_OK), "post-materialization gate is absent"
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1", "PIP_NO_INDEX": "1"})
    return subprocess.run(
        [
            str(gate),
            "--source-manifest",
            "vendor/source-manifest.json",
            "--pre-vendor-evidence",
            "build/evidence/phase-01/pre-vendor-license",
            "--evidence-root",
            str(evidence_root),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_post_materialization_gate_preserves_native_toolchain_and_receipt(tmp_path: Path) -> None:
    evidence_root = tmp_path / "license-evidence"
    result = _run_gate(evidence_root)
    assert result.returncode == 0, result.stderr

    receipt = json.loads((PRE_VENDOR_ROOT / "receipt.json").read_text(encoding="utf-8"))
    evidence = json.loads((evidence_root / "inventory.json").read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "1.0.0"
    assert evidence["pre_vendor_receipt"] == {
        "path": "build/evidence/phase-01/pre-vendor-license/receipt.json",
        "sha256": _sha256(PRE_VENDOR_ROOT / "receipt.json"),
    }
    assert evidence["pre_vendor_receipt"]["sha256"] == _load(
        "vendor/source-manifest.json"
    )["pre_vendor_receipt"]["sha256"]

    native = evidence["native_file_base_gate"]
    assert native["entrypoint"] == "vendor/sources/file-base/scripts/license-gate.sh"
    assert native["technical_qualification"] == "PASS"
    assert REQUIRED_NATIVE_TOOLS <= set(native["executed_tools"])
    assert set(native["executed_tools"]) == {
        item["path"] for item in receipt["native_file_base_gate"]["tools"]
    }
    for command in native["commands"]:
        assert command["status"] == 0
        assert (evidence_root / command["stdout_path"]).is_file()
        assert (evidence_root / command["stderr_path"]).is_file()
    assert (evidence_root / "generated/THIRD_PARTY_NOTICES.md").is_file()
    assert (evidence_root / "raw/native-invocations.log").is_file()


def test_component_identity_and_release_classifier_do_not_collapse_licenses() -> None:
    verdict = _load("supply-chain/license-verdict.json")
    use_distribution = _load("supply-chain/use-distribution.json")
    source_manifest = _load("vendor/source-manifest.json")

    assert verdict["technical_qualification"] == "PASS"
    assert verdict["release_qualification"] == "BLOCKED"
    assert verdict["reason_codes"]
    assert verdict["evidence_needed"]
    assert use_distribution["repository_visibility"] == "private"
    assert use_distribution["private_repository_is_noncommercial_evidence"] is False
    assert use_distribution["intended_use"]["status"] == "unknown"
    assert use_distribution["distribution_class"]["status"] == "unknown"
    assert use_distribution["accountable_approval"]["status"] == "missing"
    assert use_distribution["permission_references"] == []
    assert use_distribution["evidence_hashes"]
    for evidence in use_distribution["evidence_hashes"]:
        assert evidence["purpose"] == "technical-provenance-only"
        assert _sha256(REPOSITORY_ROOT / evidence["path"]) == evidence["sha256"]

    source_components = {item["id"]: item for item in source_manifest["components"]}
    classified = {item["component_id"]: item for item in verdict["components"]}
    assert set(classified) == set(EXPECTED_LICENSES)
    for component_id, (spdx, source_path, staged_path) in EXPECTED_LICENSES.items():
        record = classified[component_id]
        assert record["license"] == spdx
        assert record["source_path"] == source_path
        assert record["staged_path"] == staged_path
        assert record["source_sha256"] == source_components[component_id]["licenses"][0]["sha256"]
        assert _sha256(REPOSITORY_ROOT / source_path) == record["source_sha256"]
        assert _sha256(REPOSITORY_ROOT / staged_path) == record["staged_sha256"]
        assert (REPOSITORY_ROOT / source_path).read_bytes() == (
            REPOSITORY_ROOT / staged_path
        ).read_bytes()

    assert classified["academic-research-skills"]["release_status"] == "BLOCKED"
    assert classified["experiment-agent"]["release_status"] == "BLOCKED"
    assert classified["file-base"]["release_status"] == "SATISFIED"
