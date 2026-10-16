"""Claim-only advisory replay must revalidate every registered source span."""

import json
from uuid import uuid4

import pytest

from arw.cli import main
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph, narrative
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.review_concerns import (
    diagnose,
    export_prov,
    replay_report,
    validate_concern,
)
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.kernel.state.review_concern import ClaimRevisionTarget
from tests.integration.test_precise_source_locators import seed
from tests.unit.test_claim_graph import TEXT, record, registration
from tests.unit.test_narrative import plan, project


def claim_only(tmp_path):
    root = project(tmp_path)
    narrative.register(root)
    narrative.select(root, plan())
    run, _ = seed(root)
    source = run / "draft.txt"
    source.write_text(TEXT, encoding="utf-8")
    state = replay_run(run)
    accepted = RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": state.run_id,
                "event_id": f"evt-{uuid4()}",
                "command_id": f"cmd-{uuid4()}",
                "occurred_at": "2026-09-08T00:01:00Z",
                "actor_id": "parent.fixture",
                "actor_role": "parent_control_plane",
                "expected_revision": state.revision,
                "artifact_id": "artifact.draft",
                "artifact_kind": "manuscript",
                "media_type": "text/plain",
                "content_path": "draft.txt",
                "content_sha256": sha256_hex(source.read_bytes()),
                "base_revision": state.revision,
                "consumed_sha256": [state.last_event_sha256],
            }
        )
    )
    assert accepted.accepted
    view = claim_graph.graph(root, run_roots=(run,))
    record(root, run, registration(view))
    full = diagnose(root, (run,))
    claims = tuple(
        c for c in full.concerns if isinstance(c.target, ClaimRevisionTarget)
    )
    assert len(claims) == 1
    return (
        root,
        run,
        source,
        full,
        full.model_copy(update={"concerns": claims, "omitted_concern_count": 0}),
    )


def change_source(path, change):
    if change == "rewrite":
        path.write_text("Changed manuscript bytes", encoding="utf-8")
    else:
        path.unlink()


@pytest.mark.parametrize("change", ["rewrite", "delete"])
def test_claim_only_and_full_reports_reject_changed_plain_source(tmp_path, change):
    root, run, source, full, only = claim_only(tmp_path)
    concern = only.concerns[0]
    before = (root / ".arw/narrative/events.jsonl").read_bytes()
    assert validate_concern(concern, root, (run,)) == concern
    assert replay_report(only, root, (run,)) == only
    assert export_prov(only, root, (run,))
    assert replay_report(full, root, (run,)) == full
    change_source(source, change)
    for operation in (
        lambda: validate_concern(concern, root, (run,)),
        lambda: replay_report(only, root, (run,)),
        lambda: export_prov(only, root, (run,)),
        lambda: replay_report(full, root, (run,)),
        lambda: claim_graph.graph(root, run_roots=(run,)),
    ):
        with pytest.raises(ValueError):
            operation()
    assert (root / ".arw/narrative/events.jsonl").read_bytes() == before


@pytest.mark.parametrize("change", ["rewrite", "delete"])
@pytest.mark.parametrize("action", ["verify", "replay", "prov"])
def test_public_claim_only_cli_rejects_changed_plain_source(
    tmp_path, capsys, change, action
):
    root, run, source, _, only = claim_only(tmp_path)
    value = only.concerns[0] if action == "verify" else only
    payload = value.model_dump(mode="json")
    if action != "verify":
        payload["report_sha256"] = value.sha256
    path = root / "advisory.json"
    path.write_bytes(canonical_json_bytes(payload))
    args = [
        "review",
        action,
        "--project-root",
        str(root),
        "--run-root",
        str(run),
        "--input",
        str(path),
    ]
    assert main(args) == 0
    capsys.readouterr()
    change_source(source, change)
    assert main(args) == 65
    output = capsys.readouterr()
    assert "Traceback" not in output.err
    if output.out:
        assert json.loads(output.out).get("status") != "advisory_target_verified"
