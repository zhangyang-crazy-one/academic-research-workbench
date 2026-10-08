"""Parent anchored authentication uses N-1 authorization and event-time bounds."""

from __future__ import annotations

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph, narrative
from arw.kernel.ledger.claim_authority import anchor_attestation, attest_authenticated
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.reducer import ReducerError, validate_claim_authority_envelope
from arw.kernel.state.claim_authentication import (
    AuthenticatedAttestation,
    AuthenticatedAuthority,
)
from arw.kernel.state.models import HumanAuthorityAcceptedPayload, RuntimeCommandRequest
from arw.kernel.state.orchestration_models import HumanAuthority
from tests.unit.test_claim_graph import current_claim, record, registration, setup


def request(run, number=202, at="2026-09-08T00:04:00Z"):
    replay = replay_run(run)
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": replay.run_id,
            "occurred_at": at,
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
        }
    )


def authority(run, scope="Interpretation in this sentence only."):
    value = HumanAuthority.model_validate(
        {
            "schema_version": "arw.human-authority.v1",
            "authority_id": "authority.claims",
            "authenticated_actor_id": "author.owner",
            "accountable_role": "operator",
            "validated_by_actor_id": "parent.runtime",
            "allowed_decision_kinds": ["claim_attest"],
            "allowed_gate_ids": ["gate.claims"],
            "allowed_scopes": [scope],
            "authenticated_at": "2026-09-08T00:03:00Z",
            "expires_at": "2026-09-08T00:10:00Z",
            "evidence_sha256": ["f" * 64],
        }
    )
    outcome = RuntimeCommandService(run).append_phase4_event(
        request(run, 201, at="2026-09-08T00:03:00Z"),
        event_type="human_authority.accepted",
        payload=HumanAuthorityAcceptedPayload(
            authority=value, authority_sha256=value.authority_sha256
        ),
    )
    assert outcome.accepted, outcome.rejection
    event = outcome.event
    ref = AuthenticatedAuthority(
        authority_run_id=event.run_id,
        authority_event_id=event.event_id,
        authority_event_sha256=event.event_sha256,
        human_authority_sha256=value.authority_sha256,
        accountable_actor_id="author.owner",
        accountable_role="operator",
        gate_id="gate.claims",
        scope=scope,
    )
    return value, ref


def prepared(tmp_path):
    project, run = setup(tmp_path)
    view = claim_graph.graph(project, run_roots=(run,))
    record(project, run, registration(view))
    value, ref = authority(run)
    return project, run, value, ref


def confirm(project, run, ref, at="2026-09-08T00:04:00Z"):
    view = claim_graph.graph(project, run_roots=(run,))
    out = attest_authenticated(
        project,
        run_roots=(run,),
        expected_head=view["snapshot_sha256"],
        claim_id="claim.relation",
        authority=ref,
        statement="I confirmed this exact inference.",
        scope=ref.scope,
        policy_version="policy.v1",
        request=request(run, 202, at=at),
    )
    return view, out


