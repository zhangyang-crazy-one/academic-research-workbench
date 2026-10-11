"""Review regressions use real accepted values and inspect emitted SVG data."""

import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest
from arw_research_artifact.plot_policy import PlotFault, compile_plot
from arw_research_artifact.plot_renderer import PlotRenderer

from arw.kernel.state.numeric_core import RationalExact
from arw.kernel.state.result_plot import (
    PlotDatum,
    PlotEncoding,
    PlotLayer,
    PlotScale,
    PlotScales,
)
from tests.integration.test_result_plots import aggregate, plot, result_fixture
from tests.unit.test_numeric_core import request, scalar


def texts(svg):
    return [e for e in ET.fromstring(svg).iter() if e.tag.endswith("text")]


@pytest.mark.parametrize(
    "scale,a,b",
    [
        ("log", "1e-9", "2e-9"),
        ("linear", "1e-12", "2e-12"),
        ("log", "1e-20", "1e20"),
        ("linear", "1.000000000001", "1.000000000002"),
    ],
)
def test_real_svg_ticks_are_nonzero_distinguishable_and_deterministic(
    tmp_path, scale, a, b
):
    _, context, ref, _ = result_fixture(tmp_path, f'{{"A":{a},"B":{b}}}\n'.encode())
    ir = plot(
        (aggregate(ref), aggregate(ref, category="B", pointer="/B", layer_id="layer.b"))
    )
    ir = ir.model_copy(
        update={
            "scales": PlotScales(x=ir.scales.x, y=PlotScale(type=scale, unit="ratio"))
        }
    )
    compiled = compile_plot(ir, context)
    output = PlotRenderer().render(compiled)
    assert output == PlotRenderer().render(compile_plot(ir, context))
    tick_texts = [
        e
        for e in texts(output)
        if e.attrib["x"] == "8" and e.attrib["font-size"] == "11"
    ]
    labels = ["".join(e.itertext()) for e in tick_texts]
    assert len(labels) == len(set(labels)) == 5
    has_offset = any("y offset" in "".join(e.itertext()) for e in texts(output))
    if not has_offset:
        assert all(Decimal(label) != 0 for label in labels)
    assert all(len(label) <= 18 for label in labels)


def test_real_numeric_x_axis_keeps_small_nonzero_tick_values(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path, b'{"x":1e-9,"A":1}\n')
    layer = PlotLayer(
        layer_id="layer.xy",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="x", y="y"),
        data=(
            PlotDatum(
                datum_id="datum.xy",
                x=request("value", scalar(ref, "/x")),
                y=request("value", scalar(ref, "/A")),
            ),
        ),
    )
    ir = plot((aggregate(ref),)).model_copy(
        update={
            "layers": (layer,),
            "scales": PlotScales(
                x=PlotScale(
                    type="log",
                    unit="ratio",
                    domain=(
                        RationalExact(numerator=1, denominator=10**9),
                        RationalExact(numerator=1, denominator=500_000_000),
                    ),
                ),
                y=PlotScale(type="linear", unit="ratio"),
            ),
        }
    )
    output = PlotRenderer().render(compile_plot(ir, context))
    labels = [
        "".join(e.itertext())
        for e in texts(output)
        if Decimal(e.attrib["y"]) == ir.presentation.height - 158
    ]
    assert len(labels) == len(set(labels)) == 5
    assert all(Decimal(label) != 0 for label in labels)


def test_shared_numeric_x_multiseries_bars_fail_explicitly_before_rendering(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path, b'{"x":1,"a":1,"b":2}\n')
    layer = PlotLayer(
        layer_id="layer.bars",
        role="aggregate",
        mark="bar",
        encoding=PlotEncoding(x="x", y="y"),
        data=tuple(
            PlotDatum(
                datum_id=f"datum.{series}",
                series=series,
                x=request("value", scalar(ref, "/x")),
                y=request("value", scalar(ref, f"/{series}")),
            )
            for series in ("a", "b")
        ),
    )
    ir = plot((aggregate(ref),)).model_copy(
        update={
            "layers": (layer,),
            "scales": PlotScales(
                x=PlotScale(
                    type="linear",
                    unit="ratio",
                    domain=(
                        RationalExact(numerator=0, denominator=1),
                        RationalExact(numerator=2, denominator=1),
                    ),
                ),
                y=PlotScale(type="linear", unit="ratio"),
            ),
        }
    )
    with pytest.raises(PlotFault, match="continuous_grouped_bar_unsupported"):
        compile_plot(ir, context)
