"""Real mechanism source admission; no simulated publication-quality approval."""

import copy
import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.accepted_refs import ResolutionContext, RunPrefix
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.mechanism_figure import (
    MechanismAdvisoryReview,
    MechanismFacts,
    mechanism_figure_schema_documents,
)
from arw_research_artifact.mechanism import render_mechanism
from arw_research_artifact.mechanism_review import advisory_binding, inspect_mechanism
from arw_research_artifact.service import ResearchArtifactService
from arw_research_artifact.validation import IRValidationFault

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "public_mechanisms", ROOT / "examples/mechanism-figures/run.py"
)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def prepared(tmp_path, index=0):
    root, tasks, binding = example.setup(tmp_path)
    task = tasks["tasks"][index]
    service = ResearchArtifactService()
    ir = example.build_ir(service, root, task, index, binding)
    facts = MechanismFacts.model_validate_json(json.dumps(task["facts"]))
    return root, service, ir, facts


@pytest.mark.parametrize("index", range(3))
def test_actual_admission_render_replay_and_publication_block(tmp_path, index):
    root, service, ir, facts = prepared(tmp_path, index)
    raw, svg = render_mechanism(service, ir, run_root=root)
    assert (raw, svg) == render_mechanism(service, ir, run_root=root)
    assert inspect_mechanism(facts, ir, svg)["findings"] == []
    outcome = service.qualify(ir, run_root=root, request=example.request(root, 100))
    assert outcome["accepted"]
    assert service.inspect(ir.artifact_id, run_root=root)["renderer_available"]
    assert service.reproduce(ir.artifact_id, run_root=root)["status"] == "reproduced"
    critical = ir.model_copy(
        update={
            "artifact_id": ir.artifact_id + ".publication",
            "publication_critical": True,
            "validation_policy": ir.validation_policy.model_copy(
                update={"visual": "REQUIRED"}
            ),
        }
    )
    blocked = service.qualify(
        critical, run_root=root, request=example.request(root, 200)
    )
    assert (
        not blocked["accepted"]
        and blocked["receipt"]["validation"]["visual"] == "UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_component",
        "reverse_arrow",
        "token_mapping",
        "freeze_state",
        "missing_step",
        "fabricated_value",
        "object_identity",
        "small_text",
    ],
)
def test_source_answer_detects_fault_without_generated_baseline(tmp_path, fault):
    root, service, ir, facts = prepared(tmp_path)
    _, svg = render_mechanism(service, ir, run_root=root)
    altered = example.injected(svg, fault)
    result = inspect_mechanism(facts, ir, altered)
    assert result["status"] == "changes_required" and result["findings"]
    assert not result["publication_visual_pass"]


def test_stop_condition_is_not_optional(tmp_path):
    root, service, ir, facts = prepared(tmp_path, 1)
    _, svg = render_mechanism(service, ir, run_root=root)
    missing = example.injected(svg, "missing_stop")
    assert inspect_mechanism(facts, ir, missing)["findings"]
    content = ET.fromstring(missing).find(".//*[@id='content.decide']")
    assert facts.components[2].stop_condition.replace(" ", "") not in "".join(
        content.itertext()
    ).replace(" ", "")
    bad = facts.model_dump(mode="json")
    bad["components"][2]["stop_condition"] = None
    with pytest.raises(ValidationError, match="mechanism_condition_and_stop_required"):
        MechanismFacts.model_validate_json(json.dumps(bad))


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("type", "mechanism_incompatible_ports"),
        ("object", "mechanism_object_identity_break"),
        ("phase", "mechanism_inference_parameter_update_unsupported"),
        ("step", "at least 1 item"),
        ("extra", "Extra inputs"),
    ],
)
def test_strict_scientific_contract(tmp_path, mutation, reason):
    _, _, _, facts = prepared(tmp_path)
    bad = facts.model_dump(mode="json")
    if mutation == "type":
        bad["components"][1]["ports"][0]["value_type"] = "other"
    elif mutation == "object":
        bad["components"][1]["ports"][0]["object_id"] = "other"
    elif mutation == "phase":
        bad["components"][1]["parameters"] = "trainable"
    elif mutation == "step":
        bad["components"][1]["steps"] = []
    else:
        bad["guessed_attention_matrix"] = [0.2, 0.8]
    with pytest.raises(ValidationError, match=reason):
        MechanismFacts.model_validate_json(json.dumps(bad))


def test_digest_source_tamper_and_historical_prefix(tmp_path):
    root, service, ir, _ = prepared(tmp_path)
    replay = replay_run(root)
    # A prefix before source acceptance must not resolve later accepted facts.
    first = replay.events[0]
    context = ResolutionContext(
        "mechanism.public",
        (root,),
        run_prefixes=(RunPrefix(replay.run_id, 1, first.event_sha256),),
    )
    with pytest.raises(IRValidationFault, match="mechanism_source_unresolved"):
        render_mechanism(service, ir, run_root=root, resolution_context=context)
    with pytest.raises(IRValidationFault, match="mechanism_source_digest_mismatch"):
        render_mechanism(
            service, ir.model_copy(update={"source_sha256": "f" * 64}), run_root=root
        )
    (root / "source.json").write_bytes(b"{}\n")
    with pytest.raises(IRValidationFault, match="mechanism_source_unresolved"):
        render_mechanism(service, ir, run_root=root)


