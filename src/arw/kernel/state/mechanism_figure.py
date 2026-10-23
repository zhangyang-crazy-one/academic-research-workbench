"""Source-bound mechanism facts and a separate manually laid out figure contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.research_artifact import (
    OutputDigest,
    RendererIdentity,
    ResearchBinding,
    ValidationPolicy,
    ValidationResults,
    VisualReviewer,
)

Text = Annotated[str, Field(min_length=1, max_length=100)]
Point = Annotated[float, Field(ge=0, le=1400, allow_inf_nan=False)]


class MechanismPort(StrictModel):
    port_id: StableRuntimeId
    direction: Literal["input", "output"]
    value_type: StableRuntimeId
    object_id: StableRuntimeId
    state_id: StableRuntimeId


class TokenCorrespondence(StrictModel):
    token_id: StableRuntimeId
    text: Annotated[str, Field(min_length=1, max_length=24)]
    representation_id: StableRuntimeId
    masked: bool = False


class CoordinateOperand(StrictModel):
    label: Text
    values: tuple[int, ...] = Field(min_length=2, max_length=4)


class CoordinateSum(StrictModel):
    """Author-supplied exact toy algebra, not inferred experimental values."""

    step_index: int = Field(ge=0, le=3)
    axis_labels: tuple[Text, ...] = Field(min_length=2, max_length=4)
    operands: tuple[CoordinateOperand, ...] = Field(min_length=2, max_length=4)
    result_label: Text
    result: tuple[int, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def consistent(self):
        width = len(self.axis_labels)
        if len(self.result) != width or any(
            len(o.values) != width for o in self.operands
        ):
            raise ValueError("mechanism_coordinate_sum_dimensions")
        if any(
            sum(o.values[i] for o in self.operands) != v
            for i, v in enumerate(self.result)
        ):
            raise ValueError("mechanism_coordinate_sum_inconsistent")
        return self


class RuleChange(StrictModel):
    before_component: StableRuntimeId
    retained_clause: Text
    added_clause: Text
    conclusion: Text


class MechanismComponent(StrictModel):
    semantic_id: StableRuntimeId
    component_version: Literal["1"] = "1"
    family: Literal[
        "token_representation", "port_operation", "conditional_loop", "candidate_state"
    ]
    label: Text
    status: Literal["observed", "measured", "known", "conceptual", "unknown"]
    source_location: Text
    phase: Literal["training", "inference", "conceptual"]
    parameters: Literal["frozen", "trainable", "not_applicable"]
    ports: tuple[MechanismPort, ...] = Field(min_length=1, max_length=4)
    steps: tuple[Text, ...] = Field(min_length=1, max_length=4)
    tokens: tuple[TokenCorrespondence, ...] = Field(default=(), max_length=4)
    axes: tuple[Text, ...] = Field(default=(), max_length=2)
    condition: Text | None = None
    stop_condition: Text | None = None
    before: Text | None = None
    after: Text | None = None
    coordinate_sum: CoordinateSum | None = None
    rule_change: RuleChange | None = None

    @model_validator(mode="after")
    def concrete(self):
        ids = [p.port_id for p in self.ports]
        if len(ids) != len(set(ids)):
            raise ValueError("mechanism_duplicate_port")
        if len({t.token_id for t in self.tokens}) != len(self.tokens):
            raise ValueError("mechanism_duplicate_token")
        if self.family == "token_representation" and (not self.tokens or not self.axes):
            raise ValueError("mechanism_token_mapping_and_axes_required")
        if self.family == "conditional_loop" and (
            not self.condition or not self.stop_condition
        ):
            raise ValueError("mechanism_condition_and_stop_required")
        if self.family == "candidate_state" and (not self.before or not self.after):
            raise ValueError("mechanism_before_after_required")
        if self.family == "port_operation" and {p.direction for p in self.ports} != {
            "input",
            "output",
        }:
            raise ValueError("mechanism_operation_input_output_required")
        if self.phase == "inference" and self.parameters == "trainable":
            raise ValueError("mechanism_inference_parameter_update_unsupported")
        if self.coordinate_sum:
            table = self.coordinate_sum

            def vector(values):
                return "[" + ",".join(map(str, values)) + "]"

            if (
                self.family != "port_operation"
                or table.step_index >= len(self.steps)
                or f"{table.result_label}={vector(table.result)}"
                not in self.steps[table.step_index]
                or any(
                    f"{o.label}={vector(o.values)}" not in " ".join(self.steps)
                    for o in table.operands
                )
            ):
                raise ValueError("mechanism_coordinate_sum_source_mismatch")
        if self.rule_change and self.family != "candidate_state":
            raise ValueError("mechanism_rule_change_family")
        return self


class MechanismRelation(StrictModel):
    semantic_id: StableRuntimeId
    source_component: StableRuntimeId
    source_port: StableRuntimeId
    target_component: StableRuntimeId
    target_port: StableRuntimeId
    relation_type: Literal[
        "data",
        "condition",
        "control",
        "retrieval",
        "action",
        "observation",
        "supervision",
        "parameter_update",
    ]
    payload: Text
    trigger: Text
    feedback: bool = False


class MechanismFacts(StrictModel):
    schema_version: Literal["arw.mechanism-facts.v1"] = "arw.mechanism-facts.v1"
    question: Text
    claim: Text
    data_nature: Literal["synthetic", "research"]
    components: tuple[MechanismComponent, ...] = Field(min_length=2, max_length=6)
    relations: tuple[MechanismRelation, ...] = Field(min_length=1, max_length=8)
    innovation_id: StableRuntimeId
    object_chain: tuple[StableRuntimeId, ...] = Field(min_length=2, max_length=6)
    candidate_exception: Text

    @model_validator(mode="after")
    def connected(self):
        components = {c.semantic_id: c for c in self.components}
        ids = [c.semantic_id for c in self.components] + [
            r.semantic_id for r in self.relations
        ]
        if len(ids) != len(set(ids)) or self.innovation_id not in components:
            raise ValueError("mechanism_duplicate_identity_or_missing_innovation")
        if not set(self.object_chain) <= set(components) or len(
            set(self.object_chain)
        ) != len(self.object_chain):
            raise ValueError("mechanism_invalid_object_chain")
        connections = set()
        for r in self.relations:
            try:
                a, b = components[r.source_component], components[r.target_component]
                src = next(p for p in a.ports if p.port_id == r.source_port)
                dst = next(p for p in b.ports if p.port_id == r.target_port)
            except (KeyError, StopIteration) as exc:
                raise ValueError("mechanism_missing_endpoint") from exc
            if (
                src.direction != "output"
                or dst.direction != "input"
                or src.value_type != dst.value_type
            ):
                raise ValueError("mechanism_incompatible_ports")
            if (src.object_id, src.state_id) != (dst.object_id, dst.state_id):
                raise ValueError("mechanism_object_identity_break")
            if (
                r.relation_type in {"supervision", "parameter_update"}
                and b.phase != "training"
            ):
                raise ValueError("mechanism_training_boundary_mismatch")
            if r.relation_type == "parameter_update" and b.parameters != "trainable":
                raise ValueError("mechanism_frozen_parameter_update")
            if r.feedback:
                if a.family != "conditional_loop" or not any(
                    e.source_component == a.semantic_id and not e.feedback
                    for e in self.relations
                ):
                    raise ValueError("mechanism_feedback_exit_required")
            connections.add((r.source_component, r.target_component))
        if any(
            pair not in connections
            for pair in zip(self.object_chain, self.object_chain[1:])
        ):
            raise ValueError("mechanism_object_chain_disconnected")
        for c in self.components:
            if c.rule_change:
                d = c.rule_change
                old = components.get(d.before_component)
                if (
                    old is None
                    or f"{d.retained_clause} {d.conclusion}" != old.before
                    or f"{d.retained_clause} {d.added_clause} {d.conclusion}"
                    not in (c.after or "")
                ):
                    raise ValueError("mechanism_rule_change_source_mismatch")
        return self


class MechanismCell(StrictModel):
    semantic_id: StableRuntimeId
    x: Point
    y: Point
    width: float = Field(ge=120, le=500, allow_inf_nan=False)
    height: float = Field(ge=80, le=1000, allow_inf_nan=False)


class MechanismRoute(StrictModel):
    semantic_id: StableRuntimeId
    via: tuple[tuple[Point, Point], ...] = Field(default=(), max_length=4)
    label_x: Point
    label_y: Point


class MechanismFigureIR(StrictModel):
    schema_version: Literal["arw.mechanism-figure-ir.v1"] = "arw.mechanism-figure-ir.v1"
    artifact_kind: Literal["mechanism_figure"] = "mechanism_figure"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    source: ResearchBinding
    source_sha256: Sha256
    width_mm: float = Field(ge=80, le=500, allow_inf_nan=False)
    height_mm: float = Field(ge=80, le=500, allow_inf_nan=False)
    cells: tuple[MechanismCell, ...] = Field(min_length=2, max_length=6)
    routes: tuple[MechanismRoute, ...] = Field(min_length=1, max_length=8)
    min_font_pt: float = Field(default=8.0, ge=7, le=14, allow_inf_nan=False)
    profile: Text
    renderer_hints: RendererIdentity
    publication_critical: bool = False
    validation_policy: ValidationPolicy
    supersedes: StableRuntimeId | None = None

    @property
    def research_bindings(self):
        return (self.source,)

    @model_validator(mode="after")
    def geometry(self):
        width, height = self.width_mm * 72 / 25.4, self.height_mm * 72 / 25.4
        for values in (self.cells, self.routes):
            if len({v.semantic_id for v in values}) != len(values):
                raise ValueError("mechanism_duplicate_layout_id")
        for i, a in enumerate(self.cells):
            if (
                a.x + a.width > width - 8
                or a.y + a.height > height - 8
                or a.x < 8
                or a.y < 60
            ):
                raise ValueError("mechanism_cell_out_of_bounds")
            for b in self.cells[i + 1 :]:
                if (
                    a.x < b.x + b.width
                    and b.x < a.x + a.width
                    and a.y < b.y + b.height
                    and b.y < a.y + a.height
                ):
                    raise ValueError("mechanism_overlapping_cells")
        for route in self.routes:
            if any(
                x > width - 8 or y > height - 8
                for x, y in (*route.via, (route.label_x, route.label_y))
            ):
                raise ValueError("mechanism_route_out_of_bounds")
        if self.validation_policy.semantic != "REQUIRED" or (
            self.publication_critical and self.validation_policy.visual != "REQUIRED"
        ):
            raise ValueError("mechanism_validation_required")
        if self.supersedes == self.artifact_id:
            raise ValueError("mechanism_cannot_supersede_self")
        return self


class MechanismFigureReceipt(StrictModel):
    receipt_version: Literal["arw.mechanism-figure-receipt.v1"] = (
        "arw.mechanism-figure-receipt.v1"
    )
    artifact_kind: Literal["mechanism_figure"] = "mechanism_figure"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    ir_sha256: Sha256
    renderer: RendererIdentity
    inputs: tuple[ResearchBinding, ...]
    outputs: tuple[OutputDigest, ...]
    min_font_pt: float = Field(ge=7, allow_inf_nan=False)
    validation_policy: ValidationPolicy
    validation: ValidationResults
    qualification: Literal["PASS", "FAIL"]
    purpose: Literal["publication-critical", "exploratory"]
    visual_reviewer: VisualReviewer | None
    reason_codes: tuple[str, ...]


class MechanismReviewBinding(StrictModel):
    source_sha256: Sha256
    ir_sha256: Sha256
    svg_sha256: Sha256
    png_sha256: Sha256
    font_sha256: Sha256
    environment_sha256: Sha256


class MechanismFinding(StrictModel):
    finding_id: StableRuntimeId
    category: Literal[
        "scientific_error",
        "necessary_content_omission",
        "readability",
        "reference_gap",
        "optional_style",
    ]
    severity: Literal["critical", "major", "minor", "suggestion"]
    affected_ids: tuple[StableRuntimeId, ...] = Field(min_length=1, max_length=12)
    source_requirement: str = Field(min_length=1, max_length=1000)
    pixel_observation: str = Field(min_length=1, max_length=1000)
    difference: str = Field(min_length=1, max_length=1000)
    recommendation: str = Field(min_length=1, max_length=1000)
    pass_condition: str = Field(min_length=1, max_length=1000)
    uncertainty: str = Field(min_length=1, max_length=500)


class MechanismAdvisoryReview(StrictModel):
    schema_version: Literal["arw.mechanism-advisory-review.v1"] = (
        "arw.mechanism-advisory-review.v1"
    )
    status: Literal["reviewed", "changes_required", "unavailable", "human_pending"]
    binding: MechanismReviewBinding
    producer_id: StableRuntimeId
    reviewer_id: StableRuntimeId
    pixels_read: bool
    findings: tuple[MechanismFinding, ...] = Field(max_length=40)
    reader_retelling: dict[str, str] = Field(min_length=5, max_length=5)
    reference_comparisons: tuple[str, ...] = Field(max_length=3)
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    tool_calls: int | None = Field(default=None, ge=0)
    tokens: int | None = Field(default=None, ge=0)
    cost_note: str = Field(min_length=1, max_length=500)
    human_status: Literal["human_pending"] = "human_pending"
    publication_visual_pass: Literal[False] = False

    @model_validator(mode="after")
    def advisory_only(self):
        if self.producer_id == self.reviewer_id:
            raise ValueError("mechanism_reviewer_must_have_separate_role")
        if self.status in {"reviewed", "changes_required"} and not self.pixels_read:
            raise ValueError("mechanism_actual_pixels_required")
        if self.status == "changes_required" and not self.findings:
            raise ValueError("mechanism_review_findings_required")
        if set(self.reader_retelling) != {
            "input",
            "transformation",
            "innovation",
            "output",
            "feedback",
        }:
            raise ValueError("mechanism_reader_retelling_required")
        return self


def mechanism_figure_schema_documents():
    documents = {}
    for name, model in (
        ("mechanism-facts.schema.json", MechanismFacts),
        ("mechanism-figure-ir.schema.json", MechanismFigureIR),
        ("mechanism-figure-receipt.schema.json", MechanismFigureReceipt),
        ("mechanism-advisory-review.schema.json", MechanismAdvisoryReview),
    ):
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = value
    return documents
