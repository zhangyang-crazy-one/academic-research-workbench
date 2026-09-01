# pyright: reportMissingImports=false
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from arw import research_integrity
from arw.kernel.core.canonical import canonical_json_bytes


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


def test_chain_validator_revalidates_model_copy_contracts() -> None:
    good_source = _source()
    mutated_source = good_source.model_copy(
        update={"imported_at": "2026-99-99T99:99:99Z"}
    )
    span = _span(good_source)
    link = research_integrity.build_claim_evidence_link(
        (span,),
        claim_link_id="link.claim-001",
        claim_id="claim.paper-001",
        claim_sha256=CLAIM_SHA256,
        relation="supports",
    )

    with pytest.raises(ValueError, match="research source contract is invalid"):
        research_integrity.validate_research_integrity_chain(
            sources=(mutated_source,),
            evidence_spans=(span,),
            claim_links=(link,),
        )

    with pytest.raises(ValidationError, match="imported_at"):
        research_integrity.build_evidence_span(
            mutated_source,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=span.locator,
            extracted_text_sha256=TEXT_SHA256,
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


def test_source_builder_preserves_ars_valid_large_author_lists() -> None:
    entry = {
        **ARS_ENTRY,
        "authors": [{"family": f"ConsortiumMember{index:03d}"} for index in range(257)],
    }
    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    source = _bridge(entry)

    assert len(source.authors) == 257
    from arw.schema_registry import validate_instance

    validate_instance(
        "research-integrity-contracts.schema.json", source.model_dump(mode="json")
    )


def test_bridge_preserves_ars_valid_large_tag_lists() -> None:
    """Pinned ARS ``literature_corpus_entry`` sets no ``maxItems`` on ``tags``; the
    bridge must not impose a tighter cap than the authoritative schema."""

    entry = {
        **ARS_ENTRY,
        "tags": [f"KB-tag-{index:03d}" for index in range(257)],
    }
    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    entry_model = research_integrity.ARSLiteratureCorpusEntry.model_validate(
        entry, strict=True
    )
    assert entry_model.tags is not None and len(entry_model.tags) == 257
    source = _bridge(entry)

    assert source.bibliographic_sha256 == hashlib.sha256(
        canonical_json_bytes(entry)
    ).hexdigest()


def test_bridge_preserves_ars_valid_large_signal_lists() -> None:
    """Pinned ARS ``literature_corpus_entry`` sets no ``maxItems`` on
    ``bibliographic_integrity_signals``; the bridge must not impose a tighter cap
    than the authoritative schema, even with every signal individually valid."""

    signals: list[dict[str, object]] = []
    for index in range(257):
        signal = deepcopy(VALID_BIBLIOGRAPHIC_SIGNAL)
        signal["subject"]["citation_key"] = ARS_ENTRY["citation_key"]
        signal["signal_id"] = (
            f"bis:{ARS_ENTRY['citation_key']}:retraction_status_{index:03d}"
        )
        assert ARS_SIGNAL_VALIDATOR.is_valid(signal)
        signals.append(signal)
    entry = {**ARS_ENTRY, "bibliographic_integrity_signals": signals}

    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    entry_model = research_integrity.ARSLiteratureCorpusEntry.model_validate(
        entry, strict=True
    )
    assert (
        entry_model.bibliographic_integrity_signals is not None
        and len(entry_model.bibliographic_integrity_signals) == 257
    )
    source = _bridge(entry)

    assert source.bibliographic_sha256 == hashlib.sha256(
        canonical_json_bytes(entry)
    ).hexdigest()
    from arw.schema_registry import validate_instance

    validate_instance(
        "research-integrity-contracts.schema.json", source.model_dump(mode="json")
    )


def test_source_builder_revalidates_mutated_nested_ars_entry() -> None:
    signal = deepcopy(VALID_BIBLIOGRAPHIC_SIGNAL)
    signal["subject"]["citation_key"] = ARS_ENTRY["citation_key"]
    document = {**ARS_ENTRY, "bibliographic_integrity_signals": [signal]}
    entry = research_integrity.ARSLiteratureCorpusEntry.model_validate(
        document, strict=True
    )
    assert entry.bibliographic_integrity_signals is not None
    entry.bibliographic_integrity_signals[0]["subject"]["citation_key"] = "mutated2026"

    with pytest.raises(ValidationError, match="different citation key"):
        research_integrity.build_research_source_manifest(
            entry,
            source_id="source.paper-001",
            source_sha256=SOURCE_SHA256,
            imported_at="2026-08-26T01:03:00Z",
            imported_by="parent.runtime",
        )


def test_bundled_schema_lookup_rejects_symlink_root_and_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relative = (
        Path("skills/academic-research-suite/ars/shared/contracts/passport")
        / "bibliographic_integrity_signal.schema.json"
    )
    real_root = tmp_path / "real-plugin"
    schema = real_root / relative
    schema.parent.mkdir(parents=True)
    schema.write_text("{}\n", encoding="utf-8")
    linked_root = tmp_path / "linked-plugin"
    linked_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(linked_root))
    with pytest.raises(ValueError, match="plugin root.*unsafe"):
        research_integrity._ars_passport_schema_path(schema.name)

    declared_root = tmp_path / "declared-plugin"
    declared_root.mkdir()
    external = tmp_path / "external"
    external_schema = external / relative
    external_schema.parent.mkdir(parents=True)
    external_schema.write_text("{}\n", encoding="utf-8")
    (declared_root / "skills").symlink_to(external / "skills", target_is_directory=True)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(declared_root))
    with pytest.raises(ValueError, match="schema.*unsafe"):
        research_integrity._ars_passport_schema_path(schema.name)


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
    valid_signal = deepcopy(VALID_BIBLIOGRAPHIC_SIGNAL)
    valid_signal["subject"]["citation_key"] = ARS_ENTRY["citation_key"]
    valid_entry = {
        **ARS_ENTRY,
        "bibliographic_integrity_signals": [valid_signal],
    }
    assert ARS_SIGNAL_VALIDATOR.is_valid(valid_signal)
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

    with pytest.raises(ValueError, match="targets a different citation key"):
        _bridge(
            {
                **ARS_ENTRY,
                "bibliographic_integrity_signals": [VALID_BIBLIOGRAPHIC_SIGNAL],
            }
        )
    with pytest.raises(ValueError, match="signal IDs must be unique"):
        _bridge(
            {
                **ARS_ENTRY,
                "bibliographic_integrity_signals": [valid_signal, valid_signal],
            }
        )


