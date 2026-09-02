"""Typed error surface for the local SQLite projection store.

Every error carries a stable ``code`` plus a human-readable ``message``; the
codes are the wire contract the CLI / orchestration layers pattern-match on.
Codes are deliberately fine-grained so that callers can distinguish
recoverable migration conditions from operator-action faults.

The class hierarchy is intentionally flat: callers should branch on ``code``,
not on ``type(...)``.  The shared base class only exists so that test and
boundary code can ``except LocalStoreError`` without enumerating every subtype.
"""

from __future__ import annotations


class LocalStoreError(RuntimeError):
    """Base class for every typed fault the local store can raise.

    Subclasses override the ``code`` class variable to advertise their
    stable wire contract; the base ``__init__`` derives ``self.code`` from
    the subclass when the caller omits it.  Callers may always pass an
    explicit ``code`` to override (useful for parameterised corruption
    messages that vary across rows).
    """

    code: str = "local_store_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        if code is not None:
            self.code = code
        super().__init__(message)


class SchemaVersionUnsupportedError(LocalStoreError):
    """The on-disk ``schema_version`` is newer than this binary understands.

    Opening a newer DB is a HARD fault: the store mutates nothing (no migration
    is run) and surfaces ``schema_version_unsupported`` so the operator knows
    to upgrade the workbench binary rather than downgrade the store.
    """

    code: str = "schema_version_unsupported"


class ProjectionMetaCorruptError(LocalStoreError):
    """``projection_meta`` is missing, malformed, or contains no schema row.

    Distinct from ``SchemaVersionUnsupportedError``: this means we cannot even
    answer a schema version question.  Operators must rebuild the projection
    from canonical evidence; the file is not auto-truncated.
    """

    code: str = "projection_meta_corrupt"


class MigrationFailedError(LocalStoreError):
    """A migration step raised during application.

    The store rolls back its open transaction and leaves the DB in its prior
    state.  Caller must surface the failing migration index; never retry
    blindly — the migration code is versioned and not idempotent on retry.
    """

    code: str = "migration_failed"


class StorePathUnsafeError(LocalStoreError):
    """The requested store path is a symlink, a non-directory, or unwritable."""

    code: str = "store_path_unsafe"


class StoreOpenError(LocalStoreError):
    """Generic open-time failure (corrupt header, unreadable file, etc.)."""

    code: str = "store_open_failed"


FAULT_CODES: frozenset[str] = frozenset(
    {
        SchemaVersionUnsupportedError.code,
        ProjectionMetaCorruptError.code,
        MigrationFailedError.code,
        StorePathUnsafeError.code,
        StoreOpenError.code,
    }
)

__all__ = [
    "FAULT_CODES",
    "LocalStoreError",
    "MigrationFailedError",
    "ProjectionMetaCorruptError",
    "SchemaVersionUnsupportedError",
    "StoreOpenError",
    "StorePathUnsafeError",
]
