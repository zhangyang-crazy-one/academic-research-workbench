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
    """Read-only routing decision exposed by the installed skill.

    Host integration evidence is advisory: a missing, incomplete, or drifted
    integration lock yields ``UNVERIFIED`` with a reason code, never a blocked
    route. Release qualification and experiment execution are reported by
    their own commands, not by ``route``.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema"
        },
    )

    schema_version: Literal["1.1.0"]
    workflow_family: Literal["academic-pipeline"]
    execution_mode: Literal["inline-role-prompts"]
    source_adapter_version: Literal["0.1.27"]
    source_dependency_model: Literal["bundled-pinned-adapter"]
    source_bundled: Literal[True]
    integration_status: Literal["PASS", "UNVERIFIED"]
    integration_lock_sha256: str | None
    reason_codes: tuple[RouteReasonCode, ...]
    paper_ast_export: Literal["deferred-v2"]


def installed_route(
    verification: IntegrationVerification | None = None,
    *,
    unverified_reason: RouteReasonCode = "integration_lock_not_verified",
) -> RouteResult:
    """Return a non-mutating route; exact verification only upgrades the status."""

    return RouteResult(
        schema_version="1.1.0",
        workflow_family="academic-pipeline",
        execution_mode="inline-role-prompts",
        source_adapter_version="0.1.27",
        source_dependency_model="bundled-pinned-adapter",
        source_bundled=True,
        integration_status="PASS" if verification is not None else "UNVERIFIED",
        integration_lock_sha256=(
            verification.integration_lock_sha256 if verification is not None else None
        ),
        reason_codes=() if verification is not None else (unverified_reason,),
        paper_ast_export="deferred-v2",
    )
