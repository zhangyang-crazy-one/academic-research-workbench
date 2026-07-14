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


def test_manifest_workflow_identity_is_pairwise_and_registry_bound(tmp_path) -> None:
    from arw.journal import JournalError, initialize_run
    from arw.models import InitRunRequest
    from arw.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    (root / "input").mkdir(parents=True)
    source = root / "input" / "source.txt"
    source.write_text("bound workflow\n", encoding="utf-8")
    import hashlib

    common = {
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000001",
        "occurred_at": "2026-07-13T00:00:00Z",
        "immutable_input": {
            "path": "input/source.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "capabilities": ["canonical-journal"],
        "event_id": "evt-00000000-0000-4000-8000-000000000001",
        "command_id": "cmd-00000000-0000-4000-8000-000000000001",
        "actor_id": "parent.runtime",
    }
    with pytest.raises(ValueError, match="provided together"):
        InitRunRequest.model_validate(common)

    request = InitRunRequest.model_validate(
        {**common, "workflow_definition_sha256": "f" * 64}
    )
    with pytest.raises(JournalError, match="does not match"):
        initialize_run(root, request)
    assert not (root / "run-manifest.json").exists()


def test_phase4_workflow_is_frozen_parent_only_and_blocks_pending_completion() -> None:
    from arw.workflows import (
        PHASE4_WORKFLOW,
        WorkflowDefinitionError,
        actor_can_commit,
        authorize_phase4_transition,
        legal_transitions,
    )

    assert PHASE4_WORKFLOW.definition_id in {
        "orchestration.phase4.v1",
        "academic-pipeline.phase4.v1",
    }
    assert "dispatch" in legal_transitions(PHASE4_WORKFLOW.definition_id, "prepared")
    assert actor_can_commit("parent_control_plane", "orchestration")
    assert not actor_can_commit("worker", "orchestration")
    assert not actor_can_commit("hook", "orchestration")
    assert authorize_phase4_transition(
        PHASE4_WORKFLOW.definition_id,
        "prepared",
        "dispatch",
        actor_role="parent_control_plane",
        blockers=(),
    ).to_stage == "dispatching"
    with pytest.raises(WorkflowDefinitionError, match="blocker"):
        authorize_phase4_transition(
            PHASE4_WORKFLOW.definition_id,
            "gate_resolution",
            "complete",
            actor_role="parent_control_plane",
            blockers=("pending-human-decision",),
        )
    with pytest.raises(WorkflowDefinitionError, match="parent"):
        authorize_phase4_transition(
            PHASE4_WORKFLOW.definition_id,
            "prepared",
            "dispatch",
            actor_role="worker",
            blockers=(),
        )
