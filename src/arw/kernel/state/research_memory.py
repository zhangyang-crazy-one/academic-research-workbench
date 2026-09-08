"""Harness-neutral memory documents, bounded queries and explicit handoffs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import (
    ActorId,
    EventId,
    RunId,
    Sha256,
    StableRuntimeId,
    StrictModel,
    UtcTimestamp,
)

MemoryKind = Literal[
    "context",
    "handoff",
    "decision_note",
    "lesson",
    "blocker",
    "experiment_note",
    "source_note",
    "reproduction_note",
]
MemoryScope = Literal["run", "project", "team", "user"]
MemoryStatus = Literal["created", "active", "superseded", "rejected", "distilled"]
MemoryTrust = Literal["unreviewed", "advisory", "verified"]
Harness = Literal["codex", "claude", "cursor", "other"]
Note = Annotated[str, Field(min_length=1, max_length=1200)]


class SourceRunHarness(StrictModel):
    run_id: RunId
    harness: Harness


class Handoff(StrictModel):
    objective: Note
    current_state: Note
    completed_work: tuple[Note, ...] = Field(max_length=32)
    evidence_gathered: tuple[Note, ...] = Field(max_length=32)
    commands_evaluations_run: tuple[Note, ...] = Field(max_length=32)
    relevant_artifacts_issues_files: tuple[Note, ...] = Field(max_length=32)
    open_questions: tuple[Note, ...] = Field(max_length=32)
    blockers: tuple[Note, ...] = Field(max_length=32)
    risks: tuple[Note, ...] = Field(max_length=32)
    next_concrete_action: Note
    source_run_harness: SourceRunHarness
    intended_target_harness: Harness


class MemoryLink(StrictModel):
    kind: Literal["memory", "artifact", "decision", "author_target", "issue", "file"]
    target_id: str = Field(min_length=1, max_length=256)
    sha256: Sha256 | None = None
    event_id: EventId | None = None


class MemoryInput(StrictModel):
    memory_id: StableRuntimeId | None = None
    kind: MemoryKind
    scope: MemoryScope = "project"
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=16_384)
    source_ledger_event_ids: tuple[EventId, ...] = Field(default=(), max_length=64)
    source_artifact_ids: tuple[StableRuntimeId, ...] = Field(default=(), max_length=64)
    links: tuple[MemoryLink, ...] = Field(default=(), max_length=64)
    supersedes: tuple[StableRuntimeId, ...] = Field(default=(), max_length=16)
    privacy_classification: Literal["project_private", "shareable", "sensitive"] = (
        "project_private"
    )
    tags: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...] = Field(
        default=(), max_length=16
    )
    handoff: Handoff | None = None

    @model_validator(mode="after")
    def shape(self):
        if (self.kind == "handoff") != (self.handoff is not None):
            raise ValueError(
                "handoff kind requires exactly the structured handoff fields"
            )
        if len(self.supersedes) != len(set(self.supersedes)):
            raise ValueError("duplicate supersession target")
        if self.memory_id in self.supersedes:
            raise ValueError("memory cannot supersede itself")
        if self.scope == "team" and self.privacy_classification != "shareable":
            raise ValueError("team memory requires explicit shareable classification")
        return self


class ResearchMemory(MemoryInput):
    schema_version: Literal["arw.research-memory.v1"]
    memory_id: StableRuntimeId
    project_id: StableRuntimeId
    run_id: RunId
    source_harness: Harness
    source_agent: ActorId
    created_at: UtcTimestamp
    status: MemoryStatus
    trust: MemoryTrust
    content_digest: Sha256

    def digest_payload(self):
        return self.model_dump(mode="json", exclude={"content_digest"})

    def verify_digest(self):
        return self.content_digest == sha256_hex(
            canonical_json_bytes(self.digest_payload())
        )

    def logical_payload(self):
        value = {
            key: self.model_dump(mode="json")[key]
            for key in MemoryInput.model_fields
            if key != "memory_id"
        }
        return logical_memory_payload(
            value, project_id=self.project_id, run_id=self.run_id
        )


def logical_memory_payload(value, *, project_id, run_id):
    import copy

    value = copy.deepcopy(value)
    value.pop("memory_id", None)
    if value.get("handoff"):
        value["handoff"]["source_run_harness"].pop("harness", None)
        value["handoff"].pop("intended_target_harness", None)
    return {"project_id": project_id, "run_id": run_id, "content": value}


class MemoryQuery(StrictModel):
    query: str = Field(default="", max_length=256)
    scope: MemoryScope = "project"
    project_id: StableRuntimeId | None = None
    cross_project: bool = False
    run_id: RunId | None = None
    kind: MemoryKind | None = None
    since: UtcTimestamp | None = None
    max_items: int = Field(default=10, ge=1, le=50)
    max_tokens: int = Field(default=4096, ge=256, le=16_384)


class ProjectIdentity(StrictModel):
    schema_version: Literal["arw.project.v1"]
    project_id: StableRuntimeId


class CrossProjectGrant(StrictModel):
    project_id: StableRuntimeId
    root: str = Field(min_length=1, max_length=4096)


class MemoryAuthorization(StrictModel):
    schema_version: Literal["arw.memory-authorization.v1"] = (
        "arw.memory-authorization.v1"
    )
    allow_user_scope: bool = False
    cross_project_roots: tuple[CrossProjectGrant, ...] = Field(
        default=(), max_length=16
    )


def research_memory_schema_documents():
    documents = {}
    for name, model in [
        ("research-memory.schema.json", ResearchMemory),
        ("research-memory-input.schema.json", MemoryInput),
        ("research-memory-query.schema.json", MemoryQuery),
    ]:
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = value
    return documents
