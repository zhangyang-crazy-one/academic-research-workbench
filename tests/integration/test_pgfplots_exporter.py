"""Safe optional source export with the original accepted numerical compiler."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction

import pytest
from arw_research_artifact.pgfplots import PGFPlotsExporter, rational, tex_text
from arw_research_artifact.plot_policy import PlotFault, compile_plot
from arw_research_artifact.plot_renderer import PlotRenderer
from arw_research_artifact.service import ResearchArtifactService

from arw.kernel.core.canonical import canonical_json_bytes
from tests.integration.test_result_plots import aggregate, plot, result_fixture


def test_joint_special_characters_remain_inert():
    assert (
        tex_text("\\\\%{$&#_^~}")
        == r"\textbackslash{}\textbackslash{}\%\{\$\&\#\_\textasciicircum{}\textasciitilde{}\}"
    )
    value = tex_text(r"\input{/etc/passwd}^^5cwrite18{cmd},xmode=log")
    assert r"\input" not in value and "^^" not in value
    with pytest.raises(PlotFault):
        tex_text("nul\x00")


def test_same_compiled_values_ids_safe_text_and_source_bytes(tmp_path, monkeypatch):
    root, context, ref, _ = result_fixture(tmp_path)
    label = r"\\%{$&},xmode=log\input{file}"
    a = aggregate(ref).model_copy(
        update={"data": (aggregate(ref).data[0].model_copy(update={"series": label}),)}
    )
    ir = plot(
        (a, aggregate(ref, category="B", pointer="/B", layer_id="layer.b"))
    ).model_copy(
        update={"title": label, "caption": label, "manuscript_reference": label}
    )
    compiled = compile_plot(ir, context)
    svg = PlotRenderer().render(compiled)

    def no_process(*args, **kwargs):
        pytest.fail("source-only export must not invoke a process")

    monkeypatch.setattr(subprocess, "run", no_process)
    source, metadata = PGFPlotsExporter().export(compiled)
    second, again = PGFPlotsExporter().export(compiled)
    assert source == second and canonical_json_bytes(metadata) == canonical_json_bytes(
        again
    )
    assert metadata["fixed_environment_render"] == "not_verified"
    assert metadata["publication_quality"] == "not_verified"
    assert metadata["plot_values"] == [
        v.model_dump(mode="json") for v in compiled.plot_values
    ]
    assert all(
        v.plot_value_id.encode() in svg and v.plot_value_id.encode() in source
        for v in compiled.plot_values
        if v.channel == "y"
    )
    assert r"\input" not in source.decode()
    assert tex_text(label) in source.decode()
    assert "0.831" in source.decode() and "0.832" in source.decode()
    before = (root / "journal/segments/00000001.jsonl").read_bytes()
    out = ResearchArtifactService().export_pgfplots(
        ir, run_root=root, resolution_context=context
    )
    repeated = ResearchArtifactService().export_pgfplots(
        ir, run_root=root, resolution_context=context
    )
    assert out == repeated and (root / out["path"]).read_bytes() == source
    assert json.loads((root / out["manifest_path"]).read_text()) == metadata
    assert (root / "journal/segments/00000001.jsonl").read_bytes() == before
    assert PlotRenderer().render(compiled) == svg


def test_nonterminating_fraction_uses_exact_value_not_display(tmp_path):
    from arw.kernel.state.numeric_core import RowIds
    from arw.kernel.state.result_plot import PlotDatum, PlotEncoding, PlotLayer
    from tests.unit.test_accepted_refs import accepted_fixture
    from tests.unit.test_numeric_core import request, selection

    _, context, ref, _ = accepted_fixture(
        tmp_path, b"id,score,category\na,0,A\nb,0,A\nc,1,A\n"
    )
    request_mean = request("mean", selection(ref, row_set=RowIds(ids=("a", "b", "c"))))
    layer = PlotLayer(
        layer_id="layer.mean",
        role="aggregate",
        mark="point",
        encoding=PlotEncoding(x="category", y="value"),
        data=(PlotDatum(datum_id="mean.a", category="A", y=request_mean),),
    )
    compiled = compile_plot(plot((layer,)), context)
    assert compiled.plot_values[0].exact.as_fraction() == Fraction(1, 3)
    source, _ = PGFPlotsExporter().export(compiled)
    assert b"{1/3}" in source


@pytest.mark.parametrize("mark", ["point", "line", "bar", "strip"])
def test_marks_retain_shared_ids(tmp_path, mark):
    from arw.kernel.state.result_plot import PlotEncoding, PlotLayer
    from tests.unit.test_accepted_refs import accepted_fixture
    from tests.unit.test_numeric_core import selection

    if mark == "bar":
        _, context, ref, _ = result_fixture(tmp_path)
        layer = aggregate(ref, mark="bar")
    else:
        _, context, ref, _ = accepted_fixture(
            tmp_path, b"id,score,category,series,order\na,0.2,A,S,1\nb,0.4,B,S,2\n"
        )
        layer = PlotLayer(
            layer_id="layer.observation",
            role="observation",
            mark=mark,
            source=selection(ref),
            encoding=PlotEncoding(
                x="category", y="score", series="series", order="order"
            ),
            jitter_axis="x" if mark == "strip" else None,
        )
    compiled = compile_plot(plot((layer,)), context)
    source, metadata = PGFPlotsExporter().export(compiled)
    assert all(v.plot_value_id.encode() in source for v in compiled.plot_values)
    assert metadata["tex_invoked"] is False
    assert source == PGFPlotsExporter().export(compiled)[0]


def test_cli_writes_optional_source_candidate(tmp_path, capsys):
    from arw.cli import main

    root, _, ref, _ = result_fixture(tmp_path)
    ir = plot((aggregate(ref),))
    path = root / "input/plot.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(canonical_json_bytes(ir.model_dump(mode="json")))
    assert (
        main(
            [
                "artifact",
                "export-pgfplots",
                "--run-root",
                str(root),
                "--input",
                str(path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["fixed_environment_render"] == "not_verified"
    assert (root / output["path"]).is_file()
    assert (root / output["manifest_path"]).is_file()


def test_finite_decimals_do_not_use_tex_division():
    for value, expected in [
        (Fraction(1000003, 1000000), "1.000003"),
        (Fraction(-1, 8), "-0.125"),
        (Fraction(98765432101, 1000), "98765432.101"),
        (Fraction(0), "0"),
        (Fraction(1, 3), "{1/3}"),
    ]:
        assert rational(value) == expected


def named(layer, name):
    return layer.model_copy(
        update={
            "data": tuple(d.model_copy(update={"series": name}) for d in layer.data)
        }
    )


def legend_queue(source):
    lines = source.decode().splitlines()
    return (
        [
            line
            for line in lines
            if line.startswith(r"\addplot[") and "forget plot" not in line
        ],
        [line for line in lines if line.startswith(r"\addlegendentry")],
    )


def test_unnamed_layer_does_not_steal_named_legend_style(tmp_path):
    _, context, ref, _ = result_fixture(tmp_path)
    ir = plot(
        (
            aggregate(ref),
            named(
                aggregate(ref, category="B", pointer="/B", layer_id="layer.named"),
                "Named",
            ),
        )
    )
    source, _ = PGFPlotsExporter().export(compile_plot(ir, context))
    styles, entries = legend_queue(source)
    assert entries == [r"\addlegendentry{Named}"]
    assert len(styles) == 1
    assert "red,230;green,159;blue,0" in styles[0]


def test_interval_segments_have_one_legend_per_series(tmp_path):
    from tests.integration.test_result_plots import interval

    _, context, ref, _ = result_fixture(tmp_path)
    a = named(interval(ref), "Series A")
    first = a.data[0]
    a = a.model_copy(
        update={
            "data": (
                first,
                first.model_copy(update={"datum_id": "interval.b", "category": "B"}),
            )
        }
    )
    b = named(interval(ref).model_copy(update={"layer_id": "layer.second"}), "Series B")
    source, _ = PGFPlotsExporter().export(compile_plot(plot((a, b)), context))
    styles, entries = legend_queue(source)
    assert entries == [r"\addlegendentry{Series A}", r"\addlegendentry{Series B}"]
    assert len(styles) == 2
    assert "red,0;green,0;blue,0" in styles[0]
    assert "red,230;green,159;blue,0" in styles[1]
    assert source.count(b"forget plot") == 1


def test_same_series_across_point_and_interval_has_one_legend(tmp_path):
    from tests.integration.test_result_plots import interval

    _, context, ref, _ = result_fixture(tmp_path)
    source, _ = PGFPlotsExporter().export(
        compile_plot(
            plot((named(aggregate(ref), "Model A"), named(interval(ref), "Model A"))),
            context,
        )
    )
    styles, entries = legend_queue(source)
    assert entries == [r"\addlegendentry{Model A}"]
    assert len(styles) == 1
    assert "only marks" in styles[0]
    assert b"forget plot" in source


def plot_styles(source):
    return [
        line for line in source.decode().splitlines() if line.startswith(r"\addplot")
    ]


def tex_rgb(hex_color):
    rgb = hex_color.lstrip("#")
    return "{rgb,255:red,%d;green,%d;blue,%d}" % (
        int(rgb[:2], 16),
        int(rgb[2:4], 16),
        int(rgb[4:], 16),
    )


@pytest.mark.parametrize("palette", ["monochrome", "okabe_ito"])
def test_every_plot_owns_line_and_marker_colors_without_default_cycle(
    tmp_path, palette
):
    """#140: no PGFPlots cycle-list marker fill can leak into an explicit palette."""
    from arw.kernel.state.result_plot import PlotPresentation
    from arw_research_artifact.plot_renderer import OKABE_ITO

    _, context, ref, _ = result_fixture(tmp_path)
    first = named(aggregate(ref), "Model A")
    second = named(
        aggregate(ref, category="B", pointer="/B", layer_id="layer.second"), "Model A"
    )
    ir = plot((first, second)).model_copy(
        update={"presentation": PlotPresentation(palette=palette)}
    )
    source, _ = PGFPlotsExporter().export(compile_plot(ir, context))
    styles = plot_styles(source)
    assert len(styles) == 2 and not any(s.startswith(r"\addplot+") for s in styles)
    expected = tex_rgb("#222222" if palette == "monochrome" else OKABE_ITO[0])
    for style in styles:
        assert "color=" + expected in style
        assert "mark options={solid,draw=" + expected + ",fill=" + expected + "}" in (
            style
        )
    # Both layers of one series share the exact style; only the second is
    # excluded from the legend queue.
    assert styles[1] == styles[0].replace(
        "] coordinates {", ",forget plot] coordinates {"
    )


