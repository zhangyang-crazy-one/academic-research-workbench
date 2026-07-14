"""Owner-mapped red tests for hook-enabled/disabled parity."""

import pytest


@pytest.mark.xfail(strict=True, reason="P04-06-T02: hook parity implementation pending")
def test_p04_06_t02_disabled_hooks_preserve_parent_authority() -> None:
    assert False


@pytest.mark.xfail(strict=True, reason="P04-06-T02: continuation admission pending")
def test_p04_06_t02_hook_cannot_accept_or_retry_a_proposal() -> None:
    assert False
