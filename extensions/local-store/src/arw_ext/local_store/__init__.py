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

Lane B (PR4) adds the projection pipeline + provenance binding +
:mod:`KnowledgeProvider` adapter:

* :func:`map_ledger_events` — ledger events → canonical manifest records
  per design.md D3-amended.
* :func:`apply_projection` — write nodes / edges / assertions / provenance
  + projection checkpoints + materialized run state (task 3.1, 3.2, 3.4).
* :func:`build_full` / :func:`build_incremental` / :func:`delete_and_rebuild`
  helpers that wrap the apply into a portable unit.
* :func:`verify_checksums` — recompute record_checksums and emit audit
  faults (task 5.2).
* :class:`LocalStoreKnowledgeAdapter` — implements
  :class:`arw.ports.knowledge.KnowledgeProvider` over the local store.
"""

from __future__ import annotations

from .apply import (
    ApplyError,
    ApplyResult,
    apply_projection,
    build_graph_manifest,
)
from .errors import (
    FAULT_CODES,
    LocalStoreError,
    MigrationFailedError,
    ProjectionMetaCorruptError,
    SchemaVersionUnsupportedError,
    StoreOpenError,
    StorePathUnsafeError,
)
from .knowledge import (
    LocalStoreKnowledgeAdapter,
    reducer_state_for_replay,
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
from .projection import map_ledger_events, record_check_payload_digest
from .query import execute_query, trace_rows
from .receipts import (
    AuditFault,
    audit_root,
    clear_audit_faults,
    list_receipts,
    load_audit_faults,
    load_receipt,
    persist_audit_fault,
    persist_receipt,
    receipts_root,
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
from .verify import verify_checksums

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
    "ApplyError",
    "ApplyResult",
    "AuditFault",
    "LocalProjectionStore",
    "LocalStoreError",
    "LocalStoreKnowledgeAdapter",
    "MigrationFailedError",
    "ProjectionMetaCorruptError",
    "SchemaVersionUnsupportedError",
    "StoreOpenError",
    "StorePathUnsafeError",
    "StoreSnapshot",
    "applied_migrations",
    "apply_pending_migrations",
    "apply_projection",
    "audit_root",
    "build_graph_manifest",
    "clear_audit_faults",
    "current_schema_version",
    "execute_query",
    "initialize_fresh",
    "list_receipts",
    "load_audit_faults",
    "load_receipt",
    "map_ledger_events",
    "persist_audit_fault",
    "persist_receipt",
    "projection_meta_initial_rows",
    "read_projection_meta",
    "read_schema_version",
    "receipts_root",
    "record_check_payload_digest",
    "reducer_state_for_replay",
    "supported_schema_version",
    "trace_rows",
    "verify_checksums",
]
