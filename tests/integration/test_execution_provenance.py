"""Canonical parent observations remain independent of crate serialization."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.execution import (
    ExecutionPolicySnapshot,
    HostResult,
    NativeProcessFailure,
    ProcessFailure,
)
from arw.kernel.execution.orchestration import AssignmentSpec, OrchestrationService
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.execution_provenance import project_execution_provenance
from arw.kernel.ledger.journal import (
    JournalError,
    build_runtime_event,
    initialize_run,
    replay_run,
)
from arw.kernel.ledger.reducer import ReducerError, reduce_events
from arw.kernel.ledger.workflows import PHASE4_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    ExecutionActionFinishedPayload,
    ExecutionActionStartedPayload,
    ExecutionArtifactBoundPayload,
    ExecutionContextAcceptedPayload,
    InitRunRequest,
    RunManifest,
    RuntimeCommandRequest,
    WorkflowSource,
)
from arw.kernel.state.orchestration_models import (
    ProposedArtifact,
    WorkerProposal,
    canonical_orchestration_model_bytes,
)
from tests.integration.test_orchestration_lifecycle import _ProposalWritingAdapter, _run


def _request(root, number: int, *, role: str = "parent_control_plane"):
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": replay_run(root).run_id,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
            "expected_revision": replay_run(root).revision,
            "occurred_at": "2026-07-15T01:00:01Z",
            "actor_id": "parent.runtime"
            if role == "parent_control_plane"
            else "worker.agent",
            "actor_role": role,
        }
    )


def _language_identity():
    return {
        "uri": "https://example.org/languages/example/1.0",
        "name": "ExampleLang",
        "url": "https://example.org/languages/example",
        "version": "1.0",
    }


def test_workflow_language_requires_complete_explicit_identity():
    source = {
        "entity_id": "workflow.source",
        "relative_path": "workflow.json",
        "content_base64": "e30=",
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "programming_language": "JSON",
    }
    with pytest.raises(ValidationError):
        WorkflowSource.model_validate(source)
    source["programming_language"] = {"name": "ExampleLang"}
    with pytest.raises(ValidationError):
        WorkflowSource.model_validate(source)
    source["programming_language"] = _language_identity()
    accepted = WorkflowSource.model_validate(source)
    assert accepted.programming_language.uri == _language_identity()["uri"]
    source["programming_language"] = None
    assert WorkflowSource.model_validate(source).programming_language is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uri", "example-language"),
        ("url", "relative/language"),
        ("url", "https://user:password@example.org/language"),
        ("name", "  "),
        ("version", "  "),
    ],
)
def test_workflow_language_rejects_unusable_identity(field, value):
    source = {
        "entity_id": "workflow.source",
        "relative_path": "workflow.json",
        "content_base64": "e30=",
        "sha256": hashlib.sha256(b"{}").hexdigest(),
        "programming_language": _language_identity() | {field: value},
    }
    with pytest.raises(ValidationError):
        WorkflowSource.model_validate(source)


def test_context_metadata_revision_and_parent_authority(tmp_path):
    root, _ = _run(tmp_path)
    runtime = RuntimeCommandService(root)
    initial_bytes = (
        (root / "events.jsonl").read_bytes()
        if (root / "events.jsonl").exists()
        else None
    )
    context = {
        "workflow_definition_id": "orchestration.phase4.v1",
        "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
        "workflow_source": {
            "entity_id": "workflow.source",
            "relative_path": "workflow.json",
            "content_base64": "e30=",
            "sha256": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "programming_language": _language_identity(),
        },
        "steps": [
            {"step_id": "step.dispatch", "tool_id": "tool.adapter", "position": 1}
        ],
        "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
        "runtime": {"name": "Codex", "version": None, "build_sha256": None},
    }
    denied = runtime.accept_execution_context(
        _request(root, 700, role="worker"), context
    )
    assert not denied.accepted and denied.rejection.code == "unauthorized-actor"
    accepted = runtime.accept_execution_context(_request(root, 701), context)
    assert accepted.accepted
    assert accepted.event.schema_version == "1.4.0"
    from arw.kernel.policy.schema_registry import SchemaRegistryError, validate_instance

    invalid_wire = accepted.event.model_dump(mode="json")
    invalid_wire["payload"]["workflow_source"]["programming_language"] = "JSON"
    with pytest.raises(SchemaRegistryError):
        validate_instance("event.schema.json", invalid_wire)
    assert not runtime.accept_execution_context(_request(root, 702), context).accepted
    metadata = runtime.accept_dataset_metadata(
        _request(root, 703),
        {
            "name": "Research run",
            "description": "Observed run",
            "date_published": "2026-07-15",
            "license": "https://example.org/license",
            "supersedes_event_id": None,
            "supersedes_event_sha256": None,
            "rationale": None,
        },
    )
    assert metadata.accepted
    correction = runtime.accept_dataset_metadata(
        _request(root, 704),
        {
            "name": "Research run corrected",
            "description": "Observed run",
            "date_published": "2026-07-15",
            "license": "https://example.org/license",
            "supersedes_event_id": metadata.event.event_id,
            "supersedes_event_sha256": metadata.event.event_sha256,
            "rationale": "Correct title",
        },
    )
    assert correction.accepted
    projection = project_execution_provenance(replay_run(root).events)
    assert projection.dataset_metadata.event_id == correction.event.event_id
    assert len(projection.metadata_history) == 2
    assert runtime.read_state().schema_version == "1.0.0"
    assert initial_bytes is None or (root / "events.jsonl").read_bytes().startswith(
        initial_bytes
    )


class _CompleteAdapter(_ProposalWritingAdapter):
    async def dispatch(self, spec):
        result = await super().dispatch(spec)
        output = spec.attempt_root / "result" / "report.json"
        output.write_bytes(b"{}")
        proposal = WorkerProposal.model_validate_json(result.proposal_path.read_bytes())
        artifact = ProposedArtifact(
            relative_path="report.json",
            sha256=hashlib.sha256(b"{}").hexdigest(),
            media_type="application/json",
            schema_id="arw.review-report.v1",
            byte_count=2,
        )
        result.proposal_path.write_bytes(
            canonical_orchestration_model_bytes(
                proposal.model_copy(update={"artifacts": (artifact,)})
            )
        )
        return result


def _prepared_context_run(
    tmp_path, adapter, *, runtime_identity=None, known_language=True
):
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=adapter)
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.architect-001",
                stage_id="preparing",
                task_id="task.execute-001",
                role_id="research_architect",
                worker_identity_id="worker.architect-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    context = {
        "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
        "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
        "workflow_source": {
            "entity_id": "workflow.source",
            "relative_path": "workflow.json",
            "content_base64": "e30=",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
            "programming_language": _language_identity() if known_language else None,
        },
        "steps": [
            {"step_id": "step.dispatch", "tool_id": "tool.adapter", "position": 1}
        ],
        "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
        "runtime": runtime_identity
        or {"name": "Codex", "version": None, "build_sha256": None},
    }
    assert service.runtime.accept_execution_context(
        _request(root, 720), context
    ).accepted
    return root, service, prepared


def test_unknown_language_remains_explicit_and_incomplete(tmp_path):
    root, service, _ = _prepared_context_run(
        tmp_path, _CompleteAdapter(), known_language=False
    )
    facts = service.runtime.read_execution_provenance()
    assert facts.context.payload.workflow_source.programming_language is None
    assert "programming_language" in facts.coverage_gaps
    assert replay_run(root).recovery_health == "healthy"


def test_parent_dispatch_records_exact_tool_and_proposal_relations(tmp_path):
    root, service, prepared = _prepared_context_run(tmp_path, _CompleteAdapter())
    report = asyncio.run(service.dispatch(_request(root, 721), prepared))
    assert report.outcomes[0].status == "completed"
    events = replay_run(root).events
    facts = project_execution_provenance(events)
    assert len(facts.workflow_actions) == len(facts.tool_actions) == 1
    assert len(facts.control_actions) == 1
    assert (
        facts.control_actions[0].step_id
        == facts.tool_actions[0].started.payload.step_id
    )
    assert (
        facts.control_actions[0].tool_action_id
        == facts.tool_actions[0].started.payload.action_id
    )
    assert facts.workflow_actions[0].finished is not None
    assert facts.tool_actions[0].finished is not None
    assert facts.intent_only_attempt_ids == ()
    assert {b.payload.direction for b in facts.bindings} == {"input", "output"}
    output = next(b for b in facts.bindings if b.payload.direction == "output")
    source = next(e for e in events if e.event_id == output.payload.source_event_id)
    assert source.event_type == "proposal.accepted"
    assert output.payload.source_event_sha256 == source.event_sha256
    assert output.payload.byte_count == 2
    assert "dataset_metadata" in facts.coverage_gaps
    metadata = service.runtime.accept_dataset_metadata(
        _request(root, 725),
        {
            "name": "Completed study",
            "description": "Run output",
            "date_published": "2026-07-15",
            "license": "https://example.org/license",
            "supersedes_event_id": None,
            "supersedes_event_sha256": None,
            "rationale": None,
        },
    )
    assert metadata.accepted
    later = service.runtime.read_execution_provenance()
    assert later.dataset_metadata.payload.name == "Completed study"
    assert later.context == facts.context
    assert "dataset_metadata" not in later.coverage_gaps
    from arw.kernel.policy.schema_registry import validate_instance

    for event in events:
        if event.schema_version == "1.4.0":
            validate_instance("event.schema.json", event.model_dump(mode="json"))
    retained = (
        root
        / "attempts"
        / output.payload.attempt_id
        / "result"
        / output.payload.relative_path
    )
    retained.write_bytes(b"[]")
    rejected = replay_run(root)
    assert rejected.recovery_health == "blocked"
    assert "digest" in rejected.recovery_message
    with pytest.raises(JournalError, match="digest"):
        service.runtime.read_execution_provenance()


def test_duplicate_stale_and_rehashed_invalid_provenance(tmp_path):
    root, service, _ = _prepared_context_run(tmp_path, _CompleteAdapter())
    facts = service.runtime.read_execution_provenance()
    assert facts.context is not None
    request = _request(root, 721)
    metadata = {
        "name": "Run",
        "description": "Description",
        "date_published": "2026-07-15",
        "license": "https://example.org/license",
        "supersedes_event_id": None,
        "supersedes_event_sha256": None,
        "rationale": None,
    }
    assert service.runtime.accept_dataset_metadata(request, metadata).accepted
    assert (
        service.runtime.accept_dataset_metadata(request, metadata).rejection.code
        == "duplicate-event-id"
    )
    stale = request.model_copy(
        update={
            "event_id": _request(root, 722).event_id,
            "command_id": _request(root, 722).command_id,
        }
    )
    assert (
        service.runtime.accept_dataset_metadata(stale, metadata).rejection.code
        == "stale-revision"
    )
    accepted = replay_run(root)
    bad = build_runtime_event(
        accepted,
        event_type="execution_provenance.dataset_metadata_accepted",
        event_id="evt-00000000-0000-4000-8000-000000000723",
        command_id="cmd-00000000-0000-4000-8000-000000000723",
        occurred_at="2026-07-15T01:00:02Z",
        actor_id="parent.runtime",
        actor_role="parent_control_plane",
        payload=metadata,
    )
    # The event hash is valid, yet its supersession relation is not.
    with pytest.raises(ReducerError, match="supersede"):
        reduce_events(accepted.workflow_definition_id, (*accepted.events, bad))
    with pytest.raises(JournalError, match="invalid event"):
        build_runtime_event(
            accepted,
            event_type="execution_provenance.dataset_metadata_accepted",
            event_id="evt-00000000-0000-4000-8000-000000000724",
            command_id="cmd-00000000-0000-4000-8000-000000000724",
            occurred_at="2026-07-15T01:00:03Z",
            actor_id="worker.agent",
            actor_role="worker",
            payload=metadata,
        )


class _ResultFailureAdapter(_CompleteAdapter):
    async def dispatch(self, spec):
        result = HostResult(
            attempt_id=spec.attempt_id,
            host_agent_id="host.failure",
            proposal_path=spec.attempt_root / "result" / "proposal.json",
            codex_version="1.2.3",
            codex_binary_sha256="a" * 64,
        )
        raise NativeProcessFailure("failed with structured result", result=result)


def test_exception_host_result_is_retained_before_outcome_normalization(tmp_path):
    root, service, prepared = _prepared_context_run(tmp_path, _ResultFailureAdapter())
    report = asyncio.run(service.dispatch(_request(root, 721), prepared))
    assert report.outcomes[0].result is not None
    tools = service.runtime.read_execution_provenance().tool_actions
    assert tools[0].finished.payload.outcome == "failed"
    assert tools[0].finished.payload.host_agent_id == "host.failure"
    assert tools[0].finished.payload.observed_runtime_version == "1.2.3"


class _RetryCompleteAdapter(_CompleteAdapter):
    def __init__(self):
        self.calls = 0

    async def dispatch(self, spec):
        self.calls += 1
        if self.calls == 1:
            raise ProcessFailure("first attempt failed")
        return await super().dispatch(spec)


class _ObservedCompleteAdapter(_CompleteAdapter):
    async def dispatch(self, spec):
        result = await super().dispatch(spec)
        return replace(result, codex_version="1.2.3", codex_binary_sha256="a" * 64)


def test_complete_parent_observed_coverage_after_owner_metadata(tmp_path):
    root, service, prepared = _prepared_context_run(
        tmp_path,
        _ObservedCompleteAdapter(),
        runtime_identity={
            "name": "Codex",
            "version": "1.2.3",
            "build_sha256": "a" * 64,
        },
    )
    asyncio.run(service.dispatch(_request(root, 721), prepared))
    accepted = service.runtime.accept_dataset_metadata(
        _request(root, 725),
        {
            "name": "Observed study",
            "description": "Complete parent call",
            "date_published": "2026-07-15",
            "license": "https://example.org/license",
            "supersedes_event_id": None,
            "supersedes_event_sha256": None,
            "rationale": None,
        },
    )
    assert accepted.accepted
    facts = service.runtime.read_execution_provenance()
    assert facts.coverage_gaps == ()
    assert len(facts.control_actions) == 1
    assert {item.payload.direction for item in facts.bindings} == {"input", "output"}


def test_retry_has_two_tool_actions_and_only_second_produces_output(tmp_path):
    adapter = _RetryCompleteAdapter()
    root, service, prepared = _prepared_context_run(tmp_path, adapter)
    report = asyncio.run(service.dispatch(_request(root, 721), prepared))
    assert adapter.calls == 2
    assert len(report.outcomes[0].attempts) == 2
    facts = service.runtime.read_execution_provenance()
    assert len(facts.workflow_actions) == 1
    assert len(facts.tool_actions) == 2
    assert [a.finished.payload.outcome for a in facts.tool_actions] == [
        "failed",
        "succeeded",
    ]
    output = next(b for b in facts.bindings if b.payload.direction == "output")
    assert output.payload.attempt_id == facts.tool_actions[1].started.payload.attempt_id


class _WaitingFailureAdapter:
    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def dispatch(self, spec):
        self.entered.set()
        await self.release.wait()
        raise ProcessFailure("artifact accepted before host failure")

    async def request_cancel(self, spec):
        return None

    async def force_terminate(self, spec):
        return None


def test_separately_accepted_artifact_binds_exact_action_and_manifest(tmp_path):
    adapter = _WaitingFailureAdapter()
    root, service, prepared = _prepared_context_run(tmp_path, adapter)

    async def run_with_parent_acceptance():
        task = asyncio.create_task(service.dispatch(_request(root, 721), prepared))
        await adapter.entered.wait()
        facts = service.runtime.read_execution_provenance()
        tool = facts.tool_actions[0].started.payload
        state = service.runtime.read_state()
        active = next(
            a for a in state.active_attempts if a.attempt_id == tool.attempt_id
        )
        relative = f"attempts/{tool.attempt_id}/result/manual.json"
        content = root / relative
        content.parent.mkdir(parents=True, exist_ok=True)
        content.write_bytes(b"{}")
        digest = hashlib.sha256(b"{}").hexdigest()
        accepted = service.runtime.accept_artifact(
            ArtifactAcceptanceRequest.model_validate(
                {
                    **_request(root, 781).model_dump(mode="json"),
                    "artifact_id": "artifact.manual",
                    "artifact_kind": "report",
                    "media_type": "application/json",
                    "content_path": relative,
                    "content_sha256": digest,
                    "attempt_id": tool.attempt_id,
                    "base_revision": active.base_revision,
                    "consumed_sha256": active.consumed_sha256,
                }
            )
        )
        assert accepted.accepted
        bound = service.runtime.bind_execution_artifact(
            _request(root, 782),
            ExecutionArtifactBoundPayload(
                entity_id="artifact.manual",
                direction="output",
                action_id=tool.action_id,
                assignment_id=tool.assignment_id,
                attempt_id=tool.attempt_id,
                source_kind="artifact",
                source_event_id=accepted.event.event_id,
                source_event_sha256=accepted.event.event_sha256,
                source_manifest_sha256=accepted.event.payload.manifest_sha256,
                relative_path=relative,
                content_sha256=digest,
                byte_count=2,
            ),
        )
        assert bound.accepted
        adapter.release.set()
        await task

    asyncio.run(run_with_parent_acceptance())
    facts = service.runtime.read_execution_provenance()
    artifact = next(b for b in facts.bindings if b.payload.source_kind == "artifact")
    assert artifact.payload.entity_id == "artifact.manual"
    assert artifact.payload.action_id == facts.tool_actions[0].started.payload.action_id


class _CountingAdapter(_CompleteAdapter):
    def __init__(self):
        self.calls = 0

    async def dispatch(self, spec):
        self.calls += 1
        return await super().dispatch(spec)


def test_failed_tool_start_leaves_intent_only_and_never_calls_adapter(
    tmp_path, monkeypatch
):
    adapter = _CountingAdapter()
    root, service, prepared = _prepared_context_run(tmp_path, adapter)
    original = service.runtime.start_execution_action

    def reject_tool(request, action):
        if action.kind == "tool":
            return service.runtime._rejection(
                service.runtime.read_state(), "blocked", "test failure"
            )
        return original(request, action)

    monkeypatch.setattr(service.runtime, "start_execution_action", reject_tool)
    report = asyncio.run(service.dispatch(_request(root, 721), prepared))
    assert adapter.calls == 0
    assert report.outcomes[0].status == "failed"
    facts = service.runtime.read_execution_provenance()
    assert facts.intent_only_attempt_ids
    assert not facts.tool_actions


class _UnresolvedAdapter:
    async def dispatch(self, spec):
        await asyncio.Event().wait()

    async def request_cancel(self, spec):
        return None

    async def force_terminate(self, spec):
        return None


def test_unresolved_adapter_never_receives_fabricated_finish(tmp_path):
    root, prepare_request = _run(tmp_path)
    policy = ExecutionPolicySnapshot(
        max_concurrency=1,
        attempt_timeout_s=0.01,
        cancel_grace_s=0.01,
        max_attempts_per_assignment=1,
    )
    service = OrchestrationService(root, adapter=_UnresolvedAdapter(), policy=policy)
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.architect-001",
                stage_id="preparing",
                task_id="task.execute-001",
                role_id="research_architect",
                worker_identity_id="worker.architect-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    context = {
        "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
        "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
        "workflow_source": {
            "entity_id": "workflow.source",
            "relative_path": "workflow.json",
            "content_base64": "e30=",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
            "programming_language": _language_identity(),
        },
        "steps": [
            {"step_id": "step.dispatch", "tool_id": "tool.adapter", "position": 1}
        ],
        "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
        "runtime": {"name": None, "version": None, "build_sha256": None},
    }
    assert service.runtime.accept_execution_context(
        _request(root, 720), context
    ).accepted
    asyncio.run(service.dispatch(_request(root, 721), prepared))
    fact = service.runtime.read_execution_provenance().tool_actions[0]
    assert fact.finished is None
    assert fact.status == "adapter_entered_unresolved"


def test_cli_accepts_context_and_reports_projection(tmp_path, capsys):
    from arw.cli import main

    root, _ = _run(tmp_path)
    payload = tmp_path / "metadata.json"
    payload.write_bytes(
        canonical_json_bytes(
            {
                "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
                "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
                "workflow_source": {
                    "entity_id": "workflow.source",
                    "relative_path": "workflow.json",
                    "content_base64": "e30=",
                    "sha256": hashlib.sha256(b"{}").hexdigest(),
                    "programming_language": _language_identity(),
                },
                "steps": [
                    {
                        "step_id": "step.dispatch",
                        "tool_id": "tool.adapter",
                        "position": 1,
                    }
                ],
                "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
                "runtime": {"name": None, "version": None, "build_sha256": None},
            }
        )
    )
    request = tmp_path / "request.json"
    request.write_bytes(
        canonical_json_bytes(_request(root, 739).model_dump(mode="json"))
    )
    valid_context = payload.read_bytes()
    invalid_context = json.loads(valid_context)
    invalid_context["workflow_source"]["programming_language"] = "JSON"
    payload.write_bytes(canonical_json_bytes(invalid_context))
    before = replay_run(root).last_event_sha256
    assert (
        main(
            [
                "execution-context",
                "--run-root",
                str(root),
                "--request",
                str(request),
                "--payload",
                str(payload),
            ]
        )
        == 65
    )
    assert "programming_language" in capsys.readouterr().err
    assert replay_run(root).last_event_sha256 == before
    payload.write_bytes(valid_context)
    assert (
        main(
            [
                "execution-context",
                "--run-root",
                str(root),
                "--request",
                str(request),
                "--payload",
                str(payload),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["event"]["schema_version"] == "1.4.0"
    payload.write_bytes(
        canonical_json_bytes(
            {
                "name": "Run",
                "description": "Description",
                "date_published": "2026-07-15",
                "license": "https://example.org/license",
                "supersedes_event_id": None,
                "supersedes_event_sha256": None,
                "rationale": None,
            }
        )
    )
    request.write_bytes(
        canonical_json_bytes(_request(root, 740).model_dump(mode="json"))
    )
    assert (
        main(
            [
                "execution-metadata",
                "--run-root",
                str(root),
                "--request",
                str(request),
                "--payload",
                str(payload),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["accepted"] is True
    assert main(["execution-provenance", "--run-root", str(root)]) == 0
    assert (
        json.loads(capsys.readouterr().out)["dataset_metadata"]["payload"]["name"]
        == "Run"
    )


def test_execution_schema_branches_reject_drift():
    from pathlib import Path

    from arw.kernel.policy.schema_registry import (
        SchemaRegistryError,
        validate_schema_document,
    )

    root = Path(__file__).resolve().parents[2] / "schemas/v1"
    from arw.kernel.state.event_versions import MIGRATIONS

    migration = json.loads(
        (root.parent / "migrations/0004-execution-provenance-events.json").read_text()
    )
    assert migration["event_schema_version"] == MIGRATIONS[0][1]
    assert tuple(migration["event_types"]) == MIGRATIONS[0][2]
    execution = json.loads((root / "execution-provenance.schema.json").read_text())
    validate_schema_document("execution-provenance.schema.json", execution)
    drift = copy.deepcopy(execution)
    drift["$defs"]["ExecutionActionStartedPayload"]["properties"]["kind"] = {
        "type": "string"
    }
    with pytest.raises(SchemaRegistryError, match="drift"):
        validate_schema_document("execution-provenance.schema.json", drift)
    event = json.loads((root / "event.schema.json").read_text())
    broken = copy.deepcopy(event)
    broken["allOf"][0]["then"]["properties"]["actor_role"] = {"const": "worker"}
    with pytest.raises(SchemaRegistryError, match="branch drifted"):
        validate_schema_document("event.schema.json", broken)


def test_rehashed_cross_run_source_is_rejected_without_projection_authority(tmp_path):
    root, service, prepared = _prepared_context_run(tmp_path, _CompleteAdapter())
    asyncio.run(service.dispatch(_request(root, 721), prepared))
    accepted = replay_run(root)
    output = next(
        e
        for e in accepted.events
        if e.event_type == "execution_provenance.artifact_bound"
        and e.payload.direction == "output"
    )

    other_root = tmp_path / "other"
    source = other_root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("phase four input\n")
    manifest = RunManifest.model_validate_json(
        (root / "run-manifest.json").read_bytes()
    )
    other_id = "run-00000000-0000-4000-8000-000000000998"
    manifest_data = manifest.model_dump(mode="json")
    manifest_data.pop("created_at")
    init = InitRunRequest.model_validate(
        {
            **manifest_data,
            "run_id": other_id,
            "occurred_at": "2026-07-15T01:00:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000000000998",
            "command_id": "cmd-00000000-0000-4000-8000-000000000998",
            "actor_id": "parent.runtime",
        }
    )
    initialize_run(other_root, init)
    foreign = replay_run(other_root).events[0]
    forged_payload = output.payload.model_copy(
        update={
            "entity_id": "artifact.foreign",
            "source_event_id": foreign.event_id,
            "source_event_sha256": foreign.event_sha256,
        }
    )
    forged = build_runtime_event(
        accepted,
        event_type="execution_provenance.artifact_bound",
        event_id="evt-00000000-0000-4000-8000-000000000999",
        command_id="cmd-00000000-0000-4000-8000-000000000999",
        occurred_at="2026-07-15T01:00:03Z",
        actor_id="parent.runtime",
        actor_role="parent_control_plane",
        payload=forged_payload,
    )
    with pytest.raises(ReducerError, match="source event"):
        reduce_events(accepted.workflow_definition_id, (*accepted.events, forged))

    facts = service.runtime.read_execution_provenance()
    altered = replace(facts, bindings=())
    assert altered.bindings == ()
    assert service.runtime.read_execution_provenance().bindings == facts.bindings
    assert replay_run(root).last_event_sha256 == accepted.last_event_sha256


def test_crash_prefix_time_order_and_private_source(tmp_path):
    root, service, _ = _prepared_context_run(tmp_path, _CountingAdapter())
    facts = service.runtime.read_execution_provenance()
    assert facts.context is not None
    private = facts.context.payload.model_dump(mode="json")
    private["workflow_source"]["relative_path"] = "../../private/source.txt"
    with pytest.raises(ValueError, match="normalized"):
        ExecutionContextAcceptedPayload.model_validate(private)

    start_request = _request(root, 770)
    start = service.runtime.start_execution_action(
        start_request,
        ExecutionActionStartedPayload(
            action_id="workflow.crash",
            kind="workflow",
            workflow_action_id=None,
            assignment_id=None,
            attempt_id=None,
            step_id=None,
            tool_id=None,
            started_at="2026-07-15T02:00:00Z",
        ),
    )
    assert start.accepted
    assert (
        service.runtime.start_execution_action(
            start_request, start.event.payload
        ).rejection.code
        == "duplicate-event-id"
    )
    prefix = service.runtime.read_execution_provenance()
    assert prefix.workflow_actions[-1].finished is None
    invalid_end = service.runtime.finish_execution_action(
        _request(root, 771),
        ExecutionActionFinishedPayload(
            action_id="workflow.crash",
            ended_at="2026-07-15T01:00:00Z",
            outcome="succeeded",
        ),
    )
    assert not invalid_end.accepted
    assert (
        service.runtime.read_execution_provenance().workflow_actions[-1].finished
        is None
    )


def test_context_cannot_split_prepare_revision_prefix(tmp_path):
    root, prepare_request = _run(tmp_path)
    runtime = RuntimeCommandService(root)
    assert runtime.execute_transition(prepare_request).accepted
    context = {
        "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
        "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
        "workflow_source": {
            "entity_id": "workflow.source",
            "relative_path": "workflow.json",
            "content_base64": "e30=",
            "sha256": hashlib.sha256(b"{}").hexdigest(),
            "programming_language": _language_identity(),
        },
        "steps": [
            {"step_id": "step.dispatch", "tool_id": "tool.adapter", "position": 1}
        ],
        "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
        "runtime": {"name": None, "version": None, "build_sha256": None},
    }
    before = replay_run(root).last_event_sha256
    rejected = runtime.accept_execution_context(_request(root, 772), context)
    assert not rejected.accepted and rejected.rejection.code == "invalid-command"
    assert replay_run(root).last_event_sha256 == before
