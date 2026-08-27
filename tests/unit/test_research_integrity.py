# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from arw import research_integrity
from arw.canonical import canonical_json_bytes


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"test JSON fixture is unreadable: {path}") from error
    if not isinstance(document, dict):
        raise RuntimeError(f"test JSON fixture is not an object: {path}")
    return document


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
TEXT_SHA256 = hashlib.sha256("证据片段".encode()).hexdigest()
CLAIM_SHA256 = hashlib.sha256(b"canonical claim document").hexdigest()
ARS_ENTRY_SCHEMA = _load_json_object(
    Path(__file__).resolve().parents[2]
    / "skills/academic-research-suite/ars/shared/contracts/passport/"
    "literature_corpus_entry.schema.json"
)
ARS_ENTRY_VALIDATOR = Draft202012Validator(
    ARS_ENTRY_SCHEMA,
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)
ARS_SIGNAL_SCHEMA = _load_json_object(
    Path(__file__).resolve().parents[2]
    / "skills/academic-research-suite/ars/shared/contracts/passport/"
    "bibliographic_integrity_signal.schema.json"
)
ARS_SIGNAL_VALIDATOR = Draft202012Validator(
    ARS_SIGNAL_SCHEMA,
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)
VALID_BIBLIOGRAPHIC_SIGNAL = _load_json_object(
    Path(__file__).resolve().parents[2]
    / "skills/academic-research-suite/ars/scripts/fixtures/"
    "bibliographic_integrity_signals/retraction.json"
)


def _bridge(entry: dict[str, object]):
    return research_integrity.research_source_from_ars_entry(
        entry,
        source_id="source.paper-001",
        source_sha256=SOURCE_SHA256,
        imported_at="2026-08-26T01:03:00Z",
        imported_by="parent.runtime",
    )


def _assert_authoritative_rejection_is_enforced(entry: dict[str, Any]) -> None:
    errors = tuple(ARS_ENTRY_VALIDATOR.iter_errors(entry))
    assert errors, "test case must be rejected by the authoritative ARS schema"
    with pytest.raises(ValueError, match="ARS literature entry"):
        _bridge(entry)


def _source():
    return _bridge(ARS_ENTRY)


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
    assert isinstance(source.authors[0], research_integrity.CSLPersonalName)
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


def test_source_builder_preserves_partial_adapter_attribution() -> None:
    entry = {**ARS_ENTRY, "obtained_via": "other", "adapter_name": "custom-import"}
    del entry["adapter_version"]
    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    source = _bridge(entry)
    assert source.adapter_name == "custom-import"
    assert source.adapter_version is None


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


@pytest.mark.parametrize(
    "invalid_update",
    (
        {"arxiv_id": "not-an-arxiv-id"},
        {"venue": None},
    ),
)
def test_source_bridge_fails_closed_when_authoritative_ars_schema_rejects(
    invalid_update: dict[str, object],
) -> None:
    _assert_authoritative_rejection_is_enforced({**ARS_ENTRY, **invalid_update})


@pytest.mark.parametrize(
    "field",
    (
        "venue",
        "doi",
        "arxiv_id",
        "tags",
        "obtained_via",
        "obtained_at",
        "adapter_name",
        "adapter_version",
        "abstract",
        "user_notes",
        "source_acquired",
        "source_acquisition_date",
        "source_acquisition_path",
        "source_verified_against_original",
        "source_verification_method",
        "description_source",
        "contamination_signals_backfilled_at",
        "contamination_signals",
        "venue_type",
        "venue_type_provenance",
        "venue_type_source",
        "contamination_signal_omissions",
        "bibliographic_integrity_signals",
    ),
)
def test_bridge_rejects_explicit_null_for_every_nonnullable_optional_field(
    field: str,
) -> None:
    _assert_authoritative_rejection_is_enforced({**ARS_ENTRY, field: None})


@pytest.mark.parametrize(
    "invalid_update",
    (
        {"citation_key": "1bad-key"},
        {"doi": "doi:10.1234/example"},
        {"arxiv_id": "2401/12345"},
        {"description_source": "bibliography_latest"},
        {"authors": [{"family": "Chen", "given": None}]},
        {"authors": [{"family": "Chen", "dropping_particle": "van"}]},
        {"obtained_at": "yesterday"},
        {"source_acquisition_date": "2026-08-26"},
        {"contamination_signals_backfilled_at": "not-a-timestamp"},
        {"contamination_signals": {"openalex_unmatched": None}},
        {"contamination_signal_omissions": {"openalex_unmatched": None}},
    ),
)
def test_bridge_enforces_authoritative_patterns_formats_and_nested_null_rules(
    invalid_update: dict[str, object],
) -> None:
    _assert_authoritative_rejection_is_enforced({**ARS_ENTRY, **invalid_update})

def test_date_time_validation_does_not_depend_on_optional_format_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        research_integrity._FORMAT_CHECKER, "conforms", lambda *_args: True
    )
    _assert_authoritative_rejection_is_enforced(
        {**ARS_ENTRY, "obtained_at": "yesterday"}
    )


