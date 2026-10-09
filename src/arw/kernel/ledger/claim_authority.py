"""Parent-ledger anchoring and the full authenticated claim authority verifier."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from arw.kernel.ledger import narrative
from arw.kernel.ledger.claim_graph import (
    ClaimGraphError,
    Inputs,
    _closure,
    _evaluate_registration,
    _read_inputs,
    _registrations,
    graph,
    validate_claim_journal_event,
)
from arw.kernel.ledger.reducer import reduce_events, validate_claim_authority_envelope
from arw.kernel.state.claim_authentication import (
    AuthenticatedAttestation,
    AuthenticatedAuthority,
)
from arw.kernel.state.claim_graph import SnapshotManifest
from arw.kernel.state.models import (
    ClaimAttestationAnchoredPayload,
    RuntimeCommandRequest,
)


def _authority_state(inputs: Inputs, attestation: AuthenticatedAttestation):
    requested = attestation.authority
    item = inputs.runs.get(requested.authority_run_id)
    if item is None:
        raise ClaimGraphError(
            "dependency_outside_prefix", "authority run is absent from N-1 snapshot"
        )
    replay = item[2]
    source = next(
        (e for e in replay.events if e.event_id == requested.authority_event_id), None
    )
    if source is None:
        raise ClaimGraphError(
            "authority_outside_prefix", "authority event was not accepted in N-1"
        )
    if (
        source.event_type != "human_authority.accepted"
        or source.event_sha256 != requested.authority_event_sha256
        or source.payload.authority_sha256 != requested.human_authority_sha256
    ):
        raise ClaimGraphError(
            "authority_digest_mismatch",
            "authority acceptance identity or digest differs",
        )
    reduced = reduce_events(replay.workflow_definition_id, replay.events)
    state = next(
        (a for a in reduced.human_authorities if a.source_event_id == source.event_id),
        None,
    )
    if state is None:
        raise ClaimGraphError(
            "authority_missing", "canonical reducer has no matching authority"
        )
    return state


def verify_anchor_journal(
    run_root: Path, event, *, held_lock_roots: tuple[Path, ...] = ()
):
    """Pre-admission cross-log validation under the parent writer lock.

    Canonical replay checks the immutable local anchor and authority envelope
    in the reducer. External evidence is verified here before admission and
    independently by projections; its availability cannot block local replay.
    """
    payload = event.payload
    att = payload.attestation
    project = narrative._root((run_root / payload.project_root_relative).resolve())
    if (
        not run_root.is_relative_to(project)
        or narrative._identity(project).project_id != payload.project_id
    ):
        raise ClaimGraphError(
            "project_mismatch", "anchor project identity or root differs"
        )
    journal, _, _ = narrative._read(project, at_sequence=payload.journal_sequence)
    confirmation = journal[-1]
    if (
        confirmation["kind"] != "claim.attested"
        or confirmation["event_sha256"] != payload.journal_event_sha256
        or confirmation["payload"] != att.model_dump(mode="json")
    ):
        raise ClaimGraphError(
            "digest_mismatch", "anchor does not bind the real journal confirmation"
        )
    roots = tuple(
        project / payload.run_locations[r.run_id] for r in att.snapshot_manifest.runs
    )
    inputs = _read_inputs(
        project, roots, att.snapshot_manifest, held_lock_roots=held_lock_roots
    )
    _closure(inputs)
    old = _registrations(inputs.journal).get(att.claim_id)
    if old is None or old.claim.sha256 != att.claim_sha256:
        raise ClaimGraphError("stale_claim", "anchor target differs from N-1 claim")
    if _evaluate_registration(old, inputs)[1] != att.evidence_dependency_sha256:
        raise ClaimGraphError(
            "stale_evidence", "anchor evidence differs from N-1 dependencies"
        )
    state = _authority_state(inputs, att)
    validate_claim_authority_envelope(state, att, event.occurred_at)
    return state


def anchor_attestation(
    project_root: Path,
    *,
    run_roots: tuple[Path, ...],
    sequence: int,
    request: RuntimeCommandRequest,
) -> dict:
    """Accept an exact pending journal confirmation through the parent writer."""
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = narrative._root(project_root)
    events, _, _ = narrative._read(root, at_sequence=sequence)
    event = events[-1]
    if event["kind"] != "claim.attested":
        raise ClaimGraphError(
            "invalid_confirmation", "journal event is not a claim confirmation"
        )
    att = AuthenticatedAttestation.model_validate(event["payload"])
    inputs = _read_inputs(root, run_roots, att.snapshot_manifest)
    _closure(inputs)
    if request.run_id != att.authority.authority_run_id:
        raise ClaimGraphError(
            "authority_run_mismatch", "anchor must be written in the authority run"
        )
    authority = _authority_state(inputs, att)
    validate_claim_authority_envelope(authority, att, request.occurred_at)
    run = inputs.runs[request.run_id][0]
    payload = ClaimAttestationAnchoredPayload(
        project_id=inputs.manifest.project_id,
        project_root_relative=os.path.relpath(root, run).replace(os.sep, "/"),
        journal_sequence=sequence,
        journal_event_sha256=event["event_sha256"],
        run_locations={
            run_id: item[0].relative_to(root).as_posix()
            for run_id, item in inputs.runs.items()
        },
        attestation=att,
    )
    outcome = RuntimeCommandService(run).append_phase4_event(
        request,
        event_type="claim.attestation_anchored",
        payload=payload,
        prevalidate=lambda _state, replay: _prevalidate_anchor(
            run, replay, payload, request
        ),
    )
    return {
        "status": "authenticated" if outcome.accepted else "pending_anchor",
        "claim_id": att.claim_id,
        "claim_revision": att.claim_revision,
        "journal_sequence": sequence,
        "journal_event_sha256": event["event_sha256"],
        "anchor_event_id": outcome.event.event_id if outcome.accepted else None,
        "anchor_event_sha256": outcome.event.event_sha256 if outcome.accepted else None,
        "rejection": outcome.rejection.model_dump(mode="json")
        if outcome.rejection
        else None,
    }


def attest_authenticated(
    project_root: Path,
    *,
    run_roots: tuple[Path, ...],
    expected_head: str,
    claim_id: str,
    authority: AuthenticatedAuthority,
    statement: str,
    scope: str,
    policy_version: str,
    request: RuntimeCommandRequest,
) -> dict:
    """Append authenticated intent, then anchor it; the declaration alone proves nothing."""
    view = graph(project_root, run_roots=run_roots, expected_head=expected_head)
    claim = next(
        (
            n
            for n in view["nodes"]
            if n["node_kind"] == "Claim" and n["claim_id"] == claim_id
        ),
        None,
    )
    if claim is None:
        raise ClaimGraphError("unknown_claim", "claim is not registered in snapshot")
    snapshot = SnapshotManifest.model_validate(view["snapshot_manifest"])
    att = AuthenticatedAttestation(
        claim_id=claim_id,
        claim_revision=claim["revision"],
        claim_sha256=claim["claim_sha256"],
        evidence_dependency_sha256=claim["evidence_dependency_sha256"],
        statement=statement,
        scope=scope,
        policy_version=policy_version,
        graph_snapshot_sha256=snapshot.sha256,
        snapshot_manifest=snapshot,
        authority=authority,
    )
    inputs = _read_inputs(project_root, run_roots, snapshot)
    if request.run_id != authority.authority_run_id:
        raise ClaimGraphError(
            "authority_run_mismatch", "request targets a different authority run"
        )
    validate_claim_authority_envelope(
        _authority_state(inputs, att), att, request.occurred_at
    )
    with narrative._locked(project_root, write=True) as root:
        events, current, _ = narrative._read(root)
        if _read_inputs(root, run_roots).manifest != snapshot:
            raise ClaimGraphError(
                "stale", "authenticated confirmation predecessor advanced"
            )
        candidate = {
            "kind": "claim.attested",
            "payload": att.model_dump(mode="json"),
            "project_id": snapshot.project_id,
            "sequence": len(events) + 1,
            "previous_sha256": events[-1]["event_sha256"],
        }
        validate_claim_journal_event(candidate, events)
        event = narrative._append(
            root, events, "claim.attested", current.version, att.model_dump(mode="json")
        )
    return anchor_attestation(
        project_root, run_roots=run_roots, sequence=event["sequence"], request=request
    )


def applicability_time(inputs: Inputs, evaluation_time: str | None):
    if evaluation_time is not None:
        value = datetime.fromisoformat(evaluation_time)
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ClaimGraphError(
                "invalid_evaluation_time", "evaluation instant must be UTC"
            )
        return value, "explicit_at_time"
    events = [e for item in inputs.runs.values() for e in item[2].events]
    if not events:
        return None, "no_parent_events_in_snapshot"
    value = max(datetime.fromisoformat(e.occurred_at) for e in events)
    return value, "latest_parent_event_in_snapshot"


def verify_authenticated_record(
    inputs: Inputs,
    historical: Inputs,
    journal_event: dict,
    att: AuthenticatedAttestation,
    *,
    claim_current: bool,
    evidence_current: bool,
    dependencies_valid: bool,
    evaluation_time: str | None = None,
) -> dict:
    """Historical authorization and current applicability are independent."""
    replay = inputs.runs[att.authority.authority_run_id][2]
    anchor = next(
        (
            e
            for e in replay.events
            if e.event_type == "claim.attestation_anchored"
            and e.payload.journal_event_sha256 == journal_event["event_sha256"]
            and e.payload.journal_sequence == journal_event["sequence"]
        ),
        None,
    )
    if anchor is None:
        altered = any(
            e.event_type == "claim.attestation_anchored"
            and e.payload.project_id == inputs.manifest.project_id
            and e.payload.journal_sequence == journal_event["sequence"]
            for e in replay.events
        )
        if altered:
            return {
                "status": "unverifiable",
                "historical_authorized": False,
                "current_applicability": "unverifiable",
                "reason": "anchor_binding_mismatch",
            }
        return {
            "status": "pending_anchor",
            "historical_authorized": False,
            "current_applicability": "unanchored",
            "reason": "parent_anchor_missing",
        }
    state = verify_anchor_journal(
        inputs.runs[att.authority.authority_run_id][0],
        anchor,
        held_lock_roots=inputs.held_lock_roots,
    )
    validate_claim_authority_envelope(state, att, anchor.occurred_at)
    if (
        anchor.payload.attestation.model_dump(mode="json")
        != att.model_dump(mode="json")
        or not dependencies_valid
    ):
        return {
            "status": "stale",
            "historical_authorized": False,
            "current_applicability": "invalid_dependencies",
            "reason": "anchor_binding_mismatch",
        }
    instant, source = applicability_time(inputs, evaluation_time)
    expiry = datetime.fromisoformat(state.authority.expires_at)
    applicability = (
        "not_yet_anchored"
        if instant is not None and instant < datetime.fromisoformat(anchor.occurred_at)
        else "stale_revision"
        if not claim_current
        else "stale_evidence"
        if not evidence_current
        else "expired"
        if instant is not None and instant > expiry
        else "current"
    )
    return {
        "status": "stale" if applicability.startswith("stale") else "authenticated",
        "historical_authorized": True,
        "current_applicability": applicability,
        "anchor_event_id": anchor.event_id,
        "anchor_event_sha256": anchor.event_sha256,
        "attested_at": anchor.occurred_at,
        "evaluation_time_source": source,
        "evaluation_time": instant.isoformat().replace("+00:00", "Z")
        if instant
        else None,
    }


def _prevalidate_anchor(root, replay, payload, request):
    from arw.kernel.ledger.journal import build_runtime_event

    candidate = build_runtime_event(
        replay,
        event_type="claim.attestation_anchored",
        event_id=request.event_id,
        command_id=request.command_id,
        occurred_at=request.occurred_at,
        actor_id=request.actor_id,
        actor_role=request.actor_role,
        payload=payload,
    )
    try:
        verify_anchor_journal(root, candidate, held_lock_roots=(root,))
    except (ValueError, RuntimeError, OSError) as error:
        return "claim-anchor-invalid", str(error)
    return None


def verify_caption_confirmation(
    context, ref, target_sha256: str, *, evaluation_time: str | None = None
) -> str | None:
    """Verify an exact caption target through original journal/parent contracts.

    This is renderer-independent. The extension builds the closed semantic
    target; confirmation handles never become part of that target's identity.
    """
    from arw.kernel.ledger.claim_graph import _attestations
    from arw.kernel.state.accepted_ref import JournalEventRef

    if (
        evaluation_time is None
        or not isinstance(ref, JournalEventRef)
        or ref.payload_selector
        or context.project_root is None
        or ref.project_id != context.project_id
    ):
        return None
    fixed = None
    if (
        context.run_prefixes
        and context.journal_sequence is not None
        and context.journal_head_sha256 is not None
    ):
        from arw.kernel.state.claim_graph import JournalPrefix, RunPrefix

        if any(p.run_manifest_sha256 is None for p in context.run_prefixes):
            return None
        fixed = SnapshotManifest(
            project_id=context.project_id,
            journal=JournalPrefix(
                sequence=context.journal_sequence,
                head_sha256=context.journal_head_sha256,
            ),
            runs=tuple(
                sorted(
                    (
                        RunPrefix(
                            run_id=p.run_id,
                            run_manifest_sha256=p.run_manifest_sha256,
                            revision=p.revision,
                            head_sha256=p.head_sha256,
                        )
                        for p in context.run_prefixes
                    ),
                    key=lambda p: p.run_id,
                )
            ),
        )
    inputs = _read_inputs(
        context.project_root,
        context.run_roots,
        fixed,
        held_lock_roots=context.held_lock_roots,
    )
    _closure(inputs)
    event = next((e for e in inputs.journal if e["sequence"] == ref.sequence), None)
    if (
        event is None
        or event["event_sha256"] != ref.event_sha256
        or event["kind"] != "claim.attested"
    ):
        return None
    if event["payload"].get("schema_version") != "arw.claim-attestation.v2":
        return None
    att = AuthenticatedAttestation.model_validate(event["payload"])
    if att.scope != "caption:" + target_sha256:
        return None
    record = _registrations(inputs.journal).get(att.claim_id)
    if record is None:
        return None
    dependency = _evaluate_registration(record, inputs)[1]
    proof = next(
        (
            a
            for a in _attestations(record, dependency, inputs, evaluation_time)
            if a["source"]["event_sha256"] == ref.event_sha256
        ),
        None,
    )
    if (
        proof is None
        or not proof["historical_authorized"]
        or proof["current_applicability"] != "current"
    ):
        return None
    if (
        fixed is None
        and _read_inputs(
            context.project_root,
            context.run_roots,
            held_lock_roots=context.held_lock_roots,
        ).manifest
        != inputs.manifest
    ):
        raise ClaimGraphError(
            "stale", "caption confirmation snapshot advanced during verification"
        )
    return proof["anchor_event_sha256"]
