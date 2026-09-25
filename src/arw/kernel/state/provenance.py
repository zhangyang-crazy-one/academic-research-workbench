"""Versioned provenance assertions and exact retained-source locations."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import (
    ActorId,
    EventId,
    Sha256,
    StableRuntimeId,
    StrictModel,
    UtcTimestamp,
)


class LineRange(StrictModel):
    kind: Literal["lines"]
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("line range is reversed")
        return self


class TextPage(StrictModel):
    kind: Literal["text_page"]
    page: int = Field(ge=1)


class MarkdownSection(StrictModel):
    kind: Literal["markdown_section"]
    heading: str = Field(min_length=1, max_length=300)
    occurrence: int = Field(ge=1, le=1000)


class ByteChunk(StrictModel):
    kind: Literal["byte_chunk"]
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("byte range is empty or reversed")
        return self


class PdfLocation(StrictModel):
    schema_version: Literal["arw.pdf-location.v1"]
    kind: Literal["pdf_page", "pdf_paragraph", "pdf_section", "pdf_region", "reference_entry"]
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    label: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    pdf_source_path: str = Field(min_length=1)
    pdf_sha256: Sha256
    extraction_manifest_path: str = Field(min_length=1)
    extraction_manifest_sha256: Sha256
    extractor_name: Literal["pypdf", "grobid", "docling"]
    extractor_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        if self.end <= self.start:
            raise ValueError("PDF byte range is empty or reversed")
        if self.kind == "pdf_region" and (self.bbox is None or self.extractor_name == "pypdf"):
            raise ValueError("PDF region requires structural coordinates from an extractor")
        if self.kind == "reference_entry" and not self.label:
            raise ValueError("reference entry requires its reference ID")
        if self.bbox is not None and (self.extractor_name == "pypdf" or
                                      not all(math.isfinite(value) for value in self.bbox) or
                                      self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]):
            raise ValueError("invalid or unsupported PDF coordinates")
        return self


class SourceLocator(StrictModel):
    schema_version: Literal["arw.source-locator.v1", "arw.source-locator.v2"]
    source_artifact_id: StableRuntimeId
    source_sha256: Sha256
    source_event_id: EventId
    source_event_sha256: Sha256
    producing_activity_id: StableRuntimeId
    location: Annotated[
        LineRange | TextPage | MarkdownSection | ByteChunk | PdfLocation, Field(discriminator="kind")
    ]
    quote_sha256: Sha256

    @model_validator(mode="after")
    def location_version(self):
        if isinstance(self.location, PdfLocation) != (self.schema_version == "arw.source-locator.v2"):
            raise ValueError("PDF locations require source locator v2")
        return self


class ProvenanceRecord(StrictModel):
    """One Lite-profile provenance assertion."""

    schema_version: Literal["1.0.0"]
    record_id: StableRuntimeId
    entity_id: StableRuntimeId
    entity_type: str = Field(min_length=1, max_length=96)
    artifact_id: StableRuntimeId
    ledger_event_id: EventId | None = None
    ledger_event_digest: Sha256 | None = None
    activity_id: StableRuntimeId
    agent_id: ActorId
    created_at: UtcTimestamp
    derived_from: tuple[StableRuntimeId, ...] = Field(max_length=500)
    attributes: dict[str, object]

    def artifact_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json", exclude={"ledger_event_id", "ledger_event_digest"}
        )

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def checksum(self) -> str:
        return sha256_hex(canonical_json_bytes(self.artifact_payload()))

    @property
    def binding_checksum(self) -> str:
        return sha256_hex(canonical_json_bytes(self.canonical_payload()))


class PreciseProvenanceRecord(ProvenanceRecord):
    schema_version: Literal["2.0.0"]
    source_locator: SourceLocator

    @model_validator(mode="after")
    def same_activity(self):
        if self.activity_id != self.source_locator.producing_activity_id:
            raise ValueError("locator producing activity does not match assertion")
        return self


_RECORD = TypeAdapter(
    Annotated[
        ProvenanceRecord | PreciseProvenanceRecord,
        Field(discriminator="schema_version"),
    ]
)


def decode_provenance(raw: bytes | str) -> ProvenanceRecord | PreciseProvenanceRecord:
    return _RECORD.validate_json(raw)


def provenance_schema_documents() -> dict[str, dict]:
    documents = {}
    for name, model in (
        ("source-locator.schema.json", SourceLocator),
        ("provenance-record-v2.schema.json", PreciseProvenanceRecord),
    ):
        document = model.model_json_schema()
        if model is PreciseProvenanceRecord:
            for field in ("ledger_event_id", "ledger_event_digest"):
                document["properties"].pop(field)
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = document
    return documents
