"""Executable evidence-to-figure workflow and qualification failure boundaries."""

import json
import subprocess
import sys

import pytest
from arw_research_artifact.service import ResearchArtifactService
from arw_research_artifact.validation import IRValidationFault
from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.research_records import BodyUnavailable, ResearchRecordError
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_artifact import ResearchArtifactIR

from .test_precise_source_locators import accept, seed


def request(root, number=100):
    replay = replay_run(root)
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": replay.run_id,
            "occurred_at": "2026-09-08T00:02:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
        }
    )


def prepared(tmp_path):
    root, _ = seed(tmp_path)
    evidence = {
        "nodes": [
            {
                "id": "method.collect",
                "kind": "method",
                "label": "收集证据 / Collect evidence",
                "confidence": 80,
            },
            {
                "id": "method.analyze",
                "kind": "method",
                "label": "Analyze evidence",
                "confidence": 70,
            },
        ],
        "edges": [
            {
                "source": "method.collect",
                "target": "method.analyze",
                "relation": "precedes",
                "label": "precedes",
            }
        ],
        "caption": "Figure 1. Evidence analysis workflow.",
        "manuscript": "Figure 1 shows the workflow; accuracy is 92% in the retained experiment.",
    }
    (root / "evidence.json").write_bytes(canonical_json_bytes(evidence))
    assert accept(
        root, "artifact.evidence", "evidence.json", 3, kind="research-evidence"
    ).accepted
    event = replay_run(root).events[-1]
    pointers = ["/nodes/0", "/nodes/1", "/edges/0", "/caption", "/manuscript"]
    bindings = [
        {
            "binding_id": f"binding.{i}",
            "artifact_id": "artifact.evidence",
            "sha256": event.payload.artifact_sha256,
            "ledger_event_id": event.event_id,
            "ledger_event_sha256": event.event_sha256,
            "json_pointer": p,
        }
        for i, p in enumerate(pointers)
    ]
    spec = {
        "schema_version": "arw.research-artifact-ir.v1",
        "artifact_id": "figure.workflow",
        "artifact_kind": "methodology_figure",
        "title": "Evidence workflow",
        "author_target": "Explain how retained research evidence is analyzed.",
        "publication_critical": False,
        "research_bindings": bindings,
        "nodes": [
            {**n, "binding_id": f"binding.{i}"} for i, n in enumerate(evidence["nodes"])
        ],
        "edges": [
            {"id": "edge.order", **evidence["edges"][0], "binding_id": "binding.2"}
        ],
        "groups": [],
        "annotations": [
            {
                "id": "caption.figure",
                "role": "caption",
                "text": evidence["caption"],
                "binding_id": "binding.3",
            },
            {
                "id": "manuscript.figure",
                "role": "manuscript_reference",
                "text": evidence["manuscript"],
                "binding_id": "binding.4",
            },
        ],
        "presentation": {
            "theme": "blue",
            "direction": "top_to_bottom",
            "font_family": "Noto Sans CJK SC, sans-serif",
        },
        "validation_policy": {
            "schema": "REQUIRED",
            "provenance": "REQUIRED",
            "semantic": "REQUIRED",
            "render": "REQUIRED",
            "visual": "OPTIONAL",
        },
        "supersedes": None,
    }
    service = ResearchArtifactService()
    return root, service, service.build(spec, run_root=root)


def test_evidence_ir_svg_receipt_canonical_acceptance_and_retry(tmp_path):
    root, service, ir = prepared(tmp_path)
    req = request(root)
    result = service.qualify(ir, run_root=root, request=req)
    assert (
        result["accepted"]
        and result["receipt"]["validation"]["visual"] == "OPTIONAL_SKIPPED"
    )
    events = replay_run(root).events
    assert [e.event_type for e in events[-4:]] == [
        "research_artifact_ir_frozen",
        "research_artifact_rendered",
        "research_artifact_validated",
        "research_artifact_accepted",
    ]
    assert all(e.schema_version == "1.1.0" for e in events[-4:])
    assert result["binding"]["receipt_sha256"] == sha256_hex(
        canonical_json_bytes(result["receipt"])
    )
    assert (
        events[-1].event_sha256 not in canonical_json_bytes(result["receipt"]).decode()
    )
    assert service.reproduce(ir.artifact_id, run_root=root)["status"] == "reproduced"
    assert service.qualify(ir, run_root=root, request=req)["idempotent"]
    assert len(replay_run(root).events) == len(events)
    assert service.doctor(run_root=root)["status"] == "PASS"


