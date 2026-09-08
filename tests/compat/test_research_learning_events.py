"""Additive learning events remain readable without the optional extension."""

import copy
import json
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy.schema_registry import (
    SchemaRegistryError,
    validate_instance,
    validate_schema_document,
)
from arw.kernel.state.models import RESEARCH_LEARNING_EVENT_TYPES, CanonicalEvent
from arw.kernel.state.research_learning import learning_schema_documents
from tests.integration.test_research_artifacts import request
from tests.integration.test_research_learning import (
    approve,
    candidate,
    prepared,
    qualified,
)

pytestmark = pytest.mark.v2_compat


def fixture_events(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed, _, qualification = qualified(root, service)
    approval = approve(root, item, proposed, qualification)
    service.promote(
        item.heuristic_id,
        consent=True,
        approval_artifact_id=approval,
        request=request(root, 141),
    )
    successor = candidate(
        item.supporting_observation_ids[0],
        heuristic_id="heuristic.successor",
        supersedes=item.heuristic_id,
    )
    service.extract(successor, request=request(root, 142))
    service.reject(
        successor.heuristic_id,
        reason="Further evaluation needed",
        request=request(root, 143),
    )
    return [e.model_dump(mode="json") for e in replay_run(root).events]


def test_learning_historical_digest_stability(tmp_path, monkeypatch):
    actual = fixture_events(tmp_path)
    expected = json.loads(
        (Path(__file__).parent / "golden/research_learning_events.json").read_bytes()
    )
    assert actual == expected
    assert set(RESEARCH_LEARNING_EVENT_TYPES) <= {e["event_type"] for e in actual}
    from arw import composition
    from arw.kernel.capabilities import CapabilityUnavailable

    original = composition.import_module

    def absent(name):
        if name.startswith("arw_research_learning"):
            raise ImportError("disabled")
        return original(name)

    monkeypatch.setattr(composition, "import_module", absent)
    with pytest.raises(CapabilityUnavailable):
        composition.default_router().resolve("research.learning.observe")
    decoded = [
        CanonicalEvent.model_validate_json(json.dumps(e)).model_dump(mode="json")
        for e in expected
    ]
    assert canonical_json_bytes(decoded) == canonical_json_bytes(expected)
    for event in expected:
        validate_instance("event.schema.json", event)


@pytest.mark.parametrize("name", tuple(learning_schema_documents()))
def test_learning_schema_drift(name):
    document = learning_schema_documents()[name]
    validate_schema_document(name, document)
    changed = copy.deepcopy(document)
    changed["properties"]["schema_version"] = {"type": "string"}
    with pytest.raises(SchemaRegistryError):
        validate_schema_document(name, changed)


def test_learning_ports_and_adapter_import_boundary():
    import ast

    from arw.ports import learning

    assert {
        name
        for name in (
            "ObservationProvider",
            "HeuristicExtractor",
            "HeuristicStore",
            "HeuristicEvaluator",
            "HeuristicPromoter",
        )
        if getattr(learning, name)._is_protocol
    } == {
        "ObservationProvider",
        "HeuristicExtractor",
        "HeuristicStore",
        "HeuristicEvaluator",
        "HeuristicPromoter",
    }
    root = Path(__file__).parents[2] / "src/arw"
    for path in [*root.joinpath("kernel").rglob("*.py"), *root.glob("cli*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [x.name for x in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(
                name.startswith("arw_research_learning") for name in modules
            ), path
