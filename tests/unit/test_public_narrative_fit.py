"""Synthetic integrity tests for explicitly unbound public venue fit."""

import base64
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from arw_writing.narrative_fit import NarrativeFitError, freeze, freshness, report

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import initialize_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.narrative_fit import FitSnapshot, PublicFitSnapshot

from .test_narrative import _accept_paper_artifact, project, run_request
from .test_narrative_fit import _profile


def _public(tmp_path, pdf_raw=None):
    root = project(tmp_path)
    request = run_request(root).model_copy(
        update={
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
        }
    )
    run = root / "runs/one"
    initialize_run(run, request)
    capsule = {
        "schema_version": "arw.venue-source-capsule.v2",
        "title": "Synthetic integrity fixture",
        "official_url": "https://example.test/paper",
        "accepted_category": "synthetic",
        "accepted_year": 2026,
        "provenance": {
            "pdf_sha256": sha256_hex(pdf_raw) if pdf_raw else "b" * 64,
            "pdf_url": "https://example.test/paper.pdf",
            "pdf_byte_count": 123,
            "pdf_page_count": 3,
            "extractor": "synthetic.fixture",
            "reviewer": "synthetic.fixture",
            "read_scope": ["synthetic"],
            "limitations": ["synthetic test provenance, no actual PDF"],
        },
        "structural_summary": ["Limitations appears in synthetic capsule prose."],
        "sections": [
            {"function": function, "status": "unknown", "unknown_reason": "synthetic"}
            for function in (
                "problem",
                "gap",
                "contribution",
                "argument",
                "evidence",
                "knowledge_boundary",
            )
        ],
    }
    (run / "capsule.json").write_bytes(canonical_json_bytes(capsule))
    assert _accept_paper_artifact(
        run, "source.public", "capsule.json", 9801, kind="learning-evidence"
    ).accepted
    return run, _profile(tmp_path / "public-profile.json")


def test_public_capsule_unknown_replay_and_read_only(tmp_path):
    run, profile = _public(tmp_path)
    before = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    with pytest.raises(NarrativeFitError, match="paper run narrative binding"):
        freeze(run, "venue.synthetic", "source.public", profile)
    snapshot = freeze(
        run,
        "venue.synthetic",
        "source.public",
        profile,
        without_selected_narrative=True,
    )
    assert isinstance(snapshot, PublicFitSnapshot)
    value = report(snapshot)
    binding = value["input_binding"]
    assert binding["retained_source_capsule_sha256"] == sha256_hex(
        (run / "capsule.json").read_bytes()
    )
    assert binding["external_reviewed_pdf_sha256"] == "b" * 64
    assert binding["manuscript_source_sha256"] is None
    assert binding["narrative_sha256"] is None
    assert binding["selected_narrative_status"] == "not_selected"
    assert [r["assessment"]["status"] for r in value["official_hard_requirements"]] == [
        "not_evaluated",
        "not_evaluated",
        "unknown",
    ]
    assert (
        value["structural_expectations"]["narrative_realization"]["mechanical_status"]
        == "UNKNOWN"
    )
    assert value["empirical_status"] == "not_evaluated"
    assert value["empirical_patterns"] == []
    encoded = canonical_json_bytes(snapshot.model_dump(mode="json"))
    assert canonical_json_bytes(
        report(PublicFitSnapshot.model_validate_json(encoded))
    ) == canonical_json_bytes(value)
    with pytest.raises(ValidationError):
        FitSnapshot.model_validate_json(encoded)
    profile.write_text("changed", encoding="utf-8")
    assert canonical_json_bytes(report(snapshot)) == canonical_json_bytes(value)
    assert (
        freshness(run, snapshot, as_of=date(2026, 10, 2))["narrative"] == "not_selected"
    )
    assert (
        freshness(tmp_path / "missing-run", snapshot, as_of=date(2026, 9, 1))["status"]
        == "unavailable"
    )
    assert {
        p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()
    } == before
    for update in (
        {"profile_sha256": "c" * 64},
        {"input_kind": "markdown"},
        {"manuscript_artifact_id": "source.other"},
        {"run_id": "another-run"},
    ):
        with pytest.raises(NarrativeFitError):
            report(snapshot.model_copy(update=update))
    proof = snapshot.manuscript.model_copy(
        update={"content_base64": base64.b64encode(b"changed").decode()}
    )
    with pytest.raises(NarrativeFitError):
        report(snapshot.model_copy(update={"manuscript": proof}))


