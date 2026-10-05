"""Bounded, source-bound venue evidence; editorial patterns confer no authority."""

import json
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.narrative import ArgumentFunction

ShortText = Annotated[str, Field(min_length=1, max_length=1200)]
FullTextAccess = Literal[
    "official_full_text", "accepted_author_full_text", "preprint_full_text"
]
NEW_OPTIONAL_PROVENANCE_FIELDS = (
    "document_version",
    "source_authority",
    "related_formal_publication_url",
    "related_formal_publication_doi",
    "version_relationship_note",
)


class SectionAnnotation(StrictModel):
    section: ShortText
    locator: ShortText
    function: ArgumentFunction


class VenueSourceReview(StrictModel):
    schema_version: Literal["arw.venue-source-review.v1"] = "arw.venue-source-review.v1"
    review_id: StableRuntimeId
    source_artifact_id: StableRuntimeId
    source_sha256: Sha256
    official_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    doi: ShortText | None = None
    accepted_category: ShortText
    accepted_year: Annotated[int, Field(ge=1900, le=2200)]
    access_basis: Literal["official_full_text", "official_metadata_only"]
    reviewer: ShortText
    decision: Literal["VERIFIED"]


class VenueExemplar(StrictModel):
    schema_version: Literal["arw.venue-exemplar.v1"] = "arw.venue-exemplar.v1"
    exemplar_id: StableRuntimeId
    doi: ShortText | None = None
    official_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    source_sha256: Sha256
    source_artifact_id: StableRuntimeId
    source_review_artifact_id: StableRuntimeId
    source_reviewer: ShortText
    accepted_category: ShortText
    accepted_year: Annotated[int, Field(ge=1900, le=2200)]
    venue_id: StableRuntimeId
    domain_id: StableRuntimeId
    sections: tuple[SectionAnnotation, ...] = Field(default=(), max_length=64)
    figure_roles: tuple[ShortText, ...] = Field(default=(), max_length=32)
    evidence_forms: tuple[ShortText, ...] = Field(default=(), max_length=32)
    observed_patterns: tuple[ShortText, ...] = Field(default=(), max_length=32)
    access_basis: Literal["official_full_text", "official_metadata_only"]

    @model_validator(mode="after")
    def validate_structure(self):
        if self.access_basis == "official_full_text" and {
            item.function for item in self.sections
        } != set(ArgumentFunction.__args__):
            raise ValueError("full-text annotations must cover all six functions")
        if len(set(self.evidence_forms)) != len(self.evidence_forms):
            raise ValueError("evidence forms must be distinct")
        if self.access_basis == "official_metadata_only" and (
            self.sections
            or self.figure_roles
            or self.evidence_forms
            or self.observed_patterns
        ):
            raise ValueError(
                "metadata-only sources cannot assert full-text observations"
            )
        return self


class ReviewedPdfProvenance(StrictModel):
    """Agent review provenance for transient PDF bytes, never an author attestation."""

    pdf_sha256: Sha256
    pdf_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    pdf_byte_count: Annotated[int, Field(ge=1, le=64 * 1024 * 1024)]
    pdf_page_count: Annotated[int, Field(ge=1, le=10000)]
    extractor: ShortText
    reviewer: ShortText
    review_authority: Literal["agent_source_review"] = "agent_source_review"
    read_scope: tuple[ShortText, ...] = Field(min_length=1, max_length=64)
    limitations: tuple[ShortText, ...] = Field(min_length=1, max_length=32)
    document_version: (
        Literal["publisher_version", "accepted_author_manuscript", "author_preprint"]
        | None
    ) = None
    source_authority: (
        Literal["official_publisher", "author_repository", "preprint_repository"] | None
    ) = None
    related_formal_publication_url: (
        Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)] | None
    ) = None
    related_formal_publication_doi: ShortText | None = None
    version_relationship_note: ShortText | None = None


def validate_full_text_access(access_basis, provenance):
    if access_basis == "official_full_text":
        if provenance.document_version not in {
            None,
            "publisher_version",
        } or provenance.source_authority not in {None, "official_publisher"}:
            raise ValueError(
                "official full text cannot declare an author/preprint source version"
            )
    else:
        expected = (
            "accepted_author_manuscript"
            if access_basis == "accepted_author_full_text"
            else "author_preprint"
        )
        if (
            provenance.document_version != expected
            or provenance.source_authority
            not in {"author_repository", "preprint_repository"}
        ):
            raise ValueError(
                "non-publisher full text requires explicit matching document version and repository authority"
            )
        if not provenance.version_relationship_note:
            raise ValueError(
                "non-publisher full text requires a version relationship note"
            )


