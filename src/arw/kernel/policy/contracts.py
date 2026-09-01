"""Strict Phase 1 request/response contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from arw.kernel.policy.integration_lock import IntegrationVerification


RouteReasonCode = Literal[
    "integration_lock_not_verified",
    "integration_inputs_incomplete",
    "integration_lock_invalid_or_drifted",
]


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
    execution_mode: Literal["inline-role-prompts", "blocked"]
    source_adapter_version: Literal["0.1.27"]
    source_dependency_model: Literal["bundled-pinned-adapter"]
    source_bundled: Literal[True]
    integration_status: Literal["PASS", "BLOCKED"]
    integration_lock_sha256: str | None
    release_qualification: Literal["BLOCKED"]
    reason_codes: tuple[RouteReasonCode, ...]
    experiment_execution: Literal["disabled"]
    paper_ast_export: Literal["deferred-v2"]


def installed_route(
    verification: IntegrationVerification | None = None,
    *,
    blocked_reason: RouteReasonCode = "integration_lock_not_verified",
) -> RouteResult:
    """Return a non-mutating route that is formal only after exact verification."""

    return RouteResult(
        schema_version="1.0.0",
        workflow_family="academic-pipeline",
        execution_mode="inline-role-prompts" if verification is not None else "blocked",
        source_adapter_version="0.1.27",
        source_dependency_model="bundled-pinned-adapter",
        source_bundled=True,
        integration_status="PASS" if verification is not None else "BLOCKED",
        integration_lock_sha256=(
            verification.integration_lock_sha256 if verification is not None else None
        ),
        release_qualification="BLOCKED",
        reason_codes=() if verification is not None else (blocked_reason,),
        experiment_execution="disabled",
        paper_ast_export="deferred-v2",
    )
