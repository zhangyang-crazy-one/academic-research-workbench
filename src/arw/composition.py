"""Composition root: the only place concrete adapters are instantiated.

The CLI resolves providers through this module's routing table; kernel code
never imports adapters. This keeps the ports/adapters boundary enforceable
(see tests/compat/test_kernel_dependency_direction.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from pathlib import Path

from arw.kernel.capabilities import CapabilityRouter


def default_router(
    *,
    files_control_root: Path | None = None,
    graph_control_root: Path | None = None,
    graph_root_id: str | None = None,
    store_path: Path | None = None,
    files_root_id: str = "research-root",
    plugin_manifest: Path | None = None,
    semantica_store_path: Path | None = None,
    canonical_event_digests: Mapping[str, str] | None = None,
    accepted_artifact_ids_by_event: Mapping[str, tuple[str, ...]] | None = None,
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
        # Probe the OPTIONAL engine itself: arw.storm imports cleanly with
        # only stdlib+pydantic (the knowledge_storm import is lazy inside
        # run_storm_research), so importing arw.storm would resolve
        # successfully even when the engine is absent (review P2).  Probing
        # knowledge_storm makes resolution-time absence detection real.
        import knowledge_storm  # type: ignore[import-not-found]  # noqa: F401 -- optional probe

        from arw.storm import run_storm_research

        return run_storm_research

    router.register_optional("research.deep_survey", _storm_adapter)

    if store_path is not None:
        from arw.kernel.capabilities import CapabilityUnavailable

        def _local_store_files():
            from arw_ext.local_store import LocalProjectionStore
            from arw_ext.local_store.files import LocalStoreFilesAdapter

            # Read-path resolution must not create or migrate the store: a
            # missing DB file simply means the capability is unavailable.
            if not Path(store_path).is_file():
                raise CapabilityUnavailable(
                    "files.local (no local store at the configured path)"
                )
            store = LocalProjectionStore(Path(store_path))
            # Read-path resolution opens read-only: never migrate or mutate
            # the store as a side effect of resolving a query capability.
            store.open_readonly()
            try:
                return LocalStoreFilesAdapter(store)
            except Exception:
                store.close()
                raise

        router.register("files.local", _local_store_files)
    elif files_control_root is not None:
        from arw.adapters.files import LocalFilesAdapter
        from arw.files import load_query_generation
        from arw.kernel.capabilities import CapabilityUnavailable

        def _local_files():
            try:
                generation = load_query_generation(files_control_root, files_root_id)
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
            lambda: GraphProjectionAdapter(
                GraphStore(graph_control_root, graph_root_id)
            ),
        )
    if semantica_store_path is not None:

        def _semantica_provenance():
            module = import_module("arw_semantica")
            return module.SemanticaSQLiteAdapter(
                semantica_store_path,
                canonical_event_digests=canonical_event_digests or {},
                accepted_artifact_ids_by_event=accepted_artifact_ids_by_event or {},
                audit_database_path=store_path,
            )

        router.register_optional("knowledge.provenance", _semantica_provenance)
    if plugin_manifest is not None:
        declared = set(declared_capabilities(plugin_manifest))
        # The manifest declares broad capability names (``files``, ``graph``,
        # ...) while the router registers dotted identifiers
        # (``files.local``, ``knowledge.graph``).  Map each manifest name to
        # the router prefixes it enables; an undeclared capability is
        # deregistered so resolution reports capability-not-available.
        manifest_to_router: dict[str, tuple[str, ...]] = {
            "research": ("research.literature", "research.deep_survey"),
            "literature": ("research.literature",),
            "experiment": ("research.experiment",),
            "evidence": (),
            "files": ("files.local", "files.search"),
            "graph": ("knowledge.graph",),
            "provenance": ("knowledge.provenance",),
            "artifact": ("artifact.inspect", "artifact.sanitize"),
            "audit": ("audit.replay",),
        }
        enabled: set[str] = set()
        for name in declared:
            enabled.update(manifest_to_router.get(name, ()))
        for capability in router.available():
            if capability not in enabled:
                router._providers.pop(capability)
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
        raise ValueError(
            f"unreadable plugin manifest {plugin_manifest}: {error}"
        ) from error
    capabilities = payload.get("interface", {}).get("capabilities", [])
    return tuple(str(item) for item in capabilities)


def ingest_files_into_default_store(
    control_root: Path, root_id: str, *, generation_id: str
) -> int:
    """Ingest the selected files generation into the default local store.

    Called from the ``arw files sync/rebuild`` path after a new generation is
    selected, so the native files provider actually has data to serve (PR5
    review P1).  This is a WRITE path (sync), so creating the store at the
    default per-user cache location is intended.

    Overlapping syncs are handled by converging on the LATEST selected
    generation: if the selection moves mid-ingest, the stale attempt rolls
    back and the ingest retries against the new selection (bounded), so a
    failed first attempt never leaves the pointer permanently ahead of the
    cache (review P2, round 5).  Returns the ingested row count.
    """
    from arw_ext.local_store import LocalProjectionStore
    from arw_ext.local_store.ingest import ingest_files_generation
    from arw_ext.local_store.location import resolve_store_path

    from arw.files import load_query_generation, load_selected_generation

    target_generation_id = generation_id
    attempts = 3
    while True:
        generation = load_query_generation(control_root, root_id)
        # Bind to the generation the sync produced when it is still selected;
        # otherwise follow the CURRENT selection (a newer sync won).
        if generation.selected.generation_id != target_generation_id:
            target_generation_id = generation.selected.generation_id

        # Key the default store by the REGISTERED root's canonical path, not
        # the caller's working directory (sync may run from anywhere).
        store_path = resolve_store_path(Path(generation.root.canonical_path))
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store = LocalProjectionStore(store_path)
        store.open()
        try:
            ingested = ingest_files_generation(store.connection, generation)
            # Re-read the selection pointer right before committing: a
            # concurrent sync may have re-selected a newer generation while
            # we ingested.  Committing stale rows would leave the store ahead
            # of the control root's actual selection.
            current = load_selected_generation(control_root, root_id)
            if current.generation_id != target_generation_id:
                store.connection.rollback()
                attempts -= 1
                if attempts <= 0:
                    raise ValueError(
                        "selected generation kept moving during ingest; "
                        "giving up after bounded retries"
                    )
                target_generation_id = current.generation_id
                continue
            store.connection.commit()
            return ingested
        finally:
            store.close()


def local_store_files_provider(store_path: Path):
    """Return the native files provider over an existing local store.

    Read-only: opens with ``open_readonly`` (never creates/migrates/mutates
    the store).  Raises ``CapabilityUnavailable`` when the store file is
    absent or carries no ingested files projection — callers treat that as
    "fall back to the v1 provider", not a crash.
    """
    from arw.kernel.capabilities import CapabilityUnavailable

    if not Path(store_path).is_file():
        raise CapabilityUnavailable(
            "files.local (no local store at the configured path)"
        )

    from arw_ext.local_store import LocalProjectionStore
    from arw_ext.local_store.files import LocalStoreFilesAdapter

    store = LocalProjectionStore(Path(store_path))
    store.open_readonly()
    try:
        return LocalStoreFilesAdapter(store)
    except Exception:
        store.close()
        raise
