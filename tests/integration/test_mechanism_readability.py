"""Round2 regressions: source-bound drawing behavior, never review approval."""

import copy
import json
import xml.etree.ElementTree as ET
from itertools import pairwise

import pytest
from arw_research_artifact.mechanism import route_points
from pydantic import ValidationError

from arw.kernel.state.mechanism_figure import MechanismFacts
from tests.integration.test_mechanism_figures import example, prepared

NS = "{http://www.w3.org/2000/svg}"


def rendered(tmp_path, index):
    from arw_research_artifact.mechanism import render_mechanism

    root, service, ir, facts = prepared(tmp_path, index)
    _, svg = render_mechanism(service, ir, run_root=root)
    return ET.fromstring(svg), ir, facts


def node(root, identity):
    found = root.find(f".//*[@id='{identity}']")
    assert found is not None, identity
    return found


def test_counterexample_name_is_intact_and_reserved_above_its_route(tmp_path):
    svg, ir, facts = rendered(tmp_path, 2)
    label = node(svg, "edge-label.counterexample")
    spans = label.findall(NS + "tspan")
    assert [s.text for s in spans] == ["counterexample"]
    x, y = float(spans[0].get("x")), float(spans[0].get("y"))
    relation = next(r for r in facts.relations if r.semantic_id == "counterexample")
    points = route_points(facts, ir, relation)
    assert any(
        a[1] == b[1] and min(a[0], b[0]) <= x < max(a[0], b[0]) and a[1] - y >= 6
        for a, b in pairwise(points)
    )


def test_retry_bypasses_once_only_initial_state_and_reaches_increment(tmp_path):
    svg, ir, facts = rendered(tmp_path, 1)
    components = {c.semantic_id: c for c in facts.components}
    assert "initialize" in components
    initialize, request = components["initialize"], components["request"]
    assert "attempts=0" in " ".join(initialize.steps)
    assert "Once per episode" in " ".join(initialize.steps)
    assert all("attempts=0" not in s for s in request.steps)
    assert request.steps == ("Increment attempts; request lookup(key=public-toy).",)
    retry = next(r for r in facts.relations if r.semantic_id == "retry")
    entry = next(r for r in facts.relations if r.semantic_id == "initialized")
    assert (retry.target_component, retry.target_port) == ("request", "input")
    assert (entry.target_component, entry.target_port) == ("request", "initial")
    assert route_points(facts, ir, retry)[-1] != route_points(facts, ir, entry)[-1]
    init_cell = next(c for c in ir.cells if c.semantic_id == "initialize")
    # The horizontal return runs below the whole one-time card.
    assert all(
        y > init_cell.y + init_cell.height for _, y in route_points(facts, ir, retry)
    )
    assert "attempts=0" not in "".join(node(svg, "content.request").itertext())
    # Execute the frozen toy rules, selecting the actual graph edge each time.
    attempts, answer = 0, False
    visited = [entry.target_component]
    for observation in ("missing", "missing"):
        attempts += 1
        answer = observation == "found"
        selected = next(
            r
            for r in facts.relations
            if r.semantic_id == ("retry" if not answer and attempts < 2 else "stop")
        )
        visited.append(selected.target_component)
    assert attempts == 2 and visited == ["request", "request", "done"]


@pytest.mark.parametrize(
    "identity,port,role,attribute",
    [
        ("retry", "again", "continue", "condition"),
        ("stop", "done", "stop", "stop_condition"),
    ],
)
def test_local_predicate_leader_terminates_at_corresponding_output_port(
    tmp_path, identity, port, role, attribute
):
    svg, _, facts = rendered(tmp_path, 1)
    decide = next(c for c in facts.components if c.semantic_id == "decide")
    predicate = node(svg, f"predicate.decide.{port}")
    assert f"{role}: {getattr(decide, attribute)}" == "".join(predicate.itertext())
    leader = node(svg, f"predicate-link.decide.{port}")
    output = node(svg, f"port.decide.{port}")
    assert (leader.get("x2"), leader.get("y2")) == (output.get("cx"), output.get("cy"))
    assert node(svg, f"edge.{identity}").get("points").split()[0] == (
        f"{output.get('cx')},{output.get('cy')}"
    )


