"""Run with: uv run python extensions/research-learning/examples/qualified_lesson.py OUTPUT.

A reproducible synthetic fixture demonstrates governance, not scientific efficacy.
"""

import json
import sys
from pathlib import Path

from arw_research_learning.service import ResearchLearningService

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    InitRunRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.research_learning import HeuristicInput


def run(output):
    root = Path(output).absolute()
    root.mkdir(parents=True, exist_ok=False)
    publish_once(
        root,
        ".arw/project.json",
        canonical_json_bytes(
            {
                "schema_version": "arw.project.v1",
                "project_id": "project.learning-example",
            }
        ),
    )
    (root / ".arw/learning-policy.json").write_text('{"enabled":true}')
    source = canonical_json_bytes(
        {
            "failure": "Limited retrieval coverage left primary evidence missing",
            "fixture": True,
        }
    )
    (root / "source.json").write_bytes(source)
    base = {
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000091",
        "occurred_at": "2026-09-08T00:00:00Z",
        "actor_id": "parent.runtime",
        "event_id": "evt-00000000-0000-4000-8000-000000000001",
        "command_id": "cmd-00000000-0000-4000-8000-000000000001",
    }
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                **base,
                "immutable_input": {
                    "path": "source.json",
                    "sha256": sha256_hex(source),
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
    sequence = 1

    def request():
        nonlocal sequence
        sequence += 1
        return RuntimeCommandRequest.model_validate(
            {
                **base,
                "actor_role": "parent_control_plane",
                "expected_revision": replay_run(root).revision,
                "event_id": f"evt-00000000-0000-4000-8000-{sequence:012d}",
                "command_id": f"cmd-00000000-0000-4000-8000-{sequence:012d}",
            }
        )

    def accept(artifact_id, body):
        raw = canonical_json_bytes(body)
        relative = artifact_id + ".json"
        (root / relative).write_bytes(raw)
        state = replay_run(root)
        result = RuntimeCommandService(root).accept_artifact(
            ArtifactAcceptanceRequest.model_validate(
                {
                    **request().model_dump(),
                    "artifact_id": artifact_id,
                    "artifact_kind": "learning-evidence",
                    "media_type": "application/json",
                    "content_path": relative,
                    "content_sha256": sha256_hex(raw),
                    "base_revision": state.revision,
                    "consumed_sha256": [state.last_event_sha256],
                }
            )
        )
        if not result.accepted:
            raise RuntimeError("example artifact admission failed")
        return replay_run(root).events[-1]

    source_event = accept("artifact.failure", json.loads(source))
    service = ResearchLearningService(root, run_root=root)
    observation = service.observe(source_event.event_id, request=request())
    heuristic = HeuristicInput.model_validate_json(
        json.dumps(
            {
                "heuristic_id": "heuristic.coverage-first",
                "domain": "literature review",
                "trigger": "Primary evidence is missing",
                "proposed_action": "Check retrieval coverage before increasing judge calls",
                "applicability": {
                    "task": "literature_review",
                    "model": "fixture-model-v1",
                    "retrieval_coverage": "one corpus",
                    "call_budget": 4,
                    "output_budget": 4096,
                    "metric": "citation_recall",
                },
                "confidence": 0.6,
                "supporting_observation_ids": [observation["record_id"]],
                "counterexample_observation_ids": [],
                "unknown": [],
                "search_coverage": "One accepted synthetic failure receipt",
                "evaluation_coverage": "One synthetic independent run; generalization unmeasured",
                "producer": "manual-author",
                "producer_version": "1",
            }
        )
    )
    proposed = service.extract(heuristic, request=request())
    policy = {
        "schema_version": "arw.learning-policy.v1",
        "policy_id": "policy.example",
        "version": "1",
        "mode": "shadow",
        "run_subset": [base["run_id"]],
        "metric": "citation_recall",
        "minimum_delta": 0.0,
    }
    accept("artifact.policy", policy)
    (root / ".arw/learning-policy.json").write_text(
        json.dumps(
            {"enabled": True, "evaluation_policy_artifact_id": "artifact.policy"}
        )
    )
    accept(
        "artifact.sample",
        {
            "schema_version": "arw.learning-sample.v1",
            "heuristic_id": heuristic.heuristic_id,
            "policy_id": "policy.example",
            "policy_version": "1",
            "run_id": base["run_id"],
            "mode": "shadow",
            "metric": "citation_recall",
            "baseline": 0.4,
            "outcome": 0.7,
            "proposed_action": heuristic.proposed_action,
            "actual_action": "Check the fixture corpus coverage",
        },
    )
    evaluation = service.evaluate(
        heuristic.heuristic_id, ["artifact.sample"], request=request()
    )
    qualification = service.qualify(heuristic.heuristic_id, request=request())
    accept(
        "artifact.approval",
        {
            "action": "promote_heuristic",
            "heuristic_id": heuristic.heuristic_id,
            "heuristic_digest": proposed["content_digest"],
            "qualification_receipt_id": qualification["content_digest"],
            "to_scope": "project",
            "status": "APPROVED",
            "reviewer": "fixture.author",
        },
    )
    promotion = service.promote(
        heuristic.heuristic_id,
        consent=True,
        approval_artifact_id="artifact.approval",
        request=request(),
    )
    suggestions = service.applicable(heuristic.applicability)
    accept(
        "artifact.author-choice",
        {
            "schema_version": "arw.learning-decision.v1",
            "heuristic_id": heuristic.heuristic_id,
            "promotion_event_id": promotion["event_id"],
            "applicability": heuristic.applicability.model_dump(mode="json"),
            "author": "fixture.author",
            "chosen_action": "Expand primary-source retrieval before changing judges",
            "outcome": {"measured": False, "value": None},
        },
    )
    choice = service.decision_context(heuristic.heuristic_id, "artifact.author-choice")
    result = {
        "fixture": True,
        "evaluation": evaluation,
        "promotion": promotion,
        "suggestions": suggestions,
        "later_author_decision": choice,
        "research_efficacy": "unmeasured; numbers are synthetic fixture inputs",
    }
    (root / "example-result.json").write_bytes(canonical_json_bytes(result))
    return result


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2))
