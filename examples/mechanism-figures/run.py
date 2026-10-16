#!/usr/bin/env python3
"""Run the frozen public mechanism tasks against the real parent-owned journal."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.accepted_refs import ResolutionContext
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.mechanism_figure import MechanismFacts
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    InitRunRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.research_artifact import ResearchBinding
from arw_research_artifact.mechanism import MechanismRenderer, render_mechanism
from arw_research_artifact.mechanism_review import advisory_binding, inspect_mechanism
from arw_research_artifact.service import ResearchArtifactService

HERE = Path(__file__).resolve().parent
NS = "{http://www.w3.org/2000/svg}"


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_tasks():
    raw = (HERE / "tasks.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != (HERE / "tasks.sha256").read_text().strip():
        raise ValueError("mechanism_task_freeze_changed")
    return json.loads(raw)


def request(root, number):
    state = replay_run(root)
    return RuntimeCommandRequest.model_validate(
        dict(
            schema_version="1.0.0",
            run_id=state.run_id,
            expected_revision=state.revision,
            occurred_at="2026-10-16T04:00:00Z",
            actor_id="parent.mechanism-example",
            actor_role="parent_control_plane",
            event_id="evt-" + str(uuid.UUID(int=number, version=4)),
            command_id="cmd-" + str(uuid.UUID(int=number, version=4)),
        )
    )


def setup(output):
    tasks = load_tasks()
    root = output / "run"
    root.mkdir()
    (root / "source.json").write_bytes(canonical_json_bytes(tasks))
    initialize_run(
        root,
        InitRunRequest.model_validate(
            dict(
                schema_version="1.0.0",
                run_id="run-00000000-0000-4000-8000-000000000162",
                occurred_at="2026-10-16T04:00:00Z",
                immutable_input=dict(
                    path="source.json",
                    sha256=sha256_hex((root / "source.json").read_bytes()),
                ),
                workflow_family="academic-pipeline",
                workflow_mode="inline-role-prompts",
                workflow_definition_id=CORE_WORKFLOW.definition_id,
                workflow_definition_sha256=CORE_WORKFLOW.sha256,
                journal_layout="segmented-v1",
                capabilities=["canonical-journal"],
                event_id="evt-00000000-0000-4000-8000-000000000001",
                command_id="cmd-00000000-0000-4000-8000-000000000001",
                actor_id="parent.mechanism-example",
            )
        ),
    )
    result = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                **request(root, 2).model_dump(mode="json"),
                "artifact_id": "source.mechanisms",
                "artifact_kind": "public-synthetic-evidence",
                "media_type": "application/json",
                "content_path": "source.json",
                "content_sha256": sha256_hex((root / "source.json").read_bytes()),
                "base_revision": 1,
                "consumed_sha256": [],
            }
        )
    )
    if not result.accepted:
        raise RuntimeError("mechanism_source_admission_failed")
    event = result.event
    binding = ResearchBinding(
        binding_id="binding.mechanism",
        artifact_id="source.mechanisms",
        sha256=event.payload.artifact_sha256,
        ledger_event_id=event.event_id,
        ledger_event_sha256=event.event_sha256,
        json_pointer="",
    )
    return root, tasks, binding


def build_ir(service, root, task, index, binding):
    return service.build(
        {
            **task["layout"],
            "artifact_kind": "mechanism_figure",
            "artifact_id": "mechanism." + task["id"],
            "revision": 1,
            "source": binding.model_copy(
                update={"json_pointer": f"/tasks/{index}/facts"}
            ).model_dump(mode="json"),
            "source_sha256": sha256_hex(canonical_json_bytes(task["facts"])),
            "renderer_hints": MechanismRenderer().identity.model_dump(mode="json"),
            "publication_critical": False,
            "validation_policy": dict(
                schema="REQUIRED",
                provenance="REQUIRED",
                semantic="REQUIRED",
                render="REQUIRED",
                visual="OPTIONAL",
            ),
        },
        run_root=root,
    )


def injected(svg, fault):
    root = ET.fromstring(svg)
    if fault == "missing_component":
        root.remove(next(e for e in root if e.get("id", "").startswith("component.")))
    elif fault == "reverse_arrow":
        e = next(e for e in root if e.get("id", "").startswith("edge."))
        e.set("points", " ".join(reversed(e.get("points").split())))
    elif fault == "missing_stop":
        changed = False
        for parent in root.iter():
            for e in list(parent):
                if e.tag == NS + "text" and "stop:" in "".join(e.itertext()):
                    parent.remove(e)
                    changed = True
        if not changed:
            raise ValueError("fault_not_applicable:" + fault)
    elif fault in {
        "token_mapping",
        "freeze_state",
        "missing_step",
        "stop_role_label",
        "fabricated_value",
        "object_identity",
    }:
        needle, substitute = {
            "token_mapping": ("e_red", "e_blue"),
            "freeze_state": ("parameters: frozen", "parameters: trainable"),
            "missing_step": ("Lookup X=[E(red), E(blue)].", "Step omitted."),
            "stop_role_label": ("stop:", "removed:"),
            "fabricated_value": ("y=[1,1]", "y=[999,999]"),
            "object_identity": ("utterance@sum", "unrelated@sum"),
        }[fault]
        changed = False
        for e in root.iter(NS + "tspan"):
            if needle in (e.text or ""):
                e.text = e.text.replace(needle, substitute)
                changed = True
                break
        if not changed:
            raise ValueError("fault_not_applicable:" + fault)
    elif fault == "small_text":
        next(root.iter(NS + "text")).set("font-size", "2")
    else:
        raise ValueError("unknown_fault")
    return ET.tostring(root, encoding="utf-8") + b"\n"


def run(output, *, raster_python=None):
    start = time.monotonic()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root, tasks, binding = setup(output)
    service = ResearchArtifactService()
    context = ResolutionContext("mechanism.public", (root,))
    report = {
        "tasks_sha256": (HERE / "tasks.sha256").read_text().strip(),
        "scope": "Issue 162 milestone 1; manual layouts and structural checks",
        "tasks": [],
        "human_status": "human_pending",
        "publication_visual_pass": False,
        "explanation_search": "deferred",
        "drawio": "unsupported",
    }
    review_inputs = []
    for i, task in enumerate(tasks["tasks"]):
        facts = MechanismFacts.model_validate_json(json.dumps(task["facts"]))
        ir = build_ir(service, root, task, i, binding)
        raw, svg = render_mechanism(
            service, ir, run_root=root, resolution_context=context
        )
        name = task["id"]
        (output / (name + ".svg")).write_bytes(svg)
        (output / (name + ".ir.json")).write_bytes(raw)
        positive = inspect_mechanism(facts, ir, svg)
        accepted = service.qualify(
            ir,
            run_root=root,
            request=request(root, 100 + i),
            resolution_context=context,
        )
        reproduction = service.reproduce(
            ir.artifact_id, run_root=root, resolution_context=context
        )
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
            critical,
            run_root=root,
            request=request(root, 200 + i),
            resolution_context=context,
        )
        item = {
            "id": name,
            "source_answer_comparison": positive,
            "exploratory_accepted": accepted["accepted"],
            "reproduction": reproduction,
            "publication_without_review": blocked,
            "ir_sha256": sha256_hex(raw),
            "svg_sha256": sha256_hex(svg),
            "raster": {
                "status": "unavailable",
                "reason": "optional raster Python not supplied",
            },
            "faults": [],
        }
        if raster_python:
            result = subprocess.run(
                [
                    raster_python,
                    str(HERE.parent / "figure-benchmark/rasterize.py"),
                    str(output / (name + ".svg")),
                    str(output / (name + ".png")),
                    str(ir.width_mm),
                    str(ir.height_mm),
                    "150",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                item["raster"] = json.loads(result.stdout)
            else:
                item["raster"] = {
                    "status": "unavailable",
                    "reason": result.stderr[-1000:],
                }
        fault_names = ["missing_component", "reverse_arrow", "small_text"]
        if i == 0:
            fault_names += [
                "token_mapping",
                "freeze_state",
                "missing_step",
                "fabricated_value",
                "object_identity",
            ]
        if i == 1:
            fault_names += ["stop_role_label", "missing_stop"]
        for fault in fault_names:
            altered = injected(svg, fault)
            path = output / (name + ".negative." + fault + ".svg")
            path.write_bytes(altered)
            result = inspect_mechanism(facts, ir, altered)
            item["faults"].append(
                {
                    "fault": fault,
                    "svg": path.name,
                    "sha256": sha256_hex(altered),
                    "detected": result["status"] == "changes_required",
                    "findings": result["findings"],
                }
            )
        review_inputs.append(
            {
                "id": name,
                "source_answer": task["facts"],
                "profile": task["layout"]["profile"],
                "ir": name + ".ir.json",
                "svg": name + ".svg",
                "png": name + ".png",
                "source_sha256": ir.source_sha256,
                "ir_sha256": sha256_hex(raw),
                "svg_sha256": sha256_hex(svg),
                "raster": item["raster"],
            }
        )
        if item["raster"].get("status") == "passed":
            review_inputs[-1]["exact_binding"] = advisory_binding(
                source=task["facts"],
                ir=raw,
                svg=svg,
                png=(output / (name + ".png")).read_bytes(),
                raster=item["raster"],
            ).model_dump(mode="json")
        report["tasks"].append(item)
    report["elapsed_seconds"] = round(time.monotonic() - start, 3)
    report["automatic_model_calls"] = 0
    report["structural_counts"] = {
        "normal": len(report["tasks"]),
        "normal_flagged": sum(
            t["source_answer_comparison"]["status"] != "reviewed"
            for t in report["tasks"]
        ),
        "injected": sum(len(t["faults"]) for t in report["tasks"]),
        "detected": sum(f["detected"] for t in report["tasks"] for f in t["faults"]),
    }
    write_json(output / "report.json", report)
    write_json(
        output / "reviewer-input.json",
        {
            "schema_version": "arw.mechanism-advisory-input.v1",
            "instructions": "Read actual PNG pixels and frozen answers. No producer scores or selection conclusions are provided. Diagnose differences; do not edit or approve publication.",
            "tasks": review_inputs,
            "human_status": "human_pending",
        },
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--raster-python")
    args = parser.parse_args()
    result = run(args.output, raster_python=args.raster_python)
    print(
        json.dumps(
            {
                "counts": result["structural_counts"],
                "human_status": result["human_status"],
            }
        )
    )
