"""Canonical memory behavior, bounded recall, governance, and harness isolation."""

import json
import subprocess
import sys

import pytest
from arw_research_memory.project import MemoryAccessDenied, initialize_project
from arw_research_memory.service import ResearchMemoryService
from arw_research_memory.store import (
    MemoryConflict,
    MemoryIntegrityError,
    body_path,
    cycle_ids,
)

from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.research_records import BodyUnavailable
from arw.kernel.state.research_memory import MemoryInput, MemoryQuery
from arw.memory_mcp import TOOLS, MemoryMcpServer

from .test_precise_source_locators import accept, seed
from .test_research_artifacts import request


def prepared(tmp_path):
    root, _ = seed(tmp_path)
    initialize_project(root, "project.memory")
    return root, ResearchMemoryService(root, run_root=root)


def note(**overrides):
    return MemoryInput.model_validate_json(
        json.dumps(
            {
                "kind": "context",
                "title": "Experiment progress",
                "body": "The baseline is complete. Evaluate the retained comparison next.",
                **overrides,
            }
        )
    )


def test_save_retry_rebuild_cross_harness(tmp_path):
    root, service = prepared(tmp_path)
    receipt = service.save(note(), request=request(root))
    count = len(replay_run(root).events)
    other = ResearchMemoryService(root, run_root=root, harness="claude")
    assert (
        other.save(note(), request=request(root, 101))["memory_id"]
        == receipt["memory_id"]
    )
    assert len(replay_run(root).events) == count
    before = service.search(MemoryQuery())
    (root / ".arw/memory/index.sqlite3").unlink()
    assert service.rebuild()["rebuilt"] == 1
    assert service.search(MemoryQuery()) == before
    doc = other.read(receipt["memory_id"], query=MemoryQuery())["memory"]
    assert doc["source_harness"] == "codex"
    assert service.doctor()["status"] == "PASS"


def test_conflict_supersession_and_trust(tmp_path):
    root, service = prepared(tmp_path)
    first = service.save(note(memory_id="memory.first"), request=request(root))
    with pytest.raises(MemoryConflict):
        service.save(
            note(memory_id="memory.first", body="Different"), request=request(root, 101)
        )
    active = service.govern("memory.first", "activate", request=request(root, 102))
    assert active["status"] == "active" and active["trust"] == "unreviewed"
    second = service.save(
        note(body="Updated baseline", supersedes=["memory.first"]),
        request=request(root, 103),
    )
    assert (
        service.read(first["memory_id"], query=MemoryQuery())["lifecycle"]["status"]
        == "superseded"
    )
    assert service.search(MemoryQuery())["rank_order"] == [second["memory_id"]]


def test_privacy_scope_and_bounded_recall(tmp_path):
    root, service = prepared(tmp_path)
    with pytest.raises(MemoryAccessDenied):
        service.save(note(scope="user"), request=request(root))
    with pytest.raises(ValueError):
        service.save(
            note(body="-----BEGIN PRIVATE KEY-----\nABC"), request=request(root)
        )
    assert not (root / ".arw/memory/bodies").exists()
    saved = service.save(note(body="Long context. " * 300), request=request(root))
    assert len(json.dumps(service.search(MemoryQuery(max_tokens=256))).encode()) <= 256
    assert "memory" not in service.search(MemoryQuery())["matches"][0]
    with pytest.raises(MemoryAccessDenied):
        service.read(saved["memory_id"], query=MemoryQuery(scope="user"))
    with pytest.raises(MemoryAccessDenied):
        service.search(MemoryQuery(project_id="project.other", cross_project=True))


def test_tampering_doctor_readonly(tmp_path):
    root, service = prepared(tmp_path)
    saved = service.save(note(), request=request(root))
    body = root / body_path(saved["content_digest"])
    body.write_text("{}")
    before = body.read_bytes()
    assert service.doctor()["status"] == "FAIL"
    assert body.read_bytes() == before
    with pytest.raises(MemoryIntegrityError):
        service.search(MemoryQuery())


