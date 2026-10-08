"""Additive result-plot contracts; exact arithmetic belongs to numeric_core."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from arw.kernel.state.accepted_ref import AcceptedRef, ParentArtifactRef
from arw.kernel.state.models import Sha256, StableRuntimeId, StrictModel
from arw.kernel.state.numeric_core import (
    ONE,
    CsvSelection,
    DerivationRequest,
    NumericExpression,
    NumericPresentation,
    RationalExact,
)
from arw.kernel.state.research_artifact import (
    OutputDigest,
    RendererIdentity,
    ResearchBinding,
    ValidationPolicy,
    ValidationResults,
    VisualReviewer,
)


class PlotDisplay(StrictModel):
    scale: RationalExact = ONE
    unit_suffix: str = Field(default="", max_length=64)
    decimals: int = Field(default=3, ge=0, le=18)
    rounding_mode: Literal["ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_DOWN"] = (
        "ROUND_HALF_EVEN"
    )


class PlotScale(StrictModel):
    type: Literal["linear", "log", "band"]
    unit: str = Field(min_length=1, max_length=128)
    domain: tuple[RationalExact, RationalExact] | None = None
    categories: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def valid_domain(self):
        if self.type == "band":
            if self.domain is not None or len(set(self.categories)) != len(
                self.categories
            ):
                raise ValueError("invalid_band_domain")
        elif self.categories:
            raise ValueError("numeric_scale_has_categories")
        if self.domain:
            lo, hi = (v.as_fraction() for v in self.domain)
            if lo >= hi or (self.type == "log" and lo <= 0):
                raise ValueError("invalid_scale_domain")
        return self


class PlotScales(StrictModel):
    x: PlotScale
    y: PlotScale

    @model_validator(mode="after")
    def numeric_y(self):
        if self.y.type == "band":
            raise ValueError("band_y_unsupported")
        return self


class PlotEncoding(StrictModel):
    x: str = Field(min_length=1, max_length=128)
    y: str = Field(min_length=1, max_length=128)
    series: str | None = Field(default=None, max_length=128)
    order: str | None = Field(default=None, max_length=128)
    pair_id: str | None = Field(default=None, max_length=128)


class PlotDatum(StrictModel):
    datum_id: StableRuntimeId
    category: str = Field(default="", max_length=128)
    series: str = Field(default="", max_length=128)
    order: RationalExact | None = None
    pair_id: str | None = Field(default=None, min_length=1, max_length=128)
    x: DerivationRequest | None = None
    y: DerivationRequest | None = None
    lower: DerivationRequest | None = None
    upper: DerivationRequest | None = None


class PlotUncertainty(StrictModel):
    mode: Literal["precomputed_interval", "recompute_sd", "recompute_se"] = (
        "precomputed_interval"
    )
    interval_type: Literal["sd", "se", "ci", "range", "other"]
    sampling_unit: str = Field(min_length=1, max_length=128)
    n_source: DerivationRequest
    missing_policy: Literal["reject", "exclude"]
    method: str = Field(min_length=1, max_length=512)
    assumptions: tuple[str, ...] = Field(min_length=1, max_length=20)
    calculation_source: AcceptedRef
    confidence_level: RationalExact | None = None
    ddof: int | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def disclosure(self):
        if self.interval_type == "ci":
            if (
                self.confidence_level is None
                or not 0 < self.confidence_level.as_fraction() < 1
            ):
                raise ValueError("ci_requires_confidence_level")
        elif self.confidence_level is not None:
            raise ValueError("confidence_level_only_for_ci")
        if self.interval_type == "sd" and self.ddof is None:
            raise ValueError("sd_requires_ddof")
        return self


class PlotLayer(StrictModel):
    layer_id: StableRuntimeId
    role: Literal["observation", "aggregate", "interval"]
    mark: Literal["point", "line", "bar", "strip", "rule"]
    source: CsvSelection | None = None
    x_source: CsvSelection | None = None
    data: tuple[PlotDatum, ...] = Field(default=(), max_length=1000)
    encoding: PlotEncoding
    uncertainty: PlotUncertainty | None = None
    paired: bool = False
    jitter_axis: Literal["x"] | None = None
    display: PlotDisplay = PlotDisplay()

    @model_validator(mode="after")
    def grammar(self):
        if self.role != "observation" and self.x_source is not None:
            raise ValueError("x_source_requires_observation_role")
        if self.role == "observation":
            if self.source is None or self.data or self.uncertainty:
                raise ValueError("observations_require_csv_source")
            if self.mark not in {"point", "line", "strip"}:
                raise ValueError("invalid_observation_mark")
        elif self.role == "aggregate" and self.mark not in {"point", "line", "bar"}:
            raise ValueError("invalid_aggregate_mark")
        elif self.source is not None or not self.data:
            raise ValueError("derived_layer_requires_data")
        if self.role == "interval":
            if (
                self.mark != "rule"
                or self.uncertainty is None
                or any(
                    d.lower is None or d.upper is None or d.y is not None
                    for d in self.data
                )
            ):
                raise ValueError("interval_requires_precomputed_endpoints")
        elif self.uncertainty is not None or any(d.lower or d.upper for d in self.data):
            raise ValueError("interval_metadata_requires_interval_role")
        elif self.data and any(d.y is None for d in self.data):
            raise ValueError("derived_layer_requires_y")
        if self.mark == "line" and (
            not self.encoding.series or not self.encoding.order
        ):
            raise ValueError("line_requires_series_and_order")
        if self.paired and not self.encoding.pair_id:
            raise ValueError("paired_requires_pair_id")
        if (self.mark == "strip") != (self.jitter_axis is not None):
            raise ValueError("strip_requires_display_jitter_axis")
        if len({d.datum_id for d in self.data}) != len(self.data):
            raise ValueError("duplicate_datum_id")
        return self


class PlotPresentation(StrictModel):
    palette: Literal["okabe_ito", "monochrome"] = "okabe_ito"
    font_family: Literal["Noto Sans CJK SC, sans-serif"] = (
        "Noto Sans CJK SC, sans-serif"
    )
    width: int = Field(default=800, ge=480, le=1600)
    height: int = Field(default=560, ge=360, le=1200)


class PlotHeuristics(StrictModel):
    profile: Literal["arw.plot-heuristics.v1"] = "arw.plot-heuristics.v1"
    small_sample_threshold: int = Field(default=20, ge=1, le=10000)
    outcome_kind: Literal["continuous", "category_count"] = "continuous"
    independent_units: bool = True
    raw_data: Literal["available", "raw_unavailable"] = "available"
    effective_n: DerivationRequest | None = None
    exceptions: tuple[str, ...] = Field(default=(), max_length=20)


class CaptionBinding(StrictModel):
    binding_id: StableRuntimeId
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=1)
    number_kind: Literal[
        "result", "sample_size", "confidence_level", "figure_number", "non_result"
    ]
    confirmation: Literal["unknown", "declared", "authenticated"] = "unknown"
    plot_value_id: StableRuntimeId | None = None
    series: str | None = None
    category: str | None = None
    statistic: str | None = None
    expr: NumericExpression | None = None
    unit: str | None = None
    scale: RationalExact | None = None
    revision: int = Field(ge=1)
    metadata_key: str | None = None
    confirmation_ref: AcceptedRef | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.end_byte <= self.start_byte:
            raise ValueError("invalid_caption_span")
        if self.number_kind == "result" and any(
            v is None
            for v in (
                self.plot_value_id,
                self.series,
                self.category,
                self.statistic,
                self.expr,
                self.unit,
                self.scale,
            )
        ):
            raise ValueError("result_binding_requires_full_context")
        if (
            self.number_kind in {"sample_size", "confidence_level", "figure_number"}
            and not self.metadata_key
        ):
            raise ValueError("metadata_binding_requires_key")
        return self


def request_refs(request):
    return tuple(a.ref for a in request.expr.args if hasattr(a, "ref"))


class ResultPlotIR(StrictModel):
    schema_version: Literal["arw.result-plot-ir.v1"] = "arw.result-plot-ir.v1"
    artifact_kind: Literal["result_plot"] = "result_plot"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=180)
    author_target: str = Field(min_length=1, max_length=2000)
    publication_critical: bool = False
    panel: Literal["single"] = "single"
    scales: PlotScales
    layers: tuple[PlotLayer, ...] = Field(min_length=1, max_length=20)
    caption: str = Field(default="", max_length=2400)
    manuscript_reference: str = Field(default="", max_length=1200)
    acceptance_bindings: tuple[ResearchBinding, ...] = Field(default=(), max_length=1)
    caption_bindings: tuple[CaptionBinding, ...] = Field(default=(), max_length=100)
    figure_number: int | None = Field(default=None, ge=1, le=10000)
    heuristics: PlotHeuristics = PlotHeuristics()
    presentation: PlotPresentation = PlotPresentation()
    renderer_hints: RendererIdentity
    validation_policy: ValidationPolicy
    supersedes: StableRuntimeId | None = None

    @model_validator(mode="after")
    def contract(self):
        if len({l.layer_id for l in self.layers}) != len(self.layers):
            raise ValueError("duplicate_layer_id")
        if self.supersedes and self.revision < 2:
            raise ValueError("supersession_requires_new_revision")
        if self.supersedes == self.artifact_id:
            raise ValueError("artifact_cannot_supersede_self")
        if self.heuristics.raw_data == "raw_unavailable" and any(
            l.role == "observation" for l in self.layers
        ):
            raise ValueError("raw_unavailable_cannot_have_observations")
        if self.scales.x.type == "band" and any(
            l.x_source is not None for l in self.layers
        ):
            raise ValueError("band_x_cannot_have_x_source")
        if self.scales.x.type == "band" and any(
            d.x is not None for l in self.layers for d in l.data
        ):
            raise ValueError("band_x_cannot_have_numeric_derivation")
        if any(l.mark == "strip" for l in self.layers) and self.scales.x.type != "band":
            raise ValueError("jitter_requires_band_display_axis")
        if any(l.mark == "bar" for l in self.layers) and self.scales.y.type == "log":
            raise ValueError("log_bar_baseline_unsupported")
        if self.publication_critical and (
            not self.caption
            or not self.manuscript_reference
            or self.validation_policy.visual != "REQUIRED"
        ):
            raise ValueError("publication_requires_caption_reference_visual")
        spans = sorted((b.start_byte, b.end_byte) for b in self.caption_bindings)
        if len({b.binding_id for b in self.caption_bindings}) != len(
            self.caption_bindings
        ) or any(a[1] > b[0] for a, b in pairwise(spans)):
            raise ValueError("duplicate_or_overlapping_caption_binding")
        return self

    @property
    def data_source_refs(self):
        from arw.kernel.core.canonical import canonical_json_bytes

        refs = []
        for layer in self.layers:
            if layer.source:
                refs.append(layer.source.ref)
            if layer.x_source:
                refs.append(layer.x_source.ref)
            for datum in layer.data:
                for request in (datum.x, datum.y, datum.lower, datum.upper):
                    if request:
                        refs.extend(request_refs(request))
            if layer.uncertainty:
                refs.append(layer.uncertainty.calculation_source)
                refs.extend(request_refs(layer.uncertainty.n_source))
        if self.heuristics.effective_n:
            refs.extend(request_refs(self.heuristics.effective_n))
        unique = {canonical_json_bytes(r.model_dump(mode="json")): r for r in refs}
        return tuple(unique[k] for k in sorted(unique))

    @property
    def source_refs(self):
        from arw.kernel.core.canonical import canonical_json_bytes

        refs = self.data_source_refs + tuple(
            b.confirmation_ref for b in self.caption_bindings if b.confirmation_ref
        )
        unique = {canonical_json_bytes(r.model_dump(mode="json")): r for r in refs}
        return tuple(unique[k] for k in sorted(unique))

    @property
    def research_bindings(self):
        # The canonical refs remain in the receipt. This compatibility view is
        # used only by the existing parent-ledger lifecycle stage envelope.
        if self.acceptance_bindings:
            return self.acceptance_bindings
        return tuple(
            ResearchBinding(
                binding_id=f"plot.source.{i}",
                artifact_id=r.artifact_id,
                sha256=r.content_sha256,
                ledger_event_id=r.accepting_event_id,
                ledger_event_sha256=r.accepting_event_sha256,
                json_pointer=r.selector,
            )
            for i, r in enumerate(self.source_refs)
            if isinstance(r, ParentArtifactRef)
        )


class PlotSourceBridge(StrictModel):
    schema_version: Literal["arw.plot-source-bridge.v1"] = "arw.plot-source-bridge.v1"
    artifact_id: StableRuntimeId
    revision: int = Field(ge=1)
    source_refs: tuple[AcceptedRef, ...] = Field(min_length=1, max_length=5000)
    source_refs_sha256: Sha256

    @model_validator(mode="after")
    def canonical_refs(self):
        from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

        keys = tuple(
            canonical_json_bytes(r.model_dump(mode="json")) for r in self.source_refs
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("bridge_refs_must_be_unique_canonical_sorted")
        if self.source_refs_sha256 != sha256_hex(
            canonical_json_bytes([r.model_dump(mode="json") for r in self.source_refs])
        ):
            raise ValueError("bridge_source_refs_digest_mismatch")
        return self


class PlotValue(StrictModel):
    plot_value_id: StableRuntimeId
    derivation_id: Sha256
    exact: RationalExact
    layer: StableRuntimeId
    datum_id: str
    series: str
    category: str
    channel: Literal["x", "y", "lower", "upper"]
    statistic: str
    expr: NumericExpression
    unit: str
    scale: RationalExact = ONE
    display: NumericPresentation
    revision: int = Field(ge=1)
    stable_row_id: str | None = None


class PlotCheck(StrictModel):
    code: str
    category: Literal["integrity", "caption", "heuristic", "statistics"]
    status: Literal["PASS", "FAIL", "advisory", "unknown", "unsupported", "resolved"]
    binding_id: str | None = None
    detail: str = ""


class FigureRenderedFrom(StrictModel):
    source_refs: tuple[AcceptedRef, ...]
    ir_sha256: Sha256
    renderer: RendererIdentity


class ResultPlotReceipt(StrictModel):
    receipt_version: Literal["arw.result-plot-receipt.v1"] = (
        "arw.result-plot-receipt.v1"
    )
    artifact_id: StableRuntimeId
    artifact_kind: Literal["result_plot"] = "result_plot"
    revision: int = Field(ge=1)
    ir_sha256: Sha256
    renderer: RendererIdentity
    inputs: tuple[AcceptedRef, ...]
    rendered_from: FigureRenderedFrom
    outputs: tuple[OutputDigest, ...]
    plot_values: tuple[PlotValue, ...]
    checks: tuple[PlotCheck, ...]
    metadata: dict[str, RationalExact]
    validation_policy: ValidationPolicy
    validation: ValidationResults
    qualification: Literal["PASS", "FAIL"]
    purpose: Literal["publication-critical", "exploratory"]
    visual_reviewer: VisualReviewer | None
    reason_codes: tuple[str, ...]
    source_determinism: Literal["byte_deterministic"] = "byte_deterministic"
    fixed_environment_render: Literal["not_verified"] = "not_verified"
    publication_quality: Literal["reviewed", "not_verified"] = "not_verified"


def result_plot_schema_documents():
    documents = {}
    for name, model in [
        ("result-plot-ir.schema.json", ResultPlotIR),
        ("result-plot-receipt.schema.json", ResultPlotReceipt),
        ("plot-source-bridge.schema.json", PlotSourceBridge),
    ]:
        value = model.model_json_schema()
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        value["$id"] = f"https://academic-research-workbench.local/schemas/v1/{name}"
        documents[name] = value
    return documents
