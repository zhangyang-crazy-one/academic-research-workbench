"""Canonical inventory fingerprinting for the files projection."""

from __future__ import annotations

import hashlib
import sqlite3
import struct
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from urllib.parse import quote

from arw.files import FilesQueryGeneration

from .ingest import _fold

MAX_INVENTORY_BODY_BYTES: Final[int] = 100 * 1024 * 1024

MAX_INVENTORY_ROW_BYTES: Final[int] = 2 * MAX_INVENTORY_BODY_BYTES + 1024

MAX_INVENTORY_AGGREGATE_BYTES: Final[int] = 256 * 1024 * 1024

MAX_INVENTORY_VM_STEPS: Final[int] = 50_000_000


class InventoryError(RuntimeError):
    """Base typed error for inventory fingerprinting failures."""

    code = "inventory_error"


class InventoryTampered(InventoryError):
    """The actual inventory differs from the expected fingerprint."""

    code = "inventory_tampered"


class InventoryBudgetExceeded(InventoryError):
    """A budget guard fired (body / row / aggregate / vm steps / deadline)."""

    code = "inventory_budget_exceeded"


_UNINITIALISED_FINGERPRINT: Final[str] = "uninitialised"


def _check_deadline(deadline: float) -> None:
    """Raise ``InventoryBudgetExceeded`` if the per-request deadline elapsed."""

    if deadline == float("inf"):
        return
    if time.monotonic() > deadline:
        raise InventoryBudgetExceeded(
            "inventory fingerprint exceeded the request deadline"
        )


def _check_body_size(column_label: str, payload: bytes) -> None:
    """Bound encoded values before adding them to the fingerprint."""

    if len(payload) - 1 > MAX_INVENTORY_BODY_BYTES:
        raise InventoryBudgetExceeded(
            f"{column_label} exceeds {MAX_INVENTORY_BODY_BYTES} bytes "
            f"(actual={len(payload)})"
        )


def _frame_value(
    value: str | int | None,
    *,
    column_label: str,
    aggregate_counter: list[int],
    deadline: float,
) -> bytes:
    """Serialise one column value as ``[8-byte BE length] [bytes]``."""

    _check_deadline(deadline)
    if value is None:
        framed = b"n"
    elif value == "":
        framed = b"s"
    elif isinstance(value, bool):
        raise InventoryError(f"unexpected bool column value ({column_label})")
    elif isinstance(value, int):
        if value < 0:
            raise InventoryError(
                f"unexpected negative integer ({column_label}): {value}"
            )
        framed = b"i" + struct.pack(">Q", value)
    elif isinstance(value, str):
        framed = b"s" + value.encode("utf-8")
    else:
        raise InventoryError(
            f"unsupported column type ({column_label}): {type(value).__name__}"
        )
    _check_body_size(column_label, framed)
    out = struct.pack(">Q", len(framed)) + framed
    aggregate_counter[0] += len(out)
    if aggregate_counter[0] > MAX_INVENTORY_AGGREGATE_BYTES:
        raise InventoryBudgetExceeded(
            f"aggregate inventory exceeds {MAX_INVENTORY_AGGREGATE_BYTES} bytes "
            f"(actual={aggregate_counter[0]})"
        )
    return out


def _frame_row(
    values: tuple[object, ...],
    *,
    column_labels: tuple[str, ...],
    aggregate_counter: list[int],
    deadline: float,
) -> bytes:
    """Frame one row by concatenating per-column framed values."""

    if len(values) != len(column_labels):
        raise InventoryError(
            f"row tuple has {len(values)} values; expected {len(column_labels)}"
        )
    pieces: list[bytes] = []
    row_bytes = 0
    for label, value in zip(column_labels, values):
        piece = _frame_value(
            value,  # type: ignore[arg-type]
            column_label=f"row.{label}",
            aggregate_counter=aggregate_counter,
            deadline=deadline,
        )
        row_bytes += len(piece)
        if row_bytes > MAX_INVENTORY_ROW_BYTES:
            raise InventoryBudgetExceeded(
                f"row exceeds {MAX_INVENTORY_ROW_BYTES} bytes (actual={row_bytes})"
            )
        pieces.append(piece)
    return b"".join(pieces)


