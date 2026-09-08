"""Offline fixture: uv run --extra semantic python THIS_FILE NEW_OUTPUT_DIR."""

import json
import sys
from pathlib import Path

from arw.composition import configured_semantic_provider
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import ArtifactAcceptanceRequest, InitRunRequest


def run(output):
    root = Path(output).absolute()
    root.mkdir(parents=True, exist_ok=False)
    source = b"Fixture literature selection for a cardiac manuscript."
    (root / "input.txt").write_bytes(source)
    base = {
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000093",
        "occurred_at": "2026-09-08T00:00:00Z",
        "actor_id": "parent.runtime",
    }
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                **base,
                "event_id": "evt-00000000-0000-4000-8000-000000000001",
                "command_id": "cmd-00000000-0000-4000-8000-000000000001",
                "immutable_input": {"path": "input.txt", "sha256": sha256_hex(source)},
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

    def accept(artifact_id, raw):
        nonlocal sequence
        sequence += 1
        path = artifact_id + ".txt"
        (root / path).write_bytes(raw)
        state = replay_run(root)
        result = RuntimeCommandService(root).accept_artifact(
            ArtifactAcceptanceRequest.model_validate(
                {
                    **base,
                    "event_id": f"evt-00000000-0000-4000-8000-{sequence:012d}",
                    "command_id": f"cmd-00000000-0000-4000-8000-{sequence:012d}",
                    "actor_role": "parent_control_plane",
                    "expected_revision": state.revision,
                    "artifact_id": artifact_id,
                    "artifact_kind": "source",
                    "media_type": "text/plain",
                    "content_path": path,
                    "content_sha256": sha256_hex(raw),
                    "base_revision": state.revision,
                    "consumed_sha256": [state.last_event_sha256],
                }
            )
        )
        if not result.accepted:
            raise RuntimeError("fixture artifact acceptance failed")

    accept(
        "paper.heart", b"Fixture: heart function was measured in a limited experiment."
    )
    accept("paper.star", b"Fixture: stellar spectra were measured.")
    model = {
        "format": "arw.token-vectors.v1",
        "model_id": "fixture-domain-words",
        "version": "1",
        "dimensions": 2,
        "tokens": {
            "heart": [1, 0],
            "cardiac": [1, 0],
            "star": [0, 1],
            "stellar": [0, 1],
        },
    }
    model_path = root / "embedding.json"
    model_path.write_bytes(canonical_json_bytes(model))
    provider = configured_semantic_provider(
        root / "projection.db", root, model_path, sha256_hex(model_path.read_bytes())
    )
    receipt = provider.build(["paper.heart", "paper.star"])
    result = provider.search("cardiac")
    assert result["rows"][0]["artifact_id"] == "paper.heart"
    before = result
    provider.store_path.unlink()
    assert provider.build(["paper.heart", "paper.star"], rebuild=True) == receipt
    assert provider.search("cardiac") == before
    decision = {
        "fixture": True,
        "research_target": "Select evidence to review for a cardiac manuscript",
        "query": "cardiac",
        "retrieval": result,
        "selected_for_author_review": "paper.heart",
        "author_choice": "fixture author selects the source for full reading; ranking does not establish a claim",
        "research_effectiveness": "unmeasured",
    }
    accept("selection.record", canonical_json_bytes(decision))
    (root / "example-result.json").write_bytes(canonical_json_bytes(decision))
    return decision


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, sort_keys=True))
