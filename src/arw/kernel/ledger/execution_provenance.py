"""Pure parent-observed execution facts derived only from canonical events.

This module does not inspect a checkout, hooks, transcripts or a graph cache.
It validates event relationships for both command admission and cold replay.
"""

from __future__ import annotations

from dataclasses import dataclass

from arw.kernel.state.models import (
    EXECUTION_PROVENANCE_EVENT_TYPES,
    CanonicalEvent,
    DatasetMetadataAcceptedPayload,
    ExecutionActionFinishedPayload,
    ExecutionActionStartedPayload,
    ExecutionArtifactBoundPayload,
    ExecutionContextAcceptedPayload,
)


class ExecutionProvenanceError(ValueError):
    """The journal cannot support the asserted execution relation."""


@dataclass(frozen=True, slots=True)
class ActionFact:
    started: CanonicalEvent
    finished: CanonicalEvent | None

    @property
    def status(self) -> str:
        if self.finished is not None:
            return "terminally_observed"
        return (
            "adapter_entered_unresolved"
            if self.started.payload.kind == "tool"
            else "workflow_unresolved"
        )


@dataclass(frozen=True, slots=True)
class ControlFact:
    control_id: str
    step_id: str
    tool_id: str
    tool_action_id: str
    source_event_id: str


@dataclass(frozen=True, slots=True)
class ExecutionProvenanceState:
    context: CanonicalEvent | None
    dataset_metadata: CanonicalEvent | None
    metadata_history: tuple[CanonicalEvent, ...]
    actions: tuple[ActionFact, ...]
    control_actions: tuple[ControlFact, ...]
    bindings: tuple[CanonicalEvent, ...]
    intent_only_attempt_ids: tuple[str, ...]
    coverage_gaps: tuple[str, ...]

    @property
    def workflow_actions(self) -> tuple[ActionFact, ...]:
        return tuple(a for a in self.actions if a.started.payload.kind == "workflow")

    @property
    def tool_actions(self) -> tuple[ActionFact, ...]:
        return tuple(a for a in self.actions if a.started.payload.kind == "tool")