@pytest.mark.parametrize(
    "change", ["value", "causality", "confidence", "caption", "manuscript"]
)
def test_semantic_drift_cannot_qualify_despite_valid_svg(tmp_path, change):
    root, service, ir = prepared(tmp_path)
    value = ir.model_dump(mode="json")
    if change == "value":
        value["nodes"][0]["label"] = "Accuracy is 99%"
    elif change == "causality":
        value["edges"][0]["relation"] = "causes"
    elif change == "confidence":
        value["nodes"][0]["confidence"] = 100
    elif change == "caption":
        value["annotations"][0]["text"] = "Figure 1 proves causality."
    else:
        value["annotations"][1]["text"] = "Figure 1 shows accuracy of 99%."
    changed = ResearchArtifactIR.model_validate_json(json.dumps(value))
    before = replay_run(root).last_event_sha256
    result = service.qualify(changed, run_root=root, request=request(root))
    assert not result["accepted"]
    assert result["receipt"]["validation"]["render"] == "PASS"
    assert result["receipt"]["validation"]["semantic"] == "FAIL"
    assert replay_run(root).last_event_sha256 == before


def test_publication_visual_unavailable_is_not_pass(tmp_path):
    root, service, ir = prepared(tmp_path)
    value = ir.model_dump(mode="json")
    value["publication_critical"] = True
    value["validation_policy"]["visual"] = "REQUIRED"
    ir = ResearchArtifactIR.model_validate_json(json.dumps(value))
    result = service.qualify(ir, run_root=root, request=request(root))
    assert result["receipt"]["validation"]["visual"] == "UNAVAILABLE"
    assert not result["accepted"]


def test_accepted_visual_review_is_bound_to_exact_output(tmp_path):
    root, service, ir = prepared(tmp_path)
    value = ir.model_dump(mode="json")
    value["publication_critical"] = True
    value["validation_policy"]["visual"] = "REQUIRED"
    ir = ResearchArtifactIR.model_validate_json(json.dumps(value))
    review = {
        "schema_version": "arw.visual-review.v1",
        "ir_sha256": sha256_hex(canonical_json_bytes(ir.model_dump(mode="json"))),
        "output_sha256": sha256_hex(service.renderer.render(ir)),
        "status": "PASS",
        "reviewer": {
            "tool_id": "simulated.fixture.review",
            "version": "1",
            "identity_digest": "a" * 64,
        },
    }
    (root / "review.json").write_bytes(canonical_json_bytes(review))
    assert accept(
        root, "review.figure", "review.json", 4, kind="visual-review"
    ).accepted
    result = service.qualify(
        ir, run_root=root, request=request(root), visual_review_id="review.figure"
    )
    assert result["accepted"]
    assert result["receipt"]["visual_reviewer"]["tool_id"] == "simulated.fixture.review"


def test_renderer_pin_substitution_blocks_acceptance(tmp_path):
    root, service, ir = prepared(tmp_path)
    ir = ir.model_copy(
        update={
            "renderer_hints": ir.renderer_hints.model_copy(
                update={"identity_digest": "f" * 64}
            )
        }
    )
    with pytest.raises(IRValidationFault, match="pinned_renderer_unavailable"):
        service.qualify(ir, run_root=root, request=request(root))
    assert not (root / ".arw/artifacts/accepted").exists()


