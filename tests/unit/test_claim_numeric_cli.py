"""Public commands use real accepted artifacts and return typed failures."""

import json

from arw.cli import main
from tests.unit.test_accepted_refs import accepted_fixture
from tests.unit.test_numeric_core import request, selection


def test_numeric_cli_returns_exact_third_and_rejects_oversized_request(tmp_path, capsys):
    root, context, ref, _ = accepted_fixture(tmp_path, b"id,score\na,0\nb,0\nc,1\n")
    source = tmp_path / "request.json"
    source.write_text(request("mean", selection(ref)).model_dump_json())
    argv = ["numeric", "derive", "--request", str(source), "--project-id", context.project_id, "--run-root", str(root)]
    assert main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "exact"
    assert result["exact"] == {"numerator": 1, "denominator": 3}
    source.write_bytes(b" " * 2_097_153)
    assert main(argv) == 65
    assert json.loads(capsys.readouterr().out)["code"] == "numeric_invalid"


def test_claims_cli_exposes_structured_missing_project_failure(tmp_path, capsys):
    assert main(["claims", "graph", "--project-root", str(tmp_path), "--json"]) == 65
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert isinstance(result["code"], str)


def test_result_plot_cli_dispatches_real_service_and_preserves_numeric_identity(tmp_path, capsys):
    from tests.integration.test_result_plots import aggregate, plot

    root, _, ref, _ = accepted_fixture(tmp_path, b'{"A":0.831}\n')
    ir = plot((aggregate(ref),))
    source = root / "plot-ir.json"
    source.write_text(ir.model_dump_json())
    assert main(["artifact", "render", "--run-root", str(root), "--input", str(source)]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "candidate"
    svg = (root / rendered["path"]).read_bytes()
    assert svg.startswith(b'<svg')
    assert main(["artifact", "render", "--run-root", str(root), "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out) == rendered


def test_plot_bridge_and_caption_target_cli_are_readonly(tmp_path, capsys):
    from arw_research_artifact.plot_policy import compile_plot

    from tests.integration.test_result_plots import aggregate, binding, plot

    root, context, ref, _ = accepted_fixture(tmp_path, b'{"A":0.831}\n')
    ir = plot((aggregate(ref),), caption="A 0.831")
    value = compile_plot(ir, context).plot_values[0]
    ir = ir.model_copy(update={"caption_bindings": (binding(value, 2, 7),)})
    source = root / "plot-ir.json"
    source.write_text(ir.model_dump_json())
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    common = ["--run-root", str(root), "--input", str(source)]
    assert main(["artifact", "source-bridge", *common]) == 0
    bridge = json.loads(capsys.readouterr().out)
    assert bridge["schema_version"] == "arw.plot-source-bridge.v1"
    assert main(["artifact", "caption-targets", *common]) == 0
    targets = json.loads(capsys.readouterr().out)
    assert targets["bindings"][0]["scope"].startswith("caption:")
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_checkout_launcher_forwards_new_public_commands(tmp_path):
    from tests.unit.test_agent_runtime import LAUNCHER, _agent_env, _run

    for command, action in (("claims", "graph"), ("numeric", "derive")):
        completed = _run([str(LAUNCHER), command, action, "--help"], env=_agent_env(tmp_path))
        assert completed.returncode == 0, completed.stderr
        assert f"{command} {action}" in completed.stdout
