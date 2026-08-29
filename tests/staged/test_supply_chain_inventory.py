# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from arw.canonical import canonical_json_bytes
from arw.integration_lock import (
    IntegrationLock,
    _tree_sha256,
    _validate_arw_runtime,
    _validate_bundled_ars,
    _validate_file_base,
    _validate_license,
    integration_lock_bytes,
    observe_build_identity_binding,
    observe_hook_definition,
    observe_stage_identity,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
LEGAL_FILES = {
    "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt",
    "LICENSES/experiment-agent-CC-BY-NC-4.0.txt",
    "LICENSES/file-base-MIT.txt",
    "THIRD_PARTY_NOTICES.md",
    "MODIFICATIONS.md",
    "SBOM.cdx.json",
    "supply-chain/use-distribution.json",
    "supply-chain/license-verdict.json",
    "vendor/source-manifest.json",
    "vendor/mcp-manifest.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"required inventory file is absent: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_pretty(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rebind_inventory(stage_root: Path, *relative_paths: str) -> None:
    inventory_path = stage_root / "supply-chain/stage-inventory.json"
    inventory = _load(inventory_path)
    covered = {item["path"]: item for item in inventory["covered_files"]}
    for relative in relative_paths:
        covered[relative]["sha256"] = _sha256(stage_root / relative)
    _write_pretty(inventory_path, inventory)


def _stage(
    stage_root: Path,
    *,
    integration_lock: Path | None = None,
    cachebuster: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1", "PIP_NO_INDEX": "1"}
    )
    command = [
        str(REPOSITORY_ROOT / "scripts/stage-plugin"),
        "--clean",
        "--stage-root",
        str(stage_root),
    ]
    if integration_lock is not None:
        command.extend(("--integration-lock", str(integration_lock)))
    if cachebuster is not None:
        command.extend(("--cachebuster", cachebuster))
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _validate_stage(
    stage_root: Path, *, integration_lock: Path | None = None
) -> subprocess.CompletedProcess[str]:
    command = [
        str(REPOSITORY_ROOT / "scripts/stage-plugin"),
        "--stage-root",
        str(stage_root),
        "--validate-only",
    ]
    if integration_lock is not None:
        command.extend(("--integration-lock", str(integration_lock)))
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env={
            **os.environ,
            "PYTHONNOUSERSITE": "1",
            "UV_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _canonical_test_lock(stage_root: Path) -> bytes:
    """Return a model-valid qualification lock without publishing real evidence."""

    def repeated(value: str) -> str:
        return value * 64

    def binding(path: str, value: str = "a") -> dict[str, str]:
        return {"path": path, "sha256": repeated(value)}

    host = {
        # Phase 7 binds the retained exact host baseline; fixture locks must
        # exercise that same supported tuple rather than the prior 0.144.3
        # probe, which is intentionally covered by the negative canary tests.
        "cli_version": "codex-cli 0.144.6",
        "platform_system": "Linux",
        "platform_release": "qualification-test",
        "platform_machine": "x86_64",
        "launcher": {
            "invoked_path": "/qualification/codex",
            "resolved_path": "/qualification/codex",
            "sha256": repeated("a"),
        },
        "native_binary": {
            "invoked_path": "/qualification/codex-native",
            "resolved_path": "/qualification/codex-native",
            "sha256": repeated("b"),
        },
    }
    host["tuple_sha256"] = hashlib.sha256(canonical_json_bytes(host)).hexdigest()
    observed_arw = _validate_arw_runtime(stage_root)
    source_manifest = _load(stage_root / "vendor/source-manifest.json")
    observed_file_base = _validate_file_base(stage_root, source_manifest)
    observed_ars = _validate_bundled_ars(stage_root, source_manifest)
    observed_license = _validate_license(stage_root)
    observed_build_identity = observe_build_identity_binding(
        stage_root, source_manifest
    )
    hook_config, hook_handler, hook_definition = observe_hook_definition(stage_root)
    payload = {
        "schema_version": "arw.integration-lock.v2",
        "dependency_model": "bundled-pinned-adapter",
        "arw_runtime": observed_arw.model_dump(mode="json"),
        "ars": observed_ars.model_dump(mode="json"),
        "file_base": observed_file_base.model_dump(mode="json"),
        "codex_host": host,
        "hook": {
            "config": hook_config.model_dump(mode="json"),
            "handler": hook_handler.model_dump(mode="json"),
            "definition_algorithm": "relative-name-nul-bytes-nul-v1",
            "definition_sha256": hook_definition,
            "hook_execution_admission": "automation_vetted_bypass",
            "live_hook_execution": "observed",
            "fresh_home_default_trust": "untrusted_skipped",
            "host_canary_evidence_sha256": repeated("b"),
            "evidence_bundle_sha256": repeated("c"),
            "fresh_home_receipt_sha256": [
                repeated("a"),
                repeated("b"),
                repeated("c"),
            ],
            "arw_runtime_sha256": observed_arw.wheel.sha256,
            "stage_identity_algorithm": "content-tree-excluding-cycle-metadata-v1",
            "stage_sha256": observe_stage_identity(stage_root),
            "credential_policy_sha256": repeated("f"),
        },
        "license": observed_license.model_dump(mode="json"),
        "build_identity": observed_build_identity.model_dump(mode="json"),
        "technical_qualification": "PASS",
        "release_qualification": "BLOCKED",
    }
    lock = IntegrationLock.model_validate_json(
        canonical_json_bytes(payload), strict=True
    )
    return integration_lock_bytes(lock)


def _locally_bound_test_lock(tmp_path: Path, label: str) -> bytes:
    base_stage = tmp_path / f"{label}-lock-input" / PLUGIN_NAME
    result = _stage(base_stage)
    assert result.returncode == 0, result.stderr
    return _canonical_test_lock(base_stage)


def test_sbom_covers_frozen_python_wheels_patches_native_and_source_components() -> (
    None
):
    sbom = _load(REPOSITORY_ROOT / "SBOM.cdx.json")
    source_manifest = _load(REPOSITORY_ROOT / "vendor/source-manifest.json")
    wheelhouse = _load(REPOSITORY_ROOT / "vendor/python/wheelhouse.lock.json")

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert sbom["version"] == 1
    components = {item["bom-ref"]: item for item in sbom["components"]}
    expected_refs = {f"source:{item['id']}" for item in source_manifest["components"]}
    expected_refs |= {f"patch:{item['sha256']}" for item in source_manifest["patches"]}
    expected_refs |= {f"python-wheel:{item['file']}" for item in wheelhouse["wheels"]}
    expected_refs |= {
        f"artifact:{item['path']}" for item in source_manifest["declared_artifacts"]
    }
    expected_refs |= {
        "artifact:hooks/hooks.json",
        "artifact:hooks/arw_hook.py",
        "artifact:schemas/v1/integration-lock.schema.json",
        "artifact:vendor/mcp-manifest.json",
        "artifact:skills/academic-research-suite",
        "artifact:skills/academic-research-suite/ars",
        "artifact:skills/academic-research-suite/SKILL.md",
        "artifact:skills/academic-research-suite/manifest.json",
        "artifact:skills/academic-research-suite/VERSION",
    }
    assert expected_refs <= set(components)
    for item in source_manifest["patches"]:
        assert components[f"patch:{item['sha256']}"]["hashes"] == [
            {"alg": "SHA-256", "content": item["sha256"]}
        ]
    for wheel in wheelhouse["wheels"]:
        component = components[f"python-wheel:{wheel['file']}"]
        assert component["name"] == wheel["package"]
        assert component["version"] == wheel["version"]
        assert component["hashes"] == [{"alg": "SHA-256", "content": wheel["sha256"]}]
    for relative in (
        "hooks/hooks.json",
        "hooks/arw_hook.py",
        "schemas/v1/integration-lock.schema.json",
        "vendor/mcp-manifest.json",
    ):
        assert components[f"artifact:{relative}"]["hashes"] == [
            {"alg": "SHA-256", "content": _sha256(REPOSITORY_ROOT / relative)}
        ]
    suite_root = REPOSITORY_ROOT / "skills/academic-research-suite"
    assert components["artifact:skills/academic-research-suite"]["hashes"] == [
        {
            "alg": "SHA-256",
            "content": _tree_sha256(suite_root, ignore_runtime_caches=True),
        }
    ]
    assert components["artifact:skills/academic-research-suite/ars"]["hashes"] == [
        {
            "alg": "SHA-256",
            "content": _tree_sha256(suite_root / "ars", ignore_runtime_caches=True),
        }
    ]


def test_use_distribution_technical_provenance_hashes_are_fresh() -> None:
    declaration = _load(REPOSITORY_ROOT / "supply-chain/use-distribution.json")
    evidence = declaration["evidence_hashes"]
    assert isinstance(evidence, list)
    evidence_paths = [record["path"] for record in evidence]
    assert len(evidence_paths) == len(set(evidence_paths))
    assert set(evidence_paths) == {
        "vendor/source-manifest.json",
        "SBOM.cdx.json",
        "THIRD_PARTY_NOTICES.md",
    }
    assert "supply-chain/use-distribution.json" not in evidence_paths
    for record in evidence:
        assert record["purpose"] == "technical-provenance-only"
        evidence_path = REPOSITORY_ROOT / record["path"]
        assert evidence_path.is_file(), (
            f"missing technical provenance: {record['path']}"
        )
        assert record["sha256"] == _sha256(evidence_path), (
            f"stale technical provenance digest: {record['path']}"
        )
    sbom = _load(REPOSITORY_ROOT / "SBOM.cdx.json")
    component_refs = {item["bom-ref"] for item in sbom["components"]}
    assert "artifact:supply-chain/use-distribution.json" not in component_refs


def test_validate_only_rejects_rebound_stale_technical_provenance(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "stale-provenance" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    declaration_path = stage_root / "supply-chain/use-distribution.json"
    declaration = _load(declaration_path)
    sbom_record = next(
        record
        for record in declaration["evidence_hashes"]
        if record["path"] == "SBOM.cdx.json"
    )
    sbom_record["sha256"] = "0" * 64
    _write_pretty(declaration_path, declaration)

    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    payloads["supply-chain/use-distribution.json"]["sha256"] = _sha256(declaration_path)
    _write_pretty(identity_path, identity)
    _rebind_inventory(
        stage_root,
        "supply-chain/use-distribution.json",
        "share/arw/build-identity.json",
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "technical provenance digest mismatch: SBOM.cdx.json" in validated.stderr


def test_validate_only_rejects_missing_required_technical_provenance_row(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "missing-provenance" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    declaration_path = stage_root / "supply-chain/use-distribution.json"
    declaration = _load(declaration_path)
    declaration["evidence_hashes"] = [
        record
        for record in declaration["evidence_hashes"]
        if record["path"] != "SBOM.cdx.json"
    ]
    _write_pretty(declaration_path, declaration)

    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    payloads["supply-chain/use-distribution.json"]["sha256"] = _sha256(declaration_path)
    _write_pretty(identity_path, identity)
    _rebind_inventory(
        stage_root,
        "supply-chain/use-distribution.json",
        "share/arw/build-identity.json",
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "technical provenance path set mismatch" in validated.stderr
    assert "SBOM.cdx.json" in validated.stderr


def test_exact_stage_contains_inventory_covered_legal_outputs(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    actual = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file()
    }
    assert actual >= LEGAL_FILES
    verdict = _load(stage_root / "supply-chain/license-verdict.json")
    assert verdict["technical_qualification"] == "PASS"
    assert verdict["release_qualification"] == "BLOCKED"
    assert _load(stage_root / "vendor/source-manifest.json") == _load(
        REPOSITORY_ROOT / "vendor/source-manifest.json"
    )

    stage_inventory = _load(stage_root / "supply-chain/stage-inventory.json")
    assert stage_inventory["files"] == sorted(actual)
    assert stage_inventory["symlinks"] == []
    covered = {item["path"]: item for item in stage_inventory["covered_files"]}
    assert set(covered) == actual - {"supply-chain/stage-inventory.json"}
    for relative, record in covered.items():
        assert record["sha256"] == _sha256(stage_root / relative)
        assert record["inventory_source"] in {
            "build",
            "legal",
            "runtime",
            "source-manifest",
            "wheelhouse",
        }


def test_base_stage_remains_lock_free_and_validate_only_compatible(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "base-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    source_sbom = (REPOSITORY_ROOT / "SBOM.cdx.json").read_bytes()
    staged_sbom = stage_root / "SBOM.cdx.json"
    assert staged_sbom.read_bytes() == source_sbom
    assert not (stage_root / "supply-chain/integration-lock.json").exists()
    sbom = _load(staged_sbom)
    assert "artifact:supply-chain/integration-lock.json" not in {
        item["bom-ref"] for item in sbom["components"]
    }

    identity = _load(stage_root / "share/arw/build-identity.json")
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    assert "supply-chain/integration-lock.json" not in payloads
    assert payloads["SBOM.cdx.json"]["sha256"] == _sha256(staged_sbom)
    validated = _validate_stage(stage_root)
    assert validated.returncode == 0, validated.stderr


def test_optional_integration_lock_is_bound_without_changing_release_verdict(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "qualification-lock.json"
    lock_bytes = _locally_bound_test_lock(tmp_path, "included")
    lock_path.write_bytes(lock_bytes)
    source_sbom_path = REPOSITORY_ROOT / "SBOM.cdx.json"
    source_sbom = source_sbom_path.read_bytes()
    stage_root = tmp_path / "qualified-stage" / PLUGIN_NAME

    result = _stage(stage_root, integration_lock=lock_path)
    assert result.returncode == 0, result.stderr
    staged_lock = stage_root / "supply-chain/integration-lock.json"
    staged_sbom = stage_root / "SBOM.cdx.json"
    assert staged_lock.read_bytes() == lock_bytes
    assert source_sbom_path.read_bytes() == source_sbom

    lock_sha256 = _sha256(staged_lock)
    sbom = _load(staged_sbom)
    components = {item["bom-ref"]: item for item in sbom["components"]}
    assert components["artifact:supply-chain/integration-lock.json"] == {
        "bom-ref": "artifact:supply-chain/integration-lock.json",
        "hashes": [{"alg": "SHA-256", "content": lock_sha256}],
        "name": "supply-chain/integration-lock.json",
        "type": "file",
        "version": "1",
    }

    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    assert payloads["supply-chain/integration-lock.json"]["sha256"] == lock_sha256
    assert payloads["SBOM.cdx.json"]["sha256"] == _sha256(staged_sbom)
    assert "share/arw/build-identity.json" not in payloads

    inventory = _load(stage_root / "supply-chain/stage-inventory.json")
    covered = {item["path"]: item for item in inventory["covered_files"]}
    for relative in (
        "supply-chain/integration-lock.json",
        "SBOM.cdx.json",
        "share/arw/build-identity.json",
    ):
        assert covered[relative]["sha256"] == _sha256(stage_root / relative)
    assert (
        _load(stage_root / "supply-chain/license-verdict.json")["release_qualification"]
        == "BLOCKED"
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode == 0, validated.stderr
    validated_against_input = _validate_stage(stage_root, integration_lock=lock_path)
    assert validated_against_input.returncode == 0, validated_against_input.stderr


def test_validate_only_rejects_build_identity_metadata_falsification(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "metadata-lock.json"
    lock_path.write_bytes(_locally_bound_test_lock(tmp_path, "metadata"))
    stage_root = tmp_path / "metadata-stage" / PLUGIN_NAME
    result = _stage(stage_root, integration_lock=lock_path)
    assert result.returncode == 0, result.stderr

    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    identity["evidence"]["pre_vendor"]["sha256"] = "1" * 64
    _write_pretty(identity_path, identity)
    _rebind_inventory(stage_root, "share/arw/build-identity.json")

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "evidence.pre_vendor" in validated.stderr


@pytest.mark.parametrize(
    "relative",
    ("supply-chain/integration-lock.json", "SBOM.cdx.json"),
)
def test_validate_only_rejects_lock_or_augmented_sbom_tamper(
    tmp_path: Path, relative: str
) -> None:
    lock_path = tmp_path / "qualification-lock.json"
    lock_path.write_bytes(
        _locally_bound_test_lock(tmp_path, relative.replace("/", "-"))
    )
    stage_root = tmp_path / relative.replace("/", "-") / PLUGIN_NAME
    result = _stage(stage_root, integration_lock=lock_path)
    assert result.returncode == 0, result.stderr

    target = stage_root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "digest mismatch" in validated.stderr


def test_validate_only_rejects_reformatted_sbom_after_identity_rebind(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "reformatted-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    sbom_path = stage_root / "SBOM.cdx.json"
    sbom_path.write_text(json.dumps(_load(sbom_path)) + "\n", encoding="utf-8")
    declaration_path = stage_root / "supply-chain/use-distribution.json"
    declaration = _load(declaration_path)
    sbom_row = next(
        row for row in declaration["evidence_hashes"] if row["path"] == "SBOM.cdx.json"
    )
    sbom_row["sha256"] = _sha256(sbom_path)
    _write_pretty(declaration_path, declaration)
    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    payloads["SBOM.cdx.json"]["sha256"] = _sha256(sbom_path)
    payloads["supply-chain/use-distribution.json"]["sha256"] = _sha256(declaration_path)
    _write_pretty(identity_path, identity)
    _rebind_inventory(
        stage_root,
        "SBOM.cdx.json",
        "supply-chain/use-distribution.json",
        "share/arw/build-identity.json",
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "staged SBOM bytes are not canonical" in validated.stderr


def test_stage_rejects_noncanonical_integration_lock_bytes(tmp_path: Path) -> None:
    lock_path = tmp_path / "noncanonical-lock.json"
    lock_path.write_bytes(_locally_bound_test_lock(tmp_path, "noncanonical") + b"\n")
    stage_root = tmp_path / "rejected-stage" / PLUGIN_NAME
    result = _stage(stage_root, integration_lock=lock_path)
    assert result.returncode != 0
    assert "not canonical JSON" in result.stderr


@pytest.mark.parametrize(
    ("drift", "expected_error"),
    (
        ("cachebuster", "does not bind the staged ARW runtime"),
        ("stage-identity", "does not bind the staged content-tree identity"),
        ("ars-binding", "does not bind the staged ARS bundle"),
    ),
)
def test_stage_rejects_live_payload_drift_against_lock(
    tmp_path: Path, drift: str, expected_error: str
) -> None:
    lock_path = tmp_path / f"{drift}-lock.json"
    lock_bytes = _locally_bound_test_lock(tmp_path, drift)
    if drift in {"stage-identity", "ars-binding"}:
        payload = json.loads(lock_bytes)
        if drift == "stage-identity":
            payload["hook"]["stage_sha256"] = "0" * 64
        else:
            payload["ars"]["adapter_tree_sha256"] = "0" * 64
        lock_bytes = canonical_json_bytes(payload)
    lock_path.write_bytes(lock_bytes)
    stage_root = tmp_path / f"{drift}-stage" / PLUGIN_NAME

    result = _stage(
        stage_root,
        integration_lock=lock_path,
        cachebuster="must-drift" if drift == "cachebuster" else None,
    )
    assert result.returncode != 0
    assert expected_error in result.stderr


@pytest.mark.parametrize(
    ("drift", "expected_error"),
    (
        ("stage-identity", "does not bind the staged content-tree identity"),
        ("ars-binding", "does not bind the staged ARS bundle"),
    ),
)
def test_validate_only_recomputes_local_lock_bindings(
    tmp_path: Path, drift: str, expected_error: str
) -> None:
    lock_path = tmp_path / "qualification-lock.json"
    lock_path.write_bytes(_locally_bound_test_lock(tmp_path, "recheck"))
    stage_root = tmp_path / "recheck-stage" / PLUGIN_NAME
    result = _stage(stage_root, integration_lock=lock_path)
    assert result.returncode == 0, result.stderr

    staged_lock = stage_root / "supply-chain/integration-lock.json"
    lock_payload = _load(staged_lock)
    if drift == "stage-identity":
        lock_payload["hook"]["stage_sha256"] = "0" * 64
    else:
        lock_payload["ars"]["adapter_tree_sha256"] = "0" * 64
    staged_lock.write_bytes(canonical_json_bytes(lock_payload))

    sbom_path = stage_root / "SBOM.cdx.json"
    sbom = _load(sbom_path)
    lock_component = next(
        item
        for item in sbom["components"]
        if item["bom-ref"] == "artifact:supply-chain/integration-lock.json"
    )
    lock_component["hashes"][0]["content"] = _sha256(staged_lock)
    _write_pretty(sbom_path, sbom)

    identity_path = stage_root / "share/arw/build-identity.json"
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    payloads["supply-chain/integration-lock.json"]["sha256"] = _sha256(staged_lock)
    payloads["SBOM.cdx.json"]["sha256"] = _sha256(sbom_path)
    _write_pretty(identity_path, identity)
    _rebind_inventory(
        stage_root,
        "supply-chain/integration-lock.json",
        "SBOM.cdx.json",
        "share/arw/build-identity.json",
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert expected_error in validated.stderr


def test_validate_only_rejects_duplicate_binding_records(tmp_path: Path) -> None:
    stage_root = tmp_path / "duplicate-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    sbom_path = stage_root / "SBOM.cdx.json"
    identity_path = stage_root / "share/arw/build-identity.json"
    inventory_path = stage_root / "supply-chain/stage-inventory.json"
    declaration_path = stage_root / "supply-chain/use-distribution.json"
    original_sbom = sbom_path.read_bytes()
    original_identity = identity_path.read_bytes()
    original_inventory = inventory_path.read_bytes()
    original_declaration = declaration_path.read_bytes()

    sbom = _load(sbom_path)
    sbom["components"].append(dict(sbom["components"][0]))
    _write_pretty(sbom_path, sbom)
    declaration = _load(declaration_path)
    sbom_row = next(
        row for row in declaration["evidence_hashes"] if row["path"] == "SBOM.cdx.json"
    )
    sbom_row["sha256"] = _sha256(sbom_path)
    _write_pretty(declaration_path, declaration)
    identity = _load(identity_path)
    payloads = {item["path"]: item for item in identity["staged_payloads"]}
    payloads["SBOM.cdx.json"]["sha256"] = _sha256(sbom_path)
    payloads["supply-chain/use-distribution.json"]["sha256"] = _sha256(declaration_path)
    _write_pretty(identity_path, identity)
    _rebind_inventory(
        stage_root,
        "SBOM.cdx.json",
        "supply-chain/use-distribution.json",
        "share/arw/build-identity.json",
    )
    duplicate_sbom = _validate_stage(stage_root)
    assert duplicate_sbom.returncode != 0
    assert "duplicate component references" in duplicate_sbom.stderr

    sbom_path.write_bytes(original_sbom)
    identity_path.write_bytes(original_identity)
    inventory_path.write_bytes(original_inventory)
    declaration_path.write_bytes(original_declaration)
    identity = _load(identity_path)
    identity["staged_payloads"].append(dict(identity["staged_payloads"][0]))
    _write_pretty(identity_path, identity)
    _rebind_inventory(stage_root, "share/arw/build-identity.json")
    duplicate_payload = _validate_stage(stage_root)
    assert duplicate_payload.returncode != 0
    assert "duplicate staged payload paths" in duplicate_payload.stderr


# ---------------------------------------------------------------------------
# Phase 1 evidence staging tests: the producer MUST copy the original
# ``build/evidence/phase-01`` surfaces into ``share/arw/evidence`` so the
# installed verifier never has to read the original tree.
# ---------------------------------------------------------------------------


EVIDENCE_STAGED_PATHS = (
    "share/arw/evidence/pre_vendor.json",
    "share/arw/evidence/legal.json",
    "share/arw/evidence/upstream.json",
    "share/arw/evidence/asan_ubsan.json",
    "share/arw/evidence/tsan.json",
)


def test_staged_evidence_files_exist_with_pass_qualification(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "evidence-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    for relative in EVIDENCE_STAGED_PATHS:
        staged_path = stage_root / relative
        assert staged_path.is_file(), f"missing staged evidence: {relative}"
        payload = json.loads(staged_path.read_text(encoding="utf-8"))
        assert payload["technical_qualification"] == "PASS", (
            f"staged evidence missing PASS semantic: {relative}"
        )


def test_build_identity_evidence_block_points_at_staged_copies(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "evidence-identity-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    identity = _load(stage_root / "share/arw/build-identity.json")
    evidence = identity["evidence"]
    for label, relative in zip(
        ("pre_vendor", "legal", "upstream", "asan_ubsan", "tsan"),
        EVIDENCE_STAGED_PATHS,
    ):
        entry = evidence[label]
        assert entry["path"] == relative, (
            f"evidence.{label}.path drifts from staged copy: {entry['path']}"
        )
        assert entry["sha256"] == _sha256(stage_root / relative), (
            f"evidence.{label}.sha256 drifts from staged copy bytes"
        )


def test_validate_only_rejects_staged_evidence_qualification_drift(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "evidence-drift-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    target = stage_root / "share/arw/evidence/upstream.json"
    payload = _load(target)
    payload["technical_qualification"] = "BLOCKED"
    _write_pretty(target, payload)
    identity = _load(stage_root / "share/arw/build-identity.json")
    identity["evidence"]["upstream"]["sha256"] = _sha256(target)
    # Update staged_payloads for both files so the audit manifest gate does
    # not fail before the identity verifier has a chance to run.
    for entry in identity["staged_payloads"]:
        if entry["path"] == "share/arw/evidence/upstream.json":
            entry["sha256"] = _sha256(target)
    _write_pretty(stage_root / "share/arw/build-identity.json", identity)
    for entry in identity["staged_payloads"]:
        if entry["path"] == "share/arw/build-identity.json":
            entry["sha256"] = _sha256(stage_root / "share/arw/build-identity.json")
    _write_pretty(stage_root / "share/arw/build-identity.json", identity)
    _rebind_inventory(
        stage_root,
        "share/arw/evidence/upstream.json",
        "share/arw/build-identity.json",
    )

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "evidence.upstream" in validated.stderr


def test_validate_only_rejects_staged_evidence_path_redirect(
    tmp_path: Path,
) -> None:
    stage_root = tmp_path / "evidence-redirect-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    contracts_path = stage_root / "share/arw/file-contracts.h"
    contracts_digest = _sha256(contracts_path)

    identity = _load(stage_root / "share/arw/build-identity.json")
    identity["evidence"]["pre_vendor"] = {
        "path": "share/arw/file-contracts.h",
        "sha256": contracts_digest,
    }
    _write_pretty(stage_root / "share/arw/build-identity.json", identity)
    _rebind_inventory(stage_root, "share/arw/build-identity.json")

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "pre_vendor" in validated.stderr


def test_validate_only_rejects_whole_header_alias_on_contract_sha256(
    tmp_path: Path,
) -> None:
    """RED: validate-only must reject contract_sha256 rebound to whole-header digest."""

    stage_root = tmp_path / "header-alias-stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    contracts_path = stage_root / "share/arw/file-contracts.h"
    whole_header_digest = _sha256(contracts_path)

    identity = _load(stage_root / "share/arw/build-identity.json")
    identity["file_contract"]["contract_sha256"] = whole_header_digest
    _write_pretty(stage_root / "share/arw/build-identity.json", identity)
    _rebind_inventory(stage_root, "share/arw/build-identity.json")

    validated = _validate_stage(stage_root)
    assert validated.returncode != 0
    assert "embedded ARW_FILES_CONTRACT_SHA256" in validated.stderr
