"""Advisory review annotations; no score or scientific gate fields."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.claim_graph import Occurrence, SnapshotManifest
from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel


class ClaimRevisionTarget(StrictModel):
    kind: Literal["claim-revision"] = "claim-revision"
    claim_id: StableRuntimeId
    revision: int = Field(ge=1)
    claim_sha256: Sha256


class OccurrenceTarget(StrictModel):
    kind: Literal["occurrence"] = "occurrence"
    occurrence: Occurrence


class ReviewConcern(StrictModel):
    schema_version: Literal["arw.review-concern.v1"] = "arw.review-concern.v1"
    concern_id: StableRuntimeId
    snapshot_manifest: SnapshotManifest
    target: Annotated[
        ClaimRevisionTarget | OccurrenceTarget, Field(discriminator="kind")
    ]
    proposition_type: Literal[
        "EVALUATION", "REQUEST", "FACT", "REFERENCE", "QUOTE", "NON-ARG"
    ] = "REQUEST"
    argumentative_zone: (
        Literal["BKG", "OTH", "OWN", "AIM", "TXT", "CTR", "BAS"] | None
    ) = None
    message: str = Field(min_length=1, max_length=2048)
    source: Literal["rule", "author"] = "author"
    advisory: Literal[True] = True


class ReviewConcernReport(StrictModel):
    schema_version: Literal["arw.review-concerns.v1"] = "arw.review-concerns.v1"
    generator_version: Literal["arw.review-diagnostics.v1"] = (
        "arw.review-diagnostics.v1"
    )
    snapshot_manifest: SnapshotManifest
    concerns: tuple[ReviewConcern, ...] = Field(max_length=1000)
    omitted_concern_count: int = Field(
        default=0, ge=0, exclude_if=lambda count: count == 0
    )
    interpretation: Literal[
        "advisory_only; not a score, scientific gate or predictor accuracy claim"
    ] = "advisory_only; not a score, scientific gate or predictor accuracy claim"
    corpus_redistribution: Literal[
        "not_performed; separate license review required"
    ] = "not_performed; separate license review required"

    @model_validator(mode="after")
    def one_vector(self):
        if len({c.concern_id for c in self.concerns}) != len(self.concerns):
            raise ValueError("duplicate concern IDs")
        if any(c.snapshot_manifest != self.snapshot_manifest for c in self.concerns):
            raise ValueError("concerns must bind one exact snapshot vector")
        return self

    @property
    def sha256(self):
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


def review_concern_schema_documents():
    result = {}
    for name, model in (
        ("review-concern.schema.json", ReviewConcern),
        ("review-concerns.schema.json", ReviewConcernReport),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result
