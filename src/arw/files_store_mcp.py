"""Store-backed files MCP server (PR5 task 4.1 — MCP as transport adapter).

Serves the same five read tools as ``arw.files_mcp`` but resolves them
through the native :class:`arw_ext.local_store.files.LocalStoreFilesAdapter`
over the local projection store instead of re-loading a v1 files generation.
This is the production read path that consumes the store populated by
``arw files sync`` (review: previously the sync populated the store but no
installed read path consumed it).

The MCP layer is a thin transport adapter: it parses JSON-RPC, dispatches to
the provider, and serializes the result.  No business logic lives here.

Capability gating: the production path goes through the same
``default_router`` graph uses, so the manifest's declared capability set
gates activation here too.  Without that gate, the launcher could enable the
files read path against a plugin manifest that does not declare ``files``,
which would diverge from graph's enforcement (PR15 follow-up).
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from pydantic import ValidationError

from arw.file_contracts import CursorError
from arw.file_models import (
    FilesContextRequest,
    FilesListRequest,
    FilesOutlineRequest,
    FilesReadRequest,
    FilesSearchRequest,
)
from arw.files import FilesAdminError, load_query_generation
from arw.composition import declared_capabilities
from arw.files_mcp import TOOL_MODELS, _tool_envelope
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads

# Reuse the v1 MCP request/response contract; the provider is the only
# difference.  TOOL_MODELS maps tool names to their request models.
_DISPATCH = {
    "list_files": ("list_files", FilesListRequest),
    "read_file": ("read_file", FilesReadRequest),
    "search_files": ("search_files", FilesSearchRequest),
    "get_outline": ("get_outline", FilesOutlineRequest),
    "get_context": ("get_context", FilesContextRequest),
}

# Per-tool isError mapping (PR15 wire parity with v1 ``FilesMcpServer.handle_tool``).
# Only ``read_file`` consults ``result.status``; the other four tools always
# return isError=False — that means ``degraded`` / ``no_structure`` /
# ``stale_conflict`` etc. for outline/context are delivered as
# NOT-isError envelopes.  Anything that raises stays isError=True.
_SUCCESS_STATUSES = {"ok", "stale_conflict", "encoding_error"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academic-research-files-store")
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help=(
            "Path to the local projection store. Optional: when omitted, "
            "the store path is resolved via ``resolve_store_path`` keyed by "
            "the registered canonical root (the authoritative source in "
            "``root.json``). When the resolved path does not exist on disk "
            "the server exits with STORE_ABSENT (69) before consuming stdin."
        ),
    )
    parser.add_argument(
        "--control-root",
        type=Path,
        default=None,
        help=(
            "Authoritative control root whose ``root.json`` registers the "
            "research root. Required for the production read path so the "
            "store's recorded canonical_path cannot redirect live reads."
        ),
    )
    parser.add_argument(
        "--root-id",
        default=None,
        help=(
            "Registered root ID under --control-root. Required together with "
            "--control-root so the adapter verifies the store's recorded "
            "root_id matches the registered root."
        ),
    )
    return parser


def _platform_supports_canonical_reader() -> tuple[bool, str]:
    """Probe whether the running platform exposes the primitives the
    per-request canonical selection reader requires.

    Returns ``(True, "")`` when the platform can run the secure reader
    (Linux / macOS with ``O_NOFOLLOW``, ``O_NONBLOCK``, ``O_DIRECTORY``,
    and ``os.open(dir_fd=...)`` support) or ``(False, reason)`` when any
    primitive is missing.  The caller (``main``) maps ``False`` to a
    distinct startup error before consuming stdin so the service does
    not advertise all five tools and then refuse each request with
    ``stale_query_generation``.
    """

    missing: list[str] = []
    if getattr(os, "O_NOFOLLOW", 0) == 0:
        missing.append("O_NOFOLLOW")
    if getattr(os, "O_NONBLOCK", 0) == 0:
        missing.append("O_NONBLOCK")
    if getattr(os, "O_DIRECTORY", 0) == 0:
        missing.append("O_DIRECTORY")
    if os.open not in os.supports_dir_fd:
        missing.append("os.open(dir_fd=...)")
    if missing:
        return False, ", ".join(missing)
    return True, ""


def _resolve_allowed_root(
    control_root: Path | None,
    root_id: str | None,
) -> tuple[Path, str, str, str]:
    """Return (allowed_root, root_id, generation_id, generation_manifest_sha256)
    from the authoritative registration.

    The ``generation_manifest_sha256`` is the digest ``selected-generation.json``
    binds to the named generation; the per-request reader compares this
    digest (alongside ``root_id`` and ``generation_id``) so a writer who
    edits the pointer file to point at a different generation while
    keeping the same generation_id is still refused (the digest would
    not match).
    """

    if control_root is None or root_id is None:
        raise ValueError(
            "control_root and root_id must be supplied together; refusing "
            "to read live files without an external allowed-root anchor"
        )
    generation = load_query_generation(control_root, root_id)
    return (
        Path(generation.root.canonical_path),
        generation.root.root_id,
        generation.selected.generation_id,
        generation.selected.generation_manifest_sha256,
    )


def _open_store_adapter(
    store_path: Path,
    *,
    allowed_root: Path,
    expected_root_id: str,
    expected_generation_id: str,
    expected_generation_manifest_sha256: str,
    control_root: Path | None = None,
    root_id: str | None = None,
):
    """Open the store read-only and construct the adapter with the security check.

    The adapter verifies the cache's recorded ``canonical_path``,
    ``root_id``, and ``selected_generation_id`` all match the externally
    configured anchors before any live read; this prevents a stale cache
    from being used to serve outdated content after the canonical
    selection advanced, and prevents the cache from being used to
    redirect reads outside the registered root.

    The per-request canonical revalidation (when ``control_root`` +
    ``root_id`` are supplied) additionally compares the
    ``generation_manifest_sha256`` recorded at startup against the one
    the canonical file names, so a writer who edits the pointer file
    to point at a different generation while keeping the same
    ``generation_id`` is still refused — the digest would not match.

    The arguments are optional for back-compat with direct callers /
    tests that synthesize the projection without a registered root.
    """

    from arw_ext.local_store import LocalProjectionStore
    from arw_ext.local_store.files import LocalStoreFilesAdapter

    store = LocalProjectionStore(store_path)
    store.open_readonly()
    try:
        return LocalStoreFilesAdapter(
            store,
            allowed_root=allowed_root,
            expected_root_id=expected_root_id,
            expected_generation_id=expected_generation_id,
            # Per-request canonical-selection revalidation: pass the
            # authoritative control root + root id so the adapter can
            # re-read ``selected-generation.json`` on every request and
            # fail closed if the canonical selection advances after the
            # MCP process started (long-lived process protection; the
            # constructor check above is only the startup gate).
            canonical_root=control_root,
            root_id=root_id,
            expected_generation_manifest_sha256=expected_generation_manifest_sha256,
        )
    except Exception:
        store.close()
        raise


def _resolve_plugin_manifest() -> Path | None:
    """Resolve the plugin manifest path the same way ``_graph-mcp`` does.

    Order (per PR5 / PR15 follow-up):

    1. Explicit ``ARW_PLUGIN_MANIFEST`` — installed launcher binding.
    2. ``ARW_PLUGIN_ROOT`` set without ``ARW_PLUGIN_MANIFEST`` — installed
       mode with a missing manifest binding; the router will skip gating,
       so we surface a configuration error instead of silently passing.
    3. Source-development fallback: ``.codex-plugin/plugin.json`` beside
       ``src/arw/cli.py`` (or beside this file if that lookup fails).
    """
    manifest_env = os.environ.get("ARW_PLUGIN_MANIFEST")
    if manifest_env:
        manifest_path = Path(manifest_env)
        if not manifest_path.is_file():
            raise FilesAdminError(
                "plugin_manifest_unreadable",
                f"plugin manifest is not a readable file: {manifest_env}",
            )
        return manifest_path
    if os.environ.get("ARW_PLUGIN_ROOT"):
        raise FilesAdminError(
            "plugin_manifest_missing",
            "installed mode requires ARW_PLUGIN_MANIFEST pointing at "
            ".codex-plugin/plugin.json",
        )
    # Source-tree fallback — the in-tree plugin.json sits at the repo root
    # next to ``pyproject.toml``; reach it from this file.
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        candidate = ancestor.parent / ".codex-plugin" / "plugin.json"
        if candidate.is_file():
            return candidate
    return None


def _enforce_capability_gate(store_path: Path) -> None:
    """Validate ``files.local`` is declared in the active plugin manifest.

    Mirrors the graph launcher's gating: the manifest's declared capability
    set must include ``files`` for the read path to activate.  When the
    capability is absent (either not registered or deregistered by the
    manifest), ``CapabilityUnavailable`` is raised and the process exits
    cleanly — there is no fallback to an undeclared capability.
    """
    try:
        manifest_path = _resolve_plugin_manifest()
    except FilesAdminError as error:
        raise CapabilityUnavailable(
            f"files.local ({error.code}: {error})"
        ) from error

    from arw.composition import default_router

    router = default_router(
        store_path=store_path,
        plugin_manifest=manifest_path,
    )
    # Resolve through the router to honor the manifest's capability gating.
    # The resolved adapter is discarded (we re-open the store below with
    # the security anchors); this only validates the gate, not the adapter.
    resolved = router.resolve("files.local")
    try:
        resolved._store.close()  # noqa: SLF001 — internal teardown
    except Exception:
        pass


def _check_manifest_declares_files() -> None:
    """Pre-check that the active plugin manifest declares ``files``.

    Runs BEFORE the STORE_ABSENT (69) detection so the shim's
    store-absent→legacy fallback can never bypass a manifest that has
    explicitly withheld the ``files`` capability.  The full gate
    (``_enforce_capability_gate``) still runs after STORE_ABSENT — this
    pre-check is purely a fail-closed ordering fix; it does not touch the
    store, so it works whether or not the store file is present.

    Source-tree development runs (no ``ARW_PLUGIN_ROOT``) have no manifest
    binding and intentionally skip gating here; the full gate handles
    that path the same way.
    """
    try:
        manifest_path = _resolve_plugin_manifest()
    except FilesAdminError as error:
        raise CapabilityUnavailable(
            f"files.local ({error.code}: {error})"
        ) from error

    if manifest_path is None:
        # Source-tree mode: no manifest binding, no gate.
        return

    declared = set(declared_capabilities(manifest_path))
    if "files" not in declared:
        raise CapabilityUnavailable(
            "files.local (manifest does not declare 'files' capability; "
            "STORE_ABSENT fallback must not bypass an explicit denial)"
        )


def _handle(adapter, request: object) -> dict[str, object] | None:
    if not isinstance(request, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    identifier = request.get("id")
    if identifier is None:
        return None
    method = request.get("method")
    params = request.get("params", {})
    try:
        if method == "initialize":
            result: object = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "academic-research-files-store", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": f"Local-store {name}.",
                        "inputSchema": model.model_json_schema(mode="validation"),
                    }
                    for name, model in TOOL_MODELS.items()
                ]
            }
        elif method == "tools/call" and isinstance(params, dict):
            name = params.get("name")
            arguments = params.get("arguments", {})
            entry = _DISPATCH.get(name if isinstance(name, str) else "")
            if entry is None:
                payload, is_error = (
                    {"error_code": "unknown_tool", "message": "tool is not registered"},
                    True,
                )
                result = _tool_envelope(payload, error=is_error)
            else:
                method_name, model = entry
                try:
                    parsed = model.model_validate(arguments)
                except ValidationError as error:
                    # Wire parity with v1 ``FilesMcpServer.handle_tool``:
                    # argument validation failures are reported as
                    # ``invalid_request``, not the generic ``tool_error``.
                    result = _tool_envelope(
                        {"error_code": "invalid_request", "message": str(error)},
                        error=True,
                    )
                else:
                    try:
                        result_model = getattr(adapter, method_name)(parsed)
                        payload = result_model.model_dump(mode="json")
                        # Per-tool isError mapping (v1 parity): only
                        # ``read_file`` consults ``result.status``; the
                        # other four tools deliver degraded/no_structure/etc.
                        # as NOT-isError envelopes so downstream MCP
                        # clients can still inspect the body.
                        if method_name == "read_file":
                            is_error = getattr(result_model, "status", "ok") not in _SUCCESS_STATUSES
                        else:
                            is_error = False
                        result = _tool_envelope(payload, error=is_error)
                    except Exception as error:  # noqa: BLE001 - envelope boundary
                        code = getattr(error, "code", "tool_error")
                        result = _tool_envelope(
                            {"error_code": code, "message": str(error)}, error=True
                        )
        else:
            return {
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32601, "message": "Method not found"},
            }
    except CursorError as error:
        result = _tool_envelope(
            {"error_code": error.code, "message": str(error)}, error=True
        )
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


# Pre-protocol exit code: STORE_ABSENT — the resolved store file does not
# exist on disk.  Surfaced before any stdin consumption so the launcher can
# treat "store not set up yet" as a normal first-run state and (optionally)
# fall back to the v1 reader; the cap is dedicated so other startup
# failures (capability denial, root mismatch, corruption, generic 78) are
# distinguishable from a clean absence and never trigger that fallback.
STORE_ABSENT_EXIT_CODE = 69


def _classify_store_path(store_path: Path) -> str:
    """Return one of ``"absent"`` / ``"unsafe"`` / ``"regular"`` for ``store_path``.

    P2 safety classifier: ``Path.is_file()`` returns False for both
    genuinely-missing paths and existing-but-non-regular paths (a
    directory, FIFO, broken symlink, device, socket, or anything else
    that is not a regular file).  Reserving STORE_ABSENT (69) for the
    former means the shim's legacy fallback can fire only when there
    really is no store file to read; the latter is a configuration
    error and must surface as 78 so the shim does not silently route
    through the v1 reader.

    The classifier uses lexical ``lstat`` on every path component (no
    ``Path.resolve()`` — symlinks are inspected, not followed).  This
    disambiguates the three classes the review pinned:

    * ``"absent"`` — the final component does not exist AND every
      existing lexical ancestor is a directory (so ``arw files sync``
      could create the cache here).  Permission or I/O errors raise
      ``"unsafe"``, NOT ``"absent"`` — a directory we cannot stat is
      not a "store not set up yet" state.
    * ``"unsafe"`` — some lexical ancestor is a non-directory (regular
      file, FIFO, device, socket) OR a symlink OR there is a
      ``NotADirectoryError`` / ``PermissionError`` / other ``OSError``
      at any step.  None of these can host a regular-file cache, and
      the canonical cache layout never produces them, so they are
      always operator error (a broken symlink ancestor in particular
      looks like ``ENOENT`` on the full path but is NOT genuine
      absence).
    * ``"regular"`` — the full path is a regular file that we can read.

    A symlink AT the full path itself is reported as ``"unsafe"`` even
    when the eventual target is a healthy regular file: ``lstat`` only
    sees the symlink, and ``Path.resolve()`` is intentionally avoided
    so the classifier is pure and reproducible.
    """
    try:
        result = store_path.lstat()
    except FileNotFoundError:
        # ENOENT on the final path: either the file is missing OR an
        # ancestor is missing/broken.  Walk lexical ancestors to
        # disambiguate.
        return _classify_via_ancestor_walk(store_path)
    except (NotADirectoryError, PermissionError, OSError):
        # ENOTDIR: some lexical ancestor is a non-directory (lstat
        # could not traverse the path).  EACCES / EIO: stat failed for
        # reasons that have nothing to do with "store not set up yet".
        # Both are operator error, NOT STORE_ABSENT.
        return "unsafe"
    # Full path exists lexically.  Symlinks and non-regular entries at
    # the store path itself are rejected (the layout never produces
    # them; surfacing as 78 keeps the v1 fallback out of the picture).
    if stat.S_ISLNK(result.st_mode):
        return "unsafe"
    if stat.S_ISREG(result.st_mode):
        return "regular"
    return "unsafe"


def _classify_via_ancestor_walk(store_path: Path) -> str:
    """Disambiguate ``ENOENT`` on the full path via lexical ancestor walk.

    Walk ``store_path.parents`` from the immediate parent up to the
    root, calling ``lstat`` on each component (no ``Path.resolve()``).
    Every existing lexical ancestor must be a directory:

    * directory → keep walking up; this prefix is fine.
    * symlink, regular file, FIFO, device, etc. → the cache layout is
      wrong; return ``"unsafe"`` (a broken symlink ancestor shows up
      here, because the kernel returned ``FileNotFoundError`` on the
      full path but the immediate prefix exists lexically as a
      symlink).
    * ``FileNotFoundError`` on a particular prefix → that prefix
      itself does not exist lexically.  Do NOT short-circuit to
      ``"absent"`` — a higher prefix could still be a symlink or
      non-directory, in which case the whole chain is unsafe.  Only
      when the walk reaches the root with no drift found is the path
      genuinely uncreated (``"absent"``).
    * ``NotADirectoryError``, ``PermissionError``, other ``OSError`` at
      any step → configuration that cannot be inspected safely;
      return ``"unsafe"``.
    """
    for ancestor in store_path.parents:
        try:
            result = ancestor.lstat()
        except FileNotFoundError:
            # Keep walking — the immediate prefix is missing but a
            # higher prefix could still be a symlink / non-directory.
            continue
        except (NotADirectoryError, PermissionError, OSError):
            return "unsafe"
        # Lexical existence only; no ``Path.resolve()``.  A symlink or
        # non-directory at any ancestor position is configuration drift
        # in the canonical cache layout — operator error, not "store
        # not set up yet", and the v1 fallback must not fire.
        if not stat.S_ISDIR(result.st_mode):
            return "unsafe"
    # Walked every ancestor up to the root with no drift found; only
    # the final file itself is missing.
    return "absent"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments.count("--store") > 1:
        print(
            "files-store-mcp: startup-error: --store must appear at most once",
            file=sys.stderr,
        )
        return 64
    if (
        "--control-root" not in arguments
        or "--root-id" not in arguments
    ):
        print(
            "files-store-mcp: startup-error: --control-root and --root-id "
            "are required (production read path is fail-closed without them)",
            file=sys.stderr,
        )
        return 64
    if (
        ("--control-root" in arguments)
        != ("--root-id" in arguments)
    ):
        print(
            "files-store-mcp: startup-error: --control-root and --root-id "
            "must be supplied together",
            file=sys.stderr,
        )
        return 64
    if arguments.count("--control-root") != 1:
        print(
            "files-store-mcp: startup-error: exactly one --control-root is required",
            file=sys.stderr,
        )
        return 64
    if arguments.count("--root-id") != 1:
        print(
            "files-store-mcp: startup-error: exactly one --root-id is required",
            file=sys.stderr,
        )
        return 64
    args = build_parser().parse_args(arguments)

    # Platform support probe (P1 review #3939835815): the per-request
    # canonical selection reader requires ``O_NOFOLLOW``, ``O_NONBLOCK``,
    # ``O_DIRECTORY``, and ``os.open(dir_fd=...)``.  Windows (and some
    # BSDs) do not expose ``O_NOFOLLOW`` / ``O_NONBLOCK``, and the
    # ancestor-swap defense requires ``O_DIRECTORY`` plus
    # ``os.supports_dir_fd``.  When any primitive is missing the reader
    # would fail closed on EVERY request, so we refuse to start the
    # service BEFORE consuming stdin.  The exit code 78 (config error)
    # is distinct from STORE_ABSENT (69) and from missing-anchor (64)
    # so the launcher can distinguish an unsupported platform from a
    # missing store / bad args and route the operator to the legacy
    # reader instead of silently failing every tool call.
    platform_ok, platform_reason = _platform_supports_canonical_reader()
    if not platform_ok:
        print(
            "files-store-mcp: startup-error: unsupported_security_primitives: "
            f"missing {platform_reason}; the per-request canonical selection "
            "reader cannot run on this platform. Configure the v1 files "
            "MCP via the legacy reader (set ARW_FILES_USE_LEGACY_READER=1) "
            "or run on a POSIX platform that exposes O_NOFOLLOW.",
            file=sys.stderr,
        )
        return 78

    # Resolve the external security anchors from the authoritative
    # ``root.json`` registration (refuses the ``<control_root>/<root_id>``
    # formula — the registered canonical_path is the only authoritative
    # source for where live reads may anchor).  ``expected_generation_id``
    # is the canonical selection at startup time; the adapter MUST bind
    # against it so a stale cache cannot serve outdated content after the
    # selection advances.
    try:
        (
            allowed_root,
            expected_root_id,
            expected_generation_id,
            expected_generation_manifest_sha256,
        ) = _resolve_allowed_root(args.control_root, args.root_id)
    except (OSError, FilesAdminError, ValueError) as error:
        code = getattr(error, "code", "control_root_unsafe")
        print(
            f"files-store-mcp: startup-error: {code}: {error}",
            file=sys.stderr,
        )
        return 78

    # Resolve the store path: explicit --store wins, otherwise default via
    # ``resolve_store_path`` keyed by the registered canonical root.  The
    # default location is the per-user cache; a network filesystem error is
    # surfaced as 78 (config error) so the launcher treats it the same as
    # any other startup failure (never a fallback trigger).
    if args.store is None:
        from arw_ext.local_store.location import resolve_store_path

        try:
            store_path = resolve_store_path(allowed_root)
        except (OSError, ValueError) as error:
            code = getattr(error, "code", "store_location_unsafe")
            print(
                f"files-store-mcp: startup-error: {code}: {error}",
                file=sys.stderr,
            )
            return 78
    else:
        store_path = args.store

    # Pre-check: a manifest that has explicitly withheld ``files`` MUST
    # block STORE_ABSENT fallback.  This pre-check does not touch the
    # store, so it works whether or not the file is present — its sole
    # job is to make sure a manifest denial can never be reached through
    # the store-absent → legacy fallback path.
    try:
        _check_manifest_declares_files()
    except CapabilityUnavailable as error:
        print(
            f"files-store-mcp: startup-error: capability_unavailable: {error}",
            file=sys.stderr,
        )
        return 78

    # Pre-protocol STORE_ABSENT: the resolved store is missing on disk.
    # Signaled before any stdin consumption so the launcher can detect
    # "store not yet populated" cleanly without touching the transport.
    # Reserve this signal for genuinely absent paths only — an existing
    # but non-regular path (directory, FIFO, broken symlink, etc.) is
    # a configuration error and must surface as 78 with NO fallback so a
    # misconfigured install cannot route through the v1 reader.
    store_state = _classify_store_path(store_path)
    if store_state == "absent":
        print(
            f"files-store-mcp: STORE_ABSENT: store not found at {store_path}",
            file=sys.stderr,
        )
        return STORE_ABSENT_EXIT_CODE
    if store_state == "unsafe":
        print(
            "files-store-mcp: startup-error: store_path_unsafe: "
            f"store path is not a regular file: {store_path}",
            file=sys.stderr,
        )
        return 78

    try:
        _enforce_capability_gate(store_path)
    except CapabilityUnavailable as error:
        print(
            f"files-store-mcp: startup-error: capability_unavailable: {error}",
            file=sys.stderr,
        )
        return 78

    try:
        adapter = _open_store_adapter(
            store_path,
            allowed_root=allowed_root,
            expected_root_id=expected_root_id,
            expected_generation_id=expected_generation_id,
            expected_generation_manifest_sha256=expected_generation_manifest_sha256,
            control_root=args.control_root,
            root_id=args.root_id,
        )
    except Exception as error:  # noqa: BLE001 - startup boundary
        code = getattr(error, "code", "store_unavailable")
        print(
            f"files-store-mcp: startup-error: {code}: {error}",
            file=sys.stderr,
        )
        return 78
    _run_loop(adapter)
    return 0


def _run_loop(adapter) -> None:
    for raw_line in sys.stdin.buffer:
        try:
            request = strict_json_loads(raw_line)
        except (UnicodeError, ValueError) as error:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {error}"},
            }
        else:
            response = _handle(adapter, request)
        if response is not None:
            sys.stdout.buffer.write(canonical_json_bytes(response))
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
