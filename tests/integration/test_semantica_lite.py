"""Semantica Lite provenance integration tests."""

from __future__ import annotations

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

from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable

EVENT_ID = "evt-00000000-0000-4000-8000-000000000001"
EVENT_DIGEST = "a" * 64


def _record(
    *, entity_id: str = "claim.alpha", derived_from: tuple[str, ...] = ()
) -> ProvenanceRecord:
    return ProvenanceRecord(
        record_id=f"prov-{entity_id}",
        entity_id=entity_id,
        entity_type="Decision" if entity_id == "decision.alpha" else "Claim",
        artifact_id="artifact-alpha",
        ledger_event_id=EVENT_ID,
        ledger_event_digest=EVENT_DIGEST,
        activity_id="activity.extract",
        agent_id="agent.researcher",
        created_at="2026-09-02T00:00:00Z",
        derived_from=derived_from,
    )


def _adapter(tmp_path: Path) -> SemanticaSQLiteAdapter:
    return SemanticaSQLiteAdapter(
        tmp_path / "provenance.sqlite3",
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        audit_database_path=tmp_path / "projection.sqlite3",
    )


def test_record_requires_artifact_and_canonical_ledger_binding(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    checksum = adapter.record(_record())
    assert len(checksum) == 64

    with pytest.raises(UnboundProvenanceError, match="canonical event stream"):
        adapter.record(
            ProvenanceRecord(
                **{**_record().canonical_payload(), "ledger_event_digest": "b" * 64}
            )
        )
    with pytest.raises(UnboundProvenanceError, match="artifact id"):
        adapter.record(
            ProvenanceRecord(**{**_record().canonical_payload(), "artifact_id": ""})
        )


def test_lineage_is_bounded_and_decision_filtered(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.record(_record(entity_id="source.alpha"))
    adapter.record(_record(entity_id="decision.alpha", derived_from=("source.alpha",)))

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
            "UPDATE provenance_records SET payload = ? WHERE record_id = ?",
            (b'{"tampered":true}', "prov-claim.alpha"),
        )

    faults = adapter.verify()
    assert [fault.code for fault in faults] == ["semantica_checksum_mismatch"]
    audit_paths = list((tmp_path / "projection.sqlite3.audit").glob("*.json"))
    assert len(audit_paths) == 1
    assert (
        json.loads(audit_paths[0].read_text(encoding="utf-8"))["code"]
        == "semantica_checksum_mismatch"
    )


def test_capability_is_optional_and_manifest_gated(tmp_path: Path) -> None:
    manifest = tmp_path / "plugin.json"
    manifest.write_text(
        '{"interface":{"capabilities":["provenance"]}}', encoding="utf-8"
    )
    router = default_router(
        semantica_store_path=tmp_path / "provenance.sqlite3",
        canonical_event_digests={EVENT_ID: EVENT_DIGEST},
        plugin_manifest=manifest,
    )
    assert "knowledge.provenance" in router.available()
    assert isinstance(router.resolve("knowledge.provenance"), SemanticaSQLiteAdapter)

    absent = default_router()
    with pytest.raises(CapabilityUnavailable):
        absent.resolve("knowledge.provenance")


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
