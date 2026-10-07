"""Provider-neutral tasks and validation for an actual reviewer's findings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

CATEGORIES = (
    "argument_structure",
    "fact_integrity",
    "claim_strength",
    "definitions_boundaries",
    "traceable_revision",
)
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
NoteText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
]
EvidenceText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]

TASKS = (
    (
        "argument_structure",
        "Trace motivation, challenges, questions, comparison, results and contributions. Report a substantive missing link; do not require a fixed paragraph order or number of contributions.",
    ),
    (
        "fact_integrity",
        "Check each quantity, citation, condition and metric against the source and its evidence. Distinguish interval crossing zero from equivalence, coverage from an F1 ceiling, and local from official scores. The mechanical fact-lock result is separate.",
    ),
    (
        "claim_strength",
        "Compare each conclusion with its evidence. A protocol name does not establish novelty; a jointly changed package does not isolate component causality; shared candidates do not remove all confounding. Preserve existing cautious wording.",
    ),
    (
        "definitions_boundaries",
        "Check first-use definitions, denominator and admission rules, output availability, shared resources, evaluation scope and limitations. Preserve material boundaries once without demanding repetition.",
    ),
    (
        "traceable_revision",
        "Give the exact candidate span, relevant source/evidence, reason and smallest useful edit. Distinguish severity from confidence; mark uncertainty rather than inventing a finding.",
    ),
)


def plan(source: str, candidate: str) -> dict:
    body = {
        "schema_version": "arw.writing-review-plan.v1",
        "source_sha256": sha256_hex(source.encode()),
        "candidate_sha256": sha256_hex(candidate.encode()),
        "tasks": [
            {"category": category, "instruction": instruction}
            for category, instruction in TASKS
        ],
        "policy": "Semantic findings are reviewer judgments, not automatic fact or quality scores. Only the existing mechanical preservation/fact checks can automatically reject prose.",
    }
    return {**body, "plan_sha256": sha256_hex(canonical_json_bytes(body))}


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Span(Strict):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=4096)


class Coverage(Strict):
    category: Literal[
        "argument_structure",
        "fact_integrity",
        "claim_strength",
        "definitions_boundaries",
        "traceable_revision",
    ]
    status: Literal["reviewed", "not_applicable", "not_reviewed"]
    reason: NoteText


class Finding(Strict):
    category: Literal[
        "argument_structure",
        "fact_integrity",
        "claim_strength",
        "definitions_boundaries",
        "traceable_revision",
    ]
    severity: Literal["warning", "suggestion"]
    confidence: Literal["low", "medium", "high"]
    review_status: Literal["open", "resolved", "accepted_risk"]
    candidate_span: Span
    source_span: Span | None = None
    evidence: EvidenceText
    reason: EvidenceText
    minimal_change: EvidenceText
    resolution_reason: NoteText | None = None

    @model_validator(mode="after")
    def explained_resolution(self):
        if self.review_status != "open" and not self.resolution_reason:
            raise ValueError("resolved or accepted risk finding needs an explanation")
        return self


class ReviewRulesReport(Strict):
    schema_version: Literal["arw.writing-rule-review.v1"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: ShortText
    reviewer: ShortText
    coverage: list[Coverage] = Field(
        min_length=len(CATEGORIES), max_length=len(CATEGORIES)
    )
    findings: list[Finding] = Field(max_length=128)

    @model_validator(mode="after")
    def complete_categories(self):
        if [item.category for item in self.coverage] != list(CATEGORIES):
            raise ValueError("rule review coverage must follow every task in order")
        return self


def _exact_span(span: Span, text: str) -> bool:
    return (
        0 <= span.start < span.end <= len(text)
        and text[span.start : span.end] == span.quote
    )


def validate_report(
    report: object, review_plan: dict, source: str, candidate: str
) -> dict:
    """Validate bindings and quotes, without pretending to judge semantic truth."""
    parsed = ReviewRulesReport.model_validate(report)
    if (
        parsed.source_sha256 != review_plan["source_sha256"]
        or parsed.candidate_sha256 != review_plan["candidate_sha256"]
        or parsed.plan_sha256 != review_plan["plan_sha256"]
        or any(not _exact_span(f.candidate_span, candidate) for f in parsed.findings)
        or any(
            f.source_span is not None and not _exact_span(f.source_span, source)
            for f in parsed.findings
        )
    ):
        raise ValueError("stale or unlocated rule review")
    coverage = {item.category: item.status for item in parsed.coverage}
    if any(coverage[f.category] != "reviewed" for f in parsed.findings):
        raise ValueError("finding category was not reviewed")
    return parsed.model_dump(mode="json")
