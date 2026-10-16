"""Independent bounded scientific composition; existing v1 IRs are unchanged."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.research_artifact import (
    OutputDigest,
    RendererIdentity,
    ResearchBinding,
    ValidationPolicy,
    ValidationResults,
    VisualReviewer,
)

ShortText = Annotated[str, Field(min_length=1, max_length=120)]
Ratio = Annotated[int, Field(ge=1, le=8)]


class SequenceSegment(StrictModel):
    segment_id: StableRuntimeId
    text: ShortText
    highlighted: bool = False


class SequenceObject(StrictModel):
    kind: Literal["sequence"]
    object_id: StableRuntimeId
    state_id: StableRuntimeId
    segments: tuple[SequenceSegment, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique(self):
        if len({s.segment_id for s in self.segments}) != len(self.segments):
            raise ValueError("duplicate sequence segment")
        return self


class Entity(StrictModel):
    object_id: StableRuntimeId
    state_id: StableRuntimeId
    entity_type: ShortText
    label: ShortText


class EntityRelation(StrictModel):
    relation_id: StableRuntimeId
    source: StableRuntimeId
    target: StableRuntimeId
    relation_type: Literal["control", "data", "support"]
    label: ShortText
    directed: bool


class LocalGroup(StrictModel):
    label: ShortText
    members: tuple[StableRuntimeId, ...] = Field(min_length=1, max_length=8)


class EntityGraphObject(StrictModel):
    kind: Literal["entity_graph"]
    entities: tuple[Entity, ...] = Field(min_length=1, max_length=8)
    relations: tuple[EntityRelation, ...] = Field(max_length=12)
    expanded_group: LocalGroup | None = None

    @model_validator(mode="after")
    def endpoints(self):
        ids = [e.object_id for e in self.entities]
        relations = [r.relation_id for r in self.relations]
        if len(set(ids + relations)) != len(ids + relations):
            raise ValueError("duplicate graph identity")
        if any(r.source not in ids or r.target not in ids for r in self.relations):
            raise ValueError("relation endpoint absent")
        if self.expanded_group:
            members = self.expanded_group.members
            if len(set(members)) != len(members) or not set(members) <= set(ids):
                raise ValueError("invalid local group")
        return self


SCIENTIFIC_OBJECT = TypeAdapter(
    Annotated[SequenceObject | EntityGraphObject, Field(discriminator="kind")]
)


class SemanticEncoding(StrictModel):
    semantic_id: StableRuntimeId
    label: ShortText
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    shape: Literal["circle", "square", "diamond"]
    line_style: Literal["solid", "dashed", "dotted"]


class PanelPosition(StrictModel):
    row: int = Field(ge=0, le=3)
    column: int = Field(ge=0, le=3)
    row_span: int = Field(default=1, ge=1, le=4)
    column_span: int = Field(default=1, ge=1, le=4)
    align: Literal["start", "center", "end"] = "center"


class CompositionPanel(StrictModel):
    panel_id: StableRuntimeId
    role: Literal["audit_view", "quantitative", "schematic"]
    label: str = Field(pattern=r"^[a-d]$")
    title: ShortText
    reading_order: int = Field(ge=1, le=4)
    position: PanelPosition
    content_kind: Literal["sequence", "entity_graph", "accepted_v1"]
    content_ref: ResearchBinding
    content_sha256: Sha256
    renderer: RendererIdentity
    claims: tuple[ResearchBinding, ...] = Field(default=(), max_length=8)


class CompositionLayout(StrictModel):
    kind: Literal["row", "column", "grid"]
    row_ratios: tuple[Ratio, ...] = Field(min_length=1, max_length=4)
    column_ratios: tuple[Ratio, ...] = Field(min_length=1, max_length=4)
    gap_pt: int = Field(default=12, ge=4, le=36)
    axes: Literal["independent"] = "independent"


class FigureCompositionIR(StrictModel):
    schema_version: Literal["arw.figure-composition-ir.v1"] = (
        "arw.figure-composition-ir.v1"
    )
    artifact_kind: Literal["figure_composition"] = "figure_composition"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    visual_argument: str = Field(min_length=1, max_length=500)
    width_mm: float = Field(ge=40, le=500, allow_inf_nan=False)
    height_mm: float = Field(ge=40, le=500, allow_inf_nan=False)
    panels: tuple[CompositionPanel, ...] = Field(min_length=2, max_length=4)
    layout: CompositionLayout
    encodings: tuple[SemanticEncoding, ...] = Field(max_length=24)
    legend_ids: tuple[StableRuntimeId, ...] = Field(max_length=12)
    renderer_hints: RendererIdentity
    publication_critical: bool = False
    validation_policy: ValidationPolicy
    supersedes: StableRuntimeId | None = None

    @property
    def research_bindings(self):
        return tuple(b for p in self.panels for b in (p.content_ref, *p.claims))

    @model_validator(mode="after")
    def bounded_layout(self):
        for values in (
            [p.panel_id for p in self.panels],
            [p.label for p in self.panels],
            [e.semantic_id for e in self.encodings],
            [b.binding_id for b in self.research_bindings],
        ):
            if len(set(values)) != len(values):
                raise ValueError("duplicate composition identity")
        if sorted(p.reading_order for p in self.panels) != list(
            range(1, len(self.panels) + 1)
        ):
            raise ValueError("reading order must be contiguous")
        rows, cols = len(self.layout.row_ratios), len(self.layout.column_ratios)
        if (self.layout.kind == "row" and rows != 1) or (
            self.layout.kind == "column" and cols != 1
        ):
            raise ValueError("layout kind contradicts dimensions")
        occupied = set()
        for panel in self.panels:
            p = panel.position
            cells = {
                (r, c)
                for r in range(p.row, p.row + p.row_span)
                for c in range(p.column, p.column + p.column_span)
            }
            if (
                p.row + p.row_span > rows
                or p.column + p.column_span > cols
                or occupied & cells
            ):
                raise ValueError("overlapping or out-of-bounds panel")
            occupied |= cells
        if len(set(self.legend_ids)) != len(self.legend_ids) or not set(
            self.legend_ids
        ) <= {e.semantic_id for e in self.encodings}:
            raise ValueError("legend must reference unique shared encodings")
        if self.validation_policy.semantic != "REQUIRED":
            raise ValueError("composition semantic validation is required")
        if self.publication_critical and self.validation_policy.visual != "REQUIRED":
            raise ValueError("publication composition requires visual review")
        if self.supersedes == self.artifact_id:
            raise ValueError("composition cannot supersede itself")
        return self


class PanelTypography(StrictModel):
    panel_id: StableRuntimeId
    min_font_pt: float = Field(gt=0, allow_inf_nan=False)
    uniform_scale: float = Field(gt=0, allow_inf_nan=False)


class FigureCompositionReceipt(StrictModel):
    receipt_version: Literal["arw.figure-composition-receipt.v1"] = (
        "arw.figure-composition-receipt.v1"
    )
    artifact_kind: Literal["figure_composition"] = "figure_composition"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    ir_sha256: Sha256
    renderer: RendererIdentity
    inputs: tuple[ResearchBinding, ...]
    outputs: tuple[OutputDigest, ...]
    typography: tuple[PanelTypography, ...]
    min_font_pt: float = Field(gt=0, allow_inf_nan=False)
    font_family: Literal["Noto Sans CJK SC, sans-serif"] = (
        "Noto Sans CJK SC, sans-serif"
    )
    glyph_coverage: Literal["not_verified"] = "not_verified"
    axes: Literal["independent"] = "independent"
    validation_policy: ValidationPolicy
    validation: ValidationResults
    qualification: Literal["PASS", "FAIL"]
    purpose: Literal["publication-critical", "exploratory"]
    visual_reviewer: VisualReviewer | None
    reason_codes: tuple[str, ...]


def figure_composition_schema_documents():
    documents = {}
    for name, model in (
        ("figure-composition-ir.schema.json", FigureCompositionIR),
        ("figure-composition-receipt.schema.json", FigureCompositionReceipt),
    ):
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = value
    return documents