class ReviewedSectionAnnotation(StrictModel):
    function: ArgumentFunction
    status: Literal["observed", "unknown"]
    section: ShortText | None = None
    locator: ShortText | None = None
    paraphrase: ShortText | None = None
    unknown_reason: ShortText | None = None

    @model_validator(mode="after")
    def honest_observation(self):
        if self.status == "observed":
            if (
                not all((self.section, self.locator, self.paraphrase))
                or self.unknown_reason
            ):
                raise ValueError(
                    "observed function requires section, locator and paraphrase"
                )
        elif not self.unknown_reason or any(
            (self.section, self.locator, self.paraphrase)
        ):
            raise ValueError(
                "unknown function requires reason and cannot assert a locator"
            )
        return self


class VenueSourceCapsule(StrictModel):
    schema_version: Literal["arw.venue-source-capsule.v2"] = (
        "arw.venue-source-capsule.v2"
    )
    title: ShortText
    official_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    doi: ShortText | None = None
    accepted_category: ShortText
    accepted_year: Annotated[int, Field(ge=1900, le=2200)]
    provenance: ReviewedPdfProvenance
    structural_summary: tuple[ShortText, ...] = Field(min_length=1, max_length=64)
    sections: tuple[ReviewedSectionAnnotation, ...] = Field(min_length=6, max_length=6)
    figure_roles: tuple[ShortText, ...] = Field(default=(), max_length=32)
    evidence_forms: tuple[ShortText, ...] = Field(default=(), max_length=32)
    observed_patterns: tuple[ShortText, ...] = Field(default=(), max_length=32)
    access_basis: FullTextAccess | None = None
    retention: Literal["structural_capsule_only_full_pdf_not_retained"] = (
        "structural_capsule_only_full_pdf_not_retained"
    )

    @model_validator(mode="after")
    def exact_functions(self):
        validate_full_text_access(
            self.access_basis or "official_full_text", self.provenance
        )
        if {item.function for item in self.sections} != set(ArgumentFunction.__args__):
            raise ValueError(
                "capsule must record each function once, observed or unknown"
            )
        return self


class VenueSourceReviewV2(StrictModel):
    schema_version: Literal["arw.venue-source-review.v2"] = "arw.venue-source-review.v2"
    review_id: StableRuntimeId
    source_artifact_id: StableRuntimeId
    source_sha256: Sha256
    official_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    doi: ShortText | None = None
    accepted_category: ShortText
    accepted_year: Annotated[int, Field(ge=1900, le=2200)]
    access_basis: FullTextAccess = "official_full_text"
    reviewer: ShortText
    decision: Literal["AGENT_REVIEW_RECORDED"] = "AGENT_REVIEW_RECORDED"

    provenance: ReviewedPdfProvenance

    @model_validator(mode="after")
    def matching_access(self):
        validate_full_text_access(self.access_basis, self.provenance)
        if self.reviewer != self.provenance.reviewer:
            raise ValueError("PDF reviewer differs from source review reviewer")
        return self


class VenueExemplarV2(StrictModel):
    schema_version: Literal["arw.venue-exemplar.v2"] = "arw.venue-exemplar.v2"
    exemplar_id: StableRuntimeId
    doi: ShortText | None = None
    official_url: Annotated[str, Field(pattern=r"^https://[^\s]+$", max_length=2048)]
    source_sha256: Sha256
    source_artifact_id: StableRuntimeId
    source_review_artifact_id: StableRuntimeId
    source_reviewer: ShortText
    accepted_category: ShortText
    accepted_year: Annotated[int, Field(ge=1900, le=2200)]
    venue_id: StableRuntimeId
    domain_id: StableRuntimeId
    sections: tuple[ReviewedSectionAnnotation, ...] = Field(min_length=6, max_length=6)
    figure_roles: tuple[ShortText, ...] = Field(default=(), max_length=32)
    evidence_forms: tuple[ShortText, ...] = Field(default=(), max_length=32)
    observed_patterns: tuple[ShortText, ...] = Field(default=(), max_length=32)
    access_basis: FullTextAccess = "official_full_text"
    provenance: ReviewedPdfProvenance

    @model_validator(mode="after")
    def exact_functions(self):
        validate_full_text_access(self.access_basis, self.provenance)
        if len({item.function for item in self.sections}) != 6:
            raise ValueError("v2 must record each function once, observed or unknown")
        if self.provenance.reviewer != self.source_reviewer:
            raise ValueError("PDF reviewer differs from exemplar reviewer")
        if len(set(self.evidence_forms)) != len(self.evidence_forms):
            raise ValueError("evidence forms must be distinct")
        return self