@contextmanager
def _install_progress_handler(
    connection: sqlite3.Connection, *, progress_limit: int, deadline: float
):
    """Bound SQL work on a dedicated inventory connection."""
    steps = 0

    def interrupted() -> int:
        nonlocal steps
        steps += 1
        return int(steps > progress_limit or time.monotonic() > deadline)

    _check_deadline(deadline)
    connection.set_progress_handler(interrupted, 1)
    try:
        yield
        _check_deadline(deadline)
    except sqlite3.Error as error:
        if error.sqlite_errorcode == sqlite3.SQLITE_INTERRUPT:
            raise InventoryBudgetExceeded(
                "inventory SQL exceeded its budget"
            ) from error
        raise InventoryError(f"inventory database is unreadable: {error}") from error
    finally:
        connection.set_progress_handler(None, 0)


_CANONICAL_COLUMNS: Final[tuple[str, ...]] = (
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

_CACHE_COLUMNS: Final[tuple[str, ...]] = (
    "file_id",
    "relative_path",
    "file_type",
    "size_bytes",
    "source_digest",
    "index_state",
    "degraded_reason",
    "extraction_registration_sha256",
    "body",
    "body_nfkc_folded",
)


_SELECT_CANONICAL_SQL: Final[str] = (
    "SELECT file_id, relative_path, file_type, size_bytes, source_digest, "
    "index_state, degraded_reason, extraction_registration_sha256, body "
    "FROM files ORDER BY file_id"
)
_SELECT_CACHE_SQL: Final[str] = (
    "SELECT file_id, relative_path, file_type, size_bytes, source_digest, "
    "index_state, degraded_reason, extraction_registration_sha256, "
    "body, body_nfkc_folded FROM files ORDER BY file_id"
)


def _iter_rows_fingerprinted(
    connection: sqlite3.Connection,
    *,
    sql: str,
    columns: tuple[str, ...],
    hasher: hashlib._Hash,
    aggregate_counter: list[int],
    deadline: float,
    progress_limit: int,
) -> None:
    """Check byte lengths in SQLite before streaming and hashing each row."""
    with _install_progress_handler(
        connection, progress_limit=progress_limit, deadline=deadline
    ):
        # Return only lengths, not potentially oversized text, to Python.
        lengths_sql = ", ".join(
            f"CASE WHEN typeof({column}) = 'integer' THEN 8 "
            f"ELSE coalesce(length(CAST({column} AS BLOB)), 0) END"
            for column in columns
        )
        total = 0
        cursor = connection.execute(f"SELECT {lengths_sql} FROM files")
        try:
            for lengths in cursor:
                _check_deadline(deadline)
                if max(lengths) > MAX_INVENTORY_BODY_BYTES:
                    raise InventoryBudgetExceeded(
                        "inventory column exceeds byte budget"
                    )
                row_bytes = sum(lengths) + 9 * len(columns)
                if row_bytes > MAX_INVENTORY_ROW_BYTES:
                    raise InventoryBudgetExceeded("inventory row exceeds byte budget")
                total += row_bytes
                if total > MAX_INVENTORY_AGGREGATE_BYTES:
                    raise InventoryBudgetExceeded(
                        "inventory exceeds aggregate byte budget"
                    )
        finally:
            cursor.close()
        cursor = connection.execute(sql)
        try:
            for row in cursor:
                _check_deadline(deadline)
                if columns is _CANONICAL_COLUMNS:
                    body = row[8]
                    row = (*row, None if body is None else _fold(body))
                framed_row = _frame_row(
                    row,
                    column_labels=_CACHE_COLUMNS,
                    aggregate_counter=aggregate_counter,
                    deadline=deadline,
                )
                hasher.update(framed_row)
                _check_deadline(deadline)
        finally:
            cursor.close()


def compute_expected_inventory_fingerprint(
    generation: FilesQueryGeneration,
    *,
    deadline: float = float("inf"),
) -> str:
    """Derive the expected fingerprint from the canonical ``files.sqlite3``."""

    database_path = Path(generation.database_path)
    if database_path.is_symlink() or not database_path.is_file():
        raise InventoryError(f"canonical database is absent or unsafe: {database_path}")
    return _fingerprint_canonical_db(database_path, deadline=deadline)


def _fingerprint_canonical_db(database_path: Path, *, deadline: float) -> str:
    """Stream-hash the canonical ``files.sqlite3`` at ``database_path``."""

    connection = sqlite3.connect(f"file:{quote(str(database_path))}?mode=ro", uri=True)
    try:
        hasher = hashlib.sha256()
        aggregate_counter = [0]
        _iter_rows_fingerprinted(
            connection,
            sql=_SELECT_CANONICAL_SQL,
            columns=_CANONICAL_COLUMNS,
            hasher=hasher,
            aggregate_counter=aggregate_counter,
            deadline=deadline,
            progress_limit=MAX_INVENTORY_VM_STEPS,
        )
        return hasher.hexdigest()
    except sqlite3.Error as error:
        raise InventoryError(f"canonical database is unreadable: {error}") from error
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
    """Derive the inventory fingerprint via the LOADER-VERIFIED canonical DB."""

    if expected_generation_id is None or not expected_generation_id:
        raise InventoryError("expected_generation_id is required for trust anchor")
    if (
        expected_generation_manifest_sha256 is None
        or not expected_generation_manifest_sha256
    ):
        raise InventoryError(
            "expected_generation_manifest_sha256 is required for trust anchor"
        )

    from arw.files import FilesAdminError, load_query_generation

    try:
        generation = load_query_generation(Path(control_root), root_id)
    except FilesAdminError as error:
        raise InventoryError(
            f"canonical generation is unreadable: {error.code}: {error}"
        ) from error

    if generation.selected.generation_id != expected_generation_id:
        raise InventoryError(
            "loader selection generation_id does not match the supplied "
            f"expected identity: actual={generation.selected.generation_id!r} "
            f"expected={expected_generation_id!r}"
        )
    if (
        generation.selected.generation_manifest_sha256
        != expected_generation_manifest_sha256
    ):
        raise InventoryError(
            "loader selection generation_manifest_sha256 does not match "
            "the supplied expected identity: "
            f"actual={generation.selected.generation_manifest_sha256!r} "
            f"expected={expected_generation_manifest_sha256!r}"
        )

    return _fingerprint_canonical_db(generation.database_path, deadline=deadline)


def compute_actual_inventory_fingerprint(
    snapshot_conn: sqlite3.Connection,
    *,
    deadline: float,
    progress_limit: int | None = None,
) -> str:
    """Derive the actual fingerprint from the per-request snapshot."""

    hasher = hashlib.sha256()
    aggregate_counter = [0]
    try:
        _iter_rows_fingerprinted(
            snapshot_conn,
            sql=_SELECT_CACHE_SQL,
            columns=_CACHE_COLUMNS,
            hasher=hasher,
            aggregate_counter=aggregate_counter,
            deadline=deadline,
            progress_limit=(
                MAX_INVENTORY_VM_STEPS if progress_limit is None else progress_limit
            ),
        )
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error).lower():
            raise InventoryBudgetExceeded(
                f"SQLite progress handler aborted the inventory scan: {error}"
            ) from error
        raise
    return hasher.hexdigest()


