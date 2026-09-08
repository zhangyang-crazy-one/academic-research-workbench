"""Additive event-reader migration preserves deterministic replay and legacy bytes."""

import json
from pathlib import Path

import pytest

from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.event_versions import event_schema_version
from tests.integration.test_research_artifacts import prepared, request

pytestmark = pytest.mark.v2_compat


def test_research_artifact_event_fixture_replays_byte_stably(tmp_path):
    root, service, ir = prepared(tmp_path)
    legacy = [e.model_dump(mode="json") for e in replay_run(root).events]
    service.qualify(ir, run_root=root, request=request(root))
    service.qualify(
        ir.model_copy(
            update={"artifact_id": "figure.successor", "supersedes": ir.artifact_id}
        ),
        run_root=root,
        request=request(root, 101),
    )
    actual = [e.model_dump(mode="json") for e in replay_run(root).events]
    expected = json.loads(
        (Path(__file__).parent / "golden/research_artifact_events.json").read_bytes()
    )
    assert actual == expected
    assert actual[: len(legacy)] == legacy
    assert event_schema_version("artifact.accepted") == "1.0.0"
    assert event_schema_version("research_artifact_accepted") == "1.1.0"


@pytest.mark.parametrize(
    "name",
    ["research-artifact-ir.schema.json", "research-artifact-receipt.schema.json"],
)
def test_research_artifact_generated_schema_rejects_drift(name):
    import copy

    from arw.kernel.policy.schema_registry import (
        SchemaRegistryError,
        validate_schema_document,
    )
    from arw.kernel.state.research_artifact import research_artifact_schema_documents

    document = research_artifact_schema_documents()[name]
    validate_schema_document(name, document)
    drift = copy.deepcopy(document)
    drift["required"].pop()
    with pytest.raises(SchemaRegistryError):
        validate_schema_document(name, drift)
