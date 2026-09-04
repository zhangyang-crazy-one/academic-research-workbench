"""Semantica Lite provenance integration tests."""

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
    UnboundProvenanceError,
)

from arw.cli import build_parser
from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable

EVENT_ID = "evt-00000000-0000-4000-8000-000000000001"
EVENT_DIGEST = "a" * 64
SOURCE_EVENT_ID = "evt-00000000-0000-4000-8000-000000000002"
DECISION_EVENT_ID = "evt-00000000-0000-4000-8000-000000000003"
COPY_EVENT_ID = "evt-00000000-0000-4000-8000-000000000004"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _record(
    *,
    entity_id: str = "claim.alpha",
    derived_from: tuple[str, ...] = (),
    record_id: str | None = None,
    artifact_id: str | None = None,
    event_id: str | None = None,
    event_digest: str | None = None,
) -> ProvenanceRecord:
    default_events = {
        "claim.alpha": (EVENT_ID, EVENT_DIGEST, "artifact-alpha"),
        "source.alpha": (SOURCE_EVENT_ID, "b" * 64, "artifact-source.alpha"),
        "decision.alpha": (DECISION_EVENT_ID, "c" * 64, "artifact-decision.alpha"),
    }
    default_event_id, default_digest, default_artifact_id = default_events.get(
        entity_id, (EVENT_ID, EVENT_DIGEST, "artifact-alpha")
    )
    return ProvenanceRecord(
        schema_version="1.0.0",
        record_id=record_id or f"prov-{entity_id}",
        entity_id=entity_id,
        entity_type="Decision" if entity_id == "decision.alpha" else "Claim",
        artifact_id=artifact_id or default_artifact_id,
        ledger_event_id=event_id or default_event_id,
        ledger_event_digest=event_digest or default_digest,
        activity_id="activity.extract",
        agent_id="agent.researcher",
        created_at="2026-09-02T00:00:00Z",
        derived_from=derived_from,
        attributes={},
    )


def _adapter(
    tmp_path: Path, records: tuple[ProvenanceRecord, ...] | None = None
) -> SemanticaSQLiteAdapter:
    records = records or (_record(),)
    return SemanticaSQLiteAdapter(
        tmp_path / "provenance.sqlite3",
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
        audit_database_path=tmp_path / "projection.sqlite3",
    )


def _record_from_payload(payload: dict[str, object]) -> ProvenanceRecord:
    return ProvenanceRecord.model_validate_json(json.dumps(payload))


def test_record_requires_artifact_and_canonical_ledger_binding(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    checksum = adapter.record(_record())
    assert len(checksum) == 64

    with pytest.raises(UnboundProvenanceError, match="canonical event stream"):
        adapter.record(
            _record_from_payload(
                {**_record().canonical_payload(), "ledger_event_digest": "b" * 64}
            )
        )
    with pytest.raises(UnboundProvenanceError, match="not accepted"):
        adapter.record(
            _record_from_payload(
                {**_record().canonical_payload(), "artifact_id": "forged-artifact"}
            )
        )
    with pytest.raises(ValueError, match="artifact_id"):
        _record_from_payload({**_record().canonical_payload(), "artifact_id": ""})


def test_lineage_is_bounded_and_decision_filtered(tmp_path: Path) -> None:
    source = _record(entity_id="source.alpha")
    decision = _record(
        entity_id="decision.alpha", derived_from=("source.alpha",)
    )
    adapter = _adapter(tmp_path, (source, decision))
    adapter.record(source)
    adapter.record(decision)

    lineage = adapter.lineage("decision.alpha")
    assert [row["entity_id"] for row in lineage] == ["decision.alpha", "source.alpha"]
    assert [row["entity_id"] for row in adapter.decision_chain("decision.alpha")] == [
        "decision.alpha"
    ]


def test_tampered_sidecar_record_surfaces_an_audit_fault(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET record_id = ?, payload = ? WHERE record_id = ?",
            ("../../escaped", b'{"tampered":true}', "prov-claim.alpha"),
        )

    faults = adapter.verify()
    assert [fault.code for fault in faults] == [
        "semantica_checksum_mismatch",
        "semantica_missing_record",
    ]
    audit_paths = list((tmp_path / "projection.sqlite3.audit").glob("*.json"))
    assert len(audit_paths) == 2
    assert audit_paths[0].parent.stat().st_mode & 0o777 == 0o700
    assert {
        json.loads(path.read_text(encoding="utf-8"))["code"]
        for path in audit_paths
    } == {"semantica_checksum_mismatch", "semantica_missing_record"}
    assert all(path.name.startswith("semantica-") for path in audit_paths)
    assert not (tmp_path / "escaped").exists()

    adapter.rebuild([_record()])
    assert adapter.verify() == ()
    assert list((tmp_path / "projection.sqlite3.audit").glob("*.json")) == []


def test_lineage_uses_checksums_payload_not_duplicate_columns(tmp_path: Path) -> None:
    source = _record(entity_id="source.alpha")
    decision = _record(
        entity_id="decision.alpha", derived_from=("source.alpha",)
    )
    adapter = _adapter(tmp_path, (source, decision))
    adapter.record(source)
    adapter.record(decision)
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET entity_id = ?, derived_from_json = ? "
            "WHERE record_id = ?",
            ("attacker.alpha", '["attacker.alpha"]', "prov-decision.alpha"),
        )
    assert [row["entity_id"] for row in adapter.lineage("decision.alpha")] == [
        "decision.alpha",
        "source.alpha",
    ]
    assert adapter.lineage("attacker.alpha") == []


