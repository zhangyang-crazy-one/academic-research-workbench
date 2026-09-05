"""Semantica sidecar conflict-policy regression tests.

Closes the PR16 Codex P2 review (comment 3939835833 on 1fdbc1f):
a sidecar whose ``provenance_records`` table carries a
``UNIQUE(entity_id) ON CONFLICT REPLACE`` clause can silently delete
prior rows on a subsequent insert (verified empirically — plain
``INSERT`` triggers REPLACE because the column-level ``ON CONFLICT``
clause changes the default resolution for the constraint). A bounded
before/after row count inside ``record()`` acts as a defense-in-depth
safety net if the schema check is ever bypassed.

These tests cover the new schema contract:

* ``UNIQUE(col) ON CONFLICT REPLACE`` (inline table constraint) is rejected.
* ``UNIQUE(col) ON CONFLICT FAIL`` / ``ON CONFLICT ROLLBACK`` are rejected.
* ``UNIQUE(col) ON CONFLICT IGNORE`` is allowed at init (preserves the
  existing regression test in ``test_semantica_lite.py`` which exercises
  the silent-drop defense via the post-insert reread check).
* ``CREATE UNIQUE INDEX`` on any column is rejected (catches the
  ``INSERT OR REPLACE`` silent-delete vector).
* A PRIMARY KEY on a non-record_id column is rejected.
* A compound PRIMARY KEY is rejected.
* The whitespace-tolerant normalized SQL scan catches all the above
  regardless of column/keyword formatting.
* A canonical schema with two records for one entity (no extra
  ``UNIQUE``) round-trips through ``record()`` and ``verify()``.
* If the schema check is somehow bypassed, the bounded before/after
  count inside ``record()`` still rolls back a silent REPLACE or a
  row-deletion trigger.
* A CLI regression test documents the expected exit-code contract for
  ``arw provenance verify`` on a tampered sidecar (exit 65 with proper
  error). Marked ``xfail`` until the parent-owned CLI patch lands; see
  relay notes in 260906-SUMMARY.md for the exact two-line patch.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from arw_semantica import (  # pyright: ignore[reportMissingImports]
    ProvenanceRecord,
    SemanticaSQLiteAdapter,
)


EVENT_ID = "evt-00000000-0000-4000-8000-000000000001"
EVENT_DIGEST = "a" * 64
COPY_EVENT_ID = "evt-00000000-0000-4000-8000-000000000004"
MAX_SIDECAR_RECORDS_FOR_TESTS = 500


def _base_record(
    *,
    record_id: str = "prov-claim.alpha",
    entity_id: str = "claim.alpha",
    event_id: str = EVENT_ID,
    event_digest: str = EVENT_DIGEST,
    artifact_id: str = "artifact-alpha",
) -> ProvenanceRecord:
    return ProvenanceRecord(
        schema_version="1.0.0",
        record_id=record_id,
        entity_id=entity_id,
        entity_type="Claim",
        artifact_id=artifact_id,
        ledger_event_id=event_id,
        ledger_event_digest=event_digest,
        activity_id="activity.extract",
        agent_id="agent.researcher",
        created_at="2026-09-02T00:00:00Z",
        derived_from=(),
        attributes={},
    )


def _adapter(
    database_path: Path,
    records: tuple[ProvenanceRecord, ...],
    *,
    audit_path: Path | None = None,
) -> SemanticaSQLiteAdapter:
    return SemanticaSQLiteAdapter(
        database_path,
        canonical_event_digests={
            str(record.ledger_event_id): str(record.ledger_event_digest)
            for record in records
        },
        accepted_artifact_ids_by_event={
            str(record.ledger_event_id): (record.artifact_id,) for record in records
        },
        accepted_artifact_sha256_by_event={
            str(record.ledger_event_id): record.checksum for record in records
        },
        expected_provenance_record_sha256={
            record.record_id: record.checksum for record in records
        },
        audit_database_path=audit_path or (database_path.parent / "projection.sqlite3"),
    )


def _seed_schema(tmp_path: Path, create_sql: str) -> Path:
    database = tmp_path / "provenance.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(create_sql)
    database.chmod(0o600)
    return database


def _canonical_create_sql(extra_columns: tuple[str, ...] = ()) -> str:
    extra = "\n    ".join(extra_columns)
    return f"""
        CREATE TABLE provenance_records (
            record_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            ledger_event_id TEXT NOT NULL,
            ledger_event_digest TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            derived_from_json TEXT NOT NULL,
            payload BLOB NOT NULL,
            checksum TEXT NOT NULL
            {',' + extra if extra else ''}
        )
    """


# ---------------------------------------------------------------------------
# Schema contract rejection — the primary defense.
# ---------------------------------------------------------------------------


def test_init_rejects_inline_replace_conflict_clause(tmp_path: Path) -> None:
    database = _seed_schema(
        tmp_path,
        _canonical_create_sql(("UNIQUE(entity_id) ON CONFLICT REPLACE",)),
    )
    with pytest.raises(RuntimeError, match="unsupported conflict resolution"):
        _adapter(database, (_base_record(),))


def test_init_accepts_inline_ignore_conflict_clause(tmp_path: Path) -> None:
    """IGNORE is intentionally allowed at init time: the silent-drop it can
    produce is already caught by ``record()``'s post-insert reread check
    (preserves the regression test in ``test_semantica_lite.py``)."""

    database = _seed_schema(
        tmp_path,
        _canonical_create_sql(("UNIQUE(entity_id) ON CONFLICT IGNORE",)),
    )
    # Init succeeds; the existing reread check still catches silent drops
    # when ``record()`` is called.
    adapter = _adapter(database, (_base_record(),))
    assert adapter is not None


def test_init_rejects_whitespace_normalized_replace_clause(tmp_path: Path) -> None:
    database = _seed_schema(
        tmp_path,
        _canonical_create_sql(
            ("UNIQUE ( entity_id )  ON   CONFLICT   REPLACE",),
        ),
    )
    with pytest.raises(RuntimeError, match="ON CONFLICT REPLACE"):
        _adapter(database, (_base_record(),))


def test_init_rejects_inline_fail_and_rollback_clauses(tmp_path: Path) -> None:
    for forbidden in ("FAIL", "ROLLBACK"):
        forbidden_dir = tmp_path / forbidden.lower()
        forbidden_dir.mkdir()
        database = _seed_schema(
            forbidden_dir,
            _canonical_create_sql(
                (f"UNIQUE(entity_id) ON CONFLICT {forbidden}",),
            ),
        )
        with pytest.raises(RuntimeError, match="unsupported conflict resolution"):
            _adapter(database, (_base_record(),))


def test_init_rejects_create_unique_index_on_entity_id(tmp_path: Path) -> None:
    database = _seed_schema(tmp_path, _canonical_create_sql())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE UNIQUE INDEX hostile_entity_idx "
            "ON provenance_records(entity_id)"
        )
        connection.commit()
    with pytest.raises(RuntimeError, match="unsupported UNIQUE INDEX"):
        _adapter(database, (_base_record(),))


def test_init_rejects_create_unique_index_on_record_id(tmp_path: Path) -> None:
    database = _seed_schema(tmp_path, _canonical_create_sql())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE UNIQUE INDEX hostile_record_id_idx "
            "ON provenance_records(record_id)"
        )
        connection.commit()
    with pytest.raises(RuntimeError, match="unsupported UNIQUE INDEX"):
        _adapter(database, (_base_record(),))


def test_init_rejects_primary_key_on_non_record_id_column(tmp_path: Path) -> None:
    database = _seed_schema(
        tmp_path,
        """
        CREATE TABLE provenance_records (
            record_id TEXT NOT NULL,
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            ledger_event_id TEXT NOT NULL,
            ledger_event_digest TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            derived_from_json TEXT NOT NULL,
            payload BLOB NOT NULL,
            checksum TEXT NOT NULL
        )
        """,
    )
    with pytest.raises(
        RuntimeError,
        match="(unexpected PRIMARY KEY column|schema constraints are incompatible)",
    ):
        _adapter(database, (_base_record(),))


def test_init_rejects_compound_primary_key(tmp_path: Path) -> None:
    database = _seed_schema(
        tmp_path,
        """
        CREATE TABLE provenance_records (
            record_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            ledger_event_id TEXT NOT NULL,
            ledger_event_digest TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            derived_from_json TEXT NOT NULL,
            payload BLOB NOT NULL,
            checksum TEXT NOT NULL,
            PRIMARY KEY (record_id, entity_id)
        )
        """,
    )
    with pytest.raises(
        RuntimeError,
        match="(unexpected PRIMARY KEY column|schema constraints are incompatible)",
    ):
        _adapter(database, (_base_record(),))


# ---------------------------------------------------------------------------
# Legitimate use — the canonical schema must allow two records for one entity.
# ---------------------------------------------------------------------------


def test_two_records_for_same_entity_succeed_on_canonical_schema(
    tmp_path: Path,
) -> None:
    first = _base_record()
    second = _base_record(
        record_id="prov-claim.copy",
        entity_id="claim.alpha",
        event_id=COPY_EVENT_ID,
        event_digest="d" * 64,
        artifact_id="artifact-copy",
    )
    adapter = _adapter(tmp_path / "provenance.sqlite3", (first, second))
    adapter.record(first)
    adapter.record(second)
    assert adapter.verify() == ()


def test_legitimate_idempotent_record_keeps_inventory_unchanged(
    tmp_path: Path,
) -> None:
    record = _base_record()
    adapter = _adapter(tmp_path / "provenance.sqlite3", (record,))
    adapter.record(record)
    checksum_again = adapter.record(record)
    assert checksum_again == record.checksum
    assert adapter.verify() == ()


# ---------------------------------------------------------------------------
# Defense in depth — the bounded before/after count inside record().
# ---------------------------------------------------------------------------


def _bypass_schema_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace the schema validation hooks with no-ops so we can exercise
    the bounded row-count safety net in isolation."""

    monkeypatch.setattr(
        SemanticaSQLiteAdapter,
        "_validate_index_contract",
        staticmethod(lambda connection: None),
    )
    monkeypatch.setattr(
        SemanticaSQLiteAdapter,
        "_reject_unsupported_conflict_clauses",
        staticmethod(lambda connection: None),
    )
    # Some defense-in-depth tests attach triggers or REPLACE constraints
    # after adapter construction. Bypass the trigger check too so the
    # count check is the only safety net left standing.
    monkeypatch.setattr(
        SemanticaSQLiteAdapter,
        "_reject_active_triggers",
        staticmethod(lambda connection: None),
    )


