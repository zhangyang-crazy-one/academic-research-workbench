"""Core historical memory event invariants, independent of optional adapters."""


def validate_memory_event(kind, payload):
    from arw.kernel.state.models import ResearchMemoryPayload

    if not isinstance(payload, ResearchMemoryPayload):
        raise ValueError("memory event payload variant mismatch")  # noqa: TRY004 -- Pydantic envelope validator
    if kind in {"research_memory_created", "research_handoff_created"}:
        if (
            payload.status != "created"
            or payload.trust != "unreviewed"
            or payload.previous_memory_event_sha256 is not None
        ):
            raise ValueError("new memories must be created and unreviewed")
        if (kind == "research_handoff_created") != (payload.kind == "handoff"):
            raise ValueError("handoff event kind mismatch")
    else:
        if (
            payload.previous_memory_event_sha256 is None
            or payload.prior_status is None
            or payload.prior_trust is None
        ):
            raise ValueError("memory lifecycle must reference its prior state")
        expected = {
            "research_memory_superseded": "superseded",
            "research_memory_rejected": "rejected",
            "research_memory_distilled": "distilled",
            "research_memory_activated": "active",
            "research_memory_verified": payload.prior_status,
        }[kind]
        if payload.status != expected:
            raise ValueError("memory lifecycle status mismatch")
        if kind == "research_memory_verified":
            if payload.trust != "verified" or not all(
                (
                    payload.authorization_artifact_id,
                    payload.authorization_event_id,
                    payload.authorization_sha256,
                )
            ):
                raise ValueError(
                    "verified memory requires authoritative verification references"
                )
        elif payload.trust != payload.prior_trust:
            raise ValueError("status changes cannot change scientific trust")
        if kind == "research_memory_superseded" and (
            payload.successor_memory_id is None
            or payload.successor_memory_id == payload.memory_id
        ):
            raise ValueError("supersession requires a different successor")
