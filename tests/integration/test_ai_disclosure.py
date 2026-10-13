"""Canonical participation evidence, unknown coverage and frozen policy replay."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph
from arw.kernel.ledger.accepted_refs import resolve_ref
from arw.kernel.ledger.ai_disclosure import capture, make_draft, replay_draft
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.ai_disclosure import (
    AIActivityReceipt,
    AIDisclosurePolicy,
    AIParticipationDeclaration,
    ai_disclosure_schema_documents,
)
from arw.kernel.state.models import ArtifactAcceptanceRequest
from tests.unit.test_accepted_refs import accepted_fixture


def accept(run, ref, value, kind, identifier, path=None, media="application/json"):
    raw = canonical_json_bytes(value) if not isinstance(value, bytes) else value
    path = path or identifier + ".json"
    (run / path).write_bytes(raw)
    replay = replay_run(run)
    request = ArtifactAcceptanceRequest(
        schema_version="1.0.0",
        run_id=ref.run_id,
        event_id=f"evt-{uuid4()}",
        command_id=f"cmd-{uuid4()}",
        expected_revision=replay.revision,
        occurred_at="2026-07-13T00:02:00Z",
        actor_id="parent.runtime",
        actor_role="parent_control_plane",
        artifact_id=identifier,
        artifact_kind=kind,
        media_type=media,
        content_path=path,
        content_sha256=sha256_hex(raw),
        base_revision=replay.revision,
        consumed_sha256=[],
    )
    out = RuntimeCommandService(run).accept_artifact(request)
    assert out.accepted, out
    return ref.model_copy(
        update={
            "artifact_id": identifier,
            "accepting_event_id": out.event.event_id,
            "accepting_event_sha256": out.event.event_sha256,
            "content_sha256": sha256_hex(raw),
        }
    )


def policy():
    return AIDisclosurePolicy.model_validate_json(
        (
            Path(__file__).resolve().parents[2]
            / "examples/disclosure-policies/arr-20261012.json"
        ).read_bytes()
    )


def test_imported_unanchored_text_figures_code_keep_unknown(tmp_path):
    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Imported unreferenced prose.")
    accept(
        run,
        ref,
        b"No citations or numbers.",
        "manuscript",
        "artifact.prose",
        "paper.md",
        "text/markdown",
    )
    accept(
        run,
        ref,
        b'{"artifact_kind":"result_plot"}',
        "research-artifact",
        "artifact.figure",
    )
    accept(
        run,
        ref,
        b"print(1)\n",
        "analysis-code",
        "artifact.code",
        "analysis.py",
        "text/plain",
    )
    summary = capture(ctx)
    assert {m["material_type"] for m in summary["materials"]} >= {
        "text",
        "figure",
        "code",
    }
    assert all(
        m["ai_involvement"] == "unknown" and not m["history_complete"]
        for m in summary["materials"]
    )
    assert not any(m["histories"] for m in summary["materials"])


@pytest.mark.parametrize(
    "usage",
    [
        "imported",
        "external_edit",
        "mixed",
        "grammar_only",
        "ai_drafted",
        "ai_drafted_human_edited",
    ],
)
def test_explicit_usage_retained_and_original_refs_checked(tmp_path, usage):
    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Unreferenced draft.")
    declaration = AIParticipationDeclaration(
        declaration_id="declaration.one",
        target=ref,
        usage=usage,
        author_id="author.owner",
        detail="The author reports this history.",
    )
    accept(
        run,
        ref,
        declaration.model_dump(mode="json"),
        "ai-participation-declaration",
        "declaration.one",
    )
    assert capture(ctx)["materials"][0]["ai_involvement"] == "human-declared"
    observed = AIActivityReceipt(
        activity_id="activity.one",
        target=ref,
        usage=usage,
        system="Codex",
        harness="native",
        model="gpt-6.1-sol",
        detail="Retained receipt reports this activity; host authentication is not inferred.",
    )
    receipt_ref = accept(
        run, ref, observed.model_dump(mode="json"), "ai-activity-receipt", "receipt.one"
    )
    assert resolve_ref(receipt_ref, ctx).status == "resolved"
    item = capture(ctx)["materials"][0]
    assert item["ai_involvement"] == "observed"
    assert {h["status"] for h in item["histories"]} == {"observed", "human-declared"}
    assert {h["usage"] for h in item["histories"]} == {usage}
    (run / "receipt.one.json").write_text("{}")
    with pytest.raises(ValueError):
        capture(ctx)


def test_generic_receipt_does_not_supply_observed_and_bad_target_refuses(tmp_path):
    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Imported prose.")
    receipt = AIActivityReceipt(
        activity_id="activity.one",
        target=ref,
        usage="ai_drafted",
        system="pi",
        harness="native",
        model="configured",
        detail="Observed content",
    )
    accept(
        run, ref, receipt.model_dump(mode="json"), "ordinary-json", "receipt.generic"
    )
    assert all(m["ai_involvement"] == "unknown" for m in capture(ctx)["materials"])
    changed = receipt.model_copy(
        update={"target": ref.model_copy(update={"content_sha256": "f" * 64})}
    )
    accept(
        run, ref, changed.model_dump(mode="json"), "ai-activity-receipt", "receipt.bad"
    )
    with pytest.raises(ValueError):
        capture(ctx)


def test_dated_policy_change_does_not_rewrite_old_draft_or_approval(tmp_path, capsys):
    from arw.cli import main

    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Imported prose.")
    original = make_draft(ctx, policy())
    assert canonical_json_bytes(make_draft(ctx, policy())) == canonical_json_bytes(
        original
    )
    accept(run, ref, b"Later code", "analysis-code", "artifact.later", "later.py")
    updated = policy().model_copy(
        update={
            "policy_version": "later-policy",
            "requirements": ("Changed local policy snapshot",),
        }
    )
    assert make_draft(ctx, updated)["draft_sha256"] != original["draft_sha256"]
    assert replay_draft(original, ctx) == original
    assert (
        original["human_final_review"] == "pending"
        and original["submission"] == "not_performed"
    )
    bad = {**original, "human_final_review": "approved"}
    with pytest.raises(ValueError):
        replay_draft(bad, ctx)
    path = run / "saved-draft.json"
    path.write_bytes(canonical_json_bytes(original))
    assert (
        main(
            [
                "disclosure",
                "replay",
                "--project-root",
                str(ctx.project_root),
                "--run-root",
                str(run),
                "--draft",
                str(path),
            ]
        )
        == 0
    )
    assert (
        json.loads(capsys.readouterr().out)["draft_sha256"] == original["draft_sha256"]
    )


def test_schema_projection_matches_checked_files():
    root = Path(__file__).resolve().parents[2]
    for name, document in ai_disclosure_schema_documents().items():
        assert json.loads((root / "schemas/v1" / name).read_text()) == document


def test_graph_only_associates_summary_and_hard_check_is_unchanged(tmp_path):
    from arw.kernel.ledger.accepted_refs import ResolutionContext
    from arw.kernel.state.accepted_ref import ParentArtifactRef
    from tests.unit.test_claim_graph import setup

    project, run = setup(tmp_path)
    before = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    target = ParentArtifactRef.model_validate(
        before["coverage"]["manuscripts"][0]["accepted_ref"]
    )
    record = AIParticipationDeclaration(
        declaration_id="declaration.one",
        target=target,
        usage="grammar_only",
        author_id="author.owner",
        detail="Human-declared editing scope.",
    )
    accept(
        run,
        target,
        record.model_dump(mode="json"),
        "ai-participation-declaration",
        "declaration.one",
    )
    after = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    assert before["coverage"]["manuscripts"][0]["ai_involvement"] == "unknown"
    assert after["coverage"]["manuscripts"][0]["ai_involvement"] == "human-declared"
    summary = capture(ResolutionContext(target.project_id, (run,), project))
    assert any(m["ai_involvement"] == "human-declared" for m in summary["materials"])
    assert before["hard_checks"] == after["hard_checks"]


def test_ieee_excerpt_is_fixed_and_separate_from_arr():
    root = Path(__file__).resolve().parents[2]
    ieee = AIDisclosurePolicy.model_validate_json(
        (root / "examples/disclosure-policies/ieee-20261012.json").read_bytes()
    )
    assert ieee.template == "acknowledgments" and policy().template == "checklist"
    assert ieee.source_digest_scope == "retained-primary-excerpts"
    bad = ieee.model_dump(mode="json")
    bad["source_excerpt"] += "tampered"
    with pytest.raises(ValueError):
        AIDisclosurePolicy.model_validate(bad)


def test_malformed_participation_cannot_introduce_a_scientific_gate(tmp_path):
    from arw.kernel.state.accepted_ref import ParentArtifactRef
    from tests.unit.test_claim_graph import setup

    project, run = setup(tmp_path)
    before = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    target = ParentArtifactRef.model_validate(
        before["coverage"]["manuscripts"][0]["accepted_ref"]
    )
    accept(
        run,
        target,
        {"target": target.model_dump(mode="json")},
        "ai-activity-receipt",
        "receipt.incomplete",
    )
    after = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    assert before["hard_checks"] == after["hard_checks"]
    assert after["coverage"]["manuscripts"][0]["ai_involvement"] == "unknown"
    assert any(a["code"] == "ai_participation_unverifiable" for a in after["advisory"])


def test_imported_receipt_wording_and_old_generator_replay(tmp_path):
    run, ctx, ref, _ = accepted_fixture(tmp_path, b"Imported prose.")
    receipt = AIActivityReceipt(
        activity_id="activity.imported",
        target=ref,
        usage="imported",
        system="unknown",
        harness="synthetic",
        model="synthetic",
        detail="Imported history, not proof of AI drafting.",
    )
    accept(
        run,
        ref,
        receipt.model_dump(mode="json"),
        "ai-activity-receipt",
        "receipt.imported",
    )
    current = make_draft(ctx, policy())
    assert "does not establish AI drafting" in current["text"]
    assert replay_draft(current, ctx) == current
    old = make_draft(ctx, policy(), generator_version="1.0.0")
    assert old["generator_version"] == "1.0.0"
    assert replay_draft(old, ctx) == old
