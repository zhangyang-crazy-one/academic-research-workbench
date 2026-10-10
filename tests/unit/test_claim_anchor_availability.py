"""Cross-log evidence availability must not change canonical parent health."""

from __future__ import annotations

import shutil

import portalocker
import pytest

from arw.kernel.core.canonical import canonical_json_bytes, seal_event
from arw.kernel.ledger import claim_authority, claim_graph, narrative
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.state.claim_authentication import AuthenticatedAttestation
from tests.unit.test_claim_authentication import confirm, prepared, request
from tests.unit.test_claim_graph import current_claim, record, registration, setup
from tests.unit.test_narrative import plan, run_request


@pytest.mark.parametrize(
    "external_state", ["archived", "missing_project", "corrupt_journal"]
)
def test_parent_replay_is_independent_of_external_project(tmp_path, external_state):
    project, run, _, ref = prepared(tmp_path)
    confirm(project, run, ref)
    if external_state == "archived":
        run = shutil.copytree(run, tmp_path / "archived-run")
    elif external_state == "missing_project":
        (project / ".arw/project.json").unlink()
    else:
        path = project / narrative.RELATIVE
        path.write_bytes(path.read_bytes().replace(b"confirmed", b"tampered!"))
    replay = replay_run(run)
    assert replay.recovery_health == "healthy"
    assert replay.events[-1].event_type == "claim.attestation_anchored"


def test_129_real_admitted_anchors_do_not_poison_replay(tmp_path, monkeypatch):
    project, run, _, ref = prepared(tmp_path)
    initial = claim_graph.graph(project, run_roots=(run,))
    claim = current_claim(initial)
    for index in range(129):
        inputs = claim_graph._read_inputs(project, (run,))
        att = AuthenticatedAttestation(
            claim_id=claim["claim_id"],
            claim_revision=claim["revision"],
            claim_sha256=claim["claim_sha256"],
            evidence_dependency_sha256=claim["evidence_dependency_sha256"],
            statement=f"Independent confirmation {index}",
            scope=ref.scope,
            policy_version="policy.v1",
            graph_snapshot_sha256=inputs.manifest.sha256,
            snapshot_manifest=inputs.manifest,
            authority=ref,
        )
        with narrative._locked(project, write=True):
            events, snapshot, _ = narrative._read(project)
            event = narrative._append(
                project,
                events,
                "claim.attested",
                snapshot.version,
                att.model_dump(mode="json"),
            )
        out = claim_authority.anchor_attestation(
            project,
            run_roots=(run,),
            sequence=event["sequence"],
            request=request(run, 300 + index),
        )
        assert out["status"] == "authenticated", out

    def forbid_external_read(*args, **kwargs):
        pytest.fail("canonical parent replay accessed external claim evidence")

    monkeypatch.setattr(claim_authority, "verify_anchor_journal", forbid_external_read)
    monkeypatch.setattr(claim_authority, "_read_inputs", forbid_external_read)
    replay = replay_run(run)
    assert replay.recovery_health == "healthy"
    assert (
        sum(e.event_type == "claim.attestation_anchored" for e in replay.events) == 129
    )


def test_locked_sibling_does_not_block_parent_and_proof_is_unverifiable(tmp_path):
    project, run, _, ref = prepared(tmp_path)
    sibling = project / "runs/sibling"
    init = run_request(project).model_copy(
        update={"run_id": "run-00000000-0000-4000-8000-000000000098"}
    )
    (sibling / "input").mkdir(parents=True)
    (sibling / "input/source.txt").write_text("test source\n", encoding="utf-8")
    initialize_run(sibling, init)
    before = claim_graph.graph(project, run_roots=(run, sibling))
    out = claim_authority.attest_authenticated(
        project,
        run_roots=(run, sibling),
        expected_head=before["snapshot_sha256"],
        claim_id="claim.relation",
        authority=ref,
        statement="Multi-run confirmation",
        scope=ref.scope,
        policy_version="policy.v1",
        request=request(run, 202),
    )
    assert out["status"] == "authenticated"
    with portalocker.Lock(
        sibling / ".journal.lock",
        mode="a+b",
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    ):
        assert replay_run(run).recovery_health == "healthy"
        inputs = claim_graph._read_inputs(project, (run, sibling))
        registered = claim_graph._registrations(inputs.journal)["claim.relation"]
        dependency = claim_graph._evaluate_registration(registered, inputs)[1]
        proof = claim_graph._attestations(registered, dependency, inputs)[0]
        assert proof["status"] == "unverifiable"
        assert proof["historical_authorized"] is False
        # Source resolution also needs the sibling's included prefix. A whole
        # projection cannot certify the vector while that writer holds its lock.
        with pytest.raises(claim_graph.ClaimGraphError):
            claim_graph.graph(project, run_roots=(run, sibling), hard_check=True)


def test_canonical_replay_still_rejects_local_authority_tampering(tmp_path):
    project, run, _, ref = prepared(tmp_path)
    confirm(project, run, ref)
    path = run / "journal/segments/00000001.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    anchor = replay_run(run).events[-1].model_dump(mode="json")
    anchor["payload"]["attestation"]["scope"] = "Other scope."
    anchor["payload"]["attestation"]["authority"]["scope"] = "Other scope."
    changed = seal_event(anchor)
    path.write_bytes(b"".join(lines[:-1]) + canonical_json_bytes(changed))
    assert replay_run(run).recovery_health == "blocked"


def test_registration_validation_is_incremental_within_each_read(tmp_path, monkeypatch):
    project, run = setup(tmp_path)
    view = claim_graph.graph(project, run_roots=(run,))
    for index in range(20):
        record(project, run, registration(view, claim_id=f"claim.item{index}"))
    calls = []
    original = claim_graph.ClaimRegistration.model_validate

    def counted(value, *args, **kwargs):
        calls.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(claim_graph.ClaimRegistration, "model_validate", counted)
    narrative._read(project)
    assert len(calls) == 20
    calls.clear()
    narrative._read(project)
    assert len(calls) == 20  # Each query freshly validates actual disk bytes.


def test_claim_capacity_reserves_core_propose_withdraw_budget(tmp_path, monkeypatch):
    project, run = setup(tmp_path)
    view = claim_graph.graph(project, run_roots=(run,))
    current_size = (project / narrative.RELATIVE).stat().st_size
    reserve = 8192
    monkeypatch.setattr(narrative, "CORE_HISTORY_RESERVE", reserve)
    monkeypatch.setattr(narrative, "MAX_HISTORY", current_size + reserve)
    with pytest.raises(narrative.NarrativeError) as error:
        record(project, run, registration(view))
    assert error.value.code == "claim_history_full"
    assert (project / narrative.RELATIVE).stat().st_size == current_size
    selected = narrative._read(project)[1]
    narrative.propose(
        project,
        plan("theory"),
        expected_sha256=selected.sha256,
        reason="Consider a new core strategy.",
    )
    assert narrative._read(project)[2] is not None
