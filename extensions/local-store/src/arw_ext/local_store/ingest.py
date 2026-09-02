"""Ingest a v1 files-plane generation into the local projection store.

The local store's file projection mirrors the v1 ``files.sqlite3`` generation
semantics (design D4-amended): the original body is kept for ranking/location
parity, and both FTS5 indexes carry the NFKC-casefolded projection so
index-side MATCH semantics equal the v1 folded-substring semantics by
construction.

The ingest is idempotent (deterministic upserts keyed by ``file_id``) and
runs inside the caller's transaction.  A random cursor secret is generated
on first ingest and persisted in ``projection_meta`` so subsequent ingests
reuse it (cursors stay valid across incremental re-ingests).
"""

from __future__ import annotations

import base64
import os
import sqlite3
import unicodedata
from pathlib import Path

from arw.files import FilesQueryGeneration

from .errors import LocalStoreError

#: projection_meta keys written by the files ingest.
FILES_ROOT_ID_KEY = "files.root_id"
FILES_CANONICAL_PATH_KEY = "files.canonical_path"
FILES_GENERATION_ID_KEY = "files.selected_generation_id"
FILES_CURSOR_SECRET_KEY = "files.cursor_secret_b64"


class FilesIngestError(LocalStoreError):
    """The files-generation ingest could not complete."""

    code = "files_ingest_failed"


def _fold(body: str) -> str:
    """NFKC-casefold projection of one body (the v1 folded-substring space)."""

    return unicodedata.normalize("NFKC", body).casefold()


def _read_cursor_secret(connection: sqlite3.Connection) -> bytes:
    row = connection.execute(
        "SELECT value FROM projection_meta WHERE key = ?", (FILES_CURSOR_SECRET_KEY,)
    ).fetchone()
    if row is not None:
        return base64.b64decode(str(row[0]))
    secret = os.urandom(32)
    connection.execute(
        "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
        (FILES_CURSOR_SECRET_KEY, base64.b64encode(secret).decode("ascii")),
    )
    return secret


def read_files_meta(connection: sqlite3.Connection) -> dict[str, str] | None:
    """Return the stored files-plane metadata, or None when never ingested."""

    rows = connection.execute(
        "SELECT key, value FROM projection_meta WHERE key LIKE 'files.%'"
    ).fetchall()
    return dict(rows) if rows else None


def ingest_files_generation(
    connection: sqlite3.Connection,
    generation: FilesQueryGeneration,
) -> int:
    """Copy one v1 files generation into the store; return rows ingested.

    The source is the generation's own ``files.sqlite3`` (already validated
    by the v1 admin path).  Every row is upserted by ``file_id`` so repeated
    ingests of the same generation are no-ops.
    """

    source_path = Path(generation.database_path)
    if not source_path.is_file():
        raise FilesIngestError(f"generation database is missing: {source_path}")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        rows = source.execute(
            "SELECT file_id, relative_path, file_type, size_bytes, source_digest,"
            "       index_state, degraded_reason, extraction_registration_sha256, body"
            "  FROM files ORDER BY file_id"
        ).fetchall()
    except sqlite3.Error as error:
        raise FilesIngestError(f"generation database is unreadable: {error}") from error
    finally:
        source.close()

    cursor = connection.cursor()
    ingested = 0
    for (
        file_id,
        relative_path,
        file_type,
        size_bytes,
        source_digest,
        index_state,
        degraded_reason,
        extraction_registration_sha256,
        body,
    ) in rows:
        folded = None if body is None else _fold(str(body))
        cursor.execute(
            """
            INSERT INTO files (file_id, relative_path, file_type, size_bytes,
                               source_digest, index_state, degraded_reason,
                               extraction_registration_sha256, body_nfkc_folded, body)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                relative_path = excluded.relative_path,
                file_type = excluded.file_type,
                size_bytes = excluded.size_bytes,
                source_digest = excluded.source_digest,
                index_state = excluded.index_state,
                degraded_reason = excluded.degraded_reason,
                extraction_registration_sha256 = excluded.extraction_registration_sha256,
                body_nfkc_folded = excluded.body_nfkc_folded,
                body = excluded.body
            """,
            (
                file_id,
                relative_path,
                file_type,
                size_bytes,
                source_digest,
                index_state,
                degraded_reason,
                extraction_registration_sha256,
                folded,
                body,
            ),
        )
        # Refresh both FTS indexes (delete-then-insert; FTS5 external-content
        # is not used, so the tables are plain standalone indexes).
        cursor.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM files_fts_trigram WHERE file_id = ?", (file_id,))
        if folded is not None:
            cursor.execute(
                "INSERT INTO files_fts(file_id, relative_path, body_nfkc_folded)"
                " VALUES (?, ?, ?)",
                (file_id, relative_path, folded),
            )
            cursor.execute(
                "INSERT INTO files_fts_trigram(file_id, relative_path, body_nfkc_folded)"
                " VALUES (?, ?, ?)",
                (file_id, relative_path, folded),
            )
        ingested += 1

    # Full-snapshot semantics: rows absent from this generation were deleted
    # upstream (v1 rebuilds a generation on every sync); remove them from the
    # store and both FTS indexes so re-ingest converges with the v1 selected
    # generation (review P2: previously stale rows survived as phantom
    # stale_metadata hits).
    # Per-row membership check avoids a dynamic IN(...) clause entirely;
    # ingest is a sync-time operation, not a hot path.
    incoming_ids = {str(row[0]) for row in rows}
    stale_rows = cursor.execute("SELECT file_id FROM files").fetchall()
    for (stale_id,) in stale_rows:
        if str(stale_id) in incoming_ids:
            continue
        cursor.execute("DELETE FROM files WHERE file_id = ?", (stale_id,))
        cursor.execute("DELETE FROM files_fts WHERE file_id = ?", (stale_id,))
        cursor.execute("DELETE FROM files_fts_trigram WHERE file_id = ?", (stale_id,))

    # Record the files-plane binding metadata (root identity + selected
    # generation + cursor secret) so the adapter can serve reads without the
    # v1 generation on hand.
    cursor.execute(
        "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (FILES_ROOT_ID_KEY, generation.root.root_id),
    )
    cursor.execute(
        "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (FILES_CANONICAL_PATH_KEY, generation.root.canonical_path),
    )
    cursor.execute(
        "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (FILES_GENERATION_ID_KEY, generation.selected.generation_id),
    )
    _read_cursor_secret(connection)
    return ingested


__all__ = [
    "FILES_CANONICAL_PATH_KEY",
    "FILES_CURSOR_SECRET_KEY",
    "FILES_GENERATION_ID_KEY",
    "FILES_ROOT_ID_KEY",
    "FilesIngestError",
    "ingest_files_generation",
    "read_files_meta",
]