def test_paired_lines_use_series_color_for_every_visual_key(tmp_path):
    from arw.kernel.state.result_plot import PlotEncoding, PlotLayer
    from tests.integration.test_result_plots import selection
    from tests.unit.test_accepted_refs import accepted_fixture

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
    source, _ = PGFPlotsExporter().export(compile_plot(plot((line,)), context))
    styles = plot_styles(source)
    assert len(styles) == 2  # one path per pair, one legend entry
    for style in styles:
        assert style.startswith(r"\addplot[solid,mark=*,color=")
        color = style.split("color=", 1)[1].split(",mark options", 1)[0]
        assert "draw=" + color + ",fill=" + color in style


def test_optional_tex_compile_uses_only_palette_marker_fills(tmp_path):
    """Runs only where a TeX engine with PGFPlots already exists."""
    import shutil

    if shutil.which("pdflatex") is None or shutil.which("kpsewhich") is None:
        pytest.skip("pdflatex with PGFPlots is not installed")
    if not subprocess.run(
        ["kpsewhich", "pgfplots.sty"], capture_output=True, text=True
    ).stdout.strip():
        pytest.skip("PGFPlots is not installed")
    from arw.kernel.state.result_plot import PlotPresentation

    _, context, ref, _ = result_fixture(tmp_path)
    ir = plot(
        (
            named(aggregate(ref), "Model A"),
            named(
                aggregate(ref, category="B", pointer="/B", layer_id="layer.second"),
                "Model A",
            ),
        )
    ).model_copy(update={"presentation": PlotPresentation(palette="monochrome")})
    source, _ = PGFPlotsExporter().export(compile_plot(ir, context))
    (tmp_path / "figure.tex").write_bytes(source)
    (tmp_path / "doc.tex").write_text(
        "\\pdfcompresslevel=0\\pdfobjcompresslevel=0\n"
        "\\documentclass{article}\\usepackage{pgfplots}\\pgfplotsset{compat=1.18}\n"
        "\\begin{document}\\input{figure.tex}\\end{document}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:]
    pdf = (tmp_path / "doc.pdf").read_bytes()
    fills = {
        line.strip()
        for line in pdf.decode("latin-1").splitlines()
        if line.strip().endswith(" rg")
    }
    # Default cycle fills are blue!80!black and red!80!black.
    assert "0 0 0.8 rg" not in fills and "0.8 0 0 rg" not in fills
    assert any(f.startswith("0.13") for f in fills)
