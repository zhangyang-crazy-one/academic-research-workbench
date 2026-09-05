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
import json
import time
import unicodedata
from pathlib import Path
from typing import cast

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
        cursor = self._store.connection.execute(sql, parameters)
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
        return self._wrap(self._list_files, request, deadline=self._deadline())

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
        return self._wrap(self._read_file, request, deadline=self._deadline())

    def _read_denied(
        self, request: FilesReadRequest, status: str, code: str, message: str
    ) -> FilesReadDenied:
        return FilesReadDenied(
            schema_version="1.0.0",
            status=status,  # type: ignore[arg-type]
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
        return self._wrap(self._search_files, request, deadline=self._deadline())

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
        return self._wrap(self._get_outline, request, deadline=self._deadline())

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
        return self._wrap(self._get_context, request, deadline=self._deadline())

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