def verify_actual_inventory(
    snapshot_conn: sqlite3.Connection,
    expected_fingerprint: str,
    *,
    deadline: float,
) -> None:
    """Compute actual fingerprint; raise :class:`InventoryTampered` on mismatch."""

    if expected_fingerprint == _UNINITIALISED_FINGERPRINT:
        return
    actual = compute_actual_inventory_fingerprint(snapshot_conn, deadline=deadline)
    if actual != expected_fingerprint:
        raise InventoryTampered(
            "files table inventory fingerprint differs from the canonical "
            f"generation fingerprint: actual={actual!r} "
            f"expected={expected_fingerprint!r}"
        )


def verify_fts_trigram_consistency(
    snapshot_conn: sqlite3.Connection, *, deadline: float
) -> None:
    """Compare FTS row multiplicities within the shared request budget."""
    fts = (
        "SELECT file_id, body_nfkc_folded, COUNT(*) FROM files_fts_trigram "
        "GROUP BY file_id, body_nfkc_folded"
    )
    files = (
        "SELECT file_id, body_nfkc_folded, COUNT(*) FROM files "
        "WHERE body IS NOT NULL GROUP BY file_id, body_nfkc_folded"
    )
    with _install_progress_handler(
        snapshot_conn, progress_limit=MAX_INVENTORY_VM_STEPS, deadline=deadline
    ):
        for left, right in ((fts, files), (files, fts)):
            cursor = snapshot_conn.execute(
                f"SELECT 1 FROM ({left} EXCEPT {right}) LIMIT 1"
            )
            try:
                if cursor.fetchone() is not None:
                    raise InventoryTampered(
                        "files_fts_trigram rows differ from the files inventory"
                    )
            finally:
                cursor.close()


__all__ = [
    "MAX_INVENTORY_AGGREGATE_BYTES",
    "MAX_INVENTORY_BODY_BYTES",
    "MAX_INVENTORY_ROW_BYTES",
    "MAX_INVENTORY_VM_STEPS",
    "InventoryBudgetExceeded",
    "InventoryError",
    "InventoryTampered",
    "anchor_via_loader",
    "compute_actual_inventory_fingerprint",
    "compute_expected_inventory_fingerprint",
    "verify_actual_inventory",
    "verify_fts_trigram_consistency",
]