def test_lineage_enforces_max_rows_inside_one_entity(tmp_path: Path) -> None:
    base = _record()
    copy = _record(
        record_id="prov-claim-copy",
        artifact_id="artifact-copy",
        event_id=COPY_EVENT_ID,
        event_digest="d" * 64,
    )
    adapter = _adapter(tmp_path, (base, copy))
    adapter.record(base)
    adapter.record(copy)
    assert len(adapter.lineage("claim.alpha", max_rows=1)) == 1


def test_lineage_rejects_unchecked_sql_record_id(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET record_id = ? WHERE record_id = ?",
            ("attacker-record", "prov-claim.alpha"),
        )
    with pytest.raises(RuntimeError, match="lineage payload"):
        adapter.lineage("claim.alpha")


def test_verify_turns_text_payload_into_audit_fault(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET payload = ? WHERE record_id = ?",
            ("not-a-blob", "prov-claim.alpha"),
        )
    faults = adapter.verify()
    assert [fault.code for fault in faults] == ["semantica_checksum_mismatch"]


def test_verify_reports_missing_canonical_record_and_lineage_fails_closed(
    tmp_path: Path,
) -> None:
    record = _record()
    adapter = SemanticaSQLiteAdapter(
        tmp_path / "provenance.sqlite3",
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
        accepted_artifact_sha256_by_event={EVENT_ID: record.checksum},
        expected_provenance_record_sha256={record.record_id: record.checksum},
        audit_database_path=tmp_path / "projection.sqlite3",
    )
    adapter.record(record)
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute("DELETE FROM provenance_records")
    assert [fault.code for fault in adapter.verify()] == [
        "semantica_missing_record"
    ]
    with pytest.raises(RuntimeError, match="missing canonical provenance"):
        adapter.lineage(record.entity_id)


def test_verify_turns_checksummed_invalid_json_into_audit_fault(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    invalid = b"not-json"
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET payload = ?, checksum = ? WHERE record_id = ?",
            (invalid, hashlib.sha256(invalid).hexdigest(), "prov-claim.alpha"),
        )
    assert [fault.code for fault in adapter.verify()] == [
        "semantica_checksum_mismatch"
    ]


def test_noncanonical_checksummed_payload_is_rejected(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    record = _record()
    adapter.record(record)
    reformatted = json.dumps(record.canonical_payload(), indent=2).encode("utf-8")
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "UPDATE provenance_records SET payload = ?, checksum = ? WHERE record_id = ?",
            (
                reformatted,
                hashlib.sha256(reformatted).hexdigest(),
                record.record_id,
            ),
        )
    assert [fault.code for fault in adapter.verify()] == [
        "semantica_checksum_mismatch"
    ]
    with pytest.raises(RuntimeError, match="noncanonical"):
        adapter.lineage(record.entity_id)


