from __future__ import annotations

import hashlib
from pathlib import Path


RUN_ID = "run-00000000-0000-4000-8000-000000000031"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _service(tmp_path: Path):
    from arw.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.runtime import RuntimeCommandService
    from arw.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("attempt run\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T02:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000031",
                "command_id": "cmd-00000000-0000-4000-8000-000000000031",
                "actor_id": "parent.runtime",
            }
        ),
    )
    return root, RuntimeCommandService(root)


def _base(event: int, revision: int, role: str = "parent_control_plane") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "event_id": f"evt-00000000-0000-4000-8000-{event:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{event:012x}",
        "expected_revision": revision,
        "occurred_at": f"2026-07-13T02:01:{event % 60:02d}Z",
        "actor_id": "parent.runtime" if role == "parent_control_plane" else "operator.user",
        "actor_role": role,
    }


def test_decision_and_attempt_state_survive_fresh_replay(tmp_path: Path) -> None:
    from arw.kernel.state.models import AttemptStartRequest, HumanDecisionRequest
    from arw.runtime import RuntimeCommandService

    root, service = _service(tmp_path)
    decision = HumanDecisionRequest.model_validate(
        {
            **_base(41, 1),
            "decision_id": "decision.route",
            "blocker_code": "human-choice-required",
            "allowed_choices": ["continue", "abort"],
            "rationale_required": True,
            "source_event_ids": [],
            "unlock_transitions": ["start"],
        }
    )
    requested = service.request_decision(decision)
    assert requested.accepted
    attempt = AttemptStartRequest.model_validate(
        {
            **_base(42, 2),
            "attempt_id": "attempt.writer-001",
            "base_revision": 2,
            "consumed_sha256": [requested.state.ledger_head_sha256],
        }
    )
    started = service.start_attempt(attempt)
    assert started.accepted
    rebuilt = RuntimeCommandService(root).read_state()
    assert [item.decision_id for item in rebuilt.pending_human_decisions] == ["decision.route"]
    assert [item.attempt_id for item in rebuilt.active_attempts] == ["attempt.writer-001"]


def test_decision_resolution_and_attempt_close_are_separate_events(tmp_path: Path) -> None:
    from arw.kernel.state.models import (
        AttemptCloseRequest,
        AttemptStartRequest,
        HumanDecisionRequest,
        HumanDecisionResolveRequest,
    )

    root, service = _service(tmp_path)
    requested = service.request_decision(
        HumanDecisionRequest.model_validate(
            {
                **_base(43, 1),
                "decision_id": "decision.route",
                "blocker_code": "human-choice-required",
                "allowed_choices": ["continue", "abort"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["start"],
            }
        )
    )
    resolved = service.resolve_decision(
        HumanDecisionResolveRequest.model_validate(
            {
                **_base(44, 2, "operator"),
                "decision_id": "decision.route",
                "choice": "continue",
                "rationale": "Proceed with the registered route.",
            }
        )
    )
    assert requested.accepted and resolved.accepted
    started = service.start_attempt(
        AttemptStartRequest.model_validate(
            {
                **_base(45, 3),
                "attempt_id": "attempt.writer-001",
                "base_revision": 3,
                "consumed_sha256": [resolved.state.ledger_head_sha256],
            }
        )
    )
    closed = service.close_attempt(
        AttemptCloseRequest.model_validate(
            {
                **_base(46, 4),
                "attempt_id": "attempt.writer-001",
                "outcome": "completed",
                "proposal_sha256": "e" * 64,
            }
        )
    )
    assert started.accepted and closed.accepted
    assert closed.state.pending_human_decisions == []
    assert closed.state.active_attempts == []
    assert closed.state.accepted_revision == 5


def test_stale_or_unknown_attempt_requests_append_nothing(tmp_path: Path) -> None:
    from arw.kernel.state.models import AttemptCloseRequest, AttemptStartRequest

    root, service = _service(tmp_path)
    stale = AttemptStartRequest.model_validate(
        {
            **_base(47, 1),
            "attempt_id": "attempt.writer-001",
            "base_revision": 0,
            "consumed_sha256": ["d" * 64],
        }
    )
    before = _tree(root)
    rejected = service.start_attempt(stale)
    assert rejected.rejection is not None
    assert rejected.rejection.code in {"stale-attempt-base", "stale-consumed-input"}
    assert _tree(root) == before

    unknown = AttemptCloseRequest.model_validate(
        {
            **_base(48, 1),
            "attempt_id": "attempt.unknown-001",
            "outcome": "failed",
            "proposal_sha256": None,
        }
    )
    rejected = service.close_attempt(unknown)
    assert rejected.rejection is not None
    assert rejected.rejection.code == "unknown-attempt"
    assert _tree(root) == before


def test_pending_decision_blocks_lifecycle_transition_without_mutation(
    tmp_path: Path,
) -> None:
    from arw.kernel.state.models import HumanDecisionRequest, LifecycleTransitionRequest

    root, service = _service(tmp_path)
    requested = service.request_decision(
        HumanDecisionRequest.model_validate(
            {
                **_base(70, 1),
                "decision_id": "decision.blocks-transition",
                "blocker_code": "human-choice-required",
                "allowed_choices": ["continue", "abort"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["start"],
            }
        )
    )
    assert requested.accepted
    before = _tree(root)
    rejected = service.execute_transition(
        LifecycleTransitionRequest.model_validate(
            {
                **_base(71, 2),
                "transition_id": "start",
                "from_stage": "initialized",
            }
        )
    )

    assert rejected.rejection is not None
    assert rejected.rejection.code == "runtime-blocked"
    assert _tree(root) == before