def test_coordinate_columns_show_each_source_operand_and_sum(tmp_path):
    svg, _, facts = rendered(tmp_path, 0)
    project = next(c for c in facts.components if c.semantic_id == "project")
    assert project.coordinate_sum.axis_labels == ("red", "blue")
    for col, (name, values, total) in enumerate(
        (("red", (1, 0), 1), ("blue", (0, 1), 1))
    ):
        assert "".join(node(svg, f"coordinate.project.axis.{col}").itertext()) == name
        for row, value in enumerate(values):
            assert "".join(
                node(svg, f"coordinate.project.{row}.{col}").itertext()
            ) == str(value)
        assert "".join(node(svg, f"coordinate.project.sum.{col}").itertext()) == (
            f"{values[0]} + {values[1]} = {total}"
        )


def test_added_guard_is_isolated_in_aligned_source_expression(tmp_path):
    svg, _, facts = rendered(tmp_path, 2)
    change = next(c for c in facts.components if c.semantic_id == "after").rule_change
    assert change.added_clause == "AND not penguin"
    added = node(svg, "rule.after.added")
    assert "".join(added.itertext()) == change.added_clause
    assert added.get("font-weight") == "bold"
    assert node(svg, "rule.after.guard-box").get("stroke-width") == "2"
    for part in ("retained", "conclusion"):
        before = node(svg, f"rule.after.before.{part}").find(NS + "tspan")
        after = node(svg, f"rule.after.after.{part}").find(NS + "tspan")
        assert before.get("x") == after.get("x")


def test_structured_expansion_rejects_unsourced_or_inconsistent_values():
    tasks = example.load_tasks()["tasks"]
    bad = copy.deepcopy(tasks[0]["facts"])
    bad["components"][1]["coordinate_sum"]["result"][0] = 999
    with pytest.raises(ValidationError, match="coordinate_sum"):
        MechanismFacts.model_validate_json(json.dumps(bad))
    bad = copy.deepcopy(tasks[2]["facts"])
    bad["components"][2]["rule_change"]["added_clause"] = "AND not bird"
    with pytest.raises(ValidationError, match="rule_change"):
        MechanismFacts.model_validate_json(json.dumps(bad))


def test_predicates_follow_relation_ports_even_when_port_inventory_is_reordered(
    tmp_path,
):
    from arw_research_artifact.mechanism import MechanismRenderer

    _, _, ir, facts = prepared(tmp_path, 1)
    raw = facts.model_dump(mode="json")
    decide = next(c for c in raw["components"] if c["semantic_id"] == "decide")
    decide["ports"][1:] = reversed(decide["ports"][1:])
    facts = MechanismFacts.model_validate_json(json.dumps(raw))
    svg = ET.fromstring(MechanismRenderer().render(facts, ir))
    assert "".join(node(svg, "predicate.decide.again").itertext()) == (
        "continue: " + decide["condition"]
    )
    assert "".join(node(svg, "predicate.decide.done").itertext()) == (
        "stop: " + decide["stop_condition"]
    )


