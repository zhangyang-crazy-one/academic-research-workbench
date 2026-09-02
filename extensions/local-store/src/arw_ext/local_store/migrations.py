"""Ordered migration runner for the local projection store.

The runner is deliberately small: a numbered SQL script per migration, all
applied in a single transaction; one row per applied step recorded in
``projection_meta.applied_migrations``.

Hard guarantees (enforced by tests in ``tests/unit/test_local_store_schema.py``):

* Opening a database whose ``schema_version`` is **strictly greater** than
  the binary's maximum raises :class:`SchemaVersionUnsupportedError` and
  mutates nothing — no DDL is executed, no transaction is started.
* Opening a database whose ``projection_meta`` row exists but is missing the
  ``schema_version`` key, or carries a non-integer value, raises
  :class:`ProjectionMetaCorruptError` (distinct code, distinct recovery).
* Opening a database whose ``projection_meta`` *table* is missing is treated
  as a fresh-init signal (the table is created by migration 0001) — not a
  corrupt-fault.  This keeps the runner usable as the entry point of a
  first-open path.
* Each migration is applied inside its own transaction; a failure rolls back
  to the previous schema version.  The runner never partially applies.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Final

from .errors import (
    MigrationFailedError,
    ProjectionMetaCorruptError,
    SchemaVersionUnsupportedError,
)
from .schema import MIGRATIONS, projection_meta_initial_rows

#: ``projection_meta`` key whose value is the latest applied ``schema_version``
#: as a string.  Read first on every open; absence is a corrupt-fault *only
#: when the projection_meta table itself exists* — if the table is missing,
#: the runner treats the DB as fresh and lets migration 0001 create it.
SCHEMA_VERSION_KEY: Final = "schema_version"

#: ``projection_meta`` key whose value is a comma-separated list of migration
#: indices that have already been applied.  Used to detect "fresh init" and
#: to guard against double-application.
APPLIED_MIGRATIONS_KEY: Final = "applied_migrations"

#: Marker row that names the project-specific table the migration runner
#: trusts to exist; tests assert its presence post-init.
MIGRATIONS_TABLE_MARKER: Final = "projection_meta"


def _int_version(value: str) -> int:
    """Parse a numeric ``schema_version``.  Raises if non-integer or negative."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ProjectionMetaCorruptError(
            f"schema_version is not an integer: {value!r}"
        ) from error
    if parsed < 0:
        raise ProjectionMetaCorruptError(
            f"schema_version must be non-negative: {parsed}"
        )
    return parsed


def read_schema_version(meta_rows: Mapping[str, str]) -> int:
    """Read the ``schema_version`` from a ``projection_meta`` snapshot.

    Returns the parsed integer.  Raises :class:`ProjectionMetaCorruptError`
    when the key is absent or non-integer — distinct from
    :class:`SchemaVersionUnsupportedError`, which is reserved for the
    "version exists but is newer than this binary" case.
    """

    raw = meta_rows.get(SCHEMA_VERSION_KEY)
    if raw is None:
        raise ProjectionMetaCorruptError(
            "projection_meta is missing the schema_version row"
        )
    return _int_version(raw)


def supported_schema_version() -> int:
    """The highest ``schema_version`` the current binary understands.

    Returned as an int to match the on-disk representation.  Add new entries
    to :data:`arw_ext.local_store.schema.MIGRATIONS` and bump the
    ``SCHEMA_VERSION`` constant when introducing a new migration.
    """

    return int(MIGRATIONS[-1]["version"])


def _projection_meta_exists(connection: sqlite3.Connection) -> bool:
    """Return True if the ``projection_meta`` table is present in this DB.

    Used to disambiguate "fresh init" (table missing) from "corrupt" (table
    present but rows unreadable / incomplete).
    """

    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("projection_meta",),
    ).fetchone()
    return row is not None