def test_public_cli_and_explicit_options(tmp_path, capsys):
    from arw.cli import main

    run, profile = _public(tmp_path)
    invalid_options: tuple[dict[str, Any], ...] = (
        {},
        {"heuristic_ids": ("heuristic.test",)},
        {"realization_path": Path("fake.json")},
    )
    for options in invalid_options:
        with pytest.raises(NarrativeFitError):
            freeze(
                run,
                "venue.synthetic",
                None if not options else "source.public",
                profile,
                without_selected_narrative=True,
                **options,
            )
    frozen = tmp_path / "public-snapshot.json"
    assert (
        main(
            [
                "writing",
                "narrative-fit",
                "--run-root",
                str(run),
                "--target",
                "venue.synthetic",
                "--without-selected-narrative",
                "--manuscript-artifact-id",
                "source.public",
                "--profile",
                str(profile),
                "--snapshot-out",
                str(frozen),
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    assert (
        main(
            [
                "writing",
                "narrative-fit",
                "--target",
                "venue.synthetic",
                "--snapshot",
                str(frozen),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == captured


def test_public_manifest_cross_run_rebinding_rejected(tmp_path):
    import json

    from arw_writing.narrative_fit import _event_digest
    from arw.kernel.state.models import ArtifactManifest

    run, profile = _public(tmp_path)
    snapshot = freeze(
        run,
        "venue.synthetic",
        "source.public",
        profile,
        without_selected_narrative=True,
    )
    assert isinstance(snapshot, PublicFitSnapshot)
    proof = snapshot.manuscript
    manifest = json.loads(base64.b64decode(proof.manifest_base64))
    manifest["run_id"] = "run-00000000-0000-4000-8000-000000000002"
    encoded = canonical_json_bytes(
        ArtifactManifest.model_validate(manifest).model_dump(mode="json")
    )
    payload = proof.event.payload.model_copy(
        update={"manifest_sha256": sha256_hex(encoded)}
    )
    event = proof.event.model_copy(update={"payload": payload})
    event = event.model_copy(update={"event_sha256": _event_digest(event)})
    altered = proof.model_copy(
        update={"event": event, "manifest_base64": base64.b64encode(encoded).decode()}
    )
    with pytest.raises(NarrativeFitError, match="manifest binding differs"):
        report(snapshot.model_copy(update={"manuscript": altered}))


def test_public_capsule_actual_pdf_count_and_tamper(tmp_path):
    import io

    from pypdf import PdfWriter
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.state.models import ArtifactAcceptanceRequest

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    pdf_raw = output.getvalue()
    run, profile = _public(tmp_path, pdf_raw)
    (run / "actual.pdf").write_bytes(pdf_raw)
    state = replay_run(run)
    outcome = RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": state.run_id,
                "event_id": "evt-00000000-0000-4000-8000-000000009802",
                "command_id": "cmd-00000000-0000-4000-8000-000000009802",
                "expected_revision": state.revision,
                "occurred_at": "2026-07-13T00:01:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "artifact_id": "public.pdf",
                "artifact_kind": "learning-evidence",
                "media_type": "application/pdf",
                "content_path": "actual.pdf",
                "content_sha256": sha256_hex(pdf_raw),
                "base_revision": state.revision,
                "consumed_sha256": [state.last_event_sha256],
            }
        )
    )
    assert outcome.accepted
    snapshot = freeze(
        run,
        "venue.synthetic",
        "source.public",
        profile,
        without_selected_narrative=True,
        pdf_artifact_id="public.pdf",
    )
    assert report(snapshot)["official_hard_requirements"][1]["assessment"] == {
        "status": "met",
        "observed_page_count": 1,
    }
    with pytest.raises(NarrativeFitError, match="actual public PDF differs"):
        report(snapshot.model_copy(update={"pdf_page_count": 3}))
    empty_profile = _profile(tmp_path / "empty-profile.json")
    import json

    value = json.loads(empty_profile.read_bytes())
    value["official_hard_requirements"] = []
    empty_profile.write_bytes(canonical_json_bytes(value))
    result = report(
        freeze(
            run,
            "venue.synthetic",
            "source.public",
            empty_profile,
            without_selected_narrative=True,
        )
    )
    assert result["input_binding"]["official_requirements_status"] == "not_evaluated"
    assert "official_profile_requirements_not_supplied" in result["limits"]


def test_public_mode_cannot_replace_selected_author_narrative(tmp_path):
    from . import test_narrative_realization

    run = getattr(test_narrative_realization.paper, "__wrapped__")(tmp_path)
    profile = _profile(tmp_path / "bound-profile.json")
    with pytest.raises(NarrativeFitError, match="selected narrative fit path"):
        freeze(
            run,
            "venue.synthetic",
            "source.public",
            profile,
            without_selected_narrative=True,
        )
