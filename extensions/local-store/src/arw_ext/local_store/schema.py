"""SQLite schema DDL for the local projection store (migration ``0001``).

This module is the single source of truth for the projection store's
*initial* schema.  Every later migration must be added as a new numbered step
in :data:`MIGRATIONS`; existing SQL is never edited after it has shipped.

Design notes (mirrors ``openspec/changes/sqlite-projection-store/design.md``):

* **Journaling** — ``PRAGMA journal_mode=DELETE`` is the default per the v1
  precedent (graph_store, files.py); WAL is gated on a later lane that adds
  the network-filesystem check from design D5.
* **Foreign keys** — ``PRAGMA foreign_keys=ON`` is set at open time so the
  FK declarations below are enforced.
* **FTS5** — ``files_fts`` (unicode61, token-bound) and ``files_fts_trigram``
  (trigram substring) index the NFKC-casefolded body so the v1 ranking
  semantics remain reachable; the population step lives in a later lane.
* **Provenance** — ``provenance`` rows bind assertions / node-or-edge rows to
  the ledger event that admitted them (``ledger_event_id``,
  ``ledger_event_digest``); ``record_checksum`` is the projection-identity
  digest and is verified on demand by a later lane.
* **Indexes** — every proposal index (``nodes(type)``, the five edge indexes,
  ``provenance(node_or_edge_id)``, ``provenance(source_artifact_id)``) is
  declared here; later lanes may add secondary ones.
"""

from __future__ import annotations

# The schema version this migration produces.  Bumping it is a NORMAL schema
# change; never edit this constant after migration 0001 has shipped.
SCHEMA_VERSION: str = "1"

# Initial projection_version (= 0).  Projection versions are independent of
# schema versions; the Semantica-lite lane (PR4 task 5.1+) bumps this without
# a schema change.
INITIAL_PROJECTION_VERSION: str = "0"

#: Generator version strings recorded in projection_meta.  These are advisory
#: labels surfaced in receipts and status output — they MUST be updated when
#: the corresponding projection generator changes; they are NOT used by the
#: migration runner.
GENERATOR_VERSIONS: dict[str, str] = {
    "schema": SCHEMA_VERSION,
    "ledger_projection": "0",
    "files_projection": "0",
    "knowledge_projection": "0",
    "fts_projection": "0",
}

