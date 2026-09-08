"""Portable learning contracts; learned content never grants execution authority."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from arw.kernel.state.models import (
    EventId,
    RunId,
    Sha256,
    StableRuntimeId,
    StrictModel,
    UtcTimestamp,
)

Text = Annotated[str, Field(min_length=1, max_length=1200)]
Scope = Literal["run", "project", "domain", "global"]
Status = Literal[
    "candidate", "evaluated", "qualified", "rejected", "superseded", "promoted"
]
Mode = Literal["replay", "held-out", "shadow", "A-B", "human-review", "benchmark"]


class LearningObservation(StrictModel):
    schema_version: Literal["arw.learning-observation.v1"] = (
        "arw.learning-observation.v1"
    )
    observation_id: StableRuntimeId
    project_id: StableRuntimeId
    run_id: RunId
    ledger_event_id: EventId
    observation_kind: Literal[
        "artifact_receipt",
        "transition",
        "validation",
        "human_signal",
        "experiment",
        "tool_receipt",
    ]
    source_activity_id: StableRuntimeId | None = None
    source_tool_id: StableRuntimeId | None = None
    source_artifact_ids: tuple[StableRuntimeId, ...] = Field(default=(), max_length=64)
    trigger: Text
    outcome: Text
    human_signal: Text | None = None
    created_at: UtcTimestamp
    source_digest: Sha256
    privacy_classification: Literal["project_private", "shareable"] = "project_private"
    duplicate_of: StableRuntimeId | None = None
    dedup_policy: Literal["ledger-event-and-source-digest-v1"] = (
        "ledger-event-and-source-digest-v1"
    )


class UnknownEvidence(StrictModel):
    observation_id: StableRuntimeId
    rationale: Text


class Applicability(StrictModel):
    task: Text
    model: Text
    retrieval_coverage: Text
    call_budget: int = Field(ge=0)
    output_budget: int = Field(ge=0)
    metric: Text


class HeuristicInput(StrictModel):
    heuristic_id: StableRuntimeId
    scope: Scope = "project"
    domain_id: StableRuntimeId | None = None
    domain: Text
    trigger: Text
    proposed_action: Text
    applicability: Applicability
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    supporting_observation_ids: tuple[StableRuntimeId, ...] = Field(
        min_length=1, max_length=64
    )
    counterexample_observation_ids: tuple[StableRuntimeId, ...] = Field(
        default=(), max_length=64
    )
    unknown: tuple[UnknownEvidence, ...] = Field(default=(), max_length=64)
    search_coverage: Text
    evaluation_coverage: Text
    producer: Text
    producer_version: Text
    model_id: Text | None = None
    input_digest: Sha256 | None = None
    output_digest: Sha256 | None = None
    supersedes: StableRuntimeId | None = None

    @model_validator(mode="after")
    def valid_buckets(self):
        ids = [
            *self.supporting_observation_ids,
            *self.counterexample_observation_ids,
            *(u.observation_id for u in self.unknown),
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence buckets must be disjoint and deduplicated")
        if self.supersedes == self.heuristic_id:
            raise ValueError("self supersession is forbidden")
        if self.model_id and not (self.input_digest and self.output_digest):
            raise ValueError(
                "model extraction requires input/output digests and producer version"
            )
        return self


class ResearchHeuristic(HeuristicInput):
    schema_version: Literal["arw.research-heuristic.v1"] = "arw.research-heuristic.v1"
    project_id: StableRuntimeId
    run_id: RunId
    supporting_run_ids: tuple[RunId, ...]
    counterexample_run_ids: tuple[RunId, ...]
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    status: Status
    trust: Literal["unreviewed", "advisory"]
    qualification_receipt_id: Sha256 | None = None
    accepted_ledger_event_id: EventId | None = None


class EvaluationPolicy(StrictModel):
    schema_version: Literal["arw.learning-policy.v1"] = "arw.learning-policy.v1"
    policy_id: StableRuntimeId
    version: Text
    mode: Mode
    run_subset: tuple[RunId, ...] = Field(min_length=1, max_length=256)
    metric: Text
    minimum_delta: float = Field(allow_inf_nan=False)
    independence: Literal["one-sample-per-run-v1"] = "one-sample-per-run-v1"
    use_confidence: bool = False
    formula_id: Literal["supporting-fraction"] | None = None
    formula_version: Literal["1"] | None = None

    @model_validator(mode="after")
    def formula(self):
        if self.use_confidence and not (self.formula_id and self.formula_version):
            raise ValueError("confidence qualification requires a versioned formula")
        if len(set(self.run_subset)) != len(self.run_subset):
            raise ValueError("evaluation run subset must be unique")
        return self


class EvaluationSample(StrictModel):
    schema_version: Literal["arw.learning-sample.v1"] = "arw.learning-sample.v1"
    heuristic_id: StableRuntimeId
    policy_id: StableRuntimeId
    policy_version: Text
    run_id: RunId
    mode: Mode
    metric: Text
    baseline: float = Field(allow_inf_nan=False)
    outcome: float = Field(allow_inf_nan=False)
    proposed_action: Text
    actual_action: Text
    reviewer: Text | None = None
    approved: bool | None = None


class LearningConfiguration(StrictModel):
    enabled: bool = False
    disabled_run_ids: tuple[RunId, ...] = Field(default=(), max_length=256)
    evaluation_policy_artifact_id: StableRuntimeId | None = None


def learning_schema_documents():
    result = {}
    for name, model in [
        ("research-learning-observation.schema.json", LearningObservation),
        ("research-heuristic.schema.json", ResearchHeuristic),
        ("research-heuristic-input.schema.json", HeuristicInput),
        ("research-learning-policy.schema.json", EvaluationPolicy),
        ("research-learning-sample.schema.json", EvaluationSample),
    ]:
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result
