"""Composition root: the only place concrete adapters are instantiated.

The CLI resolves providers through this module's routing table; kernel code
never imports adapters. This keeps the ports/adapters boundary enforceable
(see tests/compat/test_kernel_dependency_direction.py).
"""

from __future__ import annotations

from pathlib import Path

from arw.kernel.capabilities import CapabilityRouter


def default_router(
    *,
    files_control_root: Path | None = None,
    graph_control_root: Path | None = None,
    graph_root_id: str | None = None,
) -> CapabilityRouter:
    """The v1-default routing table (local files + graph + ARS + integrity).

    File and graph providers require a control root, so they are registered
    only when the caller supplies one (the CLI composition sites do).
    """
    from arw.adapters.artifacts import ArtifactIntegrityAdapter
    from arw.adapters.workflow import ARSAdapter

    router = CapabilityRouter()
    router.register("research.literature", ARSAdapter)
    router.register("artifact.inspect", ArtifactIntegrityAdapter)

    if files_control_root is not None:
        from arw.files import FilesAdminService

        router.register(
            "files.local", lambda: FilesAdminService(files_control_root)
        )
    if graph_control_root is not None and graph_root_id is not None:
        from arw.adapters.knowledge import GraphProjectionAdapter
        from arw.graph_store import GraphStore

        router.register(
            "knowledge.graph",
            lambda: GraphProjectionAdapter(GraphStore(graph_control_root, graph_root_id)),
        )
    return router
