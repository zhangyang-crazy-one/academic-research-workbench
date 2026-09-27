"""Generated Draft 2020-12 contracts for the additive execution event family."""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter

from arw.kernel.state.models import (
    DatasetMetadataAcceptedPayload,
    ExecutionActionFinishedPayload,
    ExecutionActionStartedPayload,
    ExecutionArtifactBoundPayload,
    ExecutionContextAcceptedPayload,
)


def execution_provenance_schema_document() -> dict[str, Any]:
    document = TypeAdapter(
        ExecutionContextAcceptedPayload
        | DatasetMetadataAcceptedPayload
        | ExecutionActionStartedPayload
        | ExecutionActionFinishedPayload
        | ExecutionArtifactBoundPayload
    ).json_schema(mode="validation")
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = (
        "https://academic-research-workbench.local/schemas/v1/"
        "execution-provenance.schema.json"
    )
    return document