def venue_source_capsule_document(capsule: VenueSourceCapsule) -> dict:
    """Omit only newly added absent fields to preserve earlier v2 capsule bytes."""
    document = capsule.model_dump(mode="json")
    if document["access_basis"] is None:
        document.pop("access_basis")
    for field in NEW_OPTIONAL_PROVENANCE_FIELDS:
        if document["provenance"][field] is None:
            document["provenance"].pop(field)
    return document


def parse_venue_exemplar(raw: bytes):
    model = (
        VenueExemplarV2
        if json.loads(raw).get("schema_version") == "arw.venue-exemplar.v2"
        else VenueExemplar
    )
    return model.model_validate_json(raw)


def parse_venue_source_review(raw: bytes):
    model = (
        VenueSourceReviewV2
        if json.loads(raw).get("schema_version") == "arw.venue-source-review.v2"
        else VenueSourceReview
    )
    return model.model_validate_json(raw)


def verify_venue_source_binding(exemplar, review, source: bytes):
    """Recheck retained bytes and exact agent declaration on admission and replay."""
    if sha256_hex(source) != exemplar.source_sha256:
        raise ValueError("exemplar source digest mismatch")
    fields = (
        "source_artifact_id",
        "source_sha256",
        "official_url",
        "doi",
        "accepted_category",
        "accepted_year",
        "access_basis",
    )
    if (
        any(getattr(review, name) != getattr(exemplar, name) for name in fields)
        or review.reviewer != exemplar.source_reviewer
    ):
        raise ValueError("exemplar source review mismatch")
    if isinstance(exemplar, VenueExemplarV2):
        if (
            not isinstance(review, VenueSourceReviewV2)
            or review.provenance != exemplar.provenance
        ):
            raise ValueError("exemplar PDF provenance review mismatch")
        capsule = VenueSourceCapsule.model_validate_json(source)
        if (capsule.access_basis or "official_full_text") != exemplar.access_basis:
            raise ValueError("exemplar retained capsule access basis mismatch")
        if any(
            getattr(capsule, name) != getattr(exemplar, name)
            for name in (
                "official_url",
                "doi",
                "accepted_category",
                "accepted_year",
                "provenance",
                "sections",
                "figure_roles",
                "evidence_forms",
                "observed_patterns",
            )
        ):
            raise ValueError("exemplar retained capsule provenance mismatch")
    elif isinstance(review, VenueSourceReviewV2):
        raise TypeError("v1 exemplar requires v1 source review")


class VenueOutcome(StrictModel):
    schema_version: Literal["arw.venue-outcome.v1"] = "arw.venue-outcome.v1"
    outcome_id: StableRuntimeId
    venue_id: StableRuntimeId
    domain_id: StableRuntimeId
    narrative_sha256: Sha256
    narrative_version: Annotated[int, Field(ge=1)]
    heuristic_ids: tuple[StableRuntimeId, ...] = Field(max_length=64)
    heuristic_use_artifact_ids: tuple[StableRuntimeId, ...] = Field(
        default=(), max_length=64
    )
    outcome: ShortText
    evidence_artifact_id: StableRuntimeId
    evidence_digest: Sha256

    @model_validator(mode="after")
    def unique_heuristics(self):
        if len(set(self.heuristic_ids)) != len(self.heuristic_ids):
            raise ValueError("heuristic IDs must be distinct")
        if len(self.heuristic_use_artifact_ids) != len(self.heuristic_ids):
            raise ValueError("each heuristic outcome requires an accepted use artifact")
        return self


class VenueEvidencePolicy(StrictModel):
    schema_version: Literal["arw.venue-evidence-policy.v1"] = (
        "arw.venue-evidence-policy.v1"
    )
    policy_id: StableRuntimeId
    version: ShortText
    mode: Literal["venue-evidence"] = "venue-evidence"
    exemplar_observation_ids: tuple[StableRuntimeId, ...] = Field(
        min_length=1, max_length=256
    )

    @model_validator(mode="after")
    def unique_observations(self):
        if len(set(self.exemplar_observation_ids)) != len(
            self.exemplar_observation_ids
        ):
            raise ValueError("exemplar observations must be independent")
        return self


class VenueEvidenceSample(StrictModel):
    schema_version: Literal["arw.venue-evidence-sample.v1"] = (
        "arw.venue-evidence-sample.v1"
    )
    heuristic_id: StableRuntimeId
    policy_id: StableRuntimeId
    policy_version: ShortText
    exemplar_observation_id: StableRuntimeId
    finding: Literal["supporting", "counterexample", "unknown"]
    rationale: ShortText
    reviewer: ShortText


