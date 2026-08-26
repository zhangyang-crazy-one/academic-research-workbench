from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import arw.research_integrity as research_integrity
from arw.canonical import canonical_json_bytes


ARS_ENTRY = {
    "citation_key": "chen2024ai",
    "title": "人工智能辅助科研的可复现证据",
    "authors": [{"family": "陈", "given": "明"}],
    "year": 2024,
    "source_pointer": "file:///research/陈_2024_人工智能辅助科研.pdf",
    "venue": "Research Integrity Review",
    "obtained_via": "folder-scan",
    "obtained_at": "2026-08-26T01:02:03Z",
    "adapter_name": "folder_scan.py",
    "adapter_version": "1.1.0",
}
SOURCE_SHA256 = hashlib.sha256(b"exact source bytes").hexdigest()
EXTRACTION_SHA256 = hashlib.sha256(b"extraction registration").hexdigest()
TEXT_SHA256 = hashlib.sha256("证据片段".encode("utf-8")).hexdigest()
CLAIM_SHA256 = hashlib.sha256(b"canonical claim document").hexdigest()


def _source():
    return research_integrity.research_source_from_ars_entry(
        ARS_ENTRY,
        source_id="source.paper-001",
        source_sha256=SOURCE_SHA256,
        imported_at="2026-08-26T01:03:00Z",
        imported_by="parent.runtime",
    )


def _span(source):
    locator = research_integrity.EvidenceLocator(
        kind="page",
        start=1,
        end=2,
        label="page 1",
    )
    return research_integrity.build_evidence_span(
        source,
        evidence_span_id="span.paper-001.001",
        extraction_registration_sha256=EXTRACTION_SHA256,
        locator=locator,
        extracted_text_sha256=TEXT_SHA256,
    )


def test_chain_validator_rejects_upstream_document_substitution() -> None:
    assert hasattr(research_integrity, "validate_research_integrity_chain"), (
        "whole-chain digest validation is missing"
    )
    assert hasattr(research_integrity, "research_source_from_ars_entry")
    assert hasattr(research_integrity, "build_evidence_span")
    assert hasattr(research_integrity, "build_claim_evidence_link")
    assert hasattr(research_integrity, "EvidenceLocator")

    source = _source()
    span = _span(source)
    link = research_integrity.build_claim_evidence_link(
        (span,),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="supports",
    )
    substituted = source.model_copy(update={"title": "substituted title"})

    with pytest.raises(ValueError, match="source manifest digest"):
        research_integrity.validate_research_integrity_chain(
            sources=(substituted,),
            evidence_spans=(span,),
            claim_links=(link,),
        )


def test_evidence_builder_recomputes_and_propagates_source_sha256() -> None:
    assert hasattr(research_integrity, "build_evidence_span"), (
        "the evidence builder that derives upstream digests is missing"
    )
    assert hasattr(research_integrity, "research_source_from_ars_entry")
    assert hasattr(research_integrity, "EvidenceLocator")

    source = _source()
    span = _span(source)
    expected_manifest_sha256 = hashlib.sha256(
        canonical_json_bytes(source.model_dump(mode="json"))
    ).hexdigest()

    assert span.research_source_manifest_sha256 == expected_manifest_sha256
    assert span.source_sha256 == source.source_sha256 == SOURCE_SHA256
    assert not hasattr(span, "text")
    assert not hasattr(span, "quoted_text")


def test_source_builder_binds_complete_ars_entry_and_preserves_unicode() -> None:
    source = _source()
    expected_bibliographic_sha256 = hashlib.sha256(
        canonical_json_bytes(ARS_ENTRY)
    ).hexdigest()

    assert source.bibliographic_sha256 == expected_bibliographic_sha256
    assert source.title == ARS_ENTRY["title"]
    assert source.authors[0].family == "陈"
    assert source.source_pointer == ARS_ENTRY["source_pointer"]
    assert source.adapter_name == "folder_scan.py"
    assert source.adapter_version == "1.1.0"

    changed = {**ARS_ENTRY, "tags": ["新增但仍属于完整书目记录的字段"]}
    changed_source = research_integrity.research_source_from_ars_entry(
        changed,
        source_id="source.paper-001",
        source_sha256=SOURCE_SHA256,
        imported_at="2026-08-26T01:03:00Z",
        imported_by="parent.runtime",
    )
    assert changed_source.bibliographic_sha256 != source.bibliographic_sha256


