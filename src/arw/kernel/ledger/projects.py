"""Core stable project administration, independent of optional retrieval."""

from __future__ import annotations

import uuid
from pathlib import Path

import portalocker

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.research_memory import ProjectIdentity


class ProjectIdentityUnresolved(ValueError):
    code = "project_identity_unresolved"


def project_identity(root: Path) -> ProjectIdentity:
    try:
        return ProjectIdentity.model_validate_json(
            read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
        )
    except (ValueError, RuntimeError, OSError) as error:
        raise ProjectIdentityUnresolved(
            "an explicit stable ARW project identity is required"
        ) from error


def initialize_project(root: Path, project_id: str | None = None) -> ProjectIdentity:
    root = Path(root).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ProjectIdentityUnresolved("project root must be a real directory")
    directory = root / ".arw"
    lock = directory / ".project.lock"
    if directory.is_symlink() or lock.is_symlink():
        raise ProjectIdentityUnresolved("unsafe project identity path")
    directory.mkdir(mode=0o700, exist_ok=True)
    try:
        with portalocker.Lock(lock, mode="a+b", timeout=1, check_interval=0.01):
            path = directory / "project.json"
            if path.exists() or path.is_symlink():
                identity = project_identity(root)
                if project_id is not None and identity.project_id != project_id:
                    raise ProjectIdentityUnresolved(
                        "project identity already exists and differs"
                    )
                return identity
            identity = ProjectIdentity(
                schema_version="arw.project.v1",
                project_id=project_id or f"project-{uuid.uuid4()}",
            )
            publish_once(
                root,
                ".arw/project.json",
                canonical_json_bytes(identity.model_dump(mode="json")),
            )
            return identity
    except portalocker.exceptions.LockException as error:
        raise ProjectIdentityUnresolved(
            "project identity writer lock is held"
        ) from error
