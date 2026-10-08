"""Authenticated caption targets have no confirmation-ref hash cycle."""

from __future__ import annotations

from dataclasses import replace

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger import claim_graph, narrative
from arw.kernel.ledger.claim_authority import attest_authenticated
from arw.kernel.state.accepted_ref import JournalEventRef
from arw.kernel.state.claim_graph import ClaimRegistration, Occurrence
from arw.kernel.state.result_plot import PlotDisplay
from arw_research_artifact.plot_authority import CanonicalCaptionAttestationVerifier
from arw_research_artifact.plot_policy import (
    caption_target,
    compile_plot,
    caption_checks,
)
from arw_research_artifact.service import ResearchArtifactService
from tests.integration.test_claim_plot_bindings import accept_file
from tests.integration.test_result_plots import (
    result_fixture,
    plot,
    aggregate,
    binding,
    attach_bridge,
)
from tests.integration.test_research_artifacts import request as parent_request
from tests.unit.test_claim_authentication import authority, request
from tests.unit.test_narrative import plan


def prepare(tmp_path):
    run, context, ref, _ = result_fixture(tmp_path)
    project = context.project_root
    narrative.register(project)
    narrative.select(project, plan())
    caption = "Accuracy 0.83 [@a]."
    layer = aggregate(ref).model_copy(update={"display": PlotDisplay(decimals=2)})
    ir = plot((layer,), caption=caption)
    compiled = compile_plot(ir, context)
    bind = binding(compiled.plot_values[0], len("Accuracy "), len("Accuracy 0.83"))
    ir = ir.model_copy(update={"caption_bindings": (bind,)})
    compiled = compile_plot(ir, context)
    target = caption_target(compiled, bind)
    target_sha = sha256_hex(canonical_json_bytes(target))
    accept_file(run, "caption.txt", caption.encode(), 200)
    view = claim_graph.graph(project, run_roots=(run,))
    occurrence = next(
        n
        for n in view["nodes"]
        if n["node_kind"] == "Occurrence" and n["kind"] == "citation_sentence"
    )
    reg = ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": "claim.caption",
                "revision": 1,
                "statement": caption,
                "claim_kind": "result",
            },
            "occurrences": [
                {k: v for k, v in occurrence.items() if k in Occurrence.model_fields}
            ],
            "evidence": [
                {
                    "evidence_id": "evidence.data",
                    "node_kind": "ExperimentResult",
                    "original": ref.model_dump(mode="json"),
                }
            ],
            "author_id": "author.owner",
        }
    )
    claim_graph.register_claim(
        project, reg, run_roots=(run,), expected_head=view["snapshot_sha256"]
    )
    _, auth = authority(run, scope="caption:" + target_sha)
    view = claim_graph.graph(project, run_roots=(run,))
    out = attest_authenticated(
        project,
        run_roots=(run,),
        expected_head=view["snapshot_sha256"],
        claim_id="claim.caption",
        authority=auth,
        statement="I confirm this exact caption numeric target.",
        scope=auth.scope,
        policy_version="policy.v1",
        request=request(run, 202),
    )
    confirmation = JournalEventRef(
        project_id=context.project_id,
        sequence=out["journal_sequence"],
        event_sha256=out["journal_event_sha256"],
    )
    bound = bind.model_copy(
        update={"confirmation_ref": confirmation, "confirmation": "authenticated"}
    )
    authenticated_ir = ir.model_copy(update={"caption_bindings": (bound,)})
    return project, run, context, authenticated_ir, target_sha


