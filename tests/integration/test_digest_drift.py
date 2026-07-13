from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


@pytest.fixture
def verification_root() -> Path:
    build_root = REPOSITORY_ROOT / "build"
    build_root.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="digest-candidate.", dir=build_root))
    try:
        for relative in (
            "schemas/v1/source-manifest.schema.json",
            "scripts/verify-sources",
            "uv.lock",
            "vendor/source-manifest.json",
            "vendor/python/wheelhouse.lock.json",
        ):
            source = REPOSITORY_ROOT / relative
            assert source.is_file(), f"required digest input is absent: {relative}"
            _copy_file(source, root / relative)

        for relative in (
            "vendor/sources",
            "vendor/patches",
            "vendor/python/wheelhouse",
        ):
            source = REPOSITORY_ROOT / relative
            assert source.is_dir(), f"required digest input is absent: {relative}"
            shutil.copytree(source, root / relative, copy_function=os.link, symlinks=True)

        manifest = json.loads((root / "vendor/source-manifest.json").read_text(encoding="utf-8"))
        receipt = REPOSITORY_ROOT / manifest["pre_vendor_receipt"]["path"]
        _copy_file(receipt, root / manifest["pre_vendor_receipt"]["path"])
        for artifact in manifest["declared_artifacts"]:
            source = REPOSITORY_ROOT / artifact["path"]
            if source.is_file():
                _copy_file(source, root / artifact["path"])
        yield root
    finally:
        shutil.rmtree(root)


def _mutate(path: Path) -> None:
    assert path.is_file(), f"mutation target missing: {path}"
    original = path.read_bytes()
    mode = path.stat().st_mode
    path.unlink()
    path.write_bytes(original + b"\nmutation\n")
    path.chmod(mode)


def _run_verifier(root: Path) -> subprocess.CompletedProcess[str]:
    environment = {"PATH": os.environ["PATH"], "PYTHONNOUSERSITE": "1"}
    return subprocess.run(
        [str(root / "scripts/verify-sources"), "--project-root", str(root)],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_each_digest_class_fails_before_staging(verification_root: Path) -> None:
    mutations = [
        ("source", "vendor/sources/academic-research-skills/README.md"),
        ("patch", "vendor/patches/file-base/0001-file-base-server-name.patch"),
        ("legal-receipt", "build/evidence/phase-01/pre-vendor-license/receipt.json"),
        ("legal-input", "vendor/sources/file-base/LICENSE"),
        ("lock", "uv.lock"),
        ("wheelhouse", "vendor/python/wheelhouse/pytest-9.1.1-py3-none-any.whl"),
        ("binary", ".file-base/bin/file-base"),
        ("artifact", "schemas/v1/source-manifest.schema.json"),
    ]
    staging_marker = verification_root / "build/stage-created"
    for digest_class, target in mutations:
        candidate = verification_root / target
        source = REPOSITORY_ROOT / target
        _mutate(candidate)
        result = _run_verifier(verification_root)
        assert result.returncode != 0, f"{digest_class} drift was accepted"
        assert digest_class in result.stderr, result.stderr
        assert not staging_marker.exists(), f"{digest_class} drift reached staging"
        candidate.unlink()
        _copy_file(source, candidate)