def test_source_manifest_round_trips_every_aliased_csl_author_field() -> None:
    from arw.schema_registry import validate_instance

    source = _bridge(
        {
            **ARS_ENTRY,
            "authors": [
                {
                    "family": "Chen",
                    "given": "Ming",
                    "dropping-particle": "de",
                    "non-dropping-particle": "van",
                    "comma-suffix": True,
                    "static-ordering": False,
                    "parse-names": True,
                }
            ],
        }
    )
    document = source.model_dump(mode="json")
    author = document["authors"][0]
    assert {
        "dropping-particle",
        "non-dropping-particle",
        "comma-suffix",
        "static-ordering",
        "parse-names",
    } <= set(author)
    validate_instance("research-integrity-contracts.schema.json", document)
    assert (
        research_integrity.ResearchSourceManifest.model_validate_json(
            research_integrity.research_integrity_bytes(source), strict=True
        )
        == source
    )


def test_bridge_rejects_lookup_index_as_trusted_venue_source() -> None:
    with pytest.raises(ValueError, match="lookup index"):
        _bridge(
            {
                **ARS_ENTRY,
                "venue_type": "journal-article",
                "venue_type_provenance": "trusted_source_declared",
                "venue_type_source": "OpenAlex",
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
        standalone = model.model_json_schema(by_alias=True, mode="validation")
        standalone.pop("$defs", None)
        assert checked["$defs"][model.__name__] == standalone

    evidence_digests_schema = checked["$defs"]["ClaimEvidenceLink"]["properties"][
        "evidence_span_sha256"
    ]
    assert evidence_digests_schema["uniqueItems"]

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

    explicit_author_null = source.model_dump(mode="json")
    explicit_author_null["authors"][0]["given"] = None
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", explicit_author_null
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

    impossible_import = source.model_dump(mode="json")
    impossible_import["imported_at"] = "2026-99-99T99:99:99Z"
    with pytest.raises(ValidationError, match="date-time"):
        research_integrity.ResearchSourceManifest.model_validate_json(
            canonical_json_bytes(impossible_import), strict=True
        )
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance("research-integrity-contracts.schema.json", impossible_import)

    impossible_leap_second = source.model_dump(mode="json")
    impossible_leap_second["imported_at"] = "2026-01-01T12:34:60Z"
    with pytest.raises(ValidationError, match="date-time"):
        research_integrity.ResearchSourceManifest.model_validate_json(
            canonical_json_bytes(impossible_leap_second), strict=True
        )
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", impossible_leap_second
        )

    nul_source_pointer = source.model_dump(mode="json")
    nul_source_pointer["source_pointer"] = "file:///tmp/paper\x00.pdf"
    with pytest.raises(ValidationError, match="NUL"):
        research_integrity.ResearchSourceManifest.model_validate_json(
            canonical_json_bytes(nul_source_pointer), strict=True
        )
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", nul_source_pointer
        )

    for field, invalid_value in (
        ("doi", "not-a-doi"),
        ("arxiv_id", "2401/12345"),
    ):
        invalid_identifier = source.model_dump(mode="json")
        invalid_identifier[field] = invalid_value
        with pytest.raises(ValueError, match="instance validation failed"):
            validate_instance(
                "research-integrity-contracts.schema.json", invalid_identifier
            )

    unattributed_other = source.model_dump(mode="json")
    unattributed_other["authors"] = [{"family": "陈", "given": "明"}]
    unattributed_other["obtained_via"] = "other"
    unattributed_other["adapter_name"] = None
    with pytest.raises(ValidationError, match="requires adapter_name"):
        research_integrity.ResearchSourceManifest.model_validate_json(
            canonical_json_bytes(unattributed_other), strict=True
        )
    with pytest.raises(ValueError, match="semantic validation failed"):
        validate_instance(
            "research-integrity-contracts.schema.json", unattributed_other
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


# ---------------------------------------------------------------------------
# Long-field cases: the authoritative ARS ``literature_corpus_entry`` schema
# declares NO ``maxLength`` on these string mapping fields. The bridge must
# not impose tighter caps than the authoritative schema (Codex review
# 3881860978); non-ARS runtime bounds (EvidenceLocator.label,
# StableRuntimeId, ActorId, Sha256) are deliberately retained.
# ---------------------------------------------------------------------------

_LONG_ARS_FIELD_CASES: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "citation_key",
        {"citation_key": "L" + "a" * 256},  # 257 chars, pattern-safe
    ),
    ("title", {"title": "T" * 8193}),
    ("venue", {"venue": "V" * 8193}),
    ("source_pointer", {"source_pointer": "f" * 8193}),
    (
        "doi",
        {"doi": "10.1234/" + "x" * 2048},  # 2058 chars, no whitespace
    ),
    ("tag_item", {"tags": ["tag" + "x" * 8193]}),
    ("adapter_name", {"adapter_name": "a" * 257}),
    ("adapter_version", {"adapter_version": "v" * 257}),
    (
        "abstract",
        {"abstract": "A" * 1_000_001},
    ),
    (
        "user_notes",
        {"user_notes": "N" * 1_000_001},
    ),
    ("source_acquisition_path", {"source_acquisition_path": "P" * 8193}),
    (
        "description_last_audit",
        {"description_last_audit": "round" + "0" * 253},  # 258 chars
    ),
    ("venue_type_source", {"venue_type_source": "Y" * 8193}),
    (
        "csl_family",
        {"authors": [{"family": "F" * 8193}]},
    ),
    (
        "csl_given",
        {"authors": [{"family": "Smith", "given": "G" * 8193}]},
    ),
    (
        "csl_suffix",
        {"authors": [{"family": "Smith", "suffix": "S" * 1025}]},
    ),
    (
        "csl_dropping_particle",
        {"authors": [{"family": "Smith", "dropping-particle": "D" * 1025}]},
    ),
    (
        "csl_non_dropping_particle",
        {"authors": [{"family": "Smith", "non-dropping-particle": "N" * 1025}]},
    ),
)


