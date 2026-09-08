"""Confined I/O and parent-owned admission of recoverable transformation bundles.

The scanner is pure. This service invokes the existing canonical writer only
after publishing and checking a complete candidate; the export is just a mirror.
"""

from __future__ import annotations

import os
import stat
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import locked_replay
from arw.kernel.ledger.manifests import validate_accepted_event_manifests
from arw.kernel.state.models import ArtifactAcceptanceRequest

from .inspection import MAX_INPUT_BYTES, ArtifactIntegrityInspector

MAX_BUNDLE_BYTES = 14 * MAX_INPUT_BYTES
PLATFORM_SUPPORTED = (
    bool(getattr(os, "O_NOFOLLOW", 0))
    and bool(getattr(os, "O_DIRECTORY", 0))
    and all(fn in os.supports_dir_fd for fn in (os.open, os.stat, os.link, os.unlink))
)


class ArtifactOperationError(ValueError):
    """Stable reason code without leaking source text or host paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _relative_parts(relative: str) -> list[str]:
    parts = relative.split("/")
    if (
        not relative
        or "\\" in relative
        or "\x00" in relative
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ArtifactOperationError("invalid_relative_path")
    return parts


def _identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


@contextmanager
def _root_descriptor(root: Path):
    if not PLATFORM_SUPPORTED:
        raise ArtifactOperationError("platform_unsupported")
    root = Path(root)
    if ".." in root.parts:
        raise ArtifactOperationError("invalid_root")
    absolute = root if root.is_absolute() else Path.cwd() / root
    descriptors = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(absolute.anchor, flags)
        descriptors.append(descriptor)
        for part in absolute.parts[1:]:
            descriptor = os.open(part, flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        yield descriptor
    except OSError as error:
        raise ArtifactOperationError("access_denied_or_unavailable") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _read(descriptor: int, relative: str, limit: int):
    parts = _relative_parts(relative)
    opened = []
    directory_links = []
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        parent = descriptor
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=parent)
            directory_links.append((parent, part, child))
            parent = child
            opened.append(parent)
        leaf = os.open(parts[-1], flags, dir_fd=parent)
        opened.append(leaf)
        before = os.fstat(leaf)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactOperationError("nonregular_input")
        if before.st_size > limit:
            raise ArtifactOperationError("input_too_large")
        chunks, total = [], 0
        while total <= limit:
            chunk = os.read(leaf, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(leaf)
        current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(
            current
        ):
            raise ArtifactOperationError("unstable_input")
        for parent_fd, component, child_fd in directory_links:
            named = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            held = os.fstat(child_fd)
            if (named.st_dev, named.st_ino, named.st_mode) != (
                held.st_dev,
                held.st_ino,
                held.st_mode,
            ):
                raise ArtifactOperationError("unstable_input")
        if total > limit:
            raise ArtifactOperationError("input_too_large")
        return b"".join(chunks), (before.st_dev, before.st_ino)
    finally:
        for item in reversed(opened):
            os.close(item)


def _verify_root(root: Path, descriptor: int):
    with _root_descriptor(root) as current:
        a, b = os.fstat(descriptor), os.fstat(current)
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            raise ArtifactOperationError("unstable_root")


def _publish(descriptor: int, relative: str, content: bytes, source_identity):
    """Atomically install bytes without replacement; validate exact retries."""
    if len(_relative_parts(relative)) != 1:
        raise ArtifactOperationError("invalid_output_path")
    temporary = f".arw-sanitize-{uuid.uuid4().hex}.tmp"
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=descriptor,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                relative,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        actual, identity = _read(descriptor, relative, MAX_BUNDLE_BYTES)
        if actual != content or identity == source_identity:
            raise ArtifactOperationError("output_collision")
        os.fsync(descriptor)
    finally:
        os.unlink(temporary, dir_fd=descriptor)


class ArtifactIntegrityService(ArtifactIntegrityInspector):
    def __init__(self):
        self.inspector = ArtifactIntegrityInspector()

    @staticmethod
    def load_acceptance_request(path: Path) -> ArtifactAcceptanceRequest:
        with _root_descriptor(path.parent) as descriptor:
            content, _ = _read(descriptor, path.name, 65536)
        return ArtifactAcceptanceRequest.model_validate(strict_json_loads(content))

    def inspect(
        self, root: Path, relative: str, *, detectors: Sequence[str] | None = None
    ):
        _relative_parts(relative)
        with _root_descriptor(root) as descriptor:
            content, _ = _read(descriptor, relative, MAX_INPUT_BYTES)
            _verify_root(root, descriptor)
        return self.inspector.inspect_bytes(content, detectors=detectors)

    @staticmethod
    def _accepted_retry(run_root, request, descriptor):
        _verify_root(run_root, descriptor)
        with locked_replay(run_root) as (root, replayed):
            validate_accepted_event_manifests(root, replayed.events)
            for event in replayed.events:
                if (
                    event.command_id != request.command_id
                    and event.event_id != request.event_id
                ):
                    continue
                if (
                    event.event_type == "artifact.accepted"
                    and event.command_id == request.command_id
                    and event.event_id == request.event_id
                    and event.run_id == request.run_id
                    and event.actor_id == request.actor_id
                    and event.actor_role == request.actor_role
                    and event.occurred_at == request.occurred_at
                    and event.expected_revision == request.expected_revision
                    and event.payload.artifact_id == request.artifact_id
                    and event.payload.artifact_sha256 == request.content_sha256
                ):
                    return event.event_id
                raise ArtifactOperationError("command_identity_conflict")
        return None

    def sanitize(
        self,
        root: Path,
        relative: str,
        *,
        run_root: Path,
        request: ArtifactAcceptanceRequest,
        privacy: bool,
        remove_codepoints: Sequence[str],
        strip_provenance: bool = False,
        treatment: str = "unicode",
    ):
        # Check authorization and request type before any filesystem mutation.
        if privacy is not True:
            raise ArtifactOperationError("privacy_authorization_required")
        if strip_provenance or treatment != "unicode":
            raise ArtifactOperationError("unsupported_treatment")
        request = ArtifactAcceptanceRequest.model_validate(
            request.model_dump(mode="json")
        )
        _relative_parts(relative)
        with (
            _root_descriptor(root) as source_descriptor,
            _root_descriptor(run_root) as run_descriptor,
        ):
            original, source_identity = _read(
                source_descriptor, relative, MAX_INPUT_BYTES
            )
            result = self.inspector.sanitize_bytes(
                original, privacy=privacy, remove_codepoints=remove_codepoints
            )
            if not result.only_selected_changed:
                raise ArtifactOperationError("verification_failed")
            derived = result.derived_text.encode("utf-8")
            stem = f"arw-sanitize-{sha256_hex(request.command_id.encode())}"
            bundle_path, export_path = f"{stem}.receipt.json", f"{stem}.txt"
            request_identity = request.model_dump(
                mode="json",
                exclude={
                    "artifact_kind",
                    "media_type",
                    "content_path",
                    "content_sha256",
                },
            )
            bundle = {
                "schema_version": "arw.artifact-sanitization-bundle.v1",
                "request_identity": request_identity,
                "source": {
                    "relative_path": relative,
                    "text": original.decode("utf-8"),
                    "sha256": sha256_hex(original),
                },
                "derived": {
                    "relative_path": export_path,
                    "text": result.derived_text,
                    "sha256": sha256_hex(derived),
                },
                "authorization": {
                    "privacy": True,
                    "strip_provenance": False,
                    "actor_id": request.actor_id,
                },
                "verification": result.model_dump(
                    mode="json", exclude={"derived_text"}
                ),
            }
            bundle_bytes = canonical_json_bytes(bundle)
            if len(bundle_bytes) > MAX_BUNDLE_BYTES:
                raise ArtifactOperationError("bundle_too_large")
            canonical_request = request.model_copy(
                update={
                    "artifact_kind": "artifact-sanitization-receipt",
                    "media_type": "application/json",
                    "content_path": bundle_path,
                    "content_sha256": sha256_hex(bundle_bytes),
                }
            )
            # Source identity is rechecked before publishing the candidate.
            current, _ = _read(source_descriptor, relative, MAX_INPUT_BYTES)
            if current != original:
                raise ArtifactOperationError("unstable_input")
            _verify_root(root, source_descriptor)
            _verify_root(run_root, run_descriptor)
            # Do not even create a journal lock in an uninitialized directory.
            _read(run_descriptor, "run-manifest.json", 65536)
            already = self._accepted_retry(run_root, canonical_request, run_descriptor)
            _publish(run_descriptor, bundle_path, bundle_bytes, source_identity)
            _publish(run_descriptor, export_path, derived, source_identity)
            _verify_root(run_root, run_descriptor)
            response = {
                "schema_version": "arw.artifact-sanitize-result.v1",
                "accepted": False,
                "bundle_path": bundle_path,
                "bundle_sha256": canonical_request.content_sha256,
                "export_path": export_path,
                "source_sha256": sha256_hex(original),
                "derived_sha256": sha256_hex(derived),
                "verification": result.model_dump(
                    mode="json", exclude={"derived_text"}
                ),
            }
            if already:
                response.update(
                    accepted=True, status="already_accepted", event_id=already
                )
            else:
                try:
                    runtime = RuntimeCommandService(run_root)
                    _verify_root(run_root, run_descriptor)
                    outcome = runtime.accept_artifact(canonical_request)
                except (OSError, RuntimeError) as error:
                    # Candidate or even event may be durable. Never roll it back;
                    # exact retry inspects canonical replay before admitting again.
                    raise ArtifactOperationError(
                        "acceptance_interrupted_retry_required"
                    ) from error
                if not outcome.accepted:
                    already = self._accepted_retry(
                        run_root, canonical_request, run_descriptor
                    )
                    if already:
                        response.update(
                            accepted=True, status="already_accepted", event_id=already
                        )
                    else:
                        response.update(
                            status="rejected", reason_code=outcome.rejection.code
                        )
                else:
                    response.update(
                        accepted=True,
                        status="accepted",
                        event_id=outcome.event.event_id,
                    )
            _verify_root(run_root, run_descriptor)
            final_bundle, _ = _read(run_descriptor, bundle_path, MAX_BUNDLE_BYTES)
            final_export, _ = _read(run_descriptor, export_path, MAX_INPUT_BYTES)
            final_source, _ = _read(source_descriptor, relative, MAX_INPUT_BYTES)
            if (
                final_bundle != bundle_bytes
                or final_export != derived
                or final_source != original
            ):
                raise ArtifactOperationError("post_acceptance_verification_failed")
            return response
