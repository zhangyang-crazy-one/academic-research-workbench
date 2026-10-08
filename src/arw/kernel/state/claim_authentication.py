"""Authenticated-intent declarations require a separate accepted parent anchor."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from pydantic import Field, model_validator

from arw.kernel.state.claim_graph import DeclaredAttestation
from arw.kernel.state.models import (
    ActorId,
    EventId,
    RunId,
    Sha256,
    StableRuntimeId,
    StrictModel,
)


class AuthenticatedAuthority(StrictModel):
    kind: Literal["authenticated"] = "authenticated"
    authority_run_id: RunId
    authority_event_id: EventId
    authority_event_sha256: Sha256
    human_authority_sha256: Sha256
    accountable_actor_id: ActorId
    accountable_role: Literal["operator", "review_authority", "access_authority"]
    gate_id: StableRuntimeId
    scope: Annotated[str, Field(min_length=1, max_length=256)]


class AuthenticatedAttestation(DeclaredAttestation):
    schema_version: Literal["arw.claim-attestation.v2"] = "arw.claim-attestation.v2"
    authority: AuthenticatedAuthority

    @model_validator(mode="after")
    def authority_scope_and_prefix(self) -> Self:
        if self.scope != self.authority.scope:
            raise ValueError("authenticated authority scope must equal statement scope")
        if not any(
            r.run_id == self.authority.authority_run_id
            for r in self.snapshot_manifest.runs
        ):
            raise ValueError("authority run must be in the N-1 snapshot")
        return self


def parse_attestation(value: dict):
    if value.get("schema_version") == "arw.claim-attestation.v2":
        return AuthenticatedAttestation.model_validate(value)
    return DeclaredAttestation.model_validate(value)


def validate_project_ancestor(value: str) -> str:
    if value != "." and (not value or any(part != ".." for part in value.split("/"))):
        raise ValueError("project root relation must identify an ancestor")
    return value


def validate_run_locations(value: dict[str, str]) -> dict[str, str]:
    from arw.kernel.state.models import _execution_relative_path

    if len(value) > 32:
        raise ValueError("snapshot run locations exceed budget")
    for path in value.values():
        _execution_relative_path(path)
    return value


def authentication_schema_documents() -> dict[str, dict]:
    schema = AuthenticatedAttestation.model_json_schema()
    schema["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/claim-authenticated-attestation.schema.json"
    )
    from arw.kernel.state.models import ClaimAttestationAnchoredPayload

    anchor = ClaimAttestationAnchoredPayload.model_json_schema()
    anchor["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/claim-attestation-anchor.schema.json"
    )
    anchor["properties"]["attestation"] = {"$ref": schema["$id"]}
    return {
        "claim-authenticated-attestation.schema.json": schema,
        "claim-attestation-anchor.schema.json": anchor,
    }