@pytest.mark.parametrize(("label", "update"), _LONG_ARS_FIELD_CASES)
def test_bridge_preserves_authoritative_long_ars_mapping_fields(
    label: str, update: dict[str, object]
) -> None:
    """Pinned ARS ``literature_corpus_entry`` schema sets no ``maxLength`` on
    these mapping fields; the bridge must not impose tighter caps than the
    authoritative ARS schema (Codex review 3881860978 covers abstract /
    user_notes >1M and the long copied fields / CSL names / private fields).
    """

    from arw.schema_registry import validate_instance

    entry = {**ARS_ENTRY, **update}
    assert ARS_ENTRY_VALIDATOR.is_valid(entry), (
        f"authoritative ARS schema must accept the long {label} case"
    )

    research_integrity.ARSLiteratureCorpusEntry.model_validate(entry, strict=True)
    expected_digest = hashlib.sha256(canonical_json_bytes(entry)).hexdigest()
    source = _bridge(entry)
    assert source.bibliographic_sha256 == expected_digest, (
        "bridge digest must equal the canonical bytes of the supplied entry"
    )
    validate_instance(
        "research-integrity-contracts.schema.json",
        source.model_dump(mode="json"),
    )


def test_checked_installed_schema_drops_bridge_only_max_length_caps() -> None:
    """The checked research-integrity schema must mirror the
    authoritative no-max ARS mapping fields, while keeping non-ARS runtime
    bounds (EvidenceLocator.label) intact."""

    checked = _load_json_object(
        Path(__file__).resolve().parents[2]
        / "schemas/v1/research-integrity-contracts.schema.json"
    )
    generated = research_integrity.research_integrity_contracts_schema_document()
    assert checked == generated, "checked schema must equal the generated one"

    # ARS-mapping fields: ResearchSourceManifest copies these from the
    # authoritative ARS entry, so the checked schema MUST NOT impose a
    # maxLength on them.
    manifest_props = checked["$defs"]["ResearchSourceManifest"]["properties"]
    for field in (
        "citation_key",
        "title",
        "venue",
        "source_pointer",
        "doi",
        "adapter_name",
        "adapter_version",
    ):
        bound = manifest_props[field]
        if "anyOf" in bound:
            string_branches = [
                branch for branch in bound["anyOf"] if branch.get("type") == "string"
            ]
            assert string_branches, f"{field} must remain a string-or-null branch"
            for branch in string_branches:
                assert "maxLength" not in branch, (
                    f"ResearchSourceManifest.{field} retains a bridge-only "
                    f"maxLength={branch.get('maxLength')} cap"
                )
        else:
            assert bound.get("type") == "string", f"{field} must remain a string"
            assert "maxLength" not in bound, (
                f"ResearchSourceManifest.{field} retains a bridge-only "
                f"maxLength={bound.get('maxLength')} cap"
            )

    # EvidenceLocator.label keeps its bounded runtime cap.
    locator_props = checked["$defs"]["EvidenceLocator"]["properties"]["label"]
    label_branches = locator_props.get("anyOf", [locator_props])
    string_branches = [
        branch for branch in label_branches if branch.get("type") == "string"
    ]
    assert string_branches and any(
        branch.get("maxLength") == 256 for branch in string_branches
    ), "EvidenceLocator.label must keep its 256-char runtime cap"


