"""Issue #94/#95 joint fixtures using real accepted parent evidence."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from fractions import Fraction

import jsonschema
import pytest
from arw_research_artifact.plot_policy import (
    PlotFault,
    caption_checks,
    compile_plot,
    validate_svg_safety,
)
from arw_research_artifact.plot_renderer import PlotRenderer
from arw_research_artifact.service import ResearchArtifactService, verify_plot_receipt
from pydantic import ValidationError

from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.numeric_core import RowIds
from arw.kernel.state.research_artifact import ValidationPolicy
from arw.kernel.state.result_plot import (
    CaptionBinding,
    PlotDatum,
    PlotDisplay,
    PlotEncoding,
    PlotHeuristics,
    PlotLayer,
    PlotPresentation,
    PlotScale,
    PlotScales,
    PlotUncertainty,
    ResultPlotIR,
    result_plot_schema_documents,
)
from tests.unit.test_accepted_refs import accepted_fixture
from tests.unit.test_numeric_core import CTX, request, scalar, selection

from .test_research_artifacts import request as parent_request


def policy(visual="OPTIONAL"):
    return ValidationPolicy.model_validate_json(
        json.dumps(
            {
                "schema": "REQUIRED",
                "provenance": "REQUIRED",
                "semantic": "REQUIRED",
                "render": "REQUIRED",
                "visual": visual,
            }
        )
    )


def plot(layers, **kwargs):
    return ResultPlotIR(
        artifact_id="figure.result",
        revision=1,
        title="Accuracy result",
        author_target="Compare accepted experiment results",
        scales=PlotScales(
            x=PlotScale(type="band", unit="category", categories=("A", "B")),
            y=PlotScale(type="linear", unit="ratio"),
        ),
        layers=tuple(layers),
        renderer_hints=PlotRenderer().identity,
        validation_policy=policy(),
        **kwargs,
    )


def aggregate(
    ref, *, category="A", pointer="/A", mark="point", layer_id="layer.aggregate"
):
    return PlotLayer(
        layer_id=layer_id,
        role="aggregate",
        mark=mark,
        encoding=PlotEncoding(x="category", y="score"),
        data=(
            PlotDatum(
                datum_id="datum." + category.lower(),
                category=category,
                y=request("value", scalar(ref, pointer)),
            ),
        ),
    )


def result_fixture(
    tmp_path, raw=b'{"A":0.831,"B":0.832,"lower":0.80,"upper":0.85,"n":3}\n'
):
    return accepted_fixture(tmp_path, raw)


def binding(value, start, end, *, binding_id="binding.caption", **kwargs):
    return CaptionBinding(
        binding_id=binding_id,
        start_byte=start,
        end_byte=end,
        number_kind="result",
        plot_value_id=value.plot_value_id,
        series=value.series,
        category=value.category,
        statistic=value.statistic,
        expr=value.expr,
        unit=value.unit,
        scale=value.scale,
        revision=value.revision,
        confirmation="declared",
        **kwargs,
    )


def test_exact_nonterminating_groups_and_presentation_identity(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path, b"id,score,category\na,0,A\nb,0,A\nc,1,A\nd,0.832,B\n"
    )
    a = selection(ref, row_set=RowIds(ids=("a", "b", "c")))
    b = selection(ref, row_set=RowIds(ids=("d",)))
    layer = PlotLayer(
        layer_id="layer.mean",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="category", y="score"),
        data=(
            PlotDatum(datum_id="mean.a", category="A", y=request("mean", a)),
            PlotDatum(datum_id="mean.b", category="B", y=request("mean", b)),
        ),
    )
    ir = plot((layer,))
    compiled = compile_plot(ir, context)
    assert compiled.plot_values[0].exact.as_fraction() == Fraction(1, 3)
    assert (
        compiled.plot_values[0].derivation_id != compiled.plot_values[1].derivation_id
    )
    changed = ir.model_copy(
        update={"presentation": PlotPresentation(palette="monochrome")}
    )
    other = compile_plot(changed, context)
    assert [v.derivation_id for v in compiled.plot_values] == [
        v.derivation_id for v in other.plot_values
    ]
    assert PlotRenderer().render(compiled) != PlotRenderer().render(other)


def test_coordinates_use_exact_not_same_rounded_display(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path)
    a, b = (
        aggregate(ref),
        aggregate(ref, category="B", pointer="/B", layer_id="layer.b"),
    )
    a = a.model_copy(update={"display": PlotDisplay(decimals=2)})
    b = b.model_copy(update={"display": PlotDisplay(decimals=2)})
    compiled = compile_plot(plot((a, b)), context)
    assert compiled.plot_values[0].exact != compiled.plot_values[1].exact
    svg = ET.fromstring(PlotRenderer().render(compiled))
    assert len({e.attrib["cy"] for e in svg.iter() if e.tag.endswith("circle")}) == 2
    assert all(v.display.decimals == 2 for v in compiled.plot_values)


def test_caption_swapped_values_same_rounded_context_and_revision(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path)
    layer = aggregate(ref).model_copy(update={"display": PlotDisplay(decimals=2)})
    second = aggregate(ref, category="B", pointer="/B", layer_id="layer.b").model_copy(
        update={"display": PlotDisplay(decimals=2)}
    )
    ir = plot((layer, second), caption="A=0.83 B=0.83")
    compiled = compile_plot(ir, context)
    a, b = compiled.plot_values
    wrong = binding(b, 2, 6).model_copy(update={"category": "A", "expr": a.expr})
    ir = ir.model_copy(update={"caption_bindings": (wrong,)})
    checks = caption_checks(compile_plot(ir, context))
    assert any(
        c.code == "caption_context_mismatch" and c.status == "advisory" for c in checks
    )
    assert any(c.status == "unknown" for c in checks)
    stale = binding(a, 2, 6).model_copy(update={"revision": 2})
    checks = caption_checks(
        compile_plot(ir.model_copy(update={"caption_bindings": (stale,)}), context)
    )
    assert checks[0].code == "caption_revision_mismatch"
    swapped = plot((aggregate(ref),), caption="A=0.832")
    av = compile_plot(swapped, context).plot_values[0]
    swapped = swapped.model_copy(update={"caption_bindings": (binding(av, 2, 7),)})
    assert (
        caption_checks(compile_plot(swapped, context))[0].code
        == "caption_value_mismatch"
    )


def test_auth_declaration_never_upgrades_caption_to_hard_check(tmp_path):
    root, context, ref, _ = result_fixture(tmp_path)
    ir = plot((aggregate(ref),), caption="A=0.831")
    value = compile_plot(ir, context).plot_values[0]
    declared = binding(value, 2, 7).model_copy(update={"confirmation": "authenticated"})
    ir = ir.model_copy(update={"caption_bindings": (declared,)})
    checks = caption_checks(compile_plot(ir, context), hard_caption_checks=True)
    assert (
        checks[0].status == "unsupported" and checks[0].code == "caption_auth_missing"
    )
    receipt, _, _ = ResearchArtifactService().capture_result_plot(
        ir, run_root=root, hard_caption_checks=True
    )
    assert receipt.qualification == "FAIL"
    assert "caption_auth_missing" in receipt.reason_codes


def interval(
    ref, *, kind="ci", lower="/lower", upper="/upper", mode="precomputed_interval"
):
    from arw.kernel.state.numeric_core import RationalExact

    uncertainty = PlotUncertainty(
        interval_type=kind,
        sampling_unit="independent trial",
        n_source=request("value", scalar(ref, "/n")),
        missing_policy="reject",
        method="Accepted precomputed endpoints",
        assumptions=("fixed protocol",),
        calculation_source=ref,
        confidence_level=RationalExact(numerator=19, denominator=20)
        if kind == "ci"
        else None,
        ddof=1 if kind == "sd" else None,
        mode=mode,
    )
    return PlotLayer(
        layer_id="layer.interval",
        role="interval",
        mark="rule",
        encoding=PlotEncoding(x="category", y="score"),
        uncertainty=uncertainty,
        data=(
            PlotDatum(
                datum_id="interval.a",
                category="A",
                lower=request("value", scalar(ref, lower)),
                upper=request("value", scalar(ref, upper)),
            ),
        ),
    )


def test_metadata_numbers_bind_by_kind_and_interval_source_not_statistics_pass(
    tmp_path,
):
    _, context, ref, _ = result_fixture(tmp_path)
    caption = "Figure 2: n=3; ci=0.95"
    bindings = (
        CaptionBinding(
            binding_id="bind.figure",
            start_byte=7,
            end_byte=8,
            number_kind="figure_number",
            metadata_key="figure_number",
            revision=1,
        ),
        CaptionBinding(
            binding_id="bind.n",
            start_byte=12,
            end_byte=13,
            number_kind="sample_size",
            metadata_key="layer.interval.n",
            revision=1,
        ),
        CaptionBinding(
            binding_id="bind.ci",
            start_byte=18,
            end_byte=22,
            number_kind="confidence_level",
            metadata_key="layer.interval.confidence_level",
            revision=1,
        ),
    )
    ir = plot(
        (aggregate(ref), interval(ref)),
        caption=caption,
        caption_bindings=bindings,
        figure_number=2,
    )
    compiled = compile_plot(ir, context)
    assert any(
        c.code == "precomputed_interval_source_resolved" and c.status == "resolved"
        for c in compiled.checks
    )
    assert any(
        c.category == "statistics" and c.status == "unsupported"
        for c in compiled.checks
    )
    assert all(
        c.code == "caption_binding_matches"
        for c in caption_checks(compiled)
        if c.category == "caption"
    )
    bad = bindings[0].model_copy(update={"metadata_key": "layer.interval.n"})
    checks = caption_checks(
        compile_plot(ir.model_copy(update={"caption_bindings": (bad,)}), context)
    )
    assert checks[0].code == "caption_metadata_mismatch"


def test_interleaved_series_lines_order_independently(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path,
        b"id,score,category,series,order\na,0.9,B,S1,2\nb,0.1,A,S2,1\nc,0.2,A,S1,1\nd,0.8,B,S2,2\n",
    )
    layer = PlotLayer(
        layer_id="layer.line",
        role="observation",
        mark="line",
        source=selection(ref),
        encoding=PlotEncoding(x="category", y="score", series="series", order="order"),
    )
    compiled = compile_plot(plot((layer,)), context)
    root = ET.fromstring(PlotRenderer().render(compiled))
    paths = [e.attrib["d"] for e in root.iter() if e.tag.endswith("path")]
    assert len(paths) == 2 and all(
        p.count("M") == 1 and p.count("L") == 1 for p in paths
    )
    # Explicit order A→B although lexicographically first CSV row is B.
    assert all(float(p.split()[1]) < float(p.split()[4]) for p in paths)


@pytest.mark.parametrize(
    "rows,code",
    [
        ("a,0.1,A,S,1,p1\nb,0.2,B,S,2,p1\nc,0.3,A,S,1,p2\n", "missing_pair_member"),
        ("a,0.1,A,S,1,p1\nb,0.2,A,S,2,p1\nc,0.3,B,S,3,p1\n", "duplicate_pair_id"),
        ("a,0.1,A,S,1,\nb,0.2,B,S,2,p1\n", "missing_pair_id"),
    ],
)
def test_pair_missing_and_duplicates_explicit(tmp_path, rows, code):
    _, context, ref, _ = accepted_fixture(
        tmp_path, ("id,score,category,series,order,pair\n" + rows).encode()
    )
    layer = PlotLayer(
        layer_id="layer.pair",
        role="observation",
        mark="line",
        source=selection(ref),
        paired=True,
        encoding=PlotEncoding(
            x="category", y="score", series="series", order="order", pair_id="pair"
        ),
    )
    # Duplicate line orders are independently invalid; give order unique where
    # testing duplicate pairs, and put pair validation ahead of line ordering.
    with pytest.raises(PlotFault, match=code):
        compile_plot(plot((layer,)), context)


def test_pair_connections_and_stable_jitter(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path,
        b"id,score,category,series,order,pair\na,0.1,A,S,1,p1\nb,0.2,B,S,2,p1\nc,0.3,A,S,3,p2\nd,0.4,B,S,4,p2\n",
    )
    line = PlotLayer(
        layer_id="layer.pair",
        role="observation",
        mark="line",
        source=selection(ref),
        paired=True,
        encoding=PlotEncoding(
            x="category", y="score", series="series", order="order", pair_id="pair"
        ),
    )
    strip = PlotLayer(
        layer_id="layer.strip",
        role="observation",
        mark="strip",
        source=selection(ref),
        jitter_axis="x",
        encoding=PlotEncoding(x="category", y="score"),
    )
    compiled = compile_plot(plot((line, strip)), context)
    svg = PlotRenderer().render(compiled)
    assert svg == PlotRenderer().render(compiled)
    root = ET.fromstring(svg)
    assert len([e for e in root.iter() if e.tag.endswith("path")]) == 2
    ys = [e.attrib["cy"] for e in root.iter() if e.tag.endswith("circle")]
    assert ys[:4] == ys[4:]  # jitter only changes the band display axis


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("reverse", "invalid_interval"),
        ("sd", "unsupported_sd_se_recomputation"),
        ("se", "unsupported_sd_se_recomputation"),
    ],
)
def test_uncertainty_boundaries_fail_without_silent_repair(tmp_path, mutation, code):
    _, context, ref, _ = result_fixture(
        tmp_path, b'{"A":0.831,"lower":0.8,"upper":0.85,"n":1}\n'
    )
    layer = (
        interval(ref, lower="/upper", upper="/lower")
        if mutation == "reverse"
        else interval(ref, kind=mutation, mode="recompute_" + mutation)
    )
    with pytest.raises(PlotFault, match=code):
        compile_plot(plot((aggregate(ref), layer)), context)


def test_missing_uncertainty_contract_and_closed_grammar(tmp_path):
    _, _, ref, _ = result_fixture(tmp_path)
    value = interval(ref).model_dump(mode="json")
    for key in (
        "method",
        "confidence_level",
        "sampling_unit",
        "n_source",
        "assumptions",
    ):
        bad = json.loads(json.dumps(value))
        bad["uncertainty"].pop(key)
        with pytest.raises(ValidationError):
            PlotLayer.model_validate_json(json.dumps(bad))
    for field, unsupported in (("mark", "box"), ("role", "raw")):
        bad = aggregate(ref).model_dump(mode="json")
        bad[field] = unsupported
        with pytest.raises(ValidationError):
            PlotLayer.model_validate_json(json.dumps(bad))
    ir = plot((aggregate(ref),)).model_dump(mode="json")
    ir["panel"] = "facet"
    with pytest.raises(ValidationError):
        ResultPlotIR.model_validate_json(json.dumps(ir))


def test_small_sample_advisory_category_counts_raw_unavailable(tmp_path):
    root, context, ref, _ = result_fixture(tmp_path)
    h = PlotHeuristics(effective_n=request("value", scalar(ref, "/n")))
    continuous = plot((aggregate(ref, mark="bar"),), heuristics=h)
    receipt, _, _ = ResearchArtifactService().capture_result_plot(
        continuous, run_root=root
    )
    assert receipt.qualification == "PASS" and any(
        c.code == "small_sample_summary_only" and c.status == "advisory"
        for c in receipt.checks
    )
    counts = continuous.model_copy(
        update={"heuristics": h.model_copy(update={"outcome_kind": "category_count"})}
    )
    assert not any(
        c.code == "small_sample_summary_only"
        for c in compile_plot(counts, context).checks
    )
    unavailable = continuous.model_copy(
        update={"heuristics": h.model_copy(update={"raw_data": "raw_unavailable"})}
    )
    compiled = compile_plot(unavailable, context)
    assert len(compiled.plot_values) == 1 and all(
        v.stable_row_id is None for v in compiled.plot_values
    )
    assert any(c.code == "raw_unavailable" for c in compiled.checks)


def test_safe_text_xml_tex_metacharacters_determinism(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path)
    text = '<script onload="evil"> & \\ % { $ }'
    ir = plot((aggregate(ref),), caption=text)
    ir = ir.model_copy(update={"title": text})
    compiled = compile_plot(ir, context)
    output = PlotRenderer().render(compiled)
    assert output == PlotRenderer().render(compiled) and validate_svg_safety(output)
    root = ET.fromstring(output)
    assert root.find("{http://www.w3.org/2000/svg}title").text == text
    assert b"<script " not in output


@pytest.mark.parametrize(
    "body",
    [
        "<script/>",
        '<image href="https://evil.example/a.png"/>',
        '<circle onload="evil()"/>',
        '<text href="https://evil.example/">x</text>',
        '<text style="fill:url(http://evil)">x</text>',
        '<text fill="@import x">x</text>',
        "<foreignObject/>",
    ],
)
def test_svg_injection_rejected(body):
    with pytest.raises(PlotFault):
        validate_svg_safety(
            ('<svg xmlns="http://www.w3.org/2000/svg">' + body + "</svg>").encode()
        )


def test_same_run_parent_lifecycle_inspect_reproduce_visual_unavailable(tmp_path):
    root, _context, ref, _ = result_fixture(tmp_path)
    service = ResearchArtifactService()
    ir = plot((aggregate(ref),))
    result = service.qualify(ir, run_root=root, request=parent_request(root))
    assert result["accepted"]
    receipt = result["receipt"]
    assert receipt["receipt_version"] == "arw.result-plot-receipt.v1"
    assert receipt["rendered_from"]["source_refs"][0]["run_id"] == ref.run_id
    assert service.inspect(ir.artifact_id, run_root=root)["receipt"] == receipt
    assert verify_plot_receipt(
        root, replay_run(root).events, ir.artifact_id
    ).plot_values
    assert service.reproduce(ir.artifact_id, run_root=root)["status"] == "reproduced"
    publication = ir.model_copy(
        update={
            "artifact_id": "figure.publication",
            "publication_critical": True,
            "caption": "Accuracy result",
            "manuscript_reference": "Figure 2",
            "validation_policy": policy("REQUIRED"),
        }
    )
    result = service.qualify(
        publication, run_root=root, request=parent_request(root, 101)
    )
    assert (
        not result["accepted"]
        and result["receipt"]["validation"]["visual"] == "UNAVAILABLE"
    )
    assert result["receipt"]["publication_quality"] == "not_verified"


def test_cross_run_readonly_receipt_preserves_same_name_identity(tmp_path):
    first, context, ref1, _ = accepted_fixture(tmp_path, b'{"A":0.1}\n')
    second, _, ref2, _ = accepted_fixture(tmp_path, b'{"A":0.9}\n', run_index=2)
    combined = replace(context, run_roots=(first, second))
    ir = plot(
        (
            aggregate(ref1),
            aggregate(ref2, category="B", pointer="/A", layer_id="layer.b"),
        )
    )
    receipt, _, output = ResearchArtifactService().capture_result_plot(
        ir, run_root=first, resolution_context=combined
    )
    assert [v.exact.as_fraction() for v in receipt.plot_values] == [
        Fraction(1, 10),
        Fraction(9, 10),
    ]
    assert len({r.run_id for r in receipt.inputs}) == 2 and validate_svg_safety(output)
    with pytest.raises(PlotFault, match="cross_run_parent_acceptance_unsupported"):
        ResearchArtifactService().qualify(
            ir,
            run_root=first,
            request=parent_request(first),
            resolution_context=combined,
        )


def test_source_tampering_legacy_observed_and_numeric_context_fail(tmp_path):
    root, context, ref, _ = result_fixture(tmp_path)
    ir = plot((aggregate(ref),))
    (root / "data.json").write_bytes(b'{"A":0.9}\n')
    with pytest.raises(PlotFault, match="unresolved_plot_source"):
        compile_plot(ir, context)


def test_legacy_observed_display_never_treated_as_exact(tmp_path):
    _, context, ref, _ = result_fixture(
        tmp_path,
        b'{"schema_version":"arw.experiment-acceptance.v1","observed":"0.83"}\n',
    )
    with pytest.raises(PlotFault, match="numeric_unsupported"):
        compile_plot(plot((aggregate(ref, pointer="/observed"),)), context)


def test_schemas_are_additive_exact_and_strict(tmp_path):
    _, _, ref, _ = result_fixture(tmp_path)
    ir = plot((aggregate(ref),))
    documents = result_plot_schema_documents()
    jsonschema.Draft202012Validator(documents["result-plot-ir.schema.json"]).validate(
        ir.model_dump(mode="json")
    )
    for name, doc in documents.items():
        checked = json.loads(
            (__import__("pathlib").Path("schemas/v1") / name).read_text()
        )
        assert checked == doc
    value = ir.model_dump(mode="json")
    value["facet"] = "x"
    with pytest.raises(ValidationError):
        ResultPlotIR.model_validate_json(json.dumps(value))


def test_raw_observations_mean_and_precomputed_interval_share_sources(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path, b"id,score,category,lo,hi\na,0.8,A,0.78,0.86\nb,0.84,A,0.78,0.86\n"
    )
    from arw.kernel.state.numeric_core import RationalExact

    source = selection(ref)
    obs = PlotLayer(
        layer_id="layer.raw",
        role="observation",
        mark="point",
        source=source,
        encoding=PlotEncoding(x="category", y="score"),
    )
    mean = PlotLayer(
        layer_id="layer.mean",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="category", y="score"),
        data=(PlotDatum(datum_id="mean.a", category="A", y=request("mean", source)),),
    )
    lower = source.model_copy(
        update={"columns": ("lo",), "row_set": RowIds(ids=("a",))}
    )
    upper = source.model_copy(
        update={"columns": ("hi",), "row_set": RowIds(ids=("a",))}
    )
    uncertainty = PlotUncertainty(
        interval_type="ci",
        sampling_unit="trial",
        n_source=request("count", source),
        missing_policy="reject",
        method="Precomputed bootstrap endpoints",
        assumptions=("Independent trials",),
        calculation_source=ref,
        confidence_level=RationalExact(numerator=19, denominator=20),
    )
    band = PlotLayer(
        layer_id="layer.interval",
        role="interval",
        mark="rule",
        encoding=PlotEncoding(x="category", y="score"),
        uncertainty=uncertainty,
        data=(
            PlotDatum(
                datum_id="interval.a",
                category="A",
                lower=request("value", lower),
                upper=request("value", upper),
            ),
        ),
    )
    ir = plot(
        (obs, mean, band),
        heuristics=PlotHeuristics(effective_n=request("count", source)),
    )
    compiled = compile_plot(ir, context)
    assert len(compiled.plot_values) == 5
    assert sum(v.stable_row_id is not None for v in compiled.plot_values) == 2
    assert compiled.metadata["layer.interval.n"].as_fraction() == 2
    assert not any(c.code == "small_sample_summary_only" for c in compiled.checks)
    assert validate_svg_safety(PlotRenderer().render(compiled))


def test_missing_policy_does_not_hide_paired_missing_rows(tmp_path):
    _, context, ref, _ = accepted_fixture(
        tmp_path, b"id,score,category,series,order,pair\na,0.1,A,S,1,p1\nb,,B,S,2,p1\n"
    )
    source = selection(ref, missing_policy="exclude")
    layer = PlotLayer(
        layer_id="layer.paired",
        role="observation",
        mark="line",
        source=source,
        paired=True,
        encoding=PlotEncoding(
            x="category", y="score", series="series", order="order", pair_id="pair"
        ),
    )
    with pytest.raises(PlotFault, match="paired_missing_numeric_value"):
        compile_plot(plot((layer,)), context)


def test_numeric_boundaries_context_and_scale_domains(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path, b'{"A":0,"B":1,"zero":0,"neg":-1}\n')
    ir = plot((aggregate(ref),))
    scales = PlotScales(x=ir.scales.x, y=ir.scales.y.model_copy(update={"type": "log"}))
    with pytest.raises(PlotFault, match="log_value_out_of_domain"):
        PlotRenderer().render(
            compile_plot(ir.model_copy(update={"scales": scales}), context)
        )
    first = aggregate(ref)
    operand = scalar(
        ref, "/B", comparison=CTX.model_copy(update={"dataset": "different-dataset"})
    )
    second = PlotLayer(
        layer_id="layer.other",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="category", y="score"),
        data=(
            PlotDatum(
                datum_id="other.b",
                category="B",
                y=request("value", operand, context=operand.context),
            ),
        ),
    )
    with pytest.raises(PlotFault, match="plot_comparison_context_mismatch"):
        compile_plot(plot((first, second)), context)
    division = aggregate(ref).model_copy(
        update={
            "data": (
                PlotDatum(
                    datum_id="ratio.a",
                    category="A",
                    y=request("ratio", scalar(ref, "/B"), scalar(ref, "/zero")),
                ),
            )
        }
    )
    with pytest.raises(PlotFault, match="numeric_undefined"):
        compile_plot(plot((division,)), context)


def test_display_scale_preserves_derivation_and_exact_coordinates(tmp_path):
    from arw.kernel.state.numeric_core import RationalExact

    _, context, ref, _ = result_fixture(tmp_path)
    original = aggregate(ref)
    scaled = original.model_copy(
        update={
            "display": PlotDisplay(
                decimals=1,
                scale=RationalExact(numerator=100, denominator=1),
                unit_suffix="%",
            )
        }
    )
    ir = plot((scaled,), caption="A=83.1%")
    p = compile_plot(ir, context).plot_values[0]
    ir = ir.model_copy(update={"caption_bindings": (binding(p, 2, 6),)})
    assert (
        caption_checks(compile_plot(ir, context))[0].code == "caption_binding_matches"
    )
    a = compile_plot(plot((original,)), context)
    b = compile_plot(ir, context)
    assert a.plot_values[0].derivation_id == b.plot_values[0].derivation_id
    assert a.plot_values[0].exact == b.plot_values[0].exact

    def circles(compiled):
        return [
            (e.attrib["cx"], e.attrib["cy"])
            for e in ET.fromstring(PlotRenderer().render(compiled)).iter()
            if e.tag.endswith("circle")
        ]

    assert circles(a) == circles(b)


def test_visual_evidence_is_rejected_unless_exact_result_ir_output_bound(tmp_path):
    from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

    root, _, ref, _ = result_fixture(tmp_path)
    service = ResearchArtifactService()
    ir = plot(
        (aggregate(ref),), caption="Accepted estimate", manuscript_reference="Figure 1"
    )
    ir = ir.model_copy(
        update={"publication_critical": True, "validation_policy": policy("REQUIRED")}
    )
    # This is deliberately invalid simulated fixture evidence, not a review.
    _, _, output = service.capture_result_plot(ir, run_root=root)
    review = {
        "schema_version": "arw.visual-review.v1",
        "ir_sha256": "f" * 64,
        "output_sha256": sha256_hex(output),
        "status": "PASS",
        "reviewer": {
            "tool_id": "simulated.invalid.fixture",
            "version": "1",
            "identity_digest": "a" * 64,
        },
    }
    (root / "review.json").write_bytes(canonical_json_bytes(review))
    assert accept_extra(
        root, "review.invalid", "review.json", 70, "visual-review"
    ).accepted
    result = service.qualify(
        ir,
        run_root=root,
        request=parent_request(root),
        visual_review_id="review.invalid",
    )
    assert not result["accepted"]
    assert "invalid_visual_review_binding" in result["receipt"]["reason_codes"]
    assert result["receipt"]["visual_reviewer"] is None


def test_result_plot_supersession_revision_retry_and_retained_bytes(tmp_path):
    root, _, ref, _ = result_fixture(tmp_path)
    service = ResearchArtifactService()
    ir = plot((aggregate(ref),))
    req = parent_request(root)
    first = service.qualify(ir, run_root=root, request=req)
    assert (
        first["accepted"]
        and service.qualify(ir, run_root=root, request=req)["idempotent"]
    )
    path = root / ".arw/artifacts/accepted/figure.result/figure.svg"
    original = path.read_bytes()
    successor = ir.model_copy(
        update={
            "artifact_id": "figure.next",
            "revision": 2,
            "supersedes": ir.artifact_id,
        }
    )
    assert service.qualify(successor, run_root=root, request=parent_request(root, 101))[
        "accepted"
    ]
    assert path.read_bytes() == original
    wrong = successor.model_copy(
        update={
            "artifact_id": "figure.wrong",
            "revision": 4,
            "supersedes": successor.artifact_id,
        }
    )
    with pytest.raises(ValueError, match="plot_supersession_revision_mismatch"):
        service.qualify(wrong, run_root=root, request=parent_request(root, 102))


def accept_extra(root, artifact_id, path, number, kind):
    from arw.kernel.core.canonical import sha256_hex
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.state.models import ArtifactAcceptanceRequest

    replay = replay_run(root)
    base = parent_request(root, number).model_dump(mode="json")
    base.update(
        artifact_id=artifact_id,
        artifact_kind=kind,
        media_type="application/json",
        content_path=path,
        content_sha256=sha256_hex((root / path).read_bytes()),
        base_revision=replay.revision,
        consumed_sha256=[replay.last_event_sha256],
    )
    return RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate_json(json.dumps(base))
    )
