"""Provider-neutral, read-only route for the locally available core."""

from __future__ import annotations

from arw.composition import core_provider_records
from arw.kernel.policy.core_integrity import (
    CoreIntegrityError,
    installed_core_preflight,
)


def core_route_report() -> dict[str, object]:
    try:
        integrity, digests = installed_core_preflight()
        reason_codes: list[str] = [] if integrity == "PASS" else ["editable_checkout_unverified"]
    except CoreIntegrityError:
        integrity, digests = "BLOCKED", None
        reason_codes = ["core_integrity_invalid_or_drifted"]
    capabilities = core_provider_records(probe=integrity != "BLOCKED")
    return {
        "schema_version": "arw.core-route.v1",
        "core_integrity": integrity,
        "source_mode": "staged" if integrity in {"PASS", "BLOCKED"} else "editable_checkout",
        "reason_codes": reason_codes,
        "verified_digests": digests,
        "capabilities": capabilities,
        "execution_adapters": [
            {"adapter": "codex_exec", "provider_status": "requires_host_qualification"},
            {"adapter": "claude_exec", "provider_status": "not_provided"},
            {"adapter": "generic_exec", "provider_status": "not_provided"},
        ],
    }
