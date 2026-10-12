"""Safe optional source export with the original accepted numerical compiler."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction

import pytest
from arw_research_artifact.pgfplots import PGFPlotsExporter, tex_text
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
    assert "{831/1000}" in source.decode() and "{104/125}" in source.decode()
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
    from arw.kernel.state.result_plot import PlotDatum, PlotEncoding, PlotLayer
    from arw.kernel.state.numeric_core import RowIds
    from tests.unit.test_numeric_core import request, selection
    from tests.unit.test_accepted_refs import accepted_fixture

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
