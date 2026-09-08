"""Replayable lifecycle invariants independent of extension activation."""

from arw.kernel.state.models import RESEARCH_LEARNING_EVENT_TYPES


def validate_learning_progress(events, event):
    if event.event_type not in RESEARCH_LEARNING_EVENT_TYPES:
        return
    p = event.payload
    prior = [
        e
        for e in events
        if e.event_type in RESEARCH_LEARNING_EVENT_TYPES
        and e.payload.record_id == p.record_id
    ]
    expected = dict(
        zip(
            RESEARCH_LEARNING_EVENT_TYPES,
            (
                "recorded",
                "candidate",
                "evaluated",
                "qualified",
                "rejected",
                "promoted",
                "superseded",
            ),
            strict=True,
        )
    )[event.event_type]
    if p.status != expected:
        raise ValueError("learning event status mismatch")
    if p.status in {"recorded", "candidate"}:
        if prior or p.previous_event_sha256 is not None:
            raise ValueError("learning identity already exists")
    else:
        if not prior or p.previous_event_sha256 != prior[-1].event_sha256:
            raise ValueError("learning lifecycle requires the current prior event")
        old = prior[-1].payload
        if old.project_id != p.project_id:
            raise ValueError("learning project identity cannot change")
        allowed = {
            "evaluated": {"candidate", "evaluated", "qualified"},
            "qualified": {"evaluated"},
            "promoted": {"qualified"},
            "rejected": {"candidate", "evaluated", "qualified"},
            "superseded": {
                "candidate",
                "evaluated",
                "qualified",
                "rejected",
                "promoted",
            },
        }
        if old.status not in allowed[p.status]:
            raise ValueError(
                "terminal learning status requires a new successor version"
            )
        if (
            p.status in {"evaluated", "qualified", "promoted"}
            and not p.evaluation_receipt_id
        ):
            raise ValueError("evaluation receipt is required")
        if p.status in {"qualified", "promoted"} and not p.qualification_receipt_id:
            raise ValueError("qualification receipt is required")
        if p.status == "evaluated" and p.evaluation_receipt_id != p.content_digest:
            raise ValueError("evaluation receipt must bind the event body")
        if p.status == "qualified" and (
            p.qualification_receipt_id != p.content_digest
            or p.evaluation_receipt_id != old.evaluation_receipt_id
        ):
            raise ValueError("qualification must bind the prior evaluation")
        if p.status == "promoted" and (
            p.qualification_receipt_id != old.qualification_receipt_id
            or p.evaluation_receipt_id != old.evaluation_receipt_id
        ):
            raise ValueError("promotion cannot replace qualified evidence")
        if p.status == "promoted":
            if not p.consent or not p.approval_artifact_id or p.from_scope != old.scope:
                raise ValueError("promotion requires consent and approval")
            if p.scope in {"domain", "global"} and len(set(p.supporting_projects)) < 2:
                raise ValueError("broader promotion requires cross-project evidence")
        elif p.scope != old.scope:
            raise ValueError("scope changes require promotion")
        if p.status == "superseded" and (
            not p.successor_id or p.successor_id == p.record_id
        ):
            raise ValueError("supersession requires another identity")
    accepted_ids = {e.event_id for e in events}
    if not set(p.source_event_ids) <= accepted_ids:
        raise ValueError("learning references unaccepted source events")

    if len(p.source_digests) != len(p.source_event_ids):
        raise ValueError("learning provenance arrays must match")
    source_map = {e.event_id: e for e in events}
    for source_id, digest in zip(p.source_event_ids, p.source_digests, strict=True):
        source = source_map[source_id]
        if digest != getattr(source.payload, "artifact_sha256", source.event_sha256):
            raise ValueError("learning source digest mismatch")
    if p.status == "promoted" and not any(
        e.event_id in p.source_event_ids
        and e.event_type in {"artifact.accepted", "research_artifact_accepted"}
        and e.payload.artifact_id == p.approval_artifact_id
        for e in events
    ):
        raise ValueError("promotion approval must reference an accepted artifact")

    if p.status == "superseded" and not any(
        e.event_type == "research_heuristic_proposed"
        and e.payload.record_id == p.successor_id
        and e.payload.project_id == p.project_id
        and e.event_id in p.source_event_ids
        for e in events
    ):
        raise ValueError("supersession must bind a prior accepted successor")