#: Single SQL script applied by migration 0001.  The script is intentionally
#: idempotent for fresh init only (it uses ``IF NOT EXISTS``); later
#: migrations MUST NOT rely on rerun-safety and are run exactly once per
#: schema version.
MIGRATION_0001_SQL: str = """
CREATE TABLE IF NOT EXISTS projection_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materialized_run_state (
    run_id                 TEXT PRIMARY KEY,
    stage                  TEXT NOT NULL,
    status                 TEXT NOT NULL,
    started_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    last_event_sequence    INTEGER NOT NULL,
    attributes_json        TEXT NOT NULL,
    ledger_watermark       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS materialized_run_state_stage_idx
    ON materialized_run_state(stage);
CREATE INDEX IF NOT EXISTS materialized_run_state_status_idx
    ON materialized_run_state(status);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id          TEXT PRIMARY KEY,
    artifact_kind        TEXT NOT NULL,
    source_locator       TEXT NOT NULL,
    source_digest        TEXT NOT NULL,
    payload_digest       TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL,
    accepted_at          TEXT NOT NULL,
    accepting_event_id   TEXT,
    accepting_event_digest TEXT,
    projection_version   TEXT NOT NULL,
    attributes_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifacts_kind_idx ON artifacts(artifact_kind);

CREATE TABLE IF NOT EXISTS files (
    file_id                       TEXT PRIMARY KEY,
    relative_path                 TEXT NOT NULL UNIQUE,
    file_type                     TEXT NOT NULL,
    size_bytes                    INTEGER NOT NULL,
    source_digest                 TEXT NOT NULL,
    index_state                   TEXT NOT NULL,
    degraded_reason               TEXT,
    extraction_registration_sha256 TEXT,
    body_nfkc_folded              TEXT
);
CREATE INDEX IF NOT EXISTS files_index_state_idx ON files(index_state);

-- FTS5 token-bound index over NFKC-casefolded text (unicode61 + remove_diacritics 2).
-- Population is a later lane; the virtual table is created here so the
-- migration boundary is stable.
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_id UNINDEXED,
    relative_path UNINDEXED,
    body_nfkc_folded,
    tokenize='unicode61 remove_diacritics 2'
);

-- Separate trigram index for CJK / substring fallback (D4).  The trigram
-- tokenizer is SQLite FTS5 built-in; it indexes the same folded body column.
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts_trigram USING fts5(
    file_id UNINDEXED,
    relative_path UNINDEXED,
    body_nfkc_folded,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS file_extractions (
    extraction_id               TEXT PRIMARY KEY,
    file_id                     TEXT NOT NULL REFERENCES files(file_id),
    extractor_id                TEXT NOT NULL,
    extractor_version           TEXT NOT NULL,
    extracted_text_digest       TEXT NOT NULL,
    extracted_byte_size         INTEGER NOT NULL,
    registered_at               TEXT NOT NULL,
    registration_sha256         TEXT NOT NULL,
    projection_version          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS file_extractions_file_idx
    ON file_extractions(file_id);

CREATE TABLE IF NOT EXISTS nodes (
    entity_type          TEXT NOT NULL,
    entity_id            TEXT PRIMARY KEY,
    source_digest        TEXT NOT NULL,
    payload_digest       TEXT NOT NULL,
    supersession_state   TEXT NOT NULL,
    ledger_watermark     INTEGER NOT NULL,
    attributes_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_entity_type_idx ON nodes(entity_type);

CREATE TABLE IF NOT EXISTS edges (
    edge_type            TEXT NOT NULL,
    from_entity_id       TEXT NOT NULL,
    to_entity_id         TEXT NOT NULL,
    evidence_digest      TEXT NOT NULL,
    source_digest        TEXT NOT NULL,
    supersession_state   TEXT NOT NULL,
    ledger_watermark     INTEGER NOT NULL,
    attributes_json      TEXT NOT NULL,
    PRIMARY KEY (edge_type, from_entity_id, to_entity_id, evidence_digest),
    FOREIGN KEY (from_entity_id) REFERENCES nodes(entity_id),
    FOREIGN KEY (to_entity_id)   REFERENCES nodes(entity_id)
);
CREATE INDEX IF NOT EXISTS edges_from_idx
    ON edges(from_entity_id);
CREATE INDEX IF NOT EXISTS edges_to_idx
    ON edges(to_entity_id);
CREATE INDEX IF NOT EXISTS edges_type_idx
    ON edges(edge_type);
CREATE INDEX IF NOT EXISTS edges_from_type_idx
    ON edges(from_entity_id, edge_type);
CREATE INDEX IF NOT EXISTS edges_to_type_idx
    ON edges(to_entity_id, edge_type);

CREATE TABLE IF NOT EXISTS assertions (
    assertion_id        TEXT PRIMARY KEY,
    entity_type         TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    edge_type           TEXT,
    supersession_state  TEXT NOT NULL,
    source_digest       TEXT NOT NULL,
    ledger_watermark    INTEGER NOT NULL,
    projection_version  TEXT NOT NULL,
    record_checksum     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assertions_entity_idx
    ON assertions(entity_type, entity_id);

-- One provenance row per assertion (or per node-or-edge when assertion_id is
-- NULL).  The proposal's full field list is encoded as columns so the audit
-- queries are pure SQL (no JSON extraction).
CREATE TABLE IF NOT EXISTS provenance (
    provenance_id        TEXT PRIMARY KEY,
    assertion_id         TEXT REFERENCES assertions(assertion_id),
    node_or_edge_id      TEXT NOT NULL,
    source_artifact_id   TEXT,
    source_digest        TEXT NOT NULL,
    source_locator       TEXT NOT NULL,
    activity_id          TEXT,
    agent_id             TEXT,
    tool_id              TEXT,
    tool_version         TEXT,
    extraction_method    TEXT,
    confidence           REAL,
    created_at           TEXT,
    ledger_event_id      TEXT,
    ledger_event_digest  TEXT,
    projection_version   TEXT NOT NULL,
    record_checksum      TEXT NOT NULL,
    supersedes           TEXT,
    provenance_origin    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS provenance_node_or_edge_idx
    ON provenance(node_or_edge_id);
CREATE INDEX IF NOT EXISTS provenance_source_artifact_idx
    ON provenance(source_artifact_id);
CREATE INDEX IF NOT EXISTS provenance_ledger_event_idx
    ON provenance(ledger_event_id);

CREATE TABLE IF NOT EXISTS activities (
    activity_id     TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    agent_id        TEXT,
    attributes_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    display_name    TEXT,
    attributes_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id     TEXT PRIMARY KEY,
    subject_kind    TEXT NOT NULL,
    subject_id      TEXT NOT NULL,
    decision        TEXT NOT NULL,
    rationale       TEXT,
    decided_at      TEXT NOT NULL,
    decided_by      TEXT,
    attributes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_subject_idx
    ON decisions(subject_kind, subject_id);

CREATE TABLE IF NOT EXISTS projection_checkpoints (
    projection_name        TEXT PRIMARY KEY,
    last_ledger_sequence   INTEGER NOT NULL,
    last_ledger_event_digest TEXT NOT NULL,
    last_applied_at        TEXT NOT NULL,
    projection_version     TEXT NOT NULL
);
"""

