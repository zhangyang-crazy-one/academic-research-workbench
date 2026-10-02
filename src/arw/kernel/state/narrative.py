"""Provider-neutral, project-scoped paper argument strategy contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel

ArgumentFunction = Literal[
    "problem", "gap", "contribution", "argument", "evidence", "knowledge_boundary"
]
NarrativeRoute = Literal[
    "method_rq", "observation_mechanism", "resource_evaluation", "theory", "custom"
]


def _array(value: object) -> tuple:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, tuple):
        return value
    raise ValueError("narrative arrays must be JSON arrays")


class NarrativePlan(StrictModel):
    """Stable order and warrant, never a frozen finding or scientific conclusion."""

    schema_version: Literal["arw.narrative-plan.v1"] = "arw.narrative-plan.v1"
    route: NarrativeRoute
    rationale: Annotated[str, Field(min_length=12, max_length=2048)]
    problem_to_contribution: Annotated[str, Field(min_length=8, max_length=2048)]
    contribution_to_evidence: Annotated[str, Field(min_length=8, max_length=2048)]
    evidence_to_conclusion: Annotated[str, Field(min_length=8, max_length=2048)]
    scope_boundary: Annotated[str, Field(min_length=8, max_length=2048)]
    function_order: Annotated[tuple[ArgumentFunction, ...], BeforeValidator(_array)]
    evidence_forms: Annotated[
        tuple[
            Literal[
                "proof",
                "experiment",
                "observation",
                "annotation_validation",
                "theoretical_argument",
                "other",
            ],
            ...,
        ],
        BeforeValidator(_array),
    ]

    @model_validator(mode="after")
    def complete_strategy(self) -> Self:
        required = {
            "problem",
            "gap",
            "contribution",
            "argument",
            "evidence",
            "knowledge_boundary",
        }
        if len(self.function_order) != 6 or set(self.function_order) != required:
            raise ValueError(
                "function_order must order the six argument functions once; these are not chapters"
            )
        if not self.evidence_forms or len(set(self.evidence_forms)) != len(
            self.evidence_forms
        ):
            raise ValueError("evidence_forms must name at least one distinct form")
        for name in (
            "rationale",
            "problem_to_contribution",
            "contribution_to_evidence",
            "evidence_to_conclusion",
            "scope_boundary",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        return self


class NarrativeSnapshot(StrictModel):
    schema_version: Literal["arw.narrative-snapshot.v1"] = "arw.narrative-snapshot.v1"
    project_id: StableRuntimeId
    version: Annotated[int, Field(ge=1)]
    sha256: Sha256
    plan: NarrativePlan
