"""Receipt observations never replace ARS self-reports or missing evidence."""

from __future__ import annotations

import json

import pytest

from arw.kernel.policy import citations
from arw.kernel.policy.research_integrity import ARSLiteratureCorpusEntry


def _reference():
    return citations.ReferenceRecord(
        reference_id="ref.alpha", citation_key="Alpha2024", title="Alpha",
        authors=("Smith",), year=2024, doi="10.1234/alpha",
    )


def _entry(**extra):
    return ARSLiteratureCorpusEntry.model_validate({
        "citation_key": "Alpha2024", "title": "Alpha",
        "authors": [{"family": "Smith"}], "year": 2024,
        "doi": "10.1234/alpha", "source_pointer": "paper.pdf", **extra,
    })


def _receipt(status, *, provider="crossref", day=25):
    reference = _reference()
    if provider == "crossref":
        raw = json.dumps({"message": {"items": [] if status == "not_found" else [{
            "DOI": reference.doi, "title": [reference.title],
            "updated-by": [{"type": "retraction"}] if status == "retracted" else [],
        }]}}).encode()
    else:
        raw = json.dumps({"results": [] if status == "not_found" else [{
            "id": "https://openalex.org/W1", "doi": reference.doi,
            "display_name": reference.title, "is_retracted": status == "retracted",
        }]}).encode()
    if status == "unknown":
        raw = b"invalid json"
    if status == "ambiguous":
        value = json.loads(raw)
        value["message"]["items"] *= 2
        raw = json.dumps(value).encode()
    return citations.check_response(
        reference, provider, raw, observed_at=f"2026-09-{day}T00:00:00Z",
        http_status=503 if status == "unavailable" else 200,
    )


@pytest.mark.parametrize("provider", ["crossref", "openalex"])
@pytest.mark.parametrize("status,reported,observed", [
    ("not_found", False, True), ("verified", True, False),
    ("retracted", True, False),
])
def test_conclusive_conflict_keeps_both_values(provider, status, reported, observed):
    receipt = _receipt(status, provider=provider)
    key = provider + "_unmatched"
    entry = _entry(contamination_signals={key: reported}, user_notes="human note")
    before = entry.model_dump_json(exclude_unset=True)
    result = citations.contamination_observation(_reference(), [receipt], entry=entry)
    assert result["contamination_signals"] == {key: observed}
    assert result["self_reported"]["contamination_signals"] == {key: reported}
    assert result["conflicts"] == [{
        "signal": key, "reported_value": reported, "resolver_value": observed,
        "receipt_sha256": receipt.receipt_sha256,
    }]
    assert entry.model_dump_json(exclude_unset=True) == before


@pytest.mark.parametrize("status", ["unknown", "unavailable", "ambiguous"])
@pytest.mark.parametrize("reported", [True, False])
def test_inconclusive_is_neither_true_nor_false(status, reported):
    result = citations.contamination_observation(
        _reference(), [_receipt(status)],
        entry=_entry(contamination_signals={"crossref_unmatched": reported}),
    )
    assert result["contamination_signals"] == {}
    assert result["conflicts"] == []
    assert result["lookup_states"] == {"crossref": status}
    assert result["contamination_signal_omissions"] == (
        {"crossref_unmatched": "api_degraded"} if status == "unavailable" else {}
    )


def test_missing_self_report_and_manual_notes_are_not_negative_evidence():
    for entry in (None, _entry(), _entry(obtained_via="manual", user_notes="read by author"),
                  _entry(contamination_signal_omissions={"crossref_unmatched": "api_degraded"})):
        result = citations.contamination_observation(_reference(), [_receipt("verified")], entry=entry)
        assert result["contamination_signals"] == {"crossref_unmatched": False}
        assert result["conflicts"] == []
    missing = citations.contamination_observation(_reference(), [], entry=_entry())
    assert missing["lookup_states"] == {} and missing["contamination_signals"] == {}


def test_later_agreement_or_outage_cannot_erase_older_conflict():
    first = _receipt("not_found")
    entry = _entry(contamination_signals={"crossref_unmatched": False})
    for status in ("verified", "unavailable"):
        later = _receipt(status, day=26)
        result = citations.contamination_observation(_reference(), [later, first], entry=entry)
        assert result["lookup_states"] == {"crossref": status}
        assert result["conflicts"][0]["receipt_sha256"] == first.receipt_sha256
        assert len(result["conflicts"]) == 1


def test_another_reference_cannot_supply_contamination_evidence():
    other = _reference().model_copy(update={"reference_id": "ref.other"})
    with pytest.raises(ValueError, match="another reference"):
        citations.contamination_observation(other, [_receipt("verified")])


def test_arxiv_conflicts_and_unsupported_provider_signals():
    reference = _reference().model_copy(update={"arxiv_id": "2401.12345"})
    raw = b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    receipt = citations.check_response(reference, "arxiv", raw, observed_at="2026-09-25T00:00:00Z")
    entry = _entry(arxiv_id="2401.12345", contamination_signals={
        "arxiv_unmatched": False, "semantic_scholar_unmatched": True,
        "preprint_post_llm_inflection": True,
    })
    result = citations.contamination_observation(reference, [receipt], entry=entry)
    assert result["contamination_signals"] == {"arxiv_unmatched": True}
    assert result["conflicts"][0]["signal"] == "arxiv_unmatched"
    assert result["self_reported"]["contamination_signals"]["preprint_post_llm_inflection"] is True
    assert "semantic_scholar_unmatched" not in result["contamination_signals"]


def test_entry_identity_mismatch_cannot_be_compared():
    with pytest.raises(ValueError, match="differs from citation reference"):
        citations.contamination_observation(
            _reference(), [_receipt("verified")], entry=_entry(title="Different paper")
        )
