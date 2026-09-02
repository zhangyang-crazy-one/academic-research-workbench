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
        from arw.adapters.files import LocalFilesAdapter
        from arw.files import load_query_generation
        from arw.kernel.capabilities import CapabilityUnavailable

        def _local_files():
            try:
                generation = load_query_generation(files_control_root, "research-root")
            except Exception as error:
                raise CapabilityUnavailable(
                    "files.local (no synced generation; run `files sync` first)"
                ) from error
            return LocalFilesAdapter(generation)

        router.register("files.local", _local_files)
    if graph_control_root is not None and graph_root_id is not None:
        from arw.adapters.knowledge import GraphProjectionAdapter
        from arw.graph_store import GraphStore

        router.register(
            "knowledge.graph",
            lambda: GraphProjectionAdapter(GraphStore(graph_control_root, graph_root_id)),
        )
    return router


def files_admin_service(control_root: Path):
    """Admin (register/sync/rebuild/status) service — the CLI files command
    path. This is NOT the `files.local` query capability; query access is
    resolved through the router as a LocalFilesAdapter."""
    from arw.files import FilesAdminService

    return FilesAdminService(control_root)


def local_store_health(store_path: Path) -> dict:
    """Projection-health summary for one local store (task 5.3).

    Composition-root seam: the kernel never imports ``arw_ext``; the CLI
    calls this helper so the extension boundary stays one-directional.
    The store is opened read-only for the health read and closed before
    returning; the mapping is a plain dict so ``arw status`` output stays
    JSON-serializable without leaking extension types across the seam.
    """
    from arw_ext.local_store import LocalProjectionStore
    from arw_ext.local_store.health import collect_health

    store = LocalProjectionStore(Path(store_path))
    store.open()
    try:
        return collect_health(store)
    finally:
        store.close()
