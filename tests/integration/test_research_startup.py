"""Real project/run startup, interruption, conflict and proof-scope boundaries."""

import json
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from arw.cli import main
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.projects import initialize_project
from arw.kernel.policy.core_integrity import CoreIntegrityError
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.research_startup import PLAN, load_plan, start, status


def test_core_identity_is_shared_with_old_memory_alias(tmp_path, monkeypatch):
    from arw_research_memory.project import initialize_project as old_alias

    from arw.composition import initialize_memory_project

    monkeypatch.setattr(
        "arw.composition.import_module",
        lambda _: pytest.fail("optional provider imported"),
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(lambda _: initialize_project(tmp_path), range(4)))
    assert len({i.project_id for i in identities}) == 1
    assert old_alias(tmp_path) == identities[0] == initialize_memory_project(tmp_path)
    with pytest.raises(ValueError, match="differs"):
        initialize_project(tmp_path, "project.other")


def test_actual_cli_start_retry_status_and_material_acceptance(tmp_path, capsys):
    args = [
        "research",
        "start",
        "--project-root",
        str(tmp_path),
        "--direction",
        "语义学与 LLM 理解",
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    again = json.loads(capsys.readouterr().out)
    assert first == again
    assert first["core"]["integrity"] == "UNVERIFIED"
    assert first["intent"]["initial_phase"] == "scoping"
    assert first["run"]["lifecycle"] == "RUNNING"
    assert first["run"]["workflow_stage"] == "initialized"
    assert first["scientific_evidence"]["status"] == "not_evaluated"
    assert first["executor"]["status"] == "not_evaluated"
    assert not (tmp_path / ".arw/narrative").exists()
    run = tmp_path / first["run_relative"]
    (run / "reading.json").write_bytes(
        canonical_json_bytes({"synthetic": True, "reading_scope": "abstract-only"})
    )
    prior = replay_run(run)
    accepted = RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": prior.run_id,
                "occurred_at": load_plan(tmp_path).request.occurred_at,
                "event_id": f"evt-{uuid.uuid4()}",
                "command_id": f"cmd-{uuid.uuid4()}",
                "actor_id": "parent.fixture",
                "actor_role": "parent_control_plane",
                "expected_revision": prior.revision,
                "artifact_id": "reading.synthetic",
                "artifact_kind": "research-evidence",
                "media_type": "application/json",
                "content_path": "reading.json",
                "content_sha256": sha256_hex((run / "reading.json").read_bytes()),
                "base_revision": prior.revision,
                "consumed_sha256": [prior.last_event_sha256],
            }
        )
    )
    assert accepted.accepted
    report = start(tmp_path, resume=True)
    assert report["run"]["revision"] == 2
    assert report["materials"]["accepted_record_count"] == 1
    assert report["run"]["workflow_stage"] == "initialized"
    assert report["scientific_evidence"]["status"] == "not_evaluated"


