from __future__ import annotations

from datetime import UTC, datetime

import pytest


def _event(event_type: str, payload: object, *, revision: int, role: str = "parent_control_plane"):
    from arw.models import CanonicalEvent

    return CanonicalEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": event_type,
            "event_id": f"evt-00000000-0000-4000-8000-{revision:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{revision:012x}",
            "run_id": "run-00000000-0000-4000-8000-000000000001",
            "sequence": revision,
            "occurred_at": f"2026-07-13T00:00:{revision:02d}Z",
            "expected_revision": revision - 1,
            "resulting_revision": revision,
            "actor_id": "parent.runtime" if role == "parent_control_plane" else "worker.agent",
            "actor_role": role,
            "prev_event_sha256": "0" * 64,
            "payload": payload,
            "event_sha256": f"{revision:064x}",
        }
    )


def test_reducer_applies_legal_lifecycle_decisions_attempts_and_passport() -> None:
    from arw.reducer import reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "lifecycle.transitioned",
            {"transition_id": "start", "from_stage": "initialized", "to_stage": "intake"},
            revision=2,
        ),
        _event(
            "human_decision.requested",
            {
                "decision_id": "decision.review-route",
                "blocker_code": "human-choice-required",
                "starting_revision": 2,
                "allowed_choices": ["continue", "abort"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["begin_work"],
            },
            revision=3,
        ),
        _event(
            "attempt.started",
            {
                "attempt_id": "attempt.writer-001",
                "base_revision": 3,
                "consumed_sha256": [f"{3:064x}"],
            },
            revision=4,
        ),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": None,
                "checkpoint_kind": "explicit",
                "based_on_revision": 4,
                "stage": "intake",
                "fresh_until": "2026-07-14T00:00:00Z",
            },
            revision=5,
        ),
    ]
    state = reduce_events(
        "core-research.v1",
        events,
        now=datetime(2026, 7, 13, 12, tzinfo=UTC),
    )
    assert state.stage == "intake"
    assert state.accepted_revision == 5
    assert state.current_passport_sha256 == "c" * 64
    assert [item.decision_id for item in state.pending_human_decisions] == ["decision.review-route"]
    assert [item.attempt_id for item in state.active_attempts] == ["attempt.writer-001"]


def test_reducer_rejects_unauthorized_or_illegal_transition() -> None:
    from arw.reducer import ReducerError, reduce_events

    initialized = _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)
    unauthorized = _event(
        "lifecycle.transitioned",
        {"transition_id": "start", "from_stage": "initialized", "to_stage": "intake"},
        revision=2,
        role="worker",
    )
    with pytest.raises(ReducerError, match="authorized"):
        reduce_events("core-research.v1", [initialized, unauthorized])

    illegal = _event(
        "lifecycle.transitioned",
        {"transition_id": "complete", "from_stage": "initialized", "to_stage": "completed"},
        revision=2,
    )
    with pytest.raises(ReducerError, match="legal"):
        reduce_events("core-research.v1", [initialized, illegal])


def test_reducer_requires_explicit_actor_role_for_phase2_initialization() -> None:
    from arw.reducer import ReducerError, reduce_events

    initialized = _event(
        "run.initialized", {"manifest_sha256": "a" * 64}, revision=1
    ).model_copy(update={"actor_role": None})

    with pytest.raises(ReducerError, match="explicit actor role"):
        reduce_events("core-research.v1", [initialized])

    legacy = reduce_events("academic-pipeline.legacy-v1", [initialized])
    assert legacy.accepted_revision == 1


def test_reducer_keeps_shared_blocker_until_every_decision_is_resolved() -> None:
    from arw.reducer import reduce_events

    events = [_event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)]
    for revision, decision_id in ((2, "decision.first"), (3, "decision.second")):
        events.append(
            _event(
                "human_decision.requested",
                {
                    "decision_id": decision_id,
                    "blocker_code": "human-choice-required",
                    "starting_revision": revision - 1,
                    "allowed_choices": ["continue"],
                    "rationale_required": False,
                    "source_event_ids": [],
                    "unlock_transitions": ["start"],
                },
                revision=revision,
            )
        )
    events.append(
        _event(
            "human_decision.resolved",
            {"decision_id": "decision.first", "choice": "continue", "rationale": None},
            revision=4,
        )
    )

    state = reduce_events("core-research.v1", events)
    assert [item.decision_id for item in state.pending_human_decisions] == [
        "decision.second"
    ]
    assert [item.code for item in state.blockers] == ["human-choice-required"]
    assert state.legal_next_transitions == []


