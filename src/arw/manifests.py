"""Immutable content-addressed artifact and Material Passport storage."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, TypeVar

from pydantic import TypeAdapter, ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import (
    ArtifactAcceptedPayload,
    ArtifactManifest,
    CanonicalEvent,
    MaterialPassport,
    PassportAcceptedPayload,
    PassportAttemptSnapshot,
    PassportDecisionSnapshot,
    PassportPointer,
    Sha256,
    StableRuntimeId,
    StrictModel,
)
from arw.reducer import RuntimeState
from arw.orchestration_models import (
    AttemptDescriptor,
    ImmutableAssignment,
    MAX_OUTPUT_BYTES,
    ProposalValidationError,
    WorkerProposal,
    canonical_orchestration_model_bytes,
    validate_worker_proposal_bytes,
)


class ManifestError(RuntimeError):
    """Manifest bytes or their referenced content are unsafe or inconsistent."""


ManifestModel = TypeVar("ManifestModel", bound=StrictModel)

MAX_PROPOSAL_BYTES = 1_048_576

_STABLE_RUNTIME_ID = TypeAdapter(StableRuntimeId)


class RawProposalEvidence(StrictModel):
    """A retained raw proposal plus its parent-validation result."""

    schema_version: Literal["arw.raw-proposal-evidence.v1"] = "arw.raw-proposal-evidence.v1"
    attempt_id: str
    assignment_id: str
    relative_path: str
    sha256: Sha256
    byte_count: int
    evidence_path: Path
    raw_bytes: bytes
    proposal: WorkerProposal


def _safe_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ManifestError("run root must be a real directory")
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ManifestError(f"run root is unavailable: {error}") from error
    if resolved.is_symlink():
        raise ManifestError("run root must not resolve through a symlink")
    return resolved


def _safe_directory(root: Path, parts: tuple[str, ...], *, create: bool) -> Path:
    cursor = _safe_root(root)
    for part in parts:
        if not part or part in {".", ".."} or "/" in part or "\\" in part:
            raise ManifestError("manifest path component is not normalized")
        cursor = cursor / part
        if cursor.is_symlink():
            raise ManifestError("manifest path must not contain symlinks")
        if cursor.exists():
            if not cursor.is_dir():
                raise ManifestError("manifest path contains a non-directory")
        elif create:
            try:
                cursor.mkdir()
                _fsync_directory(cursor.parent)
            except OSError as error:
                raise ManifestError(f"cannot create manifest directory: {error}") from error
        else:
            raise ManifestError("manifest directory is missing")
    return cursor


def _write_once(path: Path, value: bytes) -> Path:
    if path.is_symlink():
        raise ManifestError("immutable manifest path must not be a symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != value:
            raise ManifestError("immutable manifest replacement or content collision")
        return path
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != value:
                raise ManifestError("immutable manifest replacement or content collision")
        _fsync_directory(path.parent)
        return path
    except ManifestError:
        raise
    except OSError as error:
        raise ManifestError(f"cannot publish immutable manifest: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def _safe_identifier(value: str, *, label: str) -> str:
    try:
        return _STABLE_RUNTIME_ID.validate_python(value)
    except ValidationError as error:
        raise ManifestError(f"{label} is not a safe runtime identifier") from error


def install_assignment_manifest(root: Path, assignment: ImmutableAssignment) -> Path:
    """Publish one canonical assignment exactly once as a direct parent file."""

    value = canonical_orchestration_model_bytes(assignment)
    directory = _safe_directory(root, ("assignments",), create=True)
    assignment_id = _safe_identifier(assignment.assignment_id, label="assignment ID")
    return _write_once(directory / f"{assignment_id}.json", value)


def load_assignment_manifest(root: Path, assignment_id: str) -> ImmutableAssignment:
    safe_assignment_id = _safe_identifier(assignment_id, label="assignment ID")
    directory = _safe_directory(root, ("assignments",), create=False)
    path = directory / f"{safe_assignment_id}.json"
    if path.is_symlink() or not path.is_file():
        raise ManifestError("assignment manifest is missing or unsafe")
    try:
        assignment = ImmutableAssignment.model_validate(strict_json_loads(path.read_bytes()))
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise ManifestError(f"assignment manifest is invalid: {error}") from error
    canonical = canonical_orchestration_model_bytes(assignment)
    if path.read_bytes() != canonical:
        raise ManifestError("assignment manifest is not canonical")
    return assignment


def materialize_attempt_tree(
    root: Path, assignment: ImmutableAssignment, attempt: AttemptDescriptor
) -> Path:
    """Create the immutable assignment snapshot and bounded attempt directories."""

    if attempt.assignment_id != assignment.assignment_id:
        raise ManifestError("attempt does not belong to assignment")
    installed = install_assignment_manifest(root, assignment)
    attempt_root = _safe_directory(root, ("attempts", attempt.attempt_id), create=True)
    _safe_directory(root, ("attempts", attempt.attempt_id, "scratch"), create=True)
    _safe_directory(root, ("attempts", attempt.attempt_id, "result"), create=True)
    _safe_directory(root, ("attempts", attempt.attempt_id, "observations"), create=True)
    assignment_snapshot = _write_once(
        attempt_root / "assignment.json", installed.read_bytes()
    )
    _write_once(
        attempt_root / "attempt.json",
        canonical_orchestration_model_bytes(attempt),
    )
    return assignment_snapshot


def _read_direct_file(path: Path, *, max_bytes: int) -> bytes:
    if max_bytes < 1 or max_bytes > MAX_OUTPUT_BYTES:
        raise ManifestError("proposal byte limit is outside the frozen bounds")
    if path.is_symlink() or not path.exists():
        raise ManifestError("proposal path must be a direct regular file")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise ManifestError(f"proposal path cannot be opened safely: {error}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ManifestError("proposal path must be a direct regular file")
        if before.st_size > max_bytes:
            raise ManifestError("proposal exceeds the frozen byte limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > max_bytes or after.st_size != before.st_size:
            raise ManifestError("proposal changed or exceeds the frozen byte limit")
        try:
            live = os.stat(path, follow_symlinks=False)
        except OSError as error:
            raise ManifestError(f"proposal path was replaced: {error}") from error
        if live.st_ino != before.st_ino or live.st_dev != before.st_dev:
            raise ManifestError("proposal path was replaced during intake")
        return raw
    finally:
        os.close(descriptor)


def admit_raw_proposal(
    root: Path,
    *,
    assignment: ImmutableAssignment,
    attempt: AttemptDescriptor,
    max_bytes: int = MAX_PROPOSAL_BYTES,
    expected_sha256: str | None = None,
) -> RawProposalEvidence:
    """Read and retain one direct proposal file before parent admission."""

    if attempt.assignment_id != assignment.assignment_id:
        raise ManifestError("proposal attempt does not match assignment")
    _safe_directory(root, ("attempts", attempt.attempt_id), create=False)
    result_root = _safe_directory(root, ("attempts", attempt.attempt_id, "result"), create=False)
    proposal_path = result_root / "proposal.json"
    raw = _read_direct_file(proposal_path, max_bytes=max_bytes)
    digest = sha256_hex(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ManifestError("proposal bytes were replaced or digest does not match")
    evidence_root = _safe_directory(
        root, ("evidence", "raw-proposals", attempt.attempt_id), create=True
    )
    evidence_path = _write_once(evidence_root / f"{digest}.json", raw)
    try:
        proposal, validated_digest = validate_worker_proposal_bytes(
            raw, assignment=assignment, attempt=attempt
        )
    except (ProposalValidationError, OSError, UnicodeError, ValueError) as error:
        raise ManifestError(f"proposal evidence is not admissible: {error}") from error
    if validated_digest != digest:
        raise ManifestError("proposal digest changed during validation")
    return RawProposalEvidence(
        attempt_id=attempt.attempt_id,
        assignment_id=assignment.assignment_id,
        relative_path=f"attempts/{attempt.attempt_id}/result/proposal.json",
        sha256=digest,
        byte_count=len(raw),
        evidence_path=evidence_path,
        raw_bytes=raw,
        proposal=proposal,
    )


# Explicit aliases make the parent-facing vocabulary discoverable while
# retaining the install/load naming used by the earlier artifact helpers.
write_assignment_manifest = install_assignment_manifest
write_attempt_tree = materialize_attempt_tree
validate_raw_proposal = admit_raw_proposal


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
        PassportAttemptSnapshot(
            attempt_id=item.attempt_id,
            base_revision=item.base_revision,
            consumed_sha256=list(item.consumed_sha256),
        )
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
