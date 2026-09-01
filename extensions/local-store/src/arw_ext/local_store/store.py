"""Open / close / introspect the local SQLite projection store.

This is the thin API surface Lane A of PR4 exposes; Lane B (store adapters)
and Lane C (projection pipeline) extend it with read/write paths and the
apply/rebuild machinery.  The class is deliberately minimal so the schema
landed in this lane is testable in isolation.

Concurrency contract:

* The store opens with ``PRAGMA journal_mode=DELETE`` (NOT WAL — that is a
  later lane per design D5); foreign keys are enabled.
* The connection is private to the instance; ``close()`` is idempotent.
* No ``PRAGMA locking_mode`` overrides; SQLite defaults apply (the v1
  ``graph_store.py`` / ``files.py`` precedent uses the same defaults).
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .errors import (
    LocalStoreError,
    StoreOpenError,
    StorePathUnsafeError,
)
from .migrations import (
    read_projection_meta,
    read_schema_version,
)
from .schema import SCHEMA_VERSION

#: File mode for newly created stores (0600 — parent-only).  Matches the
#: v1 graph-store atomic write convention.
DEFAULT_FILE_MODE: Final = 0o600

#: SQLite open flags applied via ``connect``: ``URI`` lets us pass
#: ``?mode=ro`` for read-only query connections later in the pipeline.
SQLITE_OPEN_FLAGS: Final = 0


@dataclass(frozen=True)
class StoreSnapshot:
    """Read-only view of the store's identity at open time."""

    schema_version: int
    projection_version: str
    generator_versions: Mapping[str, str]
    applied_migrations: tuple[int, ...]
    database_path: Path


def _resolve_database_path(path: Path) -> Path:
    """Resolve and validate a user-supplied database path.

    Rejects symlinks, non-existent parents, and any path whose parent is a
    symlink — the v1 stores treat those as unsafe for atomic replacement.
    """

    resolved = path if path.is_absolute() else Path.cwd() / path
    if resolved.is_symlink():
        raise StorePathUnsafeError(f"database path is a symlink: {resolved}")
    if resolved.parent.exists() and resolved.parent.is_symlink():
        raise StorePathUnsafeError(
            f"database parent directory is a symlink: {resolved.parent}"
        )
    return resolved


class LocalProjectionStore:
    """Wrapper around one SQLite connection backed by the migration runner.

    The instance is the unit of access for the projection store; readers and
    writers hold a long-lived instance, the migration runner runs once on
    :meth:`open`, and the underlying connection is reused for every
    subsequent operation.  Callers MUST NOT cache the raw connection.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._connection: sqlite3.Connection | None = None
        self._snapshot: StoreSnapshot | None = None

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise StoreOpenError(
                "store is not open; call open() before reading connection"
            )
        return self._connection

    @property
    def snapshot(self) -> StoreSnapshot:
        if self._snapshot is None:
            raise StoreOpenError(
                "store is not open; call open() before reading snapshot"
            )
        return self._snapshot

    def open(self) -> StoreSnapshot:
        """Open or create the store and run pending migrations.

        On a fresh database: creates the file with ``0600`` mode, applies the
        initial schema, seeds ``projection_meta``, and returns the snapshot.
        On an existing database: validates the recorded ``schema_version``,
        raises a typed fault when it is newer than this binary, otherwise
        applies pending migrations and returns the snapshot.

        Idempotent: a second ``open()`` on an already-open store is a no-op.
        """

        if self._connection is not None:
            assert self._snapshot is not None
            return self._snapshot

        # Validate the path now that we know whether the caller wants to
        # create or open an existing file.  Path resolution rejects symlinks
        # and symlink-parents; the missing-parent branch is folded in here.
        resolved = _resolve_database_path(self._database_path)
        if not resolved.exists() and not resolved.parent.exists():
            raise StorePathUnsafeError(
                f"database parent directory does not exist: {resolved.parent}"
            )
        self._database_path = resolved

        is_fresh = not self._database_path.exists()
        if is_fresh:
            try:
                self._database_path.touch(mode=DEFAULT_FILE_MODE)
            except OSError as error:
                raise StoreOpenError(
                    f"failed to create database file: {error}"
                ) from error
        else:
            if self._database_path.is_symlink():
                raise StorePathUnsafeError(
                    f"database path is a symlink: {self._database_path}"
                )
            if not self._database_path.is_file():
                raise StorePathUnsafeError(
                    f"database path is not a regular file: {self._database_path}"
                )

        try:
            connection = sqlite3.connect(str(self._database_path))
        except sqlite3.Error as error:
            raise StoreOpenError(f"sqlite connect failed: {error}") from error

        try:
            # journal_mode=DELETE is the v1 default and the safest choice for
            # network filesystems; the WAL upgrade lives in a later lane.
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as error:
            connection.close()
            raise StoreOpenError(f"failed to apply default pragmas: {error}") from error

        # Migrations run inside one transaction so a failure rolls back to
        # the pre-open state.  apply_pending_migrations also seeds the
        # projection_meta rows on the fresh-init path.
        try:
            connection.execute("BEGIN")
            from .migrations import apply_pending_migrations, initialize_fresh

            if is_fresh:
                initialize_fresh(connection)
            else:
                apply_pending_migrations(connection)
            connection.execute("COMMIT")
        except LocalStoreError:
            connection.execute("ROLLBACK")
            connection.close()
            # Best-effort cleanup of an uninitialised fresh file so the next
            # open() can start clean.  On any open failure the operator
            # receives the typed fault — they can manually inspect/remove
            # the half-built file if desired.
            if is_fresh and self._database_path.exists():
                with contextlib.suppress(OSError):
                    self._database_path.unlink()
            raise
        except sqlite3.Error as error:
            with contextlib.suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
            connection.close()
            if is_fresh and self._database_path.exists():
                with contextlib.suppress(OSError):
                    self._database_path.unlink()
            raise StoreOpenError(f"failed to run migrations: {error}") from error

        # Capture the snapshot now that we know the schema_version on disk.
        meta_rows = read_projection_meta(connection)
        schema_version = read_schema_version(meta_rows)
        from .migrations import applied_migrations

        applied = tuple(applied_migrations(meta_rows))
        projection_version = meta_rows.get("projection_version", "0")
        generator_versions: dict[str, str] = {
            key.removeprefix("generator_version."): value
            for key, value in meta_rows.items()
            if key.startswith("generator_version.")
        }
        self._connection = connection
        self._snapshot = StoreSnapshot(
            schema_version=schema_version,
            projection_version=projection_version,
            generator_versions=generator_versions,
            applied_migrations=applied,
            database_path=self._database_path,
        )
        return self._snapshot

    def close(self) -> None:
        """Close the underlying SQLite connection.  Idempotent."""

        if self._connection is None:
            return
        try:
            self._connection.close()
        finally:
            self._connection = None
            self._snapshot = None

    def __enter__(self) -> LocalProjectionStore:
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def assert_open(self) -> None:
        """Raise :class:`StoreOpenError` if the store has not been opened."""

        if self._connection is None or self._snapshot is None:
            raise StoreOpenError(
                "store is not open; call open() before accessing the database"
            )


def current_schema_version() -> str:
    """Expose the current :data:`SCHEMA_VERSION` for status / receipts."""

    return SCHEMA_VERSION


__all__ = [
    "DEFAULT_FILE_MODE",
    "SQLITE_OPEN_FLAGS",
    "LocalProjectionStore",
    "StoreSnapshot",
    "current_schema_version",
]
