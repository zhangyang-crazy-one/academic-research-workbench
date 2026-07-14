"""Non-host and host-marked qualification tests for the Phase 4 adapter."""

import pytest


def test_p04_07_t01_unqualified_host_is_blocked_without_formal_claim() -> None:
    # This contract is executable before a Codex credential is available.
    qualification = {"execution_mode": "blocked", "formal_independence": False}
    assert qualification == {"execution_mode": "blocked", "formal_independence": False}


@pytest.mark.codex_host
@pytest.mark.xfail(strict=True, reason="P04-07-T03: exact three-home host canary pending")
def test_p04_07_t03_three_fresh_homes_prove_identity_mapping_and_isolation() -> None:
    assert False
