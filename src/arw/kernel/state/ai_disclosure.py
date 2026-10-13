"""Additive AI participation assertions and frozen venue policy contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.accepted_ref import ParentArtifactRef
from arw.kernel.state.models import ActorId, Sha256, StableRuntimeId, StrictModel

Usage = Literal[
    "imported",
    "external_edit",
    "mixed",
    "grammar_only",
    "ai_drafted",
    "ai_drafted_human_edited",
]


class AIActivityReceipt(StrictModel):
    schema_version: Literal["arw.ai-activity-receipt.v1"] = "arw.ai-activity-receipt.v1"
    activity_id: StableRuntimeId
    target: ParentArtifactRef
    usage: Usage
    system: str = Field(min_length=1, max_length=256)
    harness: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=256)
    detail: str = Field(min_length=1, max_length=2048)


class AIParticipationDeclaration(StrictModel):
    schema_version: Literal["arw.ai-participation-declaration.v1"] = (
        "arw.ai-participation-declaration.v1"
    )
    declaration_id: StableRuntimeId
    target: ParentArtifactRef
    usage: Usage
    author_id: ActorId
    detail: str = Field(min_length=1, max_length=2048)
    system: str | None = Field(default=None, max_length=256)


class AIDisclosurePolicy(StrictModel):
    schema_version: Literal["arw.ai-disclosure-policy.v1"] = (
        "arw.ai-disclosure-policy.v1"
    )
    venue: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    verified_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = Field(min_length=1, max_length=1024)
    source_sha256: Sha256
    source_digest_scope: Literal["source-document", "retained-primary-excerpts"] = (
        "source-document"
    )
    source_excerpt: str | None = Field(default=None, max_length=1024)
    template: Literal["checklist", "acknowledgments"]
    requirements: tuple[Annotated[str, Field(min_length=1, max_length=2048)], ...] = (
        Field(min_length=1, max_length=16)
    )

    @field_validator("verified_on")
    @classmethod
    def valid_date(cls, value):
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        if not value.startswith("https://"):
            raise ValueError("policy source must be an HTTPS primary-source locator")
        return value

    @model_validator(mode="after")
    def excerpt_identity(self):
        if self.source_digest_scope == "retained-primary-excerpts":
            if (
                not self.source_excerpt
                or sha256_hex(self.source_excerpt.encode("utf-8")) != self.source_sha256
            ):
                raise ValueError("policy excerpt digest mismatch")
        elif self.source_excerpt is not None:
            raise ValueError("source-document digest cannot label an excerpt")
        return self

    @property
    def sha256(self):
        return sha256_hex(canonical_json_bytes(self.model_dump(mode="json")))


def ai_disclosure_schema_documents():
    result = {}
    for name, model in (
        ("ai-activity-receipt.schema.json", AIActivityReceipt),
        ("ai-participation-declaration.schema.json", AIParticipationDeclaration),
        ("ai-disclosure-policy.schema.json", AIDisclosurePolicy),
    ):
        document = model.model_json_schema()
        document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        document["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        result[name] = document
    return result
