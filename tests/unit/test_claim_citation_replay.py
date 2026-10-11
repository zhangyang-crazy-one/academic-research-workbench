"""Trusted graph checks require typed parent acceptance and original replay."""

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger import claim_graph
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy import citations
from tests.integration.test_precise_source_locators import accept
from tests.unit.test_claim_graph import current_claim, record, registration, setup


def citation_fixture(tmp_path, *, typed):
    project, run = setup(tmp_path)
    reference = citations.ReferenceRecord(
        reference_id="ref.alpha",
        citation_key="Alpha",
        title="Evidence for Alpha",
        authors=("Smith",),
        year=2024,
        doi="10.1234/alpha",
    )
    response = b'{"message":{"items":[{"DOI":"10.1234/alpha"}]}}'
    receipt = citations.check_response(
        reference, "crossref", response, observed_at="2026-09-25T00:00:00Z"
    )
    if typed:
        (run / "reference.json").write_bytes(
            canonical_json_bytes(reference.model_dump(mode="json"))
        )
        assert accept(
            run, "artifact.reference", "reference.json", 41, kind="reference-record"
        ).accepted
        citations.publish_check(run, receipt, response)
        path = f"citations/receipts/sha256/{receipt.receipt_sha256}.json"
        kind = "citation-check-receipt"
    else:
        # A genuine digest-valid receipt, without accepted reference or response.
        path, kind = "ordinary-evidence.json", "research-evidence"
        (run / path).write_bytes(
            canonical_json_bytes(receipt.model_dump(mode="json", exclude={"batch_id"}))
        )
    assert accept(run, "artifact.check", path, 42, kind=kind).accepted
    view = claim_graph.graph(project, run_roots=(run,))
    ref = next(n["source"] for n in view["nodes"] if n.get("artifact_kind") == kind)
    record(
        project,
        run,
        registration(
            view,
            evidence=[
                {
                    "evidence_id": "evidence.metadata",
                    "node_kind": "ReferenceCheck",
                    "original": ref,
                }
            ],
        ),
    )
    return project, run, receipt


def test_generic_accepted_json_does_not_establish_trusted_check(tmp_path):
    project, run, _ = citation_fixture(tmp_path, typed=False)
    view = claim_graph.graph(project, run_roots=(run,))
    checks = current_claim(view)["checks"][0]["results"]
    assert checks[0]["status"] == "not_checked"
    assert checks[0]["reason"] == "citation_acceptance_unverified"
    assert replay_run(run).recovery_health == "healthy"


@pytest.mark.parametrize("damage", ["missing", "tampered", None])
def test_graph_delegates_original_response_replay(tmp_path, monkeypatch, damage):
    project, run, receipt = citation_fixture(tmp_path, typed=True)
    response = run / "citations/responses/sha256" / receipt.response_sha256
    if damage == "missing":
        response.unlink()
    elif damage == "tampered":
        response.write_bytes(b'{"message":{"items":[]}}')
    original = citations.replay_check
    calls = []

    def replay(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(citations, "replay_check", replay)
    view = claim_graph.graph(project, run_roots=(run,))
    checks = current_claim(view)["checks"][0]["results"]
    assert calls
    assert checks[0]["status"] == ("passed" if damage is None else "not_checked")
    if damage is None:
        assert "reason" not in checks[0]  # existing dependency bytes stay compatible
    else:
        assert checks[0]["reason"] == "citation_replay_unverifiable"
    assert replay_run(run).recovery_health == "healthy"
