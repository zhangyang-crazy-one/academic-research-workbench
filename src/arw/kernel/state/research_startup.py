"""Bounded retained research startup requests; the journal remains authoritative."""

from typing import Literal

from pydantic import Field, model_validator

from arw.kernel.state.models import InitRunRequest, Sha256, StableRuntimeId, StrictModel


class ResearchStartPlan(StrictModel):
    schema_version: Literal["arw.research-start.v1"] = "arw.research-start.v1"
    project_id: StableRuntimeId
    project_identity_sha256: Sha256
    direction: str = Field(min_length=1, max_length=2048)
    phase: Literal["scoping", "literature", "experiment", "writing"]
    run_relative: str = Field(max_length=256)
    request: InitRunRequest

    @model_validator(mode="after")
    def scoped_path(self):
        if self.run_relative != f".arw/research/runs/{self.request.run_id}":
            raise ValueError("research run path differs from the retained run identity")
        if self.request.immutable_input.path != "input/research-intent.json":
            raise ValueError("research input path differs")
        if self.request.task_kind == "paper" and self.phase != "writing":
            raise ValueError(
                "paper startup requires the writing phase and selected narrative"
            )
        return self


def research_startup_schema_documents():
    document = ResearchStartPlan.model_json_schema()
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/research-startup.schema.json"
    )
    return {"research-startup.schema.json": document}
