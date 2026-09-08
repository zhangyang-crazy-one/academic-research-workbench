"""Historical memory bytes remain decodable without optional memory providers."""

import copy
import json
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy.schema_registry import (
    SchemaRegistryError,
    validate_schema_document,
)
from arw.kernel.state.models import CanonicalEvent
from arw.kernel.state.research_memory import research_memory_schema_documents
from tests.integration.test_precise_source_locators import accept
from tests.integration.test_research_artifacts import request
from tests.integration.test_research_memory import handoff, note, prepared

pytestmark = pytest.mark.v2_compat


def fixture_events(tmp_path):
    root, service = prepared(tmp_path)
    service.save(note(memory_id="memory.first"), request=request(root))
    service.govern("memory.first", "activate", request=request(root, 101))
    service.save(
        note(
            memory_id="memory.next", body="Next comparison", supersedes=["memory.first"]
        ),
        request=request(root, 102),
    )
    service.govern("memory.next", "reject", request=request(root, 103))
    saved = service.save(handoff(root), request=request(root, 104))
    for number, action in ((105, "verify"), (107, "distill")):
        relative = action + ".json"
        (root / relative).write_text(
            json.dumps(
                {
                    "action": action + "_memory",
                    "memory_id": saved["memory_id"],
                    "content_digest": saved["content_digest"],
                    "source_artifact_ids": ["artifact.source", "artifact.target"],
                }
            )
        )
        assert accept(
            root, "artifact." + action, relative, number, kind="memory-authorization"
        ).accepted
        service.govern(
            saved["memory_id"],
            action,
            request=request(root, number + 1),
            authorization_artifact_id="artifact." + action,
        )
    return [e.model_dump(mode="json") for e in replay_run(root).events]


def test_memory_events_have_stable_historical_bytes(tmp_path, monkeypatch):
    actual = fixture_events(tmp_path)
    expected = json.loads(
        (Path(__file__).parent / "golden/research_memory_events.json").read_bytes()
    )
    assert actual == expected
    from arw import composition
    from arw.kernel.capabilities import CapabilityUnavailable

    original = composition.import_module

    def missing(name):
        if name.startswith("arw_research_memory"):
            raise ImportError("disabled")
        return original(name)

    monkeypatch.setattr(composition, "import_module", missing)
    with pytest.raises(CapabilityUnavailable):
        composition.default_router().resolve("research.memory.save")
    decoded = [
        CanonicalEvent.model_validate_json(json.dumps(event)).model_dump(mode="json")
        for event in actual
    ]
    assert canonical_json_bytes(decoded) == canonical_json_bytes(expected)


@pytest.mark.parametrize("name", tuple(research_memory_schema_documents()))
def test_memory_generated_schema_drift(name):
    doc = research_memory_schema_documents()[name]
    validate_schema_document(name, doc)
    changed = copy.deepcopy(doc)
    changed["properties"]["kind"] = {"type": "string"}
    with pytest.raises(SchemaRegistryError):
        validate_schema_document(name, changed)
