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
    store_path: Path | None = None,
) -> CapabilityRouter:
    """The default routing table (local files + graph + ARS + integrity).

    File and graph providers require a control root, so they are registered
    only when the caller supplies one (the CLI composition sites do).

    When ``store_path`` is supplied AND the store carries a files projection,
    ``files.local`` resolves to the native :class:`LocalStoreFilesAdapter`
    (PR5 task 3.2: the native provider is the default once equivalence is
    proven); the v1 file-base generation path remains selectable by simply
    not passing ``store_path``.
    """
    from arw.adapters.artifacts import ArtifactIntegrityAdapter
    from arw.adapters.workflow import ARSAdapter

    router = CapabilityRouter()
    router.register("research.literature", ARSAdapter)
    router.register("artifact.inspect", ArtifactIntegrityAdapter)

    # Optional research engines degrade to capability-not-available receipts
    # when their extras are not installed (never an import error).
    def _storm_adapter():
        from arw.adapters.workflow import ARSAdapter  # noqa: F401
        from arw.storm import run_storm_research  # optional dependency-group

        return run_storm_research

    router.register_optional("research.deep_survey", _storm_adapter)

    if store_path is not None:
        from arw.kernel.capabilities import CapabilityUnavailable

        def _local_store_files():
            from arw_ext.local_store import LocalProjectionStore
            from arw_ext.local_store.files import LocalStoreFilesAdapter

            try:
                store = LocalProjectionStore(Path(store_path))
                store.open()
                return LocalStoreFilesAdapter(store)
            except Exception as error:
                raise CapabilityUnavailable(
                    "files.local (no ingested files projection in the local store)"
                ) from error

        router.register("files.local", _local_store_files)
    elif files_control_root is not None:
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


def declared_capabilities(plugin_manifest: Path) -> tuple[str, ...]:
    """Return the capability set declared by the plugin manifest (task 2.1).

    The manifest's ``interface.capabilities`` list is the operator-facing
    declaration; the composition root intersects it with the registered
    provider table at activation time so absent optional engines simply
    never activate.
    """
    import json

    try:
        payload = json.loads(Path(plugin_manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"unreadable plugin manifest {plugin_manifest}: {error}") from error
    capabilities = payload.get("interface", {}).get("capabilities", [])
    return tuple(str(item) for item in capabilities)