def read_projection_meta(connection: sqlite3.Connection) -> dict[str, str]:
    """Snapshot every ``projection_meta`` row into a dict.

    Caller decides what to do with a missing table — the migration runner uses
    :func:`_projection_meta_exists` to distinguish fresh init from
    corruption.  Public callers that want "must have a projection_meta" should
    call :func:`read_schema_version` after asserting the table exists.
    """

    rows = connection.execute("SELECT key, value FROM projection_meta").fetchall()
    return dict(rows)


def applied_migrations(meta_rows: Mapping[str, str]) -> list[int]:
    """Return the list of migration indices already applied to this DB.

    The list is sorted ascending; duplicates and invalid tokens are tolerated
    by skipping silently (the next open will re-apply anything missing).  An
    absent key yields an empty list — the "fresh init" path.
    """

    raw = meta_rows.get(APPLIED_MIGRATIONS_KEY)
    if not raw:
        return []
    out: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            # A malformed token means the meta row was hand-edited or
            # torn; never silently drop it — the contiguity check depends
            # on exact membership (review P2).
            raise ProjectionMetaCorruptError(
                f"applied_migrations contains a non-integer token: {token!r}"
            ) from None
    return sorted(out)


def _record_applied(connection: sqlite3.Connection, applied: Iterable[int]) -> None:
    """Persist the canonical "applied migrations" list back to ``projection_meta``.

    Idempotent within a single open: the runner writes once at the end of
    the run, after the final ``COMMIT``.
    """

    value = ",".join(str(index) for index in sorted(applied))
    connection.execute(
        "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (APPLIED_MIGRATIONS_KEY, value),
    )


