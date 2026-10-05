"""Venue annotations and legacy migration remain non-authoritative."""

import json

import pytest
from pydantic import ValidationError

from arw.kernel.state.research_learning import VenueQuantityGuidance
from arw.kernel.state.venue_learning import VenueExemplar, legacy_style_drafts


def test_metadata_cannot_claim_full_text_structure():
    with pytest.raises(ValidationError, match="metadata-only"):
        VenueExemplar.model_validate_json(
            json.dumps(
                {
                    "schema_version": "arw.venue-exemplar.v1",
                    "exemplar_id": "exemplar.test",
                    "official_url": "https://example.test/paper",
                    "source_sha256": "a" * 64,
                    "source_artifact_id": "artifact.source",
                    "source_reviewer": "synthetic.fixture",
                    "source_review_artifact_id": "artifact.review",
                    "accepted_category": "synthetic test",
                    "accepted_year": 2025,
                    "venue_id": "venue.test",
                    "domain_id": "domain.test",
                    "sections": [],
                    "observed_patterns": ["A claimed pattern"],
                    "access_basis": "official_metadata_only",
                }
            )
        )


def test_quantity_guidance_requires_nonmandatory_exception():
    with pytest.raises(ValidationError):
        VenueQuantityGuidance.model_validate_json(
            json.dumps(
                {
                    "minimum": 4,
                    "maximum": 8,
                    "unit": "rows",
                    "nonmandatory": False,
                    "counterexample_needs": "Inspect denser accepted tables",
                    "exception_conditions": ["Grouped settings"],
                }
            )
        )


def test_legacy_style_is_draft_with_no_source_hash_or_ledger_authority():
    raw = json.dumps(
        {
            "sources": {"paper.a": {"url": "https://example.test/paper"}},
            "style_learning": {
                "exemplars": [
                    {
                        "source_id": "paper.a",
                        "observed_patterns": ["Use a task example"],
                    }
                ]
            },
        }
    ).encode()
    result = legacy_style_drafts(raw)
    assert result["drafts"][0]["status"] == "unverified_legacy_candidate"
    assert result["drafts"][0]["source_sha256"] is None
    assert "accepted full-text source bytes" in result["drafts"][0]["needs"]


def capsule_v2_documents():
    from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

    provenance = {
        "pdf_sha256": "b" * 64,
        "pdf_url": "https://example.test/paper.pdf",
        "pdf_byte_count": 100000,
        "pdf_page_count": 8,
        "extractor": "fixture-extractor-v1",
        "reviewer": "agent.fixture",
        "review_authority": "agent_source_review",
        "read_scope": ["Main body"],
        "limitations": ["Agent annotation, not scientific validation"],
    }
    functions = (
        "problem",
        "gap",
        "contribution",
        "argument",
        "evidence",
        "knowledge_boundary",
    )
    sections = [
        {
            "function": f,
            "status": "unknown",
            "section": None,
            "locator": None,
            "paraphrase": None,
            "unknown_reason": "No identifiable passage inspected",
        }
        for f in functions
    ]
    common = {
        "official_url": "https://example.test/paper",
        "doi": None,
        "accepted_category": "fixture",
        "accepted_year": 2025,
        "provenance": provenance,
    }
    capsule = {
        "schema_version": "arw.venue-source-capsule.v2",
        "title": "Fixture",
        **common,
        "structural_summary": ["No claimed full-text retention"],
        "sections": sections,
        "figure_roles": [],
        "evidence_forms": [],
        "observed_patterns": [],
        "retention": "structural_capsule_only_full_pdf_not_retained",
    }
    raw = canonical_json_bytes(capsule)
    binding = {
        **common,
        "source_artifact_id": "artifact.capsule",
        "source_sha256": sha256_hex(raw),
        "access_basis": "official_full_text",
    }
    exemplar = {
        "schema_version": "arw.venue-exemplar.v2",
        **binding,
        "exemplar_id": "exemplar.fixture",
        "source_review_artifact_id": "artifact.review",
        "source_reviewer": "agent.fixture",
        "venue_id": "venue.fixture",
        "domain_id": "domain.fixture",
        "sections": sections,
        "figure_roles": [],
        "evidence_forms": [],
        "observed_patterns": [],
    }
    review = {
        "schema_version": "arw.venue-source-review.v2",
        **binding,
        "review_id": "review.fixture",
        "reviewer": "agent.fixture",
        "decision": "AGENT_REVIEW_RECORDED",
    }
    return capsule, exemplar, review


def test_v2_distinguishes_capsule_and_pdf_and_records_unknown_functions():
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.state.venue_learning import (
        parse_venue_exemplar,
        parse_venue_source_review,
        verify_venue_source_binding,
    )

    capsule, exemplar, review = capsule_v2_documents()
    parsed = parse_venue_exemplar(canonical_json_bytes(exemplar))
    assert parsed.source_sha256 != parsed.provenance.pdf_sha256
    assert all(
        item.status == "unknown" and item.locator is None for item in parsed.sections
    )
    verify_venue_source_binding(
        parsed,
        parse_venue_source_review(canonical_json_bytes(review)),
        canonical_json_bytes(capsule),
    )