def test_real_parent_anchor_authenticates_and_preserves_historical_expiry(tmp_path):
    project, run, _value, ref = prepared(tmp_path)
    before, out = confirm(project, run, ref)
    assert out["status"] == "authenticated"
    journal = narrative._read(project)[0][-1]
    anchor = replay_run(run).events[-1]
    assert (
        anchor.event_type == "claim.attestation_anchored"
        and anchor.schema_version == "1.6.0"
    )
    assert anchor.payload.journal_event_sha256 == journal["event_sha256"]
    assert (
        journal["payload"]["snapshot_manifest"]["journal"]["sequence"]
        == journal["sequence"] - 1
    )
    assert journal["payload"]["graph_snapshot_sha256"] == before["snapshot_sha256"]
    graph = claim_graph.graph(project, run_roots=(run,))
    verified = current_claim(graph)["attestations"][0]
    assert (
        verified["status"] == "authenticated"
        and verified["historical_authorized"] is True
    )
    assert verified["current_applicability"] == "current"
    assert verified["evaluation_time_source"] == "latest_parent_event_in_snapshot"
    past = claim_graph.graph(
        project,
        run_roots=(run,),
        as_of=graph["snapshot_manifest"],
        evaluation_time="2026-09-08T00:11:00Z",
    )
    expired = current_claim(past)["attestations"][0]
    assert (
        expired["historical_authorized"] is True
        and expired["current_applicability"] == "expired"
    )
    assert expired["evaluation_time_source"] == "explicit_at_time"
    assert (
        claim_graph.graph(project, run_roots=(run,), as_of=graph["snapshot_manifest"])
        == graph
    )
    hard = claim_graph.graph(project, run_roots=(run,), hard_check=True)
    assert (
        hard["hard_checks"]["status"] == "failed"
    )  # Unobserved/unknown MVP occurrences cannot pass.
    assert (
        hard["hard_checks"]["scope"]
        == "registered_claims_and_observed_mvp_occurrences_only"
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("accountable_actor_id", "author.other", "actor mismatch"),
        ("accountable_role", "review_authority", "role mismatch"),
        ("gate_id", "gate.other", "gate mismatch"),
        ("scope", "Other scope.", "scope mismatch"),
        ("human_authority_sha256", "a" * 64, "digest"),
        ("authority_event_sha256", "a" * 64, "digest"),
    ],
)
def test_auth_identity_mismatches_refuse_before_journal_write(
    tmp_path, field, value, reason
):
    project, run, _, ref = prepared(tmp_path)
    changed = ref.model_dump(mode="json")
    changed[field] = value
    wrong = AuthenticatedAuthority.model_validate(changed)
    raw = (project / narrative.RELATIVE).read_bytes()
    with pytest.raises((ValueError, RuntimeError), match=reason):
        confirm(project, run, wrong)
    assert (project / narrative.RELATIVE).read_bytes() == raw


@pytest.mark.parametrize(
    ("at", "reason"),
    [
        ("2026-09-08T00:02:59Z", "precedes authentication"),
        ("2026-09-08T00:10:01Z", "expired at anchor"),
    ],
)
def test_auth_time_window_refuses_before_journal_write(tmp_path, at, reason):
    project, run, _, ref = prepared(tmp_path)
    raw = (project / narrative.RELATIVE).read_bytes()
    with pytest.raises(ReducerError, match=reason):
        confirm(project, run, ref, at=at)
    assert (project / narrative.RELATIVE).read_bytes() == raw


def test_declared_does_not_upgrade_and_authenticated_intent_requires_anchor(tmp_path):
    project, run, _, ref = prepared(tmp_path)
    _before, out = confirm(project, run, ref)
    path = run / "journal/segments/00000001.jsonl"
    events = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b"".join(events[:-1]))
    graph = claim_graph.graph(project, run_roots=(run,))
    item = current_claim(graph)["attestations"][0]
    assert item["status"] == "pending_anchor" and item["historical_authorized"] is False
    recovered = anchor_attestation(
        project,
        run_roots=(run,),
        sequence=out["journal_sequence"],
        request=request(run, 203),
    )
    assert recovered["status"] == "authenticated"
    now = claim_graph.graph(project, run_roots=(run,))
    claim = current_claim(now)
    changed = registration(
        now,
        statement="The method causes the outcome.",
        revision=2,
        supersedes=claim["claim_sha256"],
    )
    record(project, run, changed)
    obsolete = current_claim(claim_graph.graph(project, run_roots=(run,)))[
        "attestations"
    ][0]
    assert (
        obsolete["historical_authorized"] is True
        and obsolete["current_applicability"] == "stale_revision"
    )
    assert obsolete["status"] == "stale"


