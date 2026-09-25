from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

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


def _build_candidate(candidate_root: Path) -> tuple[Path, Path]:
    assert shutil.which("uv"), "candidate build requires uv"
    builder_python = sys.executable if sys.version_info >= (3, 13) else shutil.which("python3.13")
    assert builder_python, "candidate build requires Python >=3.13"
    build = subprocess.run(
        [builder_python, str(REPOSITORY_ROOT / "scripts/build-candidate"), "--output-root", str(candidate_root)],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    evidence_path = candidate_root / "build-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    wheel = candidate_root / next(row["path"] for row in evidence["artifacts"] if row["kind"] == "wheel")
    return wheel, evidence_path


def _run_gate(evidence_root: Path, candidate: tuple[Path, Path] | None = None) -> subprocess.CompletedProcess[str]:
    gate = REPOSITORY_ROOT / "scripts/license-gate"
    assert gate.is_file() and os.access(gate, os.X_OK), "post-materialization gate is absent"
    wheel, evidence_path = candidate or _build_candidate(evidence_root.parent / "candidate")
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1"})
    return subprocess.run(
        [
            str(gate),
            "--source-manifest",
            "vendor/source-manifest.json",
            "--pre-vendor-evidence",
            "build/evidence/phase-01/pre-vendor-license",
            "--wheel",
            str(wheel),
            "--build-evidence",
            str(evidence_path),
            "--output-root",
            str(evidence_root),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _rewrite_wheel_with_member(wheel: Path, member: str, content: bytes) -> None:
    replacement = wheel.with_suffix(".new")
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(replacement, "w") as target:
        record_name = next(name for name in source.namelist() if name.endswith(".dist-info/RECORD"))
        rows: list[list[str]] = []
        for info in source.infolist():
            if info.filename == record_name:
                continue
            data = content if info.filename == member else source.read(info.filename)
            target.writestr(info, data)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            rows.append([info.filename, f"sha256={encoded}", str(len(data))])
        if member not in source.namelist():
            target.writestr(member, content)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
            rows.append([member, f"sha256={encoded}", str(len(content))])
        rows.append([record_name, "", ""])
        record = io.StringIO(newline="")
        csv.writer(record).writerows(rows)
        target.writestr(source.getinfo(record_name), record.getvalue().encode("utf-8"))
    replacement.replace(wheel)


def _refresh_wheel_evidence(wheel: Path, evidence_path: Path) -> None:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    row = next(item for item in evidence["artifacts"] if item["kind"] == "wheel")
    row["size"] = wheel.stat().st_size
    row["sha256"] = _sha256(wheel)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.requires_materialized_sources
@pytest.mark.requires_retained_evidence("build/evidence/phase-01/pre-vendor-license/receipt.json")
def test_gate_rejects_resealed_wheel_without_required_license(tmp_path: Path) -> None:
    wheel, evidence_path = _build_candidate(tmp_path / "valid-candidate")
    with zipfile.ZipFile(wheel) as source:
        prefix = next(name.removesuffix("METADATA") for name in source.namelist() if name.endswith(".dist-info/METADATA"))
        assert prefix + "licenses/LICENSE" in source.namelist()
        assert b"License-File: LICENSE\n" in source.read(prefix + "METADATA")
        record_name = prefix + "RECORD"
        members = [(info, source.read(info.filename)) for info in source.infolist()
                   if info.filename not in {prefix + "licenses/LICENSE", record_name}]
        record_info = source.getinfo(record_name)
    replacement = wheel.with_suffix(".new")
    with zipfile.ZipFile(replacement, "w") as target:
        rows: list[list[str]] = []
        for info, data in members:
            if info.filename == prefix + "METADATA":
                data = data.replace(b"License-File: LICENSE\n", b"")
            target.writestr(info, data)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            rows.append([info.filename, f"sha256={encoded}", str(len(data))])
        rows.append([record_name, "", ""])
        record = io.StringIO(newline="")
        csv.writer(record).writerows(rows)
        target.writestr(record_info, record.getvalue().encode("utf-8"))
    replacement.replace(wheel)
    _refresh_wheel_evidence(wheel, evidence_path)

    output_root = tmp_path / "gate-output"
    result = _run_gate(output_root, (wheel, evidence_path))
    assert result.returncode != 0
    assert "required wheel license files are absent: ['LICENSE']" in result.stderr
    assert not output_root.exists()


@pytest.mark.requires_materialized_sources
@pytest.mark.requires_retained_evidence("build/evidence/phase-01/pre-vendor-license/receipt.json")
def test_post_materialization_gate_preserves_native_toolchain_and_receipt(tmp_path: Path) -> None:
    evidence_parent = Path(os.environ.get("ARW_LICENSE_GATE_TEST_ROOT", str(tmp_path)))
    evidence_root = evidence_parent / "gate-output"
    canonical_before = {
        relative: _sha256(REPOSITORY_ROOT / relative)
        for relative in ("SBOM.cdx.json", "THIRD_PARTY_NOTICES.md", "supply-chain/use-distribution.json", "supply-chain/license-verdict.json")
    }
    result = _run_gate(evidence_root)
    assert result.returncode == 0, result.stderr

    receipt = json.loads((PRE_VENDOR_ROOT / "receipt.json").read_text(encoding="utf-8"))
    evidence = json.loads((evidence_root / "license-evidence/inventory.json").read_text(encoding="utf-8"))
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
        assert (evidence_root / "license-evidence" / command["stdout_path"]).is_file()
        assert (evidence_root / "license-evidence" / command["stderr_path"]).is_file()
    assert (evidence_root / "license-evidence/generated/THIRD_PARTY_NOTICES.md").is_file()
    assert (evidence_root / "license-evidence/raw/native-invocations.log").is_file()
    assert not (evidence_root / "THIRD_PARTY_NOTICES.md").read_bytes().endswith(
        b"\n\n"
    )
    notices = (evidence_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "bundled adapter source `skills/academic-research-suite/ars/`" in notices
    assert "identity `vendor/mcp-manifest.json`" in notices
    assert canonical_before == {relative: _sha256(REPOSITORY_ROOT / relative) for relative in canonical_before}
    assert evidence["first_party_wheel"]["sha256"] == next(
        item["hashes"][0]["content"]
        for item in json.loads((evidence_root / "SBOM.cdx.json").read_text())["components"]
        if item["bom-ref"].startswith("first-party-wheel:")
    )


@pytest.mark.requires_materialized_sources
@pytest.mark.requires_retained_evidence("build/evidence/phase-01/pre-vendor-license/receipt.json")
def test_gate_rejects_resealed_undeclared_dist_info(tmp_path: Path) -> None:
    original_root = tmp_path / "valid-candidate"
    original_wheel, _ = _build_candidate(original_root)
    with zipfile.ZipFile(original_wheel) as archive:
        prefix = next(name.removesuffix("METADATA") for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(prefix + "METADATA")
        wheel_info = archive.read(prefix + "WHEEL")
    cases = (
        ("undeclared-entry-point", "entry_points.txt", b"[console_scripts]\narw-hidden = arw.cli:main\n", "entry_points.txt"),
        ("unknown-member", "installer.json", b"{}\n", "unexpected dist-info members"),
        ("unknown-metadata-field", "METADATA", metadata + b"X-Install-Override: enabled\n", "unexpected fields"),
        ("unknown-wheel-field", "WHEEL", wheel_info + b"X-Install-Override: enabled\n", "unexpected fields"),
    )
    for label, relative, content, expected_error in cases:
        candidate_root = tmp_path / label
        shutil.copytree(original_root, candidate_root)
        wheel = candidate_root / original_wheel.relative_to(original_root)
        evidence_path = candidate_root / "build-evidence.json"
        _rewrite_wheel_with_member(wheel, prefix + relative, content)
        _refresh_wheel_evidence(wheel, evidence_path)

        output_root = tmp_path / f"{label}-gate-output"
        result = _run_gate(output_root, (wheel, evidence_path))
        assert result.returncode != 0, label
        assert expected_error in result.stderr, result.stderr
        assert not output_root.exists(), label


@pytest.mark.requires_materialized_sources
def test_component_identity_and_release_classifier_do_not_collapse_licenses() -> None:
    verdict = _load("supply-chain/license-verdict.json")
    use_distribution = _load("supply-chain/use-distribution.json")
    source_manifest = _load("vendor/source-manifest.json")

    assert verdict["technical_qualification"] == "PASS"
    assert verdict["release_qualification"] == "BLOCKED"
    assert verdict["reason_codes"]
    assert verdict["evidence_needed"]
    assert use_distribution["repository_visibility"] == "public"
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
