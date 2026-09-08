"""Stable project identities and explicit authorization, independent of host paths."""

import uuid
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.research_memory import MemoryAuthorization, ProjectIdentity


class ProjectIdentityUnresolved(ValueError):
    code = "project_identity_unresolved"


class MemoryAccessDenied(ValueError):
    code = "memory_access_denied"


def project_identity(root):
    try:
        return ProjectIdentity.model_validate_json(
            read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
        )
    except (ValueError, RuntimeError, OSError) as error:
        raise ProjectIdentityUnresolved(
            "an explicit stable ARW project identity is required"
        ) from error


def initialize_project(root, project_id=None):
    root = Path(root)
    if (root / ".arw/project.json").exists():
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


def authorization(root):
    if not (Path(root) / ".arw/memory-authorization.json").exists():
        return MemoryAuthorization()
    return MemoryAuthorization.model_validate_json(
        read_retained_bytes(root, ".arw/memory-authorization.json", max_bytes=65_536)
    )