@pytest.mark.parametrize(
    "point",
    [
        "plan_durable",
        "identity_durable",
        "request_durable",
        "input_durable",
        "run_durable",
        "manifest_only",
        "journal_directory",
        "segments_directory",
        "first_event_durable",
    ],
)
def test_actual_sigkill_resumes_same_requests_without_duplicate_events(tmp_path, point):
    code = """import os,signal,sys
from pathlib import Path
from arw.research_startup import start
from arw.kernel.ledger import journal
point=sys.argv[2]
def stop(label):
 if label==point:os.kill(os.getpid(),signal.SIGKILL)
if point in {"manifest_only","first_event_durable"}:
 original=journal._write_exclusive
 def write(path,data):
  original(path,data)
  if path.name==("run-manifest.json" if point=="manifest_only" else "00000001.jsonl"):os.kill(os.getpid(),signal.SIGKILL)
 journal._write_exclusive=write
if point in {"journal_directory","segments_directory"}:
 original_mkdir=Path.mkdir
 def mkdir(path,*args,**kwargs):
  original_mkdir(path,*args,**kwargs)
  if path.name==("journal" if point=="journal_directory" else "segments"):os.kill(os.getpid(),signal.SIGKILL)
 Path.mkdir=mkdir
start(Path(sys.argv[1]),direction="修正对世界的理解",boundary=stop)
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), point],
        capture_output=True,
        check=False,
    )
    assert process.returncode == -9, process.stderr
    plan = load_plan(tmp_path, allow_pending_identity=True)
    report = start(tmp_path, resume=True)
    assert report["project"]["project_id"] == plan.project_id
    assert report["planned_run_id"] == plan.request.run_id
    assert report["run"]["event_count"] == 1
    assert start(tmp_path, resume=True) == report


def test_plan_only_and_relocation_preserve_identity(tmp_path):
    original = tmp_path / "original"
    pending = start(original, direction="语义学与 LLM 理解", plan_only=True)
    assert pending["status"] == "startup_incomplete"
    assert pending["run"] is None
    ready = start(original, resume=True)
    moved = tmp_path / "moved"
    shutil.move(original, moved)
    assert (
        start(
            moved,
            resume=True,
            expected_project_id=ready["project"]["project_id"],
            expected_run_id=ready["planned_run_id"],
        )
        == ready
    )
    with pytest.raises(ValueError, match="identity differs"):
        status(moved, expected_project_id="project.other")


@pytest.mark.parametrize(
    "damage", ["intent", "identity", "manifest", "journal", "request", "run-symlink"]
)
def test_conflicting_or_damaged_history_is_never_reinitialized(tmp_path, damage):
    report = start(tmp_path, direction="语义学与 LLM 理解")
    run = tmp_path / report["run_relative"]
    original = (run / "journal/segments/00000001.jsonl").read_bytes()
    if damage == "intent":
        (run / "input/research-intent.json").write_bytes(b"changed")
    elif damage == "identity":
        (tmp_path / ".arw/project.json").write_bytes(
            canonical_json_bytes(
                {"schema_version": "arw.project.v1", "project_id": "project.other"}
            )
        )
    elif damage == "manifest":
        value = json.loads((run / "run-manifest.json").read_text())
        value["run_id"] = f"run-{uuid.uuid4()}"
        (run / "run-manifest.json").write_bytes(canonical_json_bytes(value))
    elif damage == "journal":
        (run / "journal/segments/00000001.jsonl").write_bytes(b"broken\n")
    elif damage == "request":
        (tmp_path / ".arw/research/init-request.json").write_bytes(b"{}")
    else:
        old = tmp_path / "old"
        shutil.move(run, old)
        run.symlink_to(old, target_is_directory=True)
    with pytest.raises((ValueError, OSError, RuntimeError)):
        start(tmp_path, resume=True)
    if damage != "journal":
        assert (run / "journal/segments/00000001.jsonl").read_bytes() == original


def test_core_drift_blocks_before_project_writes(tmp_path, monkeypatch):
    def damaged():
        raise CoreIntegrityError("fixture drift")

    monkeypatch.setattr("arw.research_startup.installed_core_preflight", damaged)
    with pytest.raises(CoreIntegrityError):
        start(tmp_path, direction="语义学与 LLM 理解")
    assert not (tmp_path / PLAN).exists()
    assert not (tmp_path / ".arw/project.json").exists()


def test_paper_start_uses_existing_selection_and_stale_guards(tmp_path):
    from arw.kernel.ledger.narrative import approve, propose, register, select
    from tests.unit.test_narrative import plan as narrative_plan

    initialize_project(tmp_path)
    with pytest.raises(ValueError):
        start(tmp_path, direction="bounded paper", phase="writing", task_kind="paper")
    assert not (tmp_path / PLAN).exists()
    register(tmp_path)
    selected = select(tmp_path, narrative_plan())
    ready = start(
        tmp_path, direction="bounded paper", phase="writing", task_kind="paper"
    )
    proposal = propose(
        tmp_path,
        narrative_plan("theory"),
        expected_sha256=selected.sha256,
        reason="author changed method",
    )
    approve(
        tmp_path,
        proposal_sha256=proposal["proposal_sha256"],
        author_id="author.fixture",
    )
    with pytest.raises(ValueError):
        status(tmp_path)
    assert replay_run(tmp_path / ready["run_relative"]).revision == 1
