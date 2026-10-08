"""Accepted writing receipts are exact, replayable narrative-fit inputs."""

from __future__ import annotations

import base64
import json
from copy import deepcopy

import pytest
from arw_writing.narrative_fit import NarrativeFitError, freeze, report
from arw_writing.service import WritingService

from arw.kernel.core.canonical import canonical_json_bytes, seal_event, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.narrative import current
from arw.kernel.state.narrative_fit import FitSnapshot
from tests.integration.test_writing import proposal as writing_proposal
from tests.unit import test_narrative_realization
from tests.unit.test_narrative import _accept_paper_artifact, _parent_request
from tests.unit.test_narrative_fit import _accepted_draft, _profile
from tests.unit.test_narrative_realization import _fixture


@pytest.fixture
def paper(tmp_path):
    return test_narrative_realization.paper.__wrapped__(tmp_path)


def _accepted_writing(paper):
    base = _fixture(paper)
    candidate = (paper / "paper.md").read_text(encoding="utf-8")
    for stage, artifact_id, number, predecessor in (
        ("outline", "outline.fit", 9701, None),
        ("blueprint", "blueprint.fit", 9702, "outline.fit"),
    ):
        value = {**base, "stage": stage}
        if predecessor is not None:
            value["predecessor_artifact_id"] = predecessor
        path = f"{stage}.json"
        (paper / path).write_bytes(canonical_json_bytes(value))
        accepted = _accept_paper_artifact(
            paper, artifact_id, path, number, kind=f"narrative-{stage}"
        )
        assert accepted.accepted, accepted.rejection
    source = "Moreover, " + candidate
    (paper / "writing-source.md").write_text(source, encoding="utf-8")
    accepted = _accept_paper_artifact(
        paper, "source.fit", "writing-source.md", 9703, kind="writing-source"
    )
    assert accepted.accepted, accepted.rejection
    proposal = writing_proposal(source, candidate)
    proposal["narrative_sha256"] = current(paper.parent.parent).sha256
    proposal["narrative_realization"] = {
        **base,
        "stage": "draft",
        "predecessor_artifact_id": "blueprint.fit",
        "source_path": f"writing/candidate/{sha256_hex(candidate.encode())}.md",
        "source_sha256": sha256_hex(candidate.encode()),
    }
    service = WritingService(paper)
    prepared = service.prepare("source.fit", proposal)
    assert prepared["controls_effective"]
    review = {
        "schema_version": "arw.writing-review.v1",
        "source_sha256": prepared["source_sha256"],
        "candidate_sha256": prepared["candidate_sha256"],
        "proposal_sha256": prepared["proposal_sha256"],
        "verification_sha256": prepared["verification_sha256"],
        "decision": "APPROVED",
        "reviewed_dimensions": prepared["verification"]["unresolved_dimensions"],
        "reviewer": "synthetic-fixture-reviewer",
        "rationale": "Synthetic test review of the exact candidate and source",
    }
    (paper / "writing-review.json").write_bytes(canonical_json_bytes(review))
    accepted = _accept_paper_artifact(
        paper,
        "review.fit",
        "writing-review.json",
        9704,
        kind="writing-human-review",
    )
    assert accepted.accepted, accepted.rejection
    outcome = service.record(
        "source.fit",
        proposal,
        request=_parent_request(paper, 9705),
        review_artifact_id="review.fit",
    )
    assert outcome["candidate_accepted"], outcome
    return outcome, candidate


def _replay(snapshot):
    frozen = canonical_json_bytes(snapshot.model_dump(mode="json"))
    return report(FitSnapshot.model_validate_json(frozen))


