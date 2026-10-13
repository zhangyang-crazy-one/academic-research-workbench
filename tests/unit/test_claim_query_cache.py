"""Original-reader work and byte equivalence for real admitted anchors."""

from time import perf_counter

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger import accepted_refs, claim_authority, claim_graph, narrative
from arw.kernel.state.claim_authentication import AuthenticatedAttestation
from tests.unit.test_claim_authentication import prepared, request
from tests.unit.test_claim_graph import current_claim


def admit(project, run, ref, claim, index):
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
    assert (
        claim_authority.anchor_attestation(
            project,
            run_roots=(run,),
            sequence=event["sequence"],
            request=request(run, 300 + index),
        )["status"]
        == "authenticated"
    )


def test_30_60_original_replay_work_and_uncached_bytes(tmp_path, monkeypatch):
    project, run, _, ref = prepared(tmp_path)
    claim = current_claim(claim_graph.graph(project, run_roots=(run,)))
    original_read = claim_graph.replay_run_prefix
    original_resolve_read = accepted_refs.replay_run_prefix
    original_anchor = claim_authority.verify_anchor_journal
    original_hist = claim_graph._historical_inputs
    measurements = []
    for count in (30, 60):
        for index in range(0 if count == 30 else 30, count):
            admit(project, run, ref, claim, index)
        calls = []

        def counted(*args, **kwargs):
            calls.append(kwargs["revision"])
            return original_read(*args, **kwargs)

        def counted_resolve(*args, **kwargs):
            calls.append(kwargs["revision"])
            return original_resolve_read(*args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(claim_graph, "replay_run_prefix", counted)
            m.setattr(accepted_refs, "replay_run_prefix", counted_resolve)
            started = perf_counter()
            cached = claim_graph.graph(project, run_roots=(run,))
            elapsed = perf_counter() - started
        assert len(calls) <= 3, calls
        measurements.append((count, len(calls), sum(calls), elapsed))

        def historical_uncached(inputs, fixed):
            return claim_graph._read_inputs(
                inputs.root,
                tuple(inputs.runs[r.run_id][0] for r in fixed.runs),
                fixed,
                figure_verifier=inputs.figure_verifier,
                held_lock_roots=inputs.held_lock_roots,
            )

        def anchor_uncached(*args, **kwargs):
            kwargs.pop("query_inputs", None)
            return original_anchor(*args, **kwargs)

        with monkeypatch.context() as m:
            m.setattr(claim_graph, "_historical_inputs", historical_uncached)
            m.setattr(claim_authority, "verify_anchor_journal", anchor_uncached)
            uncached = claim_graph.graph(project, run_roots=(run,))
        assert canonical_json_bytes(cached) == canonical_json_bytes(uncached)
        # A fixed vector and a fresh query must both revalidate disk bytes.
        with monkeypatch.context() as m:
            m.setattr(claim_graph, "replay_run_prefix", counted)
            fixed = claim_graph.graph(
                project, run_roots=(run,), as_of=cached["snapshot_manifest"]
            )
        assert canonical_json_bytes(fixed) == canonical_json_bytes(cached)
        assert len(calls) > measurements[-1][1]
    assert measurements[1][2] < measurements[0][2] * 2.5
    assert original_hist is claim_graph._historical_inputs
    print(
        "query measurements (anchors, prefix calls, revisions replayed, seconds):",
        measurements,
    )


def test_new_query_revalidates_changed_disk_and_nonmonotone_prefix(tmp_path):
    import pytest
    from arw.kernel.state.claim_graph import JournalPrefix
    from tests.unit.test_claim_authentication import confirm

    project, run, _, ref = prepared(tmp_path)
    earlier = claim_graph._read_inputs(project, (run,)).manifest
    confirm(project, run, ref)
    base = claim_graph._read_inputs(project, (run,))
    later = claim_graph._historical_inputs(base, base.manifest)
    claim_graph._closure(later)
    older = claim_graph._historical_inputs(base, earlier)
    claim_graph._closure(older)  # Non-extending vector must use the full checker.
    assert base.cache["query_closure"][0] is older
    invalid = earlier.model_copy(
        update={
            "journal": JournalPrefix(
                sequence=1, head_sha256="f" * 64
            )
        }
    )
    with pytest.raises(claim_graph.ClaimGraphError, match="journal prefix"):
        claim_graph._historical_inputs(base, invalid)
    assert claim_graph.graph(project, run_roots=(run,))
    path = project / narrative.RELATIVE
    path.write_bytes(path.read_bytes().replace(b"confirmed", b"tampered!"))
    with pytest.raises(claim_graph.ClaimGraphError):
        claim_graph.graph(project, run_roots=(run,))
