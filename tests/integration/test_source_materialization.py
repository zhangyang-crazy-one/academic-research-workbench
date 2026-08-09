from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import jsonschema


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PATCH_SHA256 = "dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a"
PHASE3_PATCH_SHA256 = "12676a7b619981f4140c2f922bfc0fd90b1bdd0f75b0da04ed00e78840da9dfc"
EXPECTED_REVISIONS = {
    "academic-research-skills": "5d9b1f288457a3b2b2f1df1e915c883e36ea9a58",
    "experiment-agent": "e291e7dc7ca268b2de7e1a9cf23bc2eef5dc0651",
    "file-base": "ee68144af5453addda995a27cce8142999f318fb",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], cwd: Path = REPOSITORY_ROOT) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1", "PIP_NO_INDEX": "1"})
    return subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True, check=False)


def _manifest() -> dict[str, object]:
    manifest_path = REPOSITORY_ROOT / "vendor/source-manifest.json"
    assert manifest_path.is_file(), "source manifest is absent"
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/source-manifest.schema.json").read_text(encoding="utf-8")
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    return payload


def test_source_work_area_is_ignored_and_materializer_is_available() -> None:
    materializer = REPOSITORY_ROOT / "scripts/materialize-sources"
    assert materializer.is_file() and os.access(materializer, os.X_OK)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "vendor/sources/file-base/LICENSE"],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "vendor/sources/file-base/LICENSE"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tracked.returncode != 0, tracked.stdout


def test_exact_snapshots_patch_and_canonical_license_paths_are_materialized() -> None:
    manifest = _manifest()
    components = {item["id"]: item for item in manifest["components"]}
    assert set(components) == set(EXPECTED_REVISIONS)
    for component_id, revision in EXPECTED_REVISIONS.items():
        component = components[component_id]
        assert component["revision"] == revision
        source = REPOSITORY_ROOT / component["source_path"]
        assert source.is_dir() and not source.is_symlink()
        for license_record in component["licenses"]:
            license_path = REPOSITORY_ROOT / license_record["path"]
            assert license_path.is_file() and _sha256(license_path) == license_record["sha256"]

    assert components["academic-research-skills"]["licenses"][0]["path"] == (
        "vendor/sources/academic-research-skills/LICENSE"
    )
    assert components["experiment-agent"]["licenses"][0]["path"] == (
        "vendor/sources/experiment-agent/LICENSE"
    )
    assert components["file-base"]["licenses"][0]["path"] == "vendor/sources/file-base/LICENSE"

    patches = manifest["patches"]
    assert [patch["order"] for patch in patches] == list(range(1, len(patches) + 1))
    assert patches[0]["path"] == "vendor/patches/file-base/0001-file-base-server-name.patch"
    assert patches[0]["sha256"] == PATCH_SHA256
    assert _sha256(REPOSITORY_ROOT / patches[0]["path"]) == PATCH_SHA256
    assert patches[2]["path"] == "vendor/patches/file-base/0003-phase3-generation-builder.patch"
    assert patches[2]["sha256"] == PHASE3_PATCH_SHA256
    assert _sha256(REPOSITORY_ROOT / patches[2]["path"]) == PHASE3_PATCH_SHA256


def test_materializer_tree_digest_uses_the_manifest_wire_encoding() -> None:
    """The online materializer must agree with the offline verifier byte-for-byte."""

    loader = importlib.machinery.SourceFileLoader(
        "arw_materialize_sources", str(REPOSITORY_ROOT / "scripts/materialize-sources")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

    manifest = _manifest()
    for component in manifest["components"]:
        source = REPOSITORY_ROOT / component["source_path"]
        assert module.tree_digest(source) == component["tree_sha256"]


def test_network_denied_verification_retains_namespace_and_syscall_evidence(tmp_path: Path) -> None:
    offline = REPOSITORY_ROOT / "scripts/offline-exec"
    verifier = REPOSITORY_ROOT / "scripts/verify-sources"
    assert offline.is_file() and os.access(offline, os.X_OK)
    assert verifier.is_file() and os.access(verifier, os.X_OK)
    evidence = tmp_path / "verify-evidence"
    result = _run([str(offline), "--evidence-root", str(evidence), str(verifier)])
    assert result.returncode == 0, result.stderr

    verdict = json.loads((evidence / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["technical_qualification"] == "PASS"
    assert verdict["network_namespace_denied"] is True
    assert verdict["strace_network_audit"] is True
    assert verdict["network_syscall_attempts"] == []
    assert (evidence / "network.strace").is_file()
    assert (evidence / "stdout.log").is_file()
    assert (evidence / "stderr.log").is_file()


def test_offline_runner_rejects_network_capable_commands(tmp_path: Path) -> None:
    offline = REPOSITORY_ROOT / "scripts/offline-exec"
    assert offline.is_file() and os.access(offline, os.X_OK)
    evidence = tmp_path / "network-attempt"
    result = _run(
        [
            str(offline),
            "--evidence-root",
            str(evidence),
            "python3",
            "-c",
            "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
        ]
    )
    assert result.returncode != 0
    verdict = json.loads((evidence / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["technical_qualification"] == "FAIL"
    assert verdict["network_syscall_attempts"]
    assert any("AF_INET" in attempt for attempt in verdict["network_syscall_attempts"])