def test_schema_projection_and_frozen_task_answers(tmp_path):
    root, _, ir, facts = prepared(tmp_path)
    for name, schema in mechanism_figure_schema_documents().items():
        assert json.loads((ROOT / "schemas/v1" / name).read_text()) == schema
    jsonschema.validate(
        ir.model_dump(mode="json"),
        mechanism_figure_schema_documents()["mechanism-figure-ir.schema.json"],
    )
    jsonschema.validate(
        facts.model_dump(mode="json"),
        mechanism_figure_schema_documents()["mechanism-facts.schema.json"],
    )
    assert (
        sha256_hex(
            canonical_json_bytes(facts.model_dump(mode="json", exclude_unset=True))
        )
        != "0" * 64
    )
    assert example.load_tasks()["license"] == "MIT"


@pytest.mark.parametrize(
    "field", ["source", "ir", "svg", "png", "fonts", "environment"]
)
def test_advisory_binding_expires_on_every_relevant_input(field):
    options = dict(
        source={"source": "public"},
        ir=b"IR",
        svg=b"SVG",
        png=b"PNG",
        raster={"fonts": [{"sha256": "f" * 64}], "rasterizer": {"name": "local"}},
    )
    before = advisory_binding(**options)
    after = copy.deepcopy(options)
    if field == "fonts":
        after["raster"]["fonts"][0]["sha256"] = "a" * 64
    elif field == "environment":
        after["raster"]["rasterizer"]["name"] = "changed"
    elif field == "source":
        after[field]["source"] = "changed"
    else:
        after[field] += b"changed"
    assert before != advisory_binding(**after)


def test_no_rasterizer_is_unavailable_not_visual_pass(tmp_path):
    report = example.run(tmp_path / "packet")
    assert report["structural_counts"] == dict(
        normal=3, normal_flagged=0, injected=16, detected=16
    )
    assert all(t["raster"]["status"] == "unavailable" for t in report["tasks"])
    assert (
        report["human_status"] == "human_pending"
        and not report["publication_visual_pass"]
    )


def test_actual_cli_dispatch_preserves_renderer_bytes(tmp_path):
    root, service, ir, _ = prepared(tmp_path)
    (root / "mechanism.json").write_bytes(
        canonical_json_bytes(ir.model_dump(mode="json"))
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "artifact",
            "render",
            "--run-root",
            str(root),
            "--input",
            "mechanism.json",
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "candidate"
    _, expected = render_mechanism(service, ir, run_root=root)
    candidates = list(
        (root / ".arw/artifacts/candidates" / ir.artifact_id).glob("*/figure.svg")
    )
    assert len(candidates) == 1 and candidates[0].read_bytes() == expected


@pytest.mark.parametrize("bad", ["approval", "no_pixels", "same_role"])
def test_advisory_contract_cannot_become_approval(bad):
    binding = advisory_binding(
        source={},
        ir=b"ir",
        svg=b"svg",
        png=b"png",
        raster={"fonts": [], "rasterizer": {}},
    )
    payload = dict(
        status="reviewed",
        binding=binding.model_dump(mode="json"),
        producer_id="producer.figure",
        reviewer_id="reviewer.figure",
        pixels_read=True,
        findings=[],
        reader_retelling={
            k: "source-defined"
            for k in ("input", "transformation", "innovation", "output", "feedback")
        },
        reference_comparisons=[],
        elapsed_seconds=1.0,
        cost_note="Actual token metering unavailable.",
    )
    assert (
        MechanismAdvisoryReview.model_validate_json(json.dumps(payload)).human_status
        == "human_pending"
    )
    if bad == "approval":
        payload["publication_visual_pass"] = True
    elif bad == "no_pixels":
        payload["pixels_read"] = False
    else:
        payload["reviewer_id"] = payload["producer_id"]
    with pytest.raises(ValidationError):
        MechanismAdvisoryReview.model_validate_json(json.dumps(payload))


def test_retained_actual_packet_is_complete_and_bound():
    evidence = ROOT / "examples/mechanism-figures/evidence"
    manifest = json.loads((evidence / "manifest.json").read_text())
    for item in manifest["files"]:
        assert sha256_hex((evidence / item["path"]).read_bytes()) == item["sha256"]
    for round_name in ("round1", "round2"):
        assert replay_run(evidence / round_name / "run").recovery_health == "healthy"
    packet = json.loads((evidence / "round2/reviewer-input.json").read_text())
    for t in packet["tasks"]:
        actual = advisory_binding(
            source=t["source_answer"],
            ir=(evidence / "round2" / t["ir"]).read_bytes(),
            svg=(evidence / "round2" / t["svg"]).read_bytes(),
            png=(evidence / "round2" / t["png"]).read_bytes(),
            raster=t["raster"],
        )
        assert actual.model_dump(mode="json") == t["exact_binding"]
    summary = json.loads((evidence / "summary.json").read_text())
    assert summary["human_status"] == "human_pending"
    assert not summary["publication_visual_pass"]
