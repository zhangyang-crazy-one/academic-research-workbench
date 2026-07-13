"""Immutable content-addressed artifact and Material Passport storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import ArtifactManifest, StrictModel


class ManifestError(RuntimeError):
    """Manifest bytes or their referenced content are unsafe or inconsistent."""


ManifestModel = TypeVar("ManifestModel", bound=StrictModel)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def manifest_bytes_and_sha256(manifest: StrictModel) -> tuple[bytes, str]:
    value = canonical_json_bytes(manifest.model_dump(mode="json", exclude_none=True))
    return value, sha256_hex(value)


def validate_content_file(root: Path, relative: str, expected_sha256: str) -> Path:
    path = PurePosixPath(relative)
    if (
        not relative
        or "\x00" in relative
        or "\\" in relative
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ManifestError("content path must be normalized and relative")
    root = root.resolve()
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ManifestError("content path must not contain a symlink")
    try:
        resolved = cursor.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as error:
        raise ManifestError(f"artifact content is unavailable: {error}") from error
    if not resolved.is_relative_to(root) or not stat.S_ISREG(mode):
        raise ManifestError("artifact content must be a regular file under the run root")
    if sha256_hex(resolved.read_bytes()) != expected_sha256:
        raise ManifestError("artifact content digest mismatch")
    return resolved


def _install(root: Path, relative_store: Path, manifest: StrictModel) -> Path:
    value, digest = manifest_bytes_and_sha256(manifest)
    store = root / relative_store
    store.mkdir(parents=True, exist_ok=True)
    target = store / f"{digest}.json"
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != value:
            raise ManifestError("content-address collision or unsafe manifest path")
        return target
    temporary = store / f".{digest}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != value:
                raise ManifestError("content-address collision during publication")
        _fsync_directory(store)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def install_artifact_manifest(root: Path, manifest: ArtifactManifest) -> Path:
    return _install(root, Path("manifests/artifacts/sha256"), manifest)


def _load(path: Path, model: type[ManifestModel]) -> ManifestModel:
    if path.is_symlink() or not path.is_file():
        raise ManifestError("manifest path is missing or unsafe")
    try:
        raw = path.read_bytes()
        value = strict_json_loads(raw)
        manifest = model.model_validate(value)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise ManifestError(f"manifest is invalid: {error}") from error
    canonical, digest = manifest_bytes_and_sha256(manifest)
    if raw != canonical or path.name != f"{digest}.json":
        raise ManifestError("manifest bytes or content address are invalid")
    return manifest


def load_artifact_manifest(root: Path, digest: str) -> ArtifactManifest:
    return _load(root / "manifests/artifacts/sha256" / f"{digest}.json", ArtifactManifest)
