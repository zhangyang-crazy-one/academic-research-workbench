from __future__ import annotations

import json

import pytest

from arw.kernel.policy.citations import (
    ReferenceRecord,
    ReferenceUse,
    aggregate_status,
    check_response,
    check_unavailable,
    contamination_signals,
    evaluate_use,
    fetch_response,
    load_check_history,
    publish_check,
    reference_from_source_manifest,
    replay_check,
)


@pytest.fixture
def reference():
    return ReferenceRecord(reference_id="ref.alpha", citation_key="Smith2024", title="Evidence for Alpha",
                           authors=("Smith",), year=2024, doi="10.1234/alpha")


def _crossref(*, retracted=False, items=None):
    if items is None:
        items = [{"DOI": "10.1234/alpha", "title": ["Evidence for Alpha"],
                  "published": {"date-parts": [[2024]]}, "author": [{"family": "Smith"}],
                  "update-to": [{"type": "retraction"}] if retracted else []}]
    return json.dumps({"message": {"items": items}}).encode()


def test_offline_replay_and_source_digest(reference, tmp_path):
    raw = _crossref()
    receipt = check_response(reference, "crossref", raw, observed_at="2026-09-25T00:00:00Z")
    assert receipt.status == "verified"
    publish_check(tmp_path, receipt, raw)
    assert replay_check(tmp_path, reference, receipt.receipt_sha256) == receipt
    response = tmp_path / "citations/responses/sha256" / receipt.response_sha256
    response.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        replay_check(tmp_path, reference, receipt.receipt_sha256)


def test_retraction_roles_and_history(reference):
    bad = check_response(reference, "crossref", _crossref(retracted=True), observed_at="2026-09-25T00:00:00Z")
    good = check_response(reference, "crossref", _crossref(), observed_at="2026-09-26T00:00:00Z")
    support = ReferenceUse(use_id="use.support", reference_id=reference.reference_id, claim_id="claim.alpha", role="supporting")
    object_use = ReferenceUse(use_id="use.object", reference_id=reference.reference_id, claim_id="claim.beta", role="research_object")
    assert evaluate_use(support, reference, [bad], applicable=["crossref"])["verdict"] == "BLOCK"
    assert evaluate_use(object_use, reference, [bad], applicable=["crossref"])["verdict"] == "HUMAN_REVIEW"
    after = evaluate_use(support, reference, [bad, good], applicable=["crossref"])
    assert after["status"] == "verified"
    assert after["verdict"] == "BLOCK"
    assert after["open_blocker_receipts"] == [bad.receipt_sha256]
    assert evaluate_use(object_use, reference, [bad, good], applicable=["crossref"])["verdict"] == "HUMAN_REVIEW"


def test_history_scan_forces_prior_blocker(reference, tmp_path):
    bad_raw = _crossref(retracted=True)
    good_raw = _crossref()
    bad = check_response(reference, "crossref", bad_raw, observed_at="2026-09-25T00:00:00Z")
    good = check_response(reference, "crossref", good_raw, observed_at="2026-09-26T00:00:00Z")
    publish_check(tmp_path, bad, bad_raw)
    publish_check(tmp_path, good, good_raw)
    history = load_check_history(tmp_path, reference)
    assert history == (bad, good)
    use = ReferenceUse(use_id="use.support", reference_id=reference.reference_id, claim_id="claim.alpha", role="supporting")
    assert evaluate_use(use, reference, history, applicable=["crossref"])["verdict"] == "BLOCK"


def test_not_found_unavailable_ambiguous_and_no_network(reference):
    empty = check_response(reference, "crossref", _crossref(items=[]), observed_at="2026-09-25T00:00:00Z")
    malformed = check_response(reference, "openalex", b"invalid json", observed_at="2026-09-25T00:00:00Z")
    double = check_response(reference, "crossref", _crossref(items=json.loads(_crossref())["message"]["items"] * 2), observed_at="2026-09-25T00:00:00Z")
    assert empty.status == "not_found"
    assert malformed.status == "unknown"
    assert double.status == "ambiguous"
    assert check_response(reference, "crossref", b"service busy", observed_at="2026-09-25T00:00:00Z", http_status=503).status == "unavailable"
    assert check_response(reference, "crossref", b"missing", observed_at="2026-09-25T00:00:00Z", http_status=404).status == "not_found"
    assert aggregate_status([empty, malformed], applicable=["crossref", "openalex"]) == "unknown"
    assert contamination_signals([empty, malformed]) == {"crossref_unmatched": True}
    support = ReferenceUse(use_id="use.support", reference_id=reference.reference_id, claim_id="claim.alpha", role="supporting")
    assert evaluate_use(support, reference, [empty], applicable=["crossref"])["verdict"] == "BLOCK"
    unavailable = check_unavailable(reference, "openalex", observed_at="2026-09-25T00:00:00Z", error_code="timeout")
    assert aggregate_status([empty, unavailable], applicable=["crossref", "openalex"]) == "unavailable"
    assert evaluate_use(support, reference, [unavailable], applicable=["openalex"])["verdict"] == "HUMAN_REVIEW"
    with pytest.raises(PermissionError, match="opt-in"):
        fetch_response(reference, "crossref")