def test_bridge_preserves_ars_valid_combined_long_field_entry() -> None:
    """One entry exercising every long-field path simultaneously still binds,
    digests canonically, and round-trips through the installed schema."""

    from arw.schema_registry import validate_instance

    entry = {
        **ARS_ENTRY,
        "title": "T" * 8193,
        "venue": "V" * 8193,
        "source_pointer": "S" * 8193,
        "doi": "10.1234/" + "x" * 2048,
        "tags": ["tag" + "x" * 8193],
        "adapter_name": "a" * 257,
        "adapter_version": "v" * 257,
        "abstract": "A" * 1_000_001,
        "user_notes": "N" * 1_000_001,
        "source_acquisition_path": "P" * 8193,
        "venue_type_source": "Y" * 8193,
        "authors": [
            {
                "family": "F" * 8193,
                "given": "G" * 8193,
                "suffix": "S" * 1025,
                "dropping-particle": "D" * 1025,
                "non-dropping-particle": "N" * 1025,
            }
        ],
    }
    assert ARS_ENTRY_VALIDATOR.is_valid(entry)
    research_integrity.ARSLiteratureCorpusEntry.model_validate(entry, strict=True)
    expected_digest = hashlib.sha256(canonical_json_bytes(entry)).hexdigest()
    source = _bridge(entry)
    assert source.bibliographic_sha256 == expected_digest
    validate_instance(
        "research-integrity-contracts.schema.json",
        source.model_dump(mode="json"),
    )