def venue_learning_schema_documents():
    result = {}
    for name, model in (
        ("venue-source-review.schema.json", VenueSourceReview),
        ("venue-source-capsule-v2.schema.json", VenueSourceCapsule),
        ("venue-source-review-v2.schema.json", VenueSourceReviewV2),
        ("venue-exemplar-v2.schema.json", VenueExemplarV2),
        ("venue-exemplar.schema.json", VenueExemplar),
        ("venue-outcome.schema.json", VenueOutcome),
        ("venue-evidence-policy.schema.json", VenueEvidencePolicy),
        ("venue-evidence-sample.schema.json", VenueEvidenceSample),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result


def legacy_style_drafts(raw: bytes) -> dict:
    """Expose legacy editorial prose as unverified drafts, never as observations."""
    if len(raw) > 65536:
        raise ValueError("legacy profile exceeds migration budget")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise TypeError("legacy profile must be an object")
    sources = document.get("sources", {})
    style = document.get("style_learning", {})
    exemplars = style.get("exemplars", [])
    if (
        not isinstance(sources, dict)
        or not isinstance(exemplars, list)
        or len(exemplars) > 256
    ):
        raise ValueError("invalid legacy source inventory")
    drafts = []
    for exemplar in exemplars:
        if not isinstance(exemplar, dict):
            raise TypeError("invalid legacy exemplar")
        source_id = exemplar.get("source_id")
        source = sources.get(source_id, {})
        patterns = exemplar.get("observed_patterns", [])
        if (
            not isinstance(source, dict)
            or not isinstance(patterns, list)
            or len(patterns) > 32
        ):
            raise ValueError("invalid legacy exemplar source or patterns")
        for index, pattern in enumerate(patterns):
            if (
                not isinstance(pattern, str)
                or not pattern.strip()
                or len(pattern) > 1200
            ):
                raise ValueError("invalid legacy observed pattern")
            drafts.append(
                {
                    "draft_id": f"{source_id}:{index}",
                    "status": "unverified_legacy_candidate",
                    "source_url": source.get("url"),
                    "source_sha256": None,
                    "proposed_action": pattern,
                    "scope": "project",
                    "authority": "advisory_only",
                    "needs": [
                        "accepted full-text source bytes",
                        "section/function annotations",
                        "domain and venue applicability",
                        "supporting and counterexample review",
                    ],
                }
            )
    for section, clauses in (
        ("consensus", style.get("consensus_argument_slots", [])),
        (
            "artifact",
            [
                (key, value)
                for key, value in style.get("artifact_contract", {}).items()
                if isinstance(value, str)
            ],
        ),
    ):
        if not isinstance(clauses, list) or len(clauses) > 256:
            raise ValueError("invalid legacy guidance clauses")
        for index, item in enumerate(clauses):
            key, pattern = item if isinstance(item, tuple) else (str(index), item)
            if (
                not isinstance(pattern, str)
                or not pattern.strip()
                or len(pattern) > 1200
            ):
                raise ValueError("invalid legacy guidance clause")
            drafts.append(
                {
                    "draft_id": f"{section}:{key}",
                    "status": "unverified_legacy_candidate",
                    "source_url": None,
                    "source_sha256": None,
                    "proposed_action": pattern,
                    "scope": "project",
                    "authority": "advisory_only",
                    "nonmandatory": True,
                    "needs": [
                        "source-backed exemplars",
                        "counterexample review",
                        "exception conditions for quantity guidance",
                        "venue/domain applicability",
                    ],
                }
            )
    if len(drafts) > 1024:
        raise ValueError("legacy candidate budget exceeded")
    return {
        "source_profile_sha256": sha256_hex(raw),
        "drafts": drafts,
        "canonical_input_sha256": sha256_hex(canonical_json_bytes(document)),
    }


def exemplar_identity_keys(exemplar: VenueExemplar | VenueExemplarV2) -> frozenset[str]:
    """Conservative independent-paper aliases; collisions cannot add support."""
    parsed = urlsplit(exemplar.official_url)
    normalized_url = urlunsplit(
        (
            "https",
            parsed.netloc.lower(),
            parsed.path.rstrip("/").lower(),
            parsed.query,
            "",
        )
    )
    keys = {"url:" + normalized_url, "sha256:" + exemplar.source_sha256}
    if isinstance(exemplar, VenueExemplarV2):
        keys.add("sha256:" + exemplar.provenance.pdf_sha256)
    if exemplar.doi:
        doi = exemplar.doi.strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.startswith(prefix):
                doi = doi[len(prefix) :]
                break
        keys.add("doi:" + doi)
    return frozenset(keys)