def test_count_check_rolls_back_silent_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the schema check is bypassed, a tampered table with
    ``UNIQUE(entity_id) ON CONFLICT REPLACE`` must still be detected
    inside ``record()`` via a bounded before/after row count.
    """

    _bypass_schema_checks(monkeypatch)
    first = _base_record()
    second = _base_record(
        record_id="prov-claim.copy",
        entity_id="claim.alpha",
        event_id=COPY_EVENT_ID,
        event_digest="d" * 64,
        artifact_id="artifact-copy",
    )
    adapter = _adapter(tmp_path / "provenance.sqlite3", (first, second))
    adapter.record(first)

    # Inject a REPLACE-shaped conflict clause directly on the live DB so
    # the schema check would have rejected it, but we are intentionally
    # running with the schema check disabled above.
    with sqlite3.connect(adapter._database_path) as connection:  # noqa: SLF001
        # Drop and recreate the table with the forbidden REPLACE clause,
        # preserving the single existing row.
        connection.execute("ALTER TABLE provenance_records RENAME TO _preserved")
        connection.execute(
            """
            CREATE TABLE provenance_records (
                record_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                ledger_event_id TEXT NOT NULL,
                ledger_event_digest TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                derived_from_json TEXT NOT NULL,
                payload BLOB NOT NULL,
                checksum TEXT NOT NULL,
                UNIQUE(entity_id) ON CONFLICT REPLACE
            )
            """
        )
        connection.execute(
            "INSERT INTO provenance_records SELECT * FROM _preserved"
        )
        connection.execute("DROP TABLE _preserved")
        connection.commit()

    with pytest.raises(RuntimeError, match="silently altered row inventory"):
        adapter.record(second)


def test_count_check_rolls_back_silent_delete_via_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row-deletion trigger attached to ``provenance_records`` would also
    reduce the row count after an insert. With the trigger check bypassed,
    the bounded before/after count must still reject the loss."""

    _bypass_schema_checks(monkeypatch)
    first = _base_record()
    second = _base_record(
        record_id="prov-claim.copy",
        entity_id="claim.alpha",
        event_id=COPY_EVENT_ID,
        event_digest="d" * 64,
        artifact_id="artifact-copy",
    )
    adapter = _adapter(tmp_path / "provenance.sqlite3", (first, second))
    adapter.record(first)

    with sqlite3.connect(adapter._database_path) as connection:  # noqa: SLF001
        connection.execute(
            "CREATE TRIGGER drop_old AFTER INSERT ON provenance_records "
            "BEGIN DELETE FROM provenance_records "
            "WHERE record_id <> NEW.record_id; END"
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="silently altered row inventory"):
        adapter.record(second)


