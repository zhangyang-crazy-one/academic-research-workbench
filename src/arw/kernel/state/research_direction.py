"""Domain-neutral data contracts for external direction and intake candidates."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from arw.kernel.state.accepted_ref import AcceptedRef
from arw.kernel.state.models import RunId, Sha256, StableRuntimeId, StrictModel

Text = Annotated[str, Field(min_length=1, max_length=2048)]
ShortText = Annotated[str, Field(min_length=1, max_length=256)]


class PackageSource(StrictModel):
    pointer: Text
    license: ShortText
    status: Literal["synthetic", "candidate", "metadata_only", "read"]


class HypothesisCandidate(StrictModel):
    hypothesis_id: StableRuntimeId
    branch_id: StableRuntimeId
    definition_id: StableRuntimeId
    statement: Text
    scope: Text
    required_controls: list[
        Literal["baseline", "equal_budget", "sham", "held_out", "all_attempts", "costs"]
    ] = Field(default_factory=list, max_length=6)


class DirectionPackage(StrictModel):
    schema_version: Literal["arw.direction-package.v1"] = "arw.direction-package.v1"
    package_id: StableRuntimeId
    package_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=32)
    package_sha256: Sha256
    title: ShortText
    scope: Text
    provenance: list[PackageSource] = Field(min_length=1, max_length=32)
    unknowns: list[Text] = Field(min_length=1, max_length=32)
    profile: dict
    profile_history: list[dict] = Field(default_factory=list, max_length=8)
    hypotheses: list[HypothesisCandidate] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique_hypotheses(self):
        ids = [item.hypothesis_id for item in self.hypotheses]
        if len(ids) != len(set(ids)):
            raise ValueError("direction hypothesis IDs must be unique")
        return self


class Operationalization(StrictModel):
    schema_version: Literal["arw.operationalization.v1"] = "arw.operationalization.v1"
    definition_id: StableRuntimeId
    sources: list[AcceptedRef] = Field(default_factory=list, max_length=16)
    author_interpretation: Text
    rival_explanations: list[Text] = Field(min_length=1, max_length=16)
    local_definition: Text
    measured_object: Text
    metric_definition: Text
    why_relevant: Text
    alternative_measurements: list[Text] = Field(min_length=1, max_length=16)
    confounders: list[Text] = Field(min_length=1, max_length=16)
    refuting_observations: list[Text] = Field(min_length=1, max_length=16)
    cannot_conclude: list[Text] = Field(min_length=1, max_length=16)
    assumptions: list[Text] = Field(default_factory=list, max_length=16)
    evidence_sought: list[Text] = Field(default_factory=list, max_length=16)


class ComparisonCondition(StrictModel):
    condition_id: StableRuntimeId
    role: Literal["baseline", "intervention", "sham", "other"]
    model_label: ShortText
    data_sha256: Sha256
    evaluation_sha256: Sha256
    token_budget: int = Field(ge=0, le=1_000_000_000)
    held_out_sha256: Sha256 | None = None


class DirectionEvidence(StrictModel):
    relation: Literal["supports", "opposes", "neutral", "null_result", "failed"]
    ref: AcceptedRef


class DirectionCase(StrictModel):
    hypothesis_id: StableRuntimeId
    definition_ref: AcceptedRef | None = None
    contract_sha256: Sha256 | None = None
    contract_version: int | None = Field(default=None, ge=1)
    result_sha256: Sha256 | None = None
    conditions: list[ComparisonCondition] = Field(default_factory=list, max_length=16)
    costs_ref: AcceptedRef | None = None
    attempts_ref: AcceptedRef | None = None
    evidence: list[DirectionEvidence] = Field(default_factory=list, max_length=32)
    narrative_candidate: Text | None = None


class DirectionBinding(StrictModel):
    schema_version: Literal["arw.direction-binding.v1"] = "arw.direction-binding.v1"
    project_id: StableRuntimeId
    ars_project_ref: Text
    run_id: RunId
    run_manifest_sha256: Sha256
    initial_event_sha256: Sha256
    package_sha256: Sha256
    package_snapshot: str = Field(max_length=256)
    branch_sha256: Sha256 | None = None
    branch_snapshot: str | None = Field(default=None, max_length=256)
    cases: list[DirectionCase] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def snapshot_addresses(self):
        if (
            self.package_snapshot
            != f".arw/research/directions/packages/{self.package_sha256}.json"
        ):
            raise ValueError("direction package snapshot address differs")
        expected = (
            None
            if self.branch_sha256 is None
            else f".arw/research/directions/branches/{self.branch_sha256}.json"
        )
        if self.branch_snapshot != expected:
            raise ValueError("direction branch snapshot address differs")
        ids = [c.hypothesis_id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("direction case IDs must be unique")
        return self


class VersionedReading(StrictModel):
    source_id: StableRuntimeId
    # The composition layer delegates this exact document to ReferenceRecord;
    # core state does not duplicate the citation policy contract.
    reference: dict
    version_label: ShortText
    carrier: Literal["web_abstract", "html", "pdf", "text"]
    source_sha256: Sha256 | None = None
    source_ref: AcceptedRef | None = None
    citation_receipts: list[Sha256] = Field(default_factory=list, max_length=16)
    reader: Literal["human", "tool", "unknown"]
    reading_status: Literal[
        "not_read", "partial", "read_declared", "failed", "timed_out"
    ]
    read_ranges: list[ShortText] = Field(default_factory=list, max_length=32)
    note: Text
    limitations: list[Text] = Field(min_length=1, max_length=16)
    affected_records: list[StableRuntimeId] = Field(default_factory=list, max_length=32)


class LiteratureIntake(StrictModel):
    schema_version: Literal["arw.literature-intake.v1"] = "arw.literature-intake.v1"
    project_id: StableRuntimeId
    package_sha256: Sha256
    sources: list[VersionedReading] = Field(min_length=1, max_length=64)


DIRECTION_ADAPTER = TypeAdapter(
    Annotated[
        DirectionPackage | DirectionBinding | Operationalization | LiteratureIntake,
        Field(discriminator="schema_version"),
    ]
)


def research_direction_schema_documents():
    document = DIRECTION_ADAPTER.json_schema()
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/research-direction.schema.json"
    )
    return {"research-direction.schema.json": document}
