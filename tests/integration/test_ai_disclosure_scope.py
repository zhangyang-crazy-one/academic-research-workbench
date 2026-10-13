"""Accepted mixed materials retain bounded proof scopes without poisoning history."""

import pytest

from arw.kernel.ledger import claim_graph
from arw.kernel.ledger.accepted_refs import ResolutionContext, resolve_ref
from arw.kernel.ledger.ai_disclosure import capture, make_draft, replay_draft
from arw.kernel.policy.research_integrity import research_source_from_ars_entry
from arw.kernel.state.accepted_ref import ParentArtifactRef
from arw.kernel.state.ai_disclosure import AIActivityReceipt
from tests.integration.test_ai_disclosure import accept, policy
from tests.unit.test_claim_graph import setup
from tests.unit.test_research_integrity import ARS_ENTRY, SOURCE_SHA256
from tests.unit.test_venue_learning import capsule_v2_documents


@pytest.mark.parametrize(
    "kind,scope", [("capsule", "structural_capsule"), ("manifest", "metadata_only")]
)
def test_mixed_materials_keep_manuscript_observed_and_replay(tmp_path, kind, scope):
    project, run = setup(tmp_path)
    before = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    target = ParentArtifactRef.model_validate(
        before["coverage"]["manuscripts"][0]["accepted_ref"]
    )
    context = ResolutionContext(target.project_id, (run,), project)
    receipt = AIActivityReceipt(
        activity_id="activity.manuscript",
        target=target,
        usage="ai_drafted",
        system="synthetic",
        harness="synthetic",
        model="synthetic",
        detail="Synthetic retained receipt.",
    )
    accept(
        run,
        target,
        receipt.model_dump(mode="json"),
        "ai-activity-receipt",
        "receipt.manuscript",
    )
    if kind == "capsule":
        value, _, _ = capsule_v2_documents()
    else:
        value = research_source_from_ars_entry(
            ARS_ENTRY,
            source_id="source.fixture",
            source_sha256=SOURCE_SHA256,
            imported_at="2026-08-26T01:02:03Z",
            imported_by="parent.runtime",
        ).model_dump(mode="json")
    other = accept(
        run,
        target,
        value,
        "venue-source-capsule" if kind == "capsule" else "research-source-manifest",
        "artifact.limited",
    )
    assert resolve_ref(other, context).proven_scope == scope
    summary = capture(context)
    manuscript = next(
        m
        for m in summary["materials"]
        if m["target"]["artifact_id"] == target.artifact_id
    )
    limited = next(
        m
        for m in summary["materials"]
        if m["target"]["artifact_id"] == "artifact.limited"
    )
    assert manuscript["ai_involvement"] == "observed"
    assert (
        limited["ai_involvement"] == "unknown"
        and limited["content_proof_scope"] == scope
    )
    draft = make_draft(context, policy())
    assert replay_draft(draft, context) == draft
    after = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    assert after["coverage"]["manuscripts"][0]["ai_involvement"] == "observed"
    assert before["hard_checks"] == after["hard_checks"]
    source_receipt = receipt.model_copy(
        update={"activity_id": "activity.source", "target": other}
    )
    accept(
        run,
        target,
        source_receipt.model_dump(mode="json"),
        "ai-activity-receipt",
        "receipt.source",
    )
    assert (
        next(
            m
            for m in capture(context)["materials"]
            if m["target"]["artifact_id"] == "artifact.limited"
        )["ai_involvement"]
        == "observed"
    )
    assert resolve_ref(other, context).proven_scope == scope
    (run / "artifact.limited.json").write_text("{}")
    with pytest.raises(ValueError):
        capture(context)
