from __future__ import annotations

import pytest


def test_registered_workflow_identity_is_deterministic_and_domain_neutral() -> None:
    from arw.workflows import CORE_WORKFLOW, workflow_definition_sha256

    assert CORE_WORKFLOW.definition_id == "core-research.v1"
    assert workflow_definition_sha256(CORE_WORKFLOW) == CORE_WORKFLOW.sha256
    assert len(CORE_WORKFLOW.sha256) == 64
    rendered = CORE_WORKFLOW.model_dump_json()
    for forbidden in ("chinese", "military", "cmnee", "dataset"):
        assert forbidden not in rendered.lower()


def test_transition_lookup_and_actor_authority_fail_closed() -> None:
    from arw.workflows import (
        WorkflowDefinitionError,
        actor_can_commit,
        legal_transitions,
        require_workflow,
    )

    assert "start" in legal_transitions("core-research.v1", "initialized")
    assert actor_can_commit("parent_control_plane", "lifecycle")
    assert actor_can_commit("operator", "human_decision")
    assert not actor_can_commit("worker", "lifecycle")
    assert not actor_can_commit("hook", "recovery")
    with pytest.raises(WorkflowDefinitionError):
        require_workflow("invented-workflow")
    with pytest.raises(WorkflowDefinitionError):
        legal_transitions("core-research.v1", "invented-stage")
