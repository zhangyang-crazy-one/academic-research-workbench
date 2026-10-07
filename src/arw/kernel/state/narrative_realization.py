"""Content-bound, provider-neutral paper argument realization contract."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, field_validator, model_validator

from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.narrative import ArgumentFunction


def _array(value: object) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    raise ValueError("nodes must be a JSON array")


class NarrativeSpan(StrictModel):
    """UTF-8 byte offsets of one paragraph in retained source content."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    sha256: Sha256

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("span end must follow start")
        return self


class NarrativeNode(StrictModel):
    node_id: StableRuntimeId
    function_id: ArgumentFunction
    narrative_sha256: Sha256
    span: NarrativeSpan
    claim_id: StableRuntimeId | None = None
    contribution_id: StableRuntimeId | None = None
    evidence_ref: StableRuntimeId | None = None
    evidence_form: Literal["proof", "experiment", "observation", "annotation_validation", "theoretical_argument", "other"] | None = None
    knowledge_boundary_id: StableRuntimeId | None = None
    conclusion: bool = False
    within_scope_boundary: bool | None = None
    post_hoc: bool = False
    hypothesis_history_ref: StableRuntimeId | None = None
    evidence_source_artifact_id: StableRuntimeId | None = None
    evidence_source_sha256: Sha256 | None = None
    new_claim_reason: str | None = Field(default=None, max_length=1024)
    interleave_reason: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def source_binding_pair(self):
        if (self.evidence_source_artifact_id is None) != (self.evidence_source_sha256 is None):
            raise ValueError("evidence source artifact and digest must occur together")
        return self


class NarrativeRealization(StrictModel):
    schema_version: Literal["arw.narrative-realization.v1"] = "arw.narrative-realization.v1"
    stage: Literal["outline", "blueprint", "draft"]
    narrative_sha256: Sha256
    source_path: str = Field(min_length=1, max_length=512)
    source_sha256: Sha256
    predecessor_artifact_id: StableRuntimeId | None = None
    nodes: Annotated[tuple[NarrativeNode, ...], BeforeValidator(_array), Field(min_length=1, max_length=512)]

    @field_validator("source_path")
    @classmethod
    def confined_source_path(cls, value: str) -> str:
        if ("\\" in value or "\x00" in value or PurePosixPath(value).is_absolute()
                or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise ValueError("source path must be normalized and relative")
        return value

    @model_validator(mode="after")
    def identities(self):
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate narrative node ID")
        if self.stage == "outline" and self.predecessor_artifact_id is not None:
            raise ValueError("outline cannot name a predecessor")
        if self.stage != "outline" and self.predecessor_artifact_id is None:
            raise ValueError("blueprint and draft require an accepted predecessor")
        return self


class HypothesisHistory(StrictModel):
    """Accepted author annotation; temporal truth still needs human scrutiny."""

    schema_version: Literal["arw.hypothesis-history.v1"] = "arw.hypothesis-history.v1"
    claim_id: StableRuntimeId
    designation: Literal["prespecified", "post_hoc", "unknown"]
    narrative_sha256: Sha256
    source_path: str = Field(min_length=1, max_length=512)
    source_sha256: Sha256
    span: NarrativeSpan

    @field_validator("source_path")
    @classmethod
    def confined_source_path(cls, value: str) -> str:
        return NarrativeRealization.confined_source_path(value)


def narrative_realization_schema_documents() -> dict[str, dict]:
    documents = {}
    for name, model in (
        ("narrative-realization.schema.json", NarrativeRealization),
        ("hypothesis-history.schema.json", HypothesisHistory),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = document
    return documents
