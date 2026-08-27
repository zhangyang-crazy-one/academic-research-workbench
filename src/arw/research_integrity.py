"""Pure ARS-to-ARW research-integrity contract bridge.

This module never loads YAML, fetches source material, writes canonical state,
or admits evidence. The parent remains the sole ``ArtifactAcceptanceRequest``
-> ``ArtifactManifest`` -> accepted Material Passport hash authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import jsonschema
from pydantic import (
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from arw.canonical import canonical_json_bytes, sha256_hex
from arw.integration_lock import IntegrationDiagnosticReport
from arw.models import ActorId, Sha256, StableRuntimeId, StrictModel, UtcTimestamp

CitationKey = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z][A-Za-z0-9_:-]*$",
    ),
]
BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=8192)]
AdapterIdentity = Annotated[str, StringConstraints(min_length=1, max_length=256)]
ArxivId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^([A-Za-z][A-Za-z0-9-]*(\.[A-Za-z0-9-]+)*/\d{7}"
            r"(v[1-9]\d*)?|\d{4}\.\d{4,5}(v[1-9]\d*)?)$"
        ),
    ),
]
_LOOKUP_SIGNAL_FIELDS = frozenset(
    {
        "semantic_scholar_unmatched",
        "openalex_unmatched",
        "crossref_unmatched",
        "arxiv_unmatched",
    }
)

_ARS_PASSPORT_SCHEMA_RELATIVE = Path(
    "skills/academic-research-suite/ars/shared/contracts/passport"
)
_ARS_PASSPORT_SCHEMA_NAMES = frozenset(
    {
        "bibliographic_integrity_signal.schema.json",
    }
)
_FORMAT_CHECKER = jsonschema.FormatChecker()


def _ars_passport_schema_path(name: str) -> Path:
    if name not in _ARS_PASSPORT_SCHEMA_NAMES:
        raise ValueError(f"unsupported bundled ARS passport schema: {name}")
    plugin_root = os.environ.get("ARW_PLUGIN_ROOT")
    root = (
        Path(plugin_root).resolve()
        if plugin_root
        else Path(__file__).resolve().parents[2]
    )
    candidate = root / _ARS_PASSPORT_SCHEMA_RELATIVE / name
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"bundled ARS passport schema is missing or unsafe: {name}")
    return candidate.resolve()


@lru_cache(maxsize=4)
def _ars_passport_validator(schema_path: str) -> jsonschema.Draft202012Validator:
    path = Path(schema_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"bundled ARS passport schema is unreadable: {path.name}") from error
    if not isinstance(document, dict):
        raise ValueError(f"bundled ARS passport schema is not an object: {path.name}")
    try:
        jsonschema.Draft202012Validator.check_schema(document)
    except jsonschema.SchemaError as error:
        raise ValueError(f"bundled ARS passport schema is invalid: {path.name}") from error
    return jsonschema.Draft202012Validator(
        document,
        format_checker=_FORMAT_CHECKER,
    )


def _validator_for_ars_passport_schema(
    name: str,
) -> jsonschema.Draft202012Validator:
    return _ars_passport_validator(str(_ars_passport_schema_path(name)))


def _reject_explicit_nulls(
    value: Any,
    *,
    document: str,
    allowed: frozenset[str] = frozenset(),
) -> Any:
    if not isinstance(value, Mapping):
        return value
    rejected = sorted(
        key for key, item in value.items() if item is None and key not in allowed
    )
    if rejected:
        raise ValueError(
            f"{document} fields do not permit explicit null: {', '.join(rejected)}"
        )
    return value


class ResearchIntegrityError(ValueError):
    """A supplied document does not form one exact canonical evidence chain."""


class CSLPersonalName(StrictModel):

    family: BoundedText
    given: Annotated[str, StringConstraints(max_length=8192)] | None = None
    suffix: Annotated[str, StringConstraints(max_length=1024)] | None = None
    dropping_particle: Annotated[str, StringConstraints(max_length=1024)] | None = Field(
        default=None, alias="dropping-particle"
    )
    non_dropping_particle: Annotated[
        str, StringConstraints(max_length=1024)
    ] | None = Field(default=None, alias="non-dropping-particle")
    comma_suffix: str | bool | None = Field(default=None, alias="comma-suffix")
    static_ordering: str | bool | None = Field(default=None, alias="static-ordering")
    parse_names: str | bool | None = Field(default=None, alias="parse-names")

    @model_validator(mode="before")
    @classmethod
    def explicit_nulls_are_forbidden(cls, value: Any) -> Any:
        return _reject_explicit_nulls(value, document="CSL personal name")


class CSLLiteralName(StrictModel):
    literal: BoundedText


CSLName = CSLPersonalName | CSLLiteralName


class ContaminationSignals(StrictModel):
    preprint_post_llm_inflection: bool | None = None
    semantic_scholar_unmatched: bool | None = None
    openalex_unmatched: bool | None = None
    crossref_unmatched: bool | None = None
    arxiv_unmatched: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_nulls_are_forbidden(cls, value: Any) -> Any:
        return _reject_explicit_nulls(value, document="contamination signals")


class ContaminationSignalOmissions(StrictModel):
    semantic_scholar_unmatched: Literal["api_degraded"] | None = None
    openalex_unmatched: Literal["api_degraded"] | None = None
    crossref_unmatched: Literal["api_degraded"] | None = None
    arxiv_unmatched: Literal["api_degraded"] | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_nulls_are_forbidden(cls, value: Any) -> Any:
        return _reject_explicit_nulls(value, document="contamination signal omissions")

    @model_validator(mode="after")
    def at_least_one_reason(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("contamination omissions require at least one reason")
        return self


class ARSLiteratureCorpusEntry(StrictModel):
    """In-memory projection of one strict ARS ``literature_corpus[]`` entry."""

    citation_key: CitationKey
    title: BoundedText
    authors: list[CSLName] = Field(min_length=1, max_length=256)
    year: Annotated[int, Field(ge=1000, le=2100)]
    source_pointer: BoundedText
    venue: BoundedText | None = None
    doi: Annotated[
        str,
        StringConstraints(max_length=2048, pattern=r"^10\.[0-9]{4,9}/[^\s]+$"),
    ] | None = None
    arxiv_id: ArxivId | None = None
    tags: list[BoundedText] | None = Field(default=None, max_length=256)
    obtained_via: Literal[
        "zotero-api",
        "zotero-bbt-export",
        "obsidian-vault",
        "folder-scan",
        "manual",
        "other",
    ] | None = None
    obtained_at: BoundedText | None = None
    adapter_name: AdapterIdentity | None = None
    adapter_version: AdapterIdentity | None = None
    abstract: Annotated[str, StringConstraints(max_length=1_000_000)] | None = None
    user_notes: Annotated[str, StringConstraints(max_length=1_000_000)] | None = None
    source_acquired: bool | None = None
    source_acquisition_date: BoundedText | None = None
    source_acquisition_path: BoundedText | None = None
    source_verified_against_original: bool | None = None
    source_verification_method: Literal[
        "codex_audit", "manual_grep", "vision_check", "none"
    ] | None = None
    description_source: Annotated[
        str,
        StringConstraints(
            pattern=r"^(original_pdf|bibliography_v[0-9]+|secondary_summary)$"
        ),
    ] | None = None
    description_last_audit: Annotated[
        str, StringConstraints(max_length=256)
    ] | None = None
    contamination_signals_backfilled_at: BoundedText | None = None
    contamination_signals: ContaminationSignals | None = None
    venue_type: Literal[
        "journal-article",
        "conference-paper",
        "book",
        "chapter",
        "dissertation",
        "preprint",
        "report",
        "dataset",
        "other",
        "unknown",
    ] | None = None
    venue_type_provenance: Literal[
        "adapter_declared",
        "user_declared",
        "trusted_source_declared",
        "unknown",
    ] | None = None
    venue_type_source: BoundedText | None = None
    contamination_signal_omissions: ContaminationSignalOmissions | None = None
    bibliographic_integrity_signals: list[dict[str, Any]] | None = Field(
        default=None, max_length=256
    )

    @model_validator(mode="before")
    @classmethod
    def explicit_nulls_match_authoritative_schema(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            document="ARS literature entry",
            allowed=frozenset({"description_last_audit"}),
        )

    @field_validator("source_pointer")
    @classmethod
    def source_pointer_is_bounded_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("source pointer cannot contain NUL")
        return value

    @field_validator(
        "obtained_at",
        "source_acquisition_date",
        "contamination_signals_backfilled_at",
    )
    @classmethod
    def date_times_match_authoritative_schema(cls, value: str | None) -> str | None:
        if value is not None and not _FORMAT_CHECKER.conforms(value, "date-time"):
            raise ValueError("ARS literature entry date-time field is invalid")
        return value

    @field_validator("bibliographic_integrity_signals")
    @classmethod
    def bibliographic_signals_match_authoritative_schema(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        if value is None:
            return value
        validator = _validator_for_ars_passport_schema(
            "bibliographic_integrity_signal.schema.json"
        )
        for index, signal in enumerate(value):
            error = next(validator.iter_errors(signal), None)
            if error is None:
                continue
            location = ".".join(str(item) for item in error.absolute_path) or "$"
            raise ValueError(
                "bibliographic integrity signal "
                f"{index} violates the authoritative schema at {location} "
                f"({error.validator})"
            )
        return value

    @model_validator(mode="after")
    def dependent_ars_fields_are_complete(self) -> Self:
        if self.obtained_via == "other" and self.adapter_name is None:
            raise ValueError("obtained_via=other requires adapter_name")
        if self.source_verified_against_original and (
            not self.source_acquired
            or self.source_verification_method in {None, "none"}
        ):
            raise ValueError("verified source metadata lacks acquired-source evidence")
        if (
            isinstance(self.source_acquired, bool)
            and not self.source_acquired
            and self.description_last_audit != "none"
        ):
            raise ValueError("unacquired sources require description_last_audit=none")
        signal_fields = (
            self.contamination_signals.model_fields_set
            if self.contamination_signals is not None
            else set()
        )
        omission_fields = (
            self.contamination_signal_omissions.model_fields_set
            if self.contamination_signal_omissions is not None
            else set()
        )
        if (
            self.contamination_signals is not None
            and self.contamination_signals.preprint_post_llm_inflection
            and self.year < 2024
        ):
            raise ValueError("post-LLM-inflection preprint signal requires year >= 2024")
        if self.obtained_via == "manual" and signal_fields & _LOOKUP_SIGNAL_FIELDS:
            raise ValueError("manual entries cannot carry lookup contamination signals")
        if (
            self.obtained_via == "manual"
            and self.contamination_signal_omissions is not None
        ):
            raise ValueError("manual entries cannot carry lookup omission reasons")
        overlapping_signals = signal_fields & omission_fields
        if overlapping_signals:
            raise ValueError(
                "computed and omitted contamination signals overlap: "
                + ", ".join(sorted(overlapping_signals))
            )
        if "arxiv_unmatched" in omission_fields and self.arxiv_id is None:
            raise ValueError("arxiv_unmatched omission requires arxiv_id")
        if (self.venue_type is None) != (self.venue_type_provenance is None):
            raise ValueError("venue type and provenance must be provided together")
        if self.venue_type == "unknown" and self.venue_type_provenance != "unknown":
            raise ValueError("unknown venue type requires unknown provenance")
        if (
            self.venue_type_provenance == "trusted_source_declared"
            and self.venue_type_source is None
        ):
            raise ValueError("trusted venue provenance requires its named source")
        return self


class ResearchSourceManifest(StrictModel):
    """Digest-bound source proposal; parent artifact acceptance is still authoritative."""

    schema_version: Literal["arw.research-source-manifest.v1"]
    source_id: StableRuntimeId
    citation_key: CitationKey
    title: BoundedText
    authors: tuple[CSLName, ...] = Field(min_length=1, max_length=256)
    year: Annotated[int, Field(ge=1000, le=2100)]
    venue: BoundedText | None
    doi: Annotated[str, StringConstraints(max_length=2048)] | None
    arxiv_id: Annotated[str, StringConstraints(max_length=256)] | None
    source_pointer: BoundedText
    source_sha256: Sha256
    bibliographic_sha256: Sha256
    obtained_via: AdapterIdentity | None
    adapter_name: AdapterIdentity | None
    adapter_version: AdapterIdentity | None
    imported_at: UtcTimestamp
    imported_by: ActorId



class EvidenceLocator(StrictModel):
    kind: Literal["page", "line", "byte", "section"]
    start: Annotated[int, Field(ge=0, le=10_000_000)]
    end: Annotated[int, Field(ge=1, le=10_000_001)]
    label: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("evidence locator end must follow start")
        return self


class EvidenceSpan(StrictModel):
    """Text-free evidence proposal; only the parent may admit its artifact manifest."""

    schema_version: Literal["arw.evidence-span.v1"]
    evidence_span_id: StableRuntimeId
    source_id: StableRuntimeId
    research_source_manifest_sha256: Sha256
    source_sha256: Sha256
    extraction_registration_sha256: Sha256
    locator: EvidenceLocator
    extracted_text_sha256: Sha256


class ClaimEvidenceLink(StrictModel):
    """Claim linkage proposal; it has no gate, retry, or Passport authority."""

    schema_version: Literal["arw.claim-evidence-link.v1"]
    claim_link_id: StableRuntimeId
    claim_id: StableRuntimeId
    claim_sha256: Sha256
    evidence_span_sha256: tuple[Sha256, ...] = Field(min_length=1, max_length=128)
    relation: Literal["supports", "contradicts", "contextualizes"]

    @model_validator(mode="after")
    def evidence_digests_are_canonical(self) -> Self:
        if tuple(sorted(set(self.evidence_span_sha256))) != self.evidence_span_sha256:
            raise ValueError("evidence span digests must be unique and canonically ordered")
        return self


ResearchIntegrityDocument = ResearchSourceManifest | EvidenceSpan | ClaimEvidenceLink
ResearchIntegrityContract = Annotated[
    IntegrationDiagnosticReport | ResearchIntegrityDocument,
    Field(discriminator="schema_version"),
]


def _ars_entry_document(entry: ARSLiteratureCorpusEntry) -> dict[str, object]:
    return entry.model_dump(
        mode="json",
        by_alias=True,
        exclude_unset=True,
    )


def research_integrity_bytes(document: StrictModel) -> bytes:
    """Return exact canonical bytes for one supplied immutable document."""

    return canonical_json_bytes(document.model_dump(mode="json"))


def research_integrity_sha256(document: StrictModel) -> str:
    return sha256_hex(research_integrity_bytes(document))


def build_research_source_manifest(
    entry: ARSLiteratureCorpusEntry,
    *,
    source_id: str,
    source_sha256: str,
    imported_at: str,
    imported_by: str,
) -> ResearchSourceManifest:
    """Build a source proposal from the exact validated in-memory ARS entry."""

    bibliographic_sha256 = sha256_hex(canonical_json_bytes(_ars_entry_document(entry)))
    return ResearchSourceManifest(
        schema_version="arw.research-source-manifest.v1",
        source_id=source_id,
        citation_key=entry.citation_key,
        title=entry.title,
        authors=tuple(entry.authors),
        year=entry.year,
        venue=entry.venue,
        doi=entry.doi,
        arxiv_id=entry.arxiv_id,
        source_pointer=entry.source_pointer,
        source_sha256=source_sha256,
        bibliographic_sha256=bibliographic_sha256,
        obtained_via=entry.obtained_via,
        adapter_name=entry.adapter_name,
        adapter_version=entry.adapter_version,
        imported_at=imported_at,
        imported_by=imported_by,
    )


def research_source_from_ars_entry(
    entry: Mapping[str, object],
    *,
    source_id: str,
    source_sha256: str,
    imported_at: str,
    imported_by: str,
) -> ResearchSourceManifest:
    """Validate an already-parsed ARS entry and bind its complete canonical bytes."""

    try:
        validated = ARSLiteratureCorpusEntry.model_validate(dict(entry), strict=True)
    except (TypeError, ValueError, ValidationError) as error:
        raise ResearchIntegrityError(f"ARS literature entry is invalid: {error}") from error
    try:
        return build_research_source_manifest(
            validated,
            source_id=source_id,
            source_sha256=source_sha256,
            imported_at=imported_at,
            imported_by=imported_by,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise ResearchIntegrityError(f"research source identity is invalid: {error}") from error


def build_evidence_span(
    source: ResearchSourceManifest,
    *,
    evidence_span_id: str,
    extraction_registration_sha256: str,
    locator: EvidenceLocator,
    extracted_text_sha256: str,
) -> EvidenceSpan:
    """Bind exact source-manifest bytes and propagate the source-content digest."""

    return EvidenceSpan(
        schema_version="arw.evidence-span.v1",
        evidence_span_id=evidence_span_id,
        source_id=source.source_id,
        research_source_manifest_sha256=research_integrity_sha256(source),
        source_sha256=source.source_sha256,
        extraction_registration_sha256=extraction_registration_sha256,
        locator=locator,
        extracted_text_sha256=extracted_text_sha256,
    )


def build_claim_evidence_link(
    evidence_spans: Sequence[EvidenceSpan],
    *,
    claim_link_id: str,
    claim_id: str,
    claim_sha256: str,
    relation: Literal["supports", "contradicts", "contextualizes"],
) -> ClaimEvidenceLink:
    """Bind a claim to the exact canonical bytes of unique evidence spans."""

    digests = tuple(research_integrity_sha256(span) for span in evidence_spans)
    if not digests or len(digests) != len(set(digests)):
        raise ResearchIntegrityError("claim links require unique non-empty evidence spans")
    return ClaimEvidenceLink(
        schema_version="arw.claim-evidence-link.v1",
        claim_link_id=claim_link_id,
        claim_id=claim_id,
        claim_sha256=claim_sha256,
        evidence_span_sha256=tuple(sorted(digests)),
        relation=relation,
    )


def validate_research_integrity_chain(
    *,
    sources: Sequence[ResearchSourceManifest],
    evidence_spans: Sequence[EvidenceSpan],
    claim_links: Sequence[ClaimEvidenceLink],
) -> None:
    """Recompute every supplied document digest and reject replacement or mutation."""

    source_map: dict[str, tuple[str, str]] = {}
    citation_keys: set[str] = set()
    for source in sources:
        if source.source_id in source_map:
            raise ResearchIntegrityError("duplicate research source ID")
        if source.citation_key in citation_keys:
            raise ResearchIntegrityError("duplicate citation key")
        citation_keys.add(source.citation_key)
        source_map[source.source_id] = (
            research_integrity_sha256(source),
            source.source_sha256,
        )

    span_ids: set[str] = set()
    span_digests: set[str] = set()
    for span in evidence_spans:
        if span.evidence_span_id in span_ids:
            raise ResearchIntegrityError("duplicate evidence span ID")
        span_ids.add(span.evidence_span_id)
        source_binding = source_map.get(span.source_id)
        if source_binding is None:
            raise ResearchIntegrityError("evidence span references a missing source")
        source_manifest_sha256, source_sha256 = source_binding
        if span.research_source_manifest_sha256 != source_manifest_sha256:
            raise ResearchIntegrityError("source manifest digest substitution detected")
        if span.source_sha256 != source_sha256:
            raise ResearchIntegrityError("source content digest propagation failed")
        span_digest = research_integrity_sha256(span)
        if span_digest in span_digests:
            raise ResearchIntegrityError("duplicate canonical evidence span document")
        span_digests.add(span_digest)

    link_ids: set[str] = set()
    claim_digests: dict[str, str] = {}
    for link in claim_links:
        if link.claim_link_id in link_ids:
            raise ResearchIntegrityError("duplicate claim-evidence link ID")
        link_ids.add(link.claim_link_id)
        existing_claim_digest = claim_digests.get(link.claim_id)
        if existing_claim_digest is None:
            claim_digests[link.claim_id] = link.claim_sha256
        elif existing_claim_digest != link.claim_sha256:
            raise ResearchIntegrityError("conflicting claim content digest")
        if tuple(sorted(set(link.evidence_span_sha256))) != link.evidence_span_sha256:
            raise ResearchIntegrityError("claim evidence digests are not canonical")
        missing = set(link.evidence_span_sha256) - span_digests
        if missing:
            raise ResearchIntegrityError("claim link references substituted evidence bytes")


def research_integrity_contracts_schema_document() -> dict[str, Any]:
    """Generate the discriminated installed schema directly from strict models."""

    document = TypeAdapter(ResearchIntegrityContract).json_schema(
        by_alias=False, mode="validation"
    )
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/"
        "research-integrity-contracts.schema.json"
    )
    document["title"] = "ARW Research Integrity Contracts"
    document["description"] = (
        "Read-only diagnostic and evidence documents. Hooks remain observational; "
        "the parent alone owns canonical state, evidence admission, retries, "
        "provenance, gates, ArtifactAcceptanceRequest, ArtifactManifest, and "
        "accepted Material Passport hashes."
    )
    return document


__all__ = (
    "ARSLiteratureCorpusEntry",
    "ClaimEvidenceLink",
    "EvidenceLocator",
    "EvidenceSpan",
    "ResearchIntegrityError",
    "ResearchSourceManifest",
    "build_claim_evidence_link",
    "build_evidence_span",
    "build_research_source_manifest",
    "research_integrity_bytes",
    "research_integrity_contracts_schema_document",
    "research_integrity_sha256",
    "research_source_from_ars_entry",
    "validate_research_integrity_chain",
)