def test_mcp_narrow_process_bound_surface(tmp_path):
    root, service = prepared(tmp_path)
    server = MemoryMcpServer(root, run_root=root, harness="claude")
    assert (
        tuple(
            t["name"]
            for t in server.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
        )
        == TOOLS
    )
    call = lambda name, args: server.handle(
        {"id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}}
    )["result"]
    assert call("shell", {})["isError"]
    assert call(
        "memory_save", {**note().model_dump(mode="json"), "source_harness": "codex"}
    )["isError"]
    assert call("memory_save", {**note().model_dump(mode="json"), "trust": "verified"})[
        "isError"
    ]
    result = call("memory_save", note().model_dump(mode="json"))
    assert not result["isError"], result
    mid = result["structuredContent"]["memory_id"]
    assert (
        service.read(mid, query=MemoryQuery())["memory"]["source_harness"] == "claude"
    )


def test_cli_and_stdio_protocol(tmp_path):
    root, _ = prepared(tmp_path)
    cmd = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "memory",
            "doctor",
            "--project-root",
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cmd.returncode == 0, cmd.stdout + cmd.stderr
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.memory_mcp",
            "--project-root",
            str(root),
            "--harness",
            "claude",
        ],
        input="".join(json.dumps(m) + "\n" for m in messages),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert len(json.loads(proc.stdout.splitlines()[1])["result"]["tools"]) == 4


def test_cycle_detection_shared_ancestry():
    assert not cycle_ids([(str(i), str(j)) for i in range(25) for j in range(i)])
    assert cycle_ids([("a", "b"), ("b", "a")]) == {"a", "b"}


def handoff(root):
    (root / "target.json").write_text(
        json.dumps(
            {"objective": "Compare the fixed baseline", "method": "paired evaluation"}
        )
    )
    assert accept(
        root, "artifact.target", "target.json", 3, kind="author-target"
    ).accepted
    target = replay_run(root).events[-1]
    details = {
        "objective": "Compare the fixed baseline",
        "current_state": "Baseline complete",
        "completed_work": ["Baseline experiment"],
        "evidence_gathered": ["artifact.source"],
        "commands_evaluations_run": ["baseline evaluation"],
        "relevant_artifacts_issues_files": ["artifact.source"],
        "open_questions": [],
        "blockers": [],
        "risks": ["Small sample"],
        "next_concrete_action": "Evaluate the paired comparison",
        "source_run_harness": {"run_id": replay_run(root).run_id, "harness": "codex"},
        "intended_target_harness": "claude",
    }
    return note(
        kind="handoff",
        handoff=details,
        source_artifact_ids=["artifact.source", "artifact.target"],
        source_ledger_event_ids=[target.event_id],
        links=[
            {
                "kind": "author_target",
                "target_id": "artifact.target",
                "event_id": target.event_id,
                "sha256": target.payload.artifact_sha256,
            }
        ],
    )


def test_handoff_codex_claude_codex_continuation(tmp_path):
    root, service = prepared(tmp_path)
    saved = service.save(handoff(root), request=request(root))
    server = MemoryMcpServer(root, harness="claude")
    read = server.call("memory_read", {"memory_id": saved["memory_id"]})
    assert read["memory"]["handoff"]["completed_work"] == ["Baseline experiment"]
    continuation = service.resume_handoff(saved["memory_id"], query=MemoryQuery())
    assert continuation["next_concrete_action"] == "Evaluate the paired comparison"
    assert (
        continuation["canonical_author_targets"][0]["value"]["method"]
        == "paired evaluation"
    )
    assert not continuation["requires_reconciliation"]
    with pytest.raises(MemoryIntegrityError):
        service.resume_handoff(saved["memory_id"], query=MemoryQuery(max_tokens=256))


def test_verify_and_authorized_purge(tmp_path):
    root, service = prepared(tmp_path)
    saved = service.save(
        note(source_artifact_ids=["artifact.source"]), request=request(root)
    )
    for number, action in [(110, "verify"), (120, "purge")]:
        evidence = {
            "action": action + "_memory",
            "memory_id": saved["memory_id"],
            "content_digest": saved["content_digest"],
            "source_artifact_ids": ["artifact.source"],
        }
        name = action + ".json"
        (root / name).write_text(json.dumps(evidence))
        assert accept(
            root, "artifact." + action, name, number, kind="memory-authorization"
        ).accepted
    verified = service.govern(
        saved["memory_id"],
        "verify",
        request=request(root, 130),
        authorization_artifact_id="artifact.verify",
    )
    assert verified["status"] == "created" and verified["trust"] == "verified"
    count = len(replay_run(root).events)
    with pytest.raises(MemoryAccessDenied):
        service.purge(saved["memory_id"], authorization_artifact_id="artifact.purge")
    service.purge(
        saved["memory_id"], authorization_artifact_id="artifact.purge", authorized=True
    )
    assert len(replay_run(root).events) == count
    with pytest.raises(BodyUnavailable):
        service.read(saved["memory_id"], query=MemoryQuery())
    assert service.search(MemoryQuery())["matches"] == []
    assert service.rebuild()["tombstones"] == 1
    assert any(
        f["code"] == "memory_body_tombstoned" for f in service.doctor()["faults"]
    )


