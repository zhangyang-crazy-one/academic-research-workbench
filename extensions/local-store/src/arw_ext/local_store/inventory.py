"""Bind cached rows to the loader-verified canonical generation.

Fingerprints encode every query-visible column and derived NFKC fold with
distinct NULL, text and integer tags. SQLite reports sizes before Python
materializes text. Byte, VM-step and time limits bound both inventory scans.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import struct
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from arw.files import FilesAdminError, FilesQueryGeneration, load_query_generation

from .ingest import _fold

# Explicit query limits: larger corpora remain valid canonical evidence.
MAX_INVENTORY_BODY_BYTES: Final[int] = 100 * 1024 * 1024
MAX_INVENTORY_ROW_BYTES: Final[int] = 2 * MAX_INVENTORY_BODY_BYTES + 1024
MAX_INVENTORY_AGGREGATE_BYTES: Final[int] = 256 * 1024 * 1024
MAX_INVENTORY_VM_STEPS: Final[int] = 50_000_000
# Startup query limit for the complete serialized database, independent of
# the per-row/aggregate fingerprint limits. Canonical ingestion is unchanged.
MAX_CANONICAL_DATABASE_BYTES: Final[int] = 256 * 1024 * 1024
_UNINITIALISED_FINGERPRINT: Final[str] = "uninitialised"
_CANONICAL_COLUMNS = (
    "file_id",
    "relative_path",
    "file_type",
    "size_bytes",
    "source_digest",
    "index_state",
    "degraded_reason",
    "extraction_registration_sha256",
    "body",
)
_CACHE_COLUMNS = (*_CANONICAL_COLUMNS, "body_nfkc_folded")


class InventoryError(RuntimeError):
    """An inventory cannot be read safely."""

    code = "inventory_error"


class InventoryTampered(InventoryError):
    """Cached rows differ from canonical evidence."""

    code = "inventory_tampered"


class InventoryBudgetExceeded(InventoryError):
    """A byte, VM-step or elapsed-time limit was reached."""

    code = "inventory_budget_exceeded"


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise InventoryBudgetExceeded("inventory exceeded the request deadline")


@contextmanager
def _inventory_guard(
    connection: sqlite3.Connection,
    *,
    deadline: float,
    progress_limit: int | None = None,
) -> Iterator[None]:
    """Own the dedicated snapshot's SQL handler for this operation."""

    _check_deadline(deadline)
    limit = MAX_INVENTORY_VM_STEPS if progress_limit is None else progress_limit
    interval = max(1, min(1000, limit))
    steps = 0

    def progress() -> int:
        nonlocal steps
        steps += interval
        return int(steps >= limit or time.monotonic() > deadline)

    connection.set_progress_handler(progress, interval)
    try:
        yield
        _check_deadline(deadline)
    except sqlite3.Error as error:
        if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
            raise InventoryBudgetExceeded(
                "inventory SQL exceeded its work budget"
            ) from error
        raise InventoryError("inventory database is unreadable") from error
    finally:
        # set_progress_handler returns None, not a prior callback. Both callers
        # own dedicated connections with no previous handler.
        connection.set_progress_handler(None, 0)


