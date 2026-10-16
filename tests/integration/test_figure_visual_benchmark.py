"""Known synthetic fault coverage; never independent visual-quality approval."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/figure-benchmark"
spec = importlib.util.spec_from_file_location(
    "arw_public_figure_benchmark", EXAMPLE / "run.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_public_task_digest_and_drift(tmp_path):
    tasks, digest = benchmark.load_tasks()
    assert len(tasks["tasks"]) == 4 and len(tasks["negative_cases"]) == 6
    assert "synthetic" in tasks["nature"].lower() and tasks["license"].startswith("MIT")
    shutil.copy(EXAMPLE / "tasks.json", tmp_path / "tasks.json")
    shutil.copy(EXAMPLE / "tasks.sha256", tmp_path / "tasks.sha256")
    (tmp_path / "tasks.json").write_bytes((tmp_path / "tasks.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="frozen_task_digest_mismatch"):
        benchmark.load_tasks(tmp_path)


def record():
    return {
        "task_sha256": "a" * 64,
        "ir_sha256": "b" * 64,
        "svg_sha256": "c" * 64,
        "pixels": {
            "png_sha256": "d" * 64,
            "rasterizer": {"name": "fixture", "version": "1"},
            "fonts": [{"sha256": "e" * 64}],
        },
    }


@pytest.mark.parametrize(
    "field", ["ir_sha256", "svg_sha256", "task_sha256", "png", "font", "renderer"]
)
def test_review_expires_on_exact_bound_change(field):
    original = record()
    review = {
        "binding_sha256": benchmark.review_binding(original),
        "producer": "generator",
        "reviewer": "fixture contract test only",
        "role": "human_nonproducer",
        "decision": "accept",
        "reason": "Schema contract fixture; no actual human acceptance.",
    }
    assert benchmark.review_state(None, original) == "pending"
    changed = copy.deepcopy(original)
    if field == "png":
        changed["pixels"]["png_sha256"] = "f" * 64
    elif field == "font":
        changed["pixels"]["fonts"][0]["sha256"] = "f" * 64
    elif field == "renderer":
        changed["pixels"]["rasterizer"]["version"] = "2"
    else:
        changed[field] = "f" * 64
    assert benchmark.review_state(review, changed) == "stale"
    review["reviewer"] = "generator"
    assert benchmark.review_state(review, original) == "invalid"
    review["reviewer"] = "fixture contract test only"
    review["reason"] = None
    assert benchmark.review_state(review, original) == "incomplete"


def test_missing_optional_renderer_is_unavailable(tmp_path):
    result = benchmark.rasterize(
        tmp_path / "x.svg",
        tmp_path / "x.png",
        {"width_mm": 180.0, "height_mm": 120.0},
        {"dpi": 150},
        python="/definitely/missing/raster-python",
    )
    assert result["status"] == "unavailable"


def rasterizer_available():
    if not Path("/usr/bin/python3").is_file():
        return False
    probe = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            "import gi,cairo;gi.require_version('Rsvg','2.0');gi.require_version('PangoCairo','1.0');from gi.repository import Rsvg,PangoCairo",
        ],
        capture_output=True,
    )
    return (
        probe.returncode == 0
        and shutil.which("fc-match") is not None
        and shutil.which("rpm") is not None
    )


def test_actual_public_tasks_render_and_preserve_negative_evidence(tmp_path):
    if not rasterizer_available():
        pytest.skip(
            "Optional system GI librsvg/Pango/Cairo/fontconfig/rpm environment is not installed"
        )
    report = benchmark.run(tmp_path / "actual")
    assert len(report["records"]) == 8
    assert report["mechanical_summary"]["denominator"] == 40
    assert (
        sum(
            report["mechanical_summary"][s]
            for s in ("passed", "failed", "unavailable", "not_run")
        )
        == 40
    )
    assert (
        report["publication_visual_pass"] is False
        and report["human_acceptance"] == "pending"
    )
    assert report["independent_review_summary"] == {
        "reviewed": 0,
        "pending": 4,
        "denominator": 4,
    }
    for task in ("loop", "mixed"):
        candidates = [r for r in report["records"] if r["task_id"] == task]
        assert {r["candidate"] for r in candidates} == {"row", "column", "grid"}
        assert len({r["facts_sha256"] for r in candidates}) == 1
        assert len({r["ir_sha256"] for r in candidates}) == 3
        assert len({r["svg_sha256"] for r in candidates}) == 3
        for c in candidates:
            pixels = c["pixels"]
            assert pixels["status"] == "passed", pixels
            assert pixels["width_px"] > 0 and pixels["height_px"] > 0
            assert pixels["fonts"] and all(
                f["sha256"] and f["license_metadata"] != "unavailable"
                for f in pixels["fonts"]
            )
            assert (tmp_path / "actual" / c["id"] / "figure.png").is_file()
            assert (tmp_path / "actual" / c["id"] / "figure-gray.png").is_file()
            assert c["independent_human"] == "pending"
    exact = next(r for r in report["records"] if r["id"] == "exact-single")
    assert all(v == "passed" for v in exact["mechanical"].values())
    stress = next(r for r in report["records"] if r["task_id"] == "stress")
    assert stress["mechanical"]["minimum_font"] == "failed"
    assert all(n["detector_status"] == "passed" for n in report["negative_cases"])
    missing = next(n for n in report["negative_cases"] if n["id"] == "glyph_missing")
    assert missing["pixels"]["font_probe_unknown_glyphs"] > 0
    pending = json.loads((tmp_path / "actual/review-pending.json").read_bytes())
    assert len(pending) == 4 and all(
        r["reviewer"] is None and r["decision"] is None for r in pending
    )


def test_retained_actual_evidence_hashes_and_dimensions():
    import hashlib
    import struct

    evidence = EXAMPLE / "evidence"
    report = json.loads((evidence / "report.json").read_bytes())
    tasks, digest = benchmark.load_tasks()
    assert report["task_sha256"] == digest
    for record in report["records"]:
        folder = evidence / record["id"]
        assert (
            hashlib.sha256((folder / "ir.json").read_bytes()).hexdigest()
            == record["ir_sha256"]
        )
        assert (
            hashlib.sha256((folder / "figure.svg").read_bytes()).hexdigest()
            == record["svg_sha256"]
        )
        for suffix, key in (
            (".png", "png_sha256"),
            ("-gray.png", "grayscale_sha256"),
            (".pdf", "pdf_sha256"),
        ):
            assert (
                hashlib.sha256((folder / ("figure" + suffix)).read_bytes()).hexdigest()
                == record["pixels"][key]
            )
        raw = (folder / "figure.png").read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", raw[16:24]) == (
            record["pixels"]["width_px"],
            record["pixels"]["height_px"],
        )
        assert record["review_binding_sha256"] == benchmark.review_binding(record)
    assert (
        report["human_acceptance"] == "pending"
        and report["publication_visual_pass"] is False
    )
    # Retained canonical history is replayable without treating cache as evidence.
    from arw.kernel.ledger.journal import replay_run
    from arw_research_artifact.service import ResearchArtifactService

    assert replay_run(evidence / "run").recovery_health == "healthy"
    assert (
        ResearchArtifactService().inspect("figure.exact", run_root=evidence / "run")[
            "status"
        ]
        == "accepted"
    )
    for fault in report["negative_cases"]:
        folder = evidence / "negative"
        assert (
            hashlib.sha256((folder / (fault["id"] + ".svg")).read_bytes()).hexdigest()
            == fault["svg_sha256"]
        )
        assert (
            hashlib.sha256((folder / (fault["id"] + ".png")).read_bytes()).hexdigest()
            == fault["pixels"]["png_sha256"]
        )
        assert fault["detector_status"] == "passed"


def test_reference_detector_uses_geometry_direction_and_identity():
    import xml.etree.ElementTree as ET

    expected = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle id="value.one" cx="10" cy="20" r="4" fill="#000000"/><g id="edge.one"><path marker-end="url(#arrow)"/></g><g id="object.one"/></svg>'
    )
    actual = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle id="value.one" cx="10" cy="50" r="4" fill="#ff0000"/><g id="edge.one"><path marker-start="url(#arrow)"/></g></svg>'
    )
    delta = benchmark.reference_differences(expected, actual)
    assert delta["missing_ids"] == ["object.one"]
    assert delta["numeric_mark_positions"] == ["value.one"]
    assert delta["series_colors"] == ["value.one"]
    assert delta["edge_directions"] == ["edge.one"]
    assert delta["viewport_changed"] is True
    assert benchmark.exact_value_differences(
        [{"plot_value_id": "one", "exact": {"numerator": 1, "denominator": 3}}],
        [{"plot_value_id": "one", "exact": {"numerator": 2, "denominator": 3}}],
    ) == ["one"]
