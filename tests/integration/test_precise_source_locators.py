"""Complete traceability is admitted only after resolving canonical source bytes."""

from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.source_locations import (
    SourceLocatorError,
    located_bytes,
    read_retained_bytes,
)
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.policy.schema_registry import (
    SchemaRegistryError,
    validate_instance,
    validate_schema_document,
)
from arw.kernel.state.models import ArtifactAcceptanceRequest, InitRunRequest
from arw.kernel.state.provenance import SourceLocator, provenance_schema_documents

RUN = "run-00000000-0000-4000-8000-000000000099"
SOURCE = b"# Results\nAccuracy is 92%.\n# Limits\nSmall sample.\n"


def seed(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "source.txt").write_bytes(SOURCE)
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN,
                "occurred_at": "2026-09-08T00:00:00Z",
                "immutable_input": {"path": "source.txt", "sha256": sha256_hex(SOURCE)},
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000001",
                "command_id": "cmd-00000000-0000-4000-8000-000000000001",
                "actor_id": "parent.runtime",
            }
        ),
    )
    source = accept(root, "artifact.source", "source.txt", 2, kind="source")
    assert source.accepted
    event = replay_run(root).events[-1]
    locator = {
        "schema_version": "arw.source-locator.v1",
        "source_artifact_id": "artifact.source",
        "source_sha256": sha256_hex(SOURCE),
        "source_event_id": event.event_id,
        "source_event_sha256": event.event_sha256,
        "producing_activity_id": "activity.extract",
        "location": {"kind": "lines", "start": 2, "end": 2},
        "quote_sha256": sha256_hex(b"Accuracy is 92%.\n"),
    }
    return root, {
        "schema_version": "2.0.0",
        "record_id": "record.accuracy",
        "entity_id": "claim.accuracy",
        "entity_type": "claim",
        "artifact_id": "artifact.assertion",
        "activity_id": "activity.extract",
        "agent_id": "parent.runtime",
        "created_at": "2026-09-08T00:00:00Z",
        "derived_from": [],
        "attributes": {"claim": "Accuracy is 92%."},
        "source_locator": locator,
    }


def accept(root, artifact_id, path, number, kind="provenance-record"):
    replay = replay_run(root)
    return RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN,
                "occurred_at": "2026-09-08T00:01:00Z",
                "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
                "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "expected_revision": replay.revision,
                "artifact_id": artifact_id,
                "artifact_kind": kind,
                "media_type": "application/json",
                "content_path": path,
                "content_sha256": sha256_hex((root / path).read_bytes()),
                "base_revision": replay.revision,
                "consumed_sha256": [replay.last_event_sha256],
            }
        )
    )


def command(root, store, action, *extra):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "provenance",
            action,
            "--run-root",
            str(root),
            "--store",
            str(store),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_source_to_assertion_cli_lineage_and_rebuild(tmp_path):
    root, record = seed(tmp_path)
    (root / "assertion.json").write_bytes(canonical_json_bytes(record))
    result = accept(root, "artifact.assertion", "assertion.json", 3)
    assert result.accepted
    store = tmp_path / "store.sqlite3"
    assert command(root, store, "rebuild")["rebuilt_records"] == 1
    before = command(root, store, "lineage", "--entity-id", "claim.accuracy")
    row = before["rows"][0]
    assert row["traceability"] == "complete"
    assert row["record"]["source_locator"] == record["source_locator"]
    assert row["record"]["activity_id"] == "activity.extract"
    assert row["record"]["ledger_event_id"] == replay_run(root).events[-1].event_id
    sidecars = list(tmp_path.glob("*.semantica.sqlite3"))
    assert len(sidecars) == 1
    for sidecar in sidecars:
        if sidecar.is_file():
            sidecar.unlink()
    command(root, store, "rebuild")
    assert command(root, store, "lineage", "--entity-id", "claim.accuracy") == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "range",
        "quote",
        "source_digest",
        "source_event",
        "activity",
        "type",
        "path",
    ],
)
def test_invalid_locator_cannot_emit_acceptance(tmp_path, fault):
    root, record = seed(tmp_path)
    locator = record["source_locator"]
    if fault == "missing":
        record.pop("source_locator")
    elif fault == "range":
        locator["location"]["end"] = 999
    elif fault == "quote":
        locator["quote_sha256"] = "f" * 64
    elif fault == "source_digest":
        locator["source_sha256"] = "f" * 64
    elif fault == "source_event":
        locator["source_event_sha256"] = "f" * 64
    elif fault == "activity":
        locator["producing_activity_id"] = "activity.other"
    elif fault == "type":
        locator["location"]["start"] = "2"
    else:
        (root / "source.txt").unlink()
        (root / "source.txt").symlink_to(tmp_path / "outside.txt")
        (tmp_path / "outside.txt").write_bytes(SOURCE)
    (root / "assertion.json").write_bytes(canonical_json_bytes(record))
    before = replay_run(root).last_event_sha256
    outcome = accept(root, "artifact.assertion", "assertion.json", 3)
    assert not outcome.accepted
    assert outcome.rejection.code == "source-locator-invalid"
    assert replay_run(root).last_event_sha256 == before


