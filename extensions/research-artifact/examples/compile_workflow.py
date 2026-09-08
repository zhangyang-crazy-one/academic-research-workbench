"""Run: uv run python extensions/research-artifact/examples/compile_workflow.py OUTPUT

Creates a fresh, explicitly exploratory figure from accepted bilingual evidence.
No simulated visual review is used; this example is not publication qualification.
"""

import json
import sys
from pathlib import Path

from arw_research_artifact.service import ResearchArtifactService

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    InitRunRequest,
    RuntimeCommandRequest,
)


def run(output):
    root = Path(output) / "run"
    root.mkdir(parents=True, exist_ok=False)
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
                "label": "分析证据 / Analyze evidence",
                "confidence": 70,
            },
        ],
        "edge": {
            "source": "method.collect",
            "target": "method.analyze",
            "relation": "precedes",
            "label": "precedes",
        },
        "caption": "Figure 1. Evidence analysis workflow.",
        "manuscript": "Figure 1 describes the sequence of evidence collection and analysis.",
    }
    raw = canonical_json_bytes(evidence)
    (root / "evidence.json").write_bytes(raw)
    run_id = "run-00000000-0000-4000-8000-000000000080"
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": run_id,
                "occurred_at": "2026-09-08T00:00:00Z",
                "immutable_input": {"path": "evidence.json", "sha256": sha256_hex(raw)},
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000080",
                "command_id": "cmd-00000000-0000-4000-8000-000000000080",
                "actor_id": "parent.runtime",
            }
        ),
    )
    common = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "occurred_at": "2026-09-08T00:01:00Z",
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
        "expected_revision": 1,
        "event_id": "evt-00000000-0000-4000-8000-000000000081",
        "command_id": "cmd-00000000-0000-4000-8000-000000000081",
    }
    outcome = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                **common,
                "artifact_id": "evidence.workflow",
                "artifact_kind": "research-evidence",
                "media_type": "application/json",
                "content_path": "evidence.json",
                "content_sha256": sha256_hex(raw),
                "base_revision": 1,
                "consumed_sha256": [replay_run(root).last_event_sha256],
            }
        )
    )
    if not outcome.accepted:
        raise RuntimeError("source acceptance failed")
    event = outcome.event
    bindings = [
        {
            "binding_id": f"binding.{i}",
            "artifact_id": "evidence.workflow",
            "sha256": sha256_hex(raw),
            "ledger_event_id": event.event_id,
            "ledger_event_sha256": event.event_sha256,
            "json_pointer": pointer,
        }
        for i, pointer in enumerate(
            ["/nodes/0", "/nodes/1", "/edge", "/caption", "/manuscript"]
        )
    ]
    spec = {
        "schema_version": "arw.research-artifact-ir.v1",
        "artifact_id": "figure.workflow",
        "artifact_kind": "methodology_figure",
        "title": "Research evidence workflow / 研究证据流程",
        "author_target": "Describe the reproducible evidence-to-analysis workflow.",
        "publication_critical": False,
        "research_bindings": bindings,
        "nodes": [
            {**n, "binding_id": f"binding.{i}"} for i, n in enumerate(evidence["nodes"])
        ],
        "edges": [
            {"id": "edge.precedes", **evidence["edge"], "binding_id": "binding.2"}
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
    ir = service.build(spec, run_root=root)
    (root / "frozen-ir.json").write_bytes(
        canonical_json_bytes(ir.model_dump(mode="json"))
    )
    req = RuntimeCommandRequest.model_validate(
        {
            **common,
            "expected_revision": 2,
            "event_id": "evt-00000000-0000-4000-8000-000000000082",
            "command_id": "cmd-00000000-0000-4000-8000-000000000082",
        }
    )
    result = service.qualify(ir, run_root=root, request=req)
    result["reproduction"] = service.reproduce(ir.artifact_id, run_root=root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return root


if __name__ == "__main__":
    run(sys.argv[1])