@pytest.mark.parametrize(
    "point", ["memory_body_durable", "memory_event_durable", "memory_index_updated"]
)
def test_crash_retry_is_create_only(tmp_path, point):
    root, service = prepared(tmp_path)
    req = request(root)

    def crash(stage):
        if stage == point:
            raise RuntimeError("simulated process termination")

    service.boundary = crash
    with pytest.raises(RuntimeError):
        service.save(note(), request=req)
    service.boundary = lambda _: None
    result = service.save(note(), request=req)
    events = [
        e for e in replay_run(root).events if e.event_type == "research_memory_created"
    ]
    assert len(events) == 1 and events[0].payload.memory_id == result["memory_id"]
    assert service.doctor()["status"] == "PASS"


def test_symlink_body_is_not_read_or_rewritten(tmp_path):
    root, service = prepared(tmp_path)
    saved = service.save(note(), request=request(root))
    body = root / body_path(saved["content_digest"])
    outside = tmp_path / "outside.json"
    outside.write_bytes(body.read_bytes())
    body.unlink()
    body.symlink_to(outside)
    assert service.doctor()["status"] == "FAIL"
    assert body.is_symlink()
    with pytest.raises(MemoryIntegrityError):
        service.read(saved["memory_id"], query=MemoryQuery())


def test_later_author_decision_stops_old_next_action(tmp_path):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.state.models import (
        HumanDecisionRequest,
        HumanDecisionResolveRequest,
    )

    root, service = prepared(tmp_path)
    saved = service.save(handoff(root), request=request(root))
    runtime = RuntimeCommandService(root)
    asked = runtime.request_decision(
        HumanDecisionRequest.model_validate(
            {
                **request(root, 150).model_dump(),
                "decision_id": "decision.method",
                "blocker_code": "method-choice",
                "allowed_choices": ["replace-method"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["start"],
            }
        )
    )
    assert asked.accepted
    resolved = runtime.resolve_decision(
        HumanDecisionResolveRequest.model_validate(
            {
                **request(root, 151).model_dump(),
                "actor_role": "operator",
                "decision_id": "decision.method",
                "choice": "replace-method",
                "rationale": "Use the revised comparison.",
            }
        )
    )
    assert resolved.accepted
    continuation = service.resume_handoff(saved["memory_id"], query=MemoryQuery())
    assert continuation["requires_reconciliation"]
    assert continuation["next_concrete_action"] is None
    assert continuation["canonical_decisions"][-1]["decision_id"] == "decision.method"


@pytest.mark.parametrize(
    "point", ["memory_body_durable", "memory_event_durable", "memory_index_updated"]
)
def test_actual_process_kill_and_retry(tmp_path, point):
    import signal

    root, service = prepared(tmp_path)
    command = """
import json, os, signal, sys
from pathlib import Path
from arw_research_memory.service import ResearchMemoryService
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_memory import MemoryInput
root=Path(sys.argv[1])
def stop(stage):
    if stage==sys.argv[2]:os.kill(os.getpid(),signal.SIGKILL)
service=ResearchMemoryService(root,run_root=root,boundary=stop)
service.save(MemoryInput.model_validate_json(sys.argv[3]),request=RuntimeCommandRequest.model_validate_json(sys.argv[4]))
"""
    req = request(root)
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            command,
            str(root),
            point,
            note().model_dump_json(),
            req.model_dump_json(),
        ],
        check=False,
        capture_output=True,
    )
    assert child.returncode == -signal.SIGKILL, child.stderr
    saved = service.save(note(), request=req)
    assert (
        service.read(saved["memory_id"], query=MemoryQuery())["memory"]["body"]
        == note().body
    )
    assert (
        len(
            [
                e
                for e in replay_run(root).events
                if e.event_type == "research_memory_created"
            ]
        )
        == 1
    )