def _fingerprint(
    connection: sqlite3.Connection,
    *,
    canonical: bool,
    deadline: float,
    progress_limit: int | None = None,
) -> str:
    columns = _CANONICAL_COLUMNS if canonical else _CACHE_COLUMNS
    # Retrieve lengths and rowids only; a giant TEXT/BLOB must not cross into
    # Python before the per-cell, per-row and remaining aggregate checks.
    lengths = ", ".join(
        f"CASE WHEN typeof({name}) = 'integer' THEN 8 "
        f"ELSE coalesce(length(CAST({name} AS BLOB)), 0) END"
        for name in columns
    )
    hasher = hashlib.sha256()
    used = 0
    with _inventory_guard(connection, deadline=deadline, progress_limit=progress_limit):
        cursor = connection.execute(
            f"SELECT rowid, {lengths} FROM files ORDER BY file_id"
        )
        try:
            for row_id, *sizes in cursor:
                _check_deadline(deadline)
                row_size = sum(sizes) + 9 * len(_CACHE_COLUMNS)
                if any(size > MAX_INVENTORY_BODY_BYTES for size in sizes):
                    raise InventoryBudgetExceeded(
                        "inventory cell exceeds the byte limit"
                    )
                if row_size > MAX_INVENTORY_ROW_BYTES:
                    raise InventoryBudgetExceeded(
                        "inventory row exceeds the byte limit"
                    )
                if used + row_size > MAX_INVENTORY_AGGREGATE_BYTES:
                    raise InventoryBudgetExceeded(
                        "inventory exceeds the aggregate byte limit"
                    )
                values = connection.execute(
                    f"SELECT {', '.join(columns)} FROM files WHERE rowid = ?", (row_id,)
                ).fetchone()
                if values is None:
                    raise InventoryError("inventory row disappeared from its snapshot")
                if canonical:
                    body = values[-1]
                    if body is not None and not isinstance(body, str):
                        raise InventoryError("canonical body has an invalid type")
                    values = (*values, None if body is None else _fold(body))
                row_used = 0
                for value in values:
                    _check_deadline(deadline)
                    if value is None:
                        tag, payload = b"N", b""
                    elif type(value) is int and 0 <= value <= 2**64 - 1:
                        tag, payload = b"I", struct.pack(">Q", value)
                    elif isinstance(value, str):
                        tag, payload = b"T", value.encode("utf-8")
                    else:
                        raise InventoryError("inventory column has an invalid type")
                    size = len(payload)
                    row_used += size + 9
                    if (
                        size > MAX_INVENTORY_BODY_BYTES
                        or row_used > MAX_INVENTORY_ROW_BYTES
                    ):
                        raise InventoryBudgetExceeded(
                            "inventory folded row exceeds the byte limit"
                        )
                    if used + size + 9 > MAX_INVENTORY_AGGREGATE_BYTES:
                        raise InventoryBudgetExceeded(
                            "inventory exceeds the aggregate byte limit"
                        )
                    hasher.update(tag)
                    hasher.update(struct.pack(">Q", size))
                    hasher.update(payload)
                    used += size + 9
        finally:
            cursor.close()
    return hasher.hexdigest()


def _verified_canonical_bytes(
    generation: FilesQueryGeneration, *, deadline: float
) -> bytes:
    """Read and hash one safe descriptor before admitting any SQLite bytes."""

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not (no_follow and nonblock and directory) or os.open not in os.supports_dir_fd:
        raise InventoryError("safe canonical database descriptor reads are unsupported")
    path = Path(generation.database_path).absolute()
    components = path.parts[1:]
    if not components or ".." in components:
        raise InventoryError("canonical database path is unsafe")
    directory_fd: int | None = None
    descriptor: int | None = None
    directory_flags = os.O_RDONLY | no_follow | directory | getattr(os, "O_CLOEXEC", 0)
    try:
        _check_deadline(deadline)
        directory_fd = os.open(path.anchor, directory_flags)
        for component in components[:-1]:
            _check_deadline(deadline)
            child = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        descriptor = os.open(
            components[-1],
            os.O_RDONLY | no_follow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InventoryError("canonical database is not a regular file")
        if before.st_size > MAX_CANONICAL_DATABASE_BYTES:
            raise InventoryBudgetExceeded(
                "canonical database exceeds the snapshot byte limit"
            )
        chunks: list[bytes] = []
        hasher = hashlib.sha256()
        total = 0
        while total < before.st_size:
            _check_deadline(deadline)
            chunk = os.read(descriptor, min(1 << 20, before.st_size - total))
            if not chunk:
                break
            total += len(chunk)
            hasher.update(chunk)
            chunks.append(chunk)
        _check_deadline(deadline)
        after = os.fstat(descriptor)
        path_now = os.stat(components[-1], dir_fd=directory_fd, follow_symlinks=False)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or identity(after) != identity(path_now):
            raise InventoryTampered("canonical database changed during snapshot read")
        if (
            total != before.st_size
            or hasher.hexdigest() != generation.manifest.database_sha256
        ):
            raise InventoryTampered(
                "canonical database digest differs from the verified manifest"
            )
        raw = b"".join(chunks)
        # Canonical generations use journal_mode=DELETE. A WAL database needs
        # additional unbound sidecar bytes and cannot be admitted as this image.
        if raw[18:20] != b"\x01\x01":
            raise InventoryError("WAL or unsupported canonical database journal format")
        _check_deadline(deadline)
        return raw
    except OSError as error:
        raise InventoryError("canonical database is unavailable or unsafe") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)


