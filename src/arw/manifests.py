"""Immutable content-addressed artifact and Material Passport storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import (
    ArtifactAcceptedPayload,
    ArtifactManifest,
    CanonicalEvent,
    MaterialPassport,
    PassportAcceptedPayload,
    PassportAttemptSnapshot,
    PassportDecisionSnapshot,
    PassportPointer,
    StrictModel,
)
from arw.reducer import RuntimeState


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
    root = root.resolve()
    store = root
    for part in relative_store.parts:
        store = store / part
        if store.is_symlink():
            raise ManifestError("manifest store path must not contain symlinks")
        if store.exists() and not store.is_dir():
            raise ManifestError("manifest store path contains a non-directory")
        if not store.exists():
            store.mkdir()
            _fsync_directory(store.parent)
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


def install_material_passport(root: Path, passport: MaterialPassport) -> Path:
    return _install(root, Path("passports/sha256"), passport)


def load_material_passport(root: Path, digest: str) -> MaterialPassport:
    return _load(root / "passports/sha256" / f"{digest}.json", MaterialPassport)


def write_passport_pointer(root: Path, pointer: PassportPointer) -> Path:
    root = root.resolve()
    target = root / "passport.json"
    value = canonical_json_bytes(pointer.model_dump(mode="json"))
    temporary = root / f".passport.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def validate_accepted_event_manifests(
    root: Path, events: tuple[CanonicalEvent, ...] | list[CanonicalEvent]
) -> None:
    """Verify every immutable manifest selected by an accepted event."""

    for event in events:
        if event.event_type == "artifact.accepted":
            assert isinstance(event.payload, ArtifactAcceptedPayload)
            manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
            if (
                manifest.run_id != event.run_id
                or manifest.artifact_id != event.payload.artifact_id
                or manifest.content_sha256 != event.payload.artifact_sha256
                or manifest.attempt_id != event.payload.attempt_id
            ):
                raise ManifestError("artifact acceptance event differs from its manifest")
        elif event.event_type == "passport.accepted":
            assert isinstance(event.payload, PassportAcceptedPayload)
            passport = load_material_passport(root, event.payload.passport_sha256)
            if (
                passport.run_id != event.run_id
                or passport.based_on_revision != event.payload.based_on_revision
                or passport.stage != event.payload.stage
                or passport.checkpoint_kind != event.payload.checkpoint_kind
                or passport.parent_passport_sha256
                != event.payload.parent_passport_sha256
                or passport.supersedes_passport_sha256
                != event.payload.supersedes_passport_sha256
                or passport.fresh_until != event.payload.fresh_until
            ):
                raise ManifestError("Passport acceptance event differs from its manifest")


def validate_event_manifest_semantics(
    root: Path,
    event: CanonicalEvent,
    state_before: RuntimeState,
) -> None:
    """Bind one selected manifest to the complete accepted state before its event."""

    from arw.workflows import require_workflow

    if event.event_type == "artifact.accepted":
        assert isinstance(event.payload, ArtifactAcceptedPayload)
        manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
        if manifest.created_at != event.occurred_at or manifest.producer_id != event.actor_id:
            raise ManifestError("artifact manifest producer or timestamp differs from its event")
        if manifest.attempt_id is None:
            if manifest.base_revision != state_before.accepted_revision:
                raise ManifestError("artifact manifest base revision is not current")
            known_hashes = {
                state_before.ledger_head_sha256,
                *state_before.accepted_artifact_manifest_sha256,
                *state_before.accepted_passport_sha256,
            }
            if any(value not in known_hashes for value in manifest.consumed_sha256):
                raise ManifestError("artifact manifest consumes an unknown hash")
        else:
            attempt = next(
                (
                    item
                    for item in state_before.active_attempts
                    if item.attempt_id == manifest.attempt_id
                ),
                None,
            )
            if (
                attempt is None
                or manifest.base_revision != attempt.base_revision
                or manifest.consumed_sha256 != attempt.consumed_sha256
            ):
                raise ManifestError("artifact manifest does not match its active attempt")
        return

    if event.event_type != "passport.accepted":
        return
    assert isinstance(event.payload, PassportAcceptedPayload)
    passport = load_material_passport(root, event.payload.passport_sha256)
    workflow = require_workflow(state_before.workflow_definition_id)
    expected_decisions = [
        PassportDecisionSnapshot.model_validate(item.model_dump(mode="json"))
        for item in state_before.pending_human_decisions
    ]
    expected_attempts = [
        PassportAttemptSnapshot.model_validate(item.model_dump(mode="json"))
        for item in state_before.active_attempts
    ]
    checks = (
        passport.workflow_definition_id == state_before.workflow_definition_id,
        passport.workflow_definition_sha256 == workflow.sha256,
        passport.based_on_revision == state_before.accepted_revision,
        passport.ledger_head_sha256 == state_before.ledger_head_sha256,
        passport.stage == state_before.stage,
        passport.parent_passport_sha256 == state_before.current_passport_sha256,
        passport.supersedes_passport_sha256 == state_before.current_passport_sha256,
        passport.accepted_artifact_manifest_sha256
        == state_before.accepted_artifact_manifest_sha256,
        passport.pending_human_decisions == expected_decisions,
        passport.active_attempts == expected_attempts,
        passport.created_at == event.occurred_at,
        passport.created_by == event.actor_id,
    )
    if not all(checks):
        raise ManifestError("Passport manifest does not bind the accepted checkpoint state")
