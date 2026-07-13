"""Strict Phase 1 request/response contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RouteResult(BaseModel):
    """Read-only routing decision exposed by the installed skill."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema"
        },
    )

    schema_version: Literal["1.0.0"]
    workflow_family: Literal["academic-pipeline"]
    execution_mode: Literal["inline-role-prompts"]
    source_adapter_version: Literal["0.1.19"]
    experiment_execution: Literal["disabled"]


def installed_route() -> RouteResult:
    """Return the deterministic, non-mutating Phase 1 route."""

    return RouteResult(
        schema_version="1.0.0",
        workflow_family="academic-pipeline",
        execution_mode="inline-role-prompts",
        source_adapter_version="0.1.19",
        experiment_execution="disabled",
    )