def test_explicit_cross_project_and_user_authorization(tmp_path):
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.state.research_memory import CrossProjectGrant, MemoryAuthorization

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    root, service = prepared(a)
    other, _ = seed(b)
    initialize_project(other, "project.other")
    foreign = ResearchMemoryService(other, run_root=other)
    saved = foreign.save(
        note(scope="team", privacy_classification="shareable"), request=request(other)
    )
    with pytest.raises(MemoryAccessDenied):
        service.search(
            MemoryQuery(scope="team", project_id="project.other", cross_project=True)
        )
    policy = MemoryAuthorization(
        allow_user_scope=True,
        cross_project_roots=(
            CrossProjectGrant(project_id="project.other", root=str(other)),
        ),
    )
    (root / ".arw/memory-authorization.json").write_bytes(
        canonical_json_bytes(policy.model_dump(mode="json"))
    )
    result = service.search(
        MemoryQuery(scope="team", project_id="project.other", cross_project=True)
    )
    assert result["matches"][0]["memory_id"] == saved["memory_id"]
    assert result["matches"][0]["source_project_id"] == "project.other"
    service.save(note(scope="user"), request=request(root))
    assert service.search(MemoryQuery())["matches"] == []
    assert len(service.search(MemoryQuery(scope="user"))["matches"]) == 1


def test_doctor_detects_index_trust_drift_without_using_it(tmp_path):
    import sqlite3

    root, service = prepared(tmp_path)
    saved = service.save(note(), request=request(root))
    with sqlite3.connect(root / ".arw/memory/index.sqlite3") as db:
        db.execute("UPDATE research_memories SET trust='verified'")
    assert any(f["code"] == "memory_index_drift" for f in service.doctor()["faults"])
    assert (
        service.read(saved["memory_id"], query=MemoryQuery())["lifecycle"]["trust"]
        == "unreviewed"
    )
    assert service.search(MemoryQuery())["matches"][0]["trust"] == "unreviewed"


def test_new_author_target_requires_reconciliation(tmp_path):
    root, service = prepared(tmp_path)
    saved = service.save(handoff(root), request=request(root))
    (root / "revised-target.json").write_text(
        json.dumps({"objective": "Use a larger sample"})
    )
    assert accept(
        root,
        "artifact.revised-target",
        "revised-target.json",
        160,
        kind="author-target",
    ).accepted
    result = service.resume_handoff(saved["memory_id"], query=MemoryQuery())
    assert result["requires_reconciliation"]
    assert (
        result["canonical_author_targets"][-1]["value"]["objective"]
        == "Use a larger sample"
    )
    assert result["next_concrete_action"] is None


def test_standard_passport_resume_consumes_handoff(tmp_path):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.state.models import CheckpointRequest

    root, service = prepared(tmp_path)
    saved = service.save(handoff(root), request=request(root))
    checkpoint = RuntimeCommandService(root).create_checkpoint(
        CheckpointRequest.model_validate(
            {
                **request(root, 170).model_dump(),
                "checkpoint_kind": "explicit",
                "fresh_until": None,
            }
        )
    )
    assert checkpoint.accepted
    resume_request = {
        **request(root, 171).model_dump(),
        "actor_role": "operator",
        "passport_sha256": checkpoint.state.current_passport_sha256,
    }
    path = root / "resume-request.json"
    path.write_text(json.dumps(resume_request))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "resume",
            "--run-root",
            str(root),
            "--request",
            str(path),
            "--memory-handoff",
            saved["memory_id"],
            "--memory-project-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        json.loads(result.stdout)["memory_handoff"]["next_concrete_action"]
        == "Evaluate the paired comparison"
    )


def test_successor_event_crash_retry_finishes_supersession(tmp_path):
    root, service = prepared(tmp_path)
    service.save(note(memory_id="memory.old"), request=request(root))
    req = request(root, 190)
    value = note(body="New result", supersedes=["memory.old"])

    def crash(stage):
        if stage == "memory_event_durable":
            raise RuntimeError("termination")

    service.boundary = crash
    with pytest.raises(RuntimeError):
        service.save(value, request=req)
    service.boundary = lambda _: None
    result = service.save(value, request=req)
    previous = service.read("memory.old", query=MemoryQuery())
    assert previous["lifecycle"]["status"] == "superseded"
    assert service.search(MemoryQuery())["rank_order"] == [result["memory_id"]]


@pytest.mark.parametrize("field", ["kind", "status", "trust"])
def test_schema_rejects_unknown_memory_vocabulary(tmp_path, field):
    from jsonschema import ValidationError

    from arw.kernel.policy.schema_registry import validate_instance

    root, service = prepared(tmp_path)
    saved = service.save(note(), request=request(root))
    document = service.read(saved["memory_id"], query=MemoryQuery())["memory"]
    document[field] = "unknown-value"
    with pytest.raises((ValidationError, ValueError)):
        validate_instance("research-memory.schema.json", document)