def test_batch_history_requires_aggregate_absence_and_keeps_real_blockers(reference, tmp_path):
    use = ReferenceUse(use_id="use.support", reference_id=reference.reference_id,
                       claim_id="claim.alpha", role="supporting")
    empty = _crossref(items=[])
    matched = json.dumps({"results": [{"id": "https://openalex.org/W1",
                            "doi": "https://doi.org/10.1234/alpha",
                            "display_name": reference.title, "publication_year": 2024}]}).encode()
    missing = check_response(reference, "crossref", empty, observed_at="2026-09-25T00:00:00Z", batch_id="batch.first")
    verified = check_response(reference, "openalex", matched, observed_at="2026-09-25T00:00:01Z", batch_id="batch.first")
    for receipt, raw in ((missing, empty), (verified, matched)):
        publish_check(tmp_path, receipt, raw)
    history = load_check_history(tmp_path, reference)
    decision = evaluate_use(use, reference, history, applicable=["crossref", "openalex"])
    assert decision == {"use_id": use.use_id, "status": "verified", "verdict": "PASS", "open_blocker_receipts": []}
    second_missing = check_response(reference, "crossref", empty, observed_at="2026-09-26T00:00:00Z", batch_id="batch.second")
    third_missing = check_response(reference, "openalex", b'{"results":[]}', observed_at="2026-09-26T00:00:01Z", batch_id="batch.second")
    for receipt, raw in ((second_missing, empty), (third_missing, b'{"results":[]}')):
        publish_check(tmp_path, receipt, raw)
    recheck = check_response(reference, "openalex", matched, observed_at="2026-09-27T00:00:00Z", batch_id="batch.third")
    publish_check(tmp_path, recheck, matched)
    decision = evaluate_use(use, reference, load_check_history(tmp_path, reference), applicable=["crossref", "openalex"])
    assert decision["status"] == "verified"
    assert decision["verdict"] == "BLOCK"
    assert set(decision["open_blocker_receipts"]) == {second_missing.receipt_sha256, third_missing.receipt_sha256}


def test_unbatched_legacy_absence_cannot_claim_multi_provider_block(reference):
    missing = check_response(reference, "crossref", _crossref(items=[]), observed_at="2026-09-25T00:00:00Z")
    use = ReferenceUse(use_id="use.support", reference_id=reference.reference_id,
                       claim_id="claim.alpha", role="supporting")
    decision = evaluate_use(use, reference, [missing], applicable=["crossref", "openalex"])
    assert decision["verdict"] == "HUMAN_REVIEW"
    assert decision["open_blocker_receipts"] == []


def test_all_provider_fixture_shapes(reference):
    openalex = {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1234/alpha",
                             "display_name": reference.title, "publication_year": 2024, "authorships": [], "is_retracted": True}]}
    dblp = {"result": {"hits": {"hit": [{"info": {"key": "journals/x/1", "title": reference.title,
                                                         "year": "2024", "authors": {"author": ["Smith"]}}}]}}}
    arxiv_ref = reference.model_copy(update={"doi": None, "arxiv_id": "2401.12345"})
    arxiv = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.12345</id><title>Evidence for Alpha</title><published>2024-01-01T00:00:00Z</published><author><name>Smith</name></author></entry></feed>'
    assert check_response(reference, "openalex", json.dumps(openalex).encode(), observed_at="2026-09-25T00:00:00Z").status == "retracted"
    assert check_response(reference, "dblp", json.dumps(dblp).encode(), observed_at="2026-09-25T00:00:00Z").status == "verified"
    assert check_response(arxiv_ref, "arxiv", arxiv, observed_at="2026-09-25T00:00:00Z").status == "verified"


def test_ars_source_bridge_binds_existing_manifest():
    from tests.unit.test_research_integrity import _source
    source = _source()
    reference = reference_from_source_manifest(source)
    assert reference.citation_key == source.citation_key
    assert reference.source_manifest_sha256 is not None