@pytest.mark.parametrize(
    "fault,index,expected_check",
    [
        ("coordinate", 0, "coordinate.project.0.0"),
        ("guard", 2, "rule.after.exact_added_clause"),
        ("predicate", 1, "predicate_port_binding:retry"),
        ("label_collision", 2, "edge_label_clear:counterexample:counterexample:"),
    ],
)
def test_actual_font_geometry_screen_rejects_independent_svg_corruption(
    tmp_path, fault, index, expected_check
):
    import subprocess

    from tests.integration.test_mechanism_figures import ROOT

    probe = subprocess.run(
        ["/usr/bin/python3", "-c", "import gi; gi.require_version('Rsvg', '2.0')"],
        capture_output=True,
        check=False,
    )
    if probe.returncode:
        pytest.skip("Optional GI/librsvg backend unavailable")
    svg, _, _ = rendered(tmp_path, index)
    if fault == "coordinate":
        node(svg, "coordinate.project.0.0").find(NS + "tspan").text = "999"
    elif fault == "guard":
        node(svg, "rule.after.added").find(NS + "tspan").text = "AND not bird"
    elif fault == "predicate":
        node(svg, "predicate-link.decide.again").set("y2", "0")
    else:
        node(svg, "edge-label.counterexample").find(NS + "tspan").set("y", "254")
    svg_path, task_path = tmp_path / "altered.svg", tmp_path / "task.json"
    svg_path.write_bytes(ET.tostring(svg))
    task_path.write_text(json.dumps(example.load_tasks()["tasks"][index]))
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            (
                "import json,runpy,sys; from pathlib import Path; "
                "screen=runpy.run_path(sys.argv[1])['screen']; "
                "r=screen(json.loads(Path(sys.argv[2]).read_text()),Path(sys.argv[3]).read_bytes()); "
                "print(json.dumps([c['check'] for c in r['checks'] if not c['passed']]))"
            ),
            str(ROOT / "examples/mechanism-figures/check_readability.py"),
            str(task_path),
            str(svg_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert any(c.startswith(expected_check) for c in json.loads(result.stdout))


def test_old_frozen_facts_remain_loadable_and_v3_decomposition_preserves_them():
    import runpy

    from tests.integration.test_mechanism_figures import ROOT

    here = ROOT / "examples/mechanism-figures"
    previous = json.loads((here / "tasks.v2.json").read_text())
    for revision in ("tasks.v1.json", "tasks.v2.json"):
        for task in json.loads((here / revision).read_text())["tasks"]:
            MechanismFacts.model_validate_json(json.dumps(task["facts"]))
    checker = runpy.run_path(str(here / "check_readability.py"))
    assert checker["source_preserved"](example.load_tasks(), previous)


def test_round3_packet_hashes_bind_current_renderer_source_pixels_and_replay():
    from arw_research_artifact.mechanism import MechanismRenderer
    from arw_research_artifact.mechanism_review import advisory_binding
    from arw_research_artifact.service import ResearchArtifactService

    from arw.kernel.core.canonical import sha256_hex
    from arw.kernel.ledger.journal import replay_run
    from tests.integration.test_mechanism_figures import ROOT

    packet = ROOT / "examples/mechanism-figures/evidence/round3"
    for item in json.loads((packet / "manifest.json").read_text())["files"]:
        raw = (packet / item["path"]).read_bytes()
        assert sha256_hex(raw) == item["sha256"]
        assert len(raw) == item["size_bytes"]
    review = json.loads((packet / "reviewer-input.json").read_text())
    for task in review["tasks"]:
        ir = (packet / task["ir"]).read_bytes()
        svg = (packet / task["svg"]).read_bytes()
        png = (packet / task["png"]).read_bytes()
        assert json.loads(ir)[
            "renderer_hints"
        ] == MechanismRenderer().identity.model_dump(mode="json")
        assert (
            advisory_binding(
                source=task["source_answer"],
                ir=ir,
                svg=svg,
                png=png,
                raster=task["raster"],
            ).model_dump(mode="json")
            == task["exact_binding"]
        )
        assert (
            ResearchArtifactService().reproduce(
                "mechanism." + task["id"], run_root=packet / "run"
            )["status"]
            == "reproduced"
        )
    assert replay_run(packet / "run").recovery_health == "healthy"
    report = json.loads((packet / "mechanical.json").read_text())
    assert report["status"] == "passed"
    assert report["independent_pixel_review"] == "not_run"
    assert not report["publication_visual_pass"]
