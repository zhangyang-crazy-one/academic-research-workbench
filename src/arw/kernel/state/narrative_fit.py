"""Frozen, advisory venue-fit input and output contracts."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from arw.kernel.state.models import CanonicalEvent, Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.narrative import NarrativeSnapshot
from arw.kernel.state.narrative_realization import NarrativeRealization


class FitPredicate(StrictModel):
    kind: Literal[
        "heading_present",
        "literal_present",
        "pdf_page_count_at_most",
        "bounded_marker_absent",
    ]
    value: str | None = Field(default=None, max_length=512)
    limit: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def valid_operand(self):
        if self.kind == "pdf_page_count_at_most":
            if self.limit is None or self.value is not None:
                raise ValueError("page predicate needs only a positive limit")
        elif not self.value or not self.value.strip() or self.limit is not None:
            raise ValueError("text predicate needs only a nonblank literal")
        return self


class FitRule(StrictModel):
    rule_id: StableRuntimeId
    statement: str = Field(min_length=1, max_length=1200)
    source_url: str = Field(min_length=1, max_length=2048)
    source_sha256: Sha256
    source_locator: str = Field(min_length=1, max_length=512)
    predicate: FitPredicate | None = None
    reviewed_by: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def reviewed_predicate(self):
        if self.predicate is not None and not self.reviewed_by:
            raise ValueError("typed official predicate requires reviewer attribution")
        return self


class VenueFitProfile(StrictModel):
    schema_version: Literal["arw.venue-fit-profile.v1"] = "arw.venue-fit-profile.v1"
    venue_id: StableRuntimeId
    version: str = Field(min_length=1, max_length=128)
    verified_on: date
    review_due: date
    official_hard_requirements: tuple[FitRule, ...] = Field(default=(), max_length=128)
    structural_expectations: tuple[FitRule, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def unique_rules(self):
        if self.review_due < self.verified_on:
            raise ValueError("profile review_due precedes verified_on")
        ids = [
            r.rule_id
            for r in (*self.official_hard_requirements, *self.structural_expectations)
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("venue-fit rule IDs must be distinct")
        return self


class FitHeuristic(StrictModel):
    heuristic_id: StableRuntimeId
    promotion_event_id: StableRuntimeId
    venue_id: StableRuntimeId
    domain_id: StableRuntimeId
    suggested_action: str = Field(min_length=1, max_length=1200)
    approved_scope: Literal["run", "project", "domain", "global"]
    inspected_record_sha256: Sha256
    inspected_record: dict
    predicate: FitPredicate | None = None
    reviewed_by: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def reviewed_predicate(self):
        if self.predicate is not None and not self.reviewed_by:
            raise ValueError("heuristic match annotation requires a reviewer")
        return self


class FitJudgment(StrictModel):
    schema_version: Literal["arw.fit-judgment.v1"] = "arw.fit-judgment.v1"
    reviewer: str = Field(min_length=1, max_length=256)
    assessment: str = Field(min_length=1, max_length=4000)
    model_id: str | None = Field(default=None, max_length=256)
    provider: str | None = Field(default=None, max_length=256)
    prompt_version: str | None = Field(default=None, max_length=256)
    input_sha256: Sha256

    @model_validator(mode="after")
    def model_provenance(self):
        fields = (self.model_id, self.provider, self.prompt_version)
        if any(v is not None for v in fields) and not all(fields):
            raise ValueError("model judgment needs model, provider and prompt version")
        return self


class FitEvidence(StrictModel):
    event: CanonicalEvent
    manifest_base64: str = Field(max_length=350_000)
    content_base64: str = Field(max_length=11_184_812)


class WritingCandidateReceiptBinding(StrictModel):
    schema_version: Literal["arw.writing-candidate-receipt-binding.v1"] = (
        "arw.writing-candidate-receipt-binding.v1"
    )
    run_manifest_sha256: Sha256
    run_manifest_base64: str = Field(max_length=90_000)
    accepted_manifest_sha256: Sha256
    accepted_manifest_base64: str = Field(max_length=350_000)
    accepted_event_id: StableRuntimeId
    accepted_event_sha256: Sha256
    receipt_sha256: Sha256
    candidate_path: str = Field(min_length=1, max_length=512)
    candidate_sha256: Sha256
    realization_sha256: Sha256


class FitSnapshot(StrictModel):
    schema_version: Literal["arw.narrative-fit-snapshot.v1"] = (
        "arw.narrative-fit-snapshot.v1"
    )
    run_id: str = Field(min_length=1, max_length=128)
    manuscript_artifact_id: StableRuntimeId
    accepted_event_sha256: Sha256
    accepted_event: CanonicalEvent
    accepted_content_sha256: Sha256
    accepted_content_base64: str = Field(max_length=11_184_812)
    accepted_binding_kind: Literal[
        "realization_sidecar", "manuscript_source", "writing_candidate_receipt"
    ] = "realization_sidecar"
    writing_candidate_binding: WritingCandidateReceiptBinding | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    realization_base64: str = Field(max_length=1_400_000)
    manuscript_source_sha256: Sha256
    manuscript_source_base64: str = Field(max_length=11_184_812)
    realization: NarrativeRealization
    narrative: NarrativeSnapshot
    profile: VenueFitProfile
    profile_sha256: Sha256
    profile_base64: str = Field(max_length=350_000)
    heuristics: tuple[FitHeuristic, ...] = Field(default=(), max_length=64)
    heuristic_set_sha256: Sha256
    validation: dict
    evidence: tuple[FitEvidence, ...] = Field(default=(), max_length=128)
    pdf_page_count: int | None = Field(default=None, ge=1)
    pdf_artifact_id: StableRuntimeId | None = None
    pdf_sha256: Sha256 | None = None
    pdf_base64: str | None = Field(default=None, max_length=11_184_812)
    judgment: FitJudgment | None = None
    # Absent on snapshots frozen before source-format-aware predicates, which
    # keep replaying their original Markdown-only heading evaluation.
    predicate_policy: Literal["source-format-v2"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def consistent(self):
        if self.realization.source_sha256 != self.manuscript_source_sha256:
            raise ValueError("realization and source digest differ")
        if (self.accepted_binding_kind == "writing_candidate_receipt") != (
            self.writing_candidate_binding is not None
        ):
            raise ValueError("writing candidate binding must match its kind")
        if (self.pdf_artifact_id is None) != (self.pdf_sha256 is None):
            raise ValueError("PDF artifact and digest must occur together")
        if (self.pdf_artifact_id is None) != (self.pdf_base64 is None):
            raise ValueError("PDF artifact and bytes must occur together")
        if self.pdf_page_count is not None and self.pdf_artifact_id is None:
            raise ValueError("PDF page count requires an accepted PDF")
        return self


class FitReport(StrictModel):
    schema_version: Literal["arw.narrative-fit-report.v1"] = (
        "arw.narrative-fit-report.v1"
    )
    target: StableRuntimeId
    input_binding: dict
    official_hard_requirements: list[dict]
    structural_expectations: dict
    empirical_status: Literal["not_evaluated", "evaluated_selected"]
    empirical_patterns: list[dict]
    judgment_status: Literal["not_supplied", "supplied"]
    reviewer_judgment: dict | None
    limits: list[str]


class PublicFitSnapshot(StrictModel):
    """Accepted public evidence with no selected author narrative or realization."""

    schema_version: Literal["arw.narrative-fit-public-snapshot.v1"] = (
        "arw.narrative-fit-public-snapshot.v1"
    )
    run_id: str = Field(min_length=1, max_length=128)
    manuscript_artifact_id: StableRuntimeId
    manuscript: FitEvidence
    input_kind: Literal["markdown", "text", "pdf", "source_capsule"]
    profile: VenueFitProfile
    profile_sha256: Sha256
    profile_base64: str = Field(max_length=350_000)
    pdf: FitEvidence | None = None
    pdf_page_count: int | None = Field(default=None, ge=1)
    selected_narrative_status: Literal["not_selected"] = "not_selected"

    @model_validator(mode="after")
    def consistent(self):
        if (self.pdf is None) != (self.pdf_page_count is None):
            raise ValueError("actual PDF proof and page count must occur together")
        return self


def narrative_fit_schema_documents() -> dict[str, dict]:
    result = {}
    for name, model in (
        ("venue-fit-profile.schema.json", VenueFitProfile),
        ("narrative-fit-snapshot.schema.json", FitSnapshot),
        ("narrative-fit-public-snapshot.schema.json", PublicFitSnapshot),
        ("fit-judgment.schema.json", FitJudgment),
        ("narrative-fit-report.schema.json", FitReport),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result