def test_bridge_still_enforces_authoritative_patterns_on_long_fields() -> None:
    """Removing the bridge-only maxLength must not weaken the authoritative
    pattern / format / NUL / cross-field / allOf rules."""

    # DOI with whitespace remains rejected (authoritative pattern)
    with pytest.raises(ValueError, match="ARS literature entry"):
        _bridge({**ARS_ENTRY, "doi": "10.1234/example with space"})

    # citation_key starting with a digit remains rejected (authoritative pattern)
    with pytest.raises(ValueError, match="ARS literature entry"):
        _bridge({**ARS_ENTRY, "citation_key": "1" + "a" * 257})

    # NUL in source_pointer still rejected
    with pytest.raises(ValueError, match="ARS literature entry"):
        _bridge({**ARS_ENTRY, "source_pointer": "ok\x00nope"})

    # date-time format still enforced on long entries
    with pytest.raises(ValueError, match="ARS literature entry"):
        _bridge({**ARS_ENTRY, "obtained_at": "yesterday"})

    # CSL non-dropping-particle on a long entry still emits the
    # dropping-particle alias wire-format and preserves the canonical field.
    long_entry = {
        **ARS_ENTRY,
        "authors": [
            {
                "family": "F" * 1024,
                "dropping-particle": "D" * 1025,
                "non-dropping-particle": "N" * 1025,
            }
        ],
    }
    assert ARS_ENTRY_VALIDATOR.is_valid(long_entry)
    source = _bridge(long_entry)
    dumped = source.model_dump(mode="json")
    assert dumped["authors"][0].get("dropping-particle") == "D" * 1025
    assert dumped["authors"][0].get("non-dropping-particle") == "N" * 1025


# ---------------------------------------------------------------------------
# Builder strict revalidation: every public builder must revalidate nested
# Pydantic model parameters from canonical bytes before constructing its
# output. ``model_copy(update=...)`` deliberately skips validation (see
# ``arw.models._phase4_record``), so a builder that hands a nested model
# directly to its output model would let bogus ``EvidenceLocator`` literals,
# overlong labels, etc. slip through. The whole-chain validator only fires
# when the caller explicitly invokes it; the builders themselves must fail
# closed at the construction boundary (Codex review 3882364624).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ("mutation_via_model_copy",),
)
def test_evidence_span_builder_revalidates_locator_from_canonical_bytes(
    label: str,
) -> None:
    """``build_evidence_span`` must refuse a ``model_copy(update=...)``
    locator that violates the strict ``EvidenceLocator`` constraints."""

    source = _source()
    base_locator = research_integrity.EvidenceLocator(
        kind="page", start=1, end=2, label="page 1"
    )

    bogus_kind = base_locator.model_copy(update={"kind": "bogus"})
    with pytest.raises(ValidationError, match="Input should be"):
        research_integrity.build_evidence_span(
            source,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=bogus_kind,
            extracted_text_sha256=TEXT_SHA256,
        )

    overlong_label = base_locator.model_copy(update={"label": "X" * 257})
    with pytest.raises(ValidationError, match="at most 256 characters"):
        research_integrity.build_evidence_span(
            source,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=overlong_label,
            extracted_text_sha256=TEXT_SHA256,
        )

    empty_label = base_locator.model_copy(update={"label": ""})
    with pytest.raises(ValidationError, match="at least 1 character"):
        research_integrity.build_evidence_span(
            source,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=empty_label,
            extracted_text_sha256=TEXT_SHA256,
        )

    negative_start = base_locator.model_copy(update={"start": -1})
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        research_integrity.build_evidence_span(
            source,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=negative_start,
            extracted_text_sha256=TEXT_SHA256,
        )