@pytest.mark.parametrize("field", ["unknown_kind", "semantic_leak", "missing_binding"])
def test_ir_structure_rejects_unknown_or_mixed_forms(tmp_path, field):
    root, service, ir = prepared(tmp_path)
    value = ir.model_dump(mode="json")
    if field == "unknown_kind":
        value["nodes"][0]["kind"] = "unrecognized"
    elif field == "semantic_leak":
        value["presentation"]["source_digest"] = "a" * 64
    else:
        value["nodes"][0]["binding_id"] = "binding.absent"
    with pytest.raises(ValidationError):
        ResearchArtifactIR.model_validate_json(json.dumps(value))


def test_supersession_keeps_prior_bytes(tmp_path):
    root, service, ir = prepared(tmp_path)
    service.qualify(ir, run_root=root, request=request(root))
    before = (root / ".arw/artifacts/accepted/figure.workflow/figure.svg").read_bytes()
    successor = ir.model_copy(
        update={"artifact_id": "figure.workflow-next", "supersedes": ir.artifact_id}
    )
    assert service.qualify(successor, run_root=root, request=request(root, 101))[
        "accepted"
    ]
    assert replay_run(root).events[-1].event_type == "research_artifact_superseded"
    assert (
        root / ".arw/artifacts/accepted/figure.workflow/figure.svg"
    ).read_bytes() == before
    assert (
        service.inspect("figure.workflow-next", run_root=root)["supersedes"]
        == ir.artifact_id
    )


@pytest.mark.parametrize("boundary", ["files_durable", "event_durable"])
def test_interrupted_qualification_retries_without_duplicate_acceptance(
    tmp_path, boundary
):
    root, service, ir = prepared(tmp_path)
    req = request(root)

    def crash(point):
        if point == boundary:
            raise SystemExit("injected process boundary")

    with pytest.raises(SystemExit):
        ResearchArtifactService(boundary=crash).qualify(ir, run_root=root, request=req)
    if boundary == "files_durable":
        with pytest.raises(ResearchRecordError, match="artifact_not_accepted"):
            service.inspect(ir.artifact_id, run_root=root)
    assert service.qualify(ir, run_root=root, request=req)["accepted"]
    assert (
        sum(
            e.event_type == "research_artifact_accepted"
            for e in replay_run(root).events
        )
        == 1
    )


def test_cli_pipeline_and_replay_without_extension_import(tmp_path):
    root, service, ir = prepared(tmp_path)
    (root / "ir.json").write_bytes(canonical_json_bytes(ir.model_dump(mode="json")))
    req = request(root)
    (root / "request.json").write_bytes(
        canonical_json_bytes(req.model_dump(mode="json"))
    )
    command = [
        sys.executable,
        "-m",
        "arw.cli",
        "artifact",
        "qualify",
        "--run-root",
        str(root),
        "--input",
        "ir.json",
        "--request",
        str(root / "request.json"),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    inspect = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "artifact",
            "inspect",
            ir.artifact_id,
            "--run-root",
            str(root),
        ],
        text=True,
        capture_output=True,
    )
    assert inspect.returncode == 0, inspect.stderr
    code = """import sys
class Block:
 def find_spec(self,fullname,*args):
  if fullname.startswith("arw_research_artifact"):raise RuntimeError("extension disabled")
sys.meta_path.insert(0,Block())
from pathlib import Path
from arw.kernel.ledger.journal import replay_run
print(replay_run(Path(sys.argv[1])).revision)
"""
    replay = subprocess.run(
        [sys.executable, "-c", code, str(root)], text=True, capture_output=True
    )
    assert replay.returncode == 0, replay.stderr


