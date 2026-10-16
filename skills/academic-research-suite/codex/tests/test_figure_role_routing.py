"""Actual role plans exclude irrelevant instructions and report capability gaps."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/route_figure.py"
SPEC = importlib.util.spec_from_file_location("figure_role_router_test", SCRIPT)
ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTER)
FIXTURES = sorted((ROOT / "tests/fixtures/figure_roles").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_six_public_briefs_have_exact_reproducible_outputs(path):
    value = json.loads(path.read_text())
    result = ROUTER.route_figure(value["brief"])
    assert result == value["expected"]
    assert result["rendered"] is False
    assert result["scientific_admission"] == "not_evaluated"
    assert result["visual_acceptance"] == "not_evaluated"
    assert "scientific_truth" in result["rules"]
    assert "safe_output" in result["rules"]
    assert "flat_minimal_muted" in result["excluded_rules"]
    if result["role"] != "quantitative":
        assert "quantitative_axes" not in result["rules"]
        assert "quantitative_axes" in result["excluded_rules"]
    if path.stem == "method_loop":
        assert result["status"] == "backend_supported"
    if path.stem in {"distribution", "mixed_main", "spatial_mechanism", "strict_box"}:
        assert result["status"] == "unavailable"
    if path.stem == "mixed_main":
        assert "quantitative_axes" in result["panels"][1]["rules"]
        assert "quantitative_axes" not in result["panels"][0]["rules"]
    assert ("strict_box" in result["rules"]) == (path.stem == "strict_box")


def example(name="point_estimate"):
    return json.loads((ROOT / f"tests/fixtures/figure_roles/{name}.json").read_text())[
        "brief"
    ]


def test_quantitative_perspective_is_blocked_and_cannot_be_relabelled_style():
    brief = example()
    brief.update(depth="comparison_perspective", style_profile="flat_minimal_muted")
    result = ROUTER.route_figure(brief)
    assert result["status"] == "blocked"
    assert "misleading_quantitative_perspective" in result["conflicts"]
    assert "flat_minimal_muted" in result["rules"]
    assert "scientific_truth" in result["rules"]


def test_requested_font_and_venue_conflict_are_not_silently_overridden():
    brief = example()
    brief["font_family"] = "Times New Roman"
    result = ROUTER.route_figure(brief)
    assert result["format"]["font_family"] == "Times New Roman"
    assert "font_family" in result["capability_gaps"]
    brief["venue_format"] = dict(
        source="synthetic:venue-profile",
        checked_at="2026-10-16",
        font_family="Other font",
        internal_title=True,
    )
    result = ROUTER.route_figure(brief)
    assert result["status"] == "blocked"
    assert "format_conflict_requires_resolution" in result["conflicts"]
    assert "venue_reference_requires_verification" in result["conflicts"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_argument",
        "unknown_role",
        "infinite_size",
        "boolean_size",
        "missing_depth_source",
        "unexpected_field",
        "nested_composite",
    ],
)
def test_invalid_brief_is_rejected(mutation):
    brief = example("mixed_main" if mutation == "nested_composite" else "method_loop")
    if mutation == "missing_argument":
        brief.pop("visual_argument")
    elif mutation == "unknown_role":
        brief["role"] = "any"
    elif mutation == "infinite_size":
        brief["target_mm"]["width"] = float("inf")
    elif mutation == "boolean_size":
        brief["target_mm"]["width"] = True
    elif mutation == "missing_depth_source":
        brief["depth"] = "spatial_mechanism"
    elif mutation == "unexpected_field":
        brief["ignore_sources"] = True
    else:
        child = copy.deepcopy(brief)
        brief["panels"][0] = child
    with pytest.raises(ValueError):
        ROUTER.route_figure(brief)


def test_real_cli_and_bounded_duplicate_json_errors(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(example()))
    args = [sys.executable, str(SCRIPT), "--brief", str(path)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "backend_supported"
    for raw in ('{"role":"schematic","role":"quantitative"}', "x" * 65537, "[]"):
        path.write_text(raw)
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        assert result.returncode == 65
        assert json.loads(result.stdout)["status"] == "error"
        assert "Traceback" not in result.stderr


def test_effective_loader_uses_overlay_before_upstream_checklists():
    skill = (ROOT.parent / "SKILL.md").read_text()
    assert skill.index("figure role routing") < skill.index(
        "manuscript artifact and figure boundaries"
    )
    team = (ROOT / "agents/academic-paper-team.md").read_text()
    assert "Do not append the old global statistics" in team
    reference = (ROOT / "references/manuscript_artifact_and_figures.md").read_text()
    assert "figure_role_routing.md" in reference
    assert "acceptable only when" not in reference


def test_explicit_author_title_has_one_policy_and_an_honest_backend_gap():
    brief = example()
    brief["internal_title"] = True
    result = ROUTER.route_figure(brief)
    assert result["format"]["internal_figure_title"] is True
    assert "explicitly selected" in result["rules"]["caption_boundary"]
    assert "internal_title" in result["capability_gaps"]
