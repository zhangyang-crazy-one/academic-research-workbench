"""Public surface of the bundled local SQLite projection store extension.

This package is a thin layer on top of an append-only ledger + artefact
manifests; it is not a source of canonical truth.  The kernel never imports
this package; composition-root code may import individual adapters when
provisioning the ``files.local`` / ``knowledge.graph`` capabilities.

Lane A (PR4) of the SQLite projection store change exposes:

* :data:`SCHEMA_VERSION` — the current schema version constant.
* :data:`MIGRATIONS` — the ordered migration registry.
* :class:`LocalProjectionStore` — the open/close API plus the migration
  runner boundary.
* :class:`StoreSnapshot` — read-only view of the post-open store identity.
* :class:`LocalStoreError` and its typed subclasses — the fault surface
  callers pattern-match on.
"""

from __future__ import annotations

from .errors import (
    FAULT_CODES,
    LocalStoreError,
    MigrationFailedError,
    ProjectionMetaCorruptError,
    SchemaVersionUnsupportedError,
    StoreOpenError,
    StorePathUnsafeError,
)
from .migrations import (
    APPLIED_MIGRATIONS_KEY,
    SCHEMA_VERSION_KEY,
    applied_migrations,
    apply_pending_migrations,
    initialize_fresh,
    read_projection_meta,
    read_schema_version,
    supported_schema_version,
)
from .schema import (
    EXPECTED_INDEXES,
    EXPECTED_TABLES,
    GENERATOR_VERSIONS,
    INITIAL_PROJECTION_VERSION,
    MIGRATIONS,
    SCHEMA_VERSION,
    projection_meta_initial_rows,
)
from .store import (
    DEFAULT_FILE_MODE,
    LocalProjectionStore,
    StoreSnapshot,
    current_schema_version,
)

__all__ = [
    "APPLIED_MIGRATIONS_KEY",
    "DEFAULT_FILE_MODE",
    "EXPECTED_INDEXES",
    "EXPECTED_TABLES",
    "FAULT_CODES",
    "GENERATOR_VERSIONS",
    "INITIAL_PROJECTION_VERSION",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_KEY",
    "LocalProjectionStore",
    "LocalStoreError",
    "MigrationFailedError",
    "ProjectionMetaCorruptError",
    "SchemaVersionUnsupportedError",
    "StoreOpenError",
    "StorePathUnsafeError",
    "StoreSnapshot",
    "applied_migrations",
    "apply_pending_migrations",
    "current_schema_version",
    "initialize_fresh",
    "projection_meta_initial_rows",
    "read_projection_meta",
    "read_schema_version",
    "supported_schema_version",
]
