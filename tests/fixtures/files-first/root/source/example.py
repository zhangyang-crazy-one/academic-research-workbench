def bind_claim_to_source(claim_id: str, source_sha256: str) -> tuple[str, str]:
    """Return a deterministic synthetic evidence edge."""
    return claim_id, source_sha256


class EvidenceIndex:
    pass