def test_authorized_purge_preserves_chain_and_refuses_reproduction(tmp_path):
    root, service, ir = prepared(tmp_path)
    service.qualify(ir, run_root=root, request=request(root))
    value = {
        "action": "purge_research_artifact",
        "artifact_id": ir.artifact_id,
        "reason": "fixture retention authorization",
    }
    (root / "retention.json").write_bytes(canonical_json_bytes(value))
    assert accept(
        root, "retention.figure", "retention.json", 110, kind="retention-authorization"
    ).accepted
    before = replay_run(root).last_event_sha256
    with pytest.raises(ResearchRecordError):
        service.purge(
            ir.artifact_id, run_root=root, authorization_artifact_id="retention.figure"
        )
    service.purge(
        ir.artifact_id,
        run_root=root,
        authorization_artifact_id="retention.figure",
        authorized=True,
    )
    assert replay_run(root).last_event_sha256 == before
    with pytest.raises(BodyUnavailable):
        service.reproduce(ir.artifact_id, run_root=root)


def test_secret_shape_rejected_before_candidate_bytes(tmp_path):
    root, service, ir = prepared(tmp_path)
    ir = ir.model_copy(
        update={"author_target": "api_key=sk-abcdefghijklmnopqrstuvwxyz012345"}
    )
    with pytest.raises(ValueError, match="secret-shaped"):
        service.qualify(ir, run_root=root, request=request(root))
    assert not (root / ".arw/artifacts").exists()


