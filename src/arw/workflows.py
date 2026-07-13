"""Immutable registered workflow definitions and event authority."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from arw.canonical import canonical_json_bytes, sha256_hex
from arw.models import ActorRole, Sha256, StableRuntimeId, StrictModel


class WorkflowDefinitionError(ValueError):
    """A workflow, stage, transition, or actor category is not registered."""


class TransitionDefinition(StrictModel):
    transition_id: StableRuntimeId
    from_stages: list[StableRuntimeId] = Field(min_length=1)
    to_stage: StableRuntimeId
    coherent_checkpoint: bool = False


class WorkflowDefinition(StrictModel):
    definition_id: StableRuntimeId
    definition_version: StableRuntimeId
    stages: list[StableRuntimeId] = Field(min_length=2)
    terminal_stages: list[StableRuntimeId]
    transitions: list[TransitionDefinition] = Field(min_length=1)
    sha256: Sha256

    @model_validator(mode="after")
    def internally_consistent(self) -> "WorkflowDefinition":
        stages = set(self.stages)
        if len(stages) != len(self.stages):
            raise ValueError("workflow stages must be unique")
        if not set(self.terminal_stages) <= stages:
            raise ValueError("terminal stages must be registered")
        transition_ids = [item.transition_id for item in self.transitions]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("workflow transition IDs must be unique")
        for transition in self.transitions:
            if not set(transition.from_stages) <= stages or transition.to_stage not in stages:
                raise ValueError("transition stages must be registered")
        return self


def workflow_definition_sha256(definition: WorkflowDefinition) -> str:
    payload = definition.model_dump(mode="json", exclude={"sha256"})
    return sha256_hex(canonical_json_bytes(payload))


_DRAFT = WorkflowDefinition(
    definition_id="core-research.v1",
    definition_version="v1.0.0",
    stages=["initialized", "intake", "work", "review", "completed", "aborted"],
    terminal_stages=["completed", "aborted"],
    transitions=[
        TransitionDefinition(transition_id="start", from_stages=["initialized"], to_stage="intake"),
        TransitionDefinition(transition_id="begin_work", from_stages=["intake"], to_stage="work"),
        TransitionDefinition(
            transition_id="request_review",
            from_stages=["work"],
            to_stage="review",
            coherent_checkpoint=True,
        ),
        TransitionDefinition(transition_id="revise", from_stages=["review"], to_stage="work"),
        TransitionDefinition(
            transition_id="complete",
            from_stages=["review"],
            to_stage="completed",
            coherent_checkpoint=True,
        ),
        TransitionDefinition(
            transition_id="abort",
            from_stages=["initialized", "intake", "work", "review"],
            to_stage="aborted",
        ),
    ],
    sha256="0" * 64,
)
CORE_WORKFLOW = _DRAFT.model_copy(update={"sha256": workflow_definition_sha256(_DRAFT)})

# Phase 1 manifests bind this identity through their frozen family/mode/schema tuple.
LEGACY_WORKFLOW_ID = "academic-pipeline.legacy-v1"
WORKFLOW_REGISTRY: dict[str, WorkflowDefinition] = {
    CORE_WORKFLOW.definition_id: CORE_WORKFLOW,
    LEGACY_WORKFLOW_ID: CORE_WORKFLOW,
}

EventCategory = Literal[
    "initialization",
    "baseline",
    "lifecycle",
    "human_decision",
    "attempt",
    "artifact",
    "passport",
    "resume",
    "recovery",
]

_AUTHORITY: dict[EventCategory, frozenset[ActorRole]] = {
    "initialization": frozenset({"parent_control_plane"}),
    "baseline": frozenset({"parent_control_plane"}),
    "lifecycle": frozenset({"parent_control_plane"}),
    "human_decision": frozenset({"parent_control_plane", "operator"}),
    "attempt": frozenset({"parent_control_plane"}),
    "artifact": frozenset({"parent_control_plane"}),
    "passport": frozenset({"parent_control_plane"}),
    "resume": frozenset({"operator"}),
    "recovery": frozenset({"operator"}),
}


def require_workflow(definition_id: str) -> WorkflowDefinition:
    try:
        return WORKFLOW_REGISTRY[definition_id]
    except KeyError as error:
        raise WorkflowDefinitionError(f"unknown workflow definition: {definition_id}") from error


def legal_transitions(definition_id: str, stage: str) -> tuple[str, ...]:
    definition = require_workflow(definition_id)
    if stage not in definition.stages:
        raise WorkflowDefinitionError(f"unknown workflow stage: {stage}")
    return tuple(
        item.transition_id for item in definition.transitions if stage in item.from_stages
    )


def require_transition(definition_id: str, stage: str, transition_id: str) -> TransitionDefinition:
    definition = require_workflow(definition_id)
    for transition in definition.transitions:
        if transition.transition_id == transition_id and stage in transition.from_stages:
            return transition
    raise WorkflowDefinitionError(
        f"transition {transition_id!r} is not legal from stage {stage!r}"
    )


def actor_can_commit(role: ActorRole, category: EventCategory) -> bool:
    return role in _AUTHORITY.get(category, frozenset())


def event_category(event_type: str) -> EventCategory:
    if event_type == "run.initialized":
        return "initialization"
    if event_type == "baseline.probe_recorded":
        return "baseline"
    prefix = event_type.split(".", 1)[0]
    mapping: dict[str, EventCategory] = {
        "lifecycle": "lifecycle",
        "human_decision": "human_decision",
        "attempt": "attempt",
        "artifact": "artifact",
        "passport": "passport",
        "resume": "resume",
        "recovery": "recovery",
    }
    try:
        return mapping[prefix]
    except KeyError as error:
        raise WorkflowDefinitionError(f"unknown event category: {event_type}") from error