@pytest.mark.parametrize("field", ["pdf_sha256", "pdf_url", "reviewer"])
def test_v2_rejects_changed_review_provenance(field):
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.state.venue_learning import (
        parse_venue_exemplar,
        parse_venue_source_review,
        verify_venue_source_binding,
    )

    capsule, exemplar, review = capsule_v2_documents()
    review["provenance"] = {
        **review["provenance"],
        field: "c" * 64 if field == "pdf_sha256" else "https://example.test/other",
    }
    with pytest.raises(
        ValueError, match="provenance review mismatch|PDF reviewer differs"
    ):
        verify_venue_source_binding(
            parse_venue_exemplar(canonical_json_bytes(exemplar)),
            parse_venue_source_review(canonical_json_bytes(review)),
            canonical_json_bytes(capsule),
        )


def test_v2_unknown_cannot_assert_locator_or_human_attestation():
    from arw.kernel.state.venue_learning import VenueExemplarV2, VenueSourceReviewV2

    _, exemplar, review = capsule_v2_documents()
    exemplar["sections"][0]["locator"] = "page 1"
    with pytest.raises(ValidationError, match="cannot assert a locator"):
        VenueExemplarV2.model_validate_json(json.dumps(exemplar))
    review["provenance"]["review_authority"] = "USER_ATTESTED_READ"
    with pytest.raises(ValidationError):
        VenueSourceReviewV2.model_validate_json(json.dumps(review))


def test_v2_capsule_rejects_duplicate_function_ids():
    from arw.kernel.state.venue_learning import VenueSourceCapsule

    capsule, _, _ = capsule_v2_documents()
    capsule["sections"][0]["function"] = capsule["sections"][1]["function"]
    with pytest.raises(ValidationError, match="each function once"):
        VenueSourceCapsule.model_validate_json(json.dumps(capsule))


def survey_v2_documents(access_basis="accepted_author_full_text"):
    from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

    capsule, exemplar, review = capsule_v2_documents()
    provenance = capsule["provenance"]
    provenance.update(
        {
            "document_version": "accepted_author_manuscript"
            if access_basis == "accepted_author_full_text"
            else "author_preprint",
            "source_authority": "preprint_repository",
            "related_formal_publication_url": "https://example.test/published-survey",
            "related_formal_publication_doi": "10.0000/survey",
            "version_relationship_note": "PDF header identifies this source version; publisher byte equivalence is unverified.",
        }
    )
    capsule["access_basis"] = exemplar["access_basis"] = review["access_basis"] = (
        access_basis
    )
    capsule["accepted_category"] = exemplar["accepted_category"] = review[
        "accepted_category"
    ] = "review_survey_author_version"
    capsule["evidence_forms"] = exemplar["evidence_forms"] = [
        "taxonomy",
        "literature comparison",
        "research agenda",
    ]
    exemplar["source_sha256"] = review["source_sha256"] = sha256_hex(
        canonical_json_bytes(capsule)
    )
    return capsule, exemplar, review


@pytest.mark.parametrize(
    "access_basis", ["accepted_author_full_text", "preprint_full_text"]
)
def test_v2_author_versions_bind_explicit_document_version(access_basis):
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.state.venue_learning import (
        parse_venue_exemplar,
        parse_venue_source_review,
        verify_venue_source_binding,
    )

    capsule, exemplar, review = survey_v2_documents(access_basis)
    verify_venue_source_binding(
        parse_venue_exemplar(canonical_json_bytes(exemplar)),
        parse_venue_source_review(canonical_json_bytes(review)),
        canonical_json_bytes(capsule),
    )


@pytest.mark.parametrize(
    "field", ["document_version", "source_authority", "version_relationship_note"]
)
def test_v2_author_versions_require_document_version_declaration(field):
    from arw.kernel.state.venue_learning import VenueSourceCapsule

    capsule, _, _ = survey_v2_documents()
    capsule["provenance"].pop(field)
    with pytest.raises(ValidationError, match="requires"):
        VenueSourceCapsule.model_validate_json(json.dumps(capsule))


def test_v2_preprint_cannot_masquerade_as_publisher_full_text():
    from arw.kernel.state.venue_learning import VenueExemplarV2

    _, exemplar, _ = survey_v2_documents("preprint_full_text")
    exemplar["access_basis"] = "official_full_text"
    with pytest.raises(ValidationError, match="cannot declare"):
        VenueExemplarV2.model_validate_json(json.dumps(exemplar))


def test_v2_serializer_preserves_existing_capsule_bytes():
    from arw.kernel.core.canonical import canonical_json_bytes
    from arw.kernel.state.venue_learning import (
        VenueSourceCapsule,
        venue_source_capsule_document,
    )

    capsule, _, _ = capsule_v2_documents()
    raw = canonical_json_bytes(capsule)
    parsed = VenueSourceCapsule.model_validate_json(raw)
    assert canonical_json_bytes(venue_source_capsule_document(parsed)) == raw
    # Established null fields remain present; only absent new metadata is omitted.
    assert "doi" in venue_source_capsule_document(parsed)
    assert "document_version" not in venue_source_capsule_document(parsed)["provenance"]
