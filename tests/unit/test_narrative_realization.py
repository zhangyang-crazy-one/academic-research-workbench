"""Paper realization checks bind real bytes, graph paths and current selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.narrative import binding_for_start, current, register, select
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.policy.narrative_realization import (
    NarrativeRealizationError,
    validate_realization,
)
from arw.kernel.policy.schema_registry import (
    validate_checked_in_schemas,
    validate_instance,
)
from arw.kernel.state.narrative_realization import NarrativeRealization

from .test_narrative import _accept_paper_artifact, plan, project, run_request


def _fixture(root: Path, label: str = "proof", *, project_root: Path | None = None):
    snapshot = current(project_root or root.parent.parent)
    statements = [
        "The studied question is narrowly defined.",
        "Prior methods leave this specific case open.",
        "A single core lemma is the contribution.",
        "Claim one follows from the lemma assumptions.",
        "The proof establishes the lemma." if label == "proof" else "The experiment shows a negative result.",
        "The conclusion is limited to these assumptions.",
    ]
    raw = "\n\n".join(statements).encode()
    (root / "paper.md").write_bytes(raw)
    ids = ("problem.one", "gap.one", "contribution.one", "argument.one", "evidence.one", "boundary.one")
    nodes = []
    cursor = 0
    for index, (function, statement) in enumerate(zip(snapshot.plan.function_order, statements)):
        encoded = statement.encode()
        node = {
            "node_id": ids[index],
            "function_id": function,
            "narrative_sha256": snapshot.sha256,
            "span": {"start": cursor, "end": cursor + len(encoded), "sha256": sha256_hex(encoded)},
        }
        if function == "argument":
            node.update(claim_id="claim.one", contribution_id="contribution.one",
                        evidence_ref="proof.one", knowledge_boundary_id="boundary.one",
                        conclusion=True, within_scope_boundary=True)
        if function == "evidence":
            node.update(evidence_ref="proof.one", contribution_id="contribution.one",
                        knowledge_boundary_id="boundary.one")
        nodes.append(node)
        cursor += len(encoded) + 2
    return {
        "schema_version": "arw.narrative-realization.v1",
        "stage": "outline",
        "narrative_sha256": snapshot.sha256,
        "source_path": "paper.md",
        "source_sha256": sha256_hex(raw),
        "nodes": nodes,
    }


@pytest.fixture
def paper(tmp_path):
    root = project(tmp_path)
    register(root)
    select(root, plan())
    run = root / "runs/one"
    request = run_request(root, binding=binding_for_start(root, run)).model_copy(update={
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
        "journal_layout": "segmented-v1",
    })
    initialize_run(run, request)
    return run


@pytest.mark.parametrize("kind", ["proof", "negative"])
def test_short_proof_and_negative_result_are_admissible_with_unknown_semantics(paper, kind):
    value = _fixture(paper, kind)
    report = validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert report["mechanical_status"] == "PASS"
    assert report["semantic_status"] == "UNKNOWN"
    assert "evidence_source_unknown" in report["human_review_reason_codes"]
    (paper / "outline.json").write_bytes(canonical_json_bytes(value))
    accepted = _accept_paper_artifact(paper, "outline.one", "outline.json", 9001, kind="narrative-outline")
    assert accepted.accepted
    digest = accepted.event.payload.narrative_report_sha256
    assert digest and sha256_hex((paper / f"narrative/reports/sha256/{digest}.json").read_bytes()) == digest


def test_missing_evidence_orphan_claim_order_stale_and_tampered_spans(paper):
    value = _fixture(paper)
    snapshot = current(paper.parent.parent)
    cases = []
    missing = {**value, "nodes": [n for n in value["nodes"] if n["function_id"] != "evidence"]}
    cases.append((missing, "narrative_function_missing"))
    orphan = {**value, "nodes": [dict(n) for n in value["nodes"]]}
    orphan["nodes"][3]["evidence_ref"] = "fabricated.ref"
    cases.append((orphan, "narrative_orphan_claim"))
    stale = {**value, "narrative_sha256": "f" * 64}
    cases.append((stale, "stale_narrative"))
    wrong_span = {**value, "nodes": [dict(n) for n in value["nodes"]]}
    wrong_span["nodes"][0]["span"] = {**wrong_span["nodes"][0]["span"], "sha256": "f" * 64}
    cases.append((wrong_span, "narrative_span_invalid"))
    for case, code in cases:
        with pytest.raises(NarrativeRealizationError) as error:
            validate_realization(paper, NarrativeRealization.model_validate(case), snapshot)
        assert error.value.code == code
    (paper / "paper.md").write_text("changed text", encoding="utf-8")
    with pytest.raises(NarrativeRealizationError) as changed:
        validate_realization(paper, NarrativeRealization.model_validate(value), snapshot)
    assert changed.value.code == "narrative_source_digest_mismatch"


def test_ordinary_paper_draft_cannot_bypass_realization(paper):
    (paper / "draft.md").write_text("A draft without annotations.", encoding="utf-8")
    outcome = _accept_paper_artifact(paper, "draft.legacy", "draft.md", 9002, kind="draft")
    assert not outcome.accepted
    assert outcome.rejection.code == "narrative_contract_invalid"


def test_schema_is_registered_and_rejects_extra_fields(paper):
    assert "narrative-realization.schema.json" in validate_checked_in_schemas()
    value = _fixture(paper)
    validate_instance("narrative-realization.schema.json", value)
    with pytest.raises(ValueError):
        validate_instance("narrative-realization.schema.json", {**value, "made_up": True})


def test_predecessor_chain_and_postaccept_manuscript_tamper(paper):
    outline = _fixture(paper)
    for stage, artifact_id, predecessor in (
        ("outline", "outline.chain", None),
        ("blueprint", "blueprint.chain", "outline.chain"),
        ("draft", "draft.chain", "blueprint.chain"),
    ):
        value = {**outline, "stage": stage}
        if predecessor is not None:
            value["predecessor_artifact_id"] = predecessor
        path = f"{stage}.json"
        (paper / path).write_bytes(canonical_json_bytes(value))
        result = _accept_paper_artifact(paper, artifact_id, path, 9100 + len(stage), kind=f"narrative-{stage}")
        assert result.accepted, result.rejection
    assert RuntimeCommandService(paper).read_state().accepted_revision == 4
    (paper / "paper.md").write_bytes(b"The text was replaced after acceptance.")
    replay = replay_run(paper)
    assert replay.recovery_health == "blocked"
    assert "accepted narrative source" in replay.recovery_message


def test_order_requires_reason_and_records_review(paper):
    value = _fixture(paper)
    nodes = [dict(n) for n in value["nodes"]]
    nodes[0]["function_id"] = "gap"
    nodes[1]["function_id"] = "problem"
    value["nodes"] = nodes
    with pytest.raises(NarrativeRealizationError) as unexplained:
        validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert unexplained.value.code == "narrative_order_unexplained"
    nodes[0]["interleave_reason"] = "The motivating gap is introduced before the question."
    nodes[1]["interleave_reason"] = "The question is specified immediately after that gap."
    report = validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert "narrative_interleave_review" in report["human_review_reason_codes"]


def test_real_evidence_binding_hypothesis_history_and_cross_chain(paper):
    value = _fixture(paper)
    source = (paper / "paper.md").read_bytes()
    (paper / "proof.txt").write_bytes(source)
    note = b"The hypothesis was recorded before evaluation."
    (paper / "hypothesis.txt").write_bytes(note)
    assert _accept_paper_artifact(paper, "source.proof", "proof.txt", 9211, kind="research-evidence").accepted
    history_doc = {
        "schema_version": "arw.hypothesis-history.v1",
        "claim_id": "claim.one", "designation": "prespecified",
        "narrative_sha256": value["narrative_sha256"],
        "source_path": "hypothesis.txt", "source_sha256": sha256_hex(note),
        "span": {"start": 0, "end": len(note), "sha256": sha256_hex(note)},
    }
    (paper / "history.json").write_bytes(canonical_json_bytes(history_doc))
    assert _accept_paper_artifact(paper, "source.hypothesis", "history.json", 9212, kind="hypothesis-history").accepted
    value["nodes"][4].update(evidence_source_artifact_id="source.proof", evidence_source_sha256=sha256_hex(source))
    value["nodes"][3]["hypothesis_history_ref"] = "source.hypothesis"
    report = validate_realization(
        paper, NarrativeRealization.model_validate(value), current(paper.parent.parent),
        events=replay_run(paper).events,
    )
    assert "evidence_source_unknown" not in report["human_review_reason_codes"]
    assert report["semantic_status"] == "UNKNOWN"
    value["nodes"][3]["hypothesis_history_ref"] = "source.fabricated"
    with pytest.raises(NarrativeRealizationError) as history_error:
        validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent),
                            events=replay_run(paper).events)
    assert history_error.value.code == "narrative_hypothesis_history_invalid"
    # An explicit historical post hoc label cannot be restated as a preset claim.
    historical_note = {**history_doc, "designation": "post_hoc"}
    (paper / "history-posthoc.json").write_bytes(canonical_json_bytes(historical_note))
    assert _accept_paper_artifact(paper, "source.posthoc", "history-posthoc.json", 9213, kind="hypothesis-history").accepted
    value["nodes"][3]["hypothesis_history_ref"] = "source.posthoc"
    with pytest.raises(NarrativeRealizationError) as mismatch:
        validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent),
                            events=replay_run(paper).events)
    assert mismatch.value.code == "narrative_posthoc_mismatch"


def test_v2_plan_requires_concrete_transition_objects_and_v1_wire_omits_them():
    old = plan()
    assert "transition_anchors" not in old.model_dump(mode="json")
    payload = old.model_dump(mode="json")
    payload.update(schema_version="arw.narrative-plan.v2", transition_anchors=[
        {"transition": "problem_to_contribution", "object_kind": "contribution", "object_ref": "lemma.one"},
        {"transition": "contribution_to_evidence", "object_kind": "evidence_form", "object_ref": "proof"},
        {"transition": "evidence_to_conclusion", "object_kind": "scope", "object_ref": "scope.one"},
    ])
    with pytest.raises(ValueError):
        type(old).model_validate(payload)
    payload["problem_to_contribution"] += " lemma.one"
    payload["contribution_to_evidence"] += " proof"
    payload["evidence_to_conclusion"] += " scope.one"
    assert type(old).model_validate(payload).schema_version == "arw.narrative-plan.v2"


def test_v2_transition_anchors_resolve_against_actual_nodes(tmp_path):
    root = project(tmp_path)
    register(root)
    old = plan()
    payload = old.model_dump(mode="json")
    payload.update(schema_version="arw.narrative-plan.v2", transition_anchors=[
        {"transition": "problem_to_contribution", "object_kind": "contribution", "object_ref": "contribution.one"},
        {"transition": "contribution_to_evidence", "object_kind": "evidence_form", "object_ref": "proof"},
        {"transition": "evidence_to_conclusion", "object_kind": "scope", "object_ref": "boundary.one"},
    ])
    payload["problem_to_contribution"] += " contribution.one"
    payload["contribution_to_evidence"] += " proof"
    payload["evidence_to_conclusion"] += " boundary.one"
    select(root, type(old).model_validate(payload))
    run = root / "runs/one"
    run.mkdir(parents=True)
    value = _fixture(run)
    with pytest.raises(NarrativeRealizationError) as unresolved:
        validate_realization(run, NarrativeRealization.model_validate(value), current(root))
    assert unresolved.value.code == "narrative_plan_anchor_unresolved"
    value["nodes"][4]["evidence_form"] = "proof"
    assert validate_realization(run, NarrativeRealization.model_validate(value), current(root))["mechanical_status"] == "PASS"


def test_generic_writing_derived_receipt_cannot_imitate_reviewed_service_admission(paper):
    value = _fixture(paper)
    value.update(stage="draft", predecessor_artifact_id="blueprint.claimed")
    source = (paper / "paper.md").read_bytes()
    (paper / "review-source.txt").write_bytes(source)
    source_event = _accept_paper_artifact(paper, "writing.source", "review-source.txt", 9299, kind="writing-source").event
    verification = {"unresolved_dimensions": [], "fact_lock": {"mechanical_status": "passed"}}
    proposal = {"author_target": "preserve claims"}
    review = {
        "schema_version": "arw.writing-review.v1", "source_sha256": sha256_hex(source),
        "candidate_sha256": sha256_hex(source), "proposal_sha256": sha256_hex(canonical_json_bytes(proposal)),
        "verification_sha256": sha256_hex(canonical_json_bytes(verification)),
        "decision": "APPROVED", "reviewed_dimensions": [], "reviewer": "fixture.reviewer",
        "rationale": "Reviewed the exact candidate text.",
    }
    (paper / "review.json").write_bytes(canonical_json_bytes(review))
    review_event = _accept_paper_artifact(paper, "writing.review", "review.json", 9300, kind="writing-human-review").event
    def binding(event, digest):
        return {
            "artifact_id": event.payload.artifact_id, "event_id": event.event_id,
            "event_sha256": event.event_sha256, "manifest_sha256": event.payload.manifest_sha256,
            "sha256": digest,
        }
    forged = {
        "accepted": True, "disposition": "accepted_after_human_review", "controls_effective": True,
        "narrative_realization": value, "candidate": source.decode(),
        "candidate_sha256": sha256_hex(source), "candidate_path": value["source_path"],
        "source_sha256": sha256_hex(source), "source_binding": binding(source_event, sha256_hex(source)),
        "review_binding": binding(review_event, sha256_hex(canonical_json_bytes(review))),
        "proposal": proposal, "proposal_sha256": review["proposal_sha256"],
        "verification": verification, "verification_sha256": review["verification_sha256"],
    }
    (paper / "forged.json").write_bytes(canonical_json_bytes(forged))
    result = _accept_paper_artifact(paper, "writing.forged", "forged.json", 9301, kind="writing-derived")
    assert not result.accepted
    assert result.rejection.code == "writing_service_required"


@pytest.mark.parametrize("heading", [
    "# Research problem",
    "Research problem\n================",
    "# Problem\n## Gap",
    "Research\nproblem\n====",
    "# Problem\nResearch\nproblem\n====",
    "Research\nproblem\n====\n# Gap",
])
def test_heading_only_function_is_rejected_at_artifact_admission(paper, heading):
    value = _fixture(paper)
    raw = (paper / "paper.md").read_bytes()
    old_end = value["nodes"][0]["span"]["end"]
    replacement = heading.encode()
    raw = replacement + raw[old_end:]
    delta = len(replacement) - old_end
    value["source_sha256"] = sha256_hex(raw)
    for index, node in enumerate(value["nodes"]):
        span = node["span"]
        if index == 0:
            span.update(end=len(replacement), sha256=sha256_hex(replacement))
        else:
            span.update(start=span["start"] + delta, end=span["end"] + delta)
    (paper / "paper.md").write_bytes(raw)
    (paper / "outline-heading.json").write_bytes(canonical_json_bytes(value))
    result = _accept_paper_artifact(paper, "outline.heading", "outline-heading.json", 9401, kind="narrative-outline")
    assert not result.accepted
    assert result.rejection.code == "narrative_heading_only"


@pytest.mark.parametrize("problem", [
    "# Problem\nThe survey studies fragmented agent evaluation practices.",
    "Research\nproblem\n====\nThe survey studies fragmented agent evaluation practices.",
    "# Problem\nResearch\nproblem\n====\nThe survey studies fragmented agent evaluation practices.",
    "# Problem\n- We study evaluation.\n---",
    "> We study evaluation.\n---",
    "# Problem\n```text\nWe study evaluation.\n```\n---",
    "# Problem\n    We study evaluation.\n---",
])
def test_heading_with_body_and_survey_synthesis_remain_admissible(paper, problem):
    value = _fixture(paper)
    paragraphs = [
        problem,
        "Existing taxonomies omit important capability boundaries.",
        "The contribution is a comparison taxonomy.",
        "The classified studies support a bounded synthesis claim.",
        "The cited literature is compared using the stated taxonomy; no new experiment is claimed.",
        "The synthesis is restricted to the reviewed literature snapshot.",
    ]
    raw = "\n\n".join(paragraphs).encode()
    cursor = 0
    for node, paragraph in zip(value["nodes"], paragraphs):
        encoded = paragraph.encode()
        node["span"] = {"start": cursor, "end": cursor + len(encoded), "sha256": sha256_hex(encoded)}
        cursor += len(encoded) + 2
    value["nodes"][4]["evidence_form"] = "other"
    value["source_sha256"] = sha256_hex(raw)
    (paper / "paper.md").write_bytes(raw)
    report = validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert report["mechanical_status"] == "PASS"
    assert report["semantic_status"] == "UNKNOWN"
    assert "evidence_source_unknown" in report["human_review_reason_codes"]
    (paper / "outline-survey.json").write_bytes(canonical_json_bytes(value))
    assert _accept_paper_artifact(paper, "outline.survey", "outline-survey.json", 9403, kind="narrative-outline").accepted


def test_supplied_source_cannot_bypass_read_budget_or_symlink_root(paper, tmp_path):
    from arw.kernel.ledger.narrative_content import verify_realization_source
    from arw.kernel.ledger.source_locations import MAX_SOURCE_BYTES

    value = NarrativeRealization.model_validate(_fixture(paper))
    with pytest.raises(NarrativeRealizationError) as oversized:
        verify_realization_source(paper, value, source_bytes=b"x" * (MAX_SOURCE_BYTES + 1))
    assert oversized.value.code == "narrative_source_invalid"
    alias = tmp_path / "run-alias"
    alias.symlink_to(paper, target_is_directory=True)
    with pytest.raises(NarrativeRealizationError) as symlink:
        verify_realization_source(alias, value, source_bytes=(paper / "paper.md").read_bytes())
    assert symlink.value.code == "narrative_source_invalid"


def test_historical_heading_acceptance_replays_without_reinterpreting_policy(paper, monkeypatch):
    from arw.kernel.policy import narrative_realization as policy

    value = _fixture(paper)
    old = (paper / "paper.md").read_bytes()
    raw = b"# " + old
    first_end = value["nodes"][0]["span"]["end"] + 2
    value["nodes"][0]["span"].update(end=first_end, sha256=sha256_hex(raw[:first_end]))
    for node in value["nodes"][1:]:
        node["span"].update(start=node["span"]["start"] + 2, end=node["span"]["end"] + 2)
    value["source_sha256"] = sha256_hex(raw)
    (paper / "paper.md").write_bytes(raw)
    (paper / "historical-outline.json").write_bytes(canonical_json_bytes(value))
    # Simulate admission under the earlier v1 policy, preserving its exact event/report.
    with monkeypatch.context() as legacy:
        legacy.setattr(policy, "_heading_only", lambda _: False)
        accepted = _accept_paper_artifact(paper, "outline.historical", "historical-outline.json", 9402, kind="narrative-outline")
        assert accepted.accepted
    with pytest.raises(NarrativeRealizationError) as current_policy:
        validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert current_policy.value.code == "narrative_heading_only"
    assert replay_run(paper).recovery_health == "healthy"