def test_real_parent_authenticated_caption_target_is_stable_without_self_reference(
    tmp_path,
):
    project, run, context, ir, target_sha = prepare(tmp_path)
    compiled = compile_plot(ir, context)
    bind = ir.caption_bindings[0]
    assert (
        sha256_hex(canonical_json_bytes(caption_target(compiled, bind))) == target_sha
    )
    verifier = CanonicalCaptionAttestationVerifier()
    proof = verifier.verify(compiled, bind, resolution_context=context)
    assert proof.status == "verified" and proof.target_sha256 == target_sha
    assert proof.evidence_sha256
    checks = caption_checks(
        compiled,
        resolution_context=context,
        hard_caption_checks=True,
        attestation_verifier=verifier,
    )
    assert any(
        c.code == "caption_binding_matches" and c.status == "PASS" for c in checks
    )
    assert not any(
        c.category == "caption" and c.status in {"FAIL", "unsupported", "unknown"}
        for c in checks
    )
    # Changing caller labels and confirmation handle changes the complete IR
    # digest, but never changes the independently frozen semantic target.
    changed = bind.model_copy(update={"confirmation": "unknown"})
    assert (
        sha256_hex(canonical_json_bytes(caption_target(compiled, changed)))
        == target_sha
    )
    forged = bind.model_copy(
        update={"confirmation_ref": None, "confirmation": "authenticated"}
    )
    assert (
        verifier.verify(compiled, forged, resolution_context=context).status
        == "auth_missing"
    )
    wrong = bind.model_copy(update={"category": "B"})
    assert (
        verifier.verify(compiled, wrong, resolution_context=context).status
        == "auth_missing"
    )
    bridged = attach_bridge(ir, run, context, number=230)
    accepted = ResearchArtifactService().qualify(
        bridged,
        run_root=run,
        request=parent_request(run, 240),
        resolution_context=context,
        hard_caption_checks=True,
        attestation_verifier=verifier,
    )
    assert accepted["accepted"], accepted
    assert accepted["receipt"]["qualification"] == "PASS"


def test_caption_wrong_or_unanchored_confirmation_remains_auth_missing(tmp_path):
    project, run, context, ir, target_sha = prepare(tmp_path)
    compiled = compile_plot(ir, context)
    binding = ir.caption_bindings[0]
    verifier = CanonicalCaptionAttestationVerifier()
    wrong_ref = binding.confirmation_ref.model_copy(update={"event_sha256": "f" * 64})
    assert (
        verifier.verify(
            compiled,
            binding.model_copy(update={"confirmation_ref": wrong_ref}),
            resolution_context=context,
        ).status
        == "auth_missing"
    )
    # A historical vector that excludes the real anchor cannot import a
    # current authorization from outside its fixed parent prefix.
    from arw.kernel.ledger.accepted_refs import RunPrefix
    from arw.kernel.ledger.journal import replay_run

    replay = replay_run(run)
    before = replay.events[-2]
    fixed = replace(
        context,
        run_prefixes=(
            RunPrefix(
                run_id=replay.run_id,
                revision=before.resulting_revision,
                head_sha256=before.event_sha256,
                run_manifest_sha256=replay.events[0].payload.manifest_sha256,
            ),
        ),
        journal_sequence=narrative._read(project)[0][-1]["sequence"],
        journal_head_sha256=narrative._read(project)[0][-1]["event_sha256"],
    )
    proof = verifier.verify(compiled, binding, resolution_context=fixed)
    assert proof.status == "auth_missing"


def test_declared_caption_scope_cannot_become_authenticated_by_ir_labels(tmp_path):
    project, run, context, ir, target_sha = prepare(tmp_path)
    from arw.kernel.ledger.claim_graph import attest_declared

    view = claim_graph.graph(project, run_roots=(run,))
    out = attest_declared(
        project,
        run_roots=(run,),
        expected_head=view["snapshot_sha256"],
        claim_id="claim.caption",
        author_id="author.owner",
        statement="Declared caption review",
        scope="caption:" + target_sha,
        policy_version="policy.v1",
    )
    declared = JournalEventRef(
        project_id=context.project_id,
        sequence=out["sequence"],
        event_sha256=out["event_sha256"],
    )
    binding = ir.caption_bindings[0].model_copy(
        update={"confirmation_ref": declared, "confirmation": "authenticated"}
    )
    changed = ir.model_copy(update={"caption_bindings": (binding,)})
    compiled = compile_plot(changed, context)
    assert (
        sha256_hex(canonical_json_bytes(caption_target(compiled, binding)))
        == target_sha
    )
    proof = CanonicalCaptionAttestationVerifier().verify(
        compiled, binding, resolution_context=context
    )
    assert proof.status == "auth_missing" and proof.evidence_sha256 is None
