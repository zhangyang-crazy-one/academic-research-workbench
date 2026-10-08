"""Exact plot compilation and distinct integrity, advisory and caption checks."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.accepted_ref import JournalEventRef, ParentArtifactRef
from arw.kernel.state.numeric_core import (
    CsvSelection,
    DerivationRequest,
    NumericExpression,
    NumericPresentation,
    RationalExact,
    RowIds,
)
from arw.kernel.state.result_plot import PlotCheck, PlotValue

from .validation import IRValidationFault


class PlotFault(IRValidationFault):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CompiledDatum:
    datum_id: str
    category: str
    series: str
    order: Fraction | None
    pair_id: str | None
    x: PlotValue | None
    y: PlotValue | None
    lower: PlotValue | None = None
    upper: PlotValue | None = None
    stable_row_id: str | None = None


@dataclass(frozen=True)
class CompiledPlot:
    ir: object
    layers: tuple[tuple[object, tuple[CompiledDatum, ...]], ...]
    plot_values: tuple[PlotValue, ...]
    checks: tuple[PlotCheck, ...]
    metadata: dict[str, RationalExact]


@dataclass(frozen=True)
class VerifiedCaptionAttestation:
    """Produced only by a trusted authority adapter, never parsed from the IR.

    The adapter must prove the journal confirmation and its parent-ledger
    anchor against the N-1 fixed prefix, confirmation time, role/gate/scope,
    IR digest and revision. Declaration fields are not evidence.
    """

    binding_id: str
    revision: int
    ir_sha256: str
    status: str  # verified | unsupported | auth_missing
    evidence_sha256: str | None = None
    target_sha256: str | None = None


class CaptionAttestationVerifier(Protocol):
    def verify(
        self, compiled, binding, *, resolution_context
    ) -> VerifiedCaptionAttestation: ...


def _check(code, category="integrity", status="PASS", **kwargs):
    return PlotCheck(code=code, category=category, status=status, **kwargs)


def _exact(request, context):
    from arw.kernel.policy.numeric_core import evaluate_derivation

    result = evaluate_derivation(request, context)
    if result.status != "exact" or result.exact is None:
        raise PlotFault(
            f"numeric_{result.status}"
            if result.status != "exact"
            else "scalar_derivation_required"
        )
    return result


def compile_plot(ir, resolution_context, *, acceptance_root=None):
    """Read-only compilation. All emitted values are replayed accepted derivations."""
    from arw.kernel.state.result_plot import ResultPlotIR

    raw_ir = canonical_json_bytes(ir.model_dump(mode="json"))
    if len(raw_ir) > 1_048_576:
        raise PlotFault("plot_ir_budget_exceeded")
    ir = ResultPlotIR.model_validate_json(raw_ir)
    from arw.kernel.ledger.accepted_refs import resolve_ref
    from arw.kernel.ledger.source_locations import read_retained_bytes
    from arw.kernel.policy.numeric_core import parse_exact_number, resolve_operand
    from arw.kernel.state.models import RunManifest

    run_ids = {
        RunManifest.model_validate_json(
            read_retained_bytes(root, "run-manifest.json")
        ).run_id
        for root in resolution_context.run_roots
    }
    refs = ir.source_refs
    if not refs:
        raise PlotFault("plot_requires_accepted_sources")
    for ref in refs:
        if isinstance(ref, ParentArtifactRef) and ref.run_id not in run_ids:
            raise PlotFault("plot_cross_run_source_unsupported")
        resolved = resolve_ref(ref, resolution_context)
        allowed_scopes = (
            {"metadata_only"}
            if isinstance(ref, JournalEventRef)
            else {"bytes", "selected_bytes"}
        )
        if resolved.status != "resolved" or resolved.proven_scope not in allowed_scopes:
            raise PlotFault("unresolved_plot_source")
    if ir.acceptance_bindings:
        if acceptance_root is None:
            raise PlotFault("bridge_target_root_required")
        verify_source_bridge(ir, acceptance_root, resolution_context)
    contexts = [l.source.context for l in ir.layers if l.source]
    contexts += [
        r.context
        for l in ir.layers
        for d in l.data
        for r in (d.y, d.lower, d.upper)
        if r
    ]
    if len({canonical_json_bytes(c.model_dump(mode="json")) for c in contexts}) != 1:
        raise PlotFault("plot_comparison_context_mismatch")
    values, layers, checks, metadata = (
        [],
        [],
        [_check("accepted_sources_resolved", status="resolved")],
        {},
    )

    def value(request, layer, datum_id, category, series, channel, row_id=None):
        result = _exact(request, resolution_context)
        digest = sha256_hex(
            canonical_json_bytes(
                {
                    "artifact_id": ir.artifact_id,
                    "layer": layer.layer_id,
                    "datum": datum_id,
                    "channel": channel,
                    "revision": ir.revision,
                }
            )
        )
        operand_units = {a.unit for a in request.expr.args if hasattr(a, "unit")}
        if len(operand_units) != 1:
            raise PlotFault("plot_unit_ambiguous")
        unit = next(iter(operand_units))
        expected_unit = ir.scales.x.unit if channel == "x" else ir.scales.y.unit
        if unit != expected_unit:
            raise PlotFault("plot_scale_unit_mismatch")
        display = NumericPresentation(
            derivation_id=result.derivation_id,
            decimals=layer.display.decimals,
            rounding_mode=layer.display.rounding_mode,
            scale=layer.display.scale,
            unit_suffix=layer.display.unit_suffix,
        )
        p = PlotValue(
            plot_value_id=f"plot.value.{digest[:32]}",
            derivation_id=result.derivation_id,
            exact=result.exact,
            layer=layer.layer_id,
            datum_id=datum_id,
            series=series,
            category=category,
            channel=channel,
            statistic=request.expr.op,
            expr=request.expr,
            unit=unit,
            scale=layer.display.scale,
            display=display,
            revision=ir.revision,
            stable_row_id=row_id,
        )
        values.append(p)
        return p

    for layer in ir.layers:
        data = []
        if layer.source:
            source = layer.source
            x_source = layer.x_source or source
            if layer.x_source:
                if (
                    x_source.row_id_column,
                    x_source.row_set,
                    x_source.group_by,
                    x_source.missing_policy,
                ) != (
                    source.row_id_column,
                    source.row_set,
                    source.group_by,
                    source.missing_policy,
                ):
                    raise PlotFault("observation_x_selection_contract_mismatch")
                if (
                    x_source.context.dataset,
                    x_source.context.split,
                    x_source.context.evaluation_condition,
                ) != (
                    source.context.dataset,
                    source.context.split,
                    source.context.evaluation_condition,
                ):
                    raise PlotFault("observation_x_context_mismatch")
                if x_source.columns != (layer.encoding.x,):
                    raise PlotFault("observation_x_requires_single_encoded_column")
            result = resolve_operand(source, resolution_context)
            if result.status != "exact":
                raise PlotFault(f"observation_{result.status}")
            if len(result.rows) > 1000:
                raise PlotFault("observation_row_budget_exceeded")
            if layer.paired and result.excluded_row_ids:
                raise PlotFault("paired_missing_numeric_value")
            x_rows = None
            if layer.x_source:
                x_result = resolve_operand(x_source, resolution_context)
                if x_result.status != "exact":
                    raise PlotFault("observation_x_invalid_source")
                x_rows = {row.row_id: row for row in x_result.rows}
                if set(x_rows) != {row.row_id for row in result.rows} or len(
                    x_rows
                ) != len(x_result.rows):
                    raise PlotFault("observation_x_row_identity_mismatch")
                if any(
                    x_rows[row.row_id].group_key != row.group_key for row in result.rows
                ):
                    raise PlotFault("observation_x_group_mismatch")
            for row in result.rows:
                fields = row.fields
                try:
                    category = (
                        fields[layer.encoding.x] if ir.scales.x.type == "band" else ""
                    )
                    series = (
                        fields[layer.encoding.series] if layer.encoding.series else ""
                    )
                    order = (
                        parse_exact_number(fields[layer.encoding.order]).as_fraction()
                        if layer.encoding.order
                        else None
                    )
                    pair = (
                        fields[layer.encoding.pair_id]
                        if layer.encoding.pair_id
                        else None
                    )
                except (
                    KeyError,
                    ValueError,
                    ZeroDivisionError,
                    OverflowError,
                ) as error:
                    raise PlotFault("missing_or_invalid_encoding") from error
                if order is not None and (
                    abs(order.numerator) > 10**128 - 1
                    or order.denominator > 10**128 - 1
                ):
                    raise PlotFault("order_out_of_domain")
                if layer.encoding.series and not series:
                    raise PlotFault("missing_series")
                if layer.paired and not pair:
                    raise PlotFault("missing_pair_id")

                def row_request(column, source=source, row_id=row.row_id):
                    if column not in source.columns:
                        raise PlotFault("numeric_encoding_column_not_selected")
                    selected = source.model_copy(
                        update={
                            "columns": (column,),
                            "row_set": RowIds(ids=(row_id,)),
                            "group_by": (),
                        }
                    )
                    return DerivationRequest(
                        expr=NumericExpression(op="value", args=(selected,)),
                        context=source.context,
                    )

                y = value(
                    row_request(layer.encoding.y),
                    layer,
                    row.row_id,
                    category,
                    series,
                    "y",
                    row.row_id,
                )
                x = (
                    None
                    if ir.scales.x.type == "band"
                    else value(
                        row_request(layer.encoding.x, source=x_source),
                        layer,
                        row.row_id,
                        category,
                        series,
                        "x",
                        row.row_id,
                    )
                )
                data.append(
                    CompiledDatum(
                        row.row_id,
                        category,
                        series,
                        order,
                        pair,
                        x,
                        y,
                        stable_row_id=row.row_id,
                    )
                )
        else:
            for datum in layer.data:
                if layer.mark == "line" and (not datum.series or datum.order is None):
                    raise PlotFault("missing_series_or_order")
                if layer.paired and not datum.pair_id:
                    raise PlotFault("missing_pair_id")
                if ir.scales.x.type != "band" and datum.x is None:
                    raise PlotFault("numeric_x_derivation_required")
                x = (
                    value(
                        datum.x,
                        layer,
                        datum.datum_id,
                        datum.category,
                        datum.series,
                        "x",
                    )
                    if datum.x
                    else None
                )
                y = (
                    value(
                        datum.y,
                        layer,
                        datum.datum_id,
                        datum.category,
                        datum.series,
                        "y",
                    )
                    if datum.y
                    else None
                )
                lower = (
                    value(
                        datum.lower,
                        layer,
                        datum.datum_id,
                        datum.category,
                        datum.series,
                        "lower",
                    )
                    if datum.lower
                    else None
                )
                upper = (
                    value(
                        datum.upper,
                        layer,
                        datum.datum_id,
                        datum.category,
                        datum.series,
                        "upper",
                    )
                    if datum.upper
                    else None
                )
                if lower and lower.exact.as_fraction() > upper.exact.as_fraction():
                    raise PlotFault("invalid_interval")
                # Category/series metadata must agree with selected CSV fields
                # when those fields are declared by the aggregate encoding.
                for request in (datum.y, datum.lower, datum.upper):
                    if request:
                        for operand in request.expr.args:
                            if isinstance(operand, CsvSelection):
                                rows = resolve_operand(operand, resolution_context).rows
                                for field, expected in (
                                    (layer.encoding.series, datum.series),
                                    (
                                        layer.encoding.x
                                        if ir.scales.x.type == "band"
                                        else None,
                                        datum.category,
                                    ),
                                ):
                                    if field and any(
                                        row.fields.get(field) != expected
                                        for row in rows
                                    ):
                                        raise PlotFault(
                                            "derived_group_encoding_mismatch"
                                        )
                data.append(
                    CompiledDatum(
                        datum.datum_id,
                        datum.category,
                        datum.series,
                        datum.order.as_fraction() if datum.order else None,
                        datum.pair_id,
                        x,
                        y,
                        lower,
                        upper,
                    )
                )
        if not data:
            raise PlotFault("empty_plot_layer")
        if len(values) > 5000:
            raise PlotFault("plot_value_budget_exceeded")
        if ir.scales.x.type == "band" and any(not d.category for d in data):
            raise PlotFault("band_category_required")
        if layer.mark == "line":
            keys = [
                (d.series, d.pair_id if layer.paired else None, d.order) for d in data
            ]
            if len(keys) != len(set(keys)):
                raise PlotFault("duplicate_series_order")
        if layer.paired:
            # Each pair must occur once at every category/order position.
            keys = [
                (
                    d.pair_id,
                    d.category
                    if ir.scales.x.type == "band"
                    else d.x.exact.as_fraction(),
                )
                for d in data
            ]
            if len(keys) != len(set(keys)):
                raise PlotFault("duplicate_pair_id")
            expected = (
                set(ir.scales.x.categories)
                if ir.scales.x.type == "band" and ir.scales.x.categories
                else {k[1] for k in keys}
            )
            if len(expected) < 2:
                raise PlotFault("missing_pair_member")
            pairs = {d.pair_id for d in data}
            if layer.mark == "line" and any(
                len({d.series for d in data if d.pair_id == pair}) != 1
                for pair in pairs
            ):
                raise PlotFault("paired_line_series_mismatch")
            if any({k[1] for k in keys if k[0] == pair} != expected for pair in pairs):
                raise PlotFault("missing_pair_member")
        if layer.uncertainty:
            u = layer.uncertainty
            for datum in layer.data:
                for req in (datum.lower, datum.upper):
                    if any(
                        isinstance(a, CsvSelection)
                        and a.missing_policy != u.missing_policy
                        for a in req.expr.args
                    ):
                        raise PlotFault("interval_missing_policy_mismatch")
            if u.mode != "precomputed_interval":
                raise PlotFault("unsupported_sd_se_recomputation")
            n = _exact(u.n_source, resolution_context).exact
            if n.denominator != 1 or n.numerator < 1:
                raise PlotFault("invalid_effective_n")
            if u.interval_type == "sd" and n.numerator <= u.ddof:
                checks.append(
                    _check(
                        "precomputed_sd_n_not_greater_than_ddof",
                        "statistics",
                        "advisory",
                    )
                )
            metadata[f"{layer.layer_id}.n"] = n
            if u.confidence_level:
                metadata[f"{layer.layer_id}.confidence_level"] = u.confidence_level
            checks.append(
                _check("precomputed_interval_source_resolved", "integrity", "resolved")
            )
            checks.append(
                _check(
                    "precomputed_statistics_not_recomputed", "statistics", "unsupported"
                )
            )
        layers.append((layer, tuple(sorted(data, key=lambda d: d.datum_id))))
    if ir.figure_number is not None:
        metadata["figure_number"] = RationalExact(
            numerator=ir.figure_number, denominator=1
        )
    if ir.heuristics.effective_n:
        n = _exact(ir.heuristics.effective_n, resolution_context).exact
        if n.denominator != 1 or n.numerator < 1:
            raise PlotFault("invalid_effective_n")
        metadata["effective_n"] = n
        h = ir.heuristics
        if (
            h.outcome_kind == "continuous"
            and h.independent_units
            and h.raw_data == "available"
            and n.numerator <= h.small_sample_threshold
            and not any(l.role == "observation" for l in ir.layers)
        ):
            checks.append(
                _check(
                    "small_sample_summary_only",
                    "heuristic",
                    "advisory",
                    detail=h.profile,
                )
            )
    if ir.heuristics.raw_data == "raw_unavailable":
        checks.append(_check("raw_unavailable", "heuristic", "advisory"))
    return CompiledPlot(ir, tuple(layers), tuple(values), tuple(checks), metadata)


def build_source_bridge(ir, resolution_context):
    """Read-only proposal, requiring explicit ordinary parent acceptance later."""
    from arw.kernel.state.result_plot import PlotSourceBridge

    compile_plot(ir.model_copy(update={"acceptance_bindings": ()}), resolution_context)
    refs = ir.source_refs
    capsule = PlotSourceBridge(
        artifact_id=ir.artifact_id,
        revision=ir.revision,
        source_refs=refs,
        source_refs_sha256=sha256_hex(
            canonical_json_bytes([r.model_dump(mode="json") for r in refs])
        ),
    )
    if len(canonical_json_bytes(capsule.model_dump(mode="json"))) > 1_048_576:
        raise PlotFault("plot_bridge_budget_exceeded")
    return capsule


def verify_source_bridge(ir, run_root, resolution_context):
    from pathlib import Path

    from arw.kernel.ledger.journal import (
        replay_run,
        replay_run_prefix,
        replay_run_under_held_lock,
    )
    from arw.kernel.ledger.manifests import load_artifact_manifest
    from arw.kernel.ledger.source_locations import read_retained_bytes
    from arw.kernel.state.models import RunManifest
    from arw.kernel.state.result_plot import PlotSourceBridge

    from .validation import accepted_content

    if len(ir.acceptance_bindings) != 1:
        raise PlotFault("plot_source_bridge_required")
    binding = ir.acceptance_bindings[0]
    if binding.json_pointer:
        raise PlotFault("bridge_requires_whole_capsule")
    held = Path(run_root).absolute() in {
        Path(p).absolute() for p in resolution_context.held_lock_roots
    }
    manifest_run = RunManifest.model_validate_json(
        read_retained_bytes(run_root, "run-manifest.json")
    )
    prefix = next(
        (p for p in resolution_context.run_prefixes if p.run_id == manifest_run.run_id),
        None,
    )
    if resolution_context.run_prefixes and prefix is None:
        raise PlotFault("bridge_target_missing_snapshot_prefix")
    arguments = (
        {}
        if prefix is None
        else {
            "revision": prefix.revision,
            "expected_head_sha256": prefix.head_sha256,
            "expected_manifest_sha256": prefix.run_manifest_sha256,
        }
    )
    replayed = (
        replay_run_under_held_lock(run_root, **arguments)
        if held
        else (
            replay_run_prefix(run_root, **arguments) if prefix else replay_run(run_root)
        )
    )
    try:
        _, event, raw = accepted_content(
            run_root,
            replayed.events,
            binding.artifact_id,
            binding.ledger_event_id,
            binding.sha256,
        )
        manifest = load_artifact_manifest(run_root, event.payload.manifest_sha256)
        if (
            event.event_type != "artifact.accepted"
            or event.event_sha256 != binding.ledger_event_sha256
            or manifest.artifact_kind != "plot-source-bridge"
            or manifest.media_type != "application/json"
        ):
            raise ValueError("bridge_acceptance_identity_mismatch")
        capsule = PlotSourceBridge.model_validate_json(raw)
        if (
            capsule.artifact_id != ir.artifact_id
            or capsule.revision != ir.revision
            or capsule.source_refs != ir.source_refs
        ):
            raise ValueError("bridge_source_refs_mismatch")
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        raise PlotFault("invalid_plot_source_bridge") from error
    return capsule


def caption_target(compiled, binding):
    """Frozen semantic target without attestation/bridge self references."""
    ir = compiled.ir
    raw = ir.caption.encode("utf-8")
    value = next(
        (v for v in compiled.plot_values if v.plot_value_id == binding.plot_value_id),
        None,
    )
    metadata = (
        compiled.metadata.get(binding.metadata_key) if binding.metadata_key else None
    )
    return {
        "schema_version": "arw.caption-numeric-target.v1",
        "artifact_id": ir.artifact_id,
        "revision": ir.revision,
        "caption": ir.caption,
        "caption_sha256": sha256_hex(raw),
        "numeric_text": raw[binding.start_byte : binding.end_byte].decode(
            "utf-8", errors="strict"
        ),
        "binding": binding.model_dump(
            mode="json", exclude={"confirmation", "confirmation_ref"}
        ),
        "plot_value": None if value is None else value.model_dump(mode="json"),
        "metadata_value": None
        if metadata is None
        else metadata.model_dump(mode="json"),
        "source_refs": [r.model_dump(mode="json") for r in ir.data_source_refs],
    }


def caption_checks(
    compiled,
    *,
    resolution_context=None,
    hard_caption_checks=False,
    attestation_verifier=None,
):
    from arw.kernel.policy.numeric_core import format_exact, parse_exact_number

    ir = compiled.ir
    values = {v.plot_value_id: v for v in compiled.plot_values}
    checks = []
    raw = ir.caption.encode("utf-8")
    numeric_occurrences = tuple(
        re.finditer(rb"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", raw)
    )
    complete_spans = {match.span() for match in numeric_occurrences}
    covered = set()
    for b in ir.caption_bindings:
        status = "advisory"
        if hard_caption_checks:
            attestation = (
                None
                if attestation_verifier is None
                else attestation_verifier.verify(
                    compiled, b, resolution_context=resolution_context
                )
            )
            if (
                attestation is None
                or attestation.status != "verified"
                or attestation.binding_id != b.binding_id
                or attestation.revision != ir.revision
                or attestation.ir_sha256
                != sha256_hex(canonical_json_bytes(ir.model_dump(mode="json")))
                or not attestation.evidence_sha256
                or attestation.target_sha256
                != sha256_hex(canonical_json_bytes(caption_target(compiled, b)))
            ):
                checks.append(
                    _check(
                        "caption_auth_missing",
                        "caption",
                        "unsupported",
                        binding_id=b.binding_id,
                    )
                )
                continue
            status = "FAIL"
        code = None
        try:
            token = raw[b.start_byte : b.end_byte].decode("utf-8")
            if (
                (b.start_byte, b.end_byte) not in complete_spans
                or b.end_byte > len(raw)
                or not re.fullmatch(
                    r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", token
                )
            ):
                raise ValueError("not a numeric occurrence")
            if b.revision != ir.revision:
                code = "caption_revision_mismatch"
            elif b.number_kind == "result":
                v = values.get(b.plot_value_id)
                if v is None or (
                    b.series,
                    b.category,
                    b.statistic,
                    b.expr,
                    b.unit,
                    b.scale,
                    b.revision,
                ) != (
                    v.series,
                    v.category,
                    v.statistic,
                    v.expr,
                    v.unit,
                    v.scale,
                    v.revision,
                ):
                    code = "caption_context_mismatch"
                elif token != format_exact(
                    v.exact, v.display.model_copy(update={"unit_suffix": ""})
                ):
                    code = "caption_value_mismatch"
            elif b.number_kind != "non_result":
                exact = compiled.metadata.get(b.metadata_key)
                # Metadata kinds cannot alias each other's slots.
                correct_slot = (
                    (
                        b.number_kind == "sample_size"
                        and (
                            b.metadata_key == "effective_n"
                            or b.metadata_key.endswith(".n")
                        )
                    )
                    or (
                        b.number_kind == "confidence_level"
                        and b.metadata_key.endswith(".confidence_level")
                    )
                    or (
                        b.number_kind == "figure_number"
                        and b.metadata_key == "figure_number"
                    )
                )
                if (
                    exact is None
                    or not correct_slot
                    or parse_exact_number(token).as_fraction()
                    != exact.as_fraction() * (b.scale.as_fraction() if b.scale else 1)
                ):
                    code = "caption_metadata_mismatch"
            covered.add((b.start_byte, b.end_byte))
        except (ValueError, UnicodeDecodeError):
            code = "invalid_caption_occurrence"
        checks.append(
            _check(
                code or "caption_binding_matches",
                "caption",
                status if code else ("PASS" if hard_caption_checks else "advisory"),
                binding_id=b.binding_id,
            )
        )
    for match in numeric_occurrences:
        if match.span() not in covered:
            checks.append(
                _check(
                    "unbound_caption_numeric_occurrence",
                    "caption",
                    "unknown",
                    detail=f"{match.start()}:{match.end()}",
                )
            )
    for layer in ir.layers:
        if layer.uncertainty and (
            layer.uncertainty.interval_type not in ir.caption.lower()
            or not any(
                b.number_kind == "sample_size"
                and b.metadata_key == f"{layer.layer_id}.n"
                for b in ir.caption_bindings
            )
        ):
            checks.append(
                _check("interval_caption_disclosure_missing", "heuristic", "advisory")
            )
    return tuple(checks)


def validate_svg_safety(output):
    """Closed result SVG grammar: inert text and geometry only."""
    if len(output) > 2_097_152 or b"<!" in output or b"<?" in output:
        raise PlotFault("unsafe_svg_declaration")
    try:
        root = ET.fromstring(output)
    except ET.ParseError as error:
        raise PlotFault("invalid_svg_xml") from error
    namespace = "{http://www.w3.org/2000/svg}"
    allowed = {
        "svg",
        "title",
        "desc",
        "g",
        "text",
        "tspan",
        "line",
        "rect",
        "circle",
        "path",
    }
    if root.tag != namespace + "svg":
        raise PlotFault("invalid_svg_root")
    ids = []
    for element in root.iter():
        if (
            not element.tag.startswith(namespace)
            or element.tag[len(namespace) :] not in allowed
        ):
            raise PlotFault("unsafe_svg_element")
        for key, value in element.attrib.items():
            local = key.rsplit("}", 1)[-1].lower()
            if (
                local.startswith("on")
                or local in {"href", "style", "src"}
                or re.search(r"url\s*\(|@import", value, re.IGNORECASE)
            ):
                raise PlotFault("unsafe_svg_attribute")
        if "id" in element.attrib:
            ids.append(element.attrib["id"])
    if len(ids) != len(set(ids)):
        raise PlotFault("duplicate_svg_id")
    return True
