"""Citation scope and complete writing receipt budget regressions."""

from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest
from arw_writing.diagnostics import sentences
from arw_writing.preservation import (
    CITATION_BINDINGS_VERSION,
    resolve_citation_bindings,
    validate_citation_bindings,
    verify,
)
from arw_writing.service import WritingReceiptBudgetError, WritingService
from arw_writing.transformer import MAX_TEXT_BYTES, SessionWritingTransformer

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import validate_accepted_event_manifests
from arw.kernel.ledger.source_locations import MAX_SOURCE_BYTES, read_retained_bytes

from .test_precise_source_locators import accept, seed
from .test_research_artifacts import request
from .test_writing import approve, proposal


def _source_run(tmp_path, source: str):
    root, _ = seed(tmp_path)
    (root / "manuscript.txt").write_text(source, encoding="utf-8")
    assert accept(
        root, "artifact.manuscript", "manuscript.txt", 40, kind="manuscript"
    ).accepted
    return root, WritingService(root)


def _prefix_proposal(source: str):
    prefix = "Moreover, "
    candidate = source.removeprefix(prefix)
    value = proposal(source, candidate)
    value["edits"] = [
        {"start": 0, "end": len(prefix), "before": prefix, "replacement": ""}
    ]
    return value


def _bounded_fact_check(monkeypatch):
    """Keep large synthetic budget cases focused on receipt composition."""
    monkeypatch.setattr(
        "arw_writing.transformer.fact_audit",
        lambda _source, _candidate: {
            "status": "available",
            "mechanical_status": "passed",
            "semantic_status": "human_review_required",
            "report": {"passed": True, "findings": []},
        },
    )


def test_six_citations_per_long_sentence_do_not_duplicate_assertions():
    source = ("A" * 650 + " [1] [2] [3] [4] [5] [6]. ") * 1000
    candidate = source.replace("A", "B")
    assert len(source.encode("utf-8")) == 676_000
    verification = verify(source, candidate, [], [])
    bindings = verification["citation_bindings"]
    assert bindings["version"] == CITATION_BINDINGS_VERSION
    assert len(bindings["source"]["assertions"]) == 1000
    assert len(bindings["source"]["bindings"]) == 6000
    assert len(bindings["candidate"]["assertions"]) == 1000
    assert len(bindings["candidate"]["bindings"]) == 6000
    assert (
        len(
            canonical_json_bytes(
                {
                    "source": source,
                    "candidate": candidate,
                    "citation_bindings": bindings,
                }
            )
        )
        < 2_100_000
    )
    assert resolve_citation_bindings(verification, source, candidate)["source"][0] == {
        "citation": "[1]",
        "assertion": "A" * 650 + " [1] [2] [3] [4] [5] [6]",
    }


def test_multibyte_byte_scopes_and_tampering_are_detected():
    source = "前言。 研究方法 [@甲] [@乙]。 结果 [3]。"
    candidate = "前言。 研究方案 [@甲] [@乙]。 结果 [3]。"
    verification = verify(source, candidate, [], [])
    source_table = verification["citation_bindings"]["source"]
    first = source_table["assertions"][0]
    raw = source.encode("utf-8")
    assert first["offset"] == len("前言。 ".encode())
    assert raw[first["offset"] : first["offset"] + first["length"]].decode() == (
        "研究方法 [@甲] [@乙]"
    )
    assert first["sha256"] == sha256_hex(
        raw[first["offset"] : first["offset"] + first["length"]]
    )
    validate_citation_bindings(verification, source, candidate)
    for field, replacement in (
        ("offset", first["offset"] + 1),
        ("length", 1),
        ("sha256", "0" * 64),
    ):
        tampered = deepcopy(verification)
        tampered["citation_bindings"]["source"]["assertions"][0][field] = replacement
        with pytest.raises(ValueError, match="scope or digest"):
            validate_citation_bindings(tampered, source, candidate)
    tampered = deepcopy(verification)
    tampered["citation_bindings"]["source"]["bindings"][0]["assertion"] = 1
    with pytest.raises(ValueError, match="scope or digest"):
        validate_citation_bindings(tampered, source, candidate)

    legacy = resolve_citation_bindings(verification, source, candidate)
    old_verification = {"citation_bindings": legacy}
    validate_citation_bindings(old_verification, source, candidate)
    legacy["source"][0]["assertion"] = "unrelated sentence"
    with pytest.raises(ValueError, match="legacy citation scope"):
        validate_citation_bindings(old_verification, source, candidate)


def test_sentence_spans_preserve_legacy_segmentation():
    text = "  First [1].  Second [2]!\n\n研究 [3]。  3.14 remains [4]? "
    separator = r"(?<!\d)[.!?]+\s*|[。！？]+\s*|\n\s*\n"
    legacy = [part.strip() for part in re.split(separator, text) if part.strip()]
    assert sentences(text) == legacy


