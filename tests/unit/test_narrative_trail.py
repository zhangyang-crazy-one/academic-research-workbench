"""Synthetic decision histories; these are not the ten-entry public author pilot."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.journal import initialize_run
from arw.kernel.ledger.narrative import (
    NarrativeError,
    approve,
    binding_for_start,
    propose,
    register,
    select,
    trail,
    trail_summary,
    withdraw,
)
from tests.unit.test_narrative import plan, project, run_request


def _events(root: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (root / ".arw/narrative/events.jsonl").read_text().splitlines()
    ]


def test_choice_sources_withdrawn_branch_successor_and_historical_view(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    register(root)
    initial = select(root, plan("method_rq"))
    first_view = trail(root)
    assert canonical_json_bytes(first_view) == canonical_json_bytes(trail(root))
    assert first_view["choices"][0]["disposition"] == "kept"
    assert first_view["current_choice_ids"] == [initial.sha256]

    branch = propose(
        root,
        plan("observation_mechanism"),
        expected_sha256=initial.sha256,
        reason="A mechanism route was considered for this study",
    )
    pending = trail(root)
    assert pending["choices"][-1]["disposition"] == "unknown"
    assert pending["unresolved_questions"][0]["kind"] == "pending_author_decision"
    branch_sequence = pending["view_sequence"]
    withdrawn = withdraw(
        root,
        proposal_sha256=branch["proposal_sha256"],
        author_id="author.owner",
        reason="The author withdrew this branch without selecting a replacement",
    )
    abandoned = trail(root)
    assert abandoned["choices"][-1]["disposition"] == "abandoned"
    assert abandoned["choices"][-1]["successor"] is None
    assert (
        abandoned["choices"][-1]["withdrawal_reason"]["source"]["event_sha256"]
        == withdrawn["withdrawal_sha256"]
    )
    assert (
        trail(root, at_sequence=branch_sequence)["choices"][-1]["disposition"]
        == "unknown"
    )

    replacement = propose(
        root,
        plan("theory"),
        expected_sha256=initial.sha256,
        reason="The theoretical argument now fits the documented contribution",
    )
    current = approve(
        root,
        proposal_sha256=replacement["proposal_sha256"],
        author_id="author.owner",
    )
    view = trail(root)
    selected, withdrawn_branch, successor = view["choices"]
    assert [item["disposition"] for item in view["choices"]] == [
        "superseded",
        "abandoned",
        "kept",
    ]
    assert selected["successor"]["choice_id"] == current.sha256
    assert (
        selected["supersession_reason"]["source"]["event_sha256"]
        == replacement["proposal_sha256"]
    )
    assert withdrawn_branch["choice_id"] == branch["proposal_sha256"]
    assert successor["plan_source"]["event_sha256"] == replacement["proposal_sha256"]
    assert successor["author_confirmation"]["author_id"] == "author.owner"
    assert (
        withdrawn_branch["author_confirmation"]["source"]["event_sha256"]
        == withdrawn["withdrawal_sha256"]
    )
    assert view["current_choice_ids"] == [current.sha256]
    assert view["history_head_sha256"] == _events(root)[-1]["event_sha256"]
    assert trail(root, at_sequence=2)["current_choice_ids"] == [initial.sha256]
    summary = trail_summary(root)
    assert summary["current_choices"][0]["choice_id"] == current.sha256
    assert {row["choice_id"] for row in summary["abandoned_routes"]} == {
        initial.sha256,
        branch["proposal_sha256"],
    }
    third_proposal = propose(
        root,
        plan("resource_evaluation"),
        expected_sha256=current.sha256,
        reason="The resource evaluation route now fits the recorded contribution",
    )
    third = approve(
        root,
        proposal_sha256=third_proposal["proposal_sha256"],
        author_id="author.owner",
    )
    twice = trail(root)
    former_successor = next(
        row for row in twice["choices"] if row["choice_id"] == current.sha256
    )
    assert (
        former_successor["change_reason"]["source"]["event_sha256"]
        == replacement["proposal_sha256"]
    )
    assert (
        former_successor["supersession_reason"]["source"]["event_sha256"]
        == third_proposal["proposal_sha256"]
    )
    assert former_successor["successor"]["choice_id"] == third.sha256


def test_withdrawal_requires_exact_author_assertion_and_fails_stale(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    register(root)
    initial = select(root, plan())
    branch = propose(
        root, plan("theory"), expected_sha256=initial.sha256, reason="Review route"
    )
    with pytest.raises(NarrativeError) as stale:
        withdraw(
            root, proposal_sha256="f" * 64, author_id="author.owner", reason="Withdraw"
        )
    assert stale.value.code == "stale_proposal"
    withdraw(
        root,
        proposal_sha256=branch["proposal_sha256"],
        author_id="author.owner",
        reason="Withdraw",
    )
    with pytest.raises(NarrativeError) as repeated:
        withdraw(
            root,
            proposal_sha256=branch["proposal_sha256"],
            author_id="author.owner",
            reason="Withdraw",
        )
    assert repeated.value.code == "stale_proposal"
    assert trail(root)["current_choice_ids"] == [initial.sha256]


def test_full_history_is_validated_before_old_view_and_stale_head_fails(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    register(root)
    select(root, plan())
    original = trail(root)
    with pytest.raises(NarrativeError) as stale:
        trail(root, expected_head_sha256="f" * 64)
    assert stale.value.code == "stale_narrative"
    with pytest.raises(NarrativeError) as invalid:
        trail(root, at_sequence=0)
    assert invalid.value.code == "invalid_sequence"
    path = root / ".arw/narrative/events.jsonl"
    path.write_bytes(path.read_bytes().replace(b"method_rq", b"theory"))
    with pytest.raises(NarrativeError) as corrupt:
        trail(root, at_sequence=1)
    assert corrupt.value.code == "corrupt_history"
    assert original["view_sequence"] == 2


def test_nonpaper_project_is_not_applicable_without_state_creation(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    before = list((root / ".arw").iterdir())
    assert trail(root)["status"] == "not_applicable"
    assert list((root / ".arw").iterdir()) == before


def test_trail_does_not_recreate_missing_lock(tmp_path: Path) -> None:
    root = project(tmp_path)
    register(root)
    select(root, plan())
    lock = root / ".arw/narrative/.lock"
    lock.unlink()
    with pytest.raises(NarrativeError) as missing:
        trail(root)
    assert missing.value.code == "corrupt_history"
    assert not lock.exists()


def test_explicit_run_relations_are_source_bound_and_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project(tmp_path)
    register(root)
    selected = select(root, plan())
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))

    def event(sequence: int, kind: str, payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            sequence=sequence,
            event_type=kind,
            event_id=f"evt-00000000-0000-4000-8000-{sequence:012d}",
            event_sha256=f"{sequence:064x}",
            payload=payload,
        )

    events = [
        event(
            1,
            "research_artifact_accepted",
            SimpleNamespace(
                artifact_id="artifact.figure",
                artifact_sha256="a" * 64,
                source_event_sha256=["b" * 64],
                supersedes=None,
            ),
        ),
        event(
            2,
            "research_artifact_superseded",
            SimpleNamespace(
                artifact_id="artifact.second", supersedes="artifact.figure"
            ),
        ),
        event(
            3,
            "research_memory_superseded",
            SimpleNamespace(
                memory_id="memory.first", successor_memory_id="memory.second"
            ),
        ),
    ]
    monkeypatch.setattr(
        "arw.kernel.ledger.journal.replay_run",
        lambda _: SimpleNamespace(
            run_id="run-00000000-0000-4000-8000-000000000001",
            recovery_health="healthy",
            events=events,
        ),
    )
    view = trail(root, run_root=run)
    relations = view["run_relations"]
    assert relations["initial_narrative_sha256"] == selected.sha256
    assert relations["relation_scope"] == "explicit_run_journal_only"
    assert relations["accepted_artifacts"][0]["artifact_id"] == "artifact.figure"
    assert relations["accepted_artifacts"][0]["source"]["event_sha256"] == f"{1:064x}"
    assert (
        relations["artifact_successors"][0]["successor_artifact_id"]
        == "artifact.second"
    )
    assert relations["memory_successors"][0]["successor_memory_id"] == "memory.second"
    assert "run_relations" not in trail(root)
    with pytest.raises(NarrativeError) as historical:
        trail(root, at_sequence=2, run_root=run)
    assert historical.value.code == "invalid_sequence"


def test_cli_trail_and_withdrawal_contract(tmp_path: Path) -> None:
    root = project(tmp_path)
    register(root)
    initial = select(root, plan())
    branch = propose(
        root, plan("theory"), expected_sha256=initial.sha256, reason="Test route"
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
    }
    base = [sys.executable, "-m", "arw.cli", "narrative"]
    denied = subprocess.run(
        [
            *base,
            "withdraw",
            "--project-root",
            str(root),
            "--proposal-sha256",
            branch["proposal_sha256"],
            "--author-id",
            "author.owner",
            "--reason",
            "Withdraw",
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert denied.returncode == 65
    assert json.loads(denied.stdout)["code"] == "author_confirmation_missing"
    accepted = subprocess.run(
        [
            *base,
            "withdraw",
            "--project-root",
            str(root),
            "--proposal-sha256",
            branch["proposal_sha256"],
            "--author-id",
            "author.owner",
            "--reason",
            "Withdraw",
            "--author-confirmed",
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
    exported = subprocess.run(
        [*base, "trail", "--project-root", str(root), "--json"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["choices"][-1]["disposition"] == "abandoned"


def _long_history(root: Path, versions: int):
    snapshot = select(root, plan("method_rq"))
    routes = ("observation_mechanism", "method_rq")
    for index in range(1, versions):
        proposal = propose(
            root,
            plan(routes[index % 2]),
            expected_sha256=snapshot.sha256,
            reason=f"Recorded change number {index}",
        )
        snapshot = approve(
            root, proposal_sha256=proposal["proposal_sha256"], author_id="author.owner"
        )
    return snapshot


def test_long_history_keeps_explicit_export_limit_but_bounded_summary(
    tmp_path: Path,
) -> None:
    root = project(tmp_path)
    register(root)
    current = _long_history(root, 40)
    with pytest.raises(NarrativeError) as limited:
        trail(root)
    assert limited.value.code == "trail_limit_exceeded"
    summary = trail_summary(root)
    assert summary["current_choices"][0]["choice_id"] == current.sha256
    assert len(summary["abandoned_routes"]) == 8
    assert summary["omitted_abandoned_route_count"] == 39 - 8
    sequences = [row["plan_source"]["sequence"] for row in summary["abandoned_routes"]]
    assert sequences == sorted(sequences)
    assert len(canonical_json_bytes(summary)) <= 65_536
    assert canonical_json_bytes(summary) == canonical_json_bytes(trail_summary(root))


def test_long_history_does_not_block_paper_handoff_or_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arw_research_memory.service import ResearchMemoryService

    from arw.kernel.state.research_memory import MemoryQuery

    root = project(tmp_path)
    register(root)
    first = select(root, plan())
    run = root / "runs/one"
    initialize_run(run, run_request(root, binding=binding_for_start(root, run)))
    snapshot = first
    for index in range(1, 40):
        proposal = propose(
            root,
            plan(("observation_mechanism", "method_rq")[index % 2]),
            expected_sha256=snapshot.sha256,
            reason=f"Recorded change number {index}",
        )
        snapshot = approve(
            root, proposal_sha256=proposal["proposal_sha256"], author_id="author.owner"
        )
    service = ResearchMemoryService(root, run_root=run)
    monkeypatch.setattr(service, "_save_bound", lambda value, request: {"saved": True})
    monkeypatch.setattr(
        service,
        "_resume_handoff_bound",
        lambda memory_id, query, snapshot: {
            "narrative_sha256": snapshot.sha256,
            "memory_id": memory_id,
        },
    )
    value = SimpleNamespace(handoff=SimpleNamespace(narrative_sha256=snapshot.sha256))
    saved = service.save(value, request=None)
    assert saved["narrative_trail"]["omitted_abandoned_route_count"] == 31
    resumed = service.resume_handoff("memory.one", query=MemoryQuery(max_tokens=16384))
    assert resumed["narrative_trail"] == saved["narrative_trail"]
    # A tight continuation budget drops only the optional trail context.
    narrative_only = len(
        canonical_json_bytes(
            {
                "narrative_sha256": snapshot.sha256,
                "memory_id": "memory.one",
                "narrative": snapshot.model_dump(mode="json"),
                "narrative_trail": {
                    "status": "omitted",
                    "reason": "continuation_budget",
                    "history_head_sha256": saved["narrative_trail"]["history_head_sha256"],
                },
            }
        )
    )
    tight = service.resume_handoff(
        "memory.one", query=MemoryQuery(max_tokens=narrative_only)
    )
    assert tight["narrative_trail"]["status"] == "omitted"


def test_operational_readers_restore_a_missing_lock(tmp_path: Path) -> None:
    from arw.kernel.ledger.narrative import current, status

    root = project(tmp_path)
    register(root)
    selected = select(root, plan())
    lock = root / ".arw/narrative/.lock"
    lock.unlink()
    assert status(root)["current"]["sha256"] == selected.sha256
    assert lock.is_file()
    lock.unlink()
    assert current(root).sha256 == selected.sha256
    assert lock.is_file()
    lock.unlink()
    assert trail_summary(root)["current_choices"][0]["choice_id"] == selected.sha256
    assert lock.is_file()


def test_run_relations_reject_a_symlinked_run_path(tmp_path: Path) -> None:
    root = project(tmp_path)
    register(root)
    select(root, plan())
    outside = tmp_path / "outside-run"
    outside.mkdir()
    (root / "runs").mkdir()
    (root / "runs/link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(NarrativeError) as escaped:
        trail(root, run_root=root / "runs/link")
    assert escaped.value.code == "project_run_mismatch"