def test_claim_link_builder_revalidates_each_evidence_span_from_canonical_bytes() -> (
    None
):
    """``build_claim_evidence_link`` must refuse an ``EvidenceSpan`` whose
    nested ``locator`` was mutated via ``model_copy(update=...)`` to violate
    the strict ``EvidenceLocator`` constraints."""

    source = _source()
    locator = research_integrity.EvidenceLocator(
        kind="page", start=1, end=2, label="page 1"
    )
    span = research_integrity.build_evidence_span(
        source,
        evidence_span_id="span.paper-001.001",
        extraction_registration_sha256=EXTRACTION_SHA256,
        locator=locator,
        extracted_text_sha256=TEXT_SHA256,
    )

    mutated_locator = locator.model_copy(update={"kind": "bogus"})
    mutated_span = span.model_copy(update={"locator": mutated_locator})
    assert mutated_span.locator.kind == "bogus"

    with pytest.raises(ValidationError, match="Input should be"):
        research_integrity.build_claim_evidence_link(
            (mutated_span,),
            claim_link_id="link.claim-001",
            claim_id="claim.paper-001",
            claim_sha256=CLAIM_SHA256,
            relation="supports",
        )

    mutated_label = locator.model_copy(update={"label": "X" * 257})
    mutated_label_span = span.model_copy(update={"locator": mutated_label})
    with pytest.raises(ValidationError, match="at most 256 characters"):
        research_integrity.build_claim_evidence_link(
            (mutated_label_span,),
            claim_link_id="link.claim-001",
            claim_id="claim.paper-001",
            claim_sha256=CLAIM_SHA256,
            relation="supports",
        )


def test_evidence_span_builder_still_accepts_a_freshly_constructed_locator() -> None:
    """The new strict revalidation must not regress builders that receive a
    locator constructed through the normal ``EvidenceLocator(...)`` path."""

    source = _source()
    locator = research_integrity.EvidenceLocator(
        kind="section", start=10, end=42, label="methods"
    )
    span = research_integrity.build_evidence_span(
        source,
        evidence_span_id="span.paper-001.001",
        extraction_registration_sha256=EXTRACTION_SHA256,
        locator=locator,
        extracted_text_sha256=TEXT_SHA256,
    )
    assert span.locator == locator


def test_evidence_span_builder_revalidates_source_from_canonical_bytes() -> None:
    """``build_evidence_span`` must revalidate the supplied
    ``ResearchSourceManifest`` from canonical bytes before deriving
    ``research_source_manifest_sha256``. A ``model_copy(update=...)``
    mutation that violates the strict ``ResearchSourceManifest`` contract
    must fail closed at the builder boundary (Codex review 3882364624)."""

    source = _source()
    locator = research_integrity.EvidenceLocator(
        kind="page", start=1, end=2, label="page 1"
    )

    bogus_schema_version = source.model_copy(
        update={"schema_version": "arw.bogus.v1"}
    )
    assert bogus_schema_version.schema_version == "arw.bogus.v1"
    with pytest.raises(ValidationError, match="schema_version"):
        research_integrity.build_evidence_span(
            bogus_schema_version,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=locator,
            extracted_text_sha256=TEXT_SHA256,
        )

    bogus_source_id = source.model_copy(
        update={"source_id": "Bogus-Capitalised"}
    )
    assert bogus_source_id.source_id == "Bogus-Capitalised"
    with pytest.raises(ValidationError, match="source_id"):
        research_integrity.build_evidence_span(
            bogus_source_id,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=locator,
            extracted_text_sha256=TEXT_SHA256,
        )

    bogus_citation_key = source.model_copy(update={"citation_key": "1bad-key"})
    assert bogus_citation_key.citation_key == "1bad-key"
    with pytest.raises(ValidationError, match="citation_key"):
        research_integrity.build_evidence_span(
            bogus_citation_key,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=locator,
            extracted_text_sha256=TEXT_SHA256,
        )

    bogus_source_sha256 = source.model_copy(
        update={"source_sha256": "not-a-real-sha256"}
    )
    assert bogus_source_sha256.source_sha256 == "not-a-real-sha256"
    with pytest.raises(ValidationError, match="source_sha256"):
        research_integrity.build_evidence_span(
            bogus_source_sha256,
            evidence_span_id="span.paper-001.001",
            extraction_registration_sha256=EXTRACTION_SHA256,
            locator=locator,
            extracted_text_sha256=TEXT_SHA256,
        )


def test_evidence_span_builder_still_accepts_a_freshly_constructed_source() -> None:
    """The new source strict revalidation must not regress the normal
    ``research_source_from_ars_entry`` → ``build_evidence_span`` flow."""

    source = _source()
    locator = research_integrity.EvidenceLocator(
        kind="section", start=10, end=42, label="methods"
    )
    span = research_integrity.build_evidence_span(
        source,
        evidence_span_id="span.paper-001.001",
        extraction_registration_sha256=EXTRACTION_SHA256,
        locator=locator,
        extracted_text_sha256=TEXT_SHA256,
    )
    assert span.source_id == source.source_id
    assert span.research_source_manifest_sha256 == research_integrity.research_integrity_sha256(
        source
    )
