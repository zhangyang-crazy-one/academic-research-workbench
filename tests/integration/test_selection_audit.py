"""Selection audit replays ARS substrate and accepted run evidence without writes."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from arw.cli import main
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.selection_audit import (
    PoolFixture,
    ReadingTrace,
    SelectionAuditError,
    _ars_builder,
    export,
    replay_fixture,
    srs_synthetic_example,
)
from tests.integration.test_artifact_sanitize import setup_run

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/selection-audit"
ARS = Path(__file__).resolve().parents[2] / "skills/academic-research-suite/ars/scripts/fixtures/claim_standing_candidate_ledger"


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _accept(root, index, name, data):
    raw = canonical_json_bytes(data)
    path = root / "audit" / f"{name}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(raw)
    state = replay_run(root)
    request = ArtifactAcceptanceRequest.model_validate({
        "schema_version": "1.0.0", "run_id": state.run_id,
        "occurred_at": "2026-08-13T02:00:00Z",
        "event_id": f"evt-00000000-0000-4000-8000-{index:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{index:012x}",
        "actor_id": "parent.runtime", "actor_role": "parent_control_plane",
        "expected_revision": state.revision, "artifact_id": f"artifact.{name}",
        "artifact_kind": "selection-audit-input", "media_type": "application/json",
        "content_path": f"audit/{name}.json", "content_sha256": sha256_hex(raw),
        "base_revision": state.revision, "consumed_sha256": [],
    })
    outcome = RuntimeCommandService(root).accept_artifact(request)
    assert outcome.accepted, outcome.rejection
    return f"artifact.{name}"


def _ars_values(tmp_path):
    builder = _ars_builder()
    plan = json.loads((ARS / "query_plan.json").read_text())
    retained = json.loads((ARS / "retrieval_input.json").read_text())
    consent = plan["consent"]
    consent["local_persistence"] = "explicit_local_export"
    consent["export_boundary"] = builder.EXPLICIT_LOCAL_EXPORT_BOUNDARY
    consent["authorized_output_path"] = str(tmp_path / "fixture-ledger.json")
    consent["consentable_plan_sha256"] = builder.digest(builder.consentable_plan_projection(plan))
    consent["receipt_sha256"] = builder.bound_digest(consent, "receipt_sha256")
    plan["plan_sha256"] = builder.bound_digest(plan, "plan_sha256")
    retained["query_plan_sha256"] = plan["plan_sha256"]
    retained["retrieval_input_sha256"] = builder.bound_digest(retained, "retrieval_input_sha256")
    ledger = builder.build_ledger(plan, retained)
    return plan, retained, ledger


def _run(tmp_path, *, trace=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root, _, _ = setup_run(tmp_path)
    plan, retained, ledger = _ars_values(tmp_path)
    plan_id = _accept(root, 200, "plan", plan)
    retrieval_id = _accept(root, 201, "retrieval", retained)
    ledger_id = _accept(root, 202, "ledger", ledger)
    trace_id = None
    if trace:
        family = next(f for f in ledger["work_families"] if f["selection_state"] == "selected")
        trace_value = ReadingTrace(
            schema_version="arw.selection-reading-trace.v1", query_plan_sha256=plan["plan_sha256"],
            candidate_ledger_sha256=ledger["candidate_ledger_sha256"],
            readings=[{"round": 1, "order": 1, "work_family_id": family["work_family_id"],
                       "raw_hit_id": family["canonical_raw_hit_id"], "stance": "unknown", "stance_basis": "unknown"}],
            reached_rounds=1, stop_reason="author logged stop after one read", complete_log=True,
        )
        trace_id = _accept(root, 203, "trace", trace_value.model_dump(mode="json"))
    return root, (plan_id, retrieval_id, ledger_id, trace_id)


def _export(root, ids):
    return export(root, expected_head=replay_run(root).last_event_sha256,
                  plan_id=ids[0], retrieval_id=ids[1], ledger_id=ids[2], trace_id=ids[3])


def test_retained_export_unknown_and_no_mutation(tmp_path):
    root, ids = _run(tmp_path)
    before = _snapshot(root)
    receipt = _export(root, ids)
    assert receipt["reading_status"] == "unknown"
    assert receipt["coverage_status"] == "unknown"
    assert receipt["estimated_support_minus_oppose"] is None
    assert receipt["raw_hit_count"] == 3 and receipt["family_count"] == 2
    assert any(row["terminal_state"] == "duplicate_version" for row in receipt["raw_rank_and_dedup"])
    assert _snapshot(root) == before


def test_recorded_read_and_replay_rejects_stale_and_tamper(tmp_path, capsys):
    root, ids = _run(tmp_path, trace=True)
    receipt = _export(root, ids)
    assert receipt["reading_status"] == "recorded" and receipt["read_family_count"] == 1
    assert receipt["correction_status"] == "descriptive_only"
    path = tmp_path / "receipt.json"
    path.write_bytes(canonical_json_bytes(receipt))
    assert main(["selection-audit", "replay", "--receipt", str(path), "--run-root", str(root)]) == 0
    capsys.readouterr()
    changed = copy.deepcopy(receipt)
    changed["read_family_count"] = 2
    path.write_bytes(canonical_json_bytes(changed))
    assert main(["selection-audit", "replay", "--receipt", str(path), "--run-root", str(root)]) == 65
    capsys.readouterr()
    with pytest.raises(SelectionAuditError, match="stale"):
        export(root, expected_head="0" * 64, plan_id=ids[0], retrieval_id=ids[1], ledger_id=ids[2])
    (root / "audit/ledger.json").write_text("{}")
    with pytest.raises((ValueError, RuntimeError)):
        _export(root, ids)


def test_cross_run_and_ars_consent_fail_closed(tmp_path):
    _root, ids = _run(tmp_path / "a")
    other, _ = _run(tmp_path / "b")
    with pytest.raises(SelectionAuditError, match="not uniquely parent accepted"):
        export(other, expected_head=replay_run(other).last_event_sha256,
               plan_id=ids[0], retrieval_id=ids[1], ledger_id="artifact.foreign")
    plan, retained, ledger = _ars_values(tmp_path)
    plan["consent"]["local_persistence"] = "session_only"
    # Invalid consent binding must fail under the normative ARS replay, before export.
    with pytest.raises(ValueError):
        _ars_builder().validate_ledger(plan, retained, ledger)


def test_public_synthetic_pool_paired_ordering_and_srs(tmp_path, capsys):
    fixture_path = FIXTURES / "self-authored-pool.json"
    fixture = PoolFixture.model_validate_json(fixture_path.read_bytes())
    before = fixture_path.read_bytes()
    receipt = replay_fixture(fixture)
    assert receipt["conclusion_direction_changed"] and receipt["reading_set_changed"]
    assert receipt["duplicate_version_count"] == 1
    assert receipt["original_citation_locator_valid"]
    assert receipt["unread_opposing_family_ids"] == ["family-oppose-a", "family-oppose-b"]
    assert receipt["scenarios"]["original"]["read_family_ids"] == fixture.original_order[:2]
    assert receipt["scenarios"]["oppose_first"]["direction"] == "oppose_tilt"
    assert receipt["srs_example"]["inclusion_probability"] == 0.5
    assert srs_synthetic_example(["unknown", "support"], [0])["estimated_support_minus_oppose"] is None
    assert main(["selection-audit", "replay", "--fixture", str(fixture_path)]) == 0
    assert json.loads(capsys.readouterr().out)["receipt_sha256"] == receipt["receipt_sha256"]
    assert fixture_path.read_bytes() == before


def test_public_launcher_replays_same_fixture_without_writes():
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    path = FIXTURES / "self-authored-pool.json"
    before = path.read_bytes()
    expected = replay_fixture(PoolFixture.model_validate_json(before))
    environment = {**os.environ, "ARW_RUNTIME": "agent", "ARW_PYTHON": sys.executable}
    result = subprocess.run(
        [str(root / "bin/arw"), "selection-audit", "replay", "--fixture", str(path)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["receipt_sha256"] == expected["receipt_sha256"]
    assert path.read_bytes() == before


def test_bundled_ars_stage_resolution_and_optional_absence(tmp_path, monkeypatch):
    import shutil
    import sys

    from arw.kernel.capabilities import CapabilityUnavailable
    from arw.selection_audit import _ars_builder

    stage = tmp_path / "stage"
    script = stage / "skills/academic-research-suite/ars/scripts/build_claim_standing_candidate_ledger.py"
    script.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[2] /
                    "skills/academic-research-suite/ars/scripts/build_claim_standing_candidate_ledger.py", script)
    schema_dir = script.parent.parent / "shared/contracts/claim_standing"
    schema_dir.mkdir(parents=True)
    for schema in (Path(__file__).resolve().parents[2] /
                   "skills/academic-research-suite/ars/shared/contracts/claim_standing").glob("*.json"):
        shutil.copyfile(schema, schema_dir / schema.name)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(stage))
    before = list(sys.path)
    plan, retained, ledger = _ars_values(tmp_path)
    _ars_builder().validate_ledger(plan, retained, ledger)
    assert sys.path == before
    script.unlink()
    with pytest.raises(CapabilityUnavailable):
        _ars_builder()


def test_complete_zero_read_trace_has_zero_coverage_but_no_direction(tmp_path):
    root, ids = _run(tmp_path)
    plan = json.loads((root / "audit/plan.json").read_text())
    ledger = json.loads((root / "audit/ledger.json").read_text())
    trace = ReadingTrace(
        schema_version="arw.selection-reading-trace.v1",
        query_plan_sha256=plan["plan_sha256"],
        candidate_ledger_sha256=ledger["candidate_ledger_sha256"],
        readings=[], reached_rounds=0, stop_reason="author logged stop before reading",
        complete_log=True,
    )
    trace_id = _accept(root, 204, "zero-trace", trace.model_dump(mode="json"))
    receipt = _export(root, (*ids[:3], trace_id))
    assert receipt["coverage_status"] == "zero"
    assert receipt["read_family_count"] == 0
    assert receipt["estimated_support_minus_oppose"] is None
    assert receipt["correction_status"] == "descriptive_only"


def test_retained_trace_rejects_synthetic_stance_and_out_of_pool(tmp_path):
    root, ids = _run(tmp_path)
    plan = json.loads((root / "audit/plan.json").read_text())
    ledger = json.loads((root / "audit/ledger.json").read_text())
    family = next(f for f in ledger["work_families"] if f["selection_state"] == "selected")
    base = {"schema_version": "arw.selection-reading-trace.v1",
            "query_plan_sha256": plan["plan_sha256"],
            "candidate_ledger_sha256": ledger["candidate_ledger_sha256"],
            "reached_rounds": 1, "stop_reason": "synthetic check", "complete_log": True}
    synthetic = {**base, "readings": [{"round": 1, "order": 1,
                  "work_family_id": family["work_family_id"],
                  "raw_hit_id": family["canonical_raw_hit_id"],
                  "stance": "support", "stance_basis": "synthetic_fixture"}]}
    trace_id = _accept(root, 205, "synthetic-trace", synthetic)
    with pytest.raises(SelectionAuditError, match="synthetic fixture"):
        _export(root, (*ids[:3], trace_id))
    outside = copy.deepcopy(synthetic)
    outside["readings"][0]["work_family_id"] = "family-absent"
    outside["readings"][0]["stance"] = "unknown"
    outside["readings"][0]["stance_basis"] = "unknown"
    trace_id = _accept(root, 206, "outside-trace", outside)
    with pytest.raises(SelectionAuditError, match="outside"):
        _export(root, (*ids[:3], trace_id))


def test_synthetic_citation_locator_is_exact_and_not_sufficient(tmp_path):
    value = json.loads((FIXTURES / "self-authored-pool.json").read_text())
    value["original_citations"][0]["quote_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="citation quote"):
        PoolFixture.model_validate(value)
