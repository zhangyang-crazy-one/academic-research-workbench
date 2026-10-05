"""Host-independent verification of an installed ARW stage.

This verifies the live closed payload, source/build evidence, candidate wheel,
license inventory and SBOM. It deliberately does not confer execution-host
qualification; that remains the IntegrationLock verifier's responsibility.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.policy.core_stage_allowlist import (
    ARS_STAGE_TREE_SHA256,
    allowed_stage_path,
)
from arw.kernel.policy.integration_lock import (
    EXPECTED_LEGAL_BLOCKERS,
    EXPECTED_TECHNICAL_PROVENANCE_PATHS,
    FileBinding,
    IntegrationLockError,
    _bound_file,
    _technical_provenance_digest,
    _validate_bundled_ars,
    _validate_file_base,
    _zip_tree_sha256,
    validate_live_audit_manifests,
)


class CoreIntegrityError(ValueError):
    """The installed stage is missing or its declared bytes have drifted."""


def _object(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise CoreIntegrityError(f"missing or unsafe stage evidence: {relative}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as error:
        raise CoreIntegrityError(f"invalid stage evidence: {relative}") from error
    if not isinstance(value, dict):
        raise CoreIntegrityError(f"stage evidence must be an object: {relative}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_executing_wheel(stage_root: Path, wheel_relative: str) -> None:
    """Bind direct CLI/MCP imports to the verified first-party wheel bytes."""

    try:
        distribution = importlib.metadata.distribution("academic-research-workbench")
        package_root = Path(distribution.locate_file("arw")).resolve()
        if Path(__file__).resolve() != package_root / "kernel/policy/core_integrity.py":
            raise CoreIntegrityError("executing ARW module is not from the installed distribution")
        purelib = package_root.parent
        wheel_path = stage_root / wheel_relative
        expected: set[str] = set()
        with zipfile.ZipFile(wheel_path) as wheel:
            for member in wheel.infolist():
                if member.is_dir() or member.filename.endswith(".dist-info/RECORD"):
                    continue
                relative = Path(member.filename)
                target = purelib / relative
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or any(part.is_symlink() for part in (target, *target.parents) if part.is_relative_to(purelib))
                    or not target.is_file()
                    or target.read_bytes() != wheel.read(member)
                ):
                    raise CoreIntegrityError("executing ARW distribution differs from staged wheel")
                expected.add(relative.as_posix())
        for top in {name.split("/", 1)[0] for name in expected if "/" in name}:
            if top.endswith(".dist-info"):
                continue
            package = purelib / top
            if package.is_symlink():
                raise CoreIntegrityError("executing ARW package root is a symlink")
            for path in package.rglob("*"):
                if "__pycache__" in path.parts:
                    continue
                if path.is_symlink() or (path.is_file() and path.relative_to(purelib).as_posix() not in expected):
                    raise CoreIntegrityError("executing ARW package has undeclared files")
    except (OSError, ValueError, zipfile.BadZipFile, importlib.metadata.PackageNotFoundError) as error:
        if isinstance(error, CoreIntegrityError):
            raise
        raise CoreIntegrityError("executing ARW distribution cannot be bound to staged wheel") from error


def _verify_license_verdict(
    stage_root: Path, declaration: dict[str, Any], inventory: dict[str, Any]
) -> None:
    """Preserve blocked legal authority without pinning incidental unknown fields."""

    verdict = _object(stage_root, "supply-chain/license-verdict.json")
    if (
        verdict.get("schema_version") != "1.0.0"
        or verdict.get("technical_qualification") != "PASS"
        or verdict.get("release_qualification") != "BLOCKED"
        or verdict.get("use_distribution_path") != "supply-chain/use-distribution.json"
        or verdict.get("reason_codes") != list(EXPECTED_LEGAL_BLOCKERS)
        or verdict.get("private_repository_is_noncommercial_evidence") is not False
        or inventory.get("technical_qualification") != "PASS"
        or inventory.get("release_qualification") != "BLOCKED"
    ):
        raise CoreIntegrityError("license verdict does not preserve blocked release authority")
    expected_declaration_keys = {
        "accountable_approval", "distribution_class", "evidence_hashes",
        "intended_use", "permission_references",
        "private_repository_is_noncommercial_evidence", "repository_visibility",
        "schema_version",
    }
    if (
        set(declaration) != expected_declaration_keys
        or declaration.get("schema_version") != "1.0.0"
        or declaration.get("private_repository_is_noncommercial_evidence") is not False
        or not isinstance(declaration.get("permission_references"), list)
    ):
        raise CoreIntegrityError("license declaration shape is invalid")
    if (
        declaration.get("intended_use") != {"status": "unknown"}
        or declaration.get("distribution_class") != {"status": "unknown"}
        or declaration.get("accountable_approval") != {"status": "missing"}
        or declaration["permission_references"] != []
    ):
        raise CoreIntegrityError("license verdict blockers do not match declaration facts")
    components = inventory.get("component_licenses")
    if not isinstance(components, list) or not components:
        raise CoreIntegrityError("license component inventory is missing")
    expected_identity = {
        "academic-research-skills": ("CC-BY-NC-4.0", "vendor/sources/academic-research-skills/LICENSE", "LICENSES/academic-research-skills-CC-BY-NC-4.0.txt", "b3848009d12a173f549ef98d9ee486e64459e8eb5d9f895bff53782b4aa86d7c"),
        "experiment-agent": ("CC-BY-NC-4.0", "vendor/sources/experiment-agent/LICENSE", "LICENSES/experiment-agent-CC-BY-NC-4.0.txt", "f66a510318fa9c98534f64c844403bf54d9019613f5a818f9d92075b91133d25"),
        "file-base": ("MIT", "vendor/sources/file-base/LICENSE", "LICENSES/file-base-MIT.txt", "1f58f9911dc5e3bcb96de28bb28e7b6bb7eb323952d29569c5d7214a152146bb"),
    }
    if len(components) != len(expected_identity) or {r.get("component_id") for r in components if isinstance(r, dict)} != set(expected_identity):
        raise CoreIntegrityError("license component identities differ from protected sources")
    expected_components: list[dict[str, Any]] = []
    for record in components:
        if not isinstance(record, dict):
            raise CoreIntegrityError("license component inventory is malformed")
        relative = record.get("staged_path")
        component_id = record.get("component_id")
        if (record.get("license"), record.get("source_path"), relative, record.get("source_sha256")) != expected_identity[component_id]:
            raise CoreIntegrityError("license component identity differs from protected source")
        if record.get("staged_sha256") != record.get("source_sha256"):
            raise CoreIntegrityError("staged license differs from protected source")
        if not isinstance(relative, str) or not relative.startswith("LICENSES/") or ".." in Path(relative).parts:
            raise CoreIntegrityError("license file path is unsafe")
        if _digest(stage_root / relative) != record.get("staged_sha256"):
            raise CoreIntegrityError("staged license bytes differ from inventory")
        expected_components.append({
            **record,
            "release_status": "BLOCKED" if record.get("license") == "CC-BY-NC-4.0" else "SATISFIED",
        })
    if verdict.get("components") != expected_components:
        raise CoreIntegrityError("license verdict components differ from inventory")


def _structural_canary_closure(stage_root: Path, actual: set[str]) -> None:
    """Close embedded adapter evidence by references, ignoring host verdicts."""

    canary_names = {p for p in actual if p == "supply-chain/host-canary.json" or p.startswith("supply-chain/host-canary/")}
    roots = [p for p in ("supply-chain/host-canary/canary.json", "supply-chain/host-canary.json") if p in canary_names]
    if not canary_names:
        return
    if len(roots) != 1:
        raise CoreIntegrityError("embedded canary namespace lacks one entry document")
    entry = roots[0]
    evidence_root = (stage_root / entry).parent
    referenced = {entry}

    def object_at(path: Path) -> dict[str, Any]:
        value = _object(stage_root, path.relative_to(stage_root).as_posix())
        if path.read_bytes() != canonical_json_bytes(value):
            raise CoreIntegrityError("embedded adapter evidence is not canonical")
        return value

    def bound(row: object) -> Path:
        binding = FileBinding.model_validate(row, strict=True)
        target = _bound_file(evidence_root, binding)
        if not target.is_relative_to(stage_root):
            raise CoreIntegrityError("embedded adapter target escaped the stage")
        stage_relative = target.relative_to(stage_root).as_posix()
        if stage_relative in canary_names:
            referenced.add(stage_relative)
        return target

    canary = object_at(stage_root / entry)
    bundle_path = bound(canary.get("evidence_bundle"))
    bundle = object_at(bundle_path)
    if bundle_path.relative_to(stage_root).as_posix() not in canary_names:
        raise CoreIntegrityError("embedded adapter bundle escaped its namespace")
    canary_receipts = canary.get("fresh_home_receipts")
    bundle_receipts = bundle.get("fresh_home_receipts")
    classifications = bundle.get("hook_status_classifications")
    if (
        not isinstance(canary_receipts, list) or len(canary_receipts) != 3
        or not isinstance(bundle_receipts, list) or len(bundle_receipts) != 3
        or not isinstance(classifications, list) or len(classifications) != 5
    ):
        raise CoreIntegrityError("embedded adapter reference structure is incomplete")
    for row in canary_receipts:
        bound(row)
    for row in bundle_receipts:
        bound(row)
    for classification in classifications:
        if not isinstance(classification, dict):
            raise CoreIntegrityError("embedded adapter classification is malformed")
        parity = object_at(bound(classification.get("evidence")))
        if parity.get("official_hook_receipt") is not None:
            bound(parity["official_hook_receipt"])
    if referenced != canary_names:
        raise CoreIntegrityError("embedded adapter evidence contains an unreferenced file")


def verify_staged_core(stage_root: Path) -> dict[str, str]:
    """Return verified stage/wheel digests, or reject before any core operation.

    No Codex executable, version, canary, hook trust, model, or provider is
    inspected. The optional integration lock is treated as an inventoried
    payload; its authority is evaluated only by the legacy dispatch path.
    """

    if not stage_root.is_absolute() or stage_root.is_symlink() or not stage_root.is_dir():
        raise CoreIntegrityError("stage root must be a direct absolute directory")
    try:
        validate_live_audit_manifests(
            stage_root, verify_host_canary_closure=False
        )
        inventory = _object(stage_root, "supply-chain/stage-inventory.json")
        _structural_canary_closure(stage_root, set(inventory["files"]))
        identity = _object(stage_root, "share/arw/build-identity.json")
        wheel_binding = identity["runtime_artifact"]["first_party_wheel"]
        wheels = tuple(sorted((stage_root / "share/arw/wheels").glob("academic_research_workbench-*.whl")))
        if len(wheels) != 1 or wheels[0].is_symlink() or not wheels[0].is_file():
            raise CoreIntegrityError("stage requires one direct first-party wheel")
        wheel_path = wheels[0]
        wheel_sha256 = _digest(wheel_path)
        if wheel_binding["path"] != wheel_path.relative_to(stage_root).as_posix() or wheel_binding["sha256"] != wheel_sha256:
            raise CoreIntegrityError("build identity does not bind the staged wheel")
        _zip_tree_sha256(wheel_path)
        project = tomllib.loads((stage_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        if project["name"] != "academic-research-workbench":
            raise CoreIntegrityError("first-party package name differs")
        with zipfile.ZipFile(wheel_path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise CoreIntegrityError("wheel distribution metadata is ambiguous")
            metadata = archive.read(metadata_names[0]).decode("utf-8")
        if f"\nName: {project['name']}\n" not in f"\n{metadata}" or f"\nVersion: {project['version']}\n" not in f"\n{metadata}":
            raise CoreIntegrityError("wheel distribution metadata differs")
        unknown = [path for path in inventory["files"] if not allowed_stage_path(path, wheel_path.name)]
        if unknown:
            raise CoreIntegrityError(f"stage contains undeclared path: {unknown[0]}")
        source = _object(stage_root, "vendor/source-manifest.json")
        if _validate_bundled_ars(stage_root, source).adapter_tree_sha256 != ARS_STAGE_TREE_SHA256:
            raise CoreIntegrityError("bundled ARS source tree differs")
        _validate_file_base(stage_root, source)
        declaration = _object(stage_root, "supply-chain/use-distribution.json")
        evidence_hashes = declaration.get("evidence_hashes")
        if not isinstance(evidence_hashes, list) or {
            row.get("path") for row in evidence_hashes if isinstance(row, dict)
        } != EXPECTED_TECHNICAL_PROVENANCE_PATHS:
            raise CoreIntegrityError("technical provenance declaration path set differs")
        for row in evidence_hashes:
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "purpose", "sha256"}
                or row["purpose"] != "technical-provenance-only"
                or row["sha256"] != _technical_provenance_digest(stage_root, row["path"])
            ):
                raise CoreIntegrityError("technical provenance declaration digest differs")
        candidate = _object(stage_root, "share/arw/evidence/candidate-build.json")
        license_inventory = _object(stage_root, "share/arw/evidence/license-inventory.json")
        _verify_license_verdict(stage_root, declaration, license_inventory)
        sbom = _object(stage_root, "SBOM.cdx.json")
        if license_inventory.get("build_evidence", {}).get("sha256") != _digest(
            stage_root / "share/arw/evidence/candidate-build.json"
        ):
            raise CoreIntegrityError("license inventory does not bind candidate build")
        if (
            license_inventory.get("build_observation") != candidate.get("build")
            or license_inventory.get("runtime_resolution_environment")
            != candidate.get("runtime_resolution_environment")
        ):
            raise CoreIntegrityError("license inventory build observation differs")
        build = candidate.get("build")
        resolved = candidate.get("resolved_runtime_inventory")
        if not isinstance(build, dict) or not isinstance(build.get("inventory"), list) or not isinstance(resolved, list):
            raise CoreIntegrityError("candidate package inventory is missing")
        rows = [*build["inventory"], *resolved]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise CoreIntegrityError("candidate package inventory is malformed")
        packages = sorted(
            {(row["name"].lower(), row["version"]): row for row in rows}.values(),
            key=lambda row: (row["name"].lower(), row["version"]),
        )
        if license_inventory.get("python_packages_observed") != packages:
            raise CoreIntegrityError("license inventory package set differs")
        wheel = identity["runtime_artifact"]["first_party_wheel"]
        wheel_rows = [row for row in candidate.get("artifacts", []) if row.get("kind") == "wheel"]
        if (
            len(wheel_rows) != 1
            or wheel_rows[0].get("sha256") != wheel_sha256
            or wheel.get("sha256") != wheel_sha256
            or Path(wheel_rows[0].get("path", "")).name != Path(wheel["path"]).name
            or identity["runtime"]["build_interpreter"] != build["python"]["version"]
        ):
            raise CoreIntegrityError("candidate build does not bind staged wheel")
        first_party = license_inventory.get("first_party_wheel")
        if not isinstance(first_party, dict) or first_party.get("sha256") != wheel_sha256 or first_party.get("file") != Path(wheel["path"]).name:
            raise CoreIntegrityError("license inventory does not bind staged wheel")
        component_rows = sbom.get("components")
        if not isinstance(component_rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("bom-ref"), str) for row in component_rows):
            raise CoreIntegrityError("SBOM components are malformed")
        components = {row["bom-ref"]: row for row in component_rows}
        if len(components) != len(component_rows):
            raise CoreIntegrityError("SBOM component references duplicate")
        observed_python = {ref: item for ref, item in components.items() if ref.startswith("python:")}
        expected_python = {
            f"python:{row['name']}@{row['version']}": {
                "name": row["name"],
                "version": row["version"],
                "hashes": [{"alg": "SHA-256", "content": row["installed_content_sha256"]}],
                "licenses": [{"expression": row["license"]}],
            }
            for row in packages
        }
        if set(observed_python) != set(expected_python) or any(
            any(observed_python[ref].get(key) != value for key, value in expected.items())
            for ref, expected in expected_python.items()
        ):
            raise CoreIntegrityError("SBOM packages differ from candidate")
        lock_relative = "supply-chain/integration-lock.json"
        lock_ref = f"artifact:{lock_relative}"
        if (stage_root / lock_relative).is_file():
            expected_lock_component = {
                "bom-ref": lock_ref,
                "hashes": [{"alg": "SHA-256", "content": _digest(stage_root / lock_relative)}],
                "name": lock_relative,
                "type": "file",
                "version": "1",
            }
            if components.get(lock_ref) != expected_lock_component:
                raise CoreIntegrityError("SBOM does not bind integration lock bytes")
        elif lock_ref in components:
            raise CoreIntegrityError("SBOM claims an absent integration lock")
        return {
            "stage_inventory_sha256": _digest(stage_root / "supply-chain/stage-inventory.json"),
            "build_identity_sha256": _digest(stage_root / "share/arw/build-identity.json"),
            "first_party_wheel_sha256": wheel_sha256,
        }
    except (IntegrationLockError, OSError, KeyError, TypeError, IndexError, ValueError) as error:
        if isinstance(error, CoreIntegrityError):
            raise
        raise CoreIntegrityError(str(error)) from error


def installed_core_preflight() -> tuple[str, dict[str, str] | None]:
    """Check installed stage, or label an explicit editable checkout UNVERIFIED."""

    source_root = Path(__file__).resolve().parents[4]
    imported_checkout = (
        (source_root / "src/arw/kernel/policy/core_integrity.py").is_file()
        and (source_root / "pyproject.toml").is_file()
        and Path(__file__).resolve().is_relative_to(source_root / "src/arw")
        and not (source_root / "share/arw/wheels").exists()
    )
    root_value = os.environ.get("ARW_PLUGIN_ROOT")
    if imported_checkout and os.environ.get("ARW_RUNTIME_MODE") != "plugin" and (
        not root_value or not (Path(root_value) / "share/arw/wheels").exists()
    ):
        return "UNVERIFIED", None
    if not root_value:
        raise CoreIntegrityError("installed plugin root is not bound")
    root = Path(root_value)
    source_package = root / "src/arw"
    if (
        os.environ.get("ARW_RUNTIME_MODE") == "agent"
        and root.is_absolute()
        and not any(part.is_symlink() for part in (root, *root.parents))
        and source_package.is_dir()
        and not source_package.is_symlink()
        and (root / "pyproject.toml").is_file()
        and (root / ".git").exists()
        and Path(__file__).resolve().is_relative_to(source_package.resolve())
        and not (root / "share/arw/wheels").exists()
    ):
        return "UNVERIFIED", None
    digests = verify_staged_core(root)
    identity = _object(root, "share/arw/build-identity.json")
    _verify_executing_wheel(root, identity["runtime_artifact"]["first_party_wheel"]["path"])
    return "PASS", digests
