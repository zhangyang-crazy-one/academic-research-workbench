from __future__ import annotations

import copy
import json

import pytest

from arw.evidence_revision import EvidenceUpdate, impact_checklist
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from evals.evidence_revision.pilot import DEFAULT_FIXTURE, run_pilot, score


@pytest.fixture
def fixture():
    return json.loads(DEFAULT_FIXTURE.read_text())


def store_for(tmp_path, fixture):
    records = [
        dict(r, source_digest=sha256_hex(canonical_json_bytes(r)))
        for r in fixture["records"]
    ]
    store = GraphStore(tmp_path / "graph", "revision-pilot")
    store.build(
        project_canonical_records(
            records, ledger_watermark=1, ledger_head_sha256="a" * 64
        )
    )
    return store


def execute(store, case, **kwargs):
    return impact_checklist(
        store,
        EvidenceUpdate.model_validate(case["update"]),
        expected_watermark=kwargs.pop("expected_watermark", 1),
        proposed_text=case["proposed_text"],
        **kwargs,
    )


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_two_rounds_and_honest_costs(tmp_path, fixture):
    original = copy.deepcopy(fixture)
    result = run_pilot(fixture, tmp_path)
    assert result["status"] == "passed"
    assert fixture == original
    assert result["totals"] == {
        "required_revisions": 17,
        "missed_required_revisions": 0,
        "false_revisions": 0,
        "stale_candidate_errors": 0,
        "accepted_stale_items_pending_review": 17,
    }
    assert result["costs"]["graph_queries"] > 0
    assert result["costs"]["graph_response_bytes"] > 0
    assert result["costs"]["model_calls"] == 0
    assert result["costs"]["model_input_tokens"] == 0
    assert result["costs"]["external_retrieval_calls"] == 0
    assert (
        sum(
            c["previous_round_stale_candidate_errors"]
            for c in result["rounds"][1]["checks"]
        )
        == 9
    )


def test_directed_trace_preserves_sibling_and_all_files(tmp_path, fixture):
    store = store_for(tmp_path, fixture)
    before = snapshot(tmp_path)
    case = fixture["rounds"][0]["updates"][0]
    case["proposed_text"]["claim-unrelated"] = "Unsafe unrelated change"
    result = execute(store, case)
    assert snapshot(tmp_path) == before
    assert {r["kind"] for r in result["candidates"]} == {
        "claim",
        "plan",
        "experiment",
        "paragraph",
    }
    assert result["unapplied_proposals"] == ["claim-unrelated"]
    assert "claim-unrelated" not in {r["record_id"] for r in result["candidates"]}
    assert all(
        r["supersedes"] and r["decision_trace"]["path"] for r in result["candidates"]
    )


def test_irrelevant_is_not_an_override_for_real_dependencies(tmp_path, fixture):
    case = fixture["rounds"][0]["updates"][0]
    case["update"]["relation"] = "irrelevant"
    result = execute(store_for(tmp_path, fixture), case)
    assert len(result["candidates"]) == 4


def test_withdrawal_declared_record_and_no_false_verdict(tmp_path, fixture):
    result = execute(store_for(tmp_path, fixture), fixture["rounds"][1]["updates"][0])
    assert len(result["candidates"]) == 5
    declared = next(
        c for c in result["candidates"] if c["record_id"] == "artifact-declared"
    )
    assert declared["decision_trace"]["path"][0] == "declared:affected_records"
    assert "does not prove" in declared["action"]
    assert all(c["status"] == "review_required_not_false" for c in result["candidates"])


@pytest.mark.parametrize("failure", ["stale", "missing", "corrupt", "budget"])
def test_incomplete_never_becomes_empty_success(tmp_path, fixture, failure):
    store = store_for(tmp_path, fixture)
    case = fixture["rounds"][0]["updates"][0]
    kwargs = {}
    if failure == "stale":
        kwargs["expected_watermark"] = 2
    elif failure == "missing":
        case["update"]["affected_records"] = ["claim-missing"]
    elif failure == "corrupt":
        selected = store.selected_generation()
        selected.database_path.write_bytes(b"not a database")
    else:
        kwargs["max_records"] = 2
    result = execute(store, case, **kwargs)
    assert result["status"] == "incomplete"
    assert result["blockers"]
    assert not result["accepted_outputs_modified"]


def test_supersedes_is_review_link_not_admission(tmp_path, fixture):
    old = next(r for r in fixture["records"] if r["entity_id"] == "claim-alpha")
    old["supersession_state"] = "superseded"
    fixture["records"].append(
        {
            "entity_id": "claim-alpha-new",
            "entity_type": "Claim",
            "payload": {"text": "Already admitted new revision"},
            "edges": [{"edge_type": "supersedes", "to_entity_id": "claim-alpha"}],
        }
    )
    result = execute(store_for(tmp_path, fixture), fixture["rounds"][0]["updates"][0])
    ids = {c["record_id"] for c in result["candidates"]}
    assert "claim-alpha-new" in ids
    assert "claim-alpha" not in ids