@pytest.mark.parametrize("identity", ["decision", "attempt", "artifact"])
def test_reducer_rejects_reused_stable_runtime_identity(identity: str) -> None:
    from arw.reducer import ReducerError, reduce_events

    events = [_event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)]
    if identity == "decision":
        events.extend(
            [
                _event(
                    "human_decision.requested",
                    {
                        "decision_id": "decision.once",
                        "blocker_code": "human-choice-required",
                        "starting_revision": 1,
                        "allowed_choices": ["continue"],
                        "rationale_required": False,
                        "source_event_ids": [],
                        "unlock_transitions": ["start"],
                    },
                    revision=2,
                ),
                _event(
                    "human_decision.resolved",
                    {"decision_id": "decision.once", "choice": "continue", "rationale": None},
                    revision=3,
                ),
                _event(
                    "human_decision.requested",
                    {
                        "decision_id": "decision.once",
                        "blocker_code": "human-choice-required",
                        "starting_revision": 3,
                        "allowed_choices": ["continue"],
                        "rationale_required": False,
                        "source_event_ids": [],
                        "unlock_transitions": ["start"],
                    },
                    revision=4,
                ),
            ]
        )
    elif identity == "attempt":
        events.extend(
            [
                _event(
                    "attempt.started",
                    {"attempt_id": "attempt.once", "base_revision": 1, "consumed_sha256": []},
                    revision=2,
                ),
                _event(
                    "attempt.closed",
                    {"attempt_id": "attempt.once", "outcome": "completed", "proposal_sha256": None},
                    revision=3,
                ),
                _event(
                    "attempt.started",
                    {"attempt_id": "attempt.once", "base_revision": 3, "consumed_sha256": []},
                    revision=4,
                ),
            ]
        )
    else:
        events.extend(
            [
                _event(
                    "artifact.accepted",
                    {
                        "artifact_id": "artifact.once",
                        "manifest_sha256": "b" * 64,
                        "artifact_sha256": "c" * 64,
                        "attempt_id": None,
                    },
                    revision=2,
                ),
                _event(
                    "artifact.accepted",
                    {
                        "artifact_id": "artifact.once",
                        "manifest_sha256": "d" * 64,
                        "artifact_sha256": "e" * 64,
                        "attempt_id": None,
                    },
                    revision=3,
                ),
            ]
        )

    with pytest.raises(ReducerError, match="already used"):
        reduce_events("core-research.v1", events)


def test_freshness_is_dynamic_and_does_not_change_events() -> None:
    from arw.reducer import reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": None,
                "checkpoint_kind": "explicit",
                "based_on_revision": 1,
                "stage": "initialized",
                "fresh_until": "2026-07-13T01:00:00Z",
            },
            revision=2,
        ),
    ]
    before = [event.model_dump(mode="json") for event in events]
    state = reduce_events(
        "core-research.v1",
        events,
        now=datetime(2026, 7, 13, 2, tzinfo=UTC),
    )
    assert "evidence-expired" in [blocker.code for blocker in state.blockers]
    assert [event.model_dump(mode="json") for event in events] == before


@pytest.mark.parametrize(
    ("based_on_revision", "supersedes", "message"),
    [
        (0, None, "stage/revision"),
        (1, "d" * 64, "supersession"),
    ],
)
def test_reducer_rejects_non_exact_or_branching_passport(
    based_on_revision: int, supersedes: str | None, message: str
) -> None:
    from arw.reducer import ReducerError, reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": supersedes,
                "checkpoint_kind": "explicit",
                "based_on_revision": based_on_revision,
                "stage": "initialized",
                "fresh_until": None,
            },
            revision=2,
        ),
    ]

    with pytest.raises(ReducerError, match=message):
        reduce_events("core-research.v1", events)