def compute_expected_inventory_fingerprint(
    generation: FilesQueryGeneration, *, deadline: float = float("inf")
) -> str:
    """Query a private image of the exact database bytes bound by the manifest."""

    _check_deadline(deadline)
    try:
        connection = sqlite3.connect(":memory:")
    except sqlite3.Error as error:
        raise InventoryError("canonical snapshot connection is unavailable") from error
    try:
        deserialize = getattr(connection, "deserialize", None)
        if not callable(deserialize):
            raise InventoryError(
                "canonical snapshot requires SQLite deserialize support"
            )
        raw = _verified_canonical_bytes(generation, deadline=deadline)
        deserialize(raw)
        # SQLite now reads only private memory, never the canonical pathname,
        # its live inode, or a subsequently introduced WAL/SHM sidecar.
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return _fingerprint(connection, canonical=True, deadline=deadline)
    except sqlite3.Error as error:
        raise InventoryError("canonical snapshot is unreadable") from error
    finally:
        connection.close()


def anchor_via_loader(
    control_root: Path,
    root_id: str,
    *,
    expected_generation_id: str,
    expected_generation_manifest_sha256: str,
    deadline: float = float("inf"),
) -> str:
    """Derive authority from verified manifests, never from cache metadata."""

    if not expected_generation_id or not expected_generation_manifest_sha256:
        raise InventoryError("generation identity is required for the trust anchor")
    try:
        generation = load_query_generation(Path(control_root), root_id)
    except FilesAdminError as error:
        raise InventoryError(
            f"canonical generation is unreadable: {error.code}"
        ) from error
    if (
        generation.selected.generation_id != expected_generation_id
        or generation.selected.generation_manifest_sha256
        != expected_generation_manifest_sha256
    ):
        raise InventoryError(
            "loader selection does not match the supplied generation identity"
        )
    return compute_expected_inventory_fingerprint(generation, deadline=deadline)


def compute_actual_inventory_fingerprint(
    snapshot_conn: sqlite3.Connection,
    *,
    deadline: float,
    progress_limit: int | None = None,
) -> str:
    return _fingerprint(
        snapshot_conn, canonical=False, deadline=deadline, progress_limit=progress_limit
    )


def verify_actual_inventory(
    snapshot_conn: sqlite3.Connection, expected_fingerprint: str, *, deadline: float
) -> None:
    if expected_fingerprint == _UNINITIALISED_FINGERPRINT:
        return
    actual = compute_actual_inventory_fingerprint(snapshot_conn, deadline=deadline)
    if actual != expected_fingerprint:
        raise InventoryTampered("files inventory differs from the canonical generation")


def verify_fts_trigram_consistency(
    snapshot_conn: sqlite3.Connection, *, deadline: float
) -> None:
    """Check content and multiplicity without returning unbounded bodies."""

    expected = """
        SELECT file_id, relative_path, body_nfkc_folded, COUNT(*) FROM files
        WHERE body IS NOT NULL GROUP BY file_id, relative_path, body_nfkc_folded
    """
    actual = """
        SELECT file_id, relative_path, body_nfkc_folded, COUNT(*) FROM files_fts_trigram
        GROUP BY file_id, relative_path, body_nfkc_folded
    """
    with _inventory_guard(snapshot_conn, deadline=deadline):
        for left, right in ((actual, expected), (expected, actual)):
            # Only a boolean crosses into Python, never attacker-controlled text.
            if snapshot_conn.execute(
                f"SELECT 1 FROM ({left} EXCEPT {right}) LIMIT 1"
            ).fetchone():
                raise InventoryTampered("files_fts_trigram content differs from files")


def verified_fts_candidate_ids(
    snapshot_conn: sqlite3.Connection,
    *,
    match_query: str,
    terms: list[str],
    deadline: float,
) -> set[str]:
    """Check MATCH recall against verified rows on the same bounded snapshot.

    Reading an FTS virtual table checks its content, but does not validate its
    shadow postings. Read-only SQLite cannot run the FTS integrity-check write
    command. A bounded substring probe therefore checks that MATCH has not lost
    any authoritative candidates. Extra candidates are filtered by the normal
    ranker. No index repair or write is attempted on the read path.
    """

    with _inventory_guard(snapshot_conn, deadline=deadline):
        candidates: set[str] = set()
        for (file_id,) in snapshot_conn.execute(
            "SELECT file_id FROM files_fts_trigram WHERE files_fts_trigram MATCH ?",
            (match_query,),
        ):
            _check_deadline(deadline)
            candidates.add(file_id)
        predicates = " AND ".join("instr(body_nfkc_folded, ?) > 0" for _ in terms)
        for (file_id,) in snapshot_conn.execute(
            f"SELECT file_id FROM files WHERE body_nfkc_folded IS NOT NULL AND {predicates}",
            tuple(terms),
        ):
            _check_deadline(deadline)
            if file_id not in candidates:
                raise InventoryTampered(
                    "FTS postings omit a canonical search candidate"
                )
        return candidates
