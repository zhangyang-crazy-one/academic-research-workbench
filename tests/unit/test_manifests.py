from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def test_artifact_manifest_has_canonical_content_address(tmp_path: Path) -> None:
    from arw.manifests import install_artifact_manifest, manifest_bytes_and_sha256
    from arw.models import ArtifactManifest
    from arw.schema_registry import validate_instance

    root = tmp_path / "run"
    root.mkdir()
    manifest = ArtifactManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000051",
            "artifact_id": "artifact.figure-001",
            "artifact_kind": "figure",
            "media_type": "image/png",
            "content_path": "outputs/figure.png",
            "content_sha256": "a" * 64,
            "producer_id": "parent.runtime",
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": ["b" * 64],
            "created_at": "2026-07-13T03:00:00Z",
        }
    )
    canonical, digest = manifest_bytes_and_sha256(manifest)
    validate_instance(
        "artifact-manifest.schema.json",
        manifest.model_dump(mode="json", exclude_none=True),
    )
    installed = install_artifact_manifest(root, manifest)
    assert installed == root / "manifests" / "artifacts" / "sha256" / f"{digest}.json"
    assert installed.read_bytes() == canonical
    assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest
    assert install_artifact_manifest(root, manifest) == installed


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt", "a/../outside.txt"])
def test_content_validation_rejects_non_normalized_paths(tmp_path: Path, path: str) -> None:
    from arw.manifests import ManifestError, validate_content_file

    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(ManifestError):
        validate_content_file(root, path, "0" * 64)


def test_content_validation_rejects_symlink_and_digest_drift(tmp_path: Path) -> None:
    from arw.manifests import ManifestError, validate_content_file

    root = tmp_path / "run"
    content = root / "outputs" / "result.txt"
    content.parent.mkdir(parents=True)
    content.write_text("accepted bytes\n", encoding="utf-8")
    expected = hashlib.sha256(content.read_bytes()).hexdigest()
    assert validate_content_file(root, "outputs/result.txt", expected) == content
    with pytest.raises(ManifestError, match="digest"):
        validate_content_file(root, "outputs/result.txt", "f" * 64)
    link = root / "outputs" / "linked.txt"
    link.symlink_to(content)
    with pytest.raises(ManifestError, match="symlink"):
        validate_content_file(root, "outputs/linked.txt", expected)
