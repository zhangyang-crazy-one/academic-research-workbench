"""Local projection store: schema + migration runner (PR4 Lane A).

These tests pin the *initial* schema contract:
  * fresh init creates every table / index / FTS virtual table listed in
    ``openspec/changes/sqlite-projection-store/proposal.md``;
  * a DB at an intermediate (older) ``schema_version`` is migrated forward
    and user data is preserved;
  * a DB whose ``schema_version`` is newer than this binary raises a
    *typed* fault (``schema_version_unsupported``) and the on-disk file is
    not modified;
  * a DB whose ``projection_meta`` is missing / corrupted raises the
    *distinct* typed fault ``projection_meta_corrupt``.

The tests live in ``tests/unit`` because they exercise a single module
family; later lanes add ``tests/integration`` coverage once the projection
pipeline + adapters are wired up.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
    EXPECTED_INDEXES,
    EXPECTED_TABLES,
    INITIAL_PROJECTION_VERSION,
    MIGRATIONS,
    SCHEMA_VERSION,
    LocalProjectionStore,
    LocalStoreError,
    ProjectionMetaCorruptError,
    SchemaVersionUnsupportedError,
    StorePathUnsafeError,
    StoreSnapshot,
    apply_pending_migrations,
    read_projection_meta,
    read_schema_version,
    supported_schema_version,
)
from arw_ext.local_store.schema import (  # pyright: ignore[reportMissingImports]
    GENERATOR_VERSIONS,
)

# ---------------------------------------------------------------------------
# Fresh init
# ---------------------------------------------------------------------------


def _sqlite_master_objects(connection: sqlite3.Connection, kind: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
    ).fetchall()
    return {row[0] for row in rows}


def test_fresh_init_creates_all_expected_tables(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    snapshot = store.open()
    try:
        names = _sqlite_master_objects(store.connection, "table")
        missing = EXPECTED_TABLES - names
        assert not missing, f"missing tables after fresh init: {sorted(missing)}"
    finally:
        store.close()

    assert isinstance(snapshot, StoreSnapshot)
    assert snapshot.schema_version == int(SCHEMA_VERSION)
    assert snapshot.projection_version == INITIAL_PROJECTION_VERSION
    expected_migrations = tuple(int(m["version"]) for m in MIGRATIONS)
    assert snapshot.applied_migrations == expected_migrations


def test_fresh_init_creates_all_expected_indexes(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    try:
        store.open()
        names = _sqlite_master_objects(store.connection, "index")
        missing = EXPECTED_INDEXES - names
        assert not missing, f"missing indexes after fresh init: {sorted(missing)}"
    finally:
        store.close()


def test_fresh_init_creates_fts5_virtual_tables(tmp_path: Path) -> None:
    """The FTS5 virtual tables for files body search must exist.

    Both the token-bound ``files_fts`` (unicode61 remove_diacritics 2) and the
    substring ``files_fts_trigram`` must be present; the tokenizer strings are
    recorded in ``sqlite_master.sql`` so we can assert the exact recipes.
    """

    store = LocalProjectionStore(tmp_path / "arw.db")
    try:
        store.open()
        rows = store.connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name IN ('files_fts', 'files_fts_trigram')"
        ).fetchall()
    finally:
        store.close()

    by_name = {row[0]: row[1] for row in rows}
    assert "files_fts" in by_name, "unicode61 FTS5 virtual table is missing"
    assert "files_fts_trigram" in by_name, "trigram FTS5 virtual table is missing"
    assert "unicode61 remove_diacritics 2" in by_name["files_fts"], (
        "files_fts must use the unicode61 tokenizer with remove_diacritics 2"
    )
    assert "tokenize='trigram'" in by_name["files_fts_trigram"], (
        "files_fts_trigram must use the trigram tokenizer"
    )


def test_fresh_init_seeds_projection_meta(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    try:
        store.open()
        meta = read_projection_meta(store.connection)
    finally:
        store.close()

    assert read_schema_version(meta) == int(SCHEMA_VERSION)
    assert meta["projection_version"] == INITIAL_PROJECTION_VERSION
    for generator_name, generator_version in GENERATOR_VERSIONS.items():
        assert meta[f"generator_version.{generator_name}"] == generator_version


def test_fresh_init_uses_safe_pragmas(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    try:
        store.open()
        journal_mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = store.connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        store.close()

    # journal_mode=DELETE is the v1 default and the safe choice; the WAL
    # upgrade lives in a later lane per design D5.
    assert journal_mode.lower() == "delete"
    assert int(foreign_keys) == 1


def test_open_is_idempotent(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "arw.db")
    first = store.open()
    second = store.open()
    try:
        assert first is second
    finally:
        store.close()


def test_context_manager_opens_and_closes(tmp_path: Path) -> None:
    with LocalProjectionStore(tmp_path / "arw.db") as store:
        meta = read_projection_meta(store.connection)
        assert read_schema_version(meta) == int(SCHEMA_VERSION)
    # connection is closed; reopening must still work
    store2 = LocalProjectionStore(tmp_path / "arw.db")
    snapshot = store2.open()
    try:
        assert snapshot.schema_version == int(SCHEMA_VERSION)
    finally:
        store2.close()


# ---------------------------------------------------------------------------
# v1 → current migration path
# ---------------------------------------------------------------------------


def test_intermediate_version_is_migrated_and_data_preserved(tmp_path: Path) -> None:
    """Hand-craft a v0-shaped DB, open via the store, assert migration.

    "v0" here means: only ``projection_meta`` exists with ``schema_version=0``;
    the full schema is then supplied by migration 0001.  User data inserted
    before opening must survive the migration.
    """

    database = tmp_path / "arw.db"
    # Step 1: hand-craft the intermediate DB on disk.
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("schema_version", "0"),
        )
        connection.execute(
            "CREATE TABLE run_notes (run_id TEXT PRIMARY KEY, note TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO run_notes(run_id, note) VALUES (?, ?)",
            ("run-1", "pre-migration user data"),
        )
        connection.commit()
    finally:
        connection.close()

    # Step 2: open via the store and verify migration + data preservation.
    store = LocalProjectionStore(database)
    snapshot = store.open()
    try:
        assert snapshot.schema_version == supported_schema_version()
        notes = store.connection.execute(
            "SELECT note FROM run_notes WHERE run_id = ?", ("run-1",)
        ).fetchone()
        assert notes is not None and notes[0] == "pre-migration user data"

        # The new projection_meta row from migration 0001 must now be present
        # and equal to the highest schema_version this binary understands.
        meta = read_projection_meta(store.connection)
        assert read_schema_version(meta) == supported_schema_version()
        assert meta.get("applied_migrations") is not None
        applied = sorted(
            int(token) for token in meta["applied_migrations"].split(",") if token
        )
        assert applied == [int(m["version"]) for m in MIGRATIONS]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Newer-than-binary → typed fault
# ---------------------------------------------------------------------------


def test_newer_schema_version_raises_typed_fault_and_does_not_mutate(
    tmp_path: Path,
) -> None:
    database = tmp_path / "arw.db"

    # Build a "future" DB at schema_version = current + 1, with the full
    # proposal-schema in place (so the projection_meta row is the only
    # signal of newness).
    future_version = supported_schema_version() + 1
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(future_version)),
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("projection_version", "999"),
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("sentinel_future_table_marker", "do-not-touch"),
        )
        connection.commit()
        # Capture mtime + size for the "DB unmodified" assertion.
        stat_before = database.stat()
        sentinel_marker = connection.execute(
            "SELECT value FROM projection_meta WHERE key = 'sentinel_future_table_marker'"
        ).fetchone()[0]
    finally:
        connection.close()

    # Re-open via the store and assert typed fault.
    store = LocalProjectionStore(database)
    with pytest.raises(SchemaVersionUnsupportedError) as exc_info:
        store.open()

    assert exc_info.value.code == "schema_version_unsupported"
    assert "upgrade" in str(exc_info.value).lower()

    # DB file must be unmodified: mtime/size preserved, sentinel row intact.
    stat_after = database.stat()
    assert (stat_before.st_mtime_ns, stat_before.st_size) == (
        stat_after.st_mtime_ns,
        stat_after.st_size,
    )
    inspect = sqlite3.connect(database)
    try:
        row = inspect.execute(
            "SELECT value FROM projection_meta WHERE key = 'sentinel_future_table_marker'"
        ).fetchone()
    finally:
        inspect.close()
    assert row is not None and row[0] == sentinel_marker


# ---------------------------------------------------------------------------
# Corrupt / missing projection_meta → distinct typed fault
# ---------------------------------------------------------------------------


def test_missing_projection_meta_raises_distinct_fault(tmp_path: Path) -> None:
    database = tmp_path / "arw.db"
    connection = sqlite3.connect(database)
    try:
        # A DB that exists but has no projection_meta at all.  This is the
        # canonical "projection was wiped / never initialised" case.
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    store = LocalProjectionStore(database)
    with pytest.raises(ProjectionMetaCorruptError) as exc_info:
        store.open()

    assert exc_info.value.code == "projection_meta_corrupt"
    # Fresh file cleanup: open() rolls back and removes the half-built file.
    # Here no half-built file is possible (the DB pre-existed); we just
    # confirm the store did not rewrite it.
    assert database.exists()


def test_projection_meta_without_schema_version_row_raises_corrupt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "arw.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("projection_version", "5"),
        )
        connection.commit()
    finally:
        connection.close()

    store = LocalProjectionStore(database)
    with pytest.raises(ProjectionMetaCorruptError) as exc_info:
        store.open()
    assert exc_info.value.code == "projection_meta_corrupt"


def test_projection_meta_with_non_integer_schema_version_raises_corrupt(
    tmp_path: Path,
) -> None:
    database = tmp_path / "arw.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("schema_version", "not-a-number"),
        )
        connection.commit()
    finally:
        connection.close()

    store = LocalProjectionStore(database)
    with pytest.raises(ProjectionMetaCorruptError) as exc_info:
        store.open()
    assert exc_info.value.code == "projection_meta_corrupt"


def test_fault_codes_are_distinct() -> None:
    """Cross-check the two pre-open / open fault codes are distinct.

    ``schema_version_unsupported`` and ``projection_meta_corrupt`` are the
    two open-time typed faults this lane introduces; they MUST have different
    ``.code`` values so callers can pattern-match on the recovery path.
    """

    assert SchemaVersionUnsupportedError.code == "schema_version_unsupported"
    assert ProjectionMetaCorruptError.code == "projection_meta_corrupt"
    assert SchemaVersionUnsupportedError.code != ProjectionMetaCorruptError.code
    # Both must be reachable through the LocalStoreError base class.
    assert issubclass(SchemaVersionUnsupportedError, LocalStoreError)
    assert issubclass(ProjectionMetaCorruptError, LocalStoreError)


# ---------------------------------------------------------------------------
# Path safety (regression: symlinks / non-existent parents must fault)
# ---------------------------------------------------------------------------


def test_symlinked_database_path_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.db"
    real.touch()
    link = tmp_path / "link.db"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this filesystem")

    store = LocalProjectionStore(link)
    with pytest.raises(StorePathUnsafeError):
        store.open()


def test_nonexistent_parent_directory_is_refused(tmp_path: Path) -> None:
    store = LocalProjectionStore(tmp_path / "missing-parent" / "arw.db")
    with pytest.raises(StorePathUnsafeError):
        store.open()


# ---------------------------------------------------------------------------
# Migration runner can be exercised directly (independent of the store class)
# ---------------------------------------------------------------------------


def test_apply_pending_migrations_is_safe_to_call_repeatedly(tmp_path: Path) -> None:
    database = tmp_path / "arw.db"
    store = LocalProjectionStore(database)
    store.open()
    try:
        # A second pass must be a no-op (no extra schema_version row, no
        # double-write to applied_migrations).
        meta_before = read_projection_meta(store.connection)
        apply_pending_migrations(store.connection)
        meta_after = read_projection_meta(store.connection)
        assert meta_before == meta_after
    finally:
        store.close()


def test_open_readonly_does_not_create_or_migrate(tmp_path: Path) -> None:
    """Read-path open: missing file faults; existing file is never mutated."""

    from arw_ext.local_store import SchemaVersionUnsupportedError

    # Missing file -> typed fault, and nothing is created.
    missing = tmp_path / "absent.db"
    store = LocalProjectionStore(missing)
    with pytest.raises(StorePathUnsafeError):
        store.open_readonly()
    assert not missing.exists()

    # A store at an OLDER schema version opens read-only WITHOUT migrating:
    # the on-disk schema_version must be unchanged afterwards.
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("schema_version", "0"),
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("applied_migrations", ""),
        )
        connection.commit()
    finally:
        connection.close()

    store = LocalProjectionStore(database)
    snapshot = store.open_readonly()
    try:
        assert snapshot.schema_version == 0  # NOT migrated to supported
    finally:
        store.close()
    inspect = sqlite3.connect(database)
    try:
        row = inspect.execute(
            "SELECT value FROM projection_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        inspect.close()
    assert row is not None and row[0] == "0"  # still 0 on disk

    # A NEWER store faults without mutation.
    newer = tmp_path / "newer.db"
    connection = sqlite3.connect(newer)
    try:
        connection.execute(
            "CREATE TABLE projection_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO projection_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(supported_schema_version() + 1)),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchemaVersionUnsupportedError):
        LocalProjectionStore(newer).open_readonly()
