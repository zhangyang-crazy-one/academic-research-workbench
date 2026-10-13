"""Advisory-only diagnostics, exact targets and original RO-Crate packaging."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from arw.kernel.artifacts.ro_crate import export_ro_crate, verify_ro_crate
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.review_concerns import (
    diagnose,
    export_prov,
    replay_report,
    validate_concern,
    validate_prov,
)
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.kernel.state.review_concern import (
    ClaimRevisionTarget,
    ReviewConcern,
    review_concern_schema_documents,
)
from tests.unit.test_claim_graph import record, registration, setup
from tests.unit.test_ro_crate_export import _complete_run


def prepared(tmp_path):
    project, run = setup(tmp_path)
    view = claim_graph.graph(project, run_roots=(run,))
    record(project, run, registration(view))
    return project, run


def test_diagnostics_do_not_change_hard_checks_or_canonical_files(tmp_path, capsys):
    from arw.cli import main

    project, run = prepared(tmp_path)
    before = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    source = (project / ".arw/narrative/events.jsonl").read_bytes()
    parent = (run / "journal/segments/00000001.jsonl").read_bytes()
    report = diagnose(project, (run,))
    assert report.concerns and all(
        c.advisory and c.argumentative_zone is None for c in report.concerns
    )
    assert not any("score" in c.model_dump() for c in report.concerns)
    assert canonical_json_bytes(report.model_dump(mode="json")) == canonical_json_bytes(
        diagnose(project, (run,)).model_dump(mode="json")
    )
    assert (
        before["hard_checks"]
        == claim_graph.graph(project, run_roots=(run,), hard_check=True)["hard_checks"]
    )
    assert (project / ".arw/narrative/events.jsonl").read_bytes() == source
    assert (run / "journal/segments/00000001.jsonl").read_bytes() == parent
    saved = project / "concerns.json"
    saved.write_bytes(
        canonical_json_bytes(
            {**report.model_dump(mode="json"), "report_sha256": report.sha256}
        )
    )
    assert (
        main(
            [
                "review",
                "replay",
                "--project-root",
                str(project),
                "--run-root",
                str(run),
                "--input",
                str(saved),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["report_sha256"] == report.sha256


def test_exact_claim_and_occurrence_targets_and_optional_zone(tmp_path):
    project, run = prepared(tmp_path)
    report = diagnose(project, (run,))
    claim = next(
        c for c in report.concerns if isinstance(c.target, ClaimRevisionTarget)
    )
    occurrence = next(
        c for c in report.concerns if not isinstance(c.target, ClaimRevisionTarget)
    )
    zoned = claim.model_copy(update={"argumentative_zone": "AIM"})
    assert validate_concern(zoned, project, (run,)).argumentative_zone == "AIM"
    bad = claim.model_copy(
        update={"target": claim.target.model_copy(update={"claim_sha256": "f" * 64})}
    )
    with pytest.raises(ValueError):
        validate_concern(bad, project, (run,))
    altered = occurrence.model_copy(
        update={
            "target": occurrence.target.model_copy(
                update={
                    "occurrence": occurrence.target.occurrence.model_copy(
                        update={"selected_sha256": "f" * 64}
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError):
        validate_concern(altered, project, (run,))
    dumped = claim.model_dump(mode="json")
    dumped["score"] = 0.9
    with pytest.raises(ValueError):
        ReviewConcern.model_validate_json(canonical_json_bytes(dumped))
    (run / "draft.txt").write_text("Changed manuscript")
    with pytest.raises(ValueError):
        replay_report(report, project, (run,))


def test_prov_links_deterministic_parent_admission_and_ro_crate(tmp_path):
    project, source_run = prepared(tmp_path / "paper")
    report = diagnose(project, (source_run,))
    prov = export_prov(report, project, (source_run,))
    assert canonical_json_bytes(prov) == canonical_json_bytes(
        export_prov(report, project, (source_run,))
    )
    assert validate_prov(prov)
    broken = json.loads(json.dumps(prov))
    broken["@graph"][0]["prov:used"] = {"@id": "#missing"}
    with pytest.raises(ValueError):
        validate_prov(broken)
    # Original exporter and verifier, with owner-backed base metadata. This
    # exercises interoperability without claiming a full real execution canary.
    run = _complete_run(tmp_path / "crate")
    original = tmp_path / "original.zip"
    export_ro_crate(run, original)
    original_bytes = original.read_bytes()
    original_sha = sha256_hex(original_bytes)
    raw = canonical_json_bytes(prov)
    (run / "claims-prov.jsonld").write_bytes(raw)
    replay = replay_run(run)
    request = ArtifactAcceptanceRequest(
        schema_version="1.0.0",
        run_id=replay.run_id,
        event_id=f"evt-{uuid4()}",
        command_id=f"cmd-{uuid4()}",
        expected_revision=replay.revision,
        occurred_at="2026-07-20T00:01:00Z",
        actor_id="parent.runtime",
        actor_role="parent_control_plane",
        artifact_id="artifact.claims-prov",
        artifact_kind="claims-prov",
        media_type="application/ld+json",
        content_path="claims-prov.jsonld",
        content_sha256=sha256_hex(raw),
        base_revision=replay.revision,
        consumed_sha256=[],
    )
    outcome = RuntimeCommandService(run).accept_artifact(request)
    assert outcome.accepted, outcome
    destination = tmp_path / "with-prov.zip"
    export_ro_crate(run, destination, include_artifact_ids=("artifact.claims-prov",))
    checks = verify_ro_crate(destination, run_root=run)
    for key in ("structure", "byte_integrity", "source_run_binding", "base_profile"):
        assert checks[key]["status"] == "pass", checks
    assert (
        original.read_bytes() == original_bytes
        and sha256_hex(original.read_bytes()) == original_sha
    )
    import zipfile

    with zipfile.ZipFile(destination) as crate:
        assert raw in [crate.read(name) for name in crate.namelist()]
    assert verify_ro_crate(original)["structure"]["status"] == "pass"


def test_schema_drift():
    root = Path(__file__).resolve().parents[2]
    for name, document in review_concern_schema_documents().items():
        assert json.loads((root / "schemas/v1" / name).read_text()) == document


def test_large_manuscript_reports_explicit_omissions_and_replays(tmp_path):
    from arw.kernel.ledger import narrative
    from tests.integration.test_precise_source_locators import accept, seed
    from tests.unit.test_narrative import plan, project

    p = project(tmp_path)
    narrative.register(p)
    narrative.select(p, plan())
    run, _ = seed(p)
    (run / "draft.txt").write_text(" ".join(str(i) for i in range(1050)))
    assert accept(run, "artifact.draft", "draft.txt", 40, kind="manuscript").accepted
    report = diagnose(p, (run,))
    assert len(report.concerns) == 1000
    assert report.omitted_concern_count == 50
    assert replay_report(report, p, (run,)) == report
    assert report.sha256 == diagnose(p, (run,)).sha256
    assert len(canonical_json_bytes(report.model_dump(mode="json"))) <= 2_097_152


@pytest.mark.parametrize("action", ["verify", "replay", "prov"])
def test_review_input_rejects_non_object_without_attribute_error(tmp_path, action):
    from argparse import Namespace

    from arw.cli_review import handle

    path = tmp_path / "input.json"
    path.write_text("[]")
    args = Namespace(
        project_root=tmp_path, run_root=[tmp_path], review_command=action, input=path
    )
    with pytest.raises(ValueError, match="JSON object"):
        handle(args)


def test_zero_omissions_preserve_original_report_bytes(tmp_path):
    from arw.kernel.state.review_concern import ReviewConcernReport

    project, run = prepared(tmp_path)
    report = diagnose(project, (run,))
    assert "omitted_concern_count" not in report.model_dump(mode="json")
    old = report.model_dump(mode="json")
    assert (
        ReviewConcernReport.model_validate_json(canonical_json_bytes(old)).sha256
        == report.sha256
    )
