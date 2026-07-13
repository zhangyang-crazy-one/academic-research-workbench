"""Strict Phase 1 canonical run and event models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


SCHEMA_VERSION = "1.0.0"
ZERO_HASH = "0" * 64

RunId = Annotated[
    str,
    StringConstraints(
        pattern=r"^run-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
EventId = Annotated[
    str,
    StringConstraints(
        pattern=r"^evt-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
CommandId = Annotated[
    str,
    StringConstraints(
        pattern=r"^cmd-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ActorId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9.-]{2,63}$")]
ProbeId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9.-]{2,63}$")]
UtcTimestamp = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    ),
]
Capability = Literal["canonical-journal", "forced-stop-replay"]


class StrictModel(BaseModel):
    """Base configuration for every canonical boundary model."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_extra={"$schema": "https://json-schema.org/draft/2020-12/schema"},
    )


class ImmutableInput(StrictModel):
    """Digest-bound repository-relative input identity."""

    path: str
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def relative_posix_path(cls, value: str) -> str:
        if not value or "\x00" in value or "\\" in value:
            raise ValueError("immutable input path must be a non-empty POSIX path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("immutable input path must be normalized and relative")
        return value


class RunManifest(StrictModel):
    """Immutable identity written exactly once when a run is initialized."""

    schema_version: Literal["1.0.0"]
    run_id: RunId
    created_at: UtcTimestamp
    immutable_input: ImmutableInput
    workflow_family: Literal["academic-pipeline"]
    workflow_mode: Literal["inline-role-prompts"]
    capabilities: list[Capability] = Field(min_length=1)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class RunInitializedPayload(StrictModel):
    manifest_sha256: Sha256


class BaselineProbePayload(StrictModel):
    probe_id: ProbeId
    status: Literal["pass", "fail"]
    summary: Annotated[str, Field(min_length=1, max_length=256)]


class CanonicalEvent(StrictModel):
    """One of the only two event envelopes admitted in Phase 1."""

    schema_version: Literal["1.0.0"]
    event_type: Literal["run.initialized", "baseline.probe_recorded"]
    event_id: EventId
    command_id: CommandId
    run_id: RunId
    sequence: Annotated[int, Field(ge=1)]
    occurred_at: UtcTimestamp
    expected_revision: Annotated[int, Field(ge=0)]
    resulting_revision: Annotated[int, Field(ge=1)]
    actor_id: ActorId
    prev_event_sha256: Sha256
    payload: RunInitializedPayload | BaselineProbePayload
    event_sha256: Sha256

    @model_validator(mode="after")
    def valid_variant_and_revision(self) -> Self:
        expected_payload = (
            RunInitializedPayload
            if self.event_type == "run.initialized"
            else BaselineProbePayload
        )
        if not isinstance(self.payload, expected_payload):
            raise ValueError("event_type and payload variant do not match")
        if self.resulting_revision != self.expected_revision + 1:
            raise ValueError("resulting_revision must increment expected_revision once")
        return self


class InitRunRequest(StrictModel):
    """Strict operator request used to construct manifest and initial event."""

    schema_version: Literal["1.0.0"]
    run_id: RunId
    occurred_at: UtcTimestamp
    immutable_input: ImmutableInput
    workflow_family: Literal["academic-pipeline"]
    workflow_mode: Literal["inline-role-prompts"]
    capabilities: list[Capability] = Field(min_length=1)
    event_id: EventId
    command_id: CommandId
    actor_id: ActorId

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_unique(cls, value: list[Capability]) -> list[Capability]:
        if len(value) != len(set(value)):
            raise ValueError("capabilities must be unique")
        return value


class AppendProbeRequest(StrictModel):
    """Strict Phase 1 append request; sequence and hashes are writer-owned."""

    schema_version: Literal["1.0.0"]
    event_type: Literal["baseline.probe_recorded"]
    event_id: EventId
    command_id: CommandId
    run_id: RunId
    occurred_at: UtcTimestamp
    expected_revision: Annotated[int, Field(ge=1)]
    actor_id: ActorId
    payload: BaselineProbePayload