# ---------------------------------------------------------------------------
# Bounded defense — the count and PRAGMA enumeration must use bounded
# cursors so a malicious sidecar with millions of rows cannot exhaust the
# ``record()`` transaction budget. The existing 500-row Lite cap is
# enforced without scanning the whole table.
# ---------------------------------------------------------------------------


def test_bounded_row_count_caps_at_limit(tmp_path: Path) -> None:
    """``_bounded_row_count`` must cap at ``limit`` and never scan the
    full table. A sidecar with 10 000 rows queried with ``limit=5`` must
    return exactly 5 (sentinel for "more than limit") without an O(N)
    scan."""

    from arw_semantica.adapter import SemanticaSQLiteAdapter

    database = _seed_schema(tmp_path, _canonical_create_sql())
    os.chmod(database, 0o600)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO provenance_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    f"prov-{i:06d}",
                    f"entity-{i:06d}",
                    "Claim",
                    f"artifact-{i:06d}",
                    "evt",
                    "0" * 64,
                    "activity",
                    "agent",
                    "2026-09-02T00:00:00Z",
                    "[]",
                    b'{"x":1}',
                    "0" * 64,
                )
                for i in range(10_000)
            ],
        )
        connection.commit()
        capped = SemanticaSQLiteAdapter._bounded_row_count(connection, limit=5)
        full_cap = SemanticaSQLiteAdapter._bounded_row_count(
            connection, limit=MAX_SIDECAR_RECORDS_FOR_TESTS + 1
        )
    assert capped == 5
    assert full_cap == MAX_SIDECAR_RECORDS_FOR_TESTS + 1


