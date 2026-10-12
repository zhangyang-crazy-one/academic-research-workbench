"""Stable project identities and explicit authorization, independent of host paths."""

from pathlib import Path

from arw.kernel.ledger.projects import (
    ProjectIdentityUnresolved,
    initialize_project,
    project_identity,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.research_memory import MemoryAuthorization

__all__ = [
    "MemoryAccessDenied",
    "ProjectIdentityUnresolved",
    "authorization",
    "initialize_project",
    "project_identity",
]


class MemoryAccessDenied(ValueError):
    code = "memory_access_denied"


def authorization(root):
    if not (Path(root) / ".arw/memory-authorization.json").exists():
        return MemoryAuthorization()
    return MemoryAuthorization.model_validate_json(
        read_retained_bytes(root, ".arw/memory-authorization.json", max_bytes=65_536)
    )