def _seed_initial_meta(connection: sqlite3.Connection) -> None:
    """Insert the canonical ``projection_meta`` rows for a fresh DB.

    Only called on the "fresh init" path; later migrations never touch this
    function.  Errors from this seed are surfaced as
    :class:`MigrationFailedError` because the init migration is itself a
    migration.
    """

    try:
        connection.executemany(
            "INSERT OR REPLACE INTO projection_meta(key, value) VALUES (?, ?)",
            projection_meta_initial_rows(),
        )
    except sqlite3.Error as error:
        raise MigrationFailedError(
            f"failed to seed projection_meta rows: {error}"
        ) from error


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a multi-statement DDL script INSIDE the caller's transaction.

    ``sqlite3.Connection.executescript`` issues an implicit COMMIT before
    running, which would break the migration runner's all-or-nothing
    guarantee.  Our scripts are plain DDL (no semicolons inside statements),
    so splitting on ``;`` and executing statement-by-statement is exact.
    """

    # Strip ``--`` comment lines first: naive ``;`` splitting otherwise
    # breaks on semicolons inside comments.  Our DDL contains no string
    # literals with ``--`` or ``;`` so line-stripping + split is exact.
    code_lines = []
    for line in script.splitlines():
        code, _, _comment = line.partition("--")
        code_lines.append(code)
    for statement in "\n".join(code_lines).split(";"):
        stripped = statement.strip()
        if stripped:
            # pi-lens-ignore: python-sql-injection
            connection.execute(stripped)


def apply_pending_migrations(connection: sqlite3.Connection) -> int:
    """Apply every migration whose index is not yet recorded.

    Returns the highest schema version applied during this call (equal to
    :func:`supported_schema_version` after a fresh init).  Raises the typed
    faults defined in :mod:`arw_ext.local_store.errors` for the documented
    failure modes; never returns ``0`` after a successful run on a DB that
    started non-empty.

    Callers MUST run this inside a transaction; the runner does not begin or
    commit one of its own.  ``store.open()`` wraps the call in
    ``BEGIN`` / ``COMMIT`` so a mid-migration failure rolls back cleanly.

    The caller signals "fresh init" by passing ``is_fresh=True`` when the
    underlying file did not exist before opening.  Without that signal a
    missing ``projection_meta`` table is treated as a corrupt-fault (the
    "DB exists but is missing the metadata table" case).
    """

    supported = supported_schema_version()
    has_meta_table = _projection_meta_exists(connection)

    if not has_meta_table:
        # Caller did not flag this as fresh init → missing meta is corruption.
        # The store.open() entry point prevents reaching this branch for a
        # truly fresh file by passing is_fresh=True; the no-flag overload
        # preserves the strict semantics documented in design.md.
        raise ProjectionMetaCorruptError(
            "projection_meta table is missing on an existing database"
        )

    # Existing DB with a projection_meta table: read first, then decide.
    try:
        meta_rows = read_projection_meta(connection)
    except sqlite3.Error as error:
        raise ProjectionMetaCorruptError(
            f"projection_meta is unreadable: {error}"
        ) from error
    on_disk_version = read_schema_version(meta_rows)

    if on_disk_version > supported:
        raise SchemaVersionUnsupportedError(
            f"database schema_version={on_disk_version} is newer than the "
            f"supported maximum {supported}; upgrade the workbench binary "
            f"before opening this store"
        )

    already_applied = applied_migrations(meta_rows)
    # The recorded migration list must be exactly the contiguous prefix
    # 1..on_disk_version; anything else means the meta rows disagree with
    # the actual schema state (e.g. a failed hand-edit) and we refuse to
    # guess — the operator rebuilds the projection from canonical evidence.
    expected_prefix = list(range(1, on_disk_version + 1))
    if already_applied != expected_prefix:
        raise ProjectionMetaCorruptError(
            f"applied_migrations {already_applied} is not the contiguous "
            f"prefix 1..{on_disk_version}; the store metadata is inconsistent"
        )
    pending = [
        migration
        for migration in MIGRATIONS
        # pi-lens-ignore: unchecked-throwing-call-python
        if int(migration["version"]) > on_disk_version
    ]
    if not pending:
        # Existing DB at supported version: nothing to do.  Schema_version
        # row already present from prior runs; we just confirm it's at the
        # expected value.
        if on_disk_version != supported:
            # The recorded schema_version disagrees with the migrations table.
            # Treat as corruption so the operator rebuilds rather than
            # silently re-applying.
            raise ProjectionMetaCorruptError(
                f"schema_version={on_disk_version} is below the supported "
                f"maximum {supported} but no pending migrations are recorded"
            )
        return on_disk_version

    try:
        for migration in pending:
            _execute_script(connection, str(migration["sql"]))
        # Mark migrations applied (idempotent merge).
        merged = sorted(
            set(already_applied) | {int(migration["version"]) for migration in pending}
        )
        _record_applied(connection, merged)
        # Reflect the new schema_version.
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION_KEY, str(supported)),
        )
    except MigrationFailedError:
        raise
    except sqlite3.Error as error:
        raise MigrationFailedError(f"migration failed: {error}") from error
    return supported


def initialize_fresh(connection: sqlite3.Connection) -> int:
    """Initialise a brand-new DB: run every migration in order + seed meta.

    Equivalent to ``apply_pending_migrations`` on a DB without a
    ``projection_meta`` table; split out so :class:`LocalProjectionStore` can
    disambiguate "fresh init" from "corrupt existing DB".  The caller is
    responsible for the wrapping transaction.
    """

    supported = supported_schema_version()
    if _projection_meta_exists(connection):
        raise ProjectionMetaCorruptError(
            "initialize_fresh refused: projection_meta table already exists"
        )
    try:
        for migration in MIGRATIONS:
            _execute_script(connection, str(migration["sql"]))
        _seed_initial_meta(connection)
        _record_applied(
            connection,
            [int(migration["version"]) for migration in MIGRATIONS],
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION_KEY, str(supported)),
        )
    except MigrationFailedError:
        raise
    except sqlite3.Error as error:
        raise MigrationFailedError(f"migration failed: {error}") from error
    return supported


__all__ = [
    "APPLIED_MIGRATIONS_KEY",
    "MIGRATIONS_TABLE_MARKER",
    "SCHEMA_VERSION_KEY",
    "applied_migrations",
    "apply_pending_migrations",
    "initialize_fresh",
    "read_projection_meta",
    "read_schema_version",
    "supported_schema_version",
]
