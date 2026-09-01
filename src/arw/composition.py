"""Composition root: the only place concrete adapters are instantiated.

The CLI resolves providers through this module's routing table; kernel code
never imports adapters. This keeps the ports/adapters boundary enforceable
(see tests/compat/test_kernel_dependency_direction.py).
"""

from __future__ import annotations

from pathlib import Path

from arw.kernel.capabilities import CapabilityRouter


def default_router() -> CapabilityRouter:
    """The v1-default routing table (local files + graph + ARS + integrity)."""
    router = CapabilityRouter()

    from arw.adapters.artifacts import ArtifactIntegrityAdapter
    from arw.adapters.workflow import ARSAdapter

    router.register("research.literature", ARSAdapter)
    router.register("artifact.inspect", ArtifactIntegrityAdapter)
    return router


def graph_store_provider(control_root: Path, root_id: str):
    """KnowledgeProvider for the v1 graph store, built lazily by the CLI."""
    from arw.adapters.knowledge import GraphProjectionAdapter
    from arw.graph_store import GraphStore

    return GraphProjectionAdapter(GraphStore(control_root, root_id))


def files_admin_service(control_root: Path):
    """FileProvider admin service for the v1 local files plane."""
    from arw.files import FilesAdminService

    return FilesAdminService(control_root)
