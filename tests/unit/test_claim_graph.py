"""Issue #94 multi-log fixtures 4–7, 9, 10 and 14."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger import claim_graph, narrative
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.state.claim_graph import ClaimRegistration, SnapshotManifest
from arw.kernel.state.models import InitRunRequest
from tests.unit.test_narrative import project, plan
from tests.integration.test_precise_source_locators import SOURCE, seed, accept

TEXT = "研究 3.1% [@a] [@b]。研究 3.1% [@a] [@b]。 Novelty statement.\nFigure 1. Accuracy 92%."


def setup(tmp_path):
    p = project(tmp_path)
    narrative.register(p)
    narrative.select(p, plan())
    root, _ = seed(p)
    (root / "draft.txt").write_text(TEXT, encoding="utf-8")
    assert accept(root, "artifact.draft", "draft.txt", 40, kind="manuscript").accepted
    return p, root


def occurrences(view, kind="citation_sentence"):
    return sorted(
        (
            n
            for n in view["nodes"]
            if n["node_kind"] == "Occurrence" and n["kind"] == kind
        ),
        key=lambda n: n["offset"],
    )


def registration(
    view,
    claim_id="claim.relation",
    evidence=(),
    relations=(),
    statement="The method is related to the outcome.",
    revision=1,
    supersedes=None,
):
    occurrence = {
        k: v
        for k, v in occurrences(view)[0].items()
        if k not in ("id", "node_kind", "registration")
    }
    return ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": claim_id,
                "revision": revision,
                "statement": statement,
                "claim_kind": "interpretation",
                "supersedes": supersedes,
            },
            "occurrences": [occurrence],
            "evidence": list(evidence),
            "relations": list(relations),
            "author_id": "author.owner",
        }
    )


def current_claim(view, claim_id="claim.relation"):
    return next(
        n
        for n in view["nodes"]
        if n["node_kind"] == "Claim" and n["claim_id"] == claim_id
    )


def record(p, r, reg, *, evidence_update=False):
    view = claim_graph.graph(p, run_roots=(r,))
    return claim_graph.register_claim(
        p,
        reg,
        run_roots=(r,),
        expected_head=view["snapshot_sha256"],
        evidence_update=evidence_update,
    )


def attest(p, r):
    before = claim_graph.graph(p, run_roots=(r,))
    out = claim_graph.attest_declared(
        p,
        run_roots=(r,),
        expected_head=before["snapshot_sha256"],
        claim_id="claim.relation",
        author_id="author.owner",
        statement="I confirmed this inference.",
        scope="Interpretation in this sentence only.",
        policy_version="policy.v1",
    )
    return before, out


def test_duplicate_utf8_occurrences_and_multiclaim_never_merge(tmp_path):
    p, r = setup(tmp_path)
    before = {
        path.relative_to(p): path.read_bytes()
        for path in p.rglob("*")
        if path.is_file()
    }
    view = claim_graph.graph(p, run_roots=(r,))
    assert view == claim_graph.graph(p, run_roots=(r,))
    assert before == {
        path.relative_to(p): path.read_bytes()
        for path in p.rglob("*")
        if path.is_file()
    }
    cited = occurrences(view)
    assert (
        len(cited) == 2
        and cited[0]["offset"] == 0
        and cited[1]["offset"] == len("研究 3.1% [@a] [@b]。".encode())
    )
    assert (
        cited[0]["selected_sha256"] == cited[1]["selected_sha256"]
        and cited[0]["id"] != cited[1]["id"]
    )
    assert len(occurrences(view, "numeric_token")) == 4
    assert len(occurrences(view, "figure_caption")) == 1
    record(p, r, registration(view))
    record(
        p,
        r,
        registration(
            view,
            claim_id="claim.second",
            statement="The separate proposition remains limited.",
        ),
    )
    graph = claim_graph.graph(p, run_roots=(r,))
    expresses = [e for e in graph["edges"] if e["relation"] == "expresses"]
    assert (
        len(expresses) == 2
        and len({e["source"] for e in expresses}) == 1
        and len({e["target"] for e in expresses}) == 2
    )
    assert graph["coverage"]["registered_occurrence_count"] == 1
    assert graph["coverage"]["registered_claim_count"] == 2
    assert graph["coverage"]["out_of_scope_sentence_count"] == 1
    assert graph["coverage"]["unknown_occurrence_count"] == 6
    assert graph["coverage"]["unobserved_claims"] == "unknown"
    assert graph["coverage"]["manuscripts"][0]["ai_involvement"] == "unknown"


def test_current_optimistic_read_detects_only_run_advance(tmp_path, monkeypatch):
    p, r = setup(tmp_path)
    old = claim_graph.graph(p, run_roots=(r,))
    original = claim_graph._project

    def advances(inputs):
        result = original(inputs)
        (r / "extra.txt").write_text("extra")
        assert accept(r, "artifact.extra", "extra.txt", 41, kind="source").accepted
        return result

    monkeypatch.setattr(claim_graph, "_project", advances)
    with pytest.raises(claim_graph.ClaimGraphError) as error:
        claim_graph.graph(p, run_roots=(r,))
    assert error.value.code == "stale"
    monkeypatch.setattr(claim_graph, "_project", original)
    assert claim_graph.graph(p, run_roots=(r,), as_of=old["snapshot_manifest"]) == old
    with pytest.raises(claim_graph.ClaimGraphError) as stale:
        claim_graph.graph(p, run_roots=(r,), expected_head=old["snapshot_sha256"])
    assert stale.value.code == "stale"


def test_current_optimistic_read_detects_only_journal_advance(tmp_path, monkeypatch):
    p, r = setup(tmp_path)
    old = claim_graph.graph(p, run_roots=(r,))
    original = claim_graph._project

    def advances(inputs):
        result = original(inputs)
        narrative.propose(
            p,
            plan("theory"),
            expected_sha256=narrative.current(p).sha256,
            reason="The author considered the theoretical route.",
        )
        return result

    monkeypatch.setattr(claim_graph, "_project", advances)
    with pytest.raises(claim_graph.ClaimGraphError) as error:
        claim_graph.graph(p, run_roots=(r,))
    assert error.value.code == "stale"
    monkeypatch.setattr(claim_graph, "_project", original)
    assert claim_graph.graph(p, run_roots=(r,), as_of=old["snapshot_manifest"]) == old


def test_declared_n_minus_one_revision_staleness_and_decision_separation(tmp_path):
    p, r = setup(tmp_path)
    view = claim_graph.graph(p, run_roots=(r,))
    reg = registration(view)
    record(p, r, reg)
    before, out = attest(p, r)
    assert out["sequence"] == before["snapshot_manifest"]["journal"]["sequence"] + 1
    assert out["graph_snapshot_sha256"] == before["snapshot_sha256"]
    event = narrative._read(p)[0][-1]
    assert (
        event["payload"]["snapshot_manifest"]["journal"]["head_sha256"]
        == event["previous_sha256"]
    )
    assert event["payload"]["graph_snapshot_sha256"] != event["event_sha256"]
    view = claim_graph.graph(p, run_roots=(r,))
    old = current_claim(view)
    assert old["attestations"][0]["status"] == "declared"
    assert old["attestations"][0]["historical_authorized"] is False
    revised = registration(
        view,
        statement="The method causes the outcome.",
        revision=2,
        supersedes=reg.claim.sha256,
    )
    record(p, r, revised)
    latest = claim_graph.graph(p, run_roots=(r,))
    assert current_claim(latest)["attestations"][0]["status"] == "stale"
    assert current_claim(latest)["revision"] == 2
    assert any(
        n["node_kind"] == "Decision"
        and n.get("attestation_scope") == "direction_decision_only"
        for n in latest["nodes"]
    )
    assert (
        claim_graph.graph(p, run_roots=(r,), as_of=before["snapshot_manifest"])
        == before
    )
    assert narrative.trail(p)["choices"][0]["disposition"] == "kept"
    assert narrative.status(p)["status"] == "selected"
    with pytest.raises(claim_graph.ClaimGraphError) as error:
        claim_graph.graph(p, run_roots=(r,), hard_check=True)
    assert error.value.code == "hard_check_unavailable"


def test_evidence_update_stales_without_semantic_revision(tmp_path):
    p, r = setup(tmp_path)
    view = claim_graph.graph(p, run_roots=(r,))
    reg = registration(view)
    record(p, r, reg)
    attest(p, r)
    source = next(
        n["source"] for n in view["nodes"] if n.get("artifact_kind") == "source"
    )
    payload = reg.model_dump(mode="json")
    payload["evidence"] = [
        {
            "evidence_id": "evidence.source",
            "node_kind": "LiteratureEvidence",
            "original": source,
        }
    ]
    changed = ClaimRegistration.model_validate(payload)
    record(p, r, changed, evidence_update=True)
    now = claim_graph.graph(p, run_roots=(r,))
    claim = current_claim(now)
    assert claim["revision"] == 1 and claim["claim_sha256"] == reg.claim.sha256
    assert claim["attestations"][0]["status"] == "stale"
    assert claim["integrity"][0]["integrity"] == "resolved"
    assert claim["relations"] == []


def test_hash_prefix_and_closure_with_real_second_run(tmp_path):
    p, r = setup(tmp_path)
    second = p / "runs/two"
    second.mkdir(parents=True)
    (second / "input.txt").write_bytes(SOURCE)
    new_id = "run-00000000-0000-4000-8000-000000000098"
    initialize_run(
        second,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": new_id,
                "occurred_at": "2026-09-08T00:00:00Z",
                "immutable_input": {"path": "input.txt", "sha256": sha256_hex(SOURCE)},
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "event_id": "evt-00000000-0000-4000-8000-000000000001",
                "command_id": "cmd-00000000-0000-4000-8000-000000000001",
                "actor_id": "parent.runtime",
                "capabilities": ["canonical-journal"],
            }
        ),
    )
    view = claim_graph.graph(p, run_roots=(r, second))
    assert len(view["snapshot_manifest"]["runs"]) == 2
    record(p, r, registration(claim_graph.graph(p, run_roots=(r,))))
    now = claim_graph.graph(p, run_roots=(r, second))
    assert (
        claim_graph.graph(p, run_roots=(r, second), as_of=view["snapshot_manifest"])
        == view
    )
    mixed = deepcopy(now["snapshot_manifest"])
    first = next(c for c in mixed["runs"] if c["run_id"] == replay_run(r).run_id)
    first["revision"] = 1
    first["head_sha256"] = replay_run(r).events[0].event_sha256
    with pytest.raises(claim_graph.ClaimGraphError) as error:
        claim_graph.graph(p, run_roots=(r, second), as_of=mixed)
    assert error.value.code == "dependency_outside_prefix"
    wrong = deepcopy(now["snapshot_manifest"])
    wrong["journal"]["head_sha256"] = "0" * 64
    with pytest.raises(claim_graph.ClaimGraphError):
        claim_graph.graph(p, run_roots=(r, second), as_of=wrong)
    (r / "journal/segments/00000001.jsonl").open("ab").write(b"{broken later tail")
    assert (
        claim_graph.graph(p, run_roots=(r, second), as_of=view["snapshot_manifest"])
        == view
    )


def test_missing_evidence_is_not_refutation_and_ai_assessment_keeps_direction(tmp_path):
    p, r = setup(tmp_path)
    view = claim_graph.graph(p, run_roots=(r,))
    original = {"kind": "issue", "target": "example", "relation": "supports"}
    evidence = [
        {
            "evidence_id": "evidence.issue",
            "node_kind": "LiteratureEvidence",
            "adapter": "memory_link",
            "original": original,
        }
    ]
    reg = registration(view, evidence=evidence)
    payload = reg.model_dump(mode="json")
    payload["assessments"] = [
        {
            "evidence_id": "evidence.issue",
            "direction": "contradicts",
            "source": "reviewer.model",
            "confidence": 0.75,
            "provenance": {"kind": "ai_review"},
        }
    ]
    record(p, r, ClaimRegistration.model_validate(payload))
    result = claim_graph.graph(p, run_roots=(r,))
    claim = current_claim(result)
    assert claim["integrity"][0]["integrity"] == "missing"
    assert claim["relations"] == []
    assert claim["assessments"][0]["direction"] == "contradicts"
    assert claim["assessments"][0]["advisory"] is True


def test_verified_metadata_and_contradiction_remain_independent(tmp_path):
    from arw.kernel.policy.citations import (
        ReferenceRecord,
        check_response,
        publish_check,
    )

    p, r = setup(tmp_path)
    reference = ReferenceRecord(
        reference_id="ref.alpha",
        citation_key="Alpha",
        title="Evidence for Alpha",
        authors=("Smith",),
        year=2024,
        doi="10.1234/alpha",
    )
    (r / "reference.json").write_bytes(
        canonical_json_bytes(reference.model_dump(mode="json"))
    )
    assert accept(
        r, "artifact.reference", "reference.json", 41, kind="reference-record"
    ).accepted
    response = b'{"message":{"items":[{"DOI":"10.1234/alpha"}]}}'
    receipt = check_response(
        reference, "crossref", response, observed_at="2026-09-25T00:00:00Z"
    )
    publish_check(r, receipt, response)
    receipt_path = f"citations/receipts/sha256/{receipt.receipt_sha256}.json"
    assert accept(
        r, "artifact.reference-check", receipt_path, 42, kind="citation-check-receipt"
    ).accepted
    view = claim_graph.graph(p, run_roots=(r,))
    ref = next(
        n["source"]
        for n in view["nodes"]
        if n.get("artifact_kind") == "citation-check-receipt"
    )
    reg = registration(
        view,
        evidence=[
            {
                "evidence_id": "evidence.metadata",
                "node_kind": "ReferenceCheck",
                "original": ref,
            }
        ],
        relations=[
            {
                "evidence_id": "evidence.metadata",
                "relation": "contradicts",
                "asserted_by": "author.owner",
                "basis": "The checked source contradicts the inference.",
            }
        ],
    )
    record(p, r, reg)
    attest(p, r)
    graph = claim_graph.graph(p, run_roots=(r,))
    claim = current_claim(graph)
    assert claim["checks"][0]["results"][0]["status"] == "passed"
    assert claim["checks"][0]["results"][0]["scope"] == "bibliographic_metadata_only"
    assert claim["relations"][0]["relation"] == "contradicts"
    assert claim["attestations"][0]["status"] == "declared"
    assert "supported" not in claim and "scientific_status" not in claim
    retained = (r / receipt_path).read_bytes()
    assert retained == canonical_json_bytes(
        receipt.model_dump(mode="json", exclude={"batch_id"})
    )


def test_retained_v2_spans_are_reused_and_legacy_locations_stay_unknown(tmp_path):
    from arw_writing.preservation import verify, resolve_citation_bindings

    p, r = setup(tmp_path)
    # A canonical accepted receipt container retains the exact #86 table. Its
    # historical contents are not rewritten into a new representation.
    raw = TEXT
    verification = verify(raw, raw, [], [])
    receipt = {
        "candidate": raw,
        "source": raw,
        "candidate_sha256": sha256_hex(raw.encode()),
        "verification": verification,
    }
    (r / "receipt.json").write_bytes(canonical_json_bytes(receipt))
    assert accept(
        r, "artifact.container", "receipt.json", 41, kind="research-evidence"
    ).accepted
    base = claim_graph.graph(p, run_roots=(r,))
    ref = next(
        n["source"]
        for n in base["nodes"]
        if n.get("artifact_kind") == "research-evidence"
    )
    inputs = claim_graph._read_inputs(p, (r,))
    selected, metadata = claim_graph._extract(ref, inputs)
    scopes = [o for o in selected if o.kind == "citation_sentence"]
    assert [(o.offset, o.length, o.selected_sha256) for o in scopes] == [
        (s["offset"], s["length"], s["sha256"])
        for s in verification["citation_bindings"]["candidate"]["assertions"]
    ]
    assert all(o.locator_version == "arw.writing-citation-bindings.v2" for o in scopes)
    assert metadata["citation_locator_scope"] == "retained_v2_byte_spans"
    # Explicit /candidate still reuses its container table, not a fresh split.
    selected_ref = {**ref, "selector": "/candidate"}
    selected, _ = claim_graph._extract(selected_ref, inputs)
    assert [
        (o.offset, o.length) for o in selected if o.kind == "citation_sentence"
    ] == [(o.offset, o.length) for o in scopes]
    original_bytes = (r / "receipt.json").read_bytes()
    assert original_bytes == canonical_json_bytes(receipt)
    legacy = deepcopy(receipt)
    legacy["verification"]["citation_bindings"] = resolve_citation_bindings(
        verification, raw, raw
    )
    (r / "legacy.json").write_bytes(canonical_json_bytes(legacy))
    assert accept(
        r, "artifact.legacy", "legacy.json", 42, kind="research-evidence"
    ).accepted
    inputs = claim_graph._read_inputs(p, (r,))
    latest = claim_graph.graph(p, run_roots=(r,))
    legacy_ref = next(
        n["source"]
        for n in latest["nodes"]
        if n.get("source", {}).get("artifact_id") == "artifact.legacy"
    )
    extracted, meta = claim_graph._extract(legacy_ref, inputs)
    assert not any(o.kind == "citation_sentence" for o in extracted)
    assert meta["unknown_citation_locations"] == 4
    assert meta["citation_locator_scope"] == "legacy_sentence_scopes_location_unknown"
    assert (r / "receipt.json").read_bytes() == original_bytes


def test_journal_tamper_and_new_torn_tail_are_separated(tmp_path):
    p, r = setup(tmp_path)
    original = claim_graph.graph(p, run_roots=(r,))
    record(p, r, registration(original))
    path = p / narrative.RELATIVE
    valid = path.read_bytes()
    path.open("ab").write(b"{broken later journal tail")
    assert (
        claim_graph.graph(p, run_roots=(r,), as_of=original["snapshot_manifest"])
        == original
    )
    with pytest.raises(claim_graph.ClaimGraphError) as corrupt:
        claim_graph.graph(p, run_roots=(r,))
    assert corrupt.value.code == "corrupt_log"
    path.write_bytes(valid.replace(b"method_rq", b"corruptxx"))
    with pytest.raises(claim_graph.ClaimGraphError):
        claim_graph.graph(p, run_roots=(r,), as_of=original["snapshot_manifest"])


def test_registered_span_tampering_and_author_assertion_fail_before_write(tmp_path):
    from arw.cli_claims import configure, handle
    from argparse import ArgumentParser

    p, r = setup(tmp_path)
    view = claim_graph.graph(p, run_roots=(r,))
    reg = registration(view)
    altered = reg.model_dump(mode="json")
    altered["occurrences"][0]["offset"] += 1
    raw = (p / narrative.RELATIVE).read_bytes()
    with pytest.raises(claim_graph.ClaimGraphError):
        record(p, r, ClaimRegistration.model_validate(altered))
    assert (p / narrative.RELATIVE).read_bytes() == raw
    parser = ArgumentParser()
    configure(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(
        [
            "claims",
            "attest",
            "--project-root",
            str(p),
            "--run-root",
            str(r),
            "--expected-head",
            view["snapshot_sha256"],
            "--claim-id",
            "claim.relation",
            "--author-id",
            "owner",
            "--statement",
            "Reviewed inference",
            "--scope",
            "sentence",
            "--policy-version",
            "policy.v1",
        ]
    )
    with pytest.raises(claim_graph.ClaimGraphError) as error:
        handle(args)
    assert error.value.code == "author_confirmation_missing"
    assert (p / narrative.RELATIVE).read_bytes() == raw


def test_schema_strictness_and_checked_in_contracts(tmp_path):
    import json
    import jsonschema
    from arw.kernel.state.claim_graph import claim_graph_schema_documents
    from pydantic import ValidationError

    p, r = setup(tmp_path)
    view = claim_graph.graph(p, run_roots=(r,))
    vector = view["snapshot_manifest"]
    with pytest.raises(ValidationError):
        SnapshotManifest.model_validate({**vector, "revision": 1})
    for name, generated in claim_graph_schema_documents().items():
        retained = json.loads(
            (Path(__file__).parents[2] / "schemas/v1" / name).read_text()
        )
        assert retained == generated
        jsonschema.Draft202012Validator.check_schema(retained)
    jsonschema.Draft202012Validator(
        claim_graph_schema_documents()["claim-graph-snapshot.schema.json"]
    ).validate(vector)


def test_legacy_accepted_link_is_preserved_without_guessing_revision(tmp_path):
    p, r = setup(tmp_path)
    link = {
        "schema_version": "arw.claim-evidence-link.v1",
        "claim_link_id": "link.legacy",
        "claim_id": "claim.legacy",
        "claim_sha256": "a" * 64,
        "evidence_span_sha256": ["b" * 64],
        "relation": "contradicts",
    }
    raw = canonical_json_bytes(link)
    (r / "link.json").write_bytes(raw)
    assert accept(
        r, "artifact.legacy-link", "link.json", 41, kind="research-evidence"
    ).accepted
    result = claim_graph.graph(p, run_roots=(r,))
    imported = result["recorded_relations"][0]
    assert imported["relation"] == "contradicts" and imported["claim_revision"] is None
    assert imported["binding_status"] == "unbound_claim_revision"
    assert imported["asserted_by"] == "parent.runtime"
    assert not any(e["relation"] == "contradicts" for e in result["edges"])
    assert (r / "link.json").read_bytes() == raw
