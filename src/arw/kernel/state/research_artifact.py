"""Strict contracts for two research figure kinds and qualification receipts."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from arw.kernel.state.models import EventId, Sha256, StableRuntimeId, StrictModel


class ResearchBinding(StrictModel):
    binding_id: StableRuntimeId
    artifact_id: StableRuntimeId
    sha256: Sha256
    ledger_event_id: EventId
    ledger_event_sha256: Sha256
    json_pointer: str = Field(max_length=512, pattern=r"^(|/.*)$")


class FigureNode(StrictModel):
    id: StableRuntimeId
    kind: Literal[
        "claim",
        "evidence",
        "method",
        "experiment",
        "result",
        "artifact",
        "activity",
        "agent",
    ]
    label: str = Field(min_length=1, max_length=240)
    binding_id: StableRuntimeId
    confidence: int = Field(ge=0, le=100)


class FigureEdge(StrictModel):
    id: StableRuntimeId
    source: StableRuntimeId
    target: StableRuntimeId
    relation: Literal[
        "supports",
        "uses",
        "produces",
        "precedes",
        "derived_from",
        "associated_with",
        "causes",
    ]
    label: str = Field(min_length=1, max_length=100)
    binding_id: StableRuntimeId


class FigureGroup(StrictModel):
    id: StableRuntimeId
    label: str = Field(min_length=1, max_length=100)
    members: tuple[StableRuntimeId, ...] = Field(min_length=1, max_length=40)


class FigureAnnotation(StrictModel):
    id: StableRuntimeId
    role: Literal["caption", "manuscript_reference", "citation", "note"]
    text: str = Field(min_length=1, max_length=1200)
    binding_id: StableRuntimeId


class Presentation(StrictModel):
    theme: Literal["blue", "monochrome"]
    direction: Literal["top_to_bottom"]
    font_family: Literal["Noto Sans CJK SC, sans-serif"]


class RendererIdentity(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    identity_digest: Sha256
    normalization_policy: str = Field(min_length=1, max_length=96)


Applicability = Literal["REQUIRED", "OPTIONAL", "NOT_APPLICABLE"]
ValidationStatus = Literal[
    "PASS", "FAIL", "UNAVAILABLE", "NOT_APPLICABLE", "OPTIONAL_SKIPPED"
]


class ValidationPolicy(StrictModel):
    model_config = ConfigDict(strict=True, extra="forbid", serialize_by_alias=True)
    schema_: Literal["REQUIRED"] = Field(alias="schema")
    provenance: Literal["REQUIRED"]
    semantic: Applicability
    render: Literal["REQUIRED"]
    visual: Applicability


class ResearchArtifactIR(StrictModel):
    schema_version: Literal["arw.research-artifact-ir.v1"]
    artifact_id: StableRuntimeId
    artifact_kind: Literal["methodology_figure", "evidence_graph_view"]
    title: str = Field(min_length=1, max_length=180)
    author_target: str = Field(min_length=1, max_length=2000)
    publication_critical: bool
    research_bindings: tuple[ResearchBinding, ...] = Field(min_length=1, max_length=100)
    nodes: tuple[FigureNode, ...] = Field(min_length=1, max_length=40)
    edges: tuple[FigureEdge, ...] = Field(max_length=60)
    groups: tuple[FigureGroup, ...] = Field(max_length=10)
    annotations: tuple[FigureAnnotation, ...] = Field(max_length=20)
    presentation: Presentation
    renderer_hints: RendererIdentity
    validation_policy: ValidationPolicy
    supersedes: StableRuntimeId | None = None

    @model_validator(mode="after")
    def references(self):
        ids = (
            [n.id for n in self.nodes]
            + [e.id for e in self.edges]
            + [g.id for g in self.groups]
            + [a.id for a in self.annotations]
        )
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate figure element ID")
        nodes = {n.id for n in self.nodes}
        bindings = {b.binding_id for b in self.research_bindings}
        if len(bindings) != len(self.research_bindings):
            raise ValueError("duplicate binding ID")
        if any(e.source not in nodes or e.target not in nodes for e in self.edges):
            raise ValueError("edge endpoint is absent")
        if any(
            e.binding_id not in bindings
            for e in (*self.nodes, *self.edges, *self.annotations)
        ):
            raise ValueError("element binding is absent")
        members = [m for g in self.groups for m in g.members]
        if len(members) != len(set(members)) or any(m not in nodes for m in members):
            raise ValueError("groups overlap or name absent nodes")
        if self.publication_critical:
            if (
                self.validation_policy.semantic != "REQUIRED"
                or self.validation_policy.visual != "REQUIRED"
            ):
                raise ValueError(
                    "publication-critical figures require semantic and visual checks"
                )
            if not {"caption", "manuscript_reference"} <= {
                a.role for a in self.annotations
            }:
                raise ValueError(
                    "publication-critical figures require caption and manuscript bindings"
                )
        if self.supersedes == self.artifact_id:
            raise ValueError("artifact cannot supersede itself")
        return self


class OutputDigest(StrictModel):
    path: str = Field(
        min_length=1, max_length=512, pattern=r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
    )
    sha256: Sha256

    @model_validator(mode="after")
    def confined(self):
        if any(part in {".", ".."} for part in self.path.split("/")):
            raise ValueError("output path is not normalized")
        return self


class ValidationResults(StrictModel):
    model_config = ConfigDict(strict=True, extra="forbid", serialize_by_alias=True)
    schema_: ValidationStatus = Field(alias="schema")
    provenance: ValidationStatus
    semantic: ValidationStatus
    render: ValidationStatus
    visual: ValidationStatus


class VisualReviewer(StrictModel):
    tool_id: str = Field(min_length=1, max_length=96)
    version: str = Field(min_length=1, max_length=64)
    identity_digest: Sha256
    evidence_artifact_id: StableRuntimeId
    evidence_event_id: EventId
    evidence_event_sha256: Sha256


class ResearchArtifactReceipt(StrictModel):
    receipt_version: Literal["arw.research-artifact-receipt.v1"]
    artifact_id: StableRuntimeId
    artifact_kind: Literal["methodology_figure", "evidence_graph_view"]
    ir_sha256: Sha256
    renderer: RendererIdentity
    inputs: tuple[ResearchBinding, ...]
    outputs: tuple[OutputDigest, ...]
    validation_policy: ValidationPolicy
    validation: ValidationResults
    qualification: Literal["PASS", "FAIL"]
    purpose: Literal["publication-critical", "exploratory"]
    visual_reviewer: VisualReviewer | None
    reason_codes: tuple[str, ...] = Field(max_length=100)


def research_artifact_schema_documents():
    documents = {}
    for name, model in [
        ("research-artifact-ir.schema.json", ResearchArtifactIR),
        ("research-artifact-receipt.schema.json", ResearchArtifactReceipt),
    ]:
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = value
    return documents


def validate_artifact_event_progress(prior_events, event) -> None:
    """Replay rejects skipped compilation stages or changed frozen identities."""
    from arw.kernel.state.models import RESEARCH_ARTIFACT_EVENT_TYPES

    if event.event_type not in RESEARCH_ARTIFACT_EVENT_TYPES:
        return
    payload = event.payload
    prior = [
        e
        for e in prior_events
        if e.event_type in RESEARCH_ARTIFACT_EVENT_TYPES
        and e.payload.artifact_id == payload.artifact_id
    ]
    stages = [
        "research_artifact_ir_frozen",
        "research_artifact_rendered",
        "research_artifact_validated",
        "research_artifact_accepted",
    ]
    if event.event_type in stages:
        position = stages.index(event.event_type)
        if [e.event_type for e in prior] != stages[:position]:
            raise ValueError(
                "research artifact lifecycle stage is missing or duplicated"
            )
        accepted_digests = {
            e.event_sha256
            for e in prior_events
            if e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        }
        if (
            not payload.source_event_sha256
            or not set(payload.source_event_sha256) <= accepted_digests
        ):
            raise ValueError("research artifact references unaccepted research inputs")
        if (
            event.event_type == "research_artifact_accepted"
            and payload.supersedes is not None
        ):
            if payload.supersedes == payload.artifact_id or not any(
                e.event_type == "research_artifact_accepted"
                and e.payload.artifact_id == payload.supersedes
                for e in prior_events
            ):
                raise ValueError("supersession cycle or non-prior predecessor")
        if prior:
            frozen = prior[0].payload
            if any(
                getattr(frozen, key) != getattr(payload, key)
                for key in (
                    "ir_sha256",
                    "renderer_identity_digest",
                    "source_event_sha256",
                )
            ):
                raise ValueError("research artifact frozen identity changed")
            receipt_sha = (
                payload.artifact_sha256
                if event.event_type == "research_artifact_accepted"
                else payload.receipt_sha256
            )
            if receipt_sha != frozen.receipt_sha256:
                raise ValueError("research artifact qualification receipt changed")
    else:
        if len(prior) != 4 or prior[-1].event_type != "research_artifact_accepted":
            raise ValueError("supersession requires a newly accepted artifact")
        if (
            prior[-1].event_id != payload.accepting_event_id
            or prior[-1].payload.supersedes != payload.supersedes
        ):
            raise ValueError("supersession differs from its accepting event")
        if not any(
            e.event_type == "research_artifact_accepted"
            and e.payload.artifact_id == payload.supersedes
            for e in prior_events
        ):
            raise ValueError("superseded artifact is not accepted")