def project_execution_provenance(
    events: tuple[CanonicalEvent, ...] | list[CanonicalEvent],
) -> ExecutionProvenanceState:
    if not events or events[0].event_type != "run.initialized":
        raise ExecutionProvenanceError("execution projection requires run.initialized")
    run_id = events[0].run_id
    context: CanonicalEvent | None = None
    metadata: list[CanonicalEvent] = []
    actions: dict[str, ActionFact] = {}
    bindings: list[CanonicalEvent] = []
    entities: dict[str, tuple[str, str, str]] = {}
    binding_keys: set[tuple[str, str, str, str]] = set()
    output_sources: set[tuple[str, str]] = set()
    event_by_id: dict[str, CanonicalEvent] = {}
    assignments: dict[str, object] = {}
    assignment_events: dict[str, CanonicalEvent] = {}
    prepared_attempts: dict[str, str] = {}
    intents: list[str] = []
    stage = "initialized"
    for event in events:
        if event.run_id != run_id:
            raise ExecutionProvenanceError("execution event belongs to another run")
        p = event.payload
        if event.event_type == "lifecycle.transitioned":
            stage = p.to_stage
        if event.event_type in {"assignment.prepared", "assignment.superseded"}:
            assignments[p.assignment.assignment_id] = p.assignment
            assignment_events[p.assignment.assignment_id] = event
        elif event.event_type == "attempt.prepared":
            prepared_attempts[p.attempt.attempt_id] = p.assignment_id
        elif event.event_type == "attempt.lifecycle" and p.status == "active":
            intents.append(p.attempt_id)
        elif event.event_type == "execution_provenance.context_accepted":
            assert isinstance(p, ExecutionContextAcceptedPayload)
            if (
                event.actor_role != "parent_control_plane"
                or context is not None
                or intents
                or stage not in {"initialized", "prepared"}
            ):
                raise ExecutionProvenanceError(
                    "execution context must be parent-owned, outside prepare prefix, and frozen before dispatch"
                )
            if p.workflow_definition_id != "orchestration.phase4.v1":
                raise ExecutionProvenanceError(
                    "context is not the active workflow definition"
                )
            context = event
        elif event.event_type == "execution_provenance.dataset_metadata_accepted":
            assert isinstance(p, DatasetMetadataAcceptedPayload)
            if not metadata:
                if p.supersedes_event_id is not None:
                    raise ExecutionProvenanceError("initial metadata cannot supersede")
            elif (
                p.supersedes_event_id != metadata[-1].event_id
                or p.supersedes_event_sha256 != metadata[-1].event_sha256
            ):
                raise ExecutionProvenanceError(
                    "metadata must supersede the latest exact event"
                )
            metadata.append(event)
        elif event.event_type == "execution_provenance.action_started":
            assert isinstance(p, ExecutionActionStartedPayload)
            if context is None or p.action_id in actions:
                raise ExecutionProvenanceError("action needs context and unique ID")
            if p.kind == "tool":
                parent = actions.get(p.workflow_action_id)
                if (
                    parent is None
                    or parent.started.payload.kind != "workflow"
                    or parent.finished
                ):
                    raise ExecutionProvenanceError(
                        "tool action needs an active workflow action"
                    )
                if (
                    p.attempt_id not in intents
                    or prepared_attempts.get(p.attempt_id) != p.assignment_id
                ):
                    raise ExecutionProvenanceError(
                        "tool action needs exact dispatch intent"
                    )
                if p.assignment_id not in assignments:
                    raise ExecutionProvenanceError(
                        "tool action needs accepted assignment"
                    )
                steps = {step.step_id: step.tool_id for step in context.payload.steps}
                if steps.get(p.step_id) != p.tool_id:
                    raise ExecutionProvenanceError(
                        "tool action instrument differs from frozen step"
                    )
                if p.started_at < parent.started.payload.started_at:
                    raise ExecutionProvenanceError(
                        "tool action starts before workflow action"
                    )
                if any(
                    action.started.payload.kind == "tool"
                    and action.started.payload.attempt_id == p.attempt_id
                    for action in actions.values()
                ):
                    raise ExecutionProvenanceError(
                        "attempt already entered the adapter"
                    )
            elif not assignments:
                raise ExecutionProvenanceError(
                    "workflow action needs prepared assignments"
                )
            elif any(
                action.started.payload.kind == "workflow" and action.finished is None
                for action in actions.values()
            ):
                raise ExecutionProvenanceError(
                    "workflow dispatch action is already active"
                )
            actions[p.action_id] = ActionFact(event, None)
        elif event.event_type == "execution_provenance.action_finished":
            assert isinstance(p, ExecutionActionFinishedPayload)
            prior = actions.get(p.action_id)
            if prior is None or prior.finished is not None:
                raise ExecutionProvenanceError("finish needs one unfinished action")
            if p.ended_at < prior.started.payload.started_at:
                raise ExecutionProvenanceError("action end precedes start")
            if (
                prior.started.payload.kind == "tool"
                and p.outcome == "succeeded"
                and (p.host_agent_id is None or p.host_result_sha256 is None)
            ):
                raise ExecutionProvenanceError(
                    "successful tool action needs structured host observation"
                )
            actions[p.action_id] = ActionFact(prior.started, event)
        elif event.event_type == "execution_provenance.artifact_bound":
            assert isinstance(p, ExecutionArtifactBoundPayload)
            binding_key = (p.action_id, p.attempt_id, p.direction, p.entity_id)
            if binding_key in binding_keys:
                raise ExecutionProvenanceError("artifact binding was already recorded")
            identity = (p.source_event_id, p.relative_path, p.content_sha256)
            if p.entity_id in entities and entities[p.entity_id] != identity:
                raise ExecutionProvenanceError("artifact entity identity changed")
            if p.direction == "output" and p.entity_id in entities:
                raise ExecutionProvenanceError("artifact output was already produced")
            if (
                p.direction == "output"
                and (p.source_event_id, p.relative_path) in output_sources
            ):
                raise ExecutionProvenanceError(
                    "accepted output source was already bound"
                )
            action = actions.get(p.action_id)
            if action is None or (
                p.direction == "output" and action.started.payload.kind != "tool"
            ):
                raise ExecutionProvenanceError("binding needs a parent-observed action")
            started = action.started.payload
            if started.kind == "workflow":
                if (
                    p.direction != "input"
                    or prepared_attempts.get(p.attempt_id) != p.assignment_id
                    or p.attempt_id not in intents
                ):
                    raise ExecutionProvenanceError(
                        "workflow input binding needs exact dispatch intent"
                    )
            elif (
                started.assignment_id != p.assignment_id
                or started.attempt_id != p.attempt_id
            ):
                raise ExecutionProvenanceError(
                    "binding action/attempt identity differs"
                )
            assignment = assignments[p.assignment_id]
            source = event_by_id.get(p.source_event_id)
            if source is None or source.event_sha256 != p.source_event_sha256:
                raise ExecutionProvenanceError(
                    "binding source event is missing or stale"
                )
            if p.source_kind == "run_input":
                if (
                    source.event_type != "run.initialized"
                    or p.source_manifest_sha256 != source.payload.manifest_sha256
                    or p.entity_id != f"input.{p.content_sha256[:32]}"
                ):
                    raise ExecutionProvenanceError(
                        "run input binding is not the immutable input source"
                    )
            elif p.source_kind == "proposal":
                if p.direction != "output" or source.event_type != "proposal.accepted":
                    raise ExecutionProvenanceError(
                        "output needs accepted proposal source"
                    )
                if (
                    source.payload.attempt_id != p.attempt_id
                    or source.payload.assignment_id != p.assignment_id
                ):
                    raise ExecutionProvenanceError(
                        "proposal source does not bind producing attempt"
                    )
                if (
                    p.source_manifest_sha256 != source.payload.proposal_sha256
                    or not any(
                        a.relative_path == p.relative_path
                        and a.sha256 == p.content_sha256
                        and a.byte_count == p.byte_count
                        for a in source.payload.proposal.artifacts
                    )
                ):
                    raise ExecutionProvenanceError(
                        "binding differs from exact proposed artifact"
                    )
            elif p.source_kind == "artifact":
                if (
                    source.event_type != "artifact.accepted"
                    or p.source_manifest_sha256 != source.payload.manifest_sha256
                    or p.content_sha256 != source.payload.artifact_sha256
                    or p.entity_id != source.payload.artifact_id
                ):
                    raise ExecutionProvenanceError(
                        "binding differs from accepted artifact manifest"
                    )
                if (
                    p.direction == "output"
                    and source.payload.attempt_id != p.attempt_id
                ):
                    raise ExecutionProvenanceError("artifact output attempt differs")
                if (
                    p.direction == "input"
                    and source.sequence >= assignment_events[p.assignment_id].sequence
                ):
                    raise ExecutionProvenanceError(
                        "input artifact was not accepted before assignment"
                    )
            if (
                p.direction == "input"
                and p.content_sha256 not in assignment.input_sha256
            ):
                raise ExecutionProvenanceError(
                    "input is not in the immutable assignment"
                )
            entities[p.entity_id] = identity
            binding_keys.add(binding_key)
            if p.direction == "output":
                output_sources.add((p.source_event_id, p.relative_path))
            bindings.append(event)
        if (
            event.event_type in EXECUTION_PROVENANCE_EVENT_TYPES
            and event.actor_role != "parent_control_plane"
        ):
            raise ExecutionProvenanceError(
                "execution provenance requires parent authority"
            )
        event_by_id[event.event_id] = event
    tool_attempts = {
        a.started.payload.attempt_id
        for a in actions.values()
        if a.started.payload.kind == "tool"
    }
    intent_only = tuple(attempt for attempt in intents if attempt not in tool_attempts)
    gaps: list[str] = []
    if context is None:
        gaps.append("workflow_context")
    else:
        if context.payload.workflow_source.content_base64 is None:
            gaps.append("workflow_source_bytes")
        if context.payload.workflow_source.programming_language is None:
            gaps.append("programming_language")
        if (
            context.payload.runtime.version is None
            or context.payload.runtime.build_sha256 is None
        ):
            gaps.append("declared_runtime_identity")
    if not metadata:
        gaps.append("dataset_metadata")
    if not any(a.started.payload.kind == "workflow" for a in actions.values()):
        gaps.append("workflow_action")
    elif not any(a.started.payload.kind == "tool" for a in actions.values()):
        gaps.append("tool_action")
    if intent_only:
        gaps.append("intent_only")
    if any(a.finished is None for a in actions.values()):
        gaps.append("unresolved_action")
    for action in actions.values():
        started = action.started.payload
        if started.kind != "tool":
            continue
        expected_inputs = set(assignments[started.assignment_id].input_sha256)
        actual_inputs = {
            e.payload.content_sha256
            for e in bindings
            if e.payload.direction == "input"
            and e.payload.attempt_id == started.attempt_id
        }
        if actual_inputs != expected_inputs:
            gaps.append(f"input_binding:{started.attempt_id}")
        proposals = [
            e
            for e in events
            if e.event_type == "proposal.accepted"
            and e.payload.attempt_id == started.attempt_id
        ]
        expected_outputs = {
            (a.relative_path, a.sha256, a.byte_count)
            for e in proposals
            for a in e.payload.proposal.artifacts
        }
        actual_outputs = {
            (e.payload.relative_path, e.payload.content_sha256, e.payload.byte_count)
            for e in bindings
            if e.payload.direction == "output"
            and e.payload.attempt_id == started.attempt_id
        }
        if actual_outputs != expected_outputs:
            gaps.append(f"output_binding:{started.attempt_id}")
        if action.finished and (
            action.finished.payload.host_agent_id is None
            or action.finished.payload.observed_runtime_version is None
        ):
            gaps.append(f"observed_host_identity:{started.attempt_id}")
    controls = tuple(
        ControlFact(
            control_id=f"control.{action.started.event_id[4:]}",
            step_id=action.started.payload.step_id,
            tool_id=action.started.payload.tool_id,
            tool_action_id=action.started.payload.action_id,
            source_event_id=action.started.event_id,
        )
        for action in actions.values()
        if action.started.payload.kind == "tool"
    )
    return ExecutionProvenanceState(
        context,
        metadata[-1] if metadata else None,
        tuple(metadata),
        tuple(actions.values()),
        controls,
        tuple(bindings),
        intent_only,
        tuple(gaps),
    )