def test_bridge_validates_each_bibliographic_integrity_signal_before_hashing() -> None:
    valid_entry = {
        **ARS_ENTRY,
        "bibliographic_integrity_signals": [VALID_BIBLIOGRAPHIC_SIGNAL],
    }
    assert ARS_SIGNAL_VALIDATOR.is_valid(VALID_BIBLIOGRAPHIC_SIGNAL)
    source = _bridge(valid_entry)
    assert (
        source.bibliographic_sha256
        == hashlib.sha256(canonical_json_bytes(valid_entry)).hexdigest()
    )

    invalid_signal = {"foo": "bar"}
    assert not ARS_SIGNAL_VALIDATOR.is_valid(invalid_signal)
    with pytest.raises(ValueError, match="bibliographic integrity signal"):
        _bridge(
            {
                **ARS_ENTRY,
                "bibliographic_integrity_signals": [invalid_signal],
            }
        )


@pytest.mark.parametrize(
    "required_field",
    ("citation_key", "title", "authors", "year", "source_pointer"),
)
def test_bridge_enforces_every_authoritative_required_field(
    required_field: str,
) -> None:
    entry = dict(ARS_ENTRY)
    del entry[required_field]
    _assert_authoritative_rejection_is_enforced(entry)


@pytest.mark.parametrize(
    "invalid_update",
    (
        {
            "source_verified_against_original": True,
            "source_verification_method": "codex_audit",
        },
        {
            "source_verified_against_original": True,
            "source_acquired": True,
            "source_verification_method": "none",
        },
        {"source_acquired": False, "description_last_audit": None},
        {
            "year": 2023,
            "contamination_signals": {"preprint_post_llm_inflection": True},
        },
        {
            "obtained_via": "manual",
            "contamination_signals": {"openalex_unmatched": False},
        },
        {"venue_type": "journal-article"},
        {"venue_type_provenance": "adapter_declared"},
        {
            "venue_type": "unknown",
            "venue_type_provenance": "adapter_declared",
        },
        {
            "venue_type": "journal-article",
            "venue_type_provenance": "trusted_source_declared",
        },
        {
            "obtained_via": "manual",
            "contamination_signal_omissions": {
                "semantic_scholar_unmatched": "api_degraded"
            },
        },
        {
            "contamination_signals": {"crossref_unmatched": False},
            "contamination_signal_omissions": {"crossref_unmatched": "api_degraded"},
        },
        {"contamination_signal_omissions": {"arxiv_unmatched": "api_degraded"}},
    ),
)
def test_bridge_enforces_every_authoritative_cross_field_rule(
    invalid_update: dict[str, object],
) -> None:
    _assert_authoritative_rejection_is_enforced({**ARS_ENTRY, **invalid_update})


@pytest.mark.parametrize(
    "valid_update",
    (
        {
            "source_verified_against_original": True,
            "source_acquired": True,
            "source_verification_method": "codex_audit",
        },
        {
            "source_acquired": True,
            "description_last_audit": None,
        },
        {
            "venue_type": "journal-article",
            "venue_type_provenance": "unknown",
        },
        {
            "obtained_via": "manual",
            "contamination_signals": {"preprint_post_llm_inflection": True},
        },
    ),
)
def test_bridge_preserves_authoritative_valid_boundary_cases(
    valid_update: dict[str, object],
) -> None:
    entry = {**ARS_ENTRY, **valid_update}
    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    _bridge(entry)


def test_claim_builder_canonicalizes_unique_span_digests_and_rejects_duplicates() -> (
    None
):
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


def test_chain_validator_rejects_ambiguous_source_and_claim_identities() -> None:
    source = _source()
    duplicate_citation = source.model_copy(
        update={"source_id": "source.paper-002", "source_sha256": "e" * 64}
    )
    with pytest.raises(ValueError, match="duplicate citation key"):
        research_integrity.validate_research_integrity_chain(
            sources=(source, duplicate_citation),
            evidence_spans=(),
            claim_links=(),
        )

    span = _span(source)
    first = research_integrity.build_claim_evidence_link(
        (span,),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="supports",
    )
    conflicting = first.model_copy(
        update={
            "claim_link_id": "link.claim-002",
            "claim_sha256": hashlib.sha256(b"substituted claim").hexdigest(),
        }
    )
    with pytest.raises(ValueError, match="conflicting claim content digest"):
        research_integrity.validate_research_integrity_chain(
            sources=(source,),
            evidence_spans=(span,),
            claim_links=(first, conflicting),
        )


def test_model_schema_branches_equal_checked_bundle_and_registry_is_strict() -> None:
    from arw.schema_registry import validate_instance

    root = Path(__file__).resolve().parents[2]
    checked = _load_json_object(
        root / "schemas/v1/research-integrity-contracts.schema.json"
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

    evidence_digests_schema = checked["$defs"]["ClaimEvidenceLink"]["properties"][
        "evidence_span_sha256"
    ]
    assert evidence_digests_schema["uniqueItems"] is True

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

    duplicate_evidence = link.model_dump(mode="json")
    duplicate_evidence["evidence_span_sha256"] = [
        link.evidence_span_sha256[0],
        link.evidence_span_sha256[0],
    ]
    with pytest.raises(ValueError, match="instance validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", duplicate_evidence
        )

    unsorted_evidence = link.model_dump(mode="json")
    unsorted_evidence["evidence_span_sha256"] = ["f" * 64, "e" * 64]
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", unsorted_evidence)
    mutated = source.model_dump(mode="json")
    mutated["unexpected"] = "rejected"
    with pytest.raises(ValueError, match="instance validation failed"):
        validate_instance("research-integrity-contracts.schema.json", mutated)

    invalid_acquisition = source.model_dump(mode="json")
    invalid_acquisition["obtained_via"] = "unknown-importer"
    with pytest.raises(ValueError, match="instance validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", invalid_acquisition
        )


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