def test_authority_later_than_n_minus_one_prefix_is_rejected(tmp_path):
    project, run = setup(tmp_path)
    record(project, run, registration(claim_graph.graph(project, run_roots=(run,))))
    before = claim_graph.graph(project, run_roots=(run,))
    _, ref = authority(run)
    claim = current_claim(before)
    att = AuthenticatedAttestation(
        claim_id="claim.relation",
        claim_revision=claim["revision"],
        claim_sha256=claim["claim_sha256"],
        evidence_dependency_sha256=claim["evidence_dependency_sha256"],
        statement="Review inference",
        scope=ref.scope,
        policy_version="policy.v1",
        graph_snapshot_sha256=before["snapshot_sha256"],
        snapshot_manifest=before["snapshot_manifest"],
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
    with pytest.raises(ValueError, match="not accepted in N-1"):
        anchor_attestation(
            project,
            run_roots=(run,),
            sequence=event["sequence"],
            request=request(run, 202),
        )
    assert replay_run(run).events[-1].event_type == "human_authority.accepted"


def test_fractional_time_comparison_uses_utc_instants(tmp_path):
    from arw.kernel.ledger.claim_authority import _authority_state

    project, run, _, ref = prepared(tmp_path)
    _before, _out = confirm(project, run, ref)
    att = AuthenticatedAttestation.model_validate(
        narrative._read(project)[0][-1]["payload"]
    )
    historical = claim_graph._read_inputs(project, (run,), att.snapshot_manifest)
    state = _authority_state(historical, att)
    validate_claim_authority_envelope(state, att, "2026-09-08T00:03:00.0001Z")
    with pytest.raises(ReducerError, match="expired"):
        validate_claim_authority_envelope(state, att, "2026-09-08T00:10:00.0001Z")


def test_anchor_journal_hash_tampering_blocks_parent_replay(tmp_path):
    project, run, _, ref = prepared(tmp_path)
    confirm(project, run, ref)
    # A hash-consistent journal rewrite still breaks the accepted parent anchor.
    from arw.kernel.core.canonical import sha256_hex

    path = project / narrative.RELATIVE
    events = narrative._read(project)[0]
    events[-1]["payload"]["statement"] = "Altered confirmation statement."
    unsigned = {k: v for k, v in events[-1].items() if k != "event_sha256"}
    events[-1]["event_sha256"] = sha256_hex(canonical_json_bytes(unsigned))
    path.write_bytes(b"".join(canonical_json_bytes(e) for e in events))
    assert (
        narrative._read(project)[0][-1]["payload"]["statement"]
        == "Altered confirmation statement."
    )
    assert replay_run(run).recovery_health == "blocked"
    with pytest.raises(claim_graph.ClaimGraphError):
        claim_graph.graph(project, run_roots=(run,))


def test_many_independent_anchors_replay_with_query_local_bounded_work(
    tmp_path, monkeypatch
):
    from arw.kernel.ledger import claim_authority

    project, run, _, ref = prepared(tmp_path)
    for index in range(10):
        before = claim_graph.graph(project, run_roots=(run,))
        out = attest_authenticated(
            project,
            run_roots=(run,),
            expected_head=before["snapshot_sha256"],
            claim_id="claim.relation",
            authority=ref,
            statement=f"Review inference {index}",
            scope=ref.scope,
            policy_version="policy.v1",
            request=request(run, 220 + index),
        )
        assert out["status"] == "authenticated"
    calls = []
    original = claim_authority._read_inputs

    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(claim_authority, "_read_inputs", count)
    assert replay_run(run).recovery_health == "healthy"
    assert len(calls) == 10
    calls.clear()
    assert replay_run(run).recovery_health == "healthy"
    assert len(calls) == 10  # Cache is discarded between actual queries.
    # A later query cannot reuse prior proof after the journal changes.
    path = project / narrative.RELATIVE
    path.write_bytes(
        path.read_bytes().replace(b"Review inference 0", b"Altered inference0")
    )
    assert replay_run(run).recovery_health == "blocked"
