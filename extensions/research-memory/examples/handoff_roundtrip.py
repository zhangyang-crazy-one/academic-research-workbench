"""uv run python extensions/research-memory/examples/handoff_roundtrip.py OUTPUT

Reproducible local Codex -> Claude MCP transport -> Codex continuation example.
It does not claim a live Claude host session.
"""

import json
import subprocess
import sys
from pathlib import Path

from arw_research_memory.project import initialize_project
from arw_research_memory.service import ResearchMemoryService

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    InitRunRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.research_memory import MemoryInput, MemoryQuery


def run(output):
    root = Path(output).absolute()
    root.mkdir(parents=True, exist_ok=False)
    initialize_project(root, "project.memory-example")
    target = canonical_json_bytes(
        {"objective": "Compare two retained baselines", "method": "paired evaluation"}
    )
    (root / "target.json").write_bytes(target)
    run_id = "run-00000000-0000-4000-8000-000000000090"
    base = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "occurred_at": "2026-09-08T00:00:00Z",
        "actor_id": "parent.runtime",
        "event_id": "evt-00000000-0000-4000-8000-000000000090",
        "command_id": "cmd-00000000-0000-4000-8000-000000000090",
    }
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                **base,
                "immutable_input": {
                    "path": "target.json",
                    "sha256": sha256_hex(target),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
            }
        ),
    )

    def request(number):
        return {
            **base,
            "actor_role": "parent_control_plane",
            "expected_revision": replay_run(root).revision,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
        }

    accepted = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                **request(91),
                "artifact_id": "artifact.target",
                "artifact_kind": "author-target",
                "media_type": "application/json",
                "content_path": "target.json",
                "content_sha256": sha256_hex(target),
                "base_revision": replay_run(root).revision,
                "consumed_sha256": [replay_run(root).last_event_sha256],
            }
        )
    )
    if not accepted.accepted:
        raise RuntimeError("example target admission failed")
    event = replay_run(root).events[-1]
    value = MemoryInput.model_validate_json(
        json.dumps(
            {
                "kind": "handoff",
                "title": "Comparison continuation",
                "body": "Baseline collection is complete. Run the paired evaluation.",
                "source_artifact_ids": ["artifact.target"],
                "source_ledger_event_ids": [event.event_id],
                "links": [
                    {
                        "kind": "author_target",
                        "target_id": "artifact.target",
                        "event_id": event.event_id,
                        "sha256": sha256_hex(target),
                    }
                ],
                "handoff": {
                    "objective": "Compare two retained baselines",
                    "current_state": "Baseline collection complete",
                    "completed_work": ["Baseline collection"],
                    "evidence_gathered": ["artifact.target"],
                    "commands_evaluations_run": [],
                    "relevant_artifacts_issues_files": ["target.json"],
                    "open_questions": [],
                    "blockers": [],
                    "risks": ["Small sample"],
                    "next_concrete_action": "Run the paired evaluation",
                    "source_run_harness": {"run_id": run_id, "harness": "codex"},
                    "intended_target_harness": "claude",
                },
            }
        )
    )
    service = ResearchMemoryService(root, run_root=root)
    saved = service.save(
        value, request=RuntimeCommandRequest.model_validate(request(92))
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "memory_read",
                "arguments": {"memory_id": saved["memory_id"]},
            },
        },
    ]
    transport = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.memory_mcp",
            "--project-root",
            str(root),
            "--harness",
            "claude",
        ],
        input="".join(json.dumps(m) + "\n" for m in messages),
        text=True,
        capture_output=True,
        check=True,
    )
    response = json.loads(transport.stdout.splitlines()[-1])["result"]
    if response["isError"]:
        raise RuntimeError("MCP example read failed")
    returned = response["structuredContent"]["memory"]["memory_id"]
    assert returned == saved["memory_id"]
    result = {
        "saved": saved,
        "adapter_read_id": returned,
        "codex_resume": service.resume_handoff(returned, query=MemoryQuery()),
    }
    (root / "example-result.json").write_bytes(canonical_json_bytes(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run(sys.argv[1])
