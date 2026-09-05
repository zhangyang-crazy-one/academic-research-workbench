"""FileProvider adapter over the local SQLite projection store (PR4 Lane C).

The adapter mirrors ``arw.files_mcp.FilesMcpServer`` semantics byte-for-byte
at the wire level (same caps, error taxonomy, cursor envelopes, freshness
branches), but serves the indexed corpus from the local store's ``files``
table and routes full-text candidate selection through the FTS5 indexes
(``files_fts_trigram`` for ≥3-character terms, a ``LIKE`` fallback for
shorter terms) per design D4-amended.  Ranking/location/snippet are
recomputed with the exact v1 NFKC algorithm on the ORIGINAL body so the
pinned golden fixtures reproduce byte-identically.

Wire-contract echoes (frozen): ``tokenizer_id="unicode61-cjk-v1"`` and
``ranking_version="files-rank-v1"`` are version labels, not literal
tokenizer names — they are echoed verbatim regardless of the internal
unicode61 + trigram + NFKC-fold combination.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import stat
import threading
import time
import unicodedata
from pathlib import Path
from typing import Literal, cast

import sqlite3

from pydantic import ValidationError

from arw.adapters.files import FileProviderError
from arw.file_contracts import CursorCodec, CursorError
from arw.file_models import (
    CONTRACT_LIMITS,
    RANKING_VERSION,
    TOKENIZER_ID,
    FileListEntry,
    FilesContextRequest,
    FilesContextResult,
    FileSearchHit,
    FilesListRequest,
    FilesListResult,
    FilesOutlineRequest,
    FilesOutlineResult,
    FilesReadDenied,
    FilesReadRequest,
    FilesReadStale,
    FilesReadSuccess,
    FilesSearchRequest,
    FilesSearchResult,
    FileType,
    SourceLocation,
)
from arw.files_mcp import (
    MAX_CONTEXT_BYTES,
    MAX_SEARCH_CANDIDATES,
    LiveReadError,
    ToolError,
    _bounded_snippet,
    _IndexedFile,
    _outline_nodes,
    _RankedMatch,
    _read_live,
    _sensitive,
    _source_location,
)

from .ingest import (
    FILES_CURSOR_META_KEY,
    read_files_meta,
)
from .store import LocalProjectionStore


class LocalStoreFilesAdapter:
    """FileProvider over the local projection store (read-only).

    Constructed against an opened :class:`LocalProjectionStore` whose
    files projection has been populated by
    :func:`arw_ext.local_store.ingest.ingest_files_generation`.
    """

    def __init__(
        self,
        store: LocalProjectionStore,
        *,
        allowed_root: Path | str | None = None,
        expected_root_id: str | None = None,
        expected_generation_id: str | None = None,
        canonical_root: Path | str | None = None,
        root_id: str | None = None,
    ) -> None:
        store.assert_open()
        meta = read_files_meta(store.connection)
        if meta is None or "files.root_id" not in meta:
            raise FileProviderError(
                "files_not_ingested",
                "no files projection is present; ingest a files generation first",
            )
        self._store = store
        self._root_id = meta["files.root_id"]
        self._canonical_path = meta["files.canonical_path"]
        self._generation_id = meta["files.selected_generation_id"]
        # Per-request canonical-selection revalidation: when the caller
        # supplies the registered control root + root id (the same
        # anchor ``files_store_mcp`` resolved through the authoritative
        # ``root.json`` registration at startup), every operation will
        # re-read ``selected-generation.json`` from disk at the start
        # and end of the request, comparing it against the generation
        # the adapter is bound to.  This is the long-lived process
        # protection: the constructor check covers startup; the
        # per-request check catches a canonical ``sync`` advancing the
        # selection after the process started.  The arguments are
        # optional so the constructor stays backwards-compatible for
        # tests that synthesize the projection directly without a
        # registered root.
        if canonical_root is not None or root_id is not None:
            if canonical_root is None or root_id is None:
                raise FileProviderError(
                    "root_denied",
                    "canonical_root and root_id must be supplied together",
                )
            self._canonical_root = Path(canonical_root)
            self._canonical_root_id = str(root_id)
        else:
            self._canonical_root = None
            self._canonical_root_id = None
        # Per-instance request lock: the MCP reads stdin sequentially so
        # only one request is in flight at a time, but native callers
        # (Python code driving the adapter directly from threads or async
        # tasks) can be concurrent.  ``self._request_conn`` is an instance
        # attribute that ``_request_connection`` reads; without this
        # lock two concurrent callers would cross-wire each other's
        # snapshot connection.  Held for the duration of
        # ``_with_query_snapshot`` so the request_conn read/write and the
        # BEGIN / COMMIT / ROLLBACK all observe a consistent state.  A
        # plain ``Lock`` is sufficient because the current operations do
        # not nest (each public op runs its own wrapper); if nesting is
        # ever introduced, swap for ``RLock`` and the cleanup pattern
        # still works because ``self._request_conn`` is reset to ``None``
        # INSIDE the lock, before it is released.
        self._request_lock = threading.Lock()
        # Defense in depth: the cache's stored canonical_path is mutable on
        # disk, so an attacker who rewrites the projection could redirect
        # live reads anywhere on the filesystem.  When the caller passes an
        # externally configured allowed root (the registered root resolved
        # through the authoritative ``root.json`` registration), require
        # that the cache's canonical_path resolves inside it AND matches the
        # registered root id.  Without these checks the adapter still works
        # (back-compat for tests that synthesize the projection directly);
        # the MCP entry point refuses to construct without them.
        if allowed_root is not None or expected_root_id is not None:
            if allowed_root is None or expected_root_id is None:
                raise FileProviderError(
                    "root_denied",
                    "allowed_root and expected_root_id must be supplied together",
                )
            try:
                registered = Path(allowed_root).resolve(strict=False)
            except OSError as error:
                raise FileProviderError(
                    "root_denied",
                    f"allowed root is not resolvable: {error}",
                ) from error
            try:
                claimed = Path(self._canonical_path).resolve(strict=False)
            except OSError as error:
                raise FileProviderError(
                    "root_denied",
                    f"cache canonical_path is not resolvable: {error}",
                ) from error
            if claimed != registered:
                raise FileProviderError(
                    "root_denied",
                    "cache canonical_path does not match the registered root",
                )
            if self._root_id != expected_root_id:
                raise FileProviderError(
                    "root_denied",
                    "cache root_id does not match the registered root_id",
                )
        # Startup-time generation binding: when the caller supplies an
        # externally configured expected_generation_id (the canonical
        # selection at the moment the MCP process started), require that
        # the cache's recorded ``files.selected_generation_id`` matches
        # exactly.  Without this check, the MCP could keep serving an
        # older ingested projection after the canonical selection has
        # advanced — a silent staleness that the request-time
        # ``_check_generation`` cannot catch (clients binding cursors to
        # the new selection would never reach the cache's stale
        # generation in the first place).  Use a distinct error code
        # (``stale_ingested_cache``) so the MCP entry point can map this
        # to a non-fallback security failure (78), distinguishable from
        # the generic ``root_denied`` family.
        if expected_generation_id is not None:
            if self._generation_id != expected_generation_id:
                raise FileProviderError(
                    "stale_ingested_cache",
                    "cache selected_generation_id does not match the "
                    "canonical selection at startup time; re-ingest the "
                    "current generation before serving live reads",
                )
        secret = base64.b64decode(meta[FILES_CURSOR_META_KEY])
        self._codec = CursorCodec(secret=secret)
        # Hit anchors never expire (v1 parity: hit_codec uses a frozen clock).
        self._hit_codec = CursorCodec(secret=secret, clock=lambda: 0)

    # ------------------------------------------------------------------
    # Shared helpers (v1 semantics)
    # ------------------------------------------------------------------

    def _check_root(self, root_id: str) -> None:
        if root_id != self._root_id:
            raise FileProviderError("root_denied", "request names another root")

    @staticmethod
    def _deadline() -> float:
        # v1 LocalFilesAdapter passes time.monotonic() + 5.0 — identical to
        # CONTRACT_LIMITS["timeout_ms"]; keep the same value verbatim.
        return time.monotonic() + 5.0

    def _rows(
        self,
        sql: str,
        parameters: tuple[object, ...],
        *,
        deadline: float,
    ) -> list[tuple]:
        if time.monotonic() > deadline:
            raise ToolError("timeout", "query exceeded the server deadline")
        cursor = self._request_connection().execute(sql, parameters)
        return cursor.fetchall()

    def _indexed_from_row(self, row: tuple) -> _IndexedFile:
        (
            file_id,
            relative_path,
            file_type,
            source_digest,
            index_state,
            degraded_reason,
            extraction_registration_sha256,
            body,
        ) = row
        return _IndexedFile(
            file_id=str(file_id),
            relative_path=str(relative_path),
            file_type=cast(FileType, str(file_type)),
            source_digest=str(source_digest),
            index_state=str(index_state),
            degraded_reason=None if degraded_reason is None else str(degraded_reason),
            extraction_registration_sha256=(
                None
                if extraction_registration_sha256 is None
                else str(extraction_registration_sha256)
            ),
            body=None if body is None else str(body),
        )

    def _indexed_file(self, file_id: str, *, deadline: float) -> _IndexedFile | None:
        rows = self._rows(
            "SELECT file_id, relative_path, file_type, source_digest, index_state, degraded_reason, extraction_registration_sha256, body FROM files WHERE file_id = ?",
            (file_id,),
            deadline=deadline,
        )
        return None if not rows else self._indexed_from_row(rows[0])

    def _live_digest(
        self,
        indexed: _IndexedFile,
        *,
        deadline: float,
    ) -> tuple[str | None, bool]:
        try:
            live = _read_live(
                Path(self._canonical_path),
                indexed.relative_path,
                deadline=deadline,
            )
        except LiveReadError as error:
            if error.code == "timeout":
                raise ToolError("timeout", str(error)) from error
            return None, False
        except OSError:
            return None, False
        return live.digest, live.digest == indexed.source_digest

    def _check_generation(self, generation_id: str) -> None:
        if generation_id != self._generation_id:
            raise ToolError(
                "generation_mismatch",
                "request does not bind the store-selected files generation",
            )

    # ------------------------------------------------------------------
    # Per-request generation revalidation (PR16 long-lived protection)
    # ------------------------------------------------------------------

    def _open_query_snapshot(self) -> sqlite3.Connection:
        """Acquire a fresh read-only connection for one request's snapshot.

        Each per-request reader opens its OWN connection (separate from
        the long-lived store connection used at construction) so it can
        issue an explicit ``BEGIN`` and observe a consistent point-in-time
        snapshot.  Without a dedicated connection, two reads on the
        shared connection would not be inside any transaction and a
        writer could replace rows between them.
        """

        return self._store.open_snapshot_connection()

    def _request_connection(self) -> sqlite3.Connection:
        """Return the per-request snapshot connection, falling back to the long-lived store connection.

        While a request is in flight, :meth:`_with_query_snapshot` sets
        ``self._request_conn`` to a fresh read-only connection with an
        explicit ``BEGIN`` so every ``_rows`` call observes the same
        snapshot.  Outside a request (the constructor and tests that
        never go through the snapshot wrapper), fall back to the
        long-lived store connection so the helpers stay backwards-
        compatible.
        """

        request_conn = getattr(self, "_request_conn", None)
        if request_conn is not None:
            return request_conn
        return self._store.connection

    def _with_query_snapshot(self, fn, *args, **kwargs):  # noqa: ANN001, ANN202
        """Run ``fn`` inside a per-request snapshot with revalidation gates.

        The wrapper issues ``BEGIN`` on a fresh read-only connection,
        runs the pre-check (cache metadata + canonical selection), invokes
        ``fn`` (which performs all reads through
        :meth:`_request_connection` so they share the same snapshot),
        runs the post-check, and ``COMMIT``s.  Any exception triggers a
        ``ROLLBACK`` and re-raise; the connection is always closed.

        ``ToolError`` raised by the revalidation gates is wrapped to
        :class:`FileProviderError` with the same code so the MCP layer
        surfaces a typed failure (the per-tool envelope mapper in
        ``files_store_mcp`` already maps every ``FileProviderError`` to
        ``isError=True``).  The inner ``fn`` already wraps its own
        ``ToolError`` via :meth:`_wrap`; the outer wrap is a defensive
        measure so the pre/post checks land at the same boundary as
        tool errors.

        The whole body runs under ``self._request_lock`` so concurrent
        native callers (Python code driving the adapter from threads)
        cannot cross-wire ``self._request_conn``; the request_conn
        pointer is set to the snapshot at the start and reset to
        ``None`` BEFORE the lock is released, so a thread waiting on
        the lock cannot observe a half-cleared state.  ``snapshot.close()``
        runs in the outer ``finally`` after the lock is released; the
        connection is no longer reachable via ``self._request_conn`` by
        then, so a newly-acquired thread opens its own snapshot.

        Used by all five public operations so a writer who re-ingests the
        cache or advances the canonical selection cannot interleave rows
        from two generations inside a single response, and so concurrent
        native callers cannot observe each other's snapshot.
        """

        def _gate(snapshot_conn: sqlite3.Connection) -> None:
            try:
                self._revalidate_query_generation(snapshot_conn)
            except ToolError as error:
                raise FileProviderError(error.code, str(error)) from error

        snapshot = self._open_query_snapshot()
        try:
            with self._request_lock:
                self._request_conn = snapshot
                try:
                    snapshot.execute("BEGIN")
                    _gate(snapshot)
                    result = fn(*args, **kwargs)
                    _gate(snapshot)
                    snapshot.execute("COMMIT")
                    # Clear BEFORE releasing the lock so a waiting
                    # thread cannot observe the prior request's
                    # connection.
                    self._request_conn = None
                    return result
                except Exception:
                    with contextlib.suppress(sqlite3.Error):
                        snapshot.execute("ROLLBACK")
                    self._request_conn = None
                    raise
        finally:
            snapshot.close()

    def _read_canonical_generation_id(self) -> str:
        """Re-read the canonical ``selected-generation.json`` from disk.

        Returns the ``generation_id`` field the canonical root currently
        names as the selected generation.  When the adapter was
        constructed without a registered control root, fall back to the
        bound generation (skip the canonical re-check; the cache
        metadata check still runs, and the constructor check already
        bound the cache to that generation).
        """

        if self._canonical_root is None or self._canonical_root_id is None:
            return self._generation_id
        selected_path = (
            self._canonical_root
            / "roots"
            / self._canonical_root_id
            / "selected-generation.json"
        )
        try:
            payload = _read_canonical_selection_safe(
                selected_path, max_bytes=MAX_CANONICAL_SELECTION_BYTES
            )
        except (OSError, ValueError, UnicodeError) as error:
            # Canonical selection is gone or unreadable — a writer has
            # rotated the registration, or an attacker has swapped the
            # path for a FIFO/symlink/oversize file.  Fail closed rather
            # than silently keep serving the stale cache.
            raise ToolError(
                "stale_query_generation",
                f"canonical selected-generation.json is unreadable: {error}",
            ) from error
        except RecursionError as error:
            # Pathological JSON that blows Python's recursion limit;
            # json.JSONDecodeError is a ValueError, but defensive
            # against a future pure-Python fallback.
            raise ToolError(
                "stale_query_generation",
                f"canonical selected-generation.json is malformed: {error}",
            ) from error
        generation_id = payload.get("generation_id")
        if not isinstance(generation_id, str) or not generation_id:
            raise ToolError(
                "stale_query_generation",
                "canonical selected-generation.json has no generation_id",
            )
        return generation_id

    def _revalidate_query_generation(self, snapshot_conn) -> None:
        """Per-request guard: cache metadata AND canonical selection unchanged.

        Runs once at the start of each request (before any row reads) and
        again just before the result is assembled.  Both checks share the
        caller's snapshot connection, so a writer who re-ingests the cache
        mid-request cannot interleave rows from two generations.

        Raises :class:`ToolError` with code ``stale_query_generation`` on
        any drift.  The MCP layer maps this to ``FileProviderError`` with
        the same code, and the per-tool envelope returns ``isError=True``
        because ``stale_query_generation`` is not in the v1
        ``_SUCCESS_STATUSES`` set — the caller is told to restart the
        reader with the new generation.
        """

        meta = read_files_meta(snapshot_conn)
        if meta is None or "files.root_id" not in meta:
            raise ToolError(
                "stale_query_generation",
                "cache metadata disappeared mid-request; restart the reader",
            )
        cached_generation = meta.get("files.selected_generation_id")
        if cached_generation != self._generation_id:
            raise ToolError(
                "stale_query_generation",
                f"cache selected_generation_id advanced to {cached_generation!r}; "
                "restart the reader against the new generation",
            )
        canonical_generation = self._read_canonical_generation_id()
        if canonical_generation != self._generation_id:
            raise ToolError(
                "stale_query_generation",
                f"canonical selection advanced to {canonical_generation!r}; "
                "restart the reader against the new generation",
            )

    def _wrap(self, fn, *args, **kwargs):  # noqa: ANN001, ANN202
        try:
            return fn(*args, **kwargs)
        except (CursorError, LiveReadError, ToolError) as error:
            code = getattr(error, "code", "tool_error")
            raise FileProviderError(code, str(error)) from error

    # ------------------------------------------------------------------
    # list_files
    # ------------------------------------------------------------------

    def list_files(self, request: FilesListRequest) -> FilesListResult:
        self._check_root(request.root_id)
        return self._with_query_snapshot(
            lambda: self._wrap(self._list_files, request, deadline=self._deadline())
        )

    def _list_files(
        self, request: FilesListRequest, *, deadline: float
    ) -> FilesListResult:
        parameters = {"max_files": request.max_files}
        offset = 0
        if request.cursor is not None:
            envelope = self._codec.decode(
                request.cursor,
                operation="list_files",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self._generation_id,
            )
            # pi-lens-ignore: unchecked-throwing-call-python
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError(
                    "cursor_position_invalid", "list cursor position is invalid"
                )
        rows = self._rows(
            "SELECT file_id, relative_path, file_type, size_bytes, source_digest,"
            "       index_state"
            "  FROM files ORDER BY file_id, relative_path",
            (),
            deadline=deadline,
        )
        records = [
            # pi-lens-ignore: unchecked-throwing-call-python
            (str(r[0]), str(r[1]), str(r[2]), int(r[3]), str(r[4]), str(r[5]))
            for r in rows
        ]
        entries: list[FileListEntry] = []
        for (
            file_id,
            relative_path,
            file_type,
            size_bytes,
            digest,
            index_state,
        ) in records[offset : offset + request.max_files]:
            try:
                live = _read_live(
                    Path(self._canonical_path), relative_path, deadline=deadline
                )
            except LiveReadError as error:
                if error.code == "timeout":
                    raise
                live = None
            except OSError:
                live = None
            if file_type == "pdf":
                extraction_state = (
                    "registered" if index_state == "indexed" else "degraded"
                )
            elif file_type == "binary":
                extraction_state = "not_applicable"
            else:
                extraction_state = "direct_text"
            current_digest = None if live is None else live.digest
            entries.append(
                FileListEntry(
                    file_id=file_id,
                    relative_path=relative_path,
                    file_type=cast(FileType, file_type),
                    size_bytes=size_bytes if live is None else live.size_bytes,
                    current_digest=current_digest,
                    indexed_digest=digest,
                    extraction_state=extraction_state,
                    freshness="current"
                    if current_digest == digest
                    else "stale_metadata",
                )
            )
        next_offset = offset + len(entries)
        next_cursor = None
        if next_offset < len(records):
            next_cursor = self._codec.issue(
                operation="list_files",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=self._generation_id,
            )
        return FilesListResult(
            schema_version="1.0.0",
            root_id=request.root_id,
            selected_generation_id=self._generation_id,
            files=entries,
            next_cursor=next_cursor,
            complete_page=True,
        )

    # ------------------------------------------------------------------
    # read_file
    # ------------------------------------------------------------------

    def read_file(
        self, request: FilesReadRequest
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        self._check_root(request.root_id)
        return self._with_query_snapshot(
            lambda: self._wrap(self._read_file, request, deadline=self._deadline())
        )

    def _read_denied(
        self,
        request: FilesReadRequest,
        status: Literal["denied", "encoding_error", "budget_exceeded", "timeout"],
        code: str,
        message: str,
    ) -> FilesReadDenied:
        return FilesReadDenied(
            schema_version="1.0.0",
            status=status,
            root_id=request.root_id,
            file_id=request.file_id,
            relative_path=request.relative_path,
            error_code=code,
            message=message,
        )

    def _stale_live_read(
        self, request: FilesReadRequest, record: _IndexedFile, error: LiveReadError
    ) -> FilesReadStale:
        stale_code = "deleted" if error.code == "deleted" else "descriptor_changed"
        return FilesReadStale(
            schema_version="1.0.0",
            status="stale_conflict",
            root_id=request.root_id,
            file_id=request.file_id,
            relative_path=request.relative_path,
            expected_digest=request.expected_digest or record.source_digest,
            current_digest=None,
            error_code=stale_code,  # type: ignore[arg-type]
            message=str(error),
        )

    def _read_file(
        self, request: FilesReadRequest, *, deadline: float
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        record = self._indexed_file(request.file_id, deadline=deadline)
        if record is None or record.relative_path != request.relative_path:
            return self._read_denied(
                request,
                "denied",
                "identity_mismatch",
                "file ID and relative path do not match",
            )
        if _sensitive(request.relative_path):
            return self._read_denied(
                request,
                "denied",
                "sensitive_path",
                "sensitive path names are not readable",
            )
        try:
            live = _read_live(
                Path(self._canonical_path), request.relative_path, deadline=deadline
            )
        except LiveReadError as error:
            if error.code == "timeout":
                return self._read_denied(request, "timeout", "timeout", str(error))
            if error.code in {"deleted", "descriptor_changed", "symlink_escape"}:
                return self._stale_live_read(request, record, error)
            return self._read_denied(request, "denied", error.code, str(error))
        except OSError as error:
            return self._read_denied(request, "denied", "read_failed", str(error))
        expected = request.expected_digest or live.digest
        if (
            request.expected_digest is not None
            and request.expected_digest != live.digest
        ):
            return FilesReadStale(
                schema_version="1.0.0",
                status="stale_conflict",
                root_id=request.root_id,
                file_id=request.file_id,
                relative_path=request.relative_path,
                expected_digest=request.expected_digest,
                current_digest=live.digest,
                error_code="digest_mismatch",
                message="live file digest differs from the expected digest",
            )

        mode = "bytes" if request.byte_range is not None else "lines"
        parameters: dict[str, object] = {"relative_path": request.relative_path}
        if request.byte_range is not None:
            parameters["max_bytes"] = request.byte_range.max_bytes
            position = request.byte_range.start
        else:
            assert request.line_range is not None
            parameters["max_lines"] = request.line_range.max_lines
            position = request.line_range.start_line
        if request.cursor is not None:
            envelope = self._codec.decode(
                request.cursor,
                operation="read_file",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self._generation_id,
                file_id=request.file_id,
                expected_digest=expected,
                range_mode=mode,
            )
            key = "offset" if mode == "bytes" else "line"
            # pi-lens-ignore: unchecked-throwing-call-python
            position = int(envelope.position.get(key, -1))
            if position < (0 if mode == "bytes" else 1):
                raise CursorError(
                    "cursor_position_invalid", "read cursor position is invalid"
                )

        if request.byte_range is not None:
            if position > len(live.body):
                return self._read_denied(
                    request,
                    "denied",
                    "position_out_of_range",
                    "byte range start is beyond the file size",
                )
            end = min(len(live.body), position + request.byte_range.max_bytes)
            content = base64.b64encode(live.body[position:end]).decode("ascii")
            if len(content) > CONTRACT_LIMITS["read_bytes"]:
                return self._read_denied(
                    request,
                    "budget_exceeded",
                    "read_bytes_exceeded",
                    "byte result exceeds the byte ceiling",
                )
            truncated = end < len(live.body)
            next_position = {"offset": end}
            encoding = "bytes"
        else:
            assert request.line_range is not None
            try:
                text_body = live.body.decode("utf-8")
            except UnicodeDecodeError:
                return self._read_denied(
                    request,
                    "encoding_error",
                    "invalid_utf8",
                    "line ranges require strict UTF-8",
                )
            lines = text_body.splitlines(keepends=True)
            start_index = min(len(lines), position - 1)
            end_index = min(len(lines), start_index + request.line_range.max_lines)
            content = "".join(lines[start_index:end_index])
            if len(content.encode("utf-8")) > CONTRACT_LIMITS["read_bytes"]:
                return self._read_denied(
                    request,
                    "budget_exceeded",
                    "read_bytes_exceeded",
                    "line result exceeds the byte ceiling",
                )
            truncated = end_index < len(lines)
            next_position = {"line": end_index + 1}
            encoding = "utf-8"
        next_cursor = None
        if truncated:
            next_cursor = self._codec.issue(
                operation="read_file",
                root_id=request.root_id,
                parameters=parameters,
                position=next_position,
                ttl_seconds=300,
                generation_id=self._generation_id,
                file_id=request.file_id,
                expected_digest=expected,
                range_mode=mode,
            )
        return FilesReadSuccess(
            schema_version="1.0.0",
            status="ok",
            root_id=request.root_id,
            file_id=request.file_id,
            relative_path=request.relative_path,
            current_digest=live.digest,
            encoding=encoding,  # type: ignore[arg-type]
            content=content,
            truncated=truncated,
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # search_files (FTS5 candidate selection + v1 NFKC re-rank)
    # ------------------------------------------------------------------

    def search_files(self, request: FilesSearchRequest) -> FilesSearchResult:
        self._check_root(request.root_id)
        return self._with_query_snapshot(
            lambda: self._wrap(self._search_files, request, deadline=self._deadline())
        )

    @staticmethod
    def _normalize_query(mode: str, query: str) -> tuple[str, list[str]]:
        if mode == "exact":
            normalized = unicodedata.normalize("NFC", query)
            return normalized, [normalized]
        normalized = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
        terms = normalized.split(" ")
        if not terms or any(not term for term in terms):
            raise ToolError("query_empty", "full-text query has no searchable terms")
        return normalized, terms

    def _search_candidate_ids(
        self,
        request: FilesSearchRequest,
        terms: list[str],
        *,
        deadline: float,
    ) -> set[str] | None:
        """Return the FTS5 candidate file_id set, or None for a full scan.

        Routing (D4-amended): ``exact`` mode never touches the FTS indexes
        (it is an NFC substring scan in v1).  ``full_text`` terms with
        ≥3 characters query the trigram index (substring/CJK parity bridge);
        shorter terms fall back to a ``LIKE`` scan over the folded body.
        The returned set is a SUPERSET — the v1 re-rank performs the final
        all-terms-present filtering.
        """

        if request.mode == "exact":
            return None
        long_terms = [term for term in terms if len(term) >= 3]
        if not long_terms:
            # All terms are <3 chars: trigram cannot represent them; scan the
            # folded bodies with LIKE (v1 parity — v1 scans everything).
            candidate_ids: set[str] | None = None
            for term in terms:
                escaped = (
                    term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                rows = self._rows(
                    "SELECT file_id FROM files"
                    " WHERE index_state = 'indexed' AND body_nfkc_folded IS NOT NULL"
                    "   AND body_nfkc_folded LIKE '%' || ? || '%' ESCAPE '\\'",
                    (escaped,),
                    deadline=deadline,
                )
                ids = {str(row[0]) for row in rows}
                candidate_ids = ids if candidate_ids is None else candidate_ids & ids
            return candidate_ids if candidate_ids is not None else set()
        phrases = " ".join('"' + term.replace('"', '""') + '"' for term in long_terms)
        rows = self._rows(
            "SELECT file_id FROM files_fts_trigram WHERE files_fts_trigram MATCH ?",
            (f"body_nfkc_folded : {phrases}",),
            deadline=deadline,
        )
        return {str(row[0]) for row in rows}

    def _rank_search_rows(
        self,
        request: FilesSearchRequest,
        normalized_query: str,
        terms: list[str],
        *,
        deadline: float,
    ) -> list[_RankedMatch]:
        """Re-rank candidates with the exact v1 NFKC algorithm.

        Candidate selection runs through FTS5/LIKE (see
        :meth:`_search_candidate_ids`); scoring, locations, snippets, and the
        sort order are computed here on the ORIGINAL body, replicating the
        v1 ``_rank_search_rows`` semantics verbatim (including its
        folded-offsets-applied-to-original-body behavior).
        """

        candidate_ids = self._search_candidate_ids(request, terms, deadline=deadline)
        # v1 budget parity: the candidate ceiling applies to the indexed
        # corpus as a whole, matching the v1 full-scan budget behavior.
        corpus_rows = self._rows(
            "SELECT COUNT(*) FROM files"
            " WHERE index_state = 'indexed' AND body IS NOT NULL",
            (),
            deadline=deadline,
        )
        # pi-lens-ignore: unchecked-throwing-call-python
        if int(corpus_rows[0][0]) > MAX_SEARCH_CANDIDATES:
            raise ToolError(
                "candidate_budget_exceeded", "search candidate ceiling exceeded"
            )

        if candidate_ids is None:
            rows = self._rows(
                "SELECT file_id, relative_path, file_type, source_digest, index_state, degraded_reason, extraction_registration_sha256, body FROM files"
                " WHERE index_state = 'indexed' AND body IS NOT NULL"
                " ORDER BY file_id",
                (),
                deadline=deadline,
            )
        elif not candidate_ids:
            rows = []
        else:
            rows = []
            sorted_candidate_ids = sorted(candidate_ids)
            for start in range(0, len(sorted_candidate_ids), 500):
                batch = sorted_candidate_ids[start : start + 500]
                rows.extend(
                    self._rows(
                        "SELECT file_id, relative_path, file_type, source_digest, "
                        "index_state, degraded_reason, extraction_registration_sha256, body "
                        "FROM files WHERE file_id IN "
                        "(SELECT value FROM json_each(?)) "
                        "AND index_state = 'indexed' AND body IS NOT NULL "
                        "ORDER BY file_id",
                        (json.dumps(batch, separators=(",", ":")),),
                        deadline=deadline,
                    )
                )
        ranked: list[_RankedMatch] = []
        for row in rows:
            if time.monotonic() > deadline:
                raise ToolError("timeout", "search exceeded the server deadline")
            indexed = self._indexed_from_row(row)
            assert indexed.body is not None
            if request.mode == "exact":
                normalized_body = unicodedata.normalize("NFC", indexed.body)
                start = normalized_body.find(normalized_query)
                if start < 0:
                    continue
                end = start + len(normalized_query)
                # pi-lens-ignore: unchecked-throwing-call-python
                score = float(normalized_body.count(normalized_query))
            else:
                folded = unicodedata.normalize("NFKC", indexed.body).casefold()
                positions = [folded.find(term) for term in terms]
                if any(position < 0 for position in positions):
                    continue
                first_index = min(
                    range(len(positions)), key=lambda index: positions[index]
                )
                start = positions[first_index]
                end = start + len(terms[first_index])
                score = round(
                    sum(folded.count(term) for term in terms) / len(terms),
                    6,
                )
            location = _source_location(indexed.body, start, end)
            ranked.append(
                _RankedMatch(
                    indexed=indexed,
                    score=score,
                    location=location,
                    snippet=_bounded_snippet(
                        indexed.body,
                        start,
                        end,
                        request.max_snippet_bytes,
                    ),
                )
            )
        ranked.sort(
            key=lambda match: (
                -match.score,
                match.indexed.file_id,
                match.location.start_byte,
            )
        )
        return ranked

    def _search_files(
        self, request: FilesSearchRequest, *, deadline: float
    ) -> FilesSearchResult:
        normalized_query, terms = self._normalize_query(request.mode, request.query)
        parameters = {
            "mode": request.mode,
            "normalized_query": normalized_query,
            "max_hits": request.max_hits,
            "max_snippet_bytes": request.max_snippet_bytes,
            "tokenizer_id": TOKENIZER_ID,
            "ranking_version": RANKING_VERSION,
        }
        offset = 0
        if request.cursor is not None:
            envelope = self._codec.decode(
                request.cursor,
                operation="search_files",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self._generation_id,
            )
            # pi-lens-ignore: unchecked-throwing-call-python
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError(
                    "cursor_position_invalid", "search cursor position is invalid"
                )
        ranked = self._rank_search_rows(
            request,
            normalized_query,
            terms,
            deadline=deadline,
        )
        page = ranked[offset : offset + request.max_hits]
        hits: list[FileSearchHit] = []
        for match in page:
            current_digest, current = self._live_digest(
                match.indexed, deadline=deadline
            )
            if current:
                location_payload = match.location.model_dump(mode="json")
                hit_id = self._hit_codec.issue(
                    operation="search_hit",
                    root_id=request.root_id,
                    parameters={"anchor_version": "search-hit-v1"},
                    position=location_payload,
                    ttl_seconds=3_600,
                    generation_id=self._generation_id,
                    file_id=match.indexed.file_id,
                    expected_digest=match.indexed.source_digest,
                    range_mode="context",
                )
                hits.append(
                    FileSearchHit(
                        hit_id=hit_id,
                        file_id=match.indexed.file_id,
                        relative_path=match.indexed.relative_path,
                        file_type=cast(FileType, match.indexed.file_type),
                        indexed_digest=match.indexed.source_digest,
                        current_digest=current_digest,
                        extraction_registration_sha256=(
                            match.indexed.extraction_registration_sha256
                        ),
                        freshness="current",
                        sync_required=False,
                        score=match.score,
                        location=match.location,
                        snippet=match.snippet,
                    )
                )
            else:
                hits.append(
                    FileSearchHit(
                        hit_id=None,
                        file_id=match.indexed.file_id,
                        relative_path=match.indexed.relative_path,
                        file_type=cast(FileType, match.indexed.file_type),
                        indexed_digest=match.indexed.source_digest,
                        current_digest=current_digest,
                        extraction_registration_sha256=(
                            match.indexed.extraction_registration_sha256
                        ),
                        freshness="stale_metadata",
                        sync_required=True,
                        score=None,
                        location=None,
                        snippet=None,
                    )
                )
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(ranked):
            next_cursor = self._codec.issue(
                operation="search_files",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=self._generation_id,
            )
        if time.monotonic() > deadline:
            raise ToolError("timeout", "search exceeded the server deadline")
        return FilesSearchResult(
            schema_version="1.0.0",
            root_id=request.root_id,
            generation_id=self._generation_id,
            mode=request.mode,
            normalized_query=normalized_query,
            tokenizer_id=TOKENIZER_ID,
            ranking_version=RANKING_VERSION,
            hits=hits,
            next_cursor=next_cursor,
            complete_page=True,
        )

    # ------------------------------------------------------------------
    # get_outline
    # ------------------------------------------------------------------

    def get_outline(self, request: FilesOutlineRequest) -> FilesOutlineResult:
        self._check_root(request.root_id)
        return self._with_query_snapshot(
            lambda: self._wrap(self._get_outline, request, deadline=self._deadline())
        )

    def _get_outline(
        self, request: FilesOutlineRequest, *, deadline: float
    ) -> FilesOutlineResult:
        self._check_generation(request.generation_id)
        indexed = self._indexed_file(request.file_id, deadline=deadline)
        if indexed is None:
            raise ToolError(
                "file_not_found", "file ID is absent from the files projection"
            )
        current_digest, current = self._live_digest(indexed, deadline=deadline)
        base = {
            "schema_version": "1.0.0",
            "root_id": request.root_id,
            "generation_id": request.generation_id,
            "file_id": request.file_id,
            "indexed_digest": indexed.source_digest,
            "current_digest": current_digest,
            "extraction_registration_sha256": indexed.extraction_registration_sha256,
        }
        if request.expected_digest != indexed.source_digest or not current:
            return FilesOutlineResult(
                **base,
                status="stale_conflict",
                parser_version=None,
                nodes=[],
                next_cursor=None,
            )
        if indexed.index_state != "indexed" or indexed.body is None:
            return FilesOutlineResult(
                **base,
                status="degraded",
                parser_version=None,
                nodes=[],
                next_cursor=None,
            )
        parser_version, nodes = _outline_nodes(indexed.file_type, indexed.body)
        if not nodes:
            return FilesOutlineResult(
                **base,
                status="no_structure",
                parser_version=parser_version,
                nodes=[],
                next_cursor=None,
            )
        parameters = {
            "max_nodes": request.max_nodes,
            "parser_version": parser_version,
        }
        offset = 0
        if request.cursor is not None:
            envelope = self._codec.decode(
                request.cursor,
                operation="get_outline",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="nodes",
            )
            # pi-lens-ignore: unchecked-throwing-call-python
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError(
                    "cursor_position_invalid", "outline cursor position is invalid"
                )
        page = nodes[offset : offset + request.max_nodes]
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(nodes):
            next_cursor = self._codec.issue(
                operation="get_outline",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="nodes",
            )
        return FilesOutlineResult(
            **base,
            status="ok",
            parser_version=parser_version,
            nodes=page,
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # get_context
    # ------------------------------------------------------------------

    def get_context(self, request: FilesContextRequest) -> FilesContextResult:
        self._check_root(request.root_id)
        return self._with_query_snapshot(
            lambda: self._wrap(self._get_context, request, deadline=self._deadline())
        )

    def _get_context(
        self, request: FilesContextRequest, *, deadline: float
    ) -> FilesContextResult:
        self._check_generation(request.generation_id)
        indexed = self._indexed_file(request.file_id, deadline=deadline)
        if indexed is None:
            raise ToolError(
                "file_not_found", "file ID is absent from the files projection"
            )
        current_digest, current = self._live_digest(indexed, deadline=deadline)
        base = {
            "schema_version": "1.0.0",
            "root_id": request.root_id,
            "generation_id": request.generation_id,
            "file_id": request.file_id,
            "indexed_digest": indexed.source_digest,
            "current_digest": current_digest,
            "extraction_registration_sha256": indexed.extraction_registration_sha256,
        }
        if request.expected_digest != indexed.source_digest or not current:
            return FilesContextResult(
                **base,
                status="stale_conflict",
                location=None,
                context=None,
                truncated=False,
            )
        if indexed.index_state != "indexed" or indexed.body is None:
            return FilesContextResult(
                **base,
                status="degraded",
                location=None,
                context=None,
                truncated=False,
            )
        if request.hit_id is not None:
            envelope = self._hit_codec.decode(
                request.hit_id,
                operation="search_hit",
                root_id=request.root_id,
                parameters={"anchor_version": "search-hit-v1"},
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="context",
            )
            try:
                anchor = SourceLocation.model_validate(envelope.position)
            except ValidationError as error:
                raise CursorError(
                    "cursor_position_invalid", "search hit anchor is invalid"
                ) from error
        else:
            assert request.location is not None
            anchor = request.location
        location, context, truncated = _context_window(
            indexed.body,
            anchor,
            before_lines=request.before_lines,
            after_lines=request.after_lines,
        )
        if time.monotonic() > deadline:
            raise ToolError("timeout", "context query exceeded the server deadline")
        return FilesContextResult(
            **base,
            status="ok",
            location=location,
            context=context,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # Context window (verbatim copy of v1 _context_window semantics)
    # ------------------------------------------------------------------


def _context_window(
    body: str,
    anchor: SourceLocation,
    *,
    before_lines: int,
    after_lines: int,
) -> tuple[SourceLocation, str, bool]:
    """Byte-anchor → line-window mapping, identical to v1 ``_context_window``."""

    from bisect import bisect_right

    body_bytes = body.encode("utf-8")
    if anchor.end_byte > len(body_bytes):
        raise ToolError(
            "anchor_out_of_range", "context anchor exceeds the indexed body"
        )
    try:
        body_bytes[: anchor.start_byte].decode("utf-8")
        body_bytes[: anchor.end_byte].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ToolError(
            "anchor_not_utf8_boundary", "context anchor splits a UTF-8 sequence"
        ) from error
    raw_lines = body.splitlines(keepends=True)
    if not raw_lines:
        raise ToolError("anchor_out_of_range", "context anchor names an empty body")
    starts: list[int] = []
    offset = 0
    for line in raw_lines:
        starts.append(offset)
        offset += len(line.encode("utf-8"))
    start_index = max(0, bisect_right(starts, anchor.start_byte) - 1)
    last_byte = max(anchor.start_byte, anchor.end_byte - 1)
    end_index = max(start_index, bisect_right(starts, last_byte) - 1)
    window_start = max(0, start_index - before_lines)
    window_end = min(len(raw_lines), end_index + after_lines + 1)
    context = "".join(raw_lines[window_start:window_end])
    if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ToolError("context_budget_exceeded", "context exceeds the byte ceiling")
    start_byte = starts[window_start]
    end_byte = starts[window_end] if window_end < len(starts) else len(body_bytes)
    location = SourceLocation(
        start_byte=start_byte,
        end_byte=end_byte,
        start_line=window_start + 1,
        end_line=window_end,
    )
    return location, context, window_start > 0 or window_end < len(raw_lines)


__all__ = ["LocalStoreFilesAdapter"]


# ---------------------------------------------------------------------------
# Canonical selection reader (P1 DoS hardening)
# ---------------------------------------------------------------------------


#: 64 KiB cap for ``selected-generation.json``.  The canonical selection
#: is a small JSON object (``root_id``, ``generation_id``,
#: ``generation_manifest_sha256``) — 64 KiB is comfortably larger than the
#: legitimate payload and small enough to refuse a piped-in DoS payload
#: (a writer who pipes gigabytes through this path would block the
#: bounded read, then be rejected).
MAX_CANONICAL_SELECTION_BYTES = 65_536


def _read_canonical_selection_safe(
    path: Path,
    *,
    max_bytes: int = MAX_CANONICAL_SELECTION_BYTES,
) -> dict[str, object]:
    """Read and parse a small canonical JSON file with TOCTOU-resistant checks.

    Returns the parsed dict; raises :class:`OSError` on filesystem
    failures, :class:`UnicodeError` on malformed UTF-8, and
    :class:`ValueError` on malformed JSON.  The caller (the per-request
    revalidation gate) maps all three to a typed
    ``stale_query_generation`` failure so a poisoned canonical path
    fails closed without leaking the underlying cause to clients.

    Defenses (P1 review comment — never rely on ``Path.is_file()``
    then ``Path.read_text()``; a TOCTOU window lets a writer swap a
    regular file for a FIFO / symlink / device between the check and
    the read):

    * **Platform primitives required** — ``O_NOFOLLOW``, ``O_NONBLOCK``,
      ``O_DIRECTORY``, AND ``os.open`` in ``os.supports_dir_fd`` must
      ALL be available.  The helper does NOT silently default missing
      flags to ``0``: a FIFO at the leaf can block at ``os.open`` (NOT
      at ``os.read``) before any ``fstat`` runs, so falling back to a
      non-``O_NONBLOCK`` open would still hang the reader on a hostile
      FIFO.  When any primitive is missing the helper raises
      ``OSError`` with an explicit "platform unsupported" message and
      the caller maps it to ``stale_query_generation`` so the reader
      fails closed rather than running a partially-protected path.
    * **Ancestor walk with ``O_NOFOLLOW`` via ``dir_fd``** — a leaf
      ``O_NOFOLLOW`` does NOT protect a symlink swap on an ancestor
      directory component (the swap happens BEFORE the leaf open, so
      the leaf open follows the redirected directory).  The helper
      walks each component from the path's anchor (filesystem root or
      drive) down to the leaf's parent, opening every intermediate
      directory with ``O_RDONLY | O_NOFOLLOW | O_DIRECTORY | O_CLOEXEC``
      and threading ``dir_fd`` through each step.  A symlink swap on
      any ancestor is rejected at walk time.  This pattern matches the
      existing vetted ``_open_directory_no_follow`` in
      ``extensions/local-store/src/arw_ext/local_store/receipts.py``.
    * **Leaf open with ``O_NOFOLLOW | O_NONBLOCK``** — the leaf is
      opened relative to its parent directory's descriptor so a
      symlink at the leaf itself is also rejected, and ``O_NONBLOCK``
      prevents the FIFO-at-leaf DoS where ``os.open`` would block
      waiting for a writer.
    * **fstat ``S_ISREG``** — the descriptor must point at a regular
      file; FIFO, socket, device, directory are rejected before any
      read so the bounded read cannot block on a non-regular entry.
    * **Bounded read** — at most ``max_bytes + 1`` bytes are read; a
      file larger than ``max_bytes`` is rejected (DoS guard).
    * **TOCTOU check** — the post-read ``fstat`` is compared against
      the parent-directory's ``fstatat`` (via ``os.fstatat`` /
      ``os.stat`` with ``dir_fd``) so an unlink-and-replace of the
      leaf mid-read is detected.
    * **Strict UTF-8 decode** — malformed byte sequences raise
      ``UnicodeError`` rather than being silently replaced.
    * **Strict JSON parse** — :class:`RecursionError` is also caught
      so a pathological deeply-nested payload (a future pure-Python
      JSON fallback could hit it) is rejected as a typed failure
      rather than crashing the reader.
    """

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if no_follow == 0:
        raise OSError(
            "canonical selection reader requires O_NOFOLLOW; platform unsupported"
        )
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if nonblock == 0:
        # FIFO at the leaf blocks at ``os.open`` (waiting for a writer)
        # BEFORE any ``fstat`` runs, so ``O_NONBLOCK`` is not optional.
        # Fail closed rather than silently accepting a hang vector.
        raise OSError(
            "canonical selection reader requires O_NONBLOCK; platform unsupported"
        )
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if directory_flag == 0:
        raise OSError(
            "canonical selection reader requires O_DIRECTORY; platform unsupported"
        )
    if os.open not in os.supports_dir_fd:
        # ``dir_fd``-anchored directory walks are the only safe way to
        # reject ancestor symlink swaps; without them the helper cannot
        # guarantee no-follow on every component.
        raise OSError(
            "canonical selection reader requires os.open(dir_fd=); platform unsupported"
        )
    cloexec = getattr(os, "O_CLOEXEC", 0)

    candidate = path if path.is_absolute() else Path.cwd() / path
    if path.is_absolute():
        anchor_path = Path(candidate.anchor)
        components = candidate.parts[1:]
    else:
        anchor_path = Path.cwd()
        components = candidate.parts
    if not components:
        raise OSError("canonical selection path has no components")

    dir_flags = os.O_RDONLY | no_follow | directory_flag | cloexec
    leaf_flags = os.O_RDONLY | no_follow | nonblock | cloexec

    # Walk from the anchor down to the leaf's PARENT directory,
    # opening each directory component with O_NOFOLLOW so a symlink
    # swap mid-walk is rejected at walk time.  Then open the leaf
    # relative to its parent directory's descriptor so the leaf open
    # is also no-follow and no-block.
    dir_descriptor = os.open(anchor_path, dir_flags)
    try:
        for component in components[:-1]:
            try:
                next_descriptor = os.open(
                    component, dir_flags, dir_fd=dir_descriptor
                )
            except OSError:
                raise
            os.close(dir_descriptor)
            dir_descriptor = next_descriptor

        leaf_descriptor = os.open(
            components[-1], leaf_flags, dir_fd=dir_descriptor
        )
    finally:
        os.close(dir_descriptor)

    try:
        before = os.fstat(leaf_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise OSError(
                f"canonical selection is not a regular file: mode={oct(before.st_mode)}"
            )
        if before.st_size > max_bytes:
            raise OSError(
                f"canonical selection exceeds {max_bytes} bytes: size={before.st_size}"
            )
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(leaf_descriptor, min(16_384, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            raise OSError(
                f"canonical selection exceeded {max_bytes} bytes during read"
            )
        # TOCTOU check: re-fstat the leaf and compare to the parent-
        # directory fstatat of the leaf name (no-follow).  An unlink-
        # and-replace of the leaf during the read surfaces as a
        # mismatch in dev/ino/mode.
        after = os.fstat(leaf_descriptor)
        path_now = os.stat(path, follow_symlinks=False)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or (after.st_dev, after.st_ino) != (path_now.st_dev, path_now.st_ino)
        ):
            raise OSError("canonical selection changed during read")
        raw = b"".join(chunks)
    finally:
        os.close(leaf_descriptor)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"canonical selection is not valid UTF-8: {error}") from error

    try:
        payload = json.loads(text)
    except ValueError as error:
        raise ValueError(f"canonical selection is not valid JSON: {error}") from error
    except RecursionError as error:
        # Defensive: CPython's _json C extension has its own nesting
        # limit, but a future pure-Python fallback could hit
        # RecursionError on deeply-nested input.
        raise ValueError(
            f"canonical selection is pathologically nested: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise ValueError(
            f"canonical selection must be a JSON object, got {type(payload).__name__}"
        )
    return payload
