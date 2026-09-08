"""Parent-only durable research artifact publication through the existing journal."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import (
    append_runtime_event_unlocked,
    build_runtime_event,
    locked_replay,
)
from arw.kernel.ledger.manifests import (
    install_artifact_manifest,
    validate_accepted_event_manifests,
)
from arw.kernel.ledger.reducer import reduce_events
from arw.kernel.state.models import (
    ArtifactManifest,
    ResearchArtifactAcceptedPayload,
    ResearchArtifactStagePayload,
    ResearchArtifactSupersededPayload,
)


class ResearchRecordError(ValueError):
    code = "research_record_invalid"


class BodyUnavailable(ResearchRecordError):
    code = "body_unavailable"


def publish_once(root: Path, relative: str, content: bytes) -> None:
    """Publish/fsync a create-only file; exact retries do not replace bytes."""
    parts = relative.split("/")
    if (
        not relative
        or any(p in {"", ".", ".."} for p in parts)
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ResearchRecordError("invalid immutable output path")
    if len(content) > 8_388_608:
        raise ResearchRecordError("immutable output exceeds byte budget")
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ResearchRecordError("immutable root is unsafe")
    if not getattr(os, "O_NOFOLLOW", 0) or os.open not in os.supports_dir_fd:
        raise ResearchRecordError(
            "safe immutable publication is unavailable on this platform"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory)
                os.fsync(directory)
            except FileExistsError:
                pass
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        try:
            existing = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                info = os.fstat(existing)
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(content):
                    raise ResearchRecordError("immutable output ID conflict")
                chunks = []
                remaining = len(content) + 1
                while remaining:
                    block = os.read(existing, min(65536, remaining))
                    if not block:
                        break
                    chunks.append(block)
                    remaining -= len(block)
                if b"".join(chunks) != content:
                    raise ResearchRecordError("immutable output ID conflict")
                return
            finally:
                os.close(existing)
        temporary = f".arw-{uuid.uuid4().hex}.tmp"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(
                temporary,
                parts[-1],
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
    except OSError as error:
        raise ResearchRecordError("immutable publication failed safely") from error
    finally:
        os.close(directory)


def commit_artifact_pipeline(root, request, prepare, *, boundary=lambda _: None):
    """Prepare under the writer lock; files precede event fsync, index follows it."""
    if request.actor_role != "parent_control_plane":
        raise ResearchRecordError("only the parent may qualify research artifacts")
    with locked_replay(root) as (_, state):
        if request.run_id != state.run_id or state.recovery_health != "healthy":
            raise ResearchRecordError(
                "run identity or recovery health prevents qualification"
            )
        validate_accepted_event_manifests(root, state.events)
        ir, receipt, files = prepare(state.events)
        reject_secret_shapes(canonical_json_bytes(ir.model_dump(mode="json")))
        if receipt.qualification != "PASS":
            for path, content in files.items():
                publish_once(root, path, content)
            return {
                "accepted": False,
                "qualification": "FAIL",
                "receipt": receipt.model_dump(mode="json"),
            }
        existing = next(
            (e for e in state.events if e.command_id == request.command_id), None
        )
        if existing is not None and (
            existing.event_type != "research_artifact_accepted"
            or existing.payload.ir_sha256 != receipt.ir_sha256
            or existing.payload.artifact_sha256
            != sha256_hex(canonical_json_bytes(receipt.model_dump(mode="json")))
        ):
            raise ResearchRecordError("command ID already binds different research content")
        operation_id = uuid.UUID(request.command_id.removeprefix("cmd-"))

        def identity(prefix, phase):
            if phase == "research_artifact_accepted":
                return request.command_id if prefix == "cmd" else request.event_id
            return f"{prefix}-{uuid.UUID(bytes=uuid.uuid5(operation_id, phase).bytes, version=4)}"

        phases = [
            "research_artifact_ir_frozen",
            "research_artifact_rendered",
            "research_artifact_validated",
            "research_artifact_accepted",
        ]
        if ir.supersedes:
            phases.append("research_artifact_superseded")
        operation_commands = {identity("cmd", p) for p in phases}
        prior = [e for e in state.events if e.command_id in operation_commands]
        if (
            existing is None
            and request.expected_revision + len(prior) != state.revision
        ):
            raise ResearchRecordError("stale qualification revision")
        accepted = [
            e for e in state.events if e.event_type == "research_artifact_accepted"
        ]
        if any(
            e.payload.artifact_id == ir.artifact_id
            and e.command_id != request.command_id
            for e in accepted
        ):
            raise ResearchRecordError(
                "artifact ID already accepted; use a new ID to supersede"
            )
        if ir.supersedes and not any(
            e.payload.artifact_id == ir.supersedes for e in accepted
        ):
            raise ResearchRecordError("superseded artifact is not accepted")
        for path, content in files.items():
            publish_once(root, path, content)
        boundary("files_durable")
        receipt_raw = canonical_json_bytes(receipt.model_dump(mode="json"))
        receipt_sha = sha256_hex(receipt_raw)
        stage = ResearchArtifactStagePayload(
            artifact_id=ir.artifact_id,
            ir_sha256=receipt.ir_sha256,
            renderer_identity_digest=receipt.renderer.identity_digest,
            receipt_sha256=receipt_sha,
            source_event_sha256=[b.ledger_event_sha256 for b in ir.research_bindings],
        )
        accepting = None
        for phase in phases:
            old = next(
                (e for e in state.events if e.command_id == identity("cmd", phase)),
                None,
            )
            if old is not None:
                if getattr(old.payload, "artifact_id", None) != ir.artifact_id or (
                    hasattr(old.payload, "ir_sha256")
                    and old.payload.ir_sha256 != receipt.ir_sha256
                ):
                    raise ResearchRecordError(
                        "partial operation conflicts with frozen input"
                    )
                if phase == "research_artifact_accepted":
                    accepting = old
                continue
            if phase == "research_artifact_accepted":
                manifest = ArtifactManifest(
                    schema_version="1.0.0",
                    run_id=state.run_id,
                    artifact_id=ir.artifact_id,
                    artifact_kind="research-artifact",
                    media_type="application/json",
                    content_path=f".arw/artifacts/accepted/{ir.artifact_id}/receipt.json",
                    content_sha256=receipt_sha,
                    producer_id=request.actor_id,
                    attempt_id=None,
                    base_revision=state.revision,
                    consumed_sha256=[state.last_event_sha256],
                    created_at=request.occurred_at,
                )
                path = install_artifact_manifest(root, manifest)
                payload = ResearchArtifactAcceptedPayload(
                    artifact_id=ir.artifact_id,
                    manifest_sha256=path.stem,
                    artifact_sha256=receipt_sha,
                    ir_sha256=receipt.ir_sha256,
                    renderer_identity_digest=receipt.renderer.identity_digest,
                    source_event_sha256=stage.source_event_sha256,
                    supersedes=ir.supersedes,
                )
            elif phase == "research_artifact_superseded":
                payload = ResearchArtifactSupersededPayload(
                    artifact_id=ir.artifact_id,
                    supersedes=ir.supersedes,
                    accepting_event_id=accepting.event_id,
                )
            else:
                payload = stage
            event = build_runtime_event(
                state,
                event_type=phase,
                event_id=identity("evt", phase),
                command_id=identity("cmd", phase),
                occurred_at=request.occurred_at,
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                payload=payload,
            )
            reduce_events(state.workflow_definition_id, (*state.events, event))
            _, state = append_runtime_event_unlocked(root, state, event)
            boundary(phase)
            if phase == "research_artifact_accepted":
                accepting = event
                boundary("event_durable")
        binding = {
            "artifact_id": ir.artifact_id,
            "ir_sha256": receipt.ir_sha256,
            "receipt_sha256": receipt_sha,
            "event_id": accepting.event_id,
            "event_sha256": accepting.event_sha256,
        }
        publish_once(
            root,
            f".arw/artifacts/accepted/{ir.artifact_id}/binding.json",
            canonical_json_bytes(binding),
        )
        boundary("projection_updated")
        return {
            "accepted": True,
            "qualification": "PASS",
            "receipt": receipt.model_dump(mode="json"),
            "binding": binding,
            "idempotent": existing is not None,
        }


def unlink_retained(root: Path, relative: str) -> None:
    """Remove one authorized body without following directory or file symlinks."""
    parts = relative.split("/")
    if any(p in {"", ".", ".."} for p in parts) or "\\" in relative:
        raise ResearchRecordError("invalid retention path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = []
    links = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=current)
            links.append((current, part, child))
            descriptors.append(child)
            current = child
        try:
            info = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode):
            raise ResearchRecordError("retention target is not a direct regular file")
        for parent, name, child in links:
            live = os.stat(name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(child)
            if (live.st_dev, live.st_ino, live.st_mode) != (
                held.st_dev,
                held.st_ino,
                held.st_mode,
            ):
                raise ResearchRecordError("retention path changed")
        os.unlink(parts[-1], dir_fd=current)
        os.fsync(current)
    except OSError as error:
        raise ResearchRecordError("retention path is unavailable or unsafe") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