#: Ordered registry of migrations.  Each entry's ``version`` is the
#: ``schema_version`` the DB carries after the migration succeeds; ``sql``
#: is the (single-statement or script) DDL applied as one transaction.
#: A later lane will introduce a typed migration step runner; for now the
#: contract is "every entry is exactly one SQL script".
MIGRATIONS: tuple[dict[str, str | int], ...] = (
    {"version": 1, "sql": MIGRATION_0001_SQL},
)

# Tables and indexes the migration runner must be able to enumerate from
# ``sqlite_master``.  Kept as a Python constant so tests can assert against the
# exact set the proposal named without parsing SQL.
EXPECTED_TABLES: frozenset[str] = frozenset({
    "projection_meta",
    "materialized_run_state",
    "artifacts",
    "files",
    "files_fts",
    "files_fts_trigram",
    "file_extractions",
    "nodes",
    "edges",
    "assertions",
    "provenance",
    "activities",
    "agents",
    "decisions",
    "projection_checkpoints",
})

EXPECTED_INDEXES: frozenset[str] = frozenset({
    "materialized_run_state_stage_idx",
    "materialized_run_state_status_idx",
    "artifacts_kind_idx",
    "files_index_state_idx",
    "file_extractions_file_idx",
    "nodes_entity_type_idx",
    "edges_from_idx",
    "edges_to_idx",
    "edges_type_idx",
    "edges_from_type_idx",
    "edges_to_type_idx",
    "assertions_entity_idx",
    "provenance_node_or_edge_idx",
    "provenance_source_artifact_idx",
    "provenance_ledger_event_idx",
    "decisions_subject_idx",
})


def projection_meta_initial_rows() -> list[tuple[str, str]]:
    """Return the ``projection_meta`` key/value rows a fresh DB must seed.

    The rows are returned in a stable order so tests and rebuilds can compare
    deterministically.  ``schema_version`` MUST appear first; the migration
    runner uses it to detect the "fresh init" path.
    """

    rows: list[tuple[str, str]] = [("schema_version", SCHEMA_VERSION)]
    rows.append(("projection_version", INITIAL_PROJECTION_VERSION))
    for generator_name, generator_version in GENERATOR_VERSIONS.items():
        rows.append((f"generator_version.{generator_name}", generator_version))
    rows.append(("created_at_digest_placeholder", "0" * 64))
    return rows


__all__ = [
    "EXPECTED_INDEXES",
    "EXPECTED_TABLES",
    "GENERATOR_VERSIONS",
    "INITIAL_PROJECTION_VERSION",
    "MIGRATIONS",
    "MIGRATION_0001_SQL",
    "SCHEMA_VERSION",
    "projection_meta_initial_rows",
]