def test_real_writing_accept_capture_and_frozen_replay(paper, tmp_path, capsys):
    from arw.cli import main

    outcome, candidate = _accepted_writing(paper)
    venue = _profile(tmp_path / "profile.json")
    snapshot = freeze(paper, "venue.synthetic", outcome["artifact_id"], venue)
    assert snapshot.accepted_binding_kind == "writing_candidate_receipt"
    assert snapshot.writing_candidate_binding is not None
    assert (
        base64.b64decode(snapshot.accepted_content_base64)
        == (paper / outcome["bundle_path"]).read_bytes()
    )
    assert base64.b64decode(snapshot.manuscript_source_base64).decode() == candidate
    first = report(snapshot)
    assert first == _replay(snapshot)
    assert first["input_binding"]["writing_candidate_receipt"]["candidate_sha256"] == (
        sha256_hex(candidate.encode())
    )
    assert replay_run(paper).events[-1].payload.artifact_id == outcome["artifact_id"]
    sidecar = paper / "explicit-realization.json"
    sidecar.write_bytes(
        canonical_json_bytes(snapshot.realization.model_dump(mode="json"))
    )
    explicit = freeze(
        paper,
        "venue.synthetic",
        outcome["artifact_id"],
        venue,
        realization_path=sidecar.relative_to(paper),
    )
    assert explicit.accepted_binding_kind == "writing_candidate_receipt"
    assert _replay(explicit) == first
    sidecar.write_bytes(b"{}\n")
    with pytest.raises(NarrativeFitError, match="explicit realization differs"):
        freeze(
            paper,
            "venue.synthetic",
            outcome["artifact_id"],
            venue,
            realization_path=sidecar.relative_to(paper),
        )
    frozen = tmp_path / "fit-snapshot.json"
    assert (
        main(
            [
                "writing",
                "narrative-fit",
                "--run-root",
                str(paper),
                "--target",
                "venue.synthetic",
                "--manuscript-artifact-id",
                outcome["artifact_id"],
                "--profile",
                str(venue),
                "--snapshot-out",
                str(frozen),
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
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
    assert json.loads(capsys.readouterr().out) == captured == first


@pytest.mark.parametrize(
    "mutation",
    [
        "receipt",
        "candidate",
        "realization",
        "manifest",
        "source_reference",
        "source_binding",
        "run_manifest",
    ],
)
def test_frozen_writing_bindings_reject_tampering(paper, tmp_path, mutation):
    outcome, _ = _accepted_writing(paper)
    snapshot = freeze(
        paper,
        "venue.synthetic",
        outcome["artifact_id"],
        _profile(tmp_path / "profile.json"),
    )
    changed = deepcopy(snapshot.model_dump(mode="json"))
    binding = changed["writing_candidate_binding"]
    if mutation == "receipt":
        changed["accepted_content_base64"] = base64.b64encode(b"{}").decode()
    elif mutation == "candidate":
        changed["manuscript_source_base64"] = base64.b64encode(b"other").decode()
        changed["manuscript_source_sha256"] = sha256_hex(b"other")
        changed["realization"]["source_sha256"] = sha256_hex(b"other")
        changed["realization_base64"] = base64.b64encode(
            canonical_json_bytes(changed["realization"])
        ).decode()
        binding["realization_sha256"] = sha256_hex(
            canonical_json_bytes(changed["realization"])
        )
    elif mutation == "realization":
        changed["realization_base64"] = base64.b64encode(b"{}").decode()
    elif mutation == "manifest":
        binding["accepted_manifest_sha256"] = "0" * 64
    elif mutation == "source_reference":
        binding["accepted_event_id"] = "evt-00000000-0000-4000-8000-000000009703"
    elif mutation == "source_binding":
        receipt = json.loads(base64.b64decode(changed["accepted_content_base64"]))
        receipt["source_binding"]["artifact_id"] = "review.fit"
        receipt_raw = canonical_json_bytes(receipt)
        receipt_sha = sha256_hex(receipt_raw)
        changed["accepted_content_base64"] = base64.b64encode(receipt_raw).decode()
        changed["accepted_content_sha256"] = binding["receipt_sha256"] = receipt_sha
        manifest = json.loads(base64.b64decode(binding["accepted_manifest_base64"]))
        manifest["content_sha256"] = receipt_sha
        manifest_raw = canonical_json_bytes(manifest)
        manifest_sha = sha256_hex(manifest_raw)
        binding["accepted_manifest_base64"] = base64.b64encode(manifest_raw).decode()
        binding["accepted_manifest_sha256"] = manifest_sha
        event = changed["accepted_event"]
        event["payload"]["artifact_sha256"] = receipt_sha
        event["payload"]["manifest_sha256"] = manifest_sha
        changed["accepted_event"] = seal_event(event)
        changed["accepted_event_sha256"] = binding["accepted_event_sha256"] = changed[
            "accepted_event"
        ]["event_sha256"]
    else:
        binding["run_manifest_sha256"] = "0" * 64
    with pytest.raises((NarrativeFitError, ValueError)) as caught:
        _replay(FitSnapshot.model_validate_json(canonical_json_bytes(changed)))
    if mutation == "source_binding":
        assert isinstance(caught.value, NarrativeFitError)
        assert caught.value.code == "writing_receipt_invalid"
        assert "source_binding differs" in str(caught.value.__cause__)


def test_live_writing_receipt_and_candidate_tamper_block_capture(paper, tmp_path):
    outcome, _ = _accepted_writing(paper)
    venue = _profile(tmp_path / "profile.json")
    receipt_path = paper / outcome["bundle_path"]
    original = receipt_path.read_bytes()
    receipt_path.write_bytes(b"{}")
    with pytest.raises((NarrativeFitError, ValueError, RuntimeError)):
        freeze(paper, "venue.synthetic", outcome["artifact_id"], venue)
    receipt_path.write_bytes(original)
    candidate_path = (
        paper
        / freeze(
            paper, "venue.synthetic", outcome["artifact_id"], venue
        ).realization.source_path
    )
    candidate_path.write_text("changed", encoding="utf-8")
    with pytest.raises((NarrativeFitError, ValueError, RuntimeError)):
        freeze(paper, "venue.synthetic", outcome["artifact_id"], venue)


def test_historical_realization_and_manuscript_source_modes_still_replay(
    paper, tmp_path
):
    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    standalone = freeze(paper, "venue.synthetic", "draft.fit", venue)
    assert standalone.accepted_binding_kind == "realization_sidecar"
    assert "writing_candidate_binding" not in standalone.model_dump(mode="json")
    assert _replay(standalone) == report(standalone)

    accepted = _accept_paper_artifact(
        paper, "source.fit", "paper.md", 9706, kind="manuscript-source"
    )
    assert accepted.accepted, accepted.rejection
    manuscript = freeze(
        paper,
        "venue.synthetic",
        "source.fit",
        venue,
        realization_path="draft.json",
    )
    assert manuscript.accepted_binding_kind == "manuscript_source"
    assert "writing_candidate_binding" not in manuscript.model_dump(mode="json")
    assert _replay(manuscript) == report(manuscript)
