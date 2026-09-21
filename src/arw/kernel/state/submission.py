"""Strict, parent-admitted submission and revision contracts.

This module deliberately contains data contracts and pure validation only.  It
does not write the journal, call a portal, or resolve an extension provider.
The runtime and composition layers remain responsible for those boundaries.
"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import (
    ActorId,
    EventId,
    RunId,
    Sha256,
    StableRuntimeId,
    StrictModel,
    UtcTimestamp,
)

SubmissionSchemaVersion = Literal["arw.submission.v1"]
SubmissionId = StableRuntimeId
SubmissionArtifactRole = Literal[
    "main_manuscript",
    "title_page",
    "marked_manuscript",
    "response_letter",
    "figure",
    "table",
    "supplement",
    "cover_letter",
    "reporting_checklist",
]
ReviewResponseStatus = Literal[
    "pending",
    "proposed",
    "addressed",
    "not_adopted",
    "needs_author_confirmation",
    "blocked",
]
CheckStatus = Literal[
    "PASS",
    "REVIEW",
    "BLOCK",
    "STALE",
    "UNSUPPORTED",
    "NOT_CHECKED",
]
CheckApplicability = Literal["REQUIRED", "OPTIONAL", "NOT_APPLICABLE"]
ReadinessStatus = Literal[
    "INCOMPLETE",
    "BLOCKED",
    "REVIEW_REQUIRED",
    "STALE",
    "READY_FOR_HUMAN_SUBMIT",
]
ExternalObservationState = Literal[
    "unverified",
    "not_submitted",
    "awaiting_human_submit",
    "submitted",
]
ExternalAttribution = Literal["user_confirmation", "platform_receipt"]

_MAX_COMPONENTS = 128
_MAX_PEOPLE = 100
_MAX_COMMENTS = 200
_MAX_DEPENDENCIES = 2048


def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


def _https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("official source URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("source URL must not contain credentials")
    return value


class SubmissionArtifactReference(StrictModel):
    """A reference to an already accepted parent artifact."""

    artifact_id: StableRuntimeId
    manifest_sha256: Sha256
    content_sha256: Sha256
    accepting_event_id: EventId


class SubmissionComponent(StrictModel):
    component_id: StableRuntimeId
    role: SubmissionArtifactRole
    artifact: SubmissionArtifactReference
    media_type: Annotated[str, Field(min_length=3, max_length=127)]
    byte_length: Annotated[int, Field(ge=0, le=64 * 1024 * 1024)]
    required: bool = True


class JournalRequirement(StrictModel):
    requirement_id: StableRuntimeId
    description: Annotated[str, Field(min_length=1, max_length=800)]
    required: bool = True
    check_kind: Annotated[str, Field(min_length=1, max_length=96)]


class JournalRequirementsSnapshot(StrictModel):
    schema_version: Literal["arw.journal-requirements.v1"]
    snapshot_id: StableRuntimeId
    journal_id: StableRuntimeId
    journal_name: Annotated[str, Field(min_length=1, max_length=240)]
    article_type: Annotated[str, Field(min_length=1, max_length=120)]
    official_source_urls: tuple[str, ...] = Field(min_length=1, max_length=32)
    retained_source_artifacts: tuple[SubmissionArtifactReference, ...] = Field(
        min_length=1, max_length=32
    )
    captured_at: UtcTimestamp
    verified_at: UtcTimestamp
    valid_until: UtcTimestamp | None = None
    requirements: tuple[JournalRequirement, ...] = Field(max_length=256)
    unknown_requirements: tuple[
        Annotated[str, Field(min_length=1, max_length=240)], ...
    ] = Field(default=(), max_length=64)
    verifier_id: ActorId

    @field_validator("official_source_urls")
    @classmethod
    def official_urls_are_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        value = tuple(_https_url(item) for item in value)
        return _unique(value, "official source URLs")

    @field_validator("requirements")
    @classmethod
    def requirement_ids_are_unique(
        cls, value: tuple[JournalRequirement, ...]
    ) -> tuple[JournalRequirement, ...]:
        _unique(tuple(item.requirement_id for item in value), "requirement IDs")
        return value


class DeclarationField(StrictModel):
    status: Literal["missing", "needs_confirmation", "confirmed", "not_applicable"]
    value: Annotated[str, Field(max_length=4096)] | None = None
    human_decision_id: StableRuntimeId | None = None
    rationale: Annotated[str, Field(max_length=1200)] | None = None

    @model_validator(mode="after")
    def authority_is_scoped(self) -> DeclarationField:
        if self.status == "confirmed" and self.human_decision_id is None:
            raise ValueError("confirmed declaration requires a scoped human decision")
        if self.status == "not_applicable" and not self.rationale:
            raise ValueError("not_applicable declaration requires a rationale")
        if self.status in {"missing", "needs_confirmation"} and self.human_decision_id:
            raise ValueError("unconfirmed declaration cannot carry a human decision")
        return self


class SubmissionAuthorDeclaration(StrictModel):
    person_id: StableRuntimeId
    display_name: Annotated[str, Field(min_length=1, max_length=160)]
    order: Annotated[int, Field(ge=0, le=_MAX_PEOPLE)]
    corresponding: bool = False
    contributions: tuple[
        Annotated[str, Field(min_length=1, max_length=96)], ...
    ] = Field(default=(), max_length=32)
    funding: DeclarationField
    conflicts: DeclarationField
    ethics: DeclarationField
    data: DeclarationField
    ai_use: DeclarationField


class SubmissionPacket(StrictModel):
    schema_version: Literal["arw.submission-packet.v1"]
    project_id: StableRuntimeId
    run_id: RunId
    submission_id: SubmissionId
    packet_version: Annotated[int, Field(ge=1, le=10_000)]
    predecessor_manifest_sha256: Sha256 | None = None
    journal_id: StableRuntimeId
    journal_name: Annotated[str, Field(min_length=1, max_length=240)]
    article_type: Annotated[str, Field(min_length=1, max_length=120)]
    round_number: Annotated[int, Field(ge=0, le=100)]
    manuscript_id: StableRuntimeId
    manuscript_version: Annotated[str, Field(min_length=1, max_length=96)]
    manuscript: SubmissionArtifactReference
    components: tuple[SubmissionComponent, ...] = Field(
        min_length=1, max_length=_MAX_COMPONENTS
    )
    policy_snapshot: SubmissionArtifactReference
    authors: tuple[SubmissionAuthorDeclaration, ...] = Field(
        min_length=1, max_length=_MAX_PEOPLE
    )
    audit_evidence: tuple[SubmissionArtifactReference, ...] = Field(
        default=(), max_length=256
    )
    response_evidence: tuple[SubmissionArtifactReference, ...] = Field(
        default=(), max_length=256
    )
    gaps: tuple[Annotated[str, Field(min_length=1, max_length=240)], ...] = Field(
        default=(), max_length=128
    )
    created_at: UtcTimestamp
    created_by: ActorId

    @model_validator(mode="after")
    def identities_and_predecessor_are_valid(self) -> SubmissionPacket:
        if self.packet_version == 1 and self.predecessor_manifest_sha256 is not None:
            raise ValueError("packet version 1 cannot have a predecessor")
        if self.packet_version > 1 and self.predecessor_manifest_sha256 is None:
            raise ValueError("successor packet requires a predecessor manifest")
        component_ids = tuple(item.component_id for item in self.components)
        _unique(component_ids, "component IDs")
        artifact_ids = tuple(item.artifact.artifact_id for item in self.components)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("submission component artifact IDs must be unique")
        author_ids = tuple(item.person_id for item in self.authors)
        _unique(author_ids, "author IDs")
        orders = tuple(item.order for item in self.authors)
        if len(orders) != len(set(orders)):
            raise ValueError("author order values must be unique")
        if sum(1 for item in self.authors if item.corresponding) != 1:
            raise ValueError("submission requires exactly one corresponding author")
        singleton_roles = {
            "main_manuscript",
            "title_page",
            "marked_manuscript",
            "response_letter",
            "cover_letter",
            "reporting_checklist",
        }
        seen_roles: set[str] = set()
        for component in self.components:
            if component.role in singleton_roles and component.role in seen_roles:
                raise ValueError(f"duplicate singleton component role: {component.role}")
            seen_roles.add(component.role)
        return self


class ReviewLocator(StrictModel):
    locator_type: Literal["heading", "line", "page", "json_pointer", "paragraph"]
    value: Annotated[str, Field(min_length=1, max_length=512)]
    manuscript_sha256: Sha256 | None = None
    render_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def render_binding_is_required(self) -> ReviewLocator:
        if self.locator_type in {"line", "page"} and self.render_sha256 is None:
            raise ValueError("page/line locations require a rendered file digest")
        return self


class ReviewComment(StrictModel):
    comment_id: StableRuntimeId
    submission_id: SubmissionId
    round_number: Annotated[int, Field(ge=1, le=100)]
    parent_comment_id: StableRuntimeId | None = None
    source_locator: ReviewLocator
    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    original_order: Annotated[int, Field(ge=0, le=_MAX_COMMENTS)]
    depends_on: tuple[StableRuntimeId, ...] = Field(default=(), max_length=64)

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return _unique(value, "comment dependencies")

    @model_validator(mode="after")
    def no_self_parent_or_dependency(self) -> ReviewComment:
        if self.parent_comment_id == self.comment_id:
            raise ValueError("comment cannot be its own parent")
        if self.comment_id in self.depends_on:
            raise ValueError("comment cannot depend on itself")
        return self


class ReviewRound(StrictModel):
    schema_version: Literal["arw.submission-review-round.v1"]
    round_id: StableRuntimeId
    submission_id: SubmissionId
    round_number: Annotated[int, Field(ge=1, le=100)]
    source_letter: SubmissionArtifactReference
    comments: tuple[ReviewComment, ...] = Field(min_length=1, max_length=_MAX_COMMENTS)
    imported_at: UtcTimestamp
    imported_by: ActorId

    @model_validator(mode="after")
    def comment_set_is_consistent(self) -> ReviewRound:
        if any(
            item.submission_id != self.submission_id
            or item.round_number != self.round_number
            for item in self.comments
        ):
            raise ValueError("review comment identity does not match its round")
        ids = tuple(item.comment_id for item in self.comments)
        _unique(ids, "review comment IDs")
        parent_ids = {item.comment_id for item in self.comments}
        if any(
            item.parent_comment_id is not None
            and item.parent_comment_id not in parent_ids
            for item in self.comments
        ):
            raise ValueError("review comment parent is absent from its round")
        if any(
            dependency not in parent_ids
            for item in self.comments
            for dependency in item.depends_on
        ):
            raise ValueError("review comment dependency is absent from its round")
        expected_ids = {
            review_comment_identity(
                self.submission_id,
                self.round_number,
                self.source_letter.manifest_sha256,
                item.source_locator,
            )
            for item in self.comments
        }
        if any(item.comment_id not in expected_ids for item in self.comments):
            raise ValueError("review comment ID is not bound to its source locator")
        edges = {
            item.comment_id: tuple(
                value
                for value in (item.parent_comment_id, *item.depends_on)
                if value is not None
            )
            for item in self.comments
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(comment_id: str) -> None:
            if comment_id in visiting:
                raise ValueError("review comment dependency cycle")
            if comment_id in visited:
                return
            visiting.add(comment_id)
            for dependency in edges[comment_id]:
                visit(dependency)
            visiting.remove(comment_id)
            visited.add(comment_id)

        for comment_id in edges:
            visit(comment_id)
        return self


class RevisionPatchEvidence(StrictModel):
    base_manuscript_sha256: Sha256
    candidate_manuscript_sha256: Sha256
    block_manifest_sha256: Sha256
    approved_scope: Annotated[str, Field(min_length=1, max_length=512)]
    apply_report: SubmissionArtifactReference
    comment_ids: tuple[StableRuntimeId, ...] = Field(min_length=1, max_length=128)

    @field_validator("comment_ids")
    @classmethod
    def patch_comment_ids_are_unique(
        cls, value: tuple[str, ...]
    ) -> tuple[str, ...]:
        return _unique(value, "patch comment IDs")


class ReviewResponse(StrictModel):
    schema_version: Literal["arw.submission-response.v1"]
    response_id: StableRuntimeId
    submission_id: SubmissionId
    round_number: Annotated[int, Field(ge=1, le=100)]
    comment_id: StableRuntimeId
    status: ReviewResponseStatus
    response_text: Annotated[str, Field(min_length=1, max_length=8000)]
    rationale: Annotated[str, Field(max_length=4000)] | None = None
    predecessor_response_id: StableRuntimeId | None = None
    evidence: tuple[SubmissionArtifactReference, ...] = Field(
        default=(), max_length=128
    )
    locations: tuple[ReviewLocator, ...] = Field(default=(), max_length=32)
    patch: RevisionPatchEvidence | None = None
    author_decision_id: StableRuntimeId | None = None

    @model_validator(mode="after")
    def closure_requires_evidence(self) -> ReviewResponse:
        if self.status == "addressed" and not (self.evidence or self.patch):
            raise ValueError("addressed response requires revision evidence")
        if self.status == "addressed" and not self.locations and self.patch is None:
            raise ValueError("addressed response requires a modification location")
        if self.status == "addressed" and any(
            locator.manuscript_sha256 is None for locator in self.locations
        ):
            raise ValueError(
                "addressed response locations must bind the manuscript digest"
            )
        if self.status == "addressed" and self.author_decision_id is None:
            raise ValueError("addressed response requires author disposition")
        if self.status == "not_adopted":
            if not self.rationale:
                raise ValueError("not_adopted response requires a rationale")
            if self.author_decision_id is None:
                raise ValueError("not_adopted response requires author disposition")
        if self.patch is not None and self.comment_id not in self.patch.comment_ids:
            raise ValueError("revision patch does not map the response comment")
        if self.status == "needs_author_confirmation" and self.author_decision_id:
            raise ValueError("pending author response cannot carry a decision")
        return self


class SubmissionCheck(StrictModel):
    check_id: StableRuntimeId
    check_kind: Annotated[str, Field(min_length=1, max_length=96)]
    applicability: CheckApplicability
    status: CheckStatus
    reason_codes: tuple[
        Annotated[str, Field(min_length=1, max_length=96)], ...
    ] = Field(default=(), max_length=32)
    source_identity: Annotated[str, Field(min_length=1, max_length=160)]
    source_version: Annotated[str, Field(min_length=1, max_length=96)]
    input_sha256: Sha256
    output_sha256: Sha256 | None = None
    coverage: Annotated[str, Field(min_length=1, max_length=512)]
    limitations: tuple[
        Annotated[str, Field(min_length=1, max_length=240)], ...
    ] = Field(default=(), max_length=32)
    evidence: tuple[SubmissionArtifactReference, ...] = Field(
        default=(), max_length=128
    )
    evaluated_at: UtcTimestamp
    valid_until: UtcTimestamp | None = None

    @model_validator(mode="after")
    def strict_pass_has_evidence(self) -> SubmissionCheck:
        if self.status == "PASS" and self.applicability == "REQUIRED" and not self.evidence:
            raise ValueError("required PASS check requires accepted evidence")
        if self.applicability == "NOT_APPLICABLE" and self.status == "PASS":
            raise ValueError("not-applicable check cannot be PASS")
        return self


class SubmissionVerifierObservation(StrictModel):
    """A bounded verifier receipt; it is evidence, not a readiness verdict."""

    schema_version: Literal["arw.submission-verifier-observation.v1"]
    observation_id: StableRuntimeId
    run_id: RunId
    submission_id: SubmissionId
    packet_manifest_sha256: Sha256
    verifier_identity: Annotated[str, Field(min_length=1, max_length=160)]
    verifier_version: Annotated[str, Field(min_length=1, max_length=96)]
    input_sha256: Sha256
    output_sha256: Sha256 | None = None
    coverage: Annotated[str, Field(min_length=1, max_length=512)]
    limitations: tuple[
        Annotated[str, Field(min_length=1, max_length=240)], ...
    ] = Field(default=(), max_length=32)
    checks: tuple[SubmissionCheck, ...] = Field(max_length=256)
    observed_at: UtcTimestamp

    @field_validator("checks")
    @classmethod
    def verifier_check_ids_are_unique(
        cls, value: tuple[SubmissionCheck, ...]
    ) -> tuple[SubmissionCheck, ...]:
        _unique(tuple(item.check_id for item in value), "verifier check IDs")
        return value


class SubmissionCheckReport(StrictModel):
    schema_version: Literal["arw.submission-check-report.v1"]
    report_id: StableRuntimeId
    submission_id: SubmissionId
    packet_manifest_sha256: Sha256
    input_fingerprint: Sha256
    evaluated_at: UtcTimestamp
    valid_until: UtcTimestamp | None = None
    checks: tuple[SubmissionCheck, ...] = Field(max_length=256)
    readiness: ReadinessStatus
    reason_codes: tuple[
        Annotated[str, Field(min_length=1, max_length=128)], ...
    ] = Field(default=(), max_length=128)

    @field_validator("checks")
    @classmethod
    def check_ids_are_unique(cls, value: tuple[SubmissionCheck, ...]) -> tuple[SubmissionCheck, ...]:
        _unique(tuple(item.check_id for item in value), "check IDs")
        return value


class SubmissionResultObservation(StrictModel):
    schema_version: Literal["arw.submission-result-observation.v1"]
    observation_id: StableRuntimeId
    submission_id: SubmissionId
    packet_manifest_sha256: Sha256
    state: ExternalObservationState
    attribution: ExternalAttribution
    recorded_at: UtcTimestamp
    external_time: UtcTimestamp | None = None
    receipt: SubmissionArtifactReference | None = None
    deviation_codes: tuple[
        Annotated[str, Field(min_length=1, max_length=128)], ...
    ] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def receipt_and_attribution_match(self) -> SubmissionResultObservation:
        if self.attribution == "platform_receipt" and self.receipt is None:
            raise ValueError("platform receipt attribution requires a retained receipt")
        if self.attribution == "user_confirmation" and self.receipt is not None:
            raise ValueError("user confirmation cannot claim a platform receipt")
        if self.state == "submitted" and self.attribution not in {
            "user_confirmation",
            "platform_receipt",
        }:
            raise ValueError("submitted observation requires explicit attribution")
        return self


class SubmissionReadinessEvaluation(StrictModel):
    schema_version: Literal["arw.submission-readiness.v1"]
    submission_id: SubmissionId
    packet_manifest_sha256: Sha256
    input_fingerprint: Sha256
    evaluated_at: UtcTimestamp
    readiness: ReadinessStatus
    reason_codes: tuple[
        Annotated[str, Field(min_length=1, max_length=128)], ...
    ] = Field(default=(), max_length=128)


SUBMISSION_SCHEMA_MODELS = (
    ("journal-requirements.schema.json", JournalRequirementsSnapshot),
    ("submission-packet.schema.json", SubmissionPacket),
    ("submission-review-round.schema.json", ReviewRound),
    ("submission-response.schema.json", ReviewResponse),
    ("submission-check-report.schema.json", SubmissionCheckReport),
    ("submission-verifier-observation.schema.json", SubmissionVerifierObservation),
    ("submission-result-observation.schema.json", SubmissionResultObservation),
    ("submission-readiness.schema.json", SubmissionReadinessEvaluation),
)
SUBMISSION_SCHEMA_NAMES = tuple(name for name, _ in SUBMISSION_SCHEMA_MODELS)


def submission_schema_documents() -> dict[str, dict[str, object]]:
    documents: dict[str, dict[str, object]] = {}
    for name, model in SUBMISSION_SCHEMA_MODELS:
        document = model.model_json_schema(mode="validation")
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = document
    return documents


def submission_input_fingerprint(
    packet: SubmissionPacket,
    *,
    dependency_sha256: tuple[Sha256, ...] = (),
) -> Sha256:
    """Calculate a stable fingerprint without making a graph authoritative."""

    payload = {
        "packet": packet.model_dump(mode="json"),
        "dependencies": list(_unique(dependency_sha256, "dependency hashes")),
    }
    return sha256_hex(canonical_json_bytes(payload))


def review_comment_identity(
    submission_id: SubmissionId,
    round_number: int,
    source_manifest_sha256: Sha256,
    locator: ReviewLocator,
) -> StableRuntimeId:
    """Derive an import-stable comment ID from source identity and locator."""

    digest = sha256_hex(
        canonical_json_bytes(
            {
                "submission_id": submission_id,
                "round_number": round_number,
                "source_manifest_sha256": source_manifest_sha256,
                "locator": locator.model_dump(mode="json"),
            }
        )
    )
    return f"review.{digest[:48]}"


def declaration_subject_sha256(
    submission_id: SubmissionId,
    person_id: StableRuntimeId,
    field_name: str,
    field: DeclarationField,
) -> Sha256:
    """Bind an author decision to one exact declaration field and value."""

    return sha256_hex(
        canonical_json_bytes(
            {
                "subject": "submission-declaration",
                "submission_id": submission_id,
                "person_id": person_id,
                "field": field_name,
                "status": field.status,
                "value": field.value,
                "rationale": field.rationale,
            }
        )
    )


def response_subject_sha256(response: ReviewResponse) -> Sha256:
    """Bind a response disposition to its exact comment and evidence body."""

    return sha256_hex(
        canonical_json_bytes(
            {
                "subject": "submission-response",
                "submission_id": response.submission_id,
                "round_number": response.round_number,
                "comment_id": response.comment_id,
                "status": response.status,
                "response_text": response.response_text,
                "rationale": response.rationale,
                "predecessor_response_id": response.predecessor_response_id,
                "evidence": [item.model_dump(mode="json") for item in response.evidence],
                "locations": [item.model_dump(mode="json") for item in response.locations],
                "patch": response.patch.model_dump(mode="json") if response.patch else None,
            }
        )
    )


def confirmation_gate_id(subject_scope: str) -> StableRuntimeId:
    """Return the deterministic eligibility gate for one exact subject scope."""

    return f"gate.submission.confirmation.{sha256_hex(subject_scope.encode())[:32]}"


def evaluate_submission_readiness(
    packet: SubmissionPacket,
    *,
    packet_manifest_sha256: Sha256,
    checks: tuple[SubmissionCheck, ...],
    responses: tuple[ReviewResponse, ...] = (),
    expected_comment_ids: tuple[StableRuntimeId, ...] = (),
    dependency_sha256: tuple[Sha256, ...] = (),
    valid_input_sha256: tuple[Sha256, ...] = (),
    evaluated_at: UtcTimestamp,
) -> SubmissionReadinessEvaluation:
    """Pure fail-closed readiness aggregation used by the parent service."""

    reason_codes: list[str] = []
    if packet.gaps:
        reason_codes.extend(f"packet_gap:{gap}" for gap in packet.gaps)

    required = {item.check_kind: item for item in checks if item.applicability == "REQUIRED"}
    required_kinds = {
        "component_integrity",
        "journal_requirements",
        "author_declarations",
        "claim_citation_coverage",
        "scientific_review",
    }
    if packet.round_number > 0:
        required_kinds.add("review_response_coverage")
    for kind in sorted(required_kinds):
        item = required.get(kind)
        if item is None:
            reason_codes.append(f"check_not_checked:{kind}")
            continue
        if item.status != "PASS":
            reason_codes.append(f"check_{item.status.lower()}:{kind}")
        elif valid_input_sha256 and item.input_sha256 not in set(valid_input_sha256):
            reason_codes.append(f"check_input_stale:{kind}")
        elif any(
            marker in " ".join((*item.reason_codes, *item.limitations)).lower()
            for marker in ("heuristic", "not_checked", "unverified")
        ):
            # A successful process or a nominal PASS cannot erase an explicit
            # limitation from a strict required check.  The parent keeps the
            # receipt, but readiness remains fail-closed.
            reason_codes.append(f"check_limited:{kind}")

    if packet.round_number > 0:
        closing = {"addressed", "not_adopted"}
        if not responses:
            reason_codes.append("review_responses_missing")
        elif any(item.status not in closing for item in responses):
            reason_codes.append("review_responses_incomplete")
        if expected_comment_ids:
            responded_ids = {item.comment_id for item in responses}
            missing = sorted(set(expected_comment_ids) - responded_ids)
            if missing:
                reason_codes.append("review_comments_unresolved")

    if packet.gaps:
        readiness: ReadinessStatus = "INCOMPLETE"
    elif any(code.startswith("check_stale") for code in reason_codes):
        readiness = "STALE"
    elif any(code.startswith("check_review") for code in reason_codes):
        readiness = "REVIEW_REQUIRED"
    elif reason_codes:
        readiness = "BLOCKED"
    else:
        readiness = "READY_FOR_HUMAN_SUBMIT"
    return SubmissionReadinessEvaluation(
        schema_version="arw.submission-readiness.v1",
        submission_id=packet.submission_id,
        packet_manifest_sha256=packet_manifest_sha256,
        input_fingerprint=submission_input_fingerprint(
            packet, dependency_sha256=dependency_sha256
        ),
        evaluated_at=evaluated_at,
        readiness=readiness,
        reason_codes=tuple(reason_codes),
    )


__all__ = [
    "SUBMISSION_SCHEMA_NAMES",
    "CheckApplicability",
    "CheckStatus",
    "DeclarationField",
    "JournalRequirement",
    "JournalRequirementsSnapshot",
    "ReadinessStatus",
    "ReviewComment",
    "ReviewLocator",
    "ReviewResponse",
    "ReviewRound",
    "RevisionPatchEvidence",
    "SubmissionArtifactReference",
    "SubmissionAuthorDeclaration",
    "SubmissionCheck",
    "SubmissionCheckReport",
    "SubmissionComponent",
    "SubmissionPacket",
    "SubmissionReadinessEvaluation",
    "SubmissionResultObservation",
    "SubmissionVerifierObservation",
    "confirmation_gate_id",
    "declaration_subject_sha256",
    "evaluate_submission_readiness",
    "response_subject_sha256",
    "review_comment_identity",
    "submission_input_fingerprint",
    "submission_schema_documents",
]
