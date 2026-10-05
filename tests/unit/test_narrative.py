"""Paper narrative selection, author change and runtime binding acceptance cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import initialize_run
from arw.kernel.ledger.narrative import (
    NarrativeError,
    approve,
    binding_for_start,
    current,
    guard_run,
    propose,
    register,
    select,
    status,
)
from arw.kernel.state.models import InitRunRequest, ResumeRequest, RunManifest
from arw.kernel.state.narrative import NarrativePlan
from arw.kernel.state.research_memory import ProjectIdentity


def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".arw").mkdir(parents=True)
    identity = ProjectIdentity(
        schema_version="arw.project.v1", project_id="project-paper-tests"
    )
    (root / ".arw/project.json").write_bytes(
        canonical_json_bytes(identity.model_dump(mode="json"))
    )
    return root


def plan(route="method_rq") -> NarrativePlan:
    return NarrativePlan(
        route=route,
        rationale="The contribution is established by a clearly ordered argument.",
        problem_to_contribution="The research problem motivates the contribution.",
        contribution_to_evidence="Evidence tests the precise contribution claim.",
        evidence_to_conclusion="Conclusions follow only the supported evidence.",
        scope_boundary="Limit conclusions to the demonstrated conditions.",
        function_order=(
            "problem",
            "gap",
            "contribution",
            "argument",
            "evidence",
            "knowledge_boundary",
        ),
        evidence_forms=("proof", "experiment", "annotation_validation"),
    )


def run_request(root: Path, *, binding=None) -> InitRunRequest:
    run = root / "runs/one"
    (run / "input").mkdir(parents=True)
    (run / "input/source.txt").write_text("test source\n", encoding="utf-8")
    return InitRunRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000001",
            "occurred_at": "2026-07-13T00:00:00Z",
            "immutable_input": {
                "path": "input/source.txt",
                "sha256": sha256_hex((run / "input/source.txt").read_bytes()),
            },
            "workflow_family": "academic-pipeline",
            "workflow_mode": "inline-role-prompts",
            "capabilities": ["canonical-journal"],
            "event_id": "evt-00000000-0000-4000-8000-000000000001",
            "command_id": "cmd-00000000-0000-4000-8000-000000000001",
            "actor_id": "parent.runtime",
            **(
                {
                    "task_kind": "paper",
                    "narrative_binding": binding.model_dump(mode="json"),
                }
                if binding
                else {}
            ),
        }
    )


def test_initial_selection_reloads_and_approved_change_preserves_history(tmp_path):
    root = project(tmp_path)
    assert status(root)["status"] == "not_applicable"
    assert register(root)["status"] == "missing_selection"
    with pytest.raises(NarrativeError, match="must be selected"):
        current(root)
    first = select(root, plan())
    assert status(root)["current"]["sha256"] == first.sha256
    with pytest.raises(NarrativeError) as duplicate:
        select(root, plan("theory"))
    assert duplicate.value.code == "already_selected"
    with pytest.raises(NarrativeError) as stale:
        propose(
            root,
            plan("theory"),
            expected_sha256="f" * 64,
            reason="Changed paper contribution",
        )
    assert stale.value.code == "stale_narrative"
    proposal = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="The author changed the contribution type",
    )
    assert current(root) == first
    assert status(root)["status"] == "pending_change"
    with pytest.raises(NarrativeError) as wrong:
        approve(root, proposal_sha256="a" * 64, author_id="author.owner")
    assert wrong.value.code == "stale_proposal"
    second = approve(
        root, proposal_sha256=proposal["proposal_sha256"], author_id="author.owner"
    )
    assert second.version == 2 and second.plan.route == "theory"
    assert status(root)["event_count"] == 4
    assert first.sha256 in (root / ".arw/narrative/events.jsonl").read_text()
    with pytest.raises(NarrativeError) as old:
        propose(root, plan(), expected_sha256=first.sha256, reason="Old agent stale")
    assert old.value.code == "stale_narrative"


def test_history_corruption_and_unsafe_paths_fail_closed(tmp_path):
    root = project(tmp_path)
    register(root)
    select(root, plan())
    history = root / ".arw/narrative/events.jsonl"
    history.write_bytes(history.read_bytes().replace(b"method_rq", b"theory"))
    with pytest.raises(NarrativeError) as corrupt:
        status(root)
    assert corrupt.value.code == "corrupt_history"
    history.unlink()
    outside = tmp_path / "outside"
    outside.write_text("outside")
    history.symlink_to(outside)
    with pytest.raises(NarrativeError):
        status(root)
    history.unlink()
    (root / ".arw/narrative/.lock").unlink()
    (root / ".arw/narrative/.lock").symlink_to(outside)
    with pytest.raises(NarrativeError) as unsafe:
        status(root)
    assert unsafe.value.code == "unsafe_state"
    assert outside.read_text() == "outside"


def test_paper_run_binds_project_and_rejects_old_agent_after_change(tmp_path):
    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    request = run_request(root, binding=binding_for_start(root, run))
    initialize_run(run, request)
    with guard_run(run, expected_sha256=first.sha256) as snapshot:
        assert snapshot == first
    proposal = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author approved revised strategy",
    )
    second = approve(
        root, proposal_sha256=proposal["proposal_sha256"], author_id="author.owner"
    )
    with (
        pytest.raises(NarrativeError) as stale,
        guard_run(run, expected_sha256=first.sha256),
    ):
        pass
    assert stale.value.code == "stale_narrative"
    with guard_run(run, expected_sha256=second.sha256) as snapshot:
        assert snapshot.version == 2
    manifest = RunManifest.model_validate_json((run / "run-manifest.json").read_bytes())
    assert (
        manifest.task_kind == "paper"
        and manifest.narrative_binding.project_id == first.project_id
    )
    with pytest.raises(ValueError, match="must occur together"):
        RunManifest.model_validate(
            {**manifest.model_dump(mode="json"), "narrative_binding": None}
        )


def test_nonpaper_run_and_paper_startup_without_selection(tmp_path):
    root = project(tmp_path)
    request = run_request(root)
    initialize_run(root / "runs/one", request)
    with guard_run(root / "runs/one") as snapshot:
        assert snapshot is None
    paper = project(tmp_path / "second")
    register(paper)
    run_request(paper)
    with pytest.raises(NarrativeError) as missing:
        binding_for_start(paper, paper / "runs/one")
    assert missing.value.code == "missing_selection"


def test_direct_resume_refuses_missing_and_stale_paper_version(tmp_path, monkeypatch):
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))
    resume = ResumeRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000001",
            "event_id": "evt-00000000-0000-4000-8000-000000000002",
            "command_id": "cmd-00000000-0000-4000-8000-000000000002",
            "expected_revision": 1,
            "occurred_at": "2026-07-13T00:00:01Z",
            "actor_id": "operator.test",
            "actor_role": "operator",
            "passport_sha256": "a" * 64,
        }
    )
    service = RuntimeCommandService(run)
    monkeypatch.setattr(service, "_resume_bound", lambda request: "entered")
    with pytest.raises(NarrativeError) as missing:
        service.resume(resume)
    assert missing.value.code == "missing_narrative_binding"
    assert (
        service.resume(resume.model_copy(update={"narrative_sha256": first.sha256}))
        == "entered"
    )
    proposal = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="New evidence route approved",
    )
    approve(root, proposal_sha256=proposal["proposal_sha256"], author_id="author.owner")
    with pytest.raises(NarrativeError) as stale:
        service.resume(resume.model_copy(update={"narrative_sha256": first.sha256}))
    assert stale.value.code == "stale_narrative"


def test_two_agents_cannot_select_or_change_same_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    root = project(tmp_path)
    register(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: _capture(lambda: select(root, plan())), range(2))
        )
    assert sum(result == "selected" for result in results) == 1
    assert results.count("already_selected") == 1
    first = current(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _capture(
                    lambda: propose(
                        root,
                        plan("theory"),
                        expected_sha256=first.sha256,
                        reason="Author reorders the claim",
                    )
                ),
                range(2),
            )
        )
    assert sum(result == "proposed" for result in results) == 1
    assert results.count("pending_change") == 1


def _capture(call):
    try:
        result = call()
        return "selected" if hasattr(result, "version") else "proposed"
    except NarrativeError as error:
        return error.code


def test_project_copy_relocates_relative_binding(tmp_path):
    import shutil

    root = project(tmp_path)
    register(root)
    first = select(root, plan("resource_evaluation"))
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))
    moved = tmp_path / "relocated"
    shutil.copytree(root, moved)
    with guard_run(moved / "runs/one", expected_sha256=first.sha256) as snapshot:
        assert snapshot.project_id == first.project_id
    (moved / ".arw/narrative/events.jsonl").unlink()
    with pytest.raises(NarrativeError) as missing, guard_run(moved / "runs/one"):
        pass
    assert missing.value.code == "missing_selection"


def test_bounded_change_and_short_writes_keep_history_readable(tmp_path, monkeypatch):
    from arw.kernel.ledger import narrative

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    path = root / ".arw/narrative/events.jsonl"
    baseline = path.read_bytes()
    with pytest.raises(NarrativeError):
        propose(root, plan("theory"), expected_sha256=first.sha256, reason="x" * 2050)
    assert path.read_bytes() == baseline
    monkeypatch.setattr(narrative, "MAX_HISTORY", len(baseline) + 2)
    with pytest.raises(NarrativeError) as full:
        propose(
            root,
            plan("theory"),
            expected_sha256=first.sha256,
            reason="Changed contribution",
        )
    assert full.value.code == "history_full"
    assert path.read_bytes() == baseline
    monkeypatch.setattr(narrative, "MAX_HISTORY", 1_048_576)
    original_write = narrative.os.write
    monkeypatch.setattr(
        narrative.os,
        "write",
        lambda fd, data: original_write(fd, data[: max(1, len(data) // 2)]),
    )
    proposed = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Changed contribution",
    )
    assert proposed["status"] == "pending_change"
    assert status(root)["event_count"] == 3


def test_cli_paper_startup_binds_before_outline_and_nonpaper_remains_generic(
    tmp_path, capsys
):
    from arw import cli

    root = project(tmp_path)
    register(root)
    run = root / "runs/one"
    request = run_request(root)
    path = tmp_path / "request.json"
    path.write_bytes(
        canonical_json_bytes(request.model_dump(mode="json", exclude_none=True))
    )
    assert (
        cli.main(
            [
                "init",
                "--run-root",
                str(run),
                "--request",
                str(path),
                "--task-kind",
                "paper",
                "--project-root",
                str(root),
            ]
        )
        == 65
    )
    assert not (run / "run-manifest.json").exists()
    select(root, plan())
    assert (
        cli.main(
            [
                "init",
                "--run-root",
                str(run),
                "--request",
                str(path),
                "--task-kind",
                "paper",
                "--project-root",
                str(root),
            ]
        )
        == 0
    )
    assert (
        RunManifest.model_validate_json(
            (run / "run-manifest.json").read_bytes()
        ).task_kind
        == "paper"
    )
    other = project(tmp_path / "other")
    other_request = run_request(other)
    other_file = tmp_path / "other-request.json"
    other_file.write_bytes(
        canonical_json_bytes(other_request.model_dump(mode="json", exclude_none=True))
    )
    assert (
        cli.main(
            [
                "init",
                "--run-root",
                str(other / "runs/one"),
                "--request",
                str(other_file),
            ]
        )
        == 0
    )
    assert (
        RunManifest.model_validate_json(
            (other / "runs/one/run-manifest.json").read_bytes()
        ).task_kind
        is None
    )


def test_real_passport_resume_checks_narrative_before_consuming(tmp_path):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.workflows import CORE_WORKFLOW
    from arw.kernel.state.models import CheckpointRequest

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    request = run_request(root, binding=binding_for_start(root, run))
    request = request.model_copy(
        update={
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
        }
    )
    initialize_run(run, request)
    service = RuntimeCommandService(run)
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": request.run_id,
                "event_id": "evt-00000000-0000-4000-8000-000000000003",
                "command_id": "cmd-00000000-0000-4000-8000-000000000003",
                "expected_revision": 1,
                "occurred_at": "2026-07-13T00:00:01Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "checkpoint_kind": "explicit",
                "fresh_until": None,
            }
        )
    )
    assert checkpoint.accepted
    passport = checkpoint.state.current_passport_sha256
    common = {
        "schema_version": "1.0.0",
        "run_id": request.run_id,
        "event_id": "evt-00000000-0000-4000-8000-000000000004",
        "command_id": "cmd-00000000-0000-4000-8000-000000000004",
        "expected_revision": 2,
        "occurred_at": "2026-07-13T00:00:02Z",
        "actor_id": "operator.test",
        "actor_role": "operator",
        "passport_sha256": passport,
    }
    before = service.read_state().accepted_revision
    with pytest.raises(NarrativeError):
        service.resume(ResumeRequest.model_validate(common))
    assert service.read_state().accepted_revision == before
    resumed = service.resume(
        ResumeRequest.model_validate({**common, "narrative_sha256": first.sha256})
    )
    assert resumed.accepted


def test_direct_paper_writing_prepare_and_record_reject_missing_or_old_version(
    tmp_path, monkeypatch
):
    from arw_writing.service import WritingService

    from tests.integration.test_writing import CANDIDATE, SOURCE
    from tests.integration.test_writing import proposal as writing_proposal

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))
    service = WritingService(run)
    monkeypatch.setattr(
        service,
        "_source",
        lambda artifact_id: (
            SOURCE.encode(),
            {"artifact_id": artifact_id, "manifest_sha256": "a" * 64},
        ),
    )
    p = writing_proposal(SOURCE, CANDIDATE)
    with pytest.raises(NarrativeError) as missing:
        service.prepare("artifact.source", p)
    assert missing.value.code == "missing_narrative_binding"
    p["narrative_sha256"] = first.sha256
    result = service.prepare("artifact.source", p)
    assert result["narrative_binding"]["version"] == 1
    change = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author changes paper argument",
    )
    second = approve(
        root, proposal_sha256=change["proposal_sha256"], author_id="author.owner"
    )
    with pytest.raises(NarrativeError) as stale:
        service.prepare("artifact.source", p)
    assert stale.value.code == "stale_narrative"
    with pytest.raises(NarrativeError) as record_stale:
        service.record("artifact.source", p, request=None)
    assert record_stale.value.code == "stale_narrative"
    p["narrative_sha256"] = second.sha256
    assert service.prepare("artifact.source", p)["narrative_binding"]["version"] == 2
    assert not (run / "writing").exists()


def test_direct_memory_handoff_save_and_resume_validate_current_narrative(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from arw_research_memory.service import ResearchMemoryService

    from arw.kernel.state.research_memory import MemoryQuery

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))
    service = ResearchMemoryService(root, run_root=run)
    monkeypatch.setattr(service, "_save_bound", lambda value, request: {"saved": True})
    monkeypatch.setattr(
        service,
        "_resume_handoff_bound",
        lambda memory_id, query, snapshot: {
            "narrative_sha256": first.sha256,
            "memory_id": memory_id,
        },
    )
    value = SimpleNamespace(handoff=SimpleNamespace(narrative_sha256=None))
    with pytest.raises(NarrativeError) as missing:
        service.save(value, request=None)
    assert missing.value.code == "missing_narrative_binding"
    value.handoff.narrative_sha256 = first.sha256
    assert service.save(value, request=None) == {"saved": True}
    assert (
        service.resume_handoff("memory.one", query=MemoryQuery(max_tokens=16384))[
            "narrative"
        ]["version"]
        == 1
    )
    change = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author changes strategy",
    )
    second = approve(
        root, proposal_sha256=change["proposal_sha256"], author_id="author.owner"
    )
    with pytest.raises(NarrativeError) as stale_save:
        service.save(value, request=None)
    assert stale_save.value.code == "stale_narrative"
    with pytest.raises(NarrativeError) as stale_resume:
        service.resume_handoff("memory.one", query=MemoryQuery(max_tokens=16384))
    assert stale_resume.value.code == "stale_narrative"
    value.handoff.narrative_sha256 = second.sha256
    assert service.save(value, request=None) == {"saved": True}


@pytest.mark.parametrize(
    "route",
    ["method_rq", "observation_mechanism", "resource_evaluation", "theory", "custom"],
)
def test_all_argument_routes_allow_uncertain_results_without_hypothesis(
    tmp_path, route
):
    root = project(tmp_path)
    register(root)
    selected = select(root, plan(route))
    assert selected.plan.route == route
    assert not hasattr(selected.plan, "hypothesis")
    assert "experiment" in selected.plan.evidence_forms


def test_project_only_memory_service_cannot_resume_canonical_handoff(tmp_path):
    from arw_research_memory.project import MemoryAccessDenied
    from arw_research_memory.service import ResearchMemoryService

    from arw.kernel.state.research_memory import MemoryQuery

    root = project(tmp_path)
    service = ResearchMemoryService(root, run_root=None)
    with pytest.raises(MemoryAccessDenied, match="current canonical run"):
        service.resume_handoff("memory.missing", query=MemoryQuery())


def test_cli_change_requires_explicit_author_confirmation_assertion(tmp_path, capsys):
    from arw import cli

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    pending = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author asks to change reasoning route",
    )
    args = [
        "narrative",
        "approve",
        "--project-root",
        str(root),
        "--proposal-sha256",
        pending["proposal_sha256"],
        "--author-id",
        "author.owner",
    ]
    assert cli.main(args) == 65
    assert json.loads(capsys.readouterr().out)["code"] == "author_confirmation_missing"
    assert current(root).sha256 == first.sha256
    assert cli.main([*args, "--author-confirmed"]) == 0
    assert current(root).version == 2


def _accept_paper_artifact(
    run: Path, artifact_id: str, relative: str, number: int, *, kind: str
):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.state.models import ArtifactAcceptanceRequest

    state = replay_run(run)
    return RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": state.run_id,
                "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
                "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
                "expected_revision": state.revision,
                "occurred_at": "2026-07-13T00:01:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "artifact_id": artifact_id,
                "artifact_kind": kind,
                "media_type": "application/json",
                "content_path": relative,
                "content_sha256": sha256_hex((run / relative).read_bytes()),
                "base_revision": state.revision,
                "consumed_sha256": [state.last_event_sha256],
            }
        )
    )


def _parent_request(run: Path, number: int):
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.state.models import RuntimeCommandRequest

    replay = replay_run(run)
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": replay.run_id,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
            "expected_revision": replay.revision,
            "occurred_at": "2026-07-13T00:02:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def test_paper_writing_record_real_receipt_and_stale_change(tmp_path):
    from arw_writing.service import WritingService

    from arw.kernel.ledger.workflows import CORE_WORKFLOW
    from tests.integration.test_writing import (
        CANDIDATE,
        SOURCE,
    )
    from tests.integration.test_writing import (
        proposal as writing_proposal,
    )

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    request = run_request(root, binding=binding_for_start(root, run)).model_copy(
        update={
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
        }
    )
    initialize_run(run, request)
    (run / "manuscript.txt").write_text(SOURCE, encoding="utf-8")
    assert _accept_paper_artifact(
        run, "artifact.manuscript", "manuscript.txt", 40, kind="writing-source"
    ).accepted
    service = WritingService(run)
    p = writing_proposal(SOURCE, CANDIDATE)
    p["narrative_sha256"] = first.sha256
    receipt = service.record("artifact.manuscript", p, request=_parent_request(run, 50))
    assert receipt["status"] == "recorded"
    assert (
        json.loads((run / receipt["bundle_path"]).read_text())["narrative_binding"][
            "sha256"
        ]
        == first.sha256
    )
    change = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author revises contribution",
    )
    second = approve(
        root, proposal_sha256=change["proposal_sha256"], author_id="author.owner"
    )
    with pytest.raises(NarrativeError) as stale:
        service.record("artifact.manuscript", p, request=_parent_request(run, 51))
    assert stale.value.code == "stale_narrative"
    p["narrative_sha256"] = second.sha256
    next_receipt = service.record(
        "artifact.manuscript", p, request=_parent_request(run, 52)
    )
    assert next_receipt["status"] == "recorded"
    assert (
        json.loads((run / next_receipt["bundle_path"]).read_text())[
            "narrative_binding"
        ]["version"]
        == 2
    )


def test_paper_handoff_real_body_resume_and_old_version_rejected(tmp_path):
    from arw_research_memory.service import ResearchMemoryService

    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.ledger.workflows import CORE_WORKFLOW
    from arw.kernel.state.research_memory import MemoryInput, MemoryQuery

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    request = run_request(root, binding=binding_for_start(root, run)).model_copy(
        update={
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
        }
    )
    initialize_run(run, request)
    (run / "target.json").write_text(
        '{"objective":"Evaluate the comparison"}', encoding="utf-8"
    )
    assert _accept_paper_artifact(
        run, "artifact.target", "target.json", 41, kind="author-target"
    ).accepted
    target = replay_run(run).events[-1]
    service = ResearchMemoryService(root, run_root=run)

    def handoff(version, memory_id):
        return MemoryInput.model_validate_json(
            json.dumps(
                {
                    "memory_id": memory_id,
                    "kind": "handoff",
                    "title": "Paper continuation",
                    "body": "Evaluate the recorded comparison.",
                    "source_artifact_ids": ["artifact.target"],
                    "source_ledger_event_ids": [target.event_id],
                    "links": [
                        {
                            "kind": "author_target",
                            "target_id": "artifact.target",
                            "event_id": target.event_id,
                            "sha256": target.payload.artifact_sha256,
                        }
                    ],
                    "handoff": {
                        "objective": "Evaluate the comparison",
                        "current_state": "Target accepted",
                        "completed_work": [],
                        "evidence_gathered": [],
                        "commands_evaluations_run": [],
                        "relevant_artifacts_issues_files": [],
                        "open_questions": [],
                        "blockers": [],
                        "risks": [],
                        "next_concrete_action": "Compare the retained values",
                        "source_run_harness": {
                            "run_id": replay_run(run).run_id,
                            "harness": "codex",
                        },
                        "intended_target_harness": "claude",
                        "narrative_sha256": version,
                    },
                }
            )
        )

    saved = service.save(
        handoff(first.sha256, "memory.paper-one"), request=_parent_request(run, 70)
    )
    resumed = service.resume_handoff(
        saved["memory_id"], query=MemoryQuery(max_tokens=16384)
    )
    assert resumed["narrative"]["sha256"] == first.sha256
    assert resumed["next_concrete_action"] == "Compare the retained values"
    change = propose(
        root,
        plan("theory"),
        expected_sha256=first.sha256,
        reason="Author changes strategy",
    )
    second = approve(
        root, proposal_sha256=change["proposal_sha256"], author_id="author.owner"
    )
    with pytest.raises(NarrativeError) as stale:
        service.resume_handoff(saved["memory_id"], query=MemoryQuery(max_tokens=16384))
    assert stale.value.code == "stale_narrative"
    new = service.save(
        handoff(second.sha256, "memory.paper-two"), request=_parent_request(run, 71)
    )
    assert (
        service.resume_handoff(new["memory_id"], query=MemoryQuery(max_tokens=16384))[
            "narrative"
        ]["version"]
        == 2
    )


def test_run_manifest_schema_rejects_unrecognized_narrative_field(tmp_path):
    from arw.kernel.policy.schema_registry import validate_instance

    root = project(tmp_path)
    request = run_request(root)
    run = root / "runs/one"
    initialize_run(run, request)
    manifest = json.loads((run / "run-manifest.json").read_text())
    validate_instance("run-manifest.schema.json", manifest)
    with pytest.raises(ValueError):
        validate_instance(
            "run-manifest.schema.json", {**manifest, "narrative_run_binding": {}}
        )
