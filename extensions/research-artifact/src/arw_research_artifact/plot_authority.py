"""Canonical caption authority adapter; renderer contracts depend on the kernel."""

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.claim_authority import verify_caption_confirmation

from .plot_policy import VerifiedCaptionAttestation, caption_target


class CanonicalCaptionAttestationVerifier:
    """Never trusts confirmation labels, author strings or an arbitrary digest."""

    def verify(self, compiled, binding, *, resolution_context):
        ir_sha = sha256_hex(canonical_json_bytes(compiled.ir.model_dump(mode="json")))
        target_sha = sha256_hex(canonical_json_bytes(caption_target(compiled, binding)))
        evidence = None
        if resolution_context is not None and binding.confirmation_ref is not None:
            evidence = verify_caption_confirmation(
                resolution_context, binding.confirmation_ref, target_sha
            )
        return VerifiedCaptionAttestation(
            binding_id=binding.binding_id,
            revision=compiled.ir.revision,
            ir_sha256=ir_sha,
            status="verified" if evidence else "auth_missing",
            evidence_sha256=evidence,
            target_sha256=target_sha,
        )