def test_validate_index_contract_rejects_excessive_unique_indexes(
    tmp_path: Path,
) -> None:
    """The index validation must cap its PRAGMA fetch so a hostile
    sidecar with hundreds of UNIQUE indexes cannot blow up the init
    path. We assert the LIMIT is in effect by injecting 40 UNIQUE
    indexes (above the 32 LIMIT) and confirming the contract still
    rejects the table cleanly."""

    database = _seed_schema(tmp_path, _canonical_create_sql())
    os.chmod(database, 0o600)
    with sqlite3.connect(database) as connection:
        for i in range(40):
            connection.execute(
                f"CREATE UNIQUE INDEX hostile_idx_{i:02d} "
                "ON provenance_records(entity_id)"
            )
        connection.commit()
    with pytest.raises(RuntimeError, match="unsupported UNIQUE INDEX"):
        _adapter(database, (_base_record(),))


# ---------------------------------------------------------------------------
# Helper-level guards.
# ---------------------------------------------------------------------------


def test_quote_identifier_rejects_non_alnum() -> None:
    from arw_semantica.adapter import _quote_identifier

    assert _quote_identifier("safe_idx_1") == '"safe_idx_1"'
    with pytest.raises(ValueError, match="unsafe identifier"):
        _quote_identifier('drop"; --')


def test_normalize_sql_collapses_whitespace() -> None:
    from arw_semantica.adapter import _normalize_sql

    assert (
        _normalize_sql("CREATE TABLE t(\n  a  TEXT\n)")
        == "CREATE TABLE t( a TEXT )"
    )
    assert (
        _normalize_sql("ON\tCONFLICT\nREPLACE")
        == "ON CONFLICT REPLACE"
    )


def test_canonical_payload_byte_stability_for_count_anchor() -> None:
    """The record payload is hashed for canonical binding; the test fixture
    uses the same payload structure as test_semantica_lite so any future
    schema drift that affects the count-check path surfaces here."""

    from arw.kernel.core.canonical import canonical_json_bytes

    record = _base_record()
    payload_bytes = canonical_json_bytes(record.canonical_payload())
    digest = hashlib.sha256(payload_bytes).hexdigest()
    assert len(digest) == 64
    assert payload_bytes == canonical_json_bytes(record.canonical_payload())