def test_near_one_mib_multibyte_manuscripts_fit_complete_receipt(monkeypatch):
    _bounded_fact_check(monkeypatch)
    source = "Moreover, 研究 " + "é" * 490_000 + " [1] [2]."
    candidate = source.removeprefix("Moreover, ")
    assert 900_000 < len(source.encode("utf-8")) < MAX_TEXT_BYTES
    result = SessionWritingTransformer().transform(source, _prefix_proposal(source))
    assert result["candidate"] == candidate
    assert len(canonical_json_bytes(result)) < MAX_SOURCE_BYTES
    validate_citation_bindings(result["verification"], source, candidate)


def test_large_receipt_prepare_review_accept_read_and_replay(tmp_path, monkeypatch):
    _bounded_fact_check(monkeypatch)
    source = "Moreover, " + ("A" * 650 + " [1] [2] [3] [4] [5] [6]. ") * 1000
    root, service = _source_run(tmp_path, source)
    p = _prefix_proposal(source)
    prepared = service.prepare("artifact.manuscript", p)
    assert prepared["controls_effective"]
    assert (
        prepared["verification"]["citation_bindings"]["version"]
        == CITATION_BINDINGS_VERSION
    )
    review_id = approve(root, prepared)
    outcome = service.record(
        "artifact.manuscript",
        p,
        request=request(root, 70),
        review_artifact_id=review_id,
    )
    assert outcome["candidate_accepted"], outcome
    raw = read_retained_bytes(root, outcome["bundle_path"], max_bytes=MAX_SOURCE_BYTES)
    assert len(raw) < MAX_SOURCE_BYTES
    retained, binding = WritingService(root)._source(outcome["artifact_id"])
    assert retained.decode("utf-8") == prepared["candidate"]
    assert binding["sha256"] == prepared["candidate_sha256"]
    replayed = replay_run(root)
    validate_accepted_event_manifests(root, replayed.events)
    assert replayed.events[-1].payload.artifact_id == outcome["artifact_id"]


def test_legacy_sentence_bindings_remain_readable_and_replayable(tmp_path, monkeypatch):
    source = "Moreover, ModelX may improve [1]. ModelX may improve [2]."
    root, service = _source_run(tmp_path, source)
    p = _prefix_proposal(source)
    original = service.verify_preservation

    def legacy(source_text, candidate_text, *, protected_terms, protected_spans):
        value = original(
            source_text,
            candidate_text,
            protected_terms=protected_terms,
            protected_spans=protected_spans,
        )
        value["citation_bindings"] = resolve_citation_bindings(
            value, source_text, candidate_text
        )
        return value

    monkeypatch.setattr(service, "verify_preservation", legacy)
    prepared = service.prepare("artifact.manuscript", p)
    review_id = approve(root, prepared)
    outcome = service.record(
        "artifact.manuscript",
        p,
        request=request(root, 70),
        review_artifact_id=review_id,
    )
    assert outcome["candidate_accepted"]
    retained, _ = WritingService(root)._source(outcome["artifact_id"])
    assert retained.decode() == prepared["candidate"]
    validate_accepted_event_manifests(root, replay_run(root).events)


def test_over_budget_fails_before_candidate_or_receipt_publication(
    tmp_path, monkeypatch
):
    source = "Moreover, ModelX improves [1]."
    root, service = _source_run(tmp_path, source)
    prepared = service.prepare("artifact.manuscript", _prefix_proposal(source))
    prepared.update(
        accepted=True,
        candidate_path="writing/candidate/should-not-exist.md",
        narrative_realization={"stage": "draft"},
        source_binding={"manifest_sha256": "a" * 64},
        oversized_padding="x" * MAX_SOURCE_BYTES,
    )
    monkeypatch.setattr(service, "_prepare_bound", lambda *args, **kwargs: prepared)
    req = request(root, 50)
    with pytest.raises(WritingReceiptBudgetError) as caught:
        service._record_bound(
            "artifact.manuscript",
            _prefix_proposal(source),
            request=req,
            review_artifact_id=None,
            detector_config=None,
            allow_network=False,
            snapshot=object(),
        )
    assert caught.value.code == "receipt_budget_exceeded"
    assert caught.value.recoverable
    assert not (root / "writing").exists()
    assert replay_run(root).revision == req.expected_revision


def test_cli_retains_typed_receipt_budget_error(monkeypatch, capsys, tmp_path):
    from arw.cli import main

    def fail(_args):
        raise WritingReceiptBudgetError("canonical writing receipt exceeds its budget")

    monkeypatch.setattr("arw.cli_writing.handle", fail)
    code = main(
        [
            "writing",
            "record",
            "--run-root",
            str(tmp_path),
            "--source-id",
            "artifact.manuscript",
            "--proposal",
            str(tmp_path / "proposal.json"),
            "--request",
            str(tmp_path / "request.json"),
        ]
    )
    assert code == 65
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["code"] == "receipt_budget_exceeded"