def test_source_builder_rejects_missing_digest_and_malformed_bibliography() -> None:
    with pytest.raises(ValueError, match="research source identity"):
        research_integrity.research_source_from_ars_entry(
            ARS_ENTRY,
            source_id="source.paper-001",
            source_sha256="",
            imported_at="2026-08-26T01:03:00Z",
            imported_by="parent.runtime",
        )
    with pytest.raises(ValueError, match="ARS literature entry"):
        research_integrity.research_source_from_ars_entry(
            {**ARS_ENTRY, "unknown_field": "must fail closed"},
            source_id="source.paper-001",
            source_sha256=SOURCE_SHA256,
            imported_at="2026-08-26T01:03:00Z",
            imported_by="parent.runtime",
        )


def test_claim_builder_canonicalizes_unique_span_digests_and_rejects_duplicates() -> None:
    source = _source()
    first = _span(source)
    second = research_integrity.build_evidence_span(
        source,
        evidence_span_id="span.paper-001.002",
        extraction_registration_sha256=EXTRACTION_SHA256,
        locator=research_integrity.EvidenceLocator(
            kind="page", start=2, end=3, label="page 2"
        ),
        extracted_text_sha256=hashlib.sha256("第二段".encode()).hexdigest(),
    )
    link = research_integrity.build_claim_evidence_link(
        (second, first),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="supports",
    )
    assert link.evidence_span_sha256 == tuple(sorted(link.evidence_span_sha256))
    assert len(link.evidence_span_sha256) == 2

    with pytest.raises(ValueError, match="unique non-empty"):
        research_integrity.build_claim_evidence_link(
            (first, first),
            claim_link_id="link.claim-001",
            claim_id="claim.paper-001",
            claim_sha256=CLAIM_SHA256,
            relation="supports",
        )
    with pytest.raises(ValidationError, match="unique and canonically ordered"):
        research_integrity.ClaimEvidenceLink(
            schema_version="arw.claim-evidence-link.v1",
            claim_link_id="link.claim-001",
            claim_id="claim.paper-001",
            claim_sha256=CLAIM_SHA256,
            evidence_span_sha256=tuple(reversed(link.evidence_span_sha256)),
            relation="supports",
        )


def test_chain_validator_rejects_source_digest_and_span_byte_substitution() -> None:
    source = _source()
    span = _span(source)
    link = research_integrity.build_claim_evidence_link(
        (span,),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="contextualizes",
    )
    research_integrity.validate_research_integrity_chain(
        sources=(source,), evidence_spans=(span,), claim_links=(link,)
    )
    with pytest.raises(ValueError, match="missing source"):
        research_integrity.validate_research_integrity_chain(
            sources=(), evidence_spans=(span,), claim_links=()
        )

    wrong_source_digest = span.model_copy(update={"source_sha256": "f" * 64})
    with pytest.raises(ValueError, match="source content digest propagation"):
        research_integrity.validate_research_integrity_chain(
            sources=(source,),
            evidence_spans=(wrong_source_digest,),
            claim_links=(),
        )

    substituted_span = span.model_copy(
        update={"extracted_text_sha256": hashlib.sha256(b"replacement").hexdigest()}
    )
    with pytest.raises(ValueError, match="substituted evidence bytes"):
        research_integrity.validate_research_integrity_chain(
            sources=(source,),
            evidence_spans=(substituted_span,),
            claim_links=(link,),
        )


def test_model_schema_branches_equal_checked_bundle_and_registry_is_strict() -> None:
    from arw.schema_registry import validate_instance

    root = Path(__file__).resolve().parents[2]
    checked = json.loads(
        (root / "schemas/v1/research-integrity-contracts.schema.json").read_text(
            encoding="utf-8"
        )
    )
    generated = research_integrity.research_integrity_contracts_schema_document()
    assert checked == generated

    for model in (
        research_integrity.ResearchSourceManifest,
        research_integrity.EvidenceSpan,
        research_integrity.ClaimEvidenceLink,
    ):
        standalone = model.model_json_schema(by_alias=False, mode="validation")
        standalone.pop("$defs", None)
        assert checked["$defs"][model.__name__] == standalone

    source = _source()
    span = _span(source)
    link = research_integrity.build_claim_evidence_link(
        (span,),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="contradicts",
    )
    for document in (source, span, link):
        validate_instance(
            "research-integrity-contracts.schema.json",
            document.model_dump(mode="json"),
        )
    mutated = source.model_dump(mode="json")
    mutated["unexpected"] = "rejected"
    with pytest.raises(ValueError, match="instance validation failed"):
        validate_instance("research-integrity-contracts.schema.json", mutated)


def test_bridge_exposes_no_parent_writer_or_hook_authority() -> None:
    for forbidden in (
        "ArtifactAcceptanceRequest",
        "ArtifactManifest",
        "MaterialPassport",
        "write_ledger",
        "retry_attempt",
        "decide_gate",
    ):
        assert not hasattr(research_integrity, forbidden)
