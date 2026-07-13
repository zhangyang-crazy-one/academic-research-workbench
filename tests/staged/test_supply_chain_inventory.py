from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


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
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    assert path.is_file(), f"required inventory file is absent: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _stage(stage_root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1", "PIP_NO_INDEX": "1"})
    return subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/stage-plugin"),
            "--clean",
            "--stage-root",
            str(stage_root),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_sbom_covers_frozen_python_wheels_patches_native_and_source_components() -> None:
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


def test_exact_stage_contains_inventory_covered_legal_outputs(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    result = _stage(stage_root)
    assert result.returncode == 0, result.stderr

    actual = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file()
    }
    assert LEGAL_FILES <= actual
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

