"""Real-run acceptance tests for the opt-in, read-only crate boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import stat
import struct
import tomllib
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import portalocker
import pytest

from arw.kernel.artifacts.ro_crate import CrateError, export_ro_crate, verify_ro_crate
from arw.kernel.execution.orchestration import AssignmentSpec, OrchestrationService
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW, PHASE4_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    ExecutionArtifactBoundPayload,
    InitRunRequest,
)
from tests.integration.test_execution_provenance import (
    _CompleteAdapter,
    _language_identity,
    _prepared_context_run,
    _request,
    _WaitingFailureAdapter,
)
from tests.integration.test_orchestration_lifecycle import _run as _phase4_run

RUN_ID = "run-00000000-0000-4000-8000-000000000037"
WHEN = "2026-07-16T00:00:00Z"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _dataset_metadata() -> dict[str, str | None]:
    return {
        "name": "Observed research dataset",
        "description": "A parent-observed research run",
        "date_published": "2026-07-20",
        "license": "https://example.org/research-license",
        "supersedes_event_id": None,
        "supersedes_event_sha256": None,
        "rationale": None,
    }


def _complete_run(
    tmp_path: Path,
    *,
    workflow_path: str = "workflow.json",
    language_identity: bool = True,
) -> Path:
    class ObservedAdapter(_CompleteAdapter):
        async def dispatch(self, spec):
            result = await super().dispatch(spec)
            return replace(result, codex_version="1.2.3", codex_binary_sha256="a" * 64)

    run, prepare_request = _phase4_run(tmp_path)
    service = OrchestrationService(run, adapter=ObservedAdapter())
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
            "relative_path": workflow_path,
            "content_base64": base64.b64encode(b"{}").decode("ascii"),
            "sha256": _sha(b"{}"),
            "programming_language": _language_identity() if language_identity else None,
        },
        "steps": [
            {"step_id": "step.dispatch", "tool_id": "tool.adapter", "position": 1}
        ],
        "tools": [{"tool_id": "tool.adapter", "name": "Adapter dispatch"}],
        "runtime": {"name": "Codex", "version": "1.2.3", "build_sha256": "a" * 64},
    }
    assert service.runtime.accept_execution_context(
        _request(run, 759), context
    ).accepted
    assert service.runtime.accept_dataset_metadata(
        _request(run, 760), _dataset_metadata()
    ).accepted
    report = asyncio.run(service.dispatch(_request(run, 761), prepared))
    assert report.outcomes[0].status == "completed"
    return run


def _run(
    tmp_path: Path,
    *,
    public_body: bytes = b"Shareable research summary\n",
    public_media_type: str = "text/plain",
) -> Path:
    root = tmp_path / "run"
    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"private input is never packaged\n")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": WHEN,
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": _sha(source.read_bytes()),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal", "forced-stop-replay"],
                "event_id": "evt-00000000-0000-4000-8000-000000000037",
                "command_id": "cmd-00000000-0000-4000-8000-000000000037",
                "actor_id": "parent.runtime",
            }
        ),
    )
    for number, kind, body in (
        (38, "public-summary", public_body),
        (39, "project-private-notes", b"private project body\n"),
    ):
        path = root / f"outputs/{number}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        revision = number - 37
        outcome = RuntimeCommandService(root).accept_artifact(
            ArtifactAcceptanceRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": f"evt-00000000-0000-4000-8000-0000000000{number}",
                    "command_id": f"cmd-00000000-0000-4000-8000-0000000000{number}",
                    "expected_revision": revision,
                    "occurred_at": WHEN,
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                    "artifact_id": f"artifact.{number}",
                    "artifact_kind": kind,
                    "media_type": public_media_type if number == 38 else "text/plain",
                    "content_path": f"outputs/{number}.txt",
                    "content_sha256": _sha(body),
                    "base_revision": revision,
                    "consumed_sha256": [],
                }
            )
        )
        assert outcome.accepted, outcome.rejection
    return root


def _inventory(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_export_is_read_only_deterministic_and_private_by_default(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    before = _inventory(run)
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    export_ro_crate(
        run, first, format="zip", include_artifact_ids=("artifact.38", "artifact.39")
    )
    export_ro_crate(
        run, second, format="zip", include_artifact_ids=("artifact.38", "artifact.39")
    )
    assert first.read_bytes() == second.read_bytes()
    assert int(first.stat().st_mtime) == 315532800
    assert _inventory(run) == before
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()
        )
        assert all(
            info.external_attr >> 16 == stat.S_IFREG | 0o644
            for info in archive.infolist()
        )
        assert "ro-crate-metadata.json" in names
        assert "arw-source-binding.json" in names
        assert len([name for name in names if name.startswith("artifacts/")]) == 1
        assert b"private project body" not in first.read_bytes()
        binding = json.loads(archive.read("arw-source-binding.json"))
        assert binding["event_count"] == 3
        assert len(binding["omissions"]) == 1
        assert binding["target_profile"] == "https://w3id.org/ro/wfrun/provenance/0.6"
        assert binding["profile_status"] == "incomplete"
        metadata = json.loads(archive.read("ro-crate-metadata.json"))
        assert metadata["@graph"][0]["conformsTo"] == {
            "@id": "https://w3id.org/ro/crate/1.3"
        }
        root_entity = next(item for item in metadata["@graph"] if item["@id"] == "./")
        assert "conformsTo" not in root_entity
        assert "name" not in root_entity
        assert "description" not in root_entity
        assert "datePublished" not in root_entity
        assert "license" not in root_entity
        assert binding["dataset_metadata"] is None
    verdict = verify_ro_crate(first, run_root=run)
    assert verdict["structure"]["status"] == "incomplete"
    assert verdict["base_profile"]["status"] == "incomplete"
    assert set(verdict["base_profile"]["missing"]) == {
        "name",
        "description",
        "datePublished",
        "license",
    }
    assert verdict["metadata_completeness"]["status"] == "incomplete"
    assert verdict["byte_integrity"]["status"] == "pass"
    assert verdict["source_run_binding"]["status"] == "pass"
    assert verdict["profile"]["status"] == "incomplete"
    assert "workflow_action" in verdict["profile"]["missing"]


def test_observed_run_passes_profile_must_with_private_action_data(
    tmp_path: Path,
) -> None:
    run = _complete_run(tmp_path)
    before = _inventory(run)
    first, second = tmp_path / "observed-a.zip", tmp_path / "observed-b.zip"
    result = export_ro_crate(run, first)
    export_ro_crate(run, second)
    assert first.read_bytes() == second.read_bytes()
    assert _inventory(run) == before
    assert result["profile"]["status"] == "pass"
    assert "workflow_language_identity" not in result["profile"]["missing"]
    assert "digest_only_action_data" in result["arw_completeness"]["missing"]
    assert "action_result_body_omitted" in result["should_warnings"]
    with zipfile.ZipFile(first) as archive:
        graph = json.loads(archive.read("ro-crate-metadata.json"))["@graph"]
    nodes = {node["@id"]: node for node in graph}
    root = nodes["./"]
    workflow_id = root["mainEntity"]["@id"]
    workflow = nodes[workflow_id]
    assert root["datePublished"] == "2026-07-20"
    assert root["license"] == "https://example.org/research-license"
    assert root["conformsTo"] == [
        {"@id": uri}
        for uri in (
            "https://w3id.org/ro/wfrun/process/0.6",
            "https://w3id.org/ro/wfrun/workflow/0.6",
            "https://w3id.org/workflowhub/workflow-ro-crate/1.1",
            "https://w3id.org/ro/wfrun/provenance/0.6",
        )
    ]
    assert all(
        nodes[item["@id"]]["@type"] == "CreativeWork" for item in root["conformsTo"]
    )
    assert {"File", "SoftwareSourceCode", "ComputationalWorkflow", "HowTo"} <= set(
        workflow["@type"]
    )
    language_id = _language_identity()["uri"]
    assert workflow["programmingLanguage"] == {"@id": language_id}
    assert nodes[language_id] == {
        "@id": language_id,
        "@type": "ComputerLanguage",
        "name": _language_identity()["name"],
        "url": {"@id": _language_identity()["url"]},
        "version": _language_identity()["version"],
    }
    workflow_action = nodes[root["mentions"][0]["@id"]]
    assert workflow_action["instrument"] == {"@id": workflow_id}
    tool_action = next(
        node
        for node in graph
        if node.get("@type") == "CreateAction" and node is not workflow_action
    )
    tool_id = tool_action["instrument"]["@id"]
    assert {"@id": tool_id} in workflow["hasPart"]
    step_id = workflow["step"][0]["@id"]
    assert nodes[step_id]["workExample"] == {"@id": tool_id}
    control = next(node for node in graph if node.get("@type") == "ControlAction")
    assert control["instrument"] == {"@id": step_id}
    assert control["object"] == {"@id": tool_action["@id"]}
    assert workflow_action["startTime"] and workflow_action["endTime"]
    assert tool_action["startTime"] and tool_action["endTime"]
    assert "result" not in tool_action
    assert "object" not in tool_action
    assert not any(node["@id"].startswith("#data/") for node in graph)
    verdict = verify_ro_crate(first, run_root=run)
    assert {
        key: verdict[key]["status"]
        for key in (
            "structure",
            "base_profile",
            "metadata_completeness",
            "byte_integrity",
            "source_run_binding",
        )
    } == dict.fromkeys(
        (
            "structure",
            "base_profile",
            "metadata_completeness",
            "byte_integrity",
            "source_run_binding",
        ),
        "pass",
    )
    assert verdict["profile"]["status"] == "pass"
    assert "workflow_language_identity" not in verdict["profile"]["missing"]
    assert verdict["arw_completeness"]["status"] == "incomplete"
    assert "digest_only_action_data" in verdict["arw_completeness"]["missing"]
    assert "action_result_body_omitted" in verdict["should_warnings"]


@pytest.mark.parametrize(
    "relation",
    [
        "mainEntity",
        "mentions",
        "workflow_type",
        "programmingLanguage",
        "language_version",
        "workflow_name",
        "profile_declaration",
        "profile_entity",
        "root_license",
        "root_date",
        "hasPart",
        "step",
        "workExample",
        "workflow_instrument",
        "tool_instrument",
        "control_instrument",
        "control_object",
        "result",
        "actionStatus",
    ],
)
def test_profile_requires_each_canonical_graph_relation(
    tmp_path: Path, relation: str
) -> None:
    run = _complete_run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    baseline = set(verify_ro_crate(crate)["profile"]["missing"])
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    nodes = {node["@id"]: node for node in metadata["@graph"]}
    root = nodes["./"]
    workflow = nodes[root["mainEntity"]["@id"]]
    actions = [node for node in nodes.values() if node.get("@type") == "CreateAction"]
    workflow_action = nodes[root["mentions"][0]["@id"]]
    tool_action = next(node for node in actions if node is not workflow_action)
    control = next(
        node for node in nodes.values() if node.get("@type") == "ControlAction"
    )
    if relation == "mainEntity":
        root.pop("mainEntity")
    elif relation == "mentions":
        root.pop("mentions")
    elif relation == "workflow_type":
        workflow["@type"].remove("ComputationalWorkflow")
    elif relation == "programmingLanguage":
        workflow.pop("programmingLanguage")
    elif relation == "language_version":
        nodes[workflow["programmingLanguage"]["@id"]].pop("version")
    elif relation == "workflow_name":
        workflow.pop("name")
    elif relation == "profile_declaration":
        root.pop("conformsTo")
    elif relation == "profile_entity":
        nodes[root["conformsTo"][-1]["@id"]]["@type"] = "Thing"
    elif relation == "root_license":
        root.pop("license")
    elif relation == "root_date":
        root.pop("datePublished")
    elif relation == "hasPart":
        workflow.pop("hasPart")
    elif relation == "step":
        workflow.pop("step")
    elif relation == "workExample":
        nodes[workflow["step"][0]["@id"]].pop("workExample")
    elif relation == "workflow_instrument":
        workflow_action.pop("instrument")
    elif relation == "tool_instrument":
        tool_action.pop("instrument")
    elif relation == "control_instrument":
        control.pop("instrument")
    elif relation == "control_object":
        control.pop("object")
    elif relation == "result":
        tool_action["result"] = [{"@id": "#unpackaged-file"}]
    else:
        tool_action.pop("actionStatus")
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["profile"]["status"] == "incomplete"
    assert set(verdict["profile"]["missing"]) - baseline
    assert verdict["byte_integrity"]["status"] == "fail"
    assert verdict["source_run_binding"]["status"] == (
        "fail" if relation in {"root_license", "root_date"} else "pass"
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("name", "Another research dataset"),
        ("description", "Changed after publication"),
        ("datePublished", "2026-07-21"),
        ("license", "https://example.org/other-license"),
    ],
)
def test_valid_root_metadata_mismatch_passes_base_and_profile_but_fails_arw(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    run = _complete_run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    root = next(node for node in metadata["@graph"] if node["@id"] == "./")
    root[field] = replacement
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["base_profile"]["status"] == "pass"
    assert verdict["base_profile"]["missing"] == []
    assert verdict["profile"]["status"] == "pass"
    assert verdict["metadata_completeness"]["status"] == "fail"
    assert verdict["arw_completeness"]["status"] == "fail"
    assert verdict["structure"]["status"] == "fail"
    assert verdict["byte_integrity"]["status"] == "fail"
    assert verdict["source_run_binding"]["status"] == "fail"


def test_valid_root_properties_without_owner_pass_base_but_not_arw_binding(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    root = next(node for node in metadata["@graph"] if node["@id"] == "./")
    owner_values = _dataset_metadata()
    root.update(
        name=owner_values["name"],
        description=owner_values["description"],
        datePublished=owner_values["date_published"],
        license=owner_values["license"],
    )
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["base_profile"]["status"] == "pass"
    assert verdict["metadata_completeness"]["status"] == "incomplete"
    assert verdict["arw_completeness"]["status"] == "incomplete"
    assert verdict["source_run_binding"]["status"] == "fail"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("name", ""),
        ("description", "   "),
        ("datePublished", "not-a-date"),
        ("license", None),
    ],
)
def test_invalid_serialized_root_property_fails_base(
    tmp_path: Path, field: str, invalid: str | None
) -> None:
    run = _complete_run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    root = next(node for node in metadata["@graph"] if node["@id"] == "./")
    root[field] = invalid
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["base_profile"]["status"] == "fail"
    assert field in verdict["base_profile"]["missing"]
    assert verdict["profile"]["status"] == "incomplete"


def test_workflow_source_substitution_fails_live_binding(tmp_path: Path) -> None:
    run = _complete_run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    binding = json.loads((crate / "arw-source-binding.json").read_bytes())
    workflow_path = binding["workflow_file"]
    (crate / workflow_path).write_bytes(b"[]")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    workflow = next(node for node in metadata["@graph"] if node["@id"] == workflow_path)
    workflow["sha256"] = _sha(b"[]")
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["source_run_binding"]["status"] == "fail"


def test_binding_profile_status_cannot_grant_conformance(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    binding_path = crate / "arw-source-binding.json"
    binding = json.loads(binding_path.read_bytes())
    binding["profile_status"] = "pass"
    binding["profile_missing"] = []
    binding_path.write_bytes(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate)
    assert verdict["profile"]["status"] == "incomplete"


def test_missing_language_identity_emits_no_programming_language_link(
    tmp_path: Path,
) -> None:
    run = _complete_run(tmp_path, language_identity=False)
    crate = tmp_path / "missing-language.zip"
    export_ro_crate(run, crate)
    with zipfile.ZipFile(crate) as archive:
        graph = json.loads(archive.read("ro-crate-metadata.json"))["@graph"]
    nodes = {node["@id"]: node for node in graph}
    workflow = nodes[nodes["./"]["mainEntity"]["@id"]]
    assert "programmingLanguage" not in workflow
    assert not any(node.get("@type") == "ComputerLanguage" for node in graph)
    verdict = verify_ro_crate(crate, run_root=run)
    assert "workflow_language_identity" in verdict["profile"]["missing"]
    assert verdict["source_run_binding"]["status"] == "pass"


def test_copied_accepted_output_links_exact_file_entry(tmp_path: Path) -> None:
    adapter = _WaitingFailureAdapter()
    run, service, prepared = _prepared_context_run(tmp_path, adapter)

    async def accept_during_dispatch() -> str:
        task = asyncio.create_task(service.dispatch(_request(run, 721), prepared))
        await adapter.entered.wait()
        tool = (
            service.runtime.read_execution_provenance().tool_actions[0].started.payload
        )
        active = next(
            item
            for item in service.runtime.read_state().active_attempts
            if item.attempt_id == tool.attempt_id
        )
        relative = f"attempts/{tool.attempt_id}/result/manual.json"
        content = run / relative
        content.parent.mkdir(parents=True, exist_ok=True)
        content.write_bytes(b"{}")
        accepted = service.runtime.accept_artifact(
            ArtifactAcceptanceRequest.model_validate(
                {
                    **_request(run, 781).model_dump(mode="json"),
                    "artifact_id": "artifact.manual",
                    "artifact_kind": "report",
                    "media_type": "application/json",
                    "content_path": relative,
                    "content_sha256": _sha(b"{}"),
                    "attempt_id": tool.attempt_id,
                    "base_revision": active.base_revision,
                    "consumed_sha256": active.consumed_sha256,
                }
            )
        )
        assert accepted.accepted
        assert service.runtime.bind_execution_artifact(
            _request(run, 782),
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
                content_sha256=_sha(b"{}"),
                byte_count=2,
            ),
        ).accepted
        adapter.release.set()
        await task
        return relative

    relative = asyncio.run(accept_during_dispatch())
    crate = tmp_path / "copied.zip"
    export_ro_crate(run, crate, include_artifact_ids=("artifact.manual",))
    with zipfile.ZipFile(crate) as archive:
        metadata = json.loads(archive.read("ro-crate-metadata.json"))
        binding = json.loads(archive.read("arw-source-binding.json"))
    item = binding["included"][0]
    assert item["source_relative_path"] == relative
    assert item["sha256"] == _sha(b"{}")
    assert item["contentSize"] == 2
    nodes = {node["@id"]: node for node in metadata["@graph"]}
    tool_action = next(
        node
        for node in nodes.values()
        if node.get("@type") == "CreateAction"
        and node.get("instrument", {}).get("@id", "").startswith("#tool/")
    )
    assert tool_action["result"] == [{"@id": item["path"]}]
    assert nodes[item["path"]]["sha256"] == _sha(b"{}")
    assert nodes[item["path"]]["contentSize"] == 2
    from arw.kernel.artifacts.ro_crate import _packaged_data_ref

    accepted_binding = next(
        event
        for event in binding["execution_facts"]["bindings"]
        if event["payload"]["source_kind"] == "artifact"
    )
    for field, altered in (
        ("source_event_id", "evt-00000000-0000-4000-8000-000000000999"),
        ("source_event_sha256", "0" * 64),
        ("source_relative_path", "different.json"),
        ("source_manifest_sha256", "0" * 64),
        ("source_content_sha256", "0" * 64),
        ("contentSize", 999),
        ("sha256", "0" * 64),
    ):
        assert _packaged_data_ref(accepted_binding, [{**item, field: altered}]) is None
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["byte_integrity"]["status"] == "pass"
    assert verdict["source_run_binding"]["status"] == "pass"


def test_private_workflow_source_path_stays_out_of_crate(tmp_path: Path) -> None:
    run = _complete_run(tmp_path, workflow_path="private/workflow.json")
    crate = tmp_path / "private.zip"
    export_ro_crate(run, crate)
    with zipfile.ZipFile(crate) as archive:
        assert all(not name.startswith("workflow/") for name in archive.namelist())
        binding_bytes = archive.read("arw-source-binding.json")
        assert b"private/workflow.json" not in binding_bytes
        binding = json.loads(binding_bytes)
        assert binding["workflow_file"] is None
        assert (
            binding["execution_facts"]["context"]["payload"]["workflow_source"][
                "relative_path"
            ]
            is None
        )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["byte_integrity"]["status"] == "pass"
    assert verdict["source_run_binding"]["status"] == "pass"
    assert "workflow_source_path_private" in verdict["profile"]["missing"]


def test_owner_metadata_secret_shape_fails_before_publication(tmp_path: Path) -> None:
    run = _run(tmp_path)
    owner = {**_dataset_metadata(), "description": "password=knownsecretvalue"}
    assert (
        RuntimeCommandService(run)
        .accept_dataset_metadata(_request(run, 750), owner)
        .accepted
    )
    output = tmp_path / "should-not-exist.zip"
    with pytest.raises(CrateError, match="owner metadata contains secret-shaped"):
        export_ro_crate(run, output)
    assert not output.exists()


def test_directory_export_and_tampered_payload(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(
        run, crate, format="directory", include_artifact_ids=("artifact.38",)
    )
    assert verify_ro_crate(crate, run_root=run)["byte_integrity"]["status"] == "pass"
    artifact = next((crate / "artifacts").iterdir())
    assert int(crate.stat().st_mtime) == 315532800
    assert int(artifact.stat().st_mtime) == 315532800
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o644
    artifact.write_bytes(b"tampered\n")
    assert verify_ro_crate(crate, run_root=run)["byte_integrity"]["status"] == "fail"


def test_metadata_only_tamper_is_detected(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    root = next(item for item in metadata["@graph"] if item["@id"] == "./")
    root["name"] = "Changed after export"
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["structure"]["status"] == "fail"
    assert verdict["byte_integrity"]["status"] == "fail"
    assert "ro-crate-metadata.json" in verdict["byte_integrity"]["issues"]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("name", "Another dataset"),
        ("description", "Another research run"),
        ("datePublished", "2026-07-21"),
        ("license", "https://example.org/other-license"),
    ],
)
@pytest.mark.parametrize("mode", ["drop", "mismatch"])
def test_event_backed_metadata_tampering_is_detected(
    tmp_path: Path, field: str, replacement: str, mode: str
) -> None:
    run = _run(tmp_path)
    outcome = RuntimeCommandService(run).accept_dataset_metadata(
        _request(run, 740), _dataset_metadata()
    )
    assert outcome.accepted
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    root = next(item for item in metadata["@graph"] if item["@id"] == "./")
    if mode == "drop":
        root.pop(field)
    else:
        root[field] = replacement
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result = verify_ro_crate(crate, run_root=run)
    assert result["structure"]["status"] == "fail"
    assert result["base_profile"]["status"] == ("fail" if mode == "drop" else "pass")
    assert (field in result["base_profile"]["missing"]) == (mode == "drop")
    assert result["metadata_completeness"]["status"] == "fail"
    assert result["arw_completeness"]["status"] == "fail"
    assert field not in result["should_warnings"]
    assert result["source_run_binding"]["status"] == "fail"


@pytest.mark.parametrize(
    ("field", "owner_field", "replacement"),
    [
        ("name", "name", "Another research dataset"),
        ("description", "description", "Another observed research run"),
        ("datePublished", "date_published", "2026-07-21"),
        ("license", "license", "https://example.org/other-license"),
    ],
)
def test_coordinated_root_and_binding_tamper_fails_canonical_source(
    tmp_path: Path, field: str, owner_field: str, replacement: str
) -> None:
    run = _complete_run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    binding_path = crate / "arw-source-binding.json"
    binding = json.loads(binding_path.read_bytes())
    binding["dataset_metadata"]["payload"][owner_field] = replacement
    binding["execution_facts"]["dataset_metadata"]["payload"][owner_field] = replacement
    binding_path.write_bytes(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    for node in metadata["@graph"]:
        if node.get("@id") == "./":
            node[field] = replacement
        elif node.get("@id") == "arw-source-binding.json":
            node["sha256"] = _sha(binding_path.read_bytes())
            node["contentSize"] = len(binding_path.read_bytes())
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    verdict = verify_ro_crate(crate, run_root=run)
    assert verdict["base_profile"]["status"] == "pass"
    assert verdict["source_run_binding"]["status"] == "fail"


def test_date_published_comes_only_from_owner_event_and_invalid_values_fail(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    outcome = RuntimeCommandService(run).accept_dataset_metadata(
        _request(run, 740), _dataset_metadata()
    )
    assert outcome.accepted
    corrected = RuntimeCommandService(run).accept_dataset_metadata(
        _request(run, 741),
        {
            **_dataset_metadata(),
            "name": "Corrected dataset name",
            "supersedes_event_id": outcome.event.event_id,
            "supersedes_event_sha256": outcome.event.event_sha256,
            "rationale": "internal review note",
        },
    )
    assert corrected.accepted
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    binding_path = crate / "arw-source-binding.json"
    binding = json.loads(binding_path.read_bytes())
    assert binding["dataset_metadata"]["payload"]["date_published"] == "2026-07-20"
    assert binding["dataset_metadata"]["event_id"] == corrected.event.event_id
    assert "rationale" not in binding["dataset_metadata"]["payload"]

    binding["dataset_metadata"]["payload"]["date_published"] = "not-an-iso-date"
    binding_path.write_bytes(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    for item in metadata["@graph"]:
        if item.get("@id") == "./":
            item["datePublished"] = "not-an-iso-date"
        elif item.get("@id") == "arw-source-binding.json":
            item["sha256"] = _sha(binding_path.read_bytes())
            item["contentSize"] = len(binding_path.read_bytes())
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    assert verify_ro_crate(crate)["structure"]["status"] == "fail"


def test_bounds_and_invalid_history_leave_no_output(tmp_path: Path) -> None:
    run = _run(tmp_path)
    out = tmp_path / "failed.zip"
    with pytest.raises(CrateError, match="event limit"):
        export_ro_crate(run, out, format="zip", max_events=2)
    assert not out.exists()
    segment = run / "journal/segments/00000001.jsonl"
    segment.write_bytes(segment.read_bytes() + b"broken\n")
    with pytest.raises(CrateError):
        export_ro_crate(run, out, format="zip")
    assert not out.exists()


def test_unsafe_directory_and_zip_entries_are_rejected(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(run, crate, format="directory")
    (crate / "escape").symlink_to(run / "input/source.txt")
    assert verify_ro_crate(crate)["structure"]["status"] == "fail"
    zipped = tmp_path / "unsafe.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(zipped, "w") as archive:
            archive.writestr("../escape", b"x")
            archive.writestr("../escape", b"y")
    assert verify_ro_crate(zipped)["structure"]["status"] == "fail"
    collision = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision, "w") as archive:
        archive.writestr("A", b"a")
        archive.writestr("a", b"b")
    assert verify_ro_crate(collision)["structure"]["status"] == "fail"


@pytest.mark.parametrize("special", ["fifo", "socket", "device", "symlink"])
def test_verify_rejects_special_roots_before_opening_as_zip(
    tmp_path: Path, monkeypatch, special: str
) -> None:
    from arw.kernel.artifacts import ro_crate

    target = tmp_path / special
    if special == "fifo":
        os.mkfifo(target)
    elif special == "socket":
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(target))
    elif special == "symlink":
        referent = tmp_path / "referent.zip"
        referent.write_bytes(b"not a crate")
        target.symlink_to(referent)
    else:
        target = Path("/dev/null")
        if not stat.S_ISCHR(target.stat().st_mode):
            pytest.skip("no character device fixture is available")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("special root must be rejected before ZIP parsing")

    monkeypatch.setattr(ro_crate.zipfile, "ZipFile", forbidden)
    assert verify_ro_crate(target)["structure"]["status"] == "fail"


def test_verify_rejects_oversized_zip_before_reading_members(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    archive = tmp_path / "bounded.zip"
    export_ro_crate(run, archive)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized archive must be rejected before ZIP parsing")

    monkeypatch.setattr(ro_crate.zipfile, "ZipFile", forbidden)
    assert (
        verify_ro_crate(archive, max_bytes=archive.stat().st_size - 1)["structure"][
            "status"
        ]
        == "fail"
    )


def test_zip_entry_count_is_preflighted_before_zipfile_builds_infos(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    archive_path = tmp_path / "too-many.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(513):
            archive.writestr(f"f/{index:04}.txt", b"x")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("entry count must be rejected before ZipFile parsing")

    monkeypatch.setattr(ro_crate.zipfile, "ZipFile", forbidden)
    result = verify_ro_crate(archive_path, max_entries=512)
    assert result["structure"]["status"] == "fail"


def test_zip_is_opened_with_nofollow_and_verified_descriptor(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    archive = tmp_path / "safe.zip"
    export_ro_crate(run, archive)
    original_zipfile = ro_crate.zipfile.ZipFile
    observed = {}

    def check_descriptor(handle, *args, **kwargs):
        observed["regular"] = stat.S_ISREG(os.fstat(handle.fileno()).st_mode)
        return original_zipfile(handle, *args, **kwargs)

    monkeypatch.setattr(ro_crate.zipfile, "ZipFile", check_descriptor)
    assert verify_ro_crate(archive)["structure"]["status"] == "incomplete"
    assert observed["regular"]


def test_zip_symlink_swap_between_check_and_open_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    archive = tmp_path / "swap.zip"
    export_ro_crate(run, archive)
    target = tmp_path / "target.zip"
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == archive and not swapped:
            archive.rename(target)
            archive.symlink_to(target)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(ro_crate.os, "open", swap_then_open)
    result = verify_ro_crate(archive)
    assert swapped
    assert result["structure"]["status"] == "fail"


def test_unsupported_zip_compression_is_a_structured_rejection(tmp_path: Path) -> None:
    run = _run(tmp_path)
    archive = tmp_path / "unsupported-compression.zip"
    export_ro_crate(run, archive)
    raw = bytearray(archive.read_bytes())
    for signature, method_offset in (
        (b"PK\x03\x04", 8),
        (b"PK\x01\x02", 10),
    ):
        position = 0
        while (position := raw.find(signature, position)) >= 0:
            raw[position + method_offset : position + method_offset + 2] = struct.pack(
                "<H", 99
            )
            position += len(signature)
    archive.write_bytes(raw)
    assert verify_ro_crate(archive)["structure"]["status"] == "fail"


def test_directory_publish_never_replaces_empty_destination_created_at_commit(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    output = tmp_path / "raced-crate"
    install = getattr(ro_crate, "_install_directory_noreplace", None)
    assert callable(install), (
        "directory publication needs an atomic no-replace operation"
    )

    def create_empty_destination(stage, destination):
        destination.mkdir()
        return install(stage, destination)

    monkeypatch.setattr(
        ro_crate, "_install_directory_noreplace", create_empty_destination
    )
    with pytest.raises(CrateError):
        export_ro_crate(run, output, format="directory")
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert not list(tmp_path.glob(".arw-crate-*"))


def test_source_run_binding_detects_new_accepted_head(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate.zip"
    export_ro_crate(run, crate, format="zip")
    (run / "run-manifest.json").write_bytes(b"{}\n")
    assert (
        verify_ro_crate(crate, run_root=run)["source_run_binding"]["status"] == "fail"
    )


def test_default_disclosure_and_selected_secret_body(tmp_path: Path) -> None:
    run = _run(tmp_path)
    default = tmp_path / "default.zip"
    export_ro_crate(run, default)
    with zipfile.ZipFile(default) as archive:
        assert all(not name.startswith("artifacts/") for name in archive.namelist())
        binding = json.loads(archive.read("arw-source-binding.json"))
        assert len(binding["omissions"]) == 2
    secret_run = _run(tmp_path / "secret", public_body=b"password=knownsecretvalue\n")
    failed = tmp_path / "failed.zip"
    with pytest.raises(CrateError, match="secret-shaped"):
        export_ro_crate(secret_run, failed, include_artifact_ids=("artifact.38",))
    assert not failed.exists()


def test_recorded_private_classification_remains_digest_only(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        public_body=b'{"privacy_classification":"project_private","body":"hidden"}\n',
        public_media_type="application/json",
    )
    crate = tmp_path / "private.zip"
    export_ro_crate(run, crate, include_artifact_ids=("artifact.38",))
    with zipfile.ZipFile(crate) as archive:
        binding = json.loads(archive.read("arw-source-binding.json"))
        assert not any(name.startswith("artifacts/") for name in archive.namelist())
        assert binding["omissions"][0]["reason"] == "sensitive_or_project_private"


def test_source_binding_rejects_self_consistent_substitution(tmp_path: Path) -> None:
    run = _run(tmp_path)
    crate = tmp_path / "crate"
    export_ro_crate(
        run, crate, format="directory", include_artifact_ids=("artifact.38",)
    )
    artifact = next((crate / "artifacts").iterdir())
    artifact.write_bytes(b"replacement\n")
    binding_path = crate / "arw-source-binding.json"
    binding = json.loads(binding_path.read_bytes())
    binding["included"][0]["sha256"] = _sha(artifact.read_bytes())
    binding["included"][0]["contentSize"] = len(artifact.read_bytes())
    binding_path.write_bytes(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    for item in metadata["@graph"]:
        if item.get("@id") == "arw-source-binding.json":
            item["sha256"] = _sha(binding_path.read_bytes())
            item["contentSize"] = len(binding_path.read_bytes())
        if item.get("@id") == artifact.relative_to(crate).as_posix():
            item["sha256"] = _sha(artifact.read_bytes())
            item["contentSize"] = len(artifact.read_bytes())
    metadata_path.write_bytes(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result = verify_ro_crate(crate, run_root=run)
    assert result["byte_integrity"]["status"] == "pass"
    assert result["source_run_binding"]["status"] == "fail"


def test_cli_registers_export_and_verify_without_changing_other_routes(
    tmp_path: Path, capsys
) -> None:
    from arw.cli import main

    run = _run(tmp_path)
    crate = tmp_path / "cli.zip"
    assert (
        main(
            [
                "artifact",
                "ro-crate-export",
                "--run-root",
                str(run),
                "--output",
                str(crate),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "exported"
    assert (
        main(
            [
                "artifact",
                "ro-crate-verify",
                "--crate",
                str(crate),
                "--run-root",
                str(run),
            ]
        )
        == 65
    )
    assert json.loads(capsys.readouterr().out)["source_run_binding"]["status"] == "pass"
    assert main(["artifact", "ro-crate-verify", "--crate", str(crate)]) == 65
    assert (
        json.loads(capsys.readouterr().out)["source_run_binding"]["status"]
        == "unverified"
    )


def test_link_entry_and_read_lock_failure_do_not_publish(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as out:
        link = zipfile.ZipInfo("artifacts/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        out.writestr(link, "../input/source.txt")
    assert verify_ro_crate(archive)["structure"]["status"] == "fail"

    def unavailable(*_args, **_kwargs):
        raise ro_crate.JournalError("lock unavailable")

    monkeypatch.setattr(ro_crate, "_read_lock", unavailable)
    output = tmp_path / "no-output.zip"
    with pytest.raises(CrateError, match="lock unavailable"):
        export_ro_crate(run, output)
    assert not output.exists()


def test_real_writer_lock_contention_rejects_snapshot(tmp_path: Path) -> None:
    run = _run(tmp_path)
    output = tmp_path / "locked.zip"
    with (
        portalocker.Lock(run / ".journal.lock", mode="rb", timeout=0),
        pytest.raises(CrateError, match="lock"),
    ):
        export_ro_crate(run, output, lock_timeout=0)
    assert not output.exists()


def test_source_change_during_copy_aborts_without_output(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    original = ro_crate.read_retained_bytes
    calls = 0

    def changed(root, relative, *, max_bytes):
        nonlocal calls
        raw = original(root, relative, max_bytes=max_bytes)
        calls += 1
        if calls == 1:
            (root / relative).write_bytes(b"changed after first read\n")
        return raw

    monkeypatch.setattr(ro_crate, "read_retained_bytes", changed)
    output = tmp_path / "race.zip"
    with pytest.raises(CrateError):
        export_ro_crate(run, output, include_artifact_ids=("artifact.38",))
    assert not output.exists()


def test_damage_to_terminal_tail_between_replays_aborts_export(
    tmp_path: Path, monkeypatch
) -> None:
    from arw.kernel.artifacts import ro_crate

    run = _run(tmp_path)
    replay = ro_crate._replay_unlocked
    calls = 0

    def damage_after_snapshot(root):
        nonlocal calls
        state = replay(root)
        calls += 1
        if calls == 1:
            with (root / "journal/segments/00000001.jsonl").open("ab") as stream:
                stream.write(b"{")
            return state
        return replay(root)

    monkeypatch.setattr(ro_crate, "_replay_unlocked", damage_after_snapshot)
    output = tmp_path / "damaged-tail.zip"
    with pytest.raises(CrateError):
        export_ro_crate(run, output)
    assert calls == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "body",
    [
        b'{"password":"cleartext-secret-value"}\n',
        b'{"nested":[{"api_key":"cleartext-secret-value"}]}\n',
        b'{"pass\\u0077ord":"cleartext-secret-value"}\n',
        b'{"note":"api\\u005fkey=cleartext-secret-value"}\n',
    ],
)
def test_selected_json_credentials_are_rejected_recursively(
    tmp_path: Path, body: bytes
) -> None:
    run = _run(tmp_path, public_body=body, public_media_type="application/json")
    output = tmp_path / "credential.zip"
    with pytest.raises(CrateError, match="sensitive|secret"):
        export_ro_crate(run, output, include_artifact_ids=("artifact.38",))
    assert not output.exists()


def test_codemeta_links_component_licenses_without_root_license() -> None:
    root = Path(__file__).resolve().parents[2]
    metadata = json.loads((root / "codemeta.json").read_bytes())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert metadata["name"] == "Academic Research Workbench"
    assert metadata["version"] == project["version"]
    assert metadata["description"] == project["description"]
    repository = "https://github.com/zhangyang-crazy-one/academic-research-workbench"
    assert metadata["codeRepository"] == repository
    links = metadata["relatedLink"]
    assert all(
        urlparse(link).scheme == "https" and urlparse(link).netloc for link in links
    )
    assert repository in links
    assert {
        "https://creativecommons.org/licenses/by-nc/4.0/",
        "https://opensource.org/license/mit",
    } <= set(links)
    assert all(urlparse(link).path for link in links)
    assert "license" not in metadata
    assert {item["license"] for item in metadata["hasPart"]} == {
        "https://creativecommons.org/licenses/by-nc/4.0/",
        "https://opensource.org/license/mit",
    }