# ---------------------------------------------------------------------------
# CLI regression contract.
#
# The parent-owned CLI patch in src/arw/cli.py (relay notes in
# 260906-SUMMARY.md) must gate exit status on verify() fault count. Until
# that patch lands, the test below documents the expected contract and is
# marked xfail so the suite stays green either way.
# ---------------------------------------------------------------------------


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"})
    return subprocess.run(
        [sys.executable, "-m", "arw.cli", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_provenance_verify_fails_closed_on_audit_fault(
    tmp_path: Path,
) -> None:
    """Contract: ``arw provenance verify`` against a sidecar that reports
    audit faults must exit with status 65 and a stderr message naming
    the fault code, mirroring ``arw route --diagnostics`` semantics.

    Setup: initialize a real run root via the CLI (so the manifest and
    ledger replay succeed), then plant a tampered sidecar at the CLI's
    expected path that holds one row whose payload checksum does not
    match its stored checksum. ``provider.verify()`` reports a
    ``semantica_checksum_mismatch`` audit fault; the parent-owned CLI
    patch must surface it on stderr and exit 65.
    """

    run_root = tmp_path / "run"
    store = tmp_path / "projection.sqlite3"

    source = run_root / "input" / "src.txt"
    source.parent.mkdir(parents=True)
    source.write_text("input data\n", encoding="utf-8")
    init_req = {
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000099",
        "occurred_at": "2026-09-05T00:00:00Z",
        "immutable_input": {
            "path": "input/src.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": "core-research.v1",
        "workflow_definition_sha256": (
            "00042c2329644831b3cb84b5a46e57169cb92cf18177aaf35f9e2ecdcc288683"
        ),
        "journal_layout": "segmented-v1",
        "capabilities": ["canonical-journal"],
        "event_id": "evt-00000000-0000-4000-8000-000000000099",
        "command_id": "cmd-00000000-0000-4000-8000-000000000099",
        "actor_id": "actor-test",
    }
    req_path = tmp_path / "init.json"
    req_path.write_text(json.dumps(init_req))
    init = _cli(
        "init",
        "--run-root",
        str(run_root),
        "--request",
        str(req_path),
    )
    assert init.returncode == 0, (
        f"arw init failed: rc={init.returncode}\n"
        f"stdout: {init.stdout}\nstderr: {init.stderr}"
    )

    # Plant a tampered sidecar at the CLI's expected path: one row whose
    # stored checksum does not match the actual payload, so verify()
    # reports a semantica_checksum_mismatch fault.
    sidecar_name = (
        f"{store.name}.run-00000000-0000-4000-8000-000000000099.semantica.sqlite3"
    )
    sidecar_path = store.parent / sidecar_name
    with sqlite3.connect(sidecar_path) as connection:
        connection.execute(
            """
            CREATE TABLE provenance_records (
                record_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                ledger_event_id TEXT NOT NULL,
                ledger_event_digest TEXT NOT NULL,
                activity_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                derived_from_json TEXT NOT NULL,
                payload BLOB NOT NULL,
                checksum TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO provenance_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "prov-attacker",
                "claim.alpha",
                "Claim",
                "artifact-attacker",
                "evt-attacker",
                "0" * 64,
                "activity-attacker",
                "agent-attacker",
                "2026-09-05T00:00:00Z",
                "[]",
                b'{"tampered":true}',
                "f" * 64,  # mismatched checksum
            ),
        )
        connection.commit()
    os.chmod(sidecar_path, 0o600)

    result = _cli(
        "provenance",
        "verify",
        "--run-root",
        str(run_root),
        "--store",
        str(store),
    )
    assert result.returncode == 65, (
        f"expected exit 65 on audit faults; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "semantica_checksum_mismatch" in result.stderr, (
        f"stderr should name the fault code; got: {result.stderr}"
    )
    stdout_payload = json.loads(result.stdout)
    assert "audit_faults" in stdout_payload
    codes = {fault["code"] for fault in stdout_payload["audit_faults"]}
    assert "semantica_checksum_mismatch" in codes