def test_cycle_terminates(tmp_path, fixture):
    claim = next(r for r in fixture["records"] if r["entity_id"] == "claim-alpha")
    claim["edges"].append(
        {"edge_type": "derived_from", "to_entity_id": "artifact-paragraph-alpha"}
    )
    result = execute(store_for(tmp_path, fixture), fixture["rounds"][0]["updates"][0])
    assert result["status"] == "review_required"
    assert len(result["candidates"]) == 4


def test_scorer_detects_missing_false_and_stale_revisions(tmp_path, fixture):
    case = fixture["rounds"][0]["updates"][0]
    result = execute(store_for(tmp_path, fixture), case)
    result["candidates"].pop()
    result["candidates"][0]["proposed_text"] = "outdated"
    result["candidates"].append(
        {"record_id": "claim-unrelated", "proposed_text": "wrong"}
    )
    scores = score(result, case["labels"])
    assert scores["missed_required_revisions"] == 1
    assert scores["false_revisions"] == 1
    assert scores["stale_candidate_errors"] == 2


def test_missing_dependency_is_measured_not_hidden(tmp_path, fixture):
    next(r for r in fixture["records"] if r["entity_id"] == "claim-alpha")["edges"] = []
    result = run_pilot(fixture, tmp_path)
    assert result["status"] == "failed"
    assert result["totals"]["missed_required_revisions"] == 8


def test_generation_switch_is_incomplete(tmp_path, fixture, monkeypatch):
    store = store_for(tmp_path, fixture)
    query = store.query
    calls = 0

    def changing(request):
        nonlocal calls
        calls += 1
        result = query(request)
        if calls == 2:
            return result.model_copy(
                update={"projection_generation_id": "changed-generation"}
            )
        return result

    monkeypatch.setattr(store, "query", changing)
    result = execute(store, fixture["rounds"][0]["updates"][0])
    assert result["status"] == "incomplete"
    assert result["blockers"] == ["projection_changed_during_review"]


def test_runner_retains_report_and_refuses_overwrite(tmp_path, monkeypatch):
    from evals.evidence_revision.pilot import main

    output = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["pilot", "--output", str(output)])
    assert main() == 0
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == before


def test_runner_exits_nonzero_for_measured_failure(tmp_path, fixture, monkeypatch):
    from evals.evidence_revision.pilot import main

    next(r for r in fixture["records"] if r["entity_id"] == "claim-alpha")["edges"] = []
    source = tmp_path / "broken.json"
    source.write_text(json.dumps(fixture))
    output = tmp_path / "failed-report.json"
    monkeypatch.setattr(
        "sys.argv", ["pilot", "--fixture", str(source), "--output", str(output)]
    )
    assert main() == 1
    assert json.loads(output.read_text())["status"] == "failed"


def test_routing_and_scores_repeat_across_disposable_generations(tmp_path, fixture):
    first = run_pilot(fixture, tmp_path / "first")
    second = run_pilot(fixture, tmp_path / "second")
    for report in (first, second):
        for round_ in report["rounds"]:
            for check in round_["checks"]:
                check["checklist"].pop("projection_generation_id")
                check["checklist"].pop("projection_manifest_sha256")
    assert first == second


@pytest.mark.parametrize("role", [[], {}, None, "unknown", "claim", 42])
def test_invalid_artifact_roles_are_incomplete(tmp_path, fixture, role):
    record = next(
        r for r in fixture["records"] if r["entity_id"] == "artifact-plan-alpha"
    )
    record["payload"]["revision_kind"] = role
    result = execute(store_for(tmp_path, fixture), fixture["rounds"][0]["updates"][0])
    assert result["status"] == "incomplete"
    assert result["blockers"] == ["unsupported_artifact_revision_kind"]
    assert "artifact-plan-alpha" not in {r["record_id"] for r in result["candidates"]}


@pytest.mark.parametrize("text", [[], {}, None, 42, "", " "])
@pytest.mark.parametrize("field", ["original", "proposed"])
def test_invalid_candidate_text_is_not_emitted(tmp_path, fixture, text, field):
    case = fixture["rounds"][0]["updates"][0]
    if field == "original":
        record = next(r for r in fixture["records"] if r["entity_id"] == "claim-alpha")
        record["payload"]["text"] = text
    else:
        case["proposed_text"]["claim-alpha"] = text
    result = execute(store_for(tmp_path, fixture), case)
    assert result["status"] == "incomplete"
    assert result["blockers"] == [f"invalid_{field}_text"]
    assert "claim-alpha" not in {r["record_id"] for r in result["candidates"]}


@pytest.mark.parametrize("attributes", [[], None, "bad"])
def test_invalid_trace_attributes_are_incomplete(
    tmp_path, fixture, monkeypatch, attributes
):
    store = store_for(tmp_path, fixture)
    query = store.query

    def malformed(request):
        result = query(request)
        result.rows[0]["attributes"] = attributes
        return result

    monkeypatch.setattr(store, "query", malformed)
    result = execute(store, fixture["rounds"][0]["updates"][0])
    assert result["status"] == "incomplete"
    assert result["blockers"] == ["invalid_record_attributes"]
    assert result["candidates"] == []