def test_reset_removes_noncanonical_sidecar_rows(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    with sqlite3.connect(tmp_path / "provenance.sqlite3") as connection:
        connection.execute(
            "INSERT INTO provenance_records "
            "(record_id, entity_id, entity_type, artifact_id, ledger_event_id, "
            "ledger_event_digest, activity_id, agent_id, created_at, derived_from_json, "
            "payload, checksum) "
            "SELECT ?, entity_id, entity_type, artifact_id, ledger_event_id, "
            "ledger_event_digest, activity_id, agent_id, created_at, derived_from_json, "
            "payload, checksum FROM provenance_records WHERE record_id = ?",
            ("prov-forged", "prov-claim.alpha"),
        )
    adapter.reset()
    with pytest.raises(RuntimeError, match="missing canonical provenance"):
        adapter.lineage("claim.alpha")


def test_sidecar_rejects_writable_audit_directory(tmp_path: Path) -> None:
    audit_directory = tmp_path / "projection.sqlite3.audit"
    audit_directory.mkdir(mode=0o700)
    audit_directory.chmod(0o777)
    with pytest.raises(ValueError, match="private 0700"):
        SemanticaSQLiteAdapter(
            tmp_path / "provenance.sqlite3",
            canonical_event_digests={EVENT_ID: EVENT_DIGEST},
            accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
            accepted_artifact_sha256_by_event={EVENT_ID: _record().checksum},
            expected_provenance_record_sha256={},
            audit_database_path=tmp_path / "projection.sqlite3",
        )


def test_tampered_sidecar_schema_is_a_provenance_error(tmp_path: Path) -> None:
    database = tmp_path / "provenance.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE provenance_records (record_id TEXT)")
    database.chmod(0o600)
    with pytest.raises(RuntimeError, match="initialization failed"):
        SemanticaSQLiteAdapter(
            database,
            canonical_event_digests={EVENT_ID: EVENT_DIGEST},
            accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
            accepted_artifact_sha256_by_event={EVENT_ID: _record().checksum},
            expected_provenance_record_sha256={},
        )


def test_sidecar_rejects_symlinked_ancestor_and_audit_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    (target / "nested").mkdir(parents=True)
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="ancestor"):
        SemanticaSQLiteAdapter(
            tmp_path / "link" / "nested" / "provenance.sqlite3",
            canonical_event_digests={EVENT_ID: EVENT_DIGEST},
            accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
            accepted_artifact_sha256_by_event={EVENT_ID: _record().checksum},
            expected_provenance_record_sha256={},
        )
    (tmp_path / "projection.sqlite3.audit").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="audit directory"):
        SemanticaSQLiteAdapter(
            tmp_path / "provenance.sqlite3",
            canonical_event_digests={EVENT_ID: EVENT_DIGEST},
            accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
            accepted_artifact_sha256_by_event={EVENT_ID: _record().checksum},
            expected_provenance_record_sha256={},
            audit_database_path=tmp_path / "projection.sqlite3",
        )


def test_installed_cli_exposes_provenance_route(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "provenance",
            "lineage",
            "--run-root",
            str(tmp_path / "run"),
            "--store",
            str(tmp_path / "projection.sqlite3"),
            "--entity-id",
            "claim.alpha",
        ]
    )
    assert args.command == "provenance"
    assert args.provenance_action == "lineage"


def test_capability_is_optional_and_manifest_gated(tmp_path: Path) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        '{"interface":{"capabilities":["provenance"]}}', encoding="utf-8"
    )
    router = default_router(
        semantica_store_path=tmp_path / "provenance.sqlite3",
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        accepted_artifact_ids_by_event={EVENT_ID: ("artifact-alpha",)},
        accepted_artifact_sha256_by_event={EVENT_ID: _record().checksum},
        expected_provenance_record_sha256={
            _record().record_id: _record().checksum
        },
        plugin_manifest=manifest,
    )
    assert "knowledge.provenance" in router.available()
    assert isinstance(router.resolve("knowledge.provenance"), SemanticaSQLiteAdapter)

    absent = default_router()
    with pytest.raises(CapabilityUnavailable):
        absent.resolve("knowledge.provenance")


def test_sidecar_is_created_with_private_permissions(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record())
    assert len(adapter.lineage("claim.alpha")) == 1
    assert (tmp_path / "provenance.sqlite3").stat().st_mode & 0o777 == 0o600
    (tmp_path / "provenance.sqlite3").chmod(0o644)
    with pytest.raises(ValueError, match="private 0600"):
        _adapter(tmp_path)


def test_provenance_artifact_schema_is_byte_stable() -> None:
    generated = ProvenanceRecord.model_json_schema(mode="validation")
    properties = generated["properties"]
    assert isinstance(properties, dict)
    properties.pop("ledger_event_id")
    properties.pop("ledger_event_digest")
    generated["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/"
        "provenance-record.schema.json"
    )
    generated["title"] = "Semantica-compatible Lite provenance record"
    checked_in = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/provenance-record.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert generated == checked_in


def test_lite_import_activates_no_heavy_modules() -> None:
    project = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(project / "extensions/semantica/src")}
    probe = """
import importlib.util
import json
import sys
import arw_semantica
_ = arw_semantica.SemanticaSQLiteAdapter
blocked = {name.split('.', 1)[0] for name in sys.modules} & {
    'faiss', 'neo4j', 'falkordb', 'torch', 'transformers',
    'sentence_transformers', 'spacy', 'fastapi', 'mcp',
}
print(json.dumps({
    "blocked": sorted(blocked),
    "upstream_semantica_installed": importlib.util.find_spec("semantica") is not None,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "blocked": [],
        "upstream_semantica_installed": False,
    }