@pytest.mark.parametrize(
    "point", ["files_durable", "research_artifact_rendered", "event_durable"]
)
def test_sigkill_recovery_preserves_single_acceptance(tmp_path, point):
    root, service, ir = prepared(tmp_path)
    req = request(root)
    (root / "ir.json").write_bytes(canonical_json_bytes(ir.model_dump(mode="json")))
    (root / "request.json").write_bytes(
        canonical_json_bytes(req.model_dump(mode="json"))
    )
    code = """import os,signal,sys
from pathlib import Path
from arw.kernel.state.models import RuntimeCommandRequest
from arw.kernel.state.research_artifact import ResearchArtifactIR
from arw_research_artifact.service import ResearchArtifactService
root=Path(sys.argv[1])
def stop(point):
 if point==sys.argv[2]:os.kill(os.getpid(),signal.SIGKILL)
ResearchArtifactService(boundary=stop).qualify(ResearchArtifactIR.model_validate_json((root/'ir.json').read_bytes()),run_root=root,request=RuntimeCommandRequest.model_validate_json((root/'request.json').read_bytes()))
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(root), point], capture_output=True
    )
    assert child.returncode == -9, child.stderr
    assert service.qualify(ir, run_root=root, request=req)["accepted"]
    assert (
        sum(
            e.event_type == "research_artifact_accepted"
            for e in replay_run(root).events
        )
        == 1
    )
    assert service.reproduce(ir.artifact_id, run_root=root)["status"] == "reproduced"


def test_concurrent_identical_qualification_serializes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    root, service, ir = prepared(tmp_path)
    req = request(root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda _: service.qualify(ir, run_root=root, request=req), range(2)
            )
        )
    assert all(o["accepted"] for o in outcomes)
    assert sum(not o["idempotent"] for o in outcomes) == 1
    assert (
        sum(
            e.event_type == "research_artifact_accepted"
            for e in replay_run(root).events
        )
        == 1
    )


def test_missing_binding_is_reported_without_doctor_repair(tmp_path):
    root, service, ir = prepared(tmp_path)
    req = request(root)
    service.qualify(ir, run_root=root, request=req)
    binding = root / f".arw/artifacts/accepted/{ir.artifact_id}/binding.json"
    binding.unlink()
    assert service.doctor(run_root=root)["status"] == "FAIL"
    assert not binding.exists()
    assert service.qualify(ir, run_root=root, request=req)["idempotent"]
    assert binding.is_file()


def test_worker_cannot_qualify_or_publish_files(tmp_path):
    root, service, ir = prepared(tmp_path)
    with pytest.raises(ResearchRecordError, match="only the parent"):
        service.qualify(
            ir,
            run_root=root,
            request=request(root).model_copy(update={"actor_role": "worker"}),
        )
    assert not (root / ".arw/artifacts").exists()


def test_side_effect_free_renderer_is_byte_deterministic(tmp_path):
    root, service, ir = prepared(tmp_path)
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert service.renderer.render(ir) == service.renderer.render(ir)
    assert {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("kind", ["claim", "evidence", "activity", "agent"])
def test_evidence_graph_view_projects_accepted_entity_kinds(tmp_path, kind):
    root, service, ir = prepared(tmp_path)
    evidence = json.loads((root / "evidence.json").read_bytes())
    evidence["nodes"][0]["kind"] = kind
    evidence["nodes"][0]["label"] = {
        "claim": "Observed accuracy is 92%.",
        "evidence": "Retained experiment result",
        "activity": "Measure accuracy",
        "agent": "Research operator",
    }[kind]
    (root / "evidence-next.json").write_bytes(canonical_json_bytes(evidence))
    assert accept(
        root,
        "artifact.graph-evidence",
        "evidence-next.json",
        4,
        kind="research-evidence",
    ).accepted
    event = replay_run(root).events[-1]
    spec = ir.model_dump(mode="json")
    spec["artifact_kind"] = "evidence_graph_view"
    spec["nodes"][0].update(evidence["nodes"][0])
    for binding in spec["research_bindings"]:
        binding.update(
            artifact_id="artifact.graph-evidence",
            sha256=event.payload.artifact_sha256,
            ledger_event_id=event.event_id,
            ledger_event_sha256=event.event_sha256,
        )
    graph = service.build(spec, run_root=root)
    assert service.qualify(graph, run_root=root, request=request(root))["accepted"]


def test_doctor_reports_unavailable_pinned_renderer(tmp_path):
    root, service, ir = prepared(tmp_path)
    service.qualify(ir, run_root=root, request=request(root))

    class UnavailableRenderer:
        identity = service.renderer.identity.model_copy(
            update={"identity_digest": "f" * 64}
        )

    result = ResearchArtifactService(renderer=UnavailableRenderer()).doctor(
        run_root=root
    )
    assert result["faults"] == [
        {"artifact_id": ir.artifact_id, "code": "pinned_renderer_unavailable"}
    ]


def test_unresolved_binding_fails_before_acceptance(tmp_path):
    root, service, ir = prepared(tmp_path)
    binding = ir.research_bindings[0].model_copy(
        update={"ledger_event_sha256": "f" * 64}
    )
    candidate = ir.model_copy(
        update={"research_bindings": (binding, *ir.research_bindings[1:])}
    )
    result = service.qualify(candidate, run_root=root, request=request(root))
    assert result["receipt"]["validation"]["provenance"] == "FAIL"
    assert not result["accepted"]


def test_external_table_units_uncertainty_and_citation_agree_with_figure(tmp_path):
    root,service,ir=prepared(tmp_path)
    table={'text':'Table 1: accuracy 92 ± 1 % on Dataset A [@study].'}
    (root/'table.json').write_bytes(canonical_json_bytes(table))
    assert accept(root,'artifact.table','table.json',4,kind='table').accepted
    event=replay_run(root).events[-1]
    value=ir.model_dump(mode='json')
    value['research_bindings'].append({'binding_id':'binding.table','artifact_id':'artifact.table','sha256':event.payload.artifact_sha256,'ledger_event_id':event.event_id,'ledger_event_sha256':event.event_sha256,'json_pointer':'/text'})
    value['annotations'].append({'id':'table.figure','role':'note','text':table['text'],'binding_id':'binding.table'})
    honest=ResearchArtifactIR.model_validate_json(json.dumps(value))
    assert service.qualify(honest,run_root=root,request=request(root))['accepted']
    value['artifact_id']='figure.wrong-units'
    value['annotations'][-1]['text']='Table 1: accuracy 92 ± 1 ms on Dataset A [@study].'
    candidate=ResearchArtifactIR.model_validate_json(json.dumps(value))
    result=service.qualify(candidate,run_root=root,request=request(root,101))
    assert not result['accepted'] and result['receipt']['validation']['semantic']=='FAIL'