def test_legacy_payload_remains_replayable_but_incomplete(tmp_path):
    root, record = seed(tmp_path)
    record["schema_version"] = "1.0.0"
    record.pop("source_locator")
    raw = canonical_json_bytes(record)
    (root / "assertion.json").write_bytes(raw)
    assert accept(root, "artifact.assertion", "assertion.json", 3).accepted
    store = tmp_path / "store.sqlite3"
    command(root, store, "rebuild")
    row = command(root, store, "lineage", "--entity-id", "claim.accuracy")["rows"][0]
    assert row["traceability"] == "legacy_incomplete"
    assert (root / "assertion.json").read_bytes() == raw


@pytest.mark.parametrize(
    "location,expected",
    [
        (
            {"kind": "markdown_section", "heading": "Results", "occurrence": 1},
            b"# Results\nAccuracy is 92%.\n",
        ),
        ({"kind": "text_page", "page": 1}, SOURCE),
        ({"kind": "byte_chunk", "start": 10, "end": 27}, b"Accuracy is 92%.\n"),
    ],
)
def test_exact_location_forms(tmp_path, location, expected):
    _, record = seed(tmp_path)
    value = record["source_locator"]
    value["location"] = location
    locator = SourceLocator.model_validate_json(json.dumps(value))
    assert located_bytes(SOURCE, locator) == expected


def test_locator_schema_is_registered_and_drift_is_detected(tmp_path):
    _, record = seed(tmp_path)
    validate_instance("source-locator.schema.json", record["source_locator"])
    validate_instance("provenance-record-v2.schema.json", record)
    drifted = copy.deepcopy(provenance_schema_documents()["source-locator.schema.json"])
    drifted["properties"]["source_sha256"]["pattern"] = ".*"
    with pytest.raises(SchemaRegistryError):
        validate_schema_document("source-locator.schema.json", drifted)


def test_read_source_rejects_traversal_and_oversize(tmp_path):
    (tmp_path / "large").write_bytes(b"xx")
    with pytest.raises(SourceLocatorError):
        read_retained_bytes(tmp_path, "large", max_bytes=1)
    with pytest.raises(SourceLocatorError):
        read_retained_bytes(tmp_path, "../large")


def test_changed_retained_source_blocks_live_complete_traceability(tmp_path):
    root, record = seed(tmp_path)
    (root / "assertion.json").write_bytes(canonical_json_bytes(record))
    assert accept(root, "artifact.assertion", "assertion.json", 3).accepted
    store = tmp_path / "store.sqlite3"
    command(root, store, "rebuild")
    (root / "source.txt").write_bytes(SOURCE.replace(b"92%", b"99%"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "provenance",
            "lineage",
            "--run-root",
            str(root),
            "--store",
            str(store),
            "--entity-id",
            "claim.accuracy",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "digest mismatch" in result.stderr


def test_locator_tamper_with_recomputed_sidecar_hash_is_refused(tmp_path):
    import sqlite3

    root, record = seed(tmp_path)
    (root / "assertion.json").write_bytes(canonical_json_bytes(record))
    assert accept(root, "artifact.assertion", "assertion.json", 3).accepted
    store = tmp_path / "store.sqlite3"
    command(root, store, "rebuild")
    sidecar = next(tmp_path.glob("*.semantica.sqlite3"))
    with sqlite3.connect(sidecar) as conn:
        raw = conn.execute("SELECT payload FROM provenance_records").fetchone()[0]
        payload = json.loads(raw)
        payload["source_locator"]["location"]["start"] = 1
        forged = canonical_json_bytes(payload)
        conn.execute(
            "UPDATE provenance_records SET payload=?, checksum=?",
            (forged, sha256_hex(forged)),
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "provenance",
            "verify",
            "--run-root",
            str(root),
            "--store",
            str(store),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "semantica_checksum_mismatch" in result.stdout


def test_cjk_crlf_quote_and_text_page_boundaries(tmp_path):
    _, record = seed(tmp_path)
    locator = SourceLocator.model_validate_json(json.dumps(record["source_locator"]))
    raw = "结果\r\n准确率92%。\r\n".encode()
    assert located_bytes(raw, locator) == "准确率92%。\r\n".encode()
    page = locator.model_copy(
        update={
            "location": __import__(
                "arw.kernel.state.provenance", fromlist=["TextPage"]
            ).TextPage(kind="text_page", page=2)
        }
    )
    assert located_bytes(b"page1\fpage2", page) == b"page2"
    with pytest.raises(SourceLocatorError):
        located_bytes(b"page1", page)
