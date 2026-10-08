"""Additive scoped references; no conversion of legacy authoritative bytes."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, field_validator

from arw.kernel.state.models import EventId, RunId, Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.provenance import SourceLocator


def validate_pointer(value: str) -> str:
    if value and not value.startswith("/"):
        raise ValueError("selector must be a JSON Pointer")
    if re.search(r"~(?![01])", value):
        raise ValueError("invalid JSON Pointer escape")
    return value


class ParentArtifactRef(StrictModel):
    scope: Literal["parent-artifact"] = "parent-artifact"
    project_id: StableRuntimeId
    run_id: RunId
    run_manifest_sha256: Sha256
    artifact_id: StableRuntimeId
    accepting_event_id: EventId
    accepting_event_sha256: Sha256
    content_sha256: Sha256
    selector: str = Field(default="", max_length=2048)
    selected_sha256: Sha256 | None = None
    producing_activity_id: StableRuntimeId | None = None
    # A locator retains its original full contract rather than reducing its
    # PDF/extraction/quote checks to a generic JSON selector.
    source_locator: SourceLocator | None = None

    _pointer = field_validator("selector")(validate_pointer)


class JournalEventRef(StrictModel):
    scope: Literal["project-journal"] = "project-journal"
    project_id: StableRuntimeId
    sequence: int = Field(ge=1)
    event_sha256: Sha256
    payload_selector: str = Field(default="", max_length=2048)

    _pointer = field_validator("payload_selector")(validate_pointer)



ParentArtifactRef.model_rebuild()
AcceptedRef = Annotated[
    ParentArtifactRef | JournalEventRef, Field(discriminator="scope")
]
ACCEPTED_REF_ADAPTER = TypeAdapter(AcceptedRef)
ADAPTER_MATRIX_VERSION = "arw.accepted-ref-adapters.v1"


def accepted_ref_schema_documents() -> dict[str, dict]:
    document = ACCEPTED_REF_ADAPTER.json_schema()
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/accepted-ref.schema.json"
    )
    return {"accepted-ref.schema.json": document}